"""g13d: reads G13 input reports and translates them into
keystrokes/profile switches/macro record-playback, loops the active
profile's LCD animation, and serves a Unix-socket control API for the
GUI -- both request/response commands (list/switch profiles) and a
"subscribe" push channel that streams live profile/color/held-key state
for the GUI's visualization. All USB device access goes through a single
lock so the concurrent asyncio tasks never issue overlapping transfers.

Macro recording: press MR to arm recording, press the G-key that should
trigger the macro (this key's own press isn't recorded), then perform the
sequence of keys to record -- they're forwarded live as normal keystrokes
and recorded with their relative timing. Press MR again to finish and
save it into the active profile's TOML file. Pressing that G-key
afterwards (while idle) plays the recorded sequence back instead of its
normal single binding.

Run as a script; Ctrl-C to stop.
"""

from __future__ import annotations

import asyncio
import os
import stat
import time
from dataclasses import replace

import evdev
from PIL import Image

from g13.daemon.protocol import SOCKET_PATH, decode, encode
from g13.hardware.device import G13Device
from g13.hardware.lcd import (
    MODE_LED_MR,
    load_frames,
    push_image,
    set_backlight,
    set_mode_leds,
    text_frame,
)
from g13.hardware.report import decode_report
from g13.profile import (
    G_KEY_IDS,
    JOYSTICK_CONTROL_IDS,
    MacroEvent,
    Profile,
    create_profile,
    ensure_default_profiles,
    load_profile,
    load_profiles,
    profile_from_payload,
    profile_sort_key,
    profile_to_dict,
    save_macro,
    save_profile,
)
from g13.system_stats import SystemStats, clock_frame, stats_frame

PROFILE_SWITCH_KEYS = {"M1": 0, "M2": 1, "M3": 2}
DEFAULT_FRAME_DURATION_MS = 200
PROFILE_SPLASH_DURATION_MS = 2000
STICK_PRESS_LOW = 64
STICK_PRESS_HIGH = 192
STICK_RELEASE_LOW = 96
STICK_RELEASE_HIGH = 160
MOUSE_POLL_SECONDS = 1 / 60
MOUSE_MAX_STEP = 12
LCD_BUTTON_MODES = {"L1": "splash", "L2": "animation", "L3": "clock", "L4": "stats"}
LCD_MODES = ("splash", "animation", "clock", "stats")


def build_uinput(profiles: list[Profile]) -> evdev.UInput:
    del profiles  # capabilities must also cover bindings added while the daemon is running
    excluded = {"KEY_MIN_INTERESTING", "KEY_MAX", "KEY_CNT"}
    all_codes = {
        code
        for name, code in evdev.ecodes.ecodes.items()
        if name.startswith(("KEY_", "BTN_"))
        and name not in excluded
        and isinstance(code, int)
        and 0 < code < evdev.ecodes.KEY_MAX
    }
    capabilities = {
        evdev.ecodes.EV_KEY: sorted(all_codes),
        evdev.ecodes.EV_REL: [evdev.ecodes.REL_X, evdev.ecodes.REL_Y],
    }
    return evdev.UInput(capabilities, name="g13-linux-virtual-keyboard")


def stick_direction_keys(
    stick_x: int, stick_y: int, previous: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Convert analog stick position to directions with release hysteresis."""
    directions = set()
    if stick_x <= (STICK_RELEASE_LOW if "STICK_LEFT" in previous else STICK_PRESS_LOW):
        directions.add("STICK_LEFT")
    if stick_x >= (STICK_RELEASE_HIGH if "STICK_RIGHT" in previous else STICK_PRESS_HIGH):
        directions.add("STICK_RIGHT")
    if stick_y <= (STICK_RELEASE_LOW if "STICK_UP" in previous else STICK_PRESS_LOW):
        directions.add("STICK_UP")
    if stick_y >= (STICK_RELEASE_HIGH if "STICK_DOWN" in previous else STICK_PRESS_HIGH):
        directions.add("STICK_DOWN")
    return frozenset(directions)


def mouse_axis_delta(raw: int) -> int:
    normalized = max(-1.0, min(1.0, (raw - 128) / 127))
    if abs(normalized) < 0.15:
        return 0
    magnitude = (abs(normalized) - 0.15) / 0.85
    step = max(1, round((magnitude**1.5) * MOUSE_MAX_STEP))
    return step if normalized > 0 else -step


def _profile_frames(profile: Profile) -> list[tuple[Image.Image, int]]:
    if profile.lcd_gif is not None:
        return load_frames(profile.lcd_gif)
    if profile.lcd_image is not None:
        return load_frames(profile.lcd_image)
    return [(text_frame(profile.name), 0)]


def _profile_splash(profile: Profile) -> Image.Image:
    if profile.lcd_image is not None:
        with Image.open(profile.lcd_image) as image:
            return image.convert("1")
    return text_frame(profile.name)


class G13Daemon:
    def __init__(self, g13: G13Device, ui: evdev.UInput, profiles: list[Profile]) -> None:
        self.g13 = g13
        self.ui = ui
        self.profiles = profiles
        self.active_index = 0
        self.held: frozenset[str] = frozenset()
        self.stick: tuple[int, int] = (128, 128)
        self.device_lock = asyncio.Lock()
        self.frames: list[tuple[Image.Image, int]] = []
        self.frame_index = 0
        self.lcd_mode = "splash"
        self.splash_until: float | None = None
        self._display_changed = asyncio.Event()
        self._stats = SystemStats()

        # MR macro recording state: "idle" -> "armed" (waiting for the
        # target G-key) -> "recording" -> back to "idle" on the next MR.
        self.mr_state = "idle"
        self.macro_target: str | None = None
        self.macro_events: list[MacroEvent] = []
        self.macro_last_time: float | None = None
        self._pending_target_release: str | None = None
        self._macro_tasks: set[asyncio.Task] = set()
        self._macro_lock = asyncio.Lock()
        self._subscribers: set[asyncio.StreamWriter] = set()

    @property
    def active_profile(self) -> Profile:
        return self.profiles[self.active_index]

    def _current_state(self) -> dict:
        profile = self.active_profile
        return {
            "kind": "state",
            "profile_id": profile.id,
            "slot": profile.slot,
            "profile": profile.name,
            "color": list(profile.color),
            "backlight_intensity": profile.backlight_intensity,
            "keys": sorted(self.held),
            "stick": list(self.stick),
            "mr_state": self.mr_state,
            "macro_target": self.macro_target,
            "lcd_mode": self.lcd_mode,
        }

    def _mode_led_mask(self) -> int:
        slot = self.active_profile.slot
        mask = 1 << (slot - 1) if slot is not None else 0
        if self.mr_state != "idle":
            mask |= MODE_LED_MR
        return mask

    async def _refresh_mode_leds(self) -> None:
        async with self.device_lock:
            await asyncio.to_thread(set_mode_leds, self.g13, self._mode_led_mask())

    async def broadcast_loop(self) -> None:
        """Pushes state at a fixed cadence, decoupled from input polling
        rate, so the stick position animates smoothly for subscribers."""
        while True:
            await self._broadcast_state()
            await asyncio.sleep(0.05)

    async def _broadcast_state(self) -> None:
        if not self._subscribers:
            return
        message = encode(self._current_state())
        dead = set()
        for writer in self._subscribers:
            try:
                writer.write(message)
                await writer.drain()
            except (ConnectionError, OSError):
                dead.add(writer)
        self._subscribers -= dead

    async def activate_profile(self, index: int) -> None:
        self.active_index = index
        profile = self.active_profile
        self.frames = _profile_frames(profile)
        self.frame_index = 0
        self.lcd_mode = "splash"
        self.splash_until = time.monotonic() + PROFILE_SPLASH_DURATION_MS / 1000
        self._display_changed.set()
        splash = _profile_splash(profile)
        async with self.device_lock:
            await asyncio.to_thread(
                set_backlight,
                self.g13,
                *profile.color,
                intensity=profile.backlight_intensity,
            )
            await asyncio.to_thread(set_mode_leds, self.g13, self._mode_led_mask())
            await asyncio.to_thread(push_image, self.g13, splash)
        print(f"active profile: {profile.name!r}")
        await self._broadcast_state()

    async def _lcd_frame_for_mode(self) -> Image.Image:
        if self.lcd_mode == "clock":
            return clock_frame()
        if self.lcd_mode == "stats":
            snapshot = await asyncio.to_thread(self._stats.sample)
            return stats_frame(snapshot)
        if self.lcd_mode == "animation" and self.frames:
            return self.frames[self.frame_index][0]
        return _profile_splash(self.active_profile)

    async def set_lcd_mode(self, mode: str) -> None:
        if mode not in LCD_MODES:
            raise ValueError(f"unknown LCD mode {mode!r}")
        self.lcd_mode = mode
        self.splash_until = None
        self.frame_index = 0
        self._display_changed.set()
        frame = await self._lcd_frame_for_mode()
        async with self.device_lock:
            await asyncio.to_thread(push_image, self.g13, frame)
        await self._broadcast_state()

    async def cycle_lcd_mode(self) -> None:
        modes = [mode for mode in LCD_MODES if mode != "animation" or self.active_profile.lcd_gif]
        current_index = modes.index(self.lcd_mode) if self.lcd_mode in modes else -1
        await self.set_lcd_mode(modes[(current_index + 1) % len(modes)])

    async def switch_profile_by_name(self, name: str) -> None:
        for index, profile in enumerate(self.profiles):
            if profile.name == name:
                if index != self.active_index:
                    await self._cancel_macros()
                    await self._release_all_held()
                    await self.activate_profile(index)
                return
        raise ValueError(f"no such profile: {name!r}")

    async def switch_profile_by_id(self, profile_id: str) -> None:
        for index, profile in enumerate(self.profiles):
            if profile.id == profile_id:
                if index != self.active_index:
                    await self._cancel_macros()
                    await self._release_all_held()
                    await self.activate_profile(index)
                return
        raise ValueError(f"no such profile ID: {profile_id!r}")

    async def switch_profile_by_slot(self, slot: int) -> None:
        for index, profile in enumerate(self.profiles):
            if profile.slot == slot:
                if index != self.active_index:
                    await self._cancel_macros()
                    await self._release_all_held()
                    await self.activate_profile(index)
                return
        raise ValueError(f"no profile assigned to M{slot}")

    def _sort_profiles(self, active_id: str) -> None:
        self.profiles.sort(key=profile_sort_key)
        self.active_index = next(
            index for index, profile in enumerate(self.profiles) if profile.id == active_id
        )

    async def _release_all_held(self) -> None:
        bindings = self.active_profile.bindings
        for name in self.held:
            code = bindings.get(name)
            if code is not None:
                self.ui.write(evdev.ecodes.EV_KEY, code, 0)
        if self.held:
            self.ui.syn()
        self.held = frozenset()

    def _record_event(self, code: int, down: bool) -> None:
        now = time.monotonic()
        delay_ms = 0 if self.macro_last_time is None else round((now - self.macro_last_time) * 1000)
        self.macro_events.append(MacroEvent(code=code, down=down, delay_ms=delay_ms))
        self.macro_last_time = now

    async def _handle_mr_press(self) -> None:
        if self.mr_state == "idle":
            self.mr_state = "armed"
            print("macro recording armed: press a G-key to record onto it")
            await self._refresh_mode_leds()
            await self._broadcast_state()
            return

        if self.mr_state == "recording" and self.macro_target and self.macro_events:
            target, events = self.macro_target, self.macro_events
            profile = self.active_profile
            await asyncio.to_thread(save_macro, profile.path, target, events)
            self.profiles[self.active_index] = await asyncio.to_thread(load_profile, profile.path)
            print(f"saved macro for {target!r} ({len(events)} events)")
        else:
            print("macro recording cancelled (nothing recorded)")

        self.mr_state = "idle"
        self.macro_target = None
        self.macro_events = []
        self.macro_last_time = None
        self._pending_target_release = None
        await self._refresh_mode_leds()
        await self._broadcast_state()

    def _launch_macro(self, events: list[MacroEvent]) -> None:
        task = asyncio.create_task(self._play_macro(events))
        self._macro_tasks.add(task)
        task.add_done_callback(self._macro_tasks.discard)

    async def _cancel_macros(self) -> None:
        tasks = list(self._macro_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _play_macro(self, events: list[MacroEvent]) -> None:
        held: set[int] = set()
        async with self._macro_lock:
            try:
                for event in events:
                    if event.delay_ms:
                        await asyncio.sleep(event.delay_ms / 1000)
                    self.ui.write(evdev.ecodes.EV_KEY, event.code, 1 if event.down else 0)
                    if event.down:
                        held.add(event.code)
                    else:
                        held.discard(event.code)
                    self.ui.syn()
            finally:
                for code in held:
                    self.ui.write(evdev.ecodes.EV_KEY, code, 0)
                if held:
                    self.ui.syn()

    async def input_loop(self) -> None:
        while True:
            async with self.device_lock:
                report = await asyncio.to_thread(self.g13.read_report, 50)
            if report is None:
                continue
            state = decode_report(report)
            self.stick = (state.stick_x, state.stick_y)
            previous_directions = frozenset(self.held & JOYSTICK_CONTROL_IDS)
            directions = (
                stick_direction_keys(state.stick_x, state.stick_y, previous_directions)
                if self.active_profile.stick_mode == "keys"
                else frozenset()
            )
            current = state.keys | directions
            pressed = current - self.held
            released = self.held - current
            self.held = current

            lcd_controls = set(LCD_BUTTON_MODES) | {"BD"}
            lcd_pressed = pressed & lcd_controls
            if "BD" in lcd_pressed:
                await self.cycle_lcd_mode()
            else:
                selected_mode = next(
                    (
                        mode
                        for key, mode in LCD_BUTTON_MODES.items()
                        if key in lcd_pressed
                    ),
                    None,
                )
                if selected_mode is not None:
                    await self.set_lcd_mode(selected_mode)
            pressed = pressed - lcd_controls
            released = released - lcd_controls

            if "MR" in pressed:
                await self._handle_mr_press()
                continue

            if self.mr_state == "armed":
                target = next(iter(sorted(pressed & G_KEY_IDS)), None)
                if target is not None:
                    self.macro_target = target
                    self.mr_state = "recording"
                    self._pending_target_release = target
                    print(f"recording macro for {target!r}; press MR again to finish")
                    await self._broadcast_state()
                continue

            if self.mr_state == "recording":
                bindings = self.active_profile.bindings
                for name in pressed:
                    code = bindings.get(name)
                    if code is not None:
                        self._record_event(code, True)
                        self.ui.write(evdev.ecodes.EV_KEY, code, 1)
                        self.ui.syn()
                for name in released:
                    if name == self._pending_target_release:
                        # the release of the tap that selected the target
                        # key -- its press was never recorded either
                        self._pending_target_release = None
                        continue
                    code = bindings.get(name)
                    if code is not None:
                        self._record_event(code, False)
                        self.ui.write(evdev.ecodes.EV_KEY, code, 0)
                        self.ui.syn()
                continue

            switch_slot = next(
                (slot + 1 for name, slot in PROFILE_SWITCH_KEYS.items() if name in pressed),
                None,
            )
            switch_to = None
            if switch_slot is not None:
                switch_to = next(
                    (
                        index
                        for index, profile in enumerate(self.profiles)
                        if profile.slot == switch_slot and index != self.active_index
                    ),
                    None,
                )
            if switch_to is not None:
                await self._cancel_macros()
                await self._release_all_held()
                await self.activate_profile(switch_to)
                continue

            profile = self.active_profile
            for name in pressed:
                if name in profile.macros:
                    self._launch_macro(profile.macros[name])
                    continue
                code = profile.bindings.get(name)
                if code is not None:
                    self.ui.write(evdev.ecodes.EV_KEY, code, 1)
                    self.ui.syn()
            for name in released:
                if name in profile.macros:
                    continue
                code = profile.bindings.get(name)
                if code is not None:
                    self.ui.write(evdev.ecodes.EV_KEY, code, 0)
                    self.ui.syn()

    async def mouse_loop(self) -> None:
        while True:
            await asyncio.sleep(MOUSE_POLL_SECONDS)
            if self.active_profile.stick_mode != "mouse":
                continue
            dx = mouse_axis_delta(self.stick[0])
            dy = mouse_axis_delta(self.stick[1])
            if dx:
                self.ui.write(evdev.ecodes.EV_REL, evdev.ecodes.REL_X, dx)
            if dy:
                self.ui.write(evdev.ecodes.EV_REL, evdev.ecodes.REL_Y, dy)
            if dx or dy:
                self.ui.syn()

    async def animation_loop(self) -> None:
        while True:
            if self.splash_until is not None:
                deadline = self.splash_until
                if await self._wait_for_display_change(max(0, deadline - time.monotonic())):
                    continue
                if self.splash_until != deadline:
                    continue
                self.splash_until = None
                self.frame_index = 0
                if self.active_profile.lcd_gif is not None:
                    self.lcd_mode = "animation"
                    async with self.device_lock:
                        await asyncio.to_thread(push_image, self.g13, self.frames[0][0])
                    await self._broadcast_state()
                continue

            mode = self.lcd_mode
            if mode in {"clock", "stats"}:
                if await self._wait_for_display_change(1.0):
                    continue
                if self.lcd_mode != mode:
                    continue
                frame = await self._lcd_frame_for_mode()
                async with self.device_lock:
                    await asyncio.to_thread(push_image, self.g13, frame)
                continue

            frames = self.frames
            if mode != "animation" or len(frames) <= 1:
                await self._wait_for_display_change(0.5)
                continue

            duration = frames[self.frame_index][1] or DEFAULT_FRAME_DURATION_MS
            if await self._wait_for_display_change(duration / 1000):
                continue
            if self.frames is not frames:
                continue  # profile changed while sleeping; re-check fresh

            self.frame_index = (self.frame_index + 1) % len(self.frames)
            async with self.device_lock:
                await asyncio.to_thread(push_image, self.g13, self.frames[self.frame_index][0])

    async def _wait_for_display_change(self, timeout: float) -> bool:
        self._display_changed.clear()
        try:
            await asyncio.wait_for(self._display_changed.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    def _profile_index_for_request(self, request: dict) -> int:
        if "id" in request:
            for index, profile in enumerate(self.profiles):
                if profile.id == request["id"]:
                    return index
            raise ValueError(f"no such profile ID: {request['id']!r}")
        if "slot" in request:
            slot = int(request["slot"])
            for index, profile in enumerate(self.profiles):
                if profile.slot == slot:
                    return index
            raise ValueError(f"no profile assigned to M{slot}")
        if "name" in request:
            for index, profile in enumerate(self.profiles):
                if profile.name == request["name"]:
                    return index
            raise ValueError(f"no such profile: {request['name']!r}")
        return self.active_index

    async def _handle_request(self, request: dict) -> dict:
        command = request.get("cmd")
        if command == "list_profiles":
            return {
                "profiles": [
                    {"id": p.id, "slot": p.slot, "name": p.name, "color": list(p.color)}
                    for p in self.profiles
                ],
                "active_id": self.active_profile.id,
                "active_slot": self.active_profile.slot,
                "active": self.active_profile.name,
            }
        if command == "switch_profile":
            if "id" in request:
                await self.switch_profile_by_id(request["id"])
            elif "slot" in request:
                await self.switch_profile_by_slot(int(request["slot"]))
            else:
                await self.switch_profile_by_name(request["name"])
            return {
                "ok": True,
                "active_id": self.active_profile.id,
                "active_slot": self.active_profile.slot,
                "active": self.active_profile.name,
            }
        if command == "get_profile":
            return {"profile": profile_to_dict(self.profiles[self._profile_index_for_request(request)])}
        if command == "update_profile":
            index = self._profile_index_for_request(request)
            original = self.profiles[index]
            updated = profile_from_payload(original, request.get("profile", {}))
            if any(
                profile.name.casefold() == updated.name.casefold() and other_index != index
                for other_index, profile in enumerate(self.profiles)
            ):
                raise ValueError(f"a profile named {updated.name!r} already exists")
            await asyncio.to_thread(save_profile, updated)
            active_id = self.active_profile.id
            if index == self.active_index:
                await self._cancel_macros()
                await self._release_all_held()
            self.profiles[index] = updated
            self._sort_profiles(active_id)
            if updated.id == active_id:
                await self.activate_profile(self.active_index)
            return {"ok": True, "profile": profile_to_dict(updated)}
        if command == "create_profile":
            active_id = self.active_profile.id
            new_profile = await asyncio.to_thread(
                create_profile, self.profiles[0].path.parent
            )
            self.profiles.append(new_profile)
            self._sort_profiles(active_id)
            await self._cancel_macros()
            await self._release_all_held()
            await self.switch_profile_by_id(new_profile.id)
            return {"ok": True, "profile": profile_to_dict(new_profile)}
        if command == "delete_profile":
            if len(self.profiles) == 1:
                raise ValueError("the final profile cannot be deleted")
            index = self._profile_index_for_request(request)
            target = self.profiles[index]
            deleting_active = index == self.active_index
            active_id = self.active_profile.id
            if deleting_active:
                await self._cancel_macros()
                await self._release_all_held()
            await asyncio.to_thread(target.path.unlink)
            self.profiles.pop(index)
            if deleting_active:
                self.active_index = 0
                await self.activate_profile(0)
            else:
                self._sort_profiles(active_id)
                await self._broadcast_state()
            return {
                "ok": True,
                "active_id": self.active_profile.id,
                "active": self.active_profile.name,
            }
        if command == "assign_profile":
            index = self._profile_index_for_request(request)
            target = self.profiles[index]
            raw_slot = request.get("slot")
            slot = None if raw_slot in (None, 0) else int(raw_slot)
            if slot is not None and slot not in (1, 2, 3):
                raise ValueError("M-key assignment must be M1, M2, M3, or unassigned")
            active_id = self.active_profile.id
            changed: list[Profile] = []
            replacements: dict[str, Profile] = {}
            for profile in self.profiles:
                new_slot = profile.slot
                if profile.id == target.id:
                    new_slot = slot
                elif slot is not None and profile.slot == slot:
                    new_slot = None
                if new_slot != profile.slot:
                    replacement = replace(profile, slot=new_slot)
                    replacements[profile.id] = replacement
                    changed.append(replacement)
            for profile in changed:
                await asyncio.to_thread(save_profile, profile)
            self.profiles = [replacements.get(profile.id, profile) for profile in self.profiles]
            self._sort_profiles(active_id)
            if active_id in replacements:
                await self.activate_profile(self.active_index)
            else:
                await self._broadcast_state()
            return {"ok": True, "profile": profile_to_dict(replacements.get(target.id, target))}
        if command == "set_lcd_mode":
            if request["mode"] == "cycle":
                await self.cycle_lcd_mode()
            else:
                await self.set_lcd_mode(request["mode"])
            return {"ok": True, "lcd_mode": self.lcd_mode}
        return {"error": f"unknown command {command!r}"}

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = decode(line)
                except Exception as exc:
                    writer.write(encode({"kind": "response", "error": str(exc)}))
                    await writer.drain()
                    continue

                if request.get("cmd") == "subscribe":
                    self._subscribers.add(writer)
                    writer.write(encode(self._current_state()))
                    await writer.drain()
                    continue

                try:
                    response = await self._handle_request(request)
                except Exception as exc:
                    response = {"error": str(exc)}
                writer.write(encode({"kind": "response", **response}))
                await writer.drain()
        except (ConnectionError, OSError):
            pass  # client disconnected; nothing to clean up beyond the finally block
        finally:
            self._subscribers.discard(writer)
            writer.close()


def prepare_socket_directory(path=SOCKET_PATH) -> None:
    """Create and validate the owner-only directory containing the control socket."""
    directory = path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = directory.lstat()
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid():
        raise RuntimeError(f"unsafe daemon socket directory: {directory}")
    directory.chmod(0o700)


async def run_async() -> None:
    ensure_default_profiles()
    profiles = load_profiles()
    if not profiles:
        raise RuntimeError("no profiles found")

    ui = build_uinput(profiles)
    try:
        with G13Device() as g13:
            daemon = G13Daemon(g13, ui, profiles)
            await daemon.activate_profile(0)

            prepare_socket_directory()
            SOCKET_PATH.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(daemon.handle_client, path=str(SOCKET_PATH))
            SOCKET_PATH.chmod(0o600)

            print(
                f"g13d running, profile: {daemon.active_profile.name!r}, "
                f"socket: {SOCKET_PATH} (Ctrl-C to stop)..."
            )
            async with server:
                await asyncio.gather(
                    daemon.input_loop(),
                    daemon.mouse_loop(),
                    daemon.animation_loop(),
                    daemon.broadcast_loop(),
                    server.serve_forever(),
                )
    finally:
        ui.close()
        SOCKET_PATH.unlink(missing_ok=True)


def run() -> None:
    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    run()
