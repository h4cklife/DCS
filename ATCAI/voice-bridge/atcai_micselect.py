"""Choosing which microphone ATCAI listens to.

`System.Speech` has no device-selection API - it opens whatever SAPI's default audio
input token points at. That token is writable without elevation, and was verified on
2026-10-25 to be what System.Speech actually honours: pinned to each of three devices in
turn, the engine opened exactly that device each time, confirmed through Core Audio's
session API rather than inferred.

So selection needs no change to the recogniser at all, and it affects **speech
applications only** - Windows' own default recording device is untouched, so Discord,
SRS and the rest carry on unaffected.
"""

import os
import subprocess

import atcai_listen

WINDOWS_DEFAULT = "windows-default"


def parse_line(line):
    """One line of micselect.ps1 output -> (kind, payload), or None.

    Kinds: CURRENT (token id or "windows-default"), WINDOWS_DEFAULT (what following
    Windows currently resolves to), INPUT ((id, name)), OK, ERROR.
    """
    line = (line or "").strip()
    if not line or "|" not in line:
        return None

    kind, _, rest = line.partition("|")
    kind = kind.strip().upper()

    if kind == "INPUT":
        token, _, name = rest.partition("|")
        token, name = token.strip(), name.strip()
        if not token or not name:
            return None
        return kind, (token, name)
    if kind in ("CURRENT", "WINDOWS_DEFAULT", "OK", "ERROR"):
        return kind, rest.strip()
    return None


def _run(arguments, timeout=30):
    """Run micselect.ps1 and return its parsed lines."""
    script = os.path.join(atcai_listen.resource_dir(), "micselect.ps1")
    if not os.path.exists(script):
        return [("ERROR", "microphone selector script missing: %s" % script)]

    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", script] + list(arguments)
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                **atcai_listen.no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        return [("ERROR", "could not run the microphone selector: %s" % exc)]

    lines = []
    for raw in (result.stdout or b"").decode("cp1252", errors="replace").splitlines():
        parsed = parse_line(raw)
        if parsed:
            lines.append(parsed)
    return lines


def list_devices():
    """(current, windows_default_name, [(token_id, name), ...]).

    current is a token id, the string "windows-default", or None if it couldn't be
    read. An empty device list means something went wrong, not that there are none.
    """
    current, resolved, devices = None, None, []
    for kind, payload in _run(["-List"]):
        if kind == "CURRENT":
            current = payload
        elif kind == "WINDOWS_DEFAULT":
            resolved = payload
        elif kind == "INPUT":
            devices.append(payload)
    return current, resolved, devices


def select(token_id):
    """Pin ATCAI's microphone. Returns (ok, message)."""
    if not token_id or token_id == WINDOWS_DEFAULT:
        return use_windows_default()
    return _result(_run(["-Set", token_id]))


def use_windows_default():
    """Go back to following whatever Windows picks. Returns (ok, message)."""
    return _result(_run(["-UseWindowsDefault"]))


def _result(lines):
    for kind, payload in lines:
        if kind == "ERROR":
            return False, payload
    for kind, payload in lines:
        if kind == "OK":
            return True, payload
    return False, "the microphone selector said nothing"


def name_for(token_id, devices):
    """Readable name for a token id, given a device list."""
    if not token_id or token_id == WINDOWS_DEFAULT:
        return "Windows default"
    for candidate, name in devices or []:
        if candidate == token_id:
            return name
    return "a microphone that is no longer available"
