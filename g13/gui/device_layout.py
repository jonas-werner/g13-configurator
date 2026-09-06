"""Declarative geometry for the G13 device visualization.

G-key and LCD coordinates are derived by scanning the alpha channel of
the bundled gui/assets/g13-stylized-transparent.png directly (find the
transparent-pixel clusters cut for each label/screen, per row) -- not eyeballed against a
pixel grid, which turned out to drift enough to matter (a manual
grid-reading pass looked fine visually but was off by 10-30px in
several places once checked against a live key press). Everything else
(BD/L-row/M-row/joystick, which have no transparency to detect) is still
from the earlier grid-reading pass. All coordinates are in the image's
own pixel space (1086x1448). keyboard_view.py draws that image as the
device body and overlays state on top of it at these coordinates --
geometry lives here as data so the drawing code stays purely
declarative.

Confirmed against a real-hardware reference photo during calibration:
only the G-key legends and the LCD actually light up; the plastic itself
stays black. g13-stylized-transparent.png
has the G1-G22 labels and the LCD screen cut to transparent, so a color
fill drawn *behind* the image shines through as glowing text/screen --
no glow effect or hand-drawn text needed. M1-M3/MR keep their printed
label (no cutout in that asset) and just get a press-ring highlight.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ASSET_PATH = Path(__file__).with_name("assets") / "g13-stylized-transparent.png"

IMAGE_W = 1086
IMAGE_H = 1448


@dataclass(frozen=True)
class KeySpec:
    id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "rect"  # "rect" or "ellipse"


LCD = KeySpec("LCD", "LCD", 347, 118, 388, 93)

BD = KeySpec("BD", "BD", 240, 239, 80, 80, "ellipse")
LIGHT = KeySpec("LIGHT", "LIGHT", 760, 239, 80, 80, "ellipse")
# The L buttons are about 96 px center-to-center, with small width
# differences in the source image. Treating them as a uniform 78 px
# button plus a 29 px gap made the error accumulate toward L4.
L_KEYS = [
    KeySpec("L1", "L1", 354, 266, 88, 38),
    KeySpec("L2", "L2", 450, 266, 88, 38),
    KeySpec("L3", "L3", 547, 266, 87, 38),
    KeySpec("L4", "L4", 643, 266, 87, 38),
]

_M_ROW_CENTERS = {"M1": 317.5, "M2": 462.0, "M3": 621.5, "MR": 772.5}
_M_ROW_KEYS = [KeySpec(mid, mid, cx - 72.5, 329.5, 145, 40) for mid, cx in _M_ROW_CENTERS.items()]


def _g_row(start: int, y: float, height: float, width: float, centers: list[float]) -> list[KeySpec]:
    return [
        KeySpec(f"G{start + i}", f"G{start + i}", cx - width / 2, y, width, height)
        for i, cx in enumerate(centers)
    ]


# Text-center x per key, read directly off the alpha-channel clusters
# for each row (see module docstring) -- not a uniform step formula,
# since the real spacing isn't perfectly uniform.
G_KEYS = [
    *_g_row(1, 408.5, 85, 110, [190.5, 313.0, 429.5, 544.0, 658.5, 777.0, 895.5]),
    *_g_row(8, 518.5, 85, 112, [182.5, 304.0, 425.5, 544.0, 665.0, 785.5, 907.0]),
    *_g_row(15, 632.5, 90, 125, [281.5, 418.5, 545.0, 671.5, 806.0]),
    *_g_row(20, 749.0, 90, 150, [387.0, 545.0, 705.5]),
]

JOYSTICK_CENTER = (943.0, 920.0)
JOYSTICK_RADIUS = 80.0
JOYSTICK_KEY_ID = "TOP"  # the stick click, per g13/hardware/report.py

# The two shapes flanking the joystick housing in the reference photo --
# best-guess mapping to the two never-fully-confirmed bits from hardware
# testing (g13/hardware/report.py). Easy to swap if this turns out
# backwards once tested live.
LEFT = KeySpec("LEFT", "LEFT", 785, 845, 70, 145)
DOWN = KeySpec("DOWN", "DOWN", 855, 1015, 170, 110)

# Bits confirmed (see g13/hardware/report.py) to fire together when the
# physical backlight/menu button (the sun icon, right of the LCD row) is
# pressed -- not a single clean bit, so we ring the icon on either.
LIGHT_BUTTON_KEYS = {"LIGHT", "LIGHT2"}

# Keys whose label is cut to transparent in the asset, so a color fill
# drawn behind the image shines through as the active profile's
# backlight color (G-keys + LCD only -- M1-M3/MR have no cutout).
BACKLIT_BY_PROFILE = {key.id for key in G_KEYS} | {"LCD"}

KEYS: list[KeySpec] = [BD, LIGHT, *L_KEYS, *G_KEYS, *_M_ROW_KEYS, LEFT, DOWN]
KEYS_BY_ID: dict[str, KeySpec] = {key.id: key for key in KEYS}
