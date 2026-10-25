"""Stop a second Manager starting, and show the one already running instead.

Not cosmetic. Two Managers each start their own voice bridges, so both tail dcs.log and
transmit every ATC reply, and both try to hold the microphone. The symptoms - doubled
speech, a microphone that behaves as though something else has it - look like bugs in
the module rather than like two copies running.

A named mutex rather than a lock file: Windows releases it when the process dies, so a
crash cannot leave the app permanently convinced it is already running.
"""

import ctypes
import os
from ctypes import wintypes

MUTEX_NAME = "Global\\ATCAI-Manager-single-instance"

ERROR_ALREADY_EXISTS = 183


def available():
    return os.name == "nt"


class Lock(object):
    """Holds the single-instance mutex for the life of the process.

    acquire() returns True when this is the only copy. The handle is deliberately kept
    on the instance: letting it be collected would release the mutex and allow a second
    Manager to start while the first is still running.
    """

    def __init__(self, name=MUTEX_NAME, kernel32=None, last_error=None):
        self.name = name
        self._kernel32 = kernel32
        # ctypes.get_last_error exists only on Windows, so it is reached through here
        # rather than directly - otherwise the module cannot be tested anywhere else.
        self._last_error = last_error
        self._handle = None
        self.already_running = False

    def _error(self):
        if self._last_error is not None:
            return self._last_error()
        return ctypes.get_last_error()

    def _api(self):
        if self._kernel32 is not None:
            return self._kernel32
        return ctypes.WinDLL("kernel32", use_last_error=True)

    def acquire(self):
        if not available():
            return True                      # nothing to enforce off Windows
        try:
            kernel32 = self._api()
            handle = kernel32.CreateMutexW(None, False, self.name)
            if not handle:
                return True                  # cannot tell; do not block startup
            if self._error() == ERROR_ALREADY_EXISTS:
                self.already_running = True
                kernel32.CloseHandle(handle)
                return False
            self._handle = handle
            return True
        except Exception:
            # A failure to check must never stop the app starting - the worst case is
            # the behaviour we have today.
            return True

    def release(self):
        if self._handle and available():
            try:
                self._api().CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None


def show_existing_window(title_prefix="ATCAI Manager", user32=None):
    """Bring the Manager that is already running to the front.

    Exiting silently would look like the app failing to start, so the second launch
    surfaces the first instead of just disappearing.
    """
    if not available():
        return False
    try:
        api = user32 or ctypes.WinDLL("user32", use_last_error=True)
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _param):
            length = api.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                api.GetWindowTextW(hwnd, buffer, length + 1)
                if buffer.value.startswith(title_prefix):
                    found.append(hwnd)
                    return False
            return True

        api.EnumWindows(visit, 0)
        if not found:
            return False
        api.ShowWindow(found[0], 9)           # SW_RESTORE, in case it is minimised
        api.SetForegroundWindow(found[0])
        return True
    except Exception:
        return False
