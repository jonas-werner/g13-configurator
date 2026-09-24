from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
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
from g13.gui.mapping_labels import mapping_label
from g13.gui.main import MainWindow


def device_point(view: G13View, x: float, y: float) -> QPoint:
    scale, ox, oy = view._transform()
    return QPoint(round(ox + x * scale), round(oy + y * scale))


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_required_device_image_is_bundled(self) -> None:
        self.assertTrue(ASSET_PATH.is_file())

    def test_mapping_labels_distinguish_chords_sequences_and_unassigned(self) -> None:
        self.assertEqual(mapping_label({}, "G4"), "Not loaded")
        profile = {
            "bindings": {"G1": "KEY_A", "G2": "BTN_RIGHT"},
            "macros": {"G1": shortcut_events(["KEY_LEFTCTRL", "KEY_K"])},
        }
        self.assertEqual(mapping_label(profile, "G1"), "L Ctrl + K")
        self.assertEqual(mapping_label(profile, "G2"), "Mouse 2")
        self.assertEqual(mapping_label(profile, "G3"), "Unassigned")
        profile["macros"]["G1"][1]["delay_ms"] = 20
        self.assertEqual(mapping_label(profile, "G1"), "Macro (4)")
        profile["stick_mode"] = "mouse"
        self.assertEqual(mapping_label(profile, "STICK_UP"), "Pointer")

    def test_live_indicator_does_not_shrink_the_device(self) -> None:
        view = G13View()
        for width, height in ((240, 320), (543, 724), (900, 850)):
            view.resize(width, height)
            scale, ox, oy = view._transform()
            self.assertEqual(scale, min(width / IMAGE_W, height / IMAGE_H))
            self.assertGreaterEqual(oy, 0)
            self.assertGreaterEqual(ox, 0)
            self.assertLessEqual(oy + IMAGE_H * scale, height)
            badge_scale, badge_x, badge_y = view._indicator_transform()
            self.assertEqual(badge_scale, scale)
            self.assertLessEqual(badge_x, ox)
            self.assertGreaterEqual(badge_x, 0)
            self.assertLessEqual(badge_y, oy)
            self.assertGreaterEqual(badge_y, 0)

    def test_reconnect_loads_mappings_after_initial_daemon_failure(self) -> None:
        profile = {"id": "cyberpunk", "name": "Cyberpunk 2077", "slot": 1,
                   "color": [255, 220, 0], "bindings": {"G4": "KEY_W"}, "macros": {}}
        client = MagicMock()
        client.list_profiles.side_effect = [OSError("Daemon starting"), {
            "profiles": [profile], "active_id": "cyberpunk", "active_slot": 1,
        }]
        client.get_profile.return_value = {"profile": profile}
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "gui.ini"), QSettings.Format.IniFormat)
            with patch("g13.gui.main.DaemonClient", return_value=client), \
                 patch("g13.gui.main.StateListener"), \
                 patch("g13.gui.main.QSettings", return_value=settings):
                window = MainWindow()
                try:
                    window._on_connection_changed(True)
                    view = window.keyboard_view
                    self.assertEqual(mapping_label(view._mapping_profile, "G4"), "W")
                    window.mapping_toggle.setChecked(True)
                    self.assertTrue(view._show_mappings)
                    # A failed refresh must not erase a successfully loaded profile.
                    client.get_profile.side_effect = OSError("Temporary failure")
                    window._load_profile("cyberpunk")
                    self.assertEqual(mapping_label(view._mapping_profile, "G4"), "W")
                    self.assertEqual(window.inspector._draft["bindings"]["G4"], "KEY_W")
                finally:
                    window.close()
                self.assertTrue(settings.value("show_mappings", type=bool))

    def test_live_badge_uses_saved_mapping_and_clears_after_release(self) -> None:
        view = G13View()
        view.set_profile({"bindings": {"G4": "KEY_W", "G15": "KEY_LEFTSHIFT"}})
        view.set_mapping_profile({"bindings": {"G4": "KEY_F"}})
        view.set_state((255, 220, 0), frozenset({"G4", "G15"}))
        self.assertEqual(view.live_mapping_text(), "G4: W\nG15: L Shift")
        view.set_state((255, 220, 0), frozenset())
        self.assertIn("G4: W", view.live_mapping_text())
        # A repeated idle state must not extend the release timeout.
        QTest.qWait(500)
        view.set_state((255, 220, 0), frozenset())
        QTest.qWait(500)
        self.assertEqual(view.live_mapping_text(), "")

    def test_live_badge_resets_on_profile_change_and_disconnect(self) -> None:
        view = G13View()
        view.set_profile({"bindings": {"G4": "KEY_W"}})
        view.set_state((1, 2, 3), frozenset({"G4", "M1"}))
        self.assertEqual(view.live_mapping_text(), "G4: W")
        view.set_profile({"bindings": {"G4": "KEY_E"}})
        self.assertEqual(view.live_mapping_text(), "")
        view.set_state((1, 2, 3), frozenset({"G4"}))
        self.assertEqual(view.live_mapping_text(), "G4: E")
        view.clear_live_state()
        self.assertEqual(view.live_mapping_text(), "")
        self.assertFalse(view._keys)

    def test_mapping_toggle_preserves_selection_and_draft_updates(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        inspector = ProfileInspector()
        inspector.mappings_changed.connect(view.set_mapping_profile)
        inspector.set_profile({
            "id": "test", "slot": 1, "name": "Test", "color": [1, 2, 3],
            "bindings": {"G4": "KEY_W"}, "macros": {},
        })
        view.key_selected.connect(inspector.select_key)
        view.set_show_mappings(True)
        key = next(key for key in G_KEYS if key.id == "G4")
        point = device_point(view, key.x + key.w / 2, key.y + key.h / 2)
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(view._selected_key, "G4")
        inspector._captured(["KEY_F"])
        self.assertEqual(mapping_label(view._mapping_profile, "G4"), "F")
        inspector.revert()
        self.assertEqual(mapping_label(view._mapping_profile, "G4"), "W")
        mapped = view.grab().toImage()
        view.set_show_mappings(False)
        self.assertNotEqual(mapped, view.grab().toImage())
        self.assertEqual(view._selected_key, "G4")

    def test_clicking_image_key_selects_g_key(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        view.show()
        selected: list[str] = []
        view.key_selected.connect(selected.append)
        key = next(key for key in G_KEYS if key.id == "G4")
        point = device_point(view, key.x + key.w / 2, key.y + key.h / 2)

        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(selected, ["G4"])

    def test_clicking_joystick_selects_press_and_direction(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        view.show()
        selected: list[str] = []
        view.key_selected.connect(selected.append)

        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=device_point(view, 944, 920))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=device_point(view, 944, 860))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=device_point(view, 944, 980))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=device_point(view, 940, 1070))

        self.assertEqual(selected, ["TOP", "STICK_UP", "STICK_DOWN", "DOWN"])

    def test_lcd_buttons_select_views_and_application_button_cycles(self) -> None:
        view = G13View()
        view.resize(IMAGE_W // 2, IMAGE_H // 2)
        view.show()
        modes: list[str] = []
        view.lcd_mode_requested.connect(modes.append)

        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=device_point(view, 590, 286))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=device_point(view, 280, 280))

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
