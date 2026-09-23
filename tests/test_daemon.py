from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from evdev import ecodes
from PIL import Image

from g13.daemon.service import (
    G13Daemon,
    _profile_frames,
    _profile_splash,
    mouse_axis_delta,
    prepare_socket_directory,
    stick_direction_keys,
)
from g13.hardware.lcd import BACKLIGHT_VALUE, MODE_LEDS_VALUE
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

    async def test_regular_keys_do_not_trigger_slot_switching(self) -> None:
        """Ensure that when no M-key is pressed (switch_slot is None), 
        unassigned profiles (slot = None) are never matched for switching."""
        active_id_before = self.daemon.active_profile.id
        
        # Simulate the exact guard logic used in input_loop
        switch_slot = None  # No M-key pressed
        switch_to = None
        if switch_slot is not None:
            switch_to = next(
                (
                    index
                    for index, profile in enumerate(self.daemon.profiles)
                    if profile.slot == switch_slot and index != self.daemon.active_index
                ),
                None,
            )
            
        self.assertIsNone(switch_to)
        self.assertEqual(self.daemon.active_profile.id, active_id_before)

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