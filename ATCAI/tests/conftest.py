"""Shared fixtures.

The modules under test are plain scripts rather than an installed package, so the
import paths are set up here once.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "manager"))
sys.path.insert(0, str(ROOT / "voice-bridge"))

# What DCS itself creates in its writeable folder; enough of these make it recognisable.
DCS_MARKERS = ("Config", "Logs", "Missions", "Mods")


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def fake_dcs(tmp_path) -> Path:
    """A directory that passes as a DCS writeable folder, with nothing installed."""
    path = tmp_path / "Saved Games" / "DCS"
    for marker in DCS_MARKERS:
        (path / marker).mkdir(parents=True)
    return path


@pytest.fixture
def installation(fake_dcs):
    import installer
    return installer.inspect_path(fake_dcs)


@pytest.fixture
def installed(installation, repo_root):
    """A DCS folder with ATCAI already installed into it."""
    import installer
    installer.install(installation, repo_root)
    return installation


@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    """Redirect the manager's preferences to a throwaway file."""
    import prefs
    target = tmp_path / "manager.json"
    monkeypatch.setattr(prefs, "prefs_path", lambda: target)
    return target


# Platform is faked by overriding the one function that decides it, never by patching
# os.name: pathlib picks WindowsPath vs PosixPath from os.name at construction time, so
# patching it globally quietly breaks every filesystem check in the test.


@pytest.fixture
def on_windows(monkeypatch):
    """Make the code under test believe it is running on native Windows."""
    import installer
    monkeypatch.setattr(installer, "running_under_wsl", lambda: False)


@pytest.fixture
def on_wsl(monkeypatch):
    """Make the code under test believe it is running under WSL."""
    import installer
    monkeypatch.setattr(installer, "running_under_wsl", lambda: True)


def dcs_lua() -> Path | None:
    """DCS ships its own Lua 5.1 interpreter; the Lua suites run on it."""
    override = os.environ.get("DCS_BIN")
    candidates = [Path(override)] if override else []
    candidates.append(Path("/mnt/c/Program Files (x86)/Steam/steamapps/common/DCSWorld/bin"))
    candidates.append(Path(r"C:\Program Files (x86)\Steam\steamapps\common\DCSWorld\bin"))
    for base in candidates:
        exe = base / "luae.exe"
        try:
            if exe.is_file():
                return exe
        except OSError:
            # A WSL-style path checked from Windows raises rather than returning False.
            continue
    return None
