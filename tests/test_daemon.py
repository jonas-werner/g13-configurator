from __future__ import annotations

import asyncio
import errno
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from evdev import ecodes
from PIL import Image
import usb.core

from g13.hardware.device import G13NotFoundError

from g13.daemon.service import (
    G13Daemon,
    _profile_frames,
    _profile_splash,
    mouse_axis_delta,
    run_async,
    _run_device_session,
    prepare_socket_directory,
    stick_direction_keys,
)
from g13.hardware.lcd import BACKLIGHT_VALUE, MODE_LEDS_VALUE
from g13.hardware.report import KEY_NAMES
from g13.profile import MacroEvent, ensure_default_profiles, load_profiles


class FakeG13:
    def __init__(self) -> None:
        self.controls: list[tuple[int, int, int, int, bytes]] = []
        self.writes: list[tuple[int, bytes]] = []

    def control_transfer(
        self, request_type: int, request: int, value: int, index: int, data: bytes
    ) -> int:
        self.controls.append((request_type, request, value, index, bytes(data)))
        return len(data)

    def write(self, endpoint: int, data: bytes) -> int:
        self.writes.append((endpoint, bytes(data)))
        return len(data)


class FakeUInput:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int]] = []
        self.syncs = 0

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value))

    def syn(self) -> None:
        self.syncs += 1


class DaemonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name)
        ensure_default_profiles(path)
        self.g13 = FakeG13()
        self.ui = FakeUInput()
        self.daemon = G13Daemon(self.g13, self.ui, load_profiles(path))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_socket_directory_is_owner_only_and_rejects_symlinks(self) -> None:
        root = Path(self.temporary_directory.name)
        socket_path = root / "runtime" / "g13d.sock"
        prepare_socket_directory(socket_path)
        self.assertEqual(socket_path.parent.stat().st_mode & 0o777, 0o700)

        link = root / "linked-runtime"
        link.symlink_to(socket_path.parent, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "unsafe daemon socket directory"):
            prepare_socket_directory(link / "g13d.sock")

    async def test_profile_update_is_live_and_persisted(self) -> None:
        response = await self.daemon._handle_request(
            {
                "cmd": "update_profile",
                "slot": 1,
                "profile": {
                    "name": "Doom",
                    "color": [120, 10, 10],
                    "backlight_intensity": 50,
                    "bindings": {"G4": "KEY_W"},
                    "macros": {},
                },
            }
        )

        self.assertTrue(response["ok"])
        self.assertEqual(self.daemon.active_profile.name, "Doom")
        self.assertEqual(self.daemon.active_profile.backlight_intensity, 50)
        self.assertEqual(self.daemon.active_profile.bindings["G4"], ecodes.KEY_W)
        self.assertEqual(load_profiles(Path(self.temporary_directory.name))[0].name, "Doom")
        mode_reports = [control for control in self.g13.controls if control[2] == MODE_LEDS_VALUE]
        self.assertEqual(mode_reports[-1][4][1], 0x01)
        backlight_reports = [
            control for control in self.g13.controls if control[2] == BACKLIGHT_VALUE
        ]
        self.assertEqual(backlight_reports[-1][4], bytes([5, 60, 5, 5, 0]))

    async def test_profile_crud_and_slot_reassignment(self) -> None:
        original_m1_id = next(profile.id for profile in self.daemon.profiles if profile.slot == 1)
        created = await self.daemon._handle_request({"cmd": "create_profile"})
        new_id = created["profile"]["id"]
        self.assertIsNone(created["profile"]["slot"])
        self.assertEqual(self.daemon.active_profile.id, new_id)

        assigned = await self.daemon._handle_request(
            {"cmd": "assign_profile", "id": new_id, "slot": 1}
        )
        self.assertEqual(assigned["profile"]["slot"], 1)
        old_m1 = next(profile for profile in self.daemon.profiles if profile.id == original_m1_id)
        self.assertIsNone(old_m1.slot)
        self.assertEqual(self.daemon.profiles[0].id, new_id)

        deleted = await self.daemon._handle_request({"cmd": "delete_profile", "id": new_id})
        self.assertTrue(deleted["ok"])
        self.assertNotIn(new_id, {profile.id for profile in self.daemon.profiles})

    async def test_all_m_slots_can_be_empty(self) -> None:
        for profile in list(self.daemon.profiles):
            await self.daemon._handle_request(
                {"cmd": "assign_profile", "id": profile.id, "slot": None}
            )
        self.assertTrue(all(profile.slot is None for profile in self.daemon.profiles))
        self.assertEqual(self.daemon._mode_led_mask(), 0)
        with self.assertRaisesRegex(ValueError, "no profile assigned"):
            await self.daemon.switch_profile_by_slot(1)

    async def test_input_only_switches_profiles_for_assigned_m_keys(self) -> None:
        original = self.daemon.profiles[0]
        cyberpunk = replace(
            self.daemon.profiles[1], slot=1, name="Cyberpunk 2077",
            bindings={"G8": ecodes.KEY_TAB},
        )
        self.daemon.profiles = [
            cyberpunk,
            replace(self.daemon.profiles[2], slot=3),
            replace(original, slot=None, name="The Ascent"),
            replace(original, slot=None, name="Another unassigned profile"),
        ]
        self.daemon.active_index = 0

        async def feed(*key_sets: tuple[str, ...]) -> None:
            reports = []
            for keys in key_sets:
                report = bytearray([1, 128, 128, 0, 0, 0, 0, 0])
                for key in keys:
                    index = KEY_NAMES.index(key)
                    report[3 + index // 8] |= 1 << (index % 8)
                reports.append(bytes(report))
            with patch.object(
                self.g13, "read_report", create=True,
                side_effect=[*reports, EOFError("end of reports")],
            ):
                with self.assertRaises(EOFError):
                    await self.daemon.input_loop()

        await feed((), ("G8",), (), ("M2",), ())
        self.assertEqual(self.daemon.active_profile.id, cyberpunk.id)
        self.assertEqual(self.ui.events, [
            (ecodes.EV_KEY, ecodes.KEY_TAB, 1),
            (ecodes.EV_KEY, ecodes.KEY_TAB, 0),
        ])
        self.daemon.active_index = 2
        with patch.object(self.daemon, "activate_profile", wraps=self.daemon.activate_profile) as activate:
            await feed(*((), ("G8",), ()) * 8)
            self.assertEqual(self.daemon.active_index, 2)
            activate.assert_not_called()
        await feed(("M3",), ())
        self.assertEqual(self.daemon.active_profile.slot, 3)
        await feed(("M1",), (), ("G8",), ())
        self.assertEqual(self.daemon.active_profile.id, cyberpunk.id)
        self.assertEqual(self.ui.events[-2:], [
            (ecodes.EV_KEY, ecodes.KEY_TAB, 1),
            (ecodes.EV_KEY, ecodes.KEY_TAB, 0),
        ])

    async def test_disconnect_stops_workers_releases_keys_and_closes_subscribers(self) -> None:
        stopped = []
        async def worker():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)
        async def fail():
            await asyncio.sleep(0)
            raise usb.core.USBError("unplugged", errno=errno.ENODEV)
        self.daemon.held = frozenset({"G4"})
        subscriber = Mock()
        self.daemon._subscribers.add(subscriber)
        server = Mock(serve_forever=worker)
        with patch.object(self.daemon, "input_loop", side_effect=fail), \
             patch.object(self.daemon, "mouse_loop", side_effect=worker), \
             patch.object(self.daemon, "animation_loop", side_effect=worker), \
             patch.object(self.daemon, "broadcast_loop", side_effect=worker):
            with self.assertRaises(usb.core.USBError):
                await self.daemon.run_loops(server)
        self.assertEqual(len(stopped), 4)
        self.assertFalse(self.daemon.held)
        self.assertIn((ecodes.EV_KEY, ecodes.KEY_W, 0), self.ui.events)
        subscriber.close.assert_called_once()
        self.assertFalse(self.daemon._subscribers)

    async def test_disconnect_and_absence_retry_before_success(self) -> None:
        with patch("g13.daemon.service._run_device_session", new_callable=AsyncMock) as session, \
             patch("g13.daemon.service.asyncio.sleep", new_callable=AsyncMock) as sleep:
            session.side_effect = [usb.core.USBError("gone", errno=errno.ENODEV),
                                   G13NotFoundError("absent"), None]
            await run_async()
            self.assertEqual(session.await_count, 3)
            self.assertEqual(sleep.await_count, 2)
            sleep.assert_awaited_with(2)

    async def test_non_disconnect_usb_errors_do_not_retry(self) -> None:
        with patch("g13.daemon.service._run_device_session", new_callable=AsyncMock) as session, \
             patch("g13.daemon.service.asyncio.sleep", new_callable=AsyncMock) as sleep:
            session.side_effect = usb.core.USBError("stalled", errno=errno.EPIPE)
            with self.assertRaises(usb.core.USBError):
                await run_async()
            sleep.assert_not_awaited()

    async def test_device_session_closes_input_and_socket_after_disconnect(self) -> None:
        socket_path = Path(self.temporary_directory.name) / "daemon.sock"
        ui = Mock()
        device_context = Mock()
        device_context.__enter__ = Mock(return_value=self.g13)
        device_context.__exit__ = Mock(return_value=False)
        async def unplugged(*args):
            raise usb.core.USBError("gone", errno=errno.ENODEV)
        with patch("g13.daemon.service.ensure_default_profiles"), \
             patch("g13.daemon.service.load_profiles", return_value=self.daemon.profiles), \
             patch("g13.daemon.service.G13Device", return_value=device_context), \
             patch("g13.daemon.service.build_uinput", return_value=ui), \
             patch("g13.daemon.service.prepare_socket_directory"), \
             patch("g13.daemon.service.SOCKET_PATH", socket_path), \
             patch.object(G13Daemon, "input_loop", side_effect=unplugged):
            with self.assertRaises(usb.core.USBError):
                await _run_device_session()
        ui.close.assert_called_once()
        device_context.__exit__.assert_called_once()
        self.assertFalse(socket_path.exists())

    async def test_waiting_for_device_does_not_create_virtual_keyboards(self) -> None:
        with patch("g13.daemon.service.ensure_default_profiles"), \
             patch("g13.daemon.service.load_profiles", return_value=self.daemon.profiles), \
             patch("g13.daemon.service.G13Device") as device, \
             patch("g13.daemon.service.build_uinput") as build:
            device.return_value.__enter__.side_effect = G13NotFoundError("absent")
            with self.assertRaises(G13NotFoundError):
                await _run_device_session()
            build.assert_not_called()

    async def test_final_profile_cannot_be_deleted(self) -> None:
        for profile in list(self.daemon.profiles[1:]):
            await self.daemon._handle_request({"cmd": "delete_profile", "id": profile.id})
        with self.assertRaisesRegex(ValueError, "final profile"):
            await self.daemon._handle_request(
                {"cmd": "delete_profile", "id": self.daemon.profiles[0].id}
            )

    async def test_subscription_state_exposes_mr_status(self) -> None:
        self.daemon.mr_state = "recording"
        self.daemon.macro_target = "G5"
        state = self.daemon._current_state()
        self.assertEqual(state["slot"], 1)
        self.assertEqual(state["mr_state"], "recording")
        self.assertEqual(state["macro_target"], "G5")

    async def test_lcd_soft_buttons_and_cycle_modes(self) -> None:
        await self.daemon.set_lcd_mode("clock")
        self.assertEqual(self.daemon.lcd_mode, "clock")
        self.assertEqual(self.daemon._current_state()["lcd_mode"], "clock")
        await self.daemon.cycle_lcd_mode()
        self.assertEqual(self.daemon.lcd_mode, "stats")
        await self.daemon.cycle_lcd_mode()
        self.assertEqual(self.daemon.lcd_mode, "splash")

    async def test_cancelling_macro_releases_held_modifier(self) -> None:
        events = [
            MacroEvent(ecodes.KEY_LEFTCTRL, True, 0),
            MacroEvent(ecodes.KEY_E, True, 10_000),
            MacroEvent(ecodes.KEY_E, False, 0),
            MacroEvent(ecodes.KEY_LEFTCTRL, False, 0),
        ]
        self.daemon._launch_macro(events)
        await asyncio.sleep(0)
        await self.daemon._cancel_macros()

        self.assertIn((ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1), self.ui.events)
        self.assertIn((ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0), self.ui.events)

    async def test_animation_transitions_from_splash_to_content(self) -> None:
        content = Image.new("1", (160, 43), 1)
        self.daemon.profiles[0] = replace(
            self.daemon.active_profile, lcd_gif=Path("/tmp/test-animation.gif")
        )
        self.daemon.frames = [(content, 0)]
        self.daemon.splash_until = time.monotonic() + 0.01
        self.daemon._display_changed.clear()
        task = asyncio.create_task(self.daemon.animation_loop())
        try:
            await asyncio.sleep(0.04)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertGreaterEqual(len(self.g13.writes), 1)

    async def test_activate_pushes_name_splash(self) -> None:
        with patch("g13.daemon.service.push_image") as push:
            await self.daemon.activate_profile(0)
        self.assertEqual(push.call_count, 1)
        image = push.call_args.args[1]
        self.assertEqual(image.size, (160, 43))

    async def test_analog_stick_direction_hysteresis(self) -> None:
        self.assertEqual(stick_direction_keys(128, 128), frozenset())
        self.assertEqual(stick_direction_keys(30, 220), {"STICK_LEFT", "STICK_DOWN"})
        self.assertIn("STICK_LEFT", stick_direction_keys(80, 128, frozenset({"STICK_LEFT"})))
        self.assertNotIn("STICK_LEFT", stick_direction_keys(110, 128, frozenset({"STICK_LEFT"})))

    async def test_mouse_mode_emits_relative_motion(self) -> None:
        self.daemon.profiles[0] = replace(self.daemon.active_profile, stick_mode="mouse")
        self.daemon.stick = (255, 0)
        task = asyncio.create_task(self.daemon.mouse_loop())
        try:
            await asyncio.sleep(0.04)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIn((ecodes.EV_REL, ecodes.REL_X, mouse_axis_delta(255)), self.ui.events)
        self.assertIn((ecodes.EV_REL, ecodes.REL_Y, mouse_axis_delta(0)), self.ui.events)

    async def test_static_splash_transitions_to_gif_frames(self) -> None:
        path = Path(self.temporary_directory.name)
        splash_path = path / "splash.png"
        gif_path = path / "animation.gif"
        Image.new("1", (160, 43), 0).save(splash_path)
        Image.new("1", (160, 43), 0).save(
            gif_path,
            save_all=True,
            append_images=[Image.new("1", (160, 43), 1)],
            duration=125,
            loop=0,
        )
        profile = replace(self.daemon.active_profile, lcd_image=splash_path, lcd_gif=gif_path)

        self.assertEqual(_profile_splash(profile).getpixel((0, 0)), 0)
        frames = _profile_frames(profile)
        self.assertEqual(len(frames), 2)
        self.assertGreater(frames[0][1], 0)


if __name__ == "__main__":
    unittest.main()
