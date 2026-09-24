from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from PIL import Image

from g13.gui.binding_editor import (
    KeyCaptureButton, MacroRecorder, ProfileInspector, event_key_name,
    shortcut_events, shortcut_key_names,
)
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

    def test_tab_is_captured_instead_of_moving_focus(self) -> None:
        window = QWidget()
        layout = QVBoxLayout(window)
        capture = KeyCaptureButton()
        neighbor = QPushButton("Next")
        layout.addWidget(capture)
        layout.addWidget(neighbor)
        window.show()
        self.app.processEvents()
        captured = []
        capture.captured.connect(captured.append)
        try:
            capture.click()
            QTest.keyClick(capture, Qt.Key.Key_Tab)
            self.assertEqual(captured, [["KEY_TAB"]])
            self.assertTrue(capture.hasFocus())
            # Normal keyboard navigation still works after capture completes.
            QTest.keyClick(capture, Qt.Key.Key_Tab)
            self.assertTrue(neighbor.hasFocus())

            capture.click()
            self.app.sendEvent(capture, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Backtab,
                Qt.KeyboardModifier.ShiftModifier,
            ))
            self.assertEqual(len(captured), 1)
            self.app.sendEvent(capture, QKeyEvent(
                QEvent.Type.KeyRelease, Qt.Key.Key_Backtab,
                Qt.KeyboardModifier.ShiftModifier,
            ))
            self.assertEqual(captured[-1], ["KEY_LEFTSHIFT", "KEY_TAB"])
        finally:
            capture.releaseKeyboard()
            window.close()

    def test_macro_records_balanced_tab_events_without_moving_focus(self) -> None:
        window = QWidget()
        layout = QVBoxLayout(window)
        recorder = MacroRecorder()
        neighbor = QPushButton("Next")
        layout.addWidget(recorder)
        layout.addWidget(neighbor)
        window.show()
        self.app.processEvents()
        try:
            recorder.click()
            QTest.keyClick(recorder, Qt.Key.Key_Tab)
            self.assertTrue(recorder.hasFocus())
            self.assertEqual(
                [(event["code"], event["down"]) for event in recorder.events()],
                [("KEY_TAB", True), ("KEY_TAB", False)],
            )
            recorder.click()
            QTest.keyClick(recorder, Qt.Key.Key_Tab)
            self.assertTrue(neighbor.hasFocus())
        finally:
            recorder.releaseKeyboard()
            window.close()

    def test_modifier_capture_waits_for_release_and_preserves_chords(self) -> None:
        capture = KeyCaptureButton()
        captured = []
        capture.captured.connect(captured.append)
        for key, name in (
            (Qt.Key.Key_Control, "KEY_LEFTCTRL"),
            (Qt.Key.Key_Alt, "KEY_LEFTALT"),
            (Qt.Key.Key_Shift, "KEY_LEFTSHIFT"),
            (Qt.Key.Key_Meta, "KEY_LEFTMETA"),
        ):
            capture.click()
            QTest.keyPress(capture, key)
            self.assertTrue(capture.recording())
            QTest.keyRelease(capture, key)
            self.assertEqual(captured[-1], [name])
        capture.click()
        for key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_K):
            QTest.keyPress(capture, key)
            self.assertTrue(capture.recording())
        QTest.keyRelease(capture, Qt.Key.Key_K)
        self.assertTrue(capture.recording())
        QTest.keyRelease(capture, Qt.Key.Key_Alt)
        QTest.keyRelease(capture, Qt.Key.Key_Control)
        self.assertEqual(captured[-1], ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_K"])

    def test_native_right_modifier_and_keypad_are_preserved(self) -> None:
        with patch.object(QApplication, "platformName", return_value="xcb"):
            event = QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Control,
                Qt.KeyboardModifier.ControlModifier, 105, 0, 0,
            )
            self.assertEqual(event_key_name(event), "KEY_RIGHTCTRL")
            self.assertEqual(shortcut_key_names(event), ["KEY_RIGHTCTRL"])
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1,
                          Qt.KeyboardModifier.KeypadModifier)
        self.assertEqual(event_key_name(event), "KEY_KP1")

    def test_recording_consumes_shortcuts_special_keys_and_repeat(self) -> None:
        window = QWidget()
        layout = QVBoxLayout(window)
        recorder = MacroRecorder()
        layout.addWidget(recorder)
        shortcut = QShortcut(QKeySequence("Ctrl+K"), window)
        triggered = []
        shortcut.activated.connect(lambda: triggered.append(True))
        window.show()
        self.app.processEvents()
        try:
            recorder.click()
            QTest.keyClick(recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
            for key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Escape,
                        Qt.Key.Key_Tab, Qt.Key.Key_Left, Qt.Key.Key_F1,
                        Qt.Key.Key_CapsLock, Qt.Key.Key_VolumeUp):
                QTest.keyClick(recorder, key)
                self.assertTrue(recorder.recording())
            before = recorder.events()
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                self.app.sendEvent(recorder, QKeyEvent(
                    kind, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
                    " ", True,
                ))
            self.assertEqual(recorder.events(), before)
            self.assertFalse(triggered)
            self.assertEqual(
                [(e["code"], e["down"]) for e in before[:4]],
                [("KEY_LEFTCTRL", True), ("KEY_K", True),
                 ("KEY_K", False), ("KEY_LEFTCTRL", False)],
            )
            for code in ("KEY_SPACE", "KEY_ENTER", "KEY_ESC", "KEY_TAB",
                         "KEY_LEFT", "KEY_F1", "KEY_CAPSLOCK", "KEY_VOLUMEUP"):
                self.assertEqual([e["down"] for e in before if e["code"] == code],
                                 [True, False])
            recorder.click()
            QTest.keyClick(recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(triggered, [True])
        finally:
            recorder.releaseKeyboard()
            window.close()

    def test_macro_stop_releases_held_keys_and_hide_cancels(self) -> None:
        recorder = MacroRecorder()
        recorder.show()
        self.app.processEvents()
        recorded = []
        recorder.recorded.connect(recorded.append)
        recorder.click()
        QTest.keyPress(recorder, Qt.Key.Key_Control)
        QTest.keyPress(recorder, Qt.Key.Key_A)
        recorder.click()
        self.assertEqual(
            [(e["code"], e["down"]) for e in recorded[-1]],
            [("KEY_LEFTCTRL", True), ("KEY_A", True),
             ("KEY_A", False), ("KEY_LEFTCTRL", False)],
        )
        recorder.click()
        QTest.keyPress(recorder, Qt.Key.Key_Alt)
        recorder.hide()
        self.assertFalse(recorder.recording())
        self.assertEqual(recorder.events(), recorded[-1])
        self.assertEqual(len(recorded), 1)

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
        inspector._captured(["KEY_LEFTCTRL", "KEY_K"])
        self.assertEqual(inspector.action_combo.currentData(), "shortcut")
        self.assertEqual(inspector._draft["macros"]["G4"],
                         shortcut_events(["KEY_LEFTCTRL", "KEY_K"]))
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

    def test_preset_replaces_old_thumb_macros_and_resets_mouse_mode(self) -> None:
        inspector = ProfileInspector()
        inspector.set_profile({
            "id": "custom", "slot": 3, "name": "Custom", "color": [1, 2, 3],
            "backlight_intensity": 45, "stick_mode": "mouse",
            "bindings": {"G2": "KEY_1", "LEFT": "BTN_LEFT"},
            "macros": {"LEFT": shortcut_events(["KEY_A"]),
                       "G9": shortcut_events(["KEY_B"])},
            "lcd_image": None, "lcd_gif": None,
        })
        inspector.preset_combo.setCurrentIndex(inspector.preset_combo.findData("The Ascent"))
        inspector._apply_preset()
        draft = inspector._draft
        self.assertEqual(draft["bindings"]["LEFT"], "KEY_C")
        self.assertEqual(draft["macros"], {})
        self.assertNotIn("G2", draft["bindings"])
        self.assertNotIn("G9", draft["bindings"])
        self.assertEqual(draft["stick_mode"], "keys")
        self.assertEqual(draft["slot"], 3)
        self.assertEqual(draft["backlight_intensity"], 45)
        inspector.revert()
        self.assertEqual(inspector._draft["stick_mode"], "mouse")
        self.assertIn("LEFT", inspector._draft["macros"])

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


if __name__ == "__main__":
    unittest.main()
