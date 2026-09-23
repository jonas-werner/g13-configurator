from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PIL import Image

from g13.gui.binding_editor import KeyCaptureButton, MacroRecorder, ProfileInspector, shortcut_events
from g13.gui.device_layout import ASSET_PATH, G_KEYS, IMAGE_H, IMAGE_W
from g13.gui.keyboard_view import G13View


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_required_device_image_is_bundled(self) -> None:
        self.assertTrue(ASSET_PATH.is_file())

    def test_clicking_image_key_selects_g_key(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        view.show()
        selected: list[str] = []
        view.key_selected.connect(selected.append)
        key = next(key for key in G_KEYS if key.id == "G4")
        point = QPoint(round((key.x + key.w / 2) / 2), round((key.y + key.h / 2) / 2))

        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(selected, ["G4"])

    def test_clicking_joystick_selects_press_and_direction(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        view.show()
        selected: list[str] = []
        view.key_selected.connect(selected.append)

        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(472, 460))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(472, 430))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(472, 490))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(470, 535))

        self.assertEqual(selected, ["TOP", "STICK_UP", "STICK_DOWN", "DOWN"])

    def test_lcd_buttons_select_views_and_application_button_cycles(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        view.show()
        modes: list[str] = []
        view.lcd_mode_requested.connect(modes.append)

        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(295, 143))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(140, 140))

        self.assertEqual(modes, ["clock", "cycle"])

    def test_shortcut_event_order_releases_modifiers_last(self) -> None:
        events = shortcut_events(["KEY_LEFTCTRL", "KEY_E"])
        self.assertEqual(
            [(event["code"], event["down"]) for event in events],
            [
                ("KEY_LEFTCTRL", True),
                ("KEY_E", True),
                ("KEY_E", False),
                ("KEY_LEFTCTRL", False),
            ],
        )

    def test_inspector_tracks_binding_draft(self) -> None:
        inspector = ProfileInspector()
        profile = {
            "id": "profile-1",
            "slot": 1,
            "name": "Profile 1",
            "color": [0, 255, 0],
            "bindings": {},
            "macros": {},
            "lcd_image": None,
            "lcd_gif": None,
        }
        inspector.set_profile(profile)
        self.assertEqual(inspector.status.text(), "")
        inspector.set_profile(profile, show_saved=True)
        self.assertEqual(inspector.status.text(), "Saved")
        inspector.set_profile(profile)
        self.assertEqual(inspector.status.text(), "")
        inspector.select_key("G4")
        inspector.action_combo.setCurrentIndex(inspector.action_combo.findData("single"))
        inspector._captured(["KEY_W"])

        self.assertTrue(inspector.is_dirty)
        self.assertEqual(inspector._draft["bindings"]["G4"], "KEY_W")
        inspector.revert()
        self.assertFalse(inspector.is_dirty)

    def test_media_picker_validation_and_preset_application(self) -> None:
        inspector = ProfileInspector()
        inspector.set_profile(
            {
                "id": "profile-1",
                "slot": 1,
                "name": "Profile 1",
                "color": [0, 255, 0],
                "bindings": {},
                "macros": {},
                "lcd_image": None,
                "lcd_gif": None,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.png"
            invalid = Path(directory) / "invalid.png"
            Image.new("1", (160, 43), 0).save(valid)
            Image.new("1", (100, 100), 0).save(invalid)
            self.assertIsNone(inspector._media_error(valid, animated=False))
            self.assertIn("160×43", inspector._media_error(invalid, animated=False))

        index = inspector.preset_combo.findData("SnowRunner")
        inspector.preset_combo.setCurrentIndex(index)
        inspector._apply_preset()
        self.assertEqual(inspector._draft["name"], "SnowRunner")
        self.assertEqual(inspector._draft["bindings"]["G4"], "KEY_W")
        self.assertTrue(inspector.is_dirty)

    def test_device_view_renders_tinted_lcd_graphic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "splash.png"
            image = Image.new("1", (160, 43), 0)
            image.putpixel((10, 10), 1)
            image.save(path)
            view = G13View()
            view.set_state((20, 140, 220), frozenset())
            view.set_lcd_content("Test", str(path), None)

            rendered = view._render_lcd_image()
            self.assertEqual(rendered.size().toTuple(), (160, 43))
            self.assertEqual(rendered.pixelColor(10, 10).getRgb()[:3], (20, 140, 220))
            self.assertEqual(rendered.pixelColor(0, 0).getRgb()[:3], (1, 3, 4))
            view.set_preview_intensity(50)
            rendered = view._render_lcd_image()
            self.assertEqual(rendered.pixelColor(10, 10).getRgb()[:3], (10, 70, 110))

    def test_inspector_edits_mouse_buttons_and_stick_mode(self) -> None:
        inspector = ProfileInspector()
        inspector.set_profile(
            {
                "id": "profile-1",
                "slot": 1,
                "name": "Profile 1",
                "color": [0, 255, 0],
                "bindings": {"LEFT": "BTN_LEFT", "STICK_UP": "KEY_UP"},
                "macros": {},
                "lcd_image": None,
                "lcd_gif": None,
                "stick_mode": "keys",
            }
        )
        inspector.select_key("LEFT")
        self.assertEqual(inspector.action_combo.currentData(), "mouse_button")
        inspector.mouse_button_combo.setCurrentIndex(
            inspector.mouse_button_combo.findData("BTN_RIGHT")
        )
        inspector.stick_mode_combo.setCurrentIndex(
            inspector.stick_mode_combo.findData("mouse")
        )
        inspector.intensity_slider.setValue(35)
        self.assertEqual(inspector._draft["bindings"]["LEFT"], "BTN_RIGHT")
        self.assertEqual(inspector._draft["stick_mode"], "mouse")
        self.assertEqual(inspector._draft["backlight_intensity"], 35)

    def test_inspector_assigns_and_deassigns_m_slots(self) -> None:
        inspector = ProfileInspector()
        inspector.set_profile(
            {
                "id": "profile-1",
                "slot": 1,
                "name": "Profile 1",
                "color": [0, 255, 0],
                "bindings": {},
                "macros": {},
                "lcd_image": None,
                "lcd_gif": None,
                "stick_mode": "keys",
            }
        )
        changes: list[tuple[str, int | None]] = []
        inspector.slot_assignment_requested.connect(
            lambda profile_id, slot: changes.append((profile_id, slot))
        )
        inspector.slot_combo.setCurrentIndex(inspector.slot_combo.findData(None))

        self.assertEqual(changes, [("profile-1", None)])
        inspector.update_slot(None)
        self.assertIsNone(inspector._profile["slot"])
        self.assertIsNone(inspector._draft["slot"])

    def test_macro_widgets_trap_tab_focus(self) -> None:
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        
        # Create a dummy window with siblings so focus *can* theoretically shift
        parent = QWidget()
        layout = QVBoxLayout(parent)
        capture_btn = KeyCaptureButton()
        macro_btn = MacroRecorder()
        layout.addWidget(capture_btn)
        layout.addWidget(macro_btn)
        
        # 1. Test KeyCaptureButton
        # By default, it should allow focus to pass to the next widget (returns True)
        self.assertTrue(capture_btn.focusNextPrevChild(True))
        
        # When capturing, it must trap the focus (returns False)
        capture_btn._begin()
        self.assertFalse(capture_btn.focusNextPrevChild(True))
        
        # 2. Test MacroRecorder
        # By default, it should allow focus to pass
        self.assertTrue(macro_btn.focusNextPrevChild(True))
        
        # When checked (recording), it must trap the focus
        macro_btn.setChecked(True)
        self.assertFalse(macro_btn.focusNextPrevChild(True))


if __name__ == "__main__":
    unittest.main()
