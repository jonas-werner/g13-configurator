"""Live-rendered visualization of the G13.

Draws a solid color fill for each backlit region, then the device photo
(the bundled gui/assets/g13-stylized-transparent.png) on top -- that image has the
G1-G22 labels and the LCD screen cut to transparent, so the fill shines
through as glowing text/screen exactly like the real hardware (confirmed
against a reference photo), with no glow effect or hand-drawn text
needed. A bright ring on whatever's currently held makes presses easy to
spot. Geometry comes from device_layout.py (data); this widget is a pure
drawing layer -- no device I/O or profile logic lives here.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from g13.gui import theme
from g13.gui.device_layout import (
    ASSET_PATH,
    BACKLIT_BY_PROFILE,
    BD,
    DOWN,
    IMAGE_H,
    IMAGE_W,
    G_KEYS,
    JOYSTICK_CENTER,
    JOYSTICK_KEY_ID,
    JOYSTICK_RADIUS,
    KEYS,
    LCD,
    L_KEYS,
    LEFT,
    LIGHT_BUTTON_KEYS,
)
from g13.hardware.lcd import load_frames, text_frame
from g13.system_stats import SystemStats, clock_frame, stats_frame

_STICK_REST = 128  # raw byte value at rest, per g13/hardware/report.py
_FILL_MARGIN = 10.0  # generous on purpose: same color on every G-key, so
# overlap between neighbors is invisible, and the opaque plastic between
# keycaps clips any excess -- cheap insurance against calibration drift.


def _expanded_rect(key) -> QRectF:
    return QRectF(key.x - _FILL_MARGIN, key.y - _FILL_MARGIN, key.w + 2 * _FILL_MARGIN, key.h + 2 * _FILL_MARGIN)


class G13View(QWidget):
    """Live visualization: set_state() updates it, paintEvent draws it."""

    key_selected = Signal(str)
    lcd_mode_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 320)
        self._color = QColor(60, 70, 100)
        self._preview_color: QColor | None = None
        self._intensity = 100
        self._preview_intensity: int | None = None
        self._keys: frozenset[str] = frozenset()
        self._selected_key: str | None = None
        self._stick = (_STICK_REST, _STICK_REST)
        self._pixmap = QPixmap(str(ASSET_PATH))
        self._lcd_current: Image.Image | None = None
        self._lcd_splash: Image.Image | None = None
        self._lcd_animation: list[tuple[Image.Image, int]] = []
        self._lcd_frame_index = 0
        self._lcd_showing_splash = False
        self._lcd_mode = "splash"
        self._stats = SystemStats()
        self._lcd_render_cache: QImage | None = None
        self._lcd_timer = QTimer(self)
        self._lcd_timer.setSingleShot(True)
        self._lcd_timer.timeout.connect(self._advance_lcd)

    def set_state(
        self,
        color: tuple[int, int, int],
        keys: frozenset[str],
        stick: tuple[int, int] = (_STICK_REST, _STICK_REST),
        intensity: int = 100,
    ) -> None:
        new_color = QColor(*color) if any(color) else QColor(60, 70, 100)
        if new_color != self._color or intensity != self._intensity:
            self._color = new_color
            self._intensity = intensity
            self._lcd_render_cache = None
        self._keys = keys
        self._stick = stick
        self.update()

    def set_selected_key(self, key_id: str | None) -> None:
        self._selected_key = key_id
        self.update()

    def set_preview_color(self, color: tuple[int, int, int] | None) -> None:
        new_color = QColor(*color) if color is not None else None
        if new_color != self._preview_color:
            self._preview_color = new_color
            self._lcd_render_cache = None
        self.update()

    def set_preview_intensity(self, intensity: int | None) -> None:
        if intensity != self._preview_intensity:
            self._preview_intensity = intensity
            self._lcd_render_cache = None
        self.update()

    def _effective_color(self) -> QColor:
        color = self._preview_color or self._color
        intensity = (
            self._preview_intensity
            if self._preview_intensity is not None
            else self._intensity
        )
        factor = intensity / 100
        return QColor(
            round(color.red() * factor),
            round(color.green() * factor),
            round(color.blue() * factor),
        )

    def set_lcd_content(
        self, profile_name: str, image_path: str | None, gif_path: str | None
    ) -> None:
        self._lcd_timer.stop()
        self._lcd_animation = []
        self._lcd_frame_index = 0
        try:
            if image_path:
                splash = load_frames(Path(image_path))[0][0]
            else:
                splash = text_frame(profile_name)
            if gif_path:
                self._lcd_animation = load_frames(Path(gif_path))
        except (OSError, ValueError):
            splash = text_frame(profile_name)
            self._lcd_animation = []

        self._lcd_splash = splash
        self._lcd_current = splash
        self._lcd_mode = "splash"
        self._lcd_showing_splash = bool(self._lcd_animation)
        self._lcd_render_cache = None
        if self._lcd_animation:
            self._lcd_timer.start(2000)
        self.update()

    def set_lcd_mode(self, mode: str) -> None:
        if mode == self._lcd_mode:
            return
        self._lcd_timer.stop()
        self._lcd_mode = mode
        self._lcd_showing_splash = False
        self._lcd_frame_index = 0
        if mode == "clock":
            self._lcd_current = clock_frame()
            self._lcd_timer.start(1000)
        elif mode == "stats":
            self._lcd_current = stats_frame(self._stats.sample())
            self._lcd_timer.start(1000)
        elif mode == "animation" and self._lcd_animation:
            self._lcd_current = self._lcd_animation[0][0]
            self._lcd_timer.start(max(20, self._lcd_animation[0][1] or 200))
        else:
            self._lcd_current = self._lcd_splash
        self._lcd_render_cache = None
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(IMAGE_W // 2, IMAGE_H // 2)

    def _is_active(self, key_id: str) -> bool:
        if key_id == "LIGHT":
            return bool(self._keys & LIGHT_BUTTON_KEYS)
        return key_id in self._keys

    def paintEvent(self, event) -> None:  # noqa: ARG002 (Qt event arg required)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        scale, offset_x, offset_y = self._transform()
        painter.translate(offset_x, offset_y)
        painter.scale(scale, scale)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._effective_color())
        painter.drawRoundedRect(QRectF(LCD.x, LCD.y, LCD.w, LCD.h), 3, 3)
        lcd_image = self._render_lcd_image()
        if lcd_image is not None:
            painter.drawImage(QRectF(LCD.x, LCD.y, LCD.w, LCD.h), lcd_image)
        for key in KEYS:
            if key.id in BACKLIT_BY_PROFILE:
                rect = _expanded_rect(key)
                if key.shape == "ellipse":
                    painter.drawEllipse(rect)
                else:
                    painter.drawRoundedRect(rect, 3, 3)

        painter.drawPixmap(0, 0, self._pixmap)

        self._draw_selection(painter)

        for key in KEYS:
            if self._is_active(key.id):
                self._draw_press_ring(painter, key)
        self._draw_joystick(painter)

    def _advance_lcd(self) -> None:
        if self._lcd_mode == "clock":
            self._lcd_current = clock_frame()
            self._lcd_render_cache = None
            self._lcd_timer.start(1000)
            self.update()
            return
        if self._lcd_mode == "stats":
            self._lcd_current = stats_frame(self._stats.sample())
            self._lcd_render_cache = None
            self._lcd_timer.start(1000)
            self.update()
            return
        if not self._lcd_animation:
            return
        if self._lcd_showing_splash:
            self._lcd_showing_splash = False
            self._lcd_mode = "animation"
            self._lcd_frame_index = 0
        else:
            self._lcd_frame_index = (self._lcd_frame_index + 1) % len(self._lcd_animation)
        self._lcd_current = self._lcd_animation[self._lcd_frame_index][0]
        self._lcd_render_cache = None
        duration = self._lcd_animation[self._lcd_frame_index][1] or 200
        self._lcd_timer.start(max(20, duration))
        self.update()

    def _render_lcd_image(self) -> QImage | None:
        if self._lcd_current is None:
            return None
        if self._lcd_render_cache is not None:
            return self._lcd_render_cache

        color = self._effective_color()
        mono = self._lcd_current.convert("1")
        rendered = Image.new("RGBA", mono.size, (1, 3, 4, 255))
        ink = Image.new("RGBA", mono.size, (color.red(), color.green(), color.blue(), 255))
        rendered.paste(ink, mask=mono)
        data = rendered.tobytes("raw", "RGBA")
        self._lcd_render_cache = QImage(
            data,
            rendered.width,
            rendered.height,
            rendered.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        return self._lcd_render_cache

    def _draw_selection(self, painter: QPainter) -> None:
        if self._selected_key is None:
            return
        pen = QPen(QColor(theme.ACCENT_DIM), 4)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        selected = next(
            (key for key in (*G_KEYS, LEFT, DOWN) if key.id == self._selected_key),
            None,
        )
        if selected is not None:
            painter.drawRoundedRect(QRectF(selected.x, selected.y, selected.w, selected.h), 6, 6)
            return

        cx, cy = JOYSTICK_CENTER
        if self._selected_key == JOYSTICK_KEY_ID:
            radius = JOYSTICK_RADIUS * 0.45
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
            return

        start_angles = {
            "STICK_RIGHT": -45,
            "STICK_UP": 45,
            "STICK_LEFT": 135,
            "STICK_DOWN": 225,
        }
        if self._selected_key in start_angles:
            radius = JOYSTICK_RADIUS * 0.9
            painter.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                start_angles[self._selected_key] * 16,
                90 * 16,
            )

    def _transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / IMAGE_W, self.height() / IMAGE_H)
        return (
            scale,
            (self.width() - IMAGE_W * scale) / 2,
            (self.height() - IMAGE_H * scale) / 2,
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            scale, offset_x, offset_y = self._transform()
            point = event.position()
            image_x = (point.x() - offset_x) / scale
            image_y = (point.y() - offset_y) / scale
            for index, key in enumerate(L_KEYS):
                if QRectF(key.x, key.y, key.w, key.h).contains(image_x, image_y):
                    self.lcd_mode_requested.emit(("splash", "animation", "clock", "stats")[index])
                    event.accept()
                    return
            bd_cx, bd_cy = BD.x + BD.w / 2, BD.y + BD.h / 2
            if (
                ((image_x - bd_cx) / (BD.w / 2)) ** 2
                + ((image_y - bd_cy) / (BD.h / 2)) ** 2
                <= 1
            ):
                self.lcd_mode_requested.emit("cycle")
                event.accept()
                return
            for key in (*G_KEYS, LEFT, DOWN):
                if QRectF(key.x, key.y, key.w, key.h).contains(image_x, image_y):
                    self.set_selected_key(key.id)
                    self.key_selected.emit(key.id)
                    event.accept()
                    return
            cx, cy = JOYSTICK_CENTER
            dx, dy = image_x - cx, image_y - cy
            distance = math.hypot(dx, dy)
            if distance <= JOYSTICK_RADIUS:
                if distance <= JOYSTICK_RADIUS * 0.45:
                    control = JOYSTICK_KEY_ID
                elif abs(dx) >= abs(dy):
                    control = "STICK_RIGHT" if dx > 0 else "STICK_LEFT"
                else:
                    control = "STICK_DOWN" if dy > 0 else "STICK_UP"
                self.set_selected_key(control)
                self.key_selected.emit(control)
                event.accept()
                return
        super().mousePressEvent(event)

    def _draw_press_ring(self, painter: QPainter, key) -> None:
        rect = QRectF(key.x, key.y, key.w, key.h)
        painter.setPen(QPen(QColor(theme.ACCENT_HI), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if key.shape == "ellipse":
            painter.drawEllipse(rect)
        else:
            painter.drawRoundedRect(rect, 4, 4)

    def _draw_joystick(self, painter: QPainter) -> None:
        cx, cy = JOYSTICK_CENTER
        if self._is_active(JOYSTICK_KEY_ID):
            ring_rect = QRectF(cx - JOYSTICK_RADIUS, cy - JOYSTICK_RADIUS, JOYSTICK_RADIUS * 2, JOYSTICK_RADIUS * 2)
            painter.setPen(QPen(QColor(theme.ACCENT_HI), 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ring_rect)

        for direction, start_angle in (
            ("STICK_RIGHT", -45),
            ("STICK_UP", 45),
            ("STICK_LEFT", 135),
            ("STICK_DOWN", 225),
        ):
            if self._is_active(direction):
                radius = JOYSTICK_RADIUS * 0.9
                painter.setPen(QPen(QColor(theme.ACCENT_HI), 4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(
                    QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                    start_angle * 16,
                    90 * 16,
                )

        for key in (LEFT, DOWN):
            if self._is_active(key.id):
                rect = QRectF(key.x, key.y, key.w, key.h)
                painter.setPen(QPen(QColor(theme.ACCENT_HI), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, 6, 6)
