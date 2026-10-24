"""Sending keystrokes to DCS, and refusing to send them anywhere else.

Kept apart from atcai_keys.py on purpose: that module decides *what* a spoken command
means and touches no OS API, which keeps it testable anywhere and keeps the dangerous
part in one small file you can read in full.

Two things here matter more than the rest:

  * **Scan codes, not virtual keys.** DCS reads the keyboard through DirectInput, which
    commonly ignores virtual-key SendInput entirely. A first attempt that appears to do
    nothing is usually this.

  * **The foreground guard.** Keys go to whatever window has focus. If DCS is not
    focused we send nothing, because the alternative is typing F-keys and backslashes
    into a browser, an editor or a Discord message box. This is not a setting.
"""

import ctypes
import os
import time
from ctypes import wintypes

DCS_PROCESS = "DCS.exe"

# Set 1 scan codes. The comms menu only needs the function keys plus a few punctuation
# keys people bind the menu to.
SCANCODES = {
    "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E, "F5": 0x3F, "F6": 0x40,
    "F7": 0x41, "F8": 0x42, "F9": 0x43, "F10": 0x44, "F11": 0x57, "F12": 0x58,
    "escape": 0x01, "esc": 0x01,
    "backslash": 0x2B, "\\": 0x2B,
    "grave": 0x29, "`": 0x29,
    "ralt": 0x38, "rctrl": 0x1D,
    "slash": 0x35, "/": 0x35,
    "semicolon": 0x27, ";": 0x27,
    "comma": 0x33, ",": 0x33,
    "period": 0x34, ".": 0x34,
    "minus": 0x0C, "-": 0x0C,
    "equals": 0x0D, "=": 0x0D,
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12, "f": 0x21,
    "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24, "k": 0x25, "l": 0x26,
    "m": 0x32, "n": 0x31, "o": 0x18, "p": 0x19, "q": 0x10, "r": 0x13,
    "s": 0x1F, "t": 0x14, "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D,
    "y": 0x15, "z": 0x2C,
}

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_KEYBOARD = 1

# F11/F12 and a few others are extended keys; the flag has to be set or they arrive
# as something else.
EXTENDED = {"F11", "F12", "rctrl", "ralt"}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def available():
    """True when this platform can send keys at all."""
    return os.name == "nt"


# Case-insensitive lookup, built once. A hand-edited key map may well say "f5" or
# "BACKSLASH", and either should work.
_BY_LOWER = {name.lower(): code for name, code in SCANCODES.items()}
_EXTENDED_LOWER = {name.lower() for name in EXTENDED}


def scancode_for(name):
    """Scan code for a key name, or None if we don't know it."""
    if not name:
        return None
    return _BY_LOWER.get(str(name).lower())


def is_extended(name):
    """Extended keys need their own flag or they arrive as something else."""
    return str(name or "").lower() in _EXTENDED_LOWER


def unknown_keys(keys):
    """Which of these key names we cannot send. Empty means the sequence is sendable."""
    return [k for k in (keys or []) if scancode_for(k) is None]


# ---------- the Windows plumbing, isolated so everything above stays testable ----------

if available():
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_ubyte * 32)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]
else:                                                  # pragma: no cover - non-Windows
    _user32 = _kernel32 = None


def foreground_process():
    """Executable name of the window that currently has focus, lowercased.

    Returns None when it cannot be determined - which the guard treats as "not DCS",
    because an unknown window is exactly the case we must not type into.
    """
    if not available():
        return None
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                       pid.value)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                        ctypes.byref(size)):
                return None
            return os.path.basename(buffer.value).lower()
        finally:
            _kernel32.CloseHandle(handle)
    except Exception:
        return None


def _tap(scancode, extended, hold_ms):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    down = _INPUT(type=INPUT_KEYBOARD,
                  union=_INPUTunion(ki=_KEYBDINPUT(0, scancode, flags, 0, None)))
    up = _INPUT(type=INPUT_KEYBOARD,
                union=_INPUTunion(ki=_KEYBDINPUT(
                    0, scancode, flags | KEYEVENTF_KEYUP, 0, None)))

    sent = _user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    if sent != 1:
        return False
    time.sleep(max(hold_ms, 1) / 1000.0)
    sent = _user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
    return sent == 1


class SendKeys(object):
    """Sends a key sequence to DCS, or explains why it won't.

    sender/focus are injectable so the decision and guard logic can be tested without
    a keyboard: nothing here reaches the real SendInput in a test run.
    """

    name = "win32"

    def __init__(self, target_process=DCS_PROCESS, sender=None, focus=None,
                 hold_ms=30, sleep=None):
        self.target_process = (target_process or DCS_PROCESS).lower()
        self._sender = sender or (lambda code, extended: _tap(code, extended, hold_ms))
        self._focus = focus or foreground_process
        self._sleep = sleep or time.sleep
        self.sent = []
        self.last_error = None

    def focused_on_target(self):
        return self._focus() == self.target_process

    def send(self, keys, delay_ms=90):
        """True when the whole sequence went out. False and last_error otherwise."""
        self.last_error = None

        if not available():
            self.last_error = "sending keys needs Windows"
            return False

        missing = unknown_keys(keys)
        if missing:
            self.last_error = "key map uses keys I cannot send: %s" % ", ".join(missing)
            return False

        # Checked immediately before sending, so alt-tabbing away mid-command cannot
        # land the rest of the sequence somewhere else.
        if not self.focused_on_target():
            where = self._focus() or "an unknown window"
            self.last_error = ("DCS is not the active window (%s is) - nothing sent"
                               % where)
            return False

        for index, key in enumerate(keys):
            if not self.focused_on_target():
                self.last_error = ("focus left DCS part-way through - stopped after "
                                   "%d of %d keys" % (index, len(keys)))
                return False
            if not self._sender(scancode_for(key), is_extended(key)):
                self.last_error = "Windows refused the keystroke for %s" % key
                return False
            self.sent.append(key)
            if index + 1 < len(keys):
                self._sleep(max(delay_ms, 0) / 1000.0)
        return True
