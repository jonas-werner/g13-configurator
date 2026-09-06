"""g13-linux GUI: header bar, a sidebar of profile rows (click to
activate), and a large live
visualization of the G13 (backlight color + currently-held keys).

Talks to g13d over its Unix socket (see g13/daemon/protocol.py): the
profile list/switch actions use short-lived request/response
connections, while a background thread holds one long-lived "subscribe"
connection that streams live state pushes into the visualization widget.
The profile editor uses short-lived control requests to update names,
colors, direct bindings, and macro sequences without restarting g13d.
"""

from __future__ import annotations

import random
import shutil
import socket
import sys
import threading

from PySide6.QtCore import QPointF, QProcess, QSettings, Qt, QTimer, QUrl, Signal, QObject
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from g13.daemon.protocol import SOCKET_PATH, decode, encode
from g13.gui import theme
from g13.gui.binding_editor import ProfileInspector
from g13.gui.keyboard_view import G13View


def open_web_link(url: str) -> None:
    """Open a web link in a browser even if the desktop HTTPS handler is wrong."""
    for executable in ("chromium", "firefox", "firefox-esr", "google-chrome"):
        path = shutil.which(executable)
        if path is not None:
            started = QProcess.startDetached(path, [url])
            if started[0] if isinstance(started, tuple) else started:
                return
    QDesktopServices.openUrl(QUrl(url))


class DaemonClient:
    """Short-lived request/response connections for one-off commands."""

    def __init__(self, path: str = str(SOCKET_PATH)) -> None:
        self.path = path

    def _request(self, message: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(self.path)
            sock.sendall(encode(message))
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            return decode(data)

    def list_profiles(self) -> dict:
        return self._request({"cmd": "list_profiles"})

    def switch_profile(self, profile_id: str) -> dict:
        return self._request({"cmd": "switch_profile", "id": profile_id})

    def get_profile(self, profile_id: str) -> dict:
        return self._request({"cmd": "get_profile", "id": profile_id})

    def update_profile(self, profile_id: str, profile: dict) -> dict:
        return self._request({"cmd": "update_profile", "id": profile_id, "profile": profile})

    def create_profile(self) -> dict:
        return self._request({"cmd": "create_profile"})

    def delete_profile(self, profile_id: str) -> dict:
        return self._request({"cmd": "delete_profile", "id": profile_id})

    def assign_profile(self, profile_id: str, slot: int | None) -> dict:
        return self._request({"cmd": "assign_profile", "id": profile_id, "slot": slot})

    def set_lcd_mode(self, mode: str) -> dict:
        return self._request({"cmd": "set_lcd_mode", "mode": mode})


class StateListener(QObject):
    """Background thread holding one persistent "subscribe" connection.

    Emits state_received(dict) and connected(bool) on the Qt thread's
    event loop (Qt marshals cross-thread signal emission automatically).
    Retries the connection every second while the daemon is unreachable.
    """

    state_received = Signal(dict)
    connected = Signal(bool)

    def __init__(self, path: str = str(SOCKET_PATH)) -> None:
        super().__init__()
        self.path = path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._listen_once()
            except OSError:
                pass
            self.connected.emit(False)
            if not self._stop.is_set():
                self._stop.wait(1.0)  # daemon not up yet, or connection dropped -- retry

    def _listen_once(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(self.path)
            sock.sendall(encode({"cmd": "subscribe"}))
            self.connected.emit(True)
            buffer = b""
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        self.state_received.emit(decode(line))


class ProfileRow(QWidget):
    """One sidebar row: a color swatch + name, click anywhere to activate."""

    clicked = Signal(str)

    def __init__(
        self,
        profile_id: str,
        slot: int | None,
        name: str,
        color: tuple[int, int, int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile_id = profile_id
        self.slot = slot
        self.name = name
        self.active = False
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.active_bar = QWidget(self)
        self.active_bar.setGeometry(0, 0, 3, 40)
        self.active_bar.setStyleSheet(f"background-color: {theme.ACCENT};")
        self.active_bar.hide()

        self.swatch = QLabel()
        self.swatch.setFixedSize(12, 12)
        r, g, b = color
        self.swatch.setStyleSheet(f"background-color: rgb({r},{g},{b}); border-radius: 6px;")

        self.slot_label = QLabel(f"M{slot}" if slot is not None else "—")
        self.slot_label.setObjectName("SlotLabel")
        self.name_label = QLabel(name)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)
        layout.addWidget(self.swatch)
        layout.addWidget(self.slot_label)
        layout.addWidget(self.name_label, 1)

        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.active = active
        if active:
            self.setStyleSheet(
                f"ProfileRow {{ background-color: {theme.SURFACE_RAISED}; "
                f"border-radius: {theme.RADIUS_CARD}px; }}"
            )
            self.active_bar.show()
            self.active_bar.raise_()
            self.name_label.setStyleSheet(f"color: {theme.ACCENT_HI}; font-weight: 600; border: none; background: transparent;")
        else:
            self.setStyleSheet("ProfileRow { background-color: transparent; }")
            self.active_bar.hide()
            self.name_label.setStyleSheet(f"color: {theme.TEXT}; border: none; background: transparent;")

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit(self.profile_id)
        super().mousePressEvent(event)


class HeaderBar(QWidget):
    """Blue-black header with quiet, angular camouflage shapes."""

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.HEADER_BG))
        painter.setPen(Qt.PenStyle.NoPen)
        rng = random.Random(0x613)
        for _ in range(max(24, self.width() // 45)):
            x = rng.uniform(-70, self.width() - 10)
            y = rng.uniform(-16, self.height() - 4)
            width = rng.uniform(45, 130)
            height = rng.uniform(18, 48)
            points = QPolygonF(
                [
                    QPointF(x, y + height * 0.30),
                    QPointF(x + width * 0.28, y),
                    QPointF(x + width * 0.73, y + height * 0.12),
                    QPointF(x + width, y + height * 0.52),
                    QPointF(x + width * 0.62, y + height),
                    QPointF(x + width * 0.15, y + height * 0.82),
                ]
            )
            painter.setBrush(QColor(rng.choice(theme.HEADER_CAMO)))
            painter.drawPolygon(points)
        painter.setPen(QColor(theme.BORDER))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("G13 CONFIGURATOR")
        self.setMinimumSize(900, 650)
        self.settings = QSettings("g13-linux", "gui")
        self.client = DaemonClient()
        self._profile_rows: dict[str, ProfileRow] = {}
        self._active_profile_id: str | None = None
        self._active_slot: int | None = None
        self._last_mr_state = "idle"

        self._build_ui()
        self._restore_geometry()

        self.listener = StateListener()
        self.listener.state_received.connect(self._on_state)
        self.listener.connected.connect(self._on_connection_changed)
        self.listener.start()

        self.refresh()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_device_area(), 1)
        root.addLayout(body, 1)

        self.toast = QLabel(self)
        self.toast.hide()

    def _build_header(self) -> QWidget:
        bar = HeaderBar()
        bar.setObjectName("HeaderBar")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 12, 0)
        layout.setSpacing(10)

        name = QLabel("G13 CONFIGURATOR")
        name.setObjectName("AppName")
        layout.addWidget(name)

        layout.addSpacing(16)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 10px;")
        layout.addWidget(self.status_dot)
        self.status_text = QLabel("Connecting…")
        self.status_text.setObjectName("Muted")
        layout.addWidget(self.status_text)

        layout.addStretch(1)

        return bar

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        section = QLabel("PROFILES")
        section.setObjectName("SidebarSectionLabel")
        layout.addWidget(section)
        layout.addSpacing(4)

        self.profile_list_widget = QWidget()
        self.profile_list_widget.setObjectName("ProfileList")
        self.profile_container = QVBoxLayout(self.profile_list_widget)
        self.profile_container.setContentsMargins(0, 0, 0, 0)
        self.profile_container.setSpacing(2)
        self.profile_container.setAlignment(Qt.AlignmentFlag.AlignTop)

        profile_scroll = QScrollArea()
        profile_scroll.setObjectName("ProfileScroll")
        profile_scroll.setWidgetResizable(True)
        profile_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        profile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        profile_scroll.setWidget(self.profile_list_widget)
        layout.addWidget(profile_scroll, 1)

        profile_buttons = QHBoxLayout()
        self.add_profile_button = QPushButton("Add")
        self.add_profile_button.clicked.connect(self._on_add_profile)
        self.delete_profile_button = QPushButton("Delete")
        self.delete_profile_button.clicked.connect(self._on_delete_profile)
        profile_buttons.addWidget(self.add_profile_button)
        profile_buttons.addWidget(self.delete_profile_button)
        layout.addLayout(profile_buttons)

        return sidebar

    def _build_device_area(self) -> QWidget:
        area = QWidget()
        area.setObjectName("DeviceArea")
        outer_layout = QVBoxLayout(area)
        outer_layout.setContentsMargins(32, 32, 16, 12)
        outer_layout.setSpacing(6)
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 16, 0)
        content_layout.setSpacing(24)
        self.keyboard_view = G13View()
        self.keyboard_view.key_selected.connect(self._on_key_selected)
        self.keyboard_view.lcd_mode_requested.connect(self._on_lcd_mode_requested)
        content_layout.addWidget(self.keyboard_view, 1)
        self.inspector = ProfileInspector()
        self.inspector.save_requested.connect(self._on_profile_save)
        self.inspector.preview_color.connect(self.keyboard_view.set_preview_color)
        self.inspector.preview_intensity.connect(self.keyboard_view.set_preview_intensity)
        self.inspector.lcd_content_changed.connect(self.keyboard_view.set_lcd_content)
        self.inspector.slot_assignment_requested.connect(self._on_slot_assignment)
        content_layout.addWidget(self.inspector)
        outer_layout.addLayout(content_layout, 1)
        credit = QLabel(
            f'Made by <a href="https://jonamiki.com" '
            f'style="color: {theme.TEXT_MUTED}; text-decoration: none;">Jonas Werner</a>'
        )
        credit.setObjectName("CreditLabel")
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        credit.setOpenExternalLinks(False)
        credit.linkActivated.connect(open_web_link)
        credit.setAlignment(Qt.AlignmentFlag.AlignRight)
        outer_layout.addWidget(credit)
        return area

    # -- Data / state --------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_profile_list(load_active=True)

    def _refresh_profile_list(self, *, load_active: bool) -> None:
        try:
            result = self.client.list_profiles()
        except OSError as exc:
            self._show_toast(f"Can't reach g13d: {exc}", error=True)
            return

        for row in self._profile_rows.values():
            row.setParent(None)
        self._profile_rows.clear()

        for profile in result["profiles"]:
            profile_id = profile["id"]
            slot = profile["slot"]
            row = ProfileRow(profile_id, slot, profile["name"], tuple(profile["color"]))
            row.clicked.connect(self._on_profile_clicked)
            row.set_active(profile_id == result["active_id"])
            self.profile_container.addWidget(row)
            self._profile_rows[profile_id] = row

        self._active_profile_id = result["active_id"]
        self._active_slot = result["active_slot"]
        self.delete_profile_button.setEnabled(len(result["profiles"]) > 1)
        if load_active:
            self._load_profile(self._active_profile_id)

    def _confirm_discard(self) -> bool:
        if not self.inspector.is_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved profile changes",
            "Discard the unsaved changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _on_profile_clicked(self, profile_id: str) -> None:
        row = self._profile_rows.get(profile_id)
        if row is None or row.active:
            return
        if not self._confirm_discard():
            return
        try:
            result = self.client.switch_profile(profile_id)
        except OSError as exc:
            self._show_toast(f"Can't reach g13d: {exc}", error=True)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)
            return
        self._show_toast(f"Switched to {result['active']}")
        self._apply_active(result["active_id"], result["active_slot"])
        self._load_profile(result["active_id"])

    def _apply_active(self, active_id: str, active_slot: int | None) -> None:
        self._active_profile_id = active_id
        self._active_slot = active_slot
        for profile_id, row in self._profile_rows.items():
            row.set_active(profile_id == active_id)

    def _load_profile(self, profile_id: str) -> None:
        try:
            result = self.client.get_profile(profile_id)
        except OSError as exc:
            self._show_toast(f"Can't load profile: {exc}", error=True)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)
            return
        self.inspector.set_profile(result["profile"])

    def _on_key_selected(self, key_id: str) -> None:
        self.inspector.select_key(key_id)

    def _on_lcd_mode_requested(self, mode: str) -> None:
        try:
            result = self.client.set_lcd_mode(mode)
        except OSError as exc:
            self._show_toast(f"Can't change LCD view: {exc}", error=True)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)

    def _on_profile_save(self, profile: dict) -> None:
        profile_id = profile["id"]
        try:
            result = self.client.update_profile(profile_id, profile)
        except OSError as exc:
            self._show_toast(f"Can't save profile: {exc}", error=True)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)
            return
        saved = result["profile"]
        self.inspector.set_profile(saved, show_saved=True)
        self._show_toast(f"Saved {saved['name']}")
        self._refresh_profile_list(load_active=False)

    def _on_add_profile(self) -> None:
        if not self._confirm_discard():
            return
        try:
            result = self.client.create_profile()
        except OSError as exc:
            self._show_toast(f"Can't create profile: {exc}", error=True)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)
            return
        self._show_toast(f"Created {result['profile']['name']}")
        self.refresh()

    def _on_delete_profile(self) -> None:
        if self._active_profile_id is None:
            return
        if not self._confirm_discard():
            return
        row = self._profile_rows.get(self._active_profile_id)
        name = row.name if row is not None else "this profile"
        answer = QMessageBox.warning(
            self,
            "Delete profile",
            f"Delete {name!r}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.client.delete_profile(self._active_profile_id)
        except OSError as exc:
            self._show_toast(f"Can't delete profile: {exc}", error=True)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)
            return
        self._show_toast(f"Deleted {name}")
        self.refresh()

    def _on_slot_assignment(self, profile_id: str, slot: int | None) -> None:
        try:
            result = self.client.assign_profile(profile_id, slot)
        except OSError as exc:
            self._show_toast(f"Can't assign M-key: {exc}", error=True)
            self._load_profile(profile_id)
            return
        if "error" in result:
            self._show_toast(result["error"], error=True)
            self._load_profile(profile_id)
            return
        self.inspector.update_slot(result["profile"]["slot"])
        self._refresh_profile_list(load_active=False)

    def _on_state(self, state: dict) -> None:
        if state.get("kind") != "state":
            return
        profile_id = state.get("profile_id", self._active_profile_id)
        if profile_id is None:
            return
        slot = state.get("slot", self._active_slot or 1)
        profile_changed = (
            self._active_profile_id is not None and profile_id != self._active_profile_id
        )
        if profile_changed and self.inspector.is_dirty:
            # A physical M-key changed profiles; discard stale edits from the old slot.
            self.inspector.revert()
        self._apply_active(profile_id, slot)
        if profile_changed:
            self._load_profile(profile_id)
        self.keyboard_view.set_state(
            tuple(state["color"]),
            frozenset(state["keys"]),
            tuple(state.get("stick", (128, 128))),
            state.get("backlight_intensity", 100),
        )
        self.keyboard_view.set_lcd_mode(state.get("lcd_mode", "splash"))
        mr_state = state.get("mr_state", "idle")
        self.inspector.set_mr_state(mr_state, state.get("macro_target"))
        if self._last_mr_state == "recording" and mr_state == "idle":
            self._load_profile(profile_id)
        self._last_mr_state = mr_state

    def _on_connection_changed(self, connected: bool) -> None:
        if connected:
            self.status_dot.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 10px;")
            self.status_text.setText("Daemon connected")
        else:
            self.status_dot.setStyleSheet(f"color: {theme.DANGER}; font-size: 10px;")
            self.status_text.setText("Daemon offline")

    # -- Toast, geometry -----------------------------------------------------

    def _show_toast(self, message: str, error: bool = False) -> None:
        color = theme.DANGER if error else theme.SUCCESS
        self.toast.setText(message)
        self.toast.setStyleSheet(
            f"background-color: {theme.SURFACE_RAISED}; color: {theme.TEXT}; "
            f"border: 1px solid {color}; border-radius: {theme.RADIUS_CONTROL}px; padding: 8px 16px;"
        )
        self.toast.adjustSize()
        x = (self.width() - self.toast.width()) // 2
        y = self.height() - self.toast.height() - 24
        self.toast.move(x, y)
        self.toast.show()
        self.toast.raise_()
        QTimer.singleShot(2200, self.toast.hide)

    def _restore_geometry(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1400, 900)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.settings.setValue("geometry", self.saveGeometry())
        self.listener.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
