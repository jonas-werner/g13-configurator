"""Editable starter layouts based on games' default PC keyboard controls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GamePreset:
    name: str
    color: tuple[int, int, int]
    bindings: dict[str, str]
    macros: dict[str, list[dict]]


def _chord(*keys: str) -> list[dict]:
    return [
        *({"code": key, "down": True, "delay_ms": 0} for key in keys),
        *({"code": key, "down": False, "delay_ms": 0} for key in reversed(keys)),
    ]


_WASD = {"G4": "KEY_W", "G10": "KEY_A", "G11": "KEY_S", "G12": "KEY_D"}

GAME_PRESETS = (
    GamePreset(
        "DOOM (2016)",
        (210, 35, 15),
        {
            **_WASD,
            "G1": "KEY_TAB",
            "G2": "KEY_1",
            "G3": "KEY_2",
            "G5": "KEY_3",
            "G6": "KEY_4",
            "G7": "KEY_5",
            "G8": "KEY_LEFTCTRL",
            "G9": "KEY_Q",
            "G13": "KEY_E",
            "G14": "KEY_R",
            "G15": "KEY_LEFTSHIFT",
            "G16": "KEY_C",
            "G17": "KEY_SPACE",
            "G18": "KEY_F",
            "G19": "KEY_G",
            "G20": "KEY_6",
            "G21": "KEY_7",
            "G22": "KEY_8",
        },
        {},
    ),
    GamePreset(
        "Subnautica 2",
        (20, 125, 210),
        {
            **_WASD,
            "G1": "KEY_TAB",
            "G2": "KEY_1",
            "G3": "KEY_2",
            "G5": "KEY_3",
            "G6": "KEY_4",
            "G7": "KEY_5",
            "G8": "KEY_LEFTSHIFT",
            "G9": "KEY_Q",
            "G13": "KEY_E",
            "G14": "KEY_R",
            "G15": "KEY_H",
            "G16": "KEY_C",
            "G17": "KEY_SPACE",
            "G18": "KEY_F",
            "G19": "KEY_V",
            "G20": "KEY_B",
            "G21": "KEY_F8",
            "G22": "KEY_ESC",
        },
        {},
    ),
    GamePreset(
        "SnowRunner",
        (80, 150, 255),
        {
            **_WASD,
            "G1": "KEY_ESC",
            "G2": "KEY_1",
            "G3": "KEY_F4",
            "G5": "KEY_L",
            "G6": "KEY_M",
            "G7": "KEY_V",
            "G8": "KEY_LEFTSHIFT",
            "G9": "KEY_Q",
            "G13": "KEY_E",
            "G14": "KEY_R",
            "G15": "KEY_B",
            "G16": "KEY_G",
            "G17": "KEY_SPACE",
            "G18": "KEY_F",
            "G19": "KEY_C",
            "G20": "KEY_4",
            "G21": "KEY_5",
            "G22": "KEY_6",
        },
        {},
    ),
    GamePreset(
        "The Ascent",
        (225, 35, 180),
        {
            **_WASD,
            "G1": "KEY_TAB",
            "G7": "KEY_ESC",
            "G8": "KEY_LEFTCTRL",
            "G9": "KEY_Q",
            "G13": "KEY_E",
            "G14": "KEY_R",
            "G15": "KEY_C",
            "G16": "KEY_G",
            "G17": "KEY_SPACE",
            "G18": "KEY_F",
            "G19": "KEY_O",
            "G20": "KEY_M",
            "G21": "KEY_T",
            "G22": "KEY_V",
        },
        {},
    ),
    GamePreset(
        "X4: Foundations",
        (245, 150, 25),
        {
            **_WASD,
            "G1": "KEY_M",
            "G7": "KEY_F5",
            "G8": "KEY_TAB",
            "G9": "KEY_Q",
            "G13": "KEY_E",
            "G14": "KEY_T",
            "G15": "KEY_Z",
            "G16": "KEY_X",
            "G17": "KEY_SPACE",
            "G21": "KEY_F",
            "G22": "KEY_O",
        },
        {
            "G2": _chord("KEY_LEFTSHIFT", "KEY_1"),
            "G3": _chord("KEY_LEFTSHIFT", "KEY_2"),
            "G5": _chord("KEY_LEFTSHIFT", "KEY_3"),
            "G6": _chord("KEY_LEFTSHIFT", "KEY_4"),
            "G18": _chord("KEY_LEFTSHIFT", "KEY_E"),
            "G19": _chord("KEY_LEFTSHIFT", "KEY_D"),
            "G20": _chord("KEY_LEFTSHIFT", "KEY_A"),
        },
    ),
)

PRESETS_BY_NAME = {preset.name: preset for preset in GAME_PRESETS}
