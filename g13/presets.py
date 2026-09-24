"""Game-specific G13 layouts. See docs/game-layouts.md for controls and sources."""

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


# Direction keys remain available for menus (and flight steering in X4).
_ARROWS = {
    "STICK_UP": "KEY_UP", "STICK_DOWN": "KEY_DOWN",
    "STICK_LEFT": "KEY_LEFT", "STICK_RIGHT": "KEY_RIGHT",
}

GAME_PRESETS = (
    # Preserve the saved custom layout, including intentional duplicate keys.
    GamePreset(
        "Cyberpunk 2077",
        (255, 220, 0),
        {
            **_ARROWS,
            "G1": "KEY_ESC",
            "G2": "KEY_1",
            "G3": "KEY_Q",
            "G4": "KEY_W",
            "G5": "KEY_E",
            "G6": "KEY_R",
            "G7": "KEY_H",
            "G8": "KEY_TAB",
            "G9": "KEY_X",
            "G10": "KEY_A",
            "G11": "KEY_S",
            "G12": "KEY_D",
            "G13": "KEY_F",
            "G14": "KEY_R",
            "G15": "KEY_LEFTSHIFT",
            "G16": "KEY_B",
            "G17": "KEY_G",
            "G18": "KEY_C",
            "G19": "KEY_LEFTALT",
            "G20": "KEY_X",
            "G21": "KEY_V",
            "G22": "KEY_SPACE",
            "DOWN": "KEY_V",
            "LEFT": "KEY_T",
            "TOP": "BTN_MIDDLE",
        },
        {},
    ),
    GamePreset(
        "DOOM (2016)",
        (210, 35, 15),
        {
            **_ARROWS,
            "G1": "KEY_ESC",  # Pause
            "G2": "KEY_1",  # Pistol
            "G3": "KEY_Q",  # Weapon wheel / swap
            "G4": "KEY_W",  # Forward
            "G5": "KEY_E",  # Use
            "G6": "KEY_R",  # Switch weapon mod
            "G7": "KEY_T",  # BFG
            "G8": "KEY_TAB",  # Dossier
            "G9": "KEY_2",  # Combat shotgun
            "G10": "KEY_A",  # Left
            "G11": "KEY_S",  # Back
            "G12": "KEY_D",  # Right
            "G13": "KEY_F",  # Glory kill / melee
            "G14": "KEY_R",  # Switch weapon mod
            "G15": "KEY_LEFTSHIFT",  # Walk
            "G16": "KEY_3",  # Plasma rifle
            "G17": "KEY_G",  # Chainsaw
            "G18": "KEY_C",  # Crouch
            "G19": "KEY_LEFTCTRL",  # Use equipment
            "G20": "KEY_F1",  # Previous equipment
            "G21": "KEY_F2",  # Next equipment
            "G22": "KEY_SPACE",  # Jump / double jump
            "LEFT": "KEY_F",  # Glory kill / melee
            "DOWN": "KEY_LEFTCTRL",  # Use equipment
            "TOP": "KEY_Q",  # Weapon wheel / swap
        },
        {},
    ),
    GamePreset(
        "Subnautica 2",
        (20, 125, 210),
        {
            **_ARROWS,
            "G1": "KEY_ESC",  # Pause
            "G2": "KEY_1",  # Tool slot 1
            "G3": "KEY_Q",  # Tool quaternary / detach chassis
            "G4": "KEY_W",  # Forward
            "G5": "KEY_E",  # Stop piloting
            "G6": "KEY_R",  # Reload
            "G7": "KEY_H",  # Holster
            "G8": "KEY_TAB",  # PDA
            "G9": "KEY_2",  # Tool slot 2
            "G10": "KEY_A",  # Left
            "G11": "KEY_S",  # Back
            "G12": "KEY_D",  # Right
            "G13": "KEY_F",  # Tool secondary / drop item
            "G14": "KEY_R",  # Reload
            "G15": "KEY_LEFTSHIFT",  # Activate biomod
            "G16": "KEY_3",  # Tool slot 3
            "G17": "KEY_4",  # Tool slot 4
            "G18": "KEY_C",  # Descend
            "G19": "KEY_5",  # Tool slot 5
            "G20": "KEY_B",  # Toggle beacons
            "G21": "KEY_V",  # Ping
            "G22": "KEY_SPACE",  # Ascend / jump
            "LEFT": "KEY_T",  # Set label
            "DOWN": "KEY_V",  # Ping
            "TOP": "BTN_MIDDLE",  # Ping
        },
        {},
    ),
    GamePreset(
        "SnowRunner",
        (80, 150, 255),
        {
            **_ARROWS,
            "G1": "KEY_ESC",  # Pause
            "G2": "KEY_F4",  # Player profile
            "G3": "KEY_Q",  # Differential lock
            "G4": "KEY_W",  # Throttle
            "G5": "KEY_E",  # AWD
            "G6": "KEY_L",  # Headlights
            "G7": "KEY_B",  # Engine
            "G8": "KEY_M",  # Map
            "G9": "KEY_V",  # Functions
            "G10": "KEY_A",  # Steer left
            "G11": "KEY_S",  # Brake / reverse
            "G12": "KEY_D",  # Steer right
            "G13": "KEY_F",  # Quick winch
            "G14": "KEY_R",  # Release winch
            "G15": "KEY_LEFTSHIFT",  # Clutch / gearbox
            "G16": "KEY_4",  # Addon 1
            "G17": "KEY_G",  # Horn
            "G18": "KEY_5",  # Addon 2
            "G19": "KEY_6",  # Addon 3
            "G20": "KEY_7",  # Addon 4
            "G21": "KEY_8",  # Addon 5
            "G22": "KEY_SPACE",  # Handbrake
            "LEFT": "KEY_F",  # Quick winch
            "DOWN": "KEY_SPACE",  # Handbrake
            "TOP": "KEY_G",  # Horn
        },
        {},
    ),
    GamePreset(
        "The Ascent",
        (225, 35, 180),
        {
            **_ARROWS,
            "G1": "KEY_ESC",  # Pause
            "G3": "KEY_Q",  # Augmentation 1
            "G4": "KEY_W",  # Forward
            "G5": "KEY_E",  # Augmentation 2
            "G6": "KEY_R",  # Reload
            "G7": "KEY_M",  # Map
            "G8": "KEY_O",  # Mission HUD
            "G10": "KEY_A",  # Left
            "G11": "KEY_S",  # Back
            "G12": "KEY_D",  # Right
            "G13": "KEY_F",  # Interact
            "G14": "KEY_R",  # Reload
            "G15": "KEY_LEFTCTRL",  # Crouch
            "G17": "KEY_G",  # Tactical
            "G18": "KEY_C",  # Hold cyberdeck / hack
            "G21": "KEY_T",  # Taxi
            "G22": "KEY_SPACE",  # Evade
            "LEFT": "KEY_C",  # Hold cyberdeck / hack
            "DOWN": "KEY_G",  # Tactical
            "TOP": "KEY_O",  # Mission HUD
        },
        {},
    ),
    GamePreset(
        "X4: Foundations",
        (245, 150, 25),
        {
            **_ARROWS,
            "G1": "KEY_ESC",  # Back / pause
            "G3": "KEY_Q",  # Roll left
            "G4": "KEY_W",  # Strafe up
            "G5": "KEY_E",  # Roll right
            "G6": "KEY_T",  # Target under cursor
            "G8": "KEY_M",  # Map
            "G10": "KEY_A",  # Strafe left
            "G11": "KEY_S",  # Strafe down
            "G12": "KEY_D",  # Strafe right
            "G13": "KEY_F",  # Interact
            "G14": "KEY_R",  # Secondary weapon / scan pulse
            "G15": "KEY_TAB",  # Boost (hold)
            "G16": "KEY_Z",  # Decrease speed
            "G18": "KEY_X",  # Increase speed
            "G20": "KEY_BACKSPACE",  # Stop engines
            "G21": "KEY_O",  # Container magnet (hold)
            "G22": "KEY_SPACE",  # Fire primary / on-foot jump
            "LEFT": "KEY_T",  # Target under cursor
            "DOWN": "KEY_BACKSPACE",  # Stop engines
            "TOP": "BTN_MIDDLE",  # Fire at cursor
        },
        {
            "G2": _chord('KEY_LEFTSHIFT', 'KEY_1'),
            "G7": _chord('KEY_LEFTSHIFT', 'KEY_2'),
            "G9": _chord('KEY_LEFTSHIFT', 'KEY_3'),
            "G17": _chord('KEY_LEFTSHIFT', 'KEY_D'),
            "G19": _chord('KEY_LEFTSHIFT', 'KEY_A'),
        },
    ),
)

PRESETS_BY_NAME = {preset.name: preset for preset in GAME_PRESETS}
