#!/usr/bin/env python3
"""Remembered settings for the ATCAI manager itself.

Distinct from the ATC settings in installer.py: those are written into DCS and change
how ATC behaves. These are the app's own memory — which DCS folder you picked, how you
like the voice set up, and whether to start it automatically — so nothing has to be
re-chosen every launch.

Stored beside the user's other application data rather than in the DCS folder, so
uninstalling ATCAI from DCS doesn't wipe your preferences.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "ATCAI"
FILENAME = "manager.json"

DEFAULTS = {
    "dcs_path": "",
    "tts_mode": "local",
    "min_confidence": 0.6,
    "strict": False,
    "auto_start_voice": False,
    "auto_start_replies": False,
}

# Guards against a hand-edited or corrupted file feeding nonsense into the GUI.
VALIDATORS = {
    "dcs_path": lambda v: isinstance(v, str),
    "tts_mode": lambda v: v in ("local", "srs"),
    "min_confidence": lambda v: isinstance(v, (int, float)) and 0.0 < float(v) <= 1.0,
    "strict": lambda v: isinstance(v, bool),
    "auto_start_voice": lambda v: isinstance(v, bool),
    "auto_start_replies": lambda v: isinstance(v, bool),
}


def prefs_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / APP_NAME.lower()


def prefs_path() -> Path:
    return prefs_dir() / FILENAME


def load(path: Path | None = None) -> dict:
    """Saved preferences, with defaults filled in. Never raises."""
    settings = dict(DEFAULTS)
    target = Path(path) if path else prefs_path()
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if not isinstance(stored, dict):
        return settings

    for key, value in stored.items():
        validator = VALIDATORS.get(key)
        # Silently drop anything unrecognised or invalid: a bad preferences file
        # should never stop the app opening.
        if validator and validator(value):
            settings[key] = value
    return settings


def save(settings: dict, path: Path | None = None) -> Path | None:
    """Write preferences. Returns the path, or None if it couldn't be written."""
    target = Path(path) if path else prefs_path()
    keep = {k: v for k, v in settings.items()
            if k in DEFAULTS and VALIDATORS[k](v)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(keep, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
    except OSError:
        return None            # read-only home, locked file: not worth failing over
    return target
