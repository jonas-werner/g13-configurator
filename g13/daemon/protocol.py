"""Newline-delimited JSON protocol between g13d and its GUI/CLI clients.

Each message is a single JSON object followed by '\\n'. Requests carry a
"cmd" field; responses carry either the requested data or an "error".

Supported requests:
  list_profiles
  switch_profile + id (or legacy slot/name)
  get_profile + id
  update_profile + id + profile payload
  create_profile
  delete_profile + id
  assign_profile + id + optional slot
  set_lcd_mode + splash/animation/clock/stats/cycle
  subscribe

Subscription states include active slot/name/color, held G13 keys,
thumbstick position, MR recording state/target, and the active LCD mode.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _runtime_directory() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        return Path(configured)
    standard = Path("/run/user") / str(os.getuid())
    if standard.is_dir():
        return standard
    return Path("/tmp") / f"g13-{os.getuid()}"


SOCKET_PATH = _runtime_directory() / "g13d.sock"


def encode(message: dict) -> bytes:
    return (json.dumps(message) + "\n").encode()


def decode(line: bytes) -> dict:
    return json.loads(line.decode())
