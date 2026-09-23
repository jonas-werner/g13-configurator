"""Profile metadata and G-key binding editor widgets."""

from __future__ import annotations

import copy
import time
from pathlib import Path

from PIL import Image as PillowImage
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMovie, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from g13.gui import theme
from g13.presets import GAME_PRESETS, PRESETS_BY_NAME


_SPECIAL_KEYS = {
    Qt.Key.Key_Space: "KEY_SPACE",
    Qt.Key.Key_Return: "KEY_ENTER",
    Qt.Key.Key_Enter: "KEY_ENTER",
    Qt.Key.Key_Escape: "KEY_ESC",
    Qt.Key.Key_Tab: "KEY_TAB",
    Qt.Key.Key_Backspace: "KEY_BACKSPACE",
    Qt.Key.Key_Delete: "KEY_DELETE",
    Qt.Key.Key_Insert: "KEY_INSERT",
    Qt.Key.Key_Home: "KEY_HOME",
    Qt.Key.Key_End: "KEY_END",
    Qt.Key.Key_PageUp: "KEY_PAGEUP",
    Qt.Key.Key_PageDown: "KEY_PAGEDOWN",
    Qt.Key.Key_Left: "KEY_LEFT",
    Qt.Key.Key_Right: "KEY_RIGHT",
    Qt.Key.Key_Up: "KEY_UP",
    Qt.Key.Key_Down: "KEY_DOWN",
    Qt.Key.Key_Minus: "KEY_MINUS",
    Qt.Key.Key_Equal: "KEY_EQUAL",
    Qt.Key.Key_BracketLeft: "KEY_LEFTBRACE",
    Qt.Key.Key_BracketRight: "KEY_RIGHTBRACE",
    Qt.Key.Key_Backslash: "KEY_BACKSLASH",
    Qt.Key.Key_Semicolon: "KEY_SEMICOLON",
    Qt.Key.Key_Apostrophe: "KEY_APOSTROPHE",
    Qt.Key.Key_Comma: "KEY_COMMA",
    Qt.Key.Key_Period: "KEY_DOT",
    Qt.Key.Key_Slash: "KEY_SLASH",
    Qt.Key.Key_QuoteLeft: "KEY_GRAVE",
}
_MODIFIER_KEYS = {
    Qt.Key.Key_Control: "KEY_LEFTCTRL",
    Qt.Key.Key_Shift: "KEY_LEFTSHIFT",
    Qt.Key.Key_Alt: "KEY_LEFTALT",
    Qt.Key.Key_Meta: "KEY_LEFTMETA",
}


def event_key_name(event: QKeyEvent) -> str | None:
    """Translate common Qt keyboard keys to Linux evdev names."""
    key = event.key()
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return f"KEY_{chr(ord('A') + key - Qt.Key.Key_A)}"
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return f"KEY_{chr(ord('0') + key - Qt.Key.Key_0)}"
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return f"KEY_F{key - Qt.Key.Key_F1 + 1}"
    return _MODIFIER_KEYS.get(key) or _SPECIAL_KEYS.get(key)


def shortcut_key_names(event: QKeyEvent) -> list[str]:
    base = event_key_name(event)
    if base is None:
        return []
    names: list[str] = []
    modifiers = event.modifiers()
    for flag, name in (
        (Qt.KeyboardModifier.ControlModifier, "KEY_LEFTCTRL"),
        (Qt.KeyboardModifier.AltModifier, "KEY_LEFTALT"),
        (Qt.KeyboardModifier.ShiftModifier, "KEY_LEFTSHIFT"),
        (Qt.KeyboardModifier.MetaModifier, "KEY_LEFTMETA"),
    ):
        if modifiers & flag and name != base:
            names.append(name)
    names.append(base)
    return names


def shortcut_events(names: list[str]) -> list[dict]:
    return [
        *({"code": name, "down": True, "delay_ms": 0} for name in names),
        *({"code": name, "down": False, "delay_ms": 0} for name in reversed(names)),
    ]


def friendly_key(name: str) -> str:
    if name.startswith("BTN_"):
        return f"Mouse {name.removeprefix('BTN_').title()}"
    return name.removeprefix("KEY_").replace("LEFT", "Left ").title()


def friendly_control(name: str) -> str:
    return {
        "LEFT": "Left joystick button",
        "DOWN": "Lower joystick button",
        "TOP": "Joystick press",
        "STICK_UP": "Joystick up",
        "STICK_DOWN": "Joystick down",
        "STICK_LEFT": "Joystick left",
        "STICK_RIGHT": "Joystick right",
    }.get(name, name)


class KeyCaptureButton(QPushButton):
    captured = Signal(list)


    def __init__(self) -> None:
        super().__init__("Capture key")
        self._capturing = False
        self.clicked.connect(self._begin)

    def focusNextPrevChild(self, next_child: bool) -> bool:
        if self._capturing:
            # Prevent the Tab key from shifting focus while recording
            return False 
        return super().focusNextPrevChild(next_child)

    def _begin(self) -> None:
        self._capturing = True
        self.setText("Press a key or shortcut…")
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._capturing and not event.isAutoRepeat():
            names = shortcut_key_names(event)
            if names:
                self._capturing = False
                self.releaseKeyboard()
                self.setText("Capture key")
                self.captured.emit(names)
                event.accept()
                return
        super().keyPressEvent(event)


class MacroRecorder(QPushButton):
    recorded = Signal(list)

    def __init__(self) -> None:
        super().__init__("Record sequence")
        self.setCheckable(True)
        self._events: list[dict] = []
        self._last_time: float | None = None
        self.clicked.connect(self._toggle)

    def focusNextPrevChild(self, next_child: bool) -> bool:
        if self.isChecked():
            # Prevent Tab/Shift+Tab from shifting focus while recording a macro
            return False 
        return super().focusNextPrevChild(next_child)

    def set_events(self, events: list[dict]) -> None:
        self._events = copy.deepcopy(events)
        self._update_text()

    def events(self) -> list[dict]:
        return copy.deepcopy(self._events)

    def _toggle(self, checked: bool) -> None:
        if checked:
            self._events = []
            self._last_time = None
            self.setText("Recording… click to stop")
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
            self._update_text()
            self.recorded.emit(self.events())

    def _update_text(self) -> None:
        if self._events:
            self.setText(f"Re-record sequence ({len(self._events)} events)")
        else:
            self.setText("Record sequence")

    def _record_event(self, event: QKeyEvent, down: bool) -> bool:
        if not self.isChecked() or event.isAutoRepeat():
            return False
        code = event_key_name(event)
        if code is None:
            return False
        now = time.monotonic()
        delay = 0 if self._last_time is None else round((now - self._last_time) * 1000)
        self._last_time = now
        self._events.append({"code": code, "down": down, "delay_ms": min(delay, 600_000)})
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._record_event(event, True):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._record_event(event, False):
            event.accept()
            return
        super().keyReleaseEvent(event)


class ProfileInspector(QFrame):
    save_requested = Signal(dict)
    preview_color = Signal(object)
    preview_intensity = Signal(object)
    lcd_content_changed = Signal(str, object, object)
    slot_assignment_requested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setFixedWidth(280)
        self._profile: dict | None = None
        self._draft: dict | None = None
        self._selected_key: str | None = None
        self._loading = False
        self._saved_confirmation = False

        layout = QVBoxLayout(self)
        title = QLabel("PROFILE EDITOR")
        title.setObjectName("SectionLabel")
        layout.addWidget(title)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._name_changed)
        form.addRow("Name", self.name_edit)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._choose_color)
        form.addRow("LED color", self.color_button)
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(0, 100)
        self.intensity_slider.setSingleStep(5)
        self.intensity_slider.setPageStep(10)
        self.intensity_slider.valueChanged.connect(self._intensity_changed)
        self.intensity_value = QLabel("100%")
        self.intensity_value.setObjectName("Muted")
        self.intensity_value.setFixedWidth(38)
        self.intensity_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        intensity_row = QHBoxLayout()
        intensity_row.setContentsMargins(0, 0, 0, 0)
        intensity_row.addWidget(self.intensity_slider, 1)
        intensity_row.addWidget(self.intensity_value)
        form.addRow("Intensity", intensity_row)
        self.stick_mode_combo = QComboBox()
        self.stick_mode_combo.addItem("Directional keys", "keys")
        self.stick_mode_combo.addItem("Mouse pointer", "mouse")
        self.stick_mode_combo.currentIndexChanged.connect(self._stick_mode_changed)
        form.addRow("Joystick", self.stick_mode_combo)
        self.slot_combo = QComboBox()
        self.slot_combo.addItem("Unassigned", None)
        self.slot_combo.addItem("M1", 1)
        self.slot_combo.addItem("M2", 2)
        self.slot_combo.addItem("M3", 3)
        self.slot_combo.currentIndexChanged.connect(self._slot_changed)
        form.addRow("M-key", self.slot_combo)
        layout.addLayout(form)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Starter template…", None)
        for preset in GAME_PRESETS:
            self.preset_combo.addItem(preset.name, preset.name)
        self.preset_button = QPushButton("Apply")
        self.preset_button.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.preset_button)
        layout.addLayout(preset_row)

        self.mr_status = QLabel()
        self.mr_status.setObjectName("StatusPill")
        self.mr_status.hide()
        layout.addWidget(self.mr_status)

        layout.addSpacing(8)
        lcd_title = QLabel("LCD CONTENT")
        lcd_title.setObjectName("SectionLabel")
        layout.addWidget(lcd_title)

        self.image_path_label = QLabel("No splash image")
        self.image_path_label.setObjectName("Muted")
        self.image_path_label.setToolTip("Shown for two seconds when this profile is selected")
        layout.addWidget(self.image_path_label)
        image_buttons = QHBoxLayout()
        choose_image = QPushButton("Choose PNG…")
        choose_image.clicked.connect(lambda: self._choose_media("lcd_image"))
        clear_image = QPushButton("Clear")
        clear_image.clicked.connect(lambda: self._clear_media("lcd_image"))
        image_buttons.addWidget(choose_image)
        image_buttons.addWidget(clear_image)
        layout.addLayout(image_buttons)
        self.image_preview = QLabel()
        self.image_preview.setObjectName("LcdPreview")
        self.image_preview.setFixedSize(240, 65)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_preview)

        self.gif_path_label = QLabel("No animation")
        self.gif_path_label.setObjectName("Muted")
        self.gif_path_label.setToolTip("Loops after the splash image")
        layout.addWidget(self.gif_path_label)
        gif_buttons = QHBoxLayout()
        choose_gif = QPushButton("Choose GIF…")
        choose_gif.clicked.connect(lambda: self._choose_media("lcd_gif"))
        clear_gif = QPushButton("Clear")
        clear_gif.clicked.connect(lambda: self._clear_media("lcd_gif"))
        gif_buttons.addWidget(choose_gif)
        gif_buttons.addWidget(clear_gif)
        layout.addLayout(gif_buttons)
        self.gif_preview = QLabel()
        self.gif_preview.setObjectName("LcdPreview")
        self.gif_preview.setFixedSize(240, 65)
        self.gif_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.gif_preview)
        self._gif_movie: QMovie | None = None

        layout.addSpacing(12)
        self.key_title = QLabel("Select a G-key on the device")
        self.key_title.setObjectName("InspectorKey")
        layout.addWidget(self.key_title)

        self.action_combo = QComboBox()
        self.action_combo.addItem("Unassigned", "none")
        self.action_combo.addItem("Single keystroke", "single")
        self.action_combo.addItem("Shortcut", "shortcut")
        self.action_combo.addItem("Macro sequence", "macro")
        self.action_combo.addItem("Mouse button", "mouse_button")
        self.action_combo.currentIndexChanged.connect(self._action_changed)
        self.action_combo.setEnabled(False)
        layout.addWidget(self.action_combo)

        self.capture_button = KeyCaptureButton()
        self.capture_button.captured.connect(self._captured)
        self.capture_button.hide()
        layout.addWidget(self.capture_button)

        self.macro_recorder = MacroRecorder()
        self.macro_recorder.recorded.connect(self._macro_recorded)
        self.macro_recorder.hide()
        layout.addWidget(self.macro_recorder)

        self.mouse_button_combo = QComboBox()
        for label, code in (
            ("Left click", "BTN_LEFT"),
            ("Right click", "BTN_RIGHT"),
            ("Middle click", "BTN_MIDDLE"),
            ("Back button", "BTN_SIDE"),
            ("Forward button", "BTN_EXTRA"),
        ):
            self.mouse_button_combo.addItem(label, code)
        self.mouse_button_combo.currentIndexChanged.connect(self._mouse_button_changed)
        self.mouse_button_combo.hide()
        layout.addWidget(self.mouse_button_combo)

        self.assignment = QLabel("No key selected")
        self.assignment.setWordWrap(True)
        self.assignment.setObjectName("Muted")
        layout.addWidget(self.assignment)
        layout.addStretch(1)

        self.status = QLabel("Load a profile to begin")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(18)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(self.revert)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.revert_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        self._update_dirty_state()

    @property
    def is_dirty(self) -> bool:
        return self._profile is not None and self._draft != self._profile

    @property
    def slot(self) -> int | None:
        return self._draft.get("slot") if self._draft else None

    def set_profile(self, profile: dict, *, show_saved: bool = False) -> None:
        self._profile = copy.deepcopy(profile)
        self._draft = copy.deepcopy(profile)
        self._saved_confirmation = show_saved
        self._loading = True
        self.name_edit.setText(profile["name"])
        self._set_color_button(tuple(profile["color"]))
        intensity = profile.get("backlight_intensity", 100)
        self.intensity_slider.setValue(intensity)
        self.intensity_value.setText(f"{intensity}%")
        self.stick_mode_combo.setCurrentIndex(
            self.stick_mode_combo.findData(profile.get("stick_mode", "keys"))
        )
        self.slot_combo.setCurrentIndex(self.slot_combo.findData(profile.get("slot")))
        self.preset_combo.setCurrentIndex(0)
        self._set_media_widgets()
        self._loading = False
        self._load_selected_action()
        self.preview_color.emit(None)
        self.preview_intensity.emit(None)
        self._emit_lcd_content()
        self._update_dirty_state()

    def select_key(self, key_id: str) -> None:
        self._selected_key = key_id
        self.key_title.setText(friendly_control(key_id))
        self.action_combo.setEnabled(self._draft is not None)
        self._load_selected_action()

    def set_mr_state(self, state: str, target: str | None) -> None:
        if state == "idle":
            self.mr_status.hide()
            return
        message = "MR armed: select a G-key" if state == "armed" else f"Recording macro for {target or 'G-key'}"
        self.mr_status.setText(message)
        self.mr_status.show()

    def update_slot(self, slot: int | None) -> None:
        if self._profile is None or self._draft is None:
            return
        self._loading = True
        self._profile["slot"] = slot
        self._draft["slot"] = slot
        self.slot_combo.setCurrentIndex(self.slot_combo.findData(slot))
        self._loading = False
        self._update_dirty_state()

    def revert(self) -> None:
        if self._profile is not None:
            self.set_profile(self._profile)

    def _load_selected_action(self) -> None:
        if self._draft is None or self._selected_key is None:
            return
        key = self._selected_key
        self._loading = True
        if key in self._draft.get("macros", {}):
            mode = "macro"
            events = self._draft["macros"][key]
            self.macro_recorder.set_events(events)
            self.assignment.setText(f"Macro: {len(events)} events")
        elif key in self._draft.get("bindings", {}):
            binding = self._draft["bindings"][key]
            mode = "mouse_button" if binding.startswith("BTN_") else "single"
            self.assignment.setText(friendly_key(binding))
            if mode == "mouse_button":
                index = self.mouse_button_combo.findData(binding)
                self.mouse_button_combo.setCurrentIndex(max(0, index))
        else:
            mode = "none"
            self.assignment.setText("Unassigned")
        self.action_combo.setCurrentIndex(self.action_combo.findData(mode))
        self._loading = False
        self._update_action_controls()

    def _action_changed(self) -> None:
        self._update_action_controls()
        if self._loading or self._draft is None or self._selected_key is None:
            return
        mode = self.action_combo.currentData()
        self._draft.setdefault("bindings", {}).pop(self._selected_key, None)
        self._draft.setdefault("macros", {}).pop(self._selected_key, None)
        if mode == "none":
            self.assignment.setText("Unassigned")
        elif mode == "macro":
            self.macro_recorder.set_events([])
            self.assignment.setText("Record a sequence")
        elif mode == "mouse_button":
            code = self.mouse_button_combo.currentData()
            self._draft["bindings"][self._selected_key] = code
            self.assignment.setText(friendly_key(code))
        else:
            self.assignment.setText("Capture an assignment")
        self._update_dirty_state()

    def _update_action_controls(self) -> None:
        mode = self.action_combo.currentData()
        self.capture_button.setVisible(mode in {"single", "shortcut"})
        self.macro_recorder.setVisible(mode == "macro")
        self.mouse_button_combo.setVisible(mode == "mouse_button")

    def _captured(self, names: list[str]) -> None:
        if self._draft is None or self._selected_key is None:
            return
        mode = self.action_combo.currentData()
        key = self._selected_key
        self._draft.setdefault("bindings", {}).pop(key, None)
        self._draft.setdefault("macros", {}).pop(key, None)
        if mode == "single":
            code = names[-1]
            self._draft["bindings"][key] = code
            self.assignment.setText(friendly_key(code))
        else:
            events = shortcut_events(names)
            self._draft["macros"][key] = events
            self.assignment.setText(" + ".join(friendly_key(name) for name in names))
        self._update_dirty_state()

    def _macro_recorded(self, events: list[dict]) -> None:
        if self._draft is None or self._selected_key is None or not events:
            return
        key = self._selected_key
        self._draft.setdefault("bindings", {}).pop(key, None)
        self._draft.setdefault("macros", {})[key] = events
        self.assignment.setText(f"Macro: {len(events)} events")
        self._update_dirty_state()

    def _mouse_button_changed(self) -> None:
        if (
            self._loading
            or self._draft is None
            or self._selected_key is None
            or self.action_combo.currentData() != "mouse_button"
        ):
            return
        code = self.mouse_button_combo.currentData()
        self._draft.setdefault("macros", {}).pop(self._selected_key, None)
        self._draft.setdefault("bindings", {})[self._selected_key] = code
        self.assignment.setText(friendly_key(code))
        self._update_dirty_state()

    def _stick_mode_changed(self) -> None:
        if not self._loading and self._draft is not None:
            self._draft["stick_mode"] = self.stick_mode_combo.currentData()
            self._update_dirty_state()

    def _intensity_changed(self, value: int) -> None:
        self.intensity_value.setText(f"{value}%")
        if not self._loading and self._draft is not None:
            self._draft["backlight_intensity"] = value
            self.preview_intensity.emit(value)
            self._update_dirty_state()

    def _slot_changed(self) -> None:
        if not self._loading and self._draft is not None:
            self.slot_assignment_requested.emit(
                self._draft["id"], self.slot_combo.currentData()
            )

    def _name_changed(self, value: str) -> None:
        if not self._loading and self._draft is not None:
            self._draft["name"] = value
            self._emit_lcd_content()
            self._update_dirty_state()

    def _apply_preset(self) -> None:
        if self._draft is None:
            return
        preset_name = self.preset_combo.currentData()
        if preset_name is None:
            return
        preset = PRESETS_BY_NAME[preset_name]
        auxiliary_bindings = {
            key: value
            for key, value in self._draft.get("bindings", {}).items()
            if not (key.startswith("G") and key[1:].isdigit())
        }
        auxiliary_macros = {
            key: value
            for key, value in self._draft.get("macros", {}).items()
            if not (key.startswith("G") and key[1:].isdigit())
        }
        self._draft["name"] = preset.name
        self._draft["color"] = list(preset.color)
        self._draft["bindings"] = {**auxiliary_bindings, **copy.deepcopy(preset.bindings)}
        self._draft["macros"] = {**auxiliary_macros, **copy.deepcopy(preset.macros)}
        self.name_edit.setText(preset.name)
        self._set_color_button(preset.color)
        self.preview_color.emit(preset.color)
        self._load_selected_action()
        self._emit_lcd_content()
        self._update_dirty_state()

    def _choose_media(self, field: str) -> None:
        if self._draft is None:
            return
        existing = self._draft.get(field)
        initial = str(Path(existing).parent) if existing else str(
            Path(__file__).resolve().parents[2] / "assets" / "game-art"
        )
        file_filter = "PNG images (*.png)" if field == "lcd_image" else "Animated GIFs (*.gif)"
        selected, _ = QFileDialog.getOpenFileName(self, "Choose LCD media", initial, file_filter)
        if not selected:
            return
        error = self._media_error(Path(selected), animated=field == "lcd_gif")
        if error:
            self.status.setText(error)
            self.status.setStyleSheet(f"color: {theme.DANGER};")
            return
        self._draft[field] = str(Path(selected).resolve())
        self._set_media_widgets()
        self._emit_lcd_content()
        self._update_dirty_state()

    @staticmethod
    def _media_error(path: Path, *, animated: bool) -> str | None:
        try:
            with PillowImage.open(path) as image:
                if image.size != (160, 43):
                    return f"LCD media must be exactly 160×43; selected {image.width}×{image.height}"
                if animated and (image.format != "GIF" or getattr(image, "n_frames", 1) < 2):
                    return "Select an animated GIF with at least two frames"
                if not animated and image.format != "PNG":
                    return "Select a PNG image"
        except OSError:
            return "The selected media file could not be read"
        return None

    def _clear_media(self, field: str) -> None:
        if self._draft is None:
            return
        self._draft[field] = None
        self._set_media_widgets()
        self._emit_lcd_content()
        self._update_dirty_state()

    def _set_media_widgets(self) -> None:
        if self._draft is None:
            return
        image_path = self._draft.get("lcd_image")
        if image_path:
            self.image_path_label.setText(Path(image_path).name)
            pixmap = QPixmap(image_path)
            self.image_preview.setPixmap(
                pixmap.scaled(
                    self.image_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )
        else:
            self.image_path_label.setText("No splash image")
            self.image_preview.clear()

        if self._gif_movie is not None:
            self._gif_movie.stop()
            self._gif_movie.deleteLater()
            self._gif_movie = None
        gif_path = self._draft.get("lcd_gif")
        if gif_path:
            self.gif_path_label.setText(Path(gif_path).name)
            self._gif_movie = QMovie(gif_path)
            self._gif_movie.setScaledSize(QSize(240, 65))
            self.gif_preview.setMovie(self._gif_movie)
            self._gif_movie.start()
        else:
            self.gif_path_label.setText("No animation")
            self.gif_preview.clear()

    def _emit_lcd_content(self) -> None:
        if self._draft is not None:
            self.lcd_content_changed.emit(
                self._draft.get("name", ""),
                self._draft.get("lcd_image"),
                self._draft.get("lcd_gif"),
            )

    def _choose_color(self) -> None:
        if self._draft is None:
            return
        initial = QColor(*self._draft["color"])
        dialog = QColorDialog(initial, self)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if dialog.exec():
            color = dialog.selectedColor()
            rgb = [color.red(), color.green(), color.blue()]
            self._draft["color"] = rgb
            self._set_color_button(tuple(rgb))
            self.preview_color.emit(tuple(rgb))
            self._update_dirty_state()

    def _set_color_button(self, color: tuple[int, int, int]) -> None:
        r, g, b = color
        self.color_button.setText(f"#{r:02X}{g:02X}{b:02X}")
        self.color_button.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); "
            f"color: {'#111111' if r + g + b > 420 else '#FFFFFF'};"
        )

    def _update_dirty_state(self) -> None:
        dirty = self.is_dirty
        if dirty:
            self._saved_confirmation = False
        valid_name = bool(self._draft and self._draft.get("name", "").strip())
        self.save_button.setEnabled(dirty and valid_name)
        self.revert_button.setEnabled(dirty)
        if self._profile is None:
            self.status.setText("Load a profile to begin")
        elif not valid_name:
            self.status.setText("Profile name cannot be empty")
            self.status.setStyleSheet(f"color: {theme.DANGER};")
        elif dirty:
            self.status.setText("Unsaved changes")
            self.status.setStyleSheet(f"color: {theme.WARNING};")
        elif self._saved_confirmation:
            self.status.setText("Saved")
            self.status.setStyleSheet(f"color: {theme.SUCCESS};")
        else:
            self.status.clear()
            self.status.setStyleSheet(f"color: {theme.TEXT_MUTED};")

    def _save(self) -> None:
        if self._draft is not None and self.is_dirty:
            self.save_requested.emit(copy.deepcopy(self._draft))
