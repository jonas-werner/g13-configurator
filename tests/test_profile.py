from __future__ import annotations

import tempfile
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

import tomli_w
from evdev import ecodes
from PIL import Image

from g13.presets import GAME_PRESETS
from g13.profile import (
    ProfileError,
    create_profile,
    ensure_default_profiles,
    load_profiles,
    profile_from_payload,
    profile_to_dict,
    save_profile,
)


class ProfileTests(unittest.TestCase):
    def test_defaults_create_three_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profiles = load_profiles(path)

            self.assertEqual([profile.slot for profile in profiles], [1, 2, 3])
            self.assertEqual([profile.name for profile in profiles], ["Cyberpunk 2077", "Profile 2", "Profile 3"])
            self.assertEqual(profiles[0].bindings["LEFT"], ecodes.KEY_T)
            self.assertEqual(profiles[0].bindings["DOWN"], ecodes.KEY_V)
            self.assertEqual(profiles[0].bindings["TOP"], ecodes.BTN_MIDDLE)
            self.assertEqual(profiles[0].bindings["STICK_UP"], ecodes.KEY_UP)

    def test_cyberpunk_export_matches_first_run_and_existing_edits_survive(self) -> None:
        exported = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "assets/profiles/cyberpunk-2077.toml").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profile = load_profiles(path)[0]
            self.assertEqual(profile_to_dict(profile)["bindings"], exported["bindings"])
            self.assertEqual(profile.backlight_intensity, 60)
            edited = replace(profile, name="My layout", bindings={"G22": ecodes.KEY_T})
            save_profile(edited)
            ensure_default_profiles(path)
            loaded = load_profiles(path)[0]
            self.assertEqual(loaded.name, "My layout")
            self.assertEqual(loaded.bindings["G22"], ecodes.KEY_T)
            self.assertNotIn("G4", loaded.bindings)

    def test_legacy_migration_preserves_recorded_macro(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "alphabet.toml").write_text(
                tomli_w.dumps(
                    {
                        "name": "alphabet",
                        "color": [0, 255, 0],
                        "bindings": {"G1": "KEY_A"},
                        "macros": {
                            "G2": [
                                {"code": "KEY_B", "down": True, "delay_ms": 0},
                                {"code": "KEY_B", "down": False, "delay_ms": 20},
                            ]
                        },
                    }
                )
            )

            ensure_default_profiles(path)
            profiles = load_profiles(path)

            self.assertEqual(profiles[0].name, "Profile 1")
            self.assertEqual(profiles[0].bindings["G1"], ecodes.KEY_A)
            self.assertEqual(profiles[0].macros["G2"][1].delay_ms, 20)
            self.assertEqual(len(profiles), 1)

    def test_profiles_can_be_created_unassigned_and_sorted_after_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            first = create_profile(path)
            second = create_profile(path)
            self.assertIsNone(first.slot)
            self.assertIsNone(second.slot)
            self.assertNotEqual(first.id, second.id)

            profiles = load_profiles(path)
            self.assertEqual([profile.slot for profile in profiles[:3]], [1, 2, 3])
            self.assertTrue(all(profile.slot is None for profile in profiles[3:]))

    def test_unassigned_slot_round_trips_as_zero_in_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profile = load_profiles(path)[0]
            save_profile(replace(profile, slot=None))

            loaded = next(item for item in load_profiles(path) if item.id == profile.id)
            self.assertIsNone(loaded.slot)
            with loaded.path.open("rb") as source:
                self.assertEqual(tomllib.load(source)["slot"], 0)

    def test_payload_round_trip_supports_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            original = load_profiles(path)[0]
            payload = profile_to_dict(original)
            payload["name"] = "Doom"
            payload["color"] = [180, 20, 10]
            payload["bindings"] = {"G4": "KEY_W", "G10": "KEY_A"}
            payload["macros"] = {
                "G11": [
                    {"code": "KEY_LEFTCTRL", "down": True, "delay_ms": 0},
                    {"code": "KEY_E", "down": True, "delay_ms": 0},
                    {"code": "KEY_E", "down": False, "delay_ms": 0},
                    {"code": "KEY_LEFTCTRL", "down": False, "delay_ms": 0},
                ]
            }
            updated = profile_from_payload(original, payload)
            save_profile(updated)

            loaded = load_profiles(path)[0]
            self.assertEqual(loaded.name, "Doom")
            self.assertEqual(loaded.color, (180, 20, 10))
            self.assertEqual(loaded.bindings["G4"], ecodes.KEY_W)
            self.assertEqual(len(loaded.macros["G11"]), 4)

    def test_unbalanced_macro_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profile = load_profiles(path)[0]
            payload = profile_to_dict(profile)
            payload["macros"] = {
                "G1": [{"code": "KEY_LEFTSHIFT", "down": True, "delay_ms": 0}]
            }
            with self.assertRaisesRegex(ProfileError, "leaves one or more keys held"):
                profile_from_payload(profile, payload)

    def test_saved_toml_never_contains_null_lcd_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profile = load_profiles(path)[0]
            save_profile(profile)
            with profile.path.open("rb") as source:
                data = tomllib.load(source)
            self.assertNotIn("lcd_image", data)
            self.assertNotIn("lcd_gif", data)

    def test_backlight_intensity_round_trip_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profile = load_profiles(path)[0]
            payload = profile_to_dict(profile)
            payload["backlight_intensity"] = 45
            save_profile(profile_from_payload(profile, payload))
            self.assertEqual(load_profiles(path)[0].backlight_intensity, 45)

            payload["backlight_intensity"] = 101
            with self.assertRaisesRegex(ProfileError, "0 to 100"):
                profile_from_payload(profile, payload)

    def test_static_image_and_animation_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            image_path = path / "splash.png"
            gif_path = path / "animation.gif"
            Image.new("1", (160, 43), 0).save(image_path)
            Image.new("1", (160, 43), 0).save(
                gif_path,
                save_all=True,
                append_images=[Image.new("1", (160, 43), 1)],
                duration=125,
                loop=0,
            )
            profile = load_profiles(path)[0]
            payload = profile_to_dict(profile)
            payload["lcd_image"] = str(image_path)
            payload["lcd_gif"] = str(gif_path)
            save_profile(profile_from_payload(profile, payload))

            loaded = load_profiles(path)[0]
            self.assertEqual(loaded.lcd_image, image_path)
            self.assertEqual(loaded.lcd_gif, gif_path)

    def test_wrong_lcd_dimensions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            image_path = path / "wrong.png"
            Image.new("1", (320, 86), 0).save(image_path)
            profile = load_profiles(path)[0]
            payload = profile_to_dict(profile)
            payload["lcd_image"] = str(image_path)
            with self.assertRaisesRegex(ProfileError, "exactly 160x43"):
                profile_from_payload(profile, payload)

    def test_all_game_presets_are_valid_profile_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_default_profiles(path)
            profile = load_profiles(path)[0]
            for preset in GAME_PRESETS:
                with self.subTest(preset=preset.name):
                    payload = profile_to_dict(profile)
                    payload.update(
                        {
                            "name": preset.name,
                            "color": list(preset.color),
                            "bindings": preset.bindings,
                            "macros": preset.macros,
                        }
                    )
                    updated = profile_from_payload(profile, payload)
                    self.assertTrue(updated.bindings or updated.macros)


if __name__ == "__main__":
    unittest.main()
