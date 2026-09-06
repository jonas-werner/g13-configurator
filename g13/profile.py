"""Profile schema: TOML files describing G-key bindings for a named profile.

Profiles live in ~/.config/g13-linux/profiles/*.toml. Each file contains a
stable M-key `slot`, a display `name`, and a `[bindings]` table mapping a
G13 key name (e.g. "G1")
to a key to emit: a single letter/digit ("a", "1") or a full evdev key
name ("KEY_LEFTCTRL"). Two optional fields control the LCD/backlight
while the profile is active:

  color = [r, g, b]            # backlight color, defaults to white
  backlight_intensity = 75     # 0-100%, defaults to 100
  lcd_image = "splash.png"     # exact-size 160x43 PNG profile splash
  lcd_gif = "animation.gif"    # optional exact-size looping animation

Relative media paths resolve against the profile file's directory. The
profile name is rendered when no splash image is selected.

A third optional table holds recorded macros -- a G-key with an entry
here plays back the recorded sequence on press instead of its normal
single binding:

  [macros]
  G5 = [
      { code = "a", down = true, delay_ms = 0 },
      { code = "a", down = false, delay_ms = 50 },
  ]
"""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w
from evdev import ecodes
from PIL import Image

PROFILES_DIR = Path.home() / ".config" / "g13-linux" / "profiles"
PROFILE_SLOTS = (1, 2, 3)
G_KEY_IDS = frozenset(f"G{i}" for i in range(1, 23))
JOYSTICK_CONTROL_IDS = frozenset(
    {"LEFT", "DOWN", "TOP", "STICK_UP", "STICK_DOWN", "STICK_LEFT", "STICK_RIGHT"}
)
ASSIGNABLE_CONTROL_IDS = G_KEY_IDS | JOYSTICK_CONTROL_IDS
DEFAULT_JOYSTICK_BINDINGS = {
    "LEFT": "BTN_LEFT",
    "DOWN": "BTN_RIGHT",
    "TOP": "BTN_MIDDLE",
    "STICK_UP": "KEY_UP",
    "STICK_DOWN": "KEY_DOWN",
    "STICK_LEFT": "KEY_LEFT",
    "STICK_RIGHT": "KEY_RIGHT",
}
STICK_MODES = frozenset({"keys", "mouse"})
LCD_SIZE = (160, 43)
MAX_MACRO_EVENTS = 2048
MAX_MACRO_DELAY_MS = 600_000


class ProfileError(RuntimeError):
    """Raised for malformed profile files or bindings."""


@dataclass(frozen=True)
class MacroEvent:
    code: int  # evdev keycode
    down: bool  # True for a key press, False for a release
    delay_ms: int  # delay before this event, relative to the previous one


@dataclass(frozen=True)
class Profile:
    slot: int | None
    name: str
    path: Path
    bindings: dict[str, int]  # G13 control name -> evdev key/button code
    color: tuple[int, int, int] = (255, 255, 255)
    backlight_intensity: int = 100
    lcd_image: Path | None = None
    lcd_gif: Path | None = None
    macros: dict[str, list[MacroEvent]] = field(default_factory=dict)
    stick_mode: str = "keys"

    @property
    def id(self) -> str:
        return self.path.stem


def resolve_keycode(value: str) -> int:
    """Resolve a TOML binding value ('a', '1', 'KEY_TAB') to an evdev keycode."""
    if value.upper().startswith(("KEY_", "BTN_")):
        name = value.upper()
    elif len(value) == 1 and (value.isalpha() or value.isdigit()):
        name = f"KEY_{value.upper()}"
    else:
        raise ProfileError(f"can't resolve key binding {value!r}")

    code = getattr(ecodes, name, None)
    if not isinstance(code, int):
        raise ProfileError(f"unknown evdev key name {name!r} (from {value!r})")
    return code


def keycode_to_str(code: int) -> str:
    """Inverse of resolve_keycode, for serializing recorded macros back to TOML."""
    name = ecodes.KEY.get(code)
    if name is None:
        name = ecodes.BTN.get(code)
    if name is None:
        raise ProfileError(f"unknown evdev keycode {code!r}")
    if isinstance(name, list | tuple):
        name = next(
            (candidate for candidate in name if candidate.startswith(("KEY_", "BTN_"))),
            name[0],
        )
    return name


def _resolve_color(data: dict) -> tuple[int, int, int]:
    color = data.get("color", [255, 255, 255])
    if (
        not isinstance(color, list | tuple)
        or len(color) != 3
        or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)
    ):
        raise ProfileError(f"invalid color {color!r}, expected [r, g, b] with each 0-255")
    return (color[0], color[1], color[2])


def _resolve_backlight_intensity(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ProfileError(
            f"backlight_intensity must be an integer from 0 to 100, got {value!r}"
        )
    return value


def _resolve_lcd_media(data: dict, field: str, path: Path, *, animated: bool) -> Path | None:
    value = data.get(field)
    if not value:
        return None
    if not isinstance(value, str):
        raise ProfileError(f"{field} must be a file path")
    candidate = Path(value)
    candidate = candidate if candidate.is_absolute() else path.parent / candidate
    if not candidate.is_file():
        raise ProfileError(f"{field} does not exist: {candidate}")
    try:
        with Image.open(candidate) as image:
            if image.size != LCD_SIZE:
                raise ProfileError(
                    f"{field} must be exactly {LCD_SIZE[0]}x{LCD_SIZE[1]} pixels, "
                    f"got {image.size[0]}x{image.size[1]}"
                )
            frame_count = getattr(image, "n_frames", 1)
            if animated and (image.format != "GIF" or frame_count < 2):
                raise ProfileError(f"{field} must be an animated GIF with at least two frames")
            if not animated and image.format != "PNG":
                raise ProfileError(f"{field} must be a PNG image")
    except OSError as exc:
        raise ProfileError(f"cannot read {field}: {candidate}") from exc
    return candidate


def _resolve_stick_mode(value: Any) -> str:
    if value not in STICK_MODES:
        raise ProfileError(f"stick_mode must be one of {sorted(STICK_MODES)}, got {value!r}")
    return value


def _validate_g_key(value: str) -> str:
    if value not in ASSIGNABLE_CONTROL_IDS:
        raise ProfileError(f"unknown assignable G13 control {value!r}")
    return value


def _validate_macro_events(g13_key: str, events: list[MacroEvent]) -> None:
    if not events:
        raise ProfileError(f"macro for {g13_key} is empty")
    if len(events) > MAX_MACRO_EVENTS:
        raise ProfileError(f"macro for {g13_key} exceeds {MAX_MACRO_EVENTS} events")

    held: set[int] = set()
    for event in events:
        if not 0 <= event.delay_ms <= MAX_MACRO_DELAY_MS:
            raise ProfileError(
                f"macro for {g13_key} has invalid delay {event.delay_ms}; "
                f"expected 0-{MAX_MACRO_DELAY_MS} ms"
            )
        if event.down:
            if event.code in held:
                raise ProfileError(f"macro for {g13_key} presses an already-held key")
            held.add(event.code)
        else:
            if event.code not in held:
                raise ProfileError(f"macro for {g13_key} releases a key that is not held")
            held.remove(event.code)
    if held:
        raise ProfileError(f"macro for {g13_key} leaves one or more keys held")


def _resolve_bindings(data: dict[str, Any]) -> dict[str, int]:
    if not isinstance(data, dict):
        raise ProfileError("bindings must be a table")
    bindings = {}
    for g13_key, value in data.items():
        _validate_g_key(g13_key)
        if not isinstance(value, str):
            raise ProfileError(f"binding for {g13_key} must be a key name")
        bindings[g13_key] = resolve_keycode(value)
    return bindings


def _resolve_macros(data: dict) -> dict[str, list[MacroEvent]]:
    macros: dict[str, list[MacroEvent]] = {}
    raw_macros = data.get("macros", {})
    if not isinstance(raw_macros, dict):
        raise ProfileError("macros must be a table")
    for g13_key, raw_events in raw_macros.items():
        _validate_g_key(g13_key)
        if not isinstance(raw_events, list):
            raise ProfileError(f"macro for {g13_key} must be a list of events")
        events = []
        for event in raw_events:
            if not isinstance(event, dict):
                raise ProfileError(f"macro event for {g13_key} must be a table")
            if not isinstance(event.get("down"), bool):
                raise ProfileError(f"macro event for {g13_key} needs a boolean down value")
            try:
                code = resolve_keycode(event["code"])
                delay_ms = int(event["delay_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProfileError(f"invalid macro event for {g13_key}: {event!r}") from exc
            events.append(MacroEvent(code=code, down=event["down"], delay_ms=delay_ms))
        _validate_macro_events(g13_key, events)
        macros[g13_key] = events
    return macros


def load_profile(path: Path, default_slot: int | None = None) -> Profile:
    with path.open("rb") as f:
        data = tomllib.load(f)

    try:
        name = data["name"]
        raw_bindings = data["bindings"]
    except KeyError as exc:
        raise ProfileError(f"{path}: missing required field {exc}") from exc

    raw_slot = data.get("slot", default_slot)
    slot = None if raw_slot == 0 else raw_slot
    if slot is not None and slot not in PROFILE_SLOTS:
        raise ProfileError(f"{path}: invalid or missing profile slot {slot!r}")
    if not isinstance(name, str) or not name.strip():
        raise ProfileError(f"{path}: profile name must not be empty")

    return Profile(
        slot=slot,
        name=name,
        path=path,
        bindings=_resolve_bindings(raw_bindings),
        color=_resolve_color(data),
        backlight_intensity=_resolve_backlight_intensity(data.get("backlight_intensity", 100)),
        lcd_image=_resolve_lcd_media(data, "lcd_image", path, animated=False),
        lcd_gif=_resolve_lcd_media(data, "lcd_gif", path, animated=True),
        macros=_resolve_macros(data),
        stick_mode=_resolve_stick_mode(data.get("stick_mode", "keys")),
    )


def load_profiles(directory: Path = PROFILES_DIR) -> list[Profile]:
    profiles = [load_profile(path) for path in sorted(directory.glob("*.toml"))]
    slots = [profile.slot for profile in profiles if profile.slot is not None]
    if len(slots) != len(set(slots)):
        raise ProfileError("profile slots must be unique")
    return sorted(
        profiles,
        key=profile_sort_key,
    )


def profile_sort_key(profile: Profile) -> tuple:
    natural_name = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", profile.name.casefold())
    )
    return (profile.slot is None, profile.slot or 99, natural_name, profile.id)


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    def control_sort(item: tuple[str, Any]) -> tuple[int, int | str]:
        key = item[0]
        if key.startswith("G") and key[1:].isdigit():
            return (0, int(key[1:]))
        return (1, key)

    return {
        "id": profile.id,
        "slot": profile.slot,
        "name": profile.name,
        "color": list(profile.color),
        "backlight_intensity": profile.backlight_intensity,
        "bindings": {
            key: keycode_to_str(code)
            for key, code in sorted(profile.bindings.items(), key=control_sort)
        },
        "macros": {
            key: [
                {
                    "code": keycode_to_str(event.code),
                    "down": event.down,
                    "delay_ms": event.delay_ms,
                }
                for event in events
            ]
            for key, events in sorted(profile.macros.items(), key=control_sort)
        },
        "lcd_image": str(profile.lcd_image) if profile.lcd_image is not None else None,
        "lcd_gif": str(profile.lcd_gif) if profile.lcd_gif is not None else None,
        "stick_mode": profile.stick_mode,
    }


def profile_from_payload(profile: Profile, payload: dict[str, Any]) -> Profile:
    name = payload.get("name", profile.name)
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("profile name must not be empty")
    if len(name.strip()) > 80:
        raise ProfileError("profile name must be 80 characters or fewer")

    color_data = {"color": payload.get("color", list(profile.color))}
    bindings = _resolve_bindings(payload.get("bindings", profile_to_dict(profile)["bindings"]))
    macros = _resolve_macros({"macros": payload.get("macros", profile_to_dict(profile)["macros"])})
    media_data = {
        "lcd_image": payload.get(
            "lcd_image", str(profile.lcd_image) if profile.lcd_image is not None else None
        ),
        "lcd_gif": payload.get(
            "lcd_gif", str(profile.lcd_gif) if profile.lcd_gif is not None else None
        ),
    }
    overlap = set(bindings) & set(macros)
    if overlap:
        # A macro takes precedence at runtime, so remove shadowed direct bindings.
        bindings = {key: value for key, value in bindings.items() if key not in overlap}

    return Profile(
        slot=profile.slot,
        name=name.strip(),
        path=profile.path,
        bindings=bindings,
        color=_resolve_color(color_data),
        backlight_intensity=_resolve_backlight_intensity(
            payload.get("backlight_intensity", profile.backlight_intensity)
        ),
        lcd_image=_resolve_lcd_media(media_data, "lcd_image", profile.path, animated=False),
        lcd_gif=_resolve_lcd_media(media_data, "lcd_gif", profile.path, animated=True),
        macros=macros,
        stick_mode=_resolve_stick_mode(payload.get("stick_mode", profile.stick_mode)),
    )


def _profile_toml(profile: Profile) -> dict[str, Any]:
    data = profile_to_dict(profile)
    data.pop("id")
    data["slot"] = profile.slot or 0
    data.pop("lcd_image")
    data.pop("lcd_gif")
    for field, media_path in (("lcd_image", profile.lcd_image), ("lcd_gif", profile.lcd_gif)):
        if media_path is not None:
            try:
                data[field] = str(media_path.relative_to(profile.path.parent))
            except ValueError:
                data[field] = str(media_path)
    if not profile.macros:
        data.pop("macros")
    return data


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w") as temporary:
            temporary.write(tomli_w.dumps(data))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def save_profile(profile: Profile) -> None:
    """Atomically persist a complete validated profile."""
    profile_from_payload(profile, profile_to_dict(profile))
    data = _profile_toml(profile)
    _atomic_write(profile.path, data)


def save_macro(path: Path, g13_key: str, events: list[MacroEvent]) -> None:
    """Persist a recorded macro into its profile's TOML file."""
    profile = load_profile(path)
    _validate_g_key(g13_key)
    _validate_macro_events(g13_key, events)
    save_profile(
        Profile(
            slot=profile.slot,
            name=profile.name,
            path=profile.path,
            bindings={key: code for key, code in profile.bindings.items() if key != g13_key},
            color=profile.color,
            backlight_intensity=profile.backlight_intensity,
            lcd_image=profile.lcd_image,
            lcd_gif=profile.lcd_gif,
            macros={**profile.macros, g13_key: events},
            stick_mode=profile.stick_mode,
        )
    )


def _write_profile(
    path: Path,
    slot: int | None,
    name: str,
    bindings: dict[str, str],
    color: tuple[int, int, int],
) -> None:
    _atomic_write(
        path,
        {
            "slot": slot or 0,
            "name": name,
            "bindings": bindings,
            "color": list(color),
            "backlight_intensity": 100,
            "stick_mode": "keys",
        },
    )


def ensure_default_profiles(directory: Path = PROFILES_DIR) -> None:
    """Migrate legacy profiles and seed a first-run profile set."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = sorted(directory.glob("*.toml"))
    if not paths:
        default_colors = {1: (0, 255, 0), 2: (0, 120, 255), 3: (190, 70, 255)}
        for slot in PROFILE_SLOTS:
            _write_profile(
                directory / f"profile-{slot}.toml",
                slot,
                f"Profile {slot}",
                DEFAULT_JOYSTICK_BINDINGS,
                default_colors[slot],
            )
        return

    raw_profiles: list[tuple[Path, dict[str, Any]]] = []
    occupied: set[int] = set()
    for path in paths:
        with path.open("rb") as source:
            data = tomllib.load(source)
        explicit_slot = data.get("slot")
        if explicit_slot not in (None, 0):
            if explicit_slot not in PROFILE_SLOTS or explicit_slot in occupied:
                raise ProfileError(f"{path}: duplicate or invalid slot {explicit_slot!r}")
            occupied.add(explicit_slot)
        raw_profiles.append((path, data))

    available = iter(slot for slot in PROFILE_SLOTS if slot not in occupied)
    for path, data in raw_profiles:
        changed = False
        if "slot" not in data:
            try:
                data["slot"] = next(available)
            except StopIteration:
                data["slot"] = 0
            changed = True
        legacy_name = data.get("name")
        if legacy_name in {"alphabet", "numbers"}:
            data["name"] = f"Profile {data['slot'] or len(raw_profiles)}"
            changed = True
        bindings = data.setdefault("bindings", {})
        macros = data.get("macros", {})
        for control, code in DEFAULT_JOYSTICK_BINDINGS.items():
            if control not in bindings and control not in macros:
                bindings[control] = code
                changed = True
        if "stick_mode" not in data:
            data["stick_mode"] = "keys"
            changed = True
        if changed:
            _atomic_write(path, data)


def create_profile(directory: Path = PROFILES_DIR) -> Profile:
    """Create a uniquely named, unassigned profile."""
    directory.mkdir(parents=True, exist_ok=True)
    profiles = load_profiles(directory)
    existing_names = {profile.name.casefold() for profile in profiles}
    number = 1
    name = "New Profile"
    while name.casefold() in existing_names:
        number += 1
        name = f"New Profile {number}"
    path = directory / f"profile-{uuid.uuid4().hex}.toml"
    _write_profile(path, None, name, DEFAULT_JOYSTICK_BINDINGS, (80, 140, 220))
    return load_profile(path)
