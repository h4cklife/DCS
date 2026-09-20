#!/usr/bin/env python3
"""Install, remove, enable, disable and configure ATCAI in a DCS installation.

No GUI: this is the layer the manager app sits on, and everything here is callable and
testable on its own.

ATCAI lives entirely inside DCS's writeable directory ("Saved Games\\DCS"), never the
game install, so nothing here needs administrator rights:

    Scripts/ATCAI/*.lua          the ATC scripts, plus generated config.lua and inbox.lua
    Scripts/Hooks/atcai_autoload.lua   the loader that pulls ATCAI into every mission

Disabling renames the hook rather than deleting it, so settings and scripts survive.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_FILES = (
    "atc_config.lua",
    "atc_core.lua",
    "atc_traffic.lua",
    "atc_menu.lua",
    "atc_inbox.lua",
)
HOOK_FILE = "atcai_autoload.lua"
DISABLED_SUFFIX = ".disabled"

SCRIPTS_SUBDIR = Path("Scripts") / "ATCAI"
HOOKS_SUBDIR = Path("Scripts") / "Hooks"

# Files DCS itself creates; used to tell a real writeable directory from a folder that
# merely happens to be called "DCS".
WRITEDIR_MARKERS = ("Config", "Logs", "Missions", "Mods")

SAVED_GAMES_GUID = "{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}"
USER_SHELL_FOLDERS = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"

# Settings the Lua side understands. Mirrors ATC.CONFIG_FIELDS in atc_config.lua;
# tools/test_installer.py asserts the two agree.
CONFIG_FIELDS = {
    "tts_frequency": str,
    "tts_modulation": str,
    "airbase_search_radius": (int, float),
    "airbase_air_radius": (int, float),
    "inbox_poll_seconds": (int, float),
    "traffic_field_radius": (int, float),
    "traffic_roll_speed": (int, float),
    "traffic_final_range": (int, float),
    "traffic_final_height": (int, float),
    "traffic_final_arc": (int, float),
}


@dataclass
class Installation:
    """A DCS writeable directory ATCAI can be installed into."""

    path: Path
    label: str
    verified: bool
    notes: list[str] = field(default_factory=list)

    @property
    def scripts_dir(self) -> Path:
        return self.path / SCRIPTS_SUBDIR

    @property
    def hooks_dir(self) -> Path:
        return self.path / HOOKS_SUBDIR

    @property
    def hook_path(self) -> Path:
        return self.hooks_dir / HOOK_FILE

    @property
    def disabled_hook_path(self) -> Path:
        return self.hooks_dir / (HOOK_FILE + DISABLED_SUFFIX)

    @property
    def config_path(self) -> Path:
        return self.scripts_dir / "config.lua"


# ---------- locating DCS ----------


def running_under_wsl() -> bool:
    # os.name first: when Windows Python is launched from a \\wsl.localhost\... path,
    # a rooted read of /proc/version resolves onto the WSL share and reports microsoft,
    # which would send us hunting for DCS under /mnt/c on a machine that has no /mnt.
    if os.name == "nt":
        return False
    try:
        with open("/proc/version") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def no_window():
    """Stop Windows flashing a console window for each helper process we launch.

    Without this a console pops up over the game for every spoken reply and every
    recognised phrase. Windows-only; harmless everywhere else.
    """
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def windows_to_local(path: str) -> str:
    """C:\\Users\\x -> /mnt/c/Users/x when we're running inside WSL."""
    if not running_under_wsl():
        return path
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if not match:
        return path
    drive, rest = match.group(1).lower(), match.group(2).replace("\\", "/")
    return "/mnt/%s/%s" % (drive, rest)


def _expand_windows_vars(value: str) -> str:
    """Expand %USERPROFILE% and friends, including when we're not on Windows."""
    def replace(match):
        name = match.group(1)
        got = os.environ.get(name)
        if got:
            return got
        if name.upper() == "USERPROFILE":
            profile = _windows_userprofile()
            if profile:
                return profile
        return match.group(0)

    return re.sub(r"%([^%]+)%", replace, value)


def _windows_userprofile() -> str | None:
    if os.environ.get("USERPROFILE"):
        return os.environ["USERPROFILE"]
    if not running_under_wsl():
        return None
    try:
        result = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"],
                                capture_output=True, timeout=15, **no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.decode("cp1252", errors="replace").strip()
    return value or None


def saved_games_roots() -> list[Path]:
    """Every plausible "Saved Games" folder, most authoritative first.

    The registry is checked because OneDrive and manual moves routinely relocate this
    folder, and assuming %USERPROFILE%\\Saved Games would then quietly target the wrong
    place.
    """
    roots: list[Path] = []

    def add(candidate: str | None):
        if not candidate:
            return
        local = Path(windows_to_local(_expand_windows_vars(candidate)))
        if local not in roots:
            roots.append(local)

    add(_registry_saved_games())

    profile = _windows_userprofile()
    if profile:
        add(str(Path(windows_to_local(profile)) / "Saved Games"))

    if running_under_wsl():
        users = Path("/mnt/c/Users")
        if users.is_dir():
            for entry in sorted(users.iterdir()):
                if entry.is_dir() and entry.name not in ("Public", "Default", "All Users"):
                    add(str(entry / "Saved Games"))

    return [root for root in roots if root.is_dir()]


def _registry_saved_games() -> str | None:
    """Read the Saved Games known-folder path out of the Windows registry."""
    if not running_under_wsl():
        try:
            import winreg  # noqa: PLC0415 - Windows only
        except ImportError:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                USER_SHELL_FOLDERS.split("\\", 1)[1]) as key:
                value, _ = winreg.QueryValueEx(key, SAVED_GAMES_GUID)
                return value
        except OSError:
            return None

    try:
        result = subprocess.run(
            ["reg.exe", "query", USER_SHELL_FOLDERS, "/v", SAVED_GAMES_GUID],
            capture_output=True, timeout=15, **no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("cp1252", errors="replace")
    match = re.search(r"REG_(?:EXPAND_)?SZ\s+(.+)", text)
    return match.group(1).strip() if match else None


def inspect_path(path: Path, label: str | None = None) -> Installation:
    """Describe a candidate directory, saying plainly how confident we are."""
    path = Path(path)
    notes: list[str] = []
    present = [marker for marker in WRITEDIR_MARKERS if (path / marker).is_dir()]

    if not path.is_dir():
        notes.append("Folder does not exist.")
        verified = False
    elif len(present) >= 2:
        verified = True
    else:
        verified = False
        notes.append(
            "This doesn't look like a DCS folder - expected to find %s inside it."
            % " or ".join(WRITEDIR_MARKERS)
        )

    return Installation(path=path, label=label or path.name, verified=verified, notes=notes)


def find_installations() -> list[Installation]:
    """Every DCS writeable directory we can find. Empty means: ask the user."""
    found: list[Installation] = []
    seen: set[Path] = set()

    for root in saved_games_roots():
        for entry in sorted(root.iterdir()):
            # DCS, DCS.openbeta, DCS.dcs_serverrelease, ...
            if not entry.is_dir() or not entry.name.lower().startswith("dcs"):
                continue
            resolved = entry.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidate = inspect_path(entry)
            if candidate.verified:
                found.append(candidate)

    return found


# ---------- where our own files come from ----------


def resource_root() -> Path:
    """The folder holding lua/, whether running from source or a packaged binary."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent


def missing_sources(root: Path | None = None) -> list[str]:
    """Any ATCAI file we'd need to install but can't find. Empty means good to go."""
    root = Path(root) if root else resource_root()
    missing = []
    for name in SCRIPT_FILES:
        if not (root / "lua" / "atc" / name).is_file():
            missing.append("lua/atc/%s" % name)
    if not (root / "lua" / "hooks" / HOOK_FILE).is_file():
        missing.append("lua/hooks/%s" % HOOK_FILE)
    return missing


# ---------- status ----------


def status(installation: Installation) -> dict:
    """What's installed right now, and what the user should do about it."""
    scripts = installation.scripts_dir
    installed_files = [name for name in SCRIPT_FILES if (scripts / name).is_file()]
    hook_enabled = installation.hook_path.is_file()
    hook_disabled = installation.disabled_hook_path.is_file()

    complete = len(installed_files) == len(SCRIPT_FILES) and (hook_enabled or hook_disabled)
    partial = bool(installed_files) and not complete

    return {
        "installed": complete,
        "partial": partial,
        "enabled": hook_enabled,
        "scripts_present": installed_files,
        "scripts_missing": [n for n in SCRIPT_FILES if n not in installed_files],
        "hook_present": hook_enabled or hook_disabled,
        "config_present": installation.config_path.is_file(),
        "dcs_running": is_dcs_running(),
    }


def is_dcs_running() -> bool:
    """DCS reads hooks only at startup, so a running DCS means 'restart to apply'."""
    try:
        if running_under_wsl() or os.name == "nt":
            result = subprocess.run(["tasklist.exe", "/FI", "IMAGENAME eq DCS.exe"],
                                    capture_output=True, timeout=20, **no_window())
            return b"DCS.exe" in result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return False


# ---------- install / remove ----------


def install(installation: Installation, root: Path | None = None) -> list[str]:
    """Copy the scripts and the loader hook in. Returns what it did."""
    root = Path(root) if root else resource_root()
    missing = missing_sources(root)
    if missing:
        raise FileNotFoundError("ATCAI files are missing: %s" % ", ".join(missing))

    actions = []
    installation.scripts_dir.mkdir(parents=True, exist_ok=True)
    installation.hooks_dir.mkdir(parents=True, exist_ok=True)

    for name in SCRIPT_FILES:
        shutil.copy2(root / "lua" / "atc" / name, installation.scripts_dir / name)
        actions.append("installed %s" % name)

    shutil.copy2(root / "lua" / "hooks" / HOOK_FILE, installation.hook_path)
    actions.append("installed %s" % HOOK_FILE)

    # A previous disable leaves a stale copy that would otherwise be resurrected later.
    if installation.disabled_hook_path.is_file():
        installation.disabled_hook_path.unlink()
        actions.append("removed the disabled hook left over from before")

    return actions


def uninstall(installation: Installation, remove_config: bool = False) -> list[str]:
    """Remove everything we installed. Settings are kept unless asked otherwise."""
    actions = []

    for path in (installation.hook_path, installation.disabled_hook_path):
        if path.is_file():
            path.unlink()
            actions.append("removed %s" % path.name)

    for name in SCRIPT_FILES:
        target = installation.scripts_dir / name
        if target.is_file():
            target.unlink()
            actions.append("removed %s" % name)

    if remove_config and installation.config_path.is_file():
        installation.config_path.unlink()
        actions.append("removed config.lua")

    inbox = installation.scripts_dir / "inbox.lua"
    if inbox.is_file():
        inbox.unlink()
        actions.append("removed inbox.lua")

    # Only tidy the folder away if nothing of the user's is left in it.
    if installation.scripts_dir.is_dir() and not any(installation.scripts_dir.iterdir()):
        installation.scripts_dir.rmdir()
        actions.append("removed the ATCAI folder")

    return actions


def set_enabled(installation: Installation, enabled: bool) -> list[str]:
    """Turn ATCAI on or off by moving the hook aside, keeping scripts and settings."""
    if enabled:
        if installation.hook_path.is_file():
            return []
        if installation.disabled_hook_path.is_file():
            installation.disabled_hook_path.rename(installation.hook_path)
            return ["enabled ATCAI"]
        raise FileNotFoundError("ATCAI is not installed, so it cannot be enabled.")

    if installation.disabled_hook_path.is_file() and not installation.hook_path.is_file():
        return []
    if not installation.hook_path.is_file():
        raise FileNotFoundError("ATCAI is not installed, so it cannot be disabled.")
    if installation.disabled_hook_path.is_file():
        installation.disabled_hook_path.unlink()
    installation.hook_path.rename(installation.disabled_hook_path)
    return ["disabled ATCAI"]


# ---------- settings ----------


def lua_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def render_config(settings: dict) -> str:
    """Turn settings into the Lua table atc_config.lua reads."""
    lines = [
        "-- Written by the ATCAI manager. Values here override the script defaults.",
        "ATCAI_CONFIG = {",
    ]
    for key in sorted(settings):
        value = settings[key]
        expected = CONFIG_FIELDS.get(key)
        if expected is None:
            raise ValueError("unknown setting: %s" % key)
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ValueError("%s has the wrong type" % key)
        if isinstance(value, str):
            rendered = lua_quote(value)
        else:
            if value <= 0:
                raise ValueError("%s must be positive" % key)
            rendered = repr(float(value)) if isinstance(value, float) else str(value)
        lines.append("    %s = %s," % (key, rendered))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_config(installation: Installation, settings: dict) -> Path:
    installation.scripts_dir.mkdir(parents=True, exist_ok=True)
    target = installation.config_path
    temp = target.with_suffix(".lua.tmp")
    temp.write_text(render_config(settings), encoding="utf-8")
    # The mission may dofile() this at any moment, so swap it in atomically.
    os.replace(temp, target)
    return target


def read_config(installation: Installation) -> dict:
    """Read settings back. Deliberately forgiving: unreadable means 'no settings'."""
    path = installation.config_path
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    settings: dict = {}
    for key, expected in CONFIG_FIELDS.items():
        match = re.search(r'\b%s\s*=\s*("([^"]*)"|[-\d.]+)' % re.escape(key), text)
        if not match:
            continue
        if match.group(2) is not None:
            settings[key] = match.group(2)
        else:
            raw = match.group(1)
            settings[key] = float(raw) if "." in raw else int(raw)
    return settings
