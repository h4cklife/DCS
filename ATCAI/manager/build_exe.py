#!/usr/bin/env python3
"""Build the standalone ATCAI Manager executable.

    python build_exe.py

Produces dist/ATCAI-Manager.exe (Windows) or dist/ATCAI-Manager (Linux) — a single file
with Python, Tkinter and every ATCAI script bundled inside, so the people you give it to
install nothing.

This must run on the platform you're building for: PyInstaller does not cross-compile,
so a Windows .exe has to be built from Windows Python. Under WSL it will look for a
Windows Python and use that.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "ATCAI-Manager"

# (what to bundle, where it lands inside the executable)
BUNDLED = [
    (ROOT / "lua", "lua"),
    (ROOT / "voice-bridge" / "recognize.ps1", "voice-bridge"),
    (ROOT / "voice-bridge" / "mictest.ps1", "voice-bridge"),
]


def running_under_wsl() -> bool:
    try:
        with open("/proc/version") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def windows_python() -> str | None:
    """A real Windows Python, not the Microsoft Store stub that just prints an advert.

    The stub answers --version with "Python was not found...", so the check has to look
    at what came back rather than trusting the exit code.
    """
    candidates = ["py.exe", "python.exe", "python3.exe"]
    # The usual per-user install location, in case it isn't on PATH.
    from glob import glob
    candidates += sorted(glob("/mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe"),
                         reverse=True)

    for candidate in candidates:
        try:
            result = subprocess.run([candidate, "--version"], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        text = (result.stdout + result.stderr).decode("cp1252", errors="replace").strip()
        if "was not found" in text.lower():
            continue                              # Microsoft Store stub
        if result.returncode == 0 and text.lower().startswith("python"):
            return candidate
    return None


def separator(for_windows: bool) -> str:
    # PyInstaller splits --add-data on ';' for Windows and ':' elsewhere.
    return ";" if for_windows else ":"


def build_command(python: str, for_windows: bool) -> list[str]:
    command = [
        python, "-m", "PyInstaller",
        "--onefile",
        "--windowed",                       # no console window behind the GUI
        "--name", NAME,
        "--paths", str(ROOT / "manager"),
        "--paths", str(ROOT / "voice-bridge"),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--noconfirm",
    ]
    for source, target in BUNDLED:
        command += ["--add-data", "%s%s%s" % (source, separator(for_windows), target)]
    command.append(str(ROOT / "manager" / "app.py"))
    return command


def main() -> int:
    for source, _ in BUNDLED:
        if not source.exists():
            print("missing: %s" % source, file=sys.stderr)
            return 1

    if running_under_wsl():
        python = windows_python()
        if not python:
            print(
                "No Windows Python found.\n\n"
                "PyInstaller cannot cross-compile, so building ATCAI-Manager.exe needs\n"
                "Python installed on Windows (python.org, tick 'Add to PATH'), then:\n"
                "    py -m pip install pyinstaller\n\n"
                "Alternatively build it on a Windows machine, or in CI on a Windows\n"
                "runner, and only distribute the resulting .exe.",
                file=sys.stderr,
            )
            return 2
        for_windows = True
    else:
        python = sys.executable
        for_windows = os.name == "nt"

    command = build_command(python, for_windows)
    print(" ".join(command))
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        return result.returncode

    built = ROOT / "dist" / (NAME + (".exe" if for_windows else ""))
    print("\nBuilt %s" % built)
    print("Hand that single file to anyone with DCS - they need nothing else installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
