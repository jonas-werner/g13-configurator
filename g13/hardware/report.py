"""Decoding raw G13 input reports into joystick + key state.

Byte layout confirmed against two independent reference drivers named in
this project's brief (Lordbooker/linux-g13-driver, ecraven/g13):

    report[0]    report ID (constant)
    report[1]    joystick X (0-255, ~128 centered)
    report[2]    joystick Y (0-255, ~128 centered)
    report[3:8]  40-bit key bitmask, byte = 3 + key_index // 8,
                 bit = key_index % 8

KEY_NAMES follows that driver's enum. Verified against live hardware:
all 22 G-keys, M1-M3, MR, BD, L1-L4 (the round button + 4 small buttons
below the LCD), and TOP (the joystick click) all match exactly. There is
no M4 -- the real G13 only has M1-M3 plus MR, and those four ARE the
"buttons below the LCD", not a separate group. LEFT/DOWN appeared once
each in early testing (possibly an angled stick-click) but didn't
reproduce in focused testing -- treat as unconfirmed until it matters.

Two entries are known to NOT be momentary keys and are pulled out into
separate G13State fields instead:
  - LIGHT_STATE is a persistent flag (set whenever the backlight is on),
    not a key press -- exposed as `backlight_on`.
  - MISC_TOGGLE flickers independently of any button (seen changing
    during plain joystick movement with nothing pressed) -- likely a
    firmware sequence/heartbeat bit. Excluded from `keys` as noise.
"""

from __future__ import annotations

from dataclasses import dataclass

KEY_NAMES = [
    "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8",
    "G9", "G10", "G11", "G12", "G13", "G14", "G15", "G16",
    "G17", "G18", "G19", "G20", "G21", "G22", "UNDEF1", "LIGHT_STATE",
    "BD", "L1", "L2", "L3", "L4", "M1", "M2", "M3",
    "MR", "LEFT", "DOWN", "TOP", "UNDEF3", "LIGHT", "LIGHT2", "MISC_TOGGLE",
]

# Not momentary keys -- see module docstring.
STATUS_FLAGS = {"LIGHT_STATE"}
NOISE_BITS = {"MISC_TOGGLE"}


@dataclass(frozen=True)
class G13State:
    stick_x: int
    stick_y: int
    keys: frozenset[str]
    backlight_on: bool


def decode_report(report: bytes) -> G13State:
    """Decode an 8-byte raw input report into joystick + pressed key names."""
    if len(report) != 8:
        raise ValueError(f"expected an 8-byte report, got {len(report)}")

    active = {
        name
        for index, name in enumerate(KEY_NAMES)
        if report[3 + index // 8] & (1 << (index % 8))
    }
    keys = active - STATUS_FLAGS - NOISE_BITS
    return G13State(
        stick_x=report[1],
        stick_y=report[2],
        keys=frozenset(keys),
        backlight_on="LIGHT_STATE" in active,
    )
