"""Design tokens for the g13-linux GUI, and the QSS built from them.

Every color/radius/spacing value used by GUI widgets should come from
here, not be hardcoded inline -- keeps the whole app restylable from one
place. Palette follows a near-black layered-surface look with a single
saturated accent, in the spirit of modern gaming-peripheral configurators
(G HUB / Synapse / VIA).
"""

from __future__ import annotations

# -- Color tokens --------------------------------------------------------
BG = "#0B0E14"
SURFACE = "#12161F"
SURFACE_RAISED = "#1A1F2B"
HEADER_BG = "#111B26"
HEADER_CAMO = ("#0F1923", "#142230", "#172735", "#10202C")
BORDER = "#262C3A"
TEXT = "#E6E9EF"
TEXT_MUTED = "#94A0B8"
ACCENT = "#35C9E8"
ACCENT_HI = "#5FD9F2"
ACCENT_DIM = "#1B7C93"
SUCCESS = "#3DDC97"  # live key-press flash
WARNING = "#F5A524"
DANGER = "#F0616D"

# -- Shape tokens ---------------------------------------------------------
RADIUS_CONTROL = 6
RADIUS_CARD = 10
RADIUS_DEVICE = 16

# -- Spacing (4px grid) ----------------------------------------------------
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_6 = 24

FONT_FAMILY = '"Segoe UI", "Noto Sans", sans-serif'

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 14px;
}}

QLabel#AppName {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QLabel#SectionLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

QLabel#SidebarSectionLabel {{
    background-color: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1px;
}}

QLabel#Muted {{
    background-color: transparent;
    color: {TEXT_MUTED};
    font-size: 12px;
}}

QLabel#CreditLabel {{
    background-color: transparent;
    color: {TEXT_MUTED};
    font-size: 11px;
    padding: 2px 4px 0 0;
}}

QLabel#SlotLabel {{
    background-color: transparent;
    color: {ACCENT_HI};
    font-size: 11px;
    font-weight: 700;
}}

QLabel#InspectorKey {{
    color: {TEXT};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#StatusPill {{
    background-color: {ACCENT_DIM};
    color: {TEXT};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 8px;
}}

QLabel#LcdPreview {{
    background-color: #000000;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
}}

#HeaderBar {{
    border-bottom: 1px solid {BORDER};
}}

#HeaderBar QLabel {{
    background-color: transparent;
}}

#Sidebar {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}

#ProfileScroll, #ProfileScroll > QWidget > QWidget, #ProfileList {{
    background-color: transparent;
    border: none;
}}

#ProfileScroll QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    margin: 0;
}}

#ProfileScroll QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 4px;
    min-height: 28px;
}}

#ProfileScroll QScrollBar::add-line:vertical,
#ProfileScroll QScrollBar::sub-line:vertical {{
    height: 0;
}}

#DeviceArea {{
    background-color: {BG};
}}

QFrame#Inspector {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}

QLineEdit, QComboBox {{
    background-color: {SURFACE_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 8px;
}}

QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}

QSlider::groove:horizontal {{
    background-color: {BORDER};
    border-radius: 2px;
    height: 4px;
}}

QSlider::sub-page:horizontal {{
    background-color: {ACCENT_DIM};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background-color: {ACCENT_HI};
    border: 1px solid {ACCENT};
    border-radius: 7px;
    margin: -5px 0;
    width: 14px;
}}

QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
}}

QListWidget::item {{
    padding: 0px;
    margin: 2px 0px;
    border-radius: {RADIUS_CARD}px;
}}

QPushButton {{
    background-color: {SURFACE_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 12px;
    font-weight: 500;
}}

QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HI};
}}

QPushButton:pressed {{
    background-color: {BORDER};
}}

QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {SURFACE};
    border-color: {BORDER};
}}

QPushButton#PrimaryButton {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
}}

QPushButton#PrimaryButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {SURFACE};
    border-color: {BORDER};
}}

QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px dashed {BORDER};
    color: {TEXT_MUTED};
}}

QPushButton#GhostButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HI};
}}

QToolButton {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    color: {TEXT_MUTED};
    padding: 6px;
}}

QToolButton:hover {{
    background-color: {SURFACE_RAISED};
    color: {TEXT};
}}

QMenu {{
    background-color: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 20px;
    border-radius: {RADIUS_CONTROL}px;
}}

QMenu::item:selected {{
    background-color: {SURFACE};
    color: {ACCENT_HI};
}}
"""
