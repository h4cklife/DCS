#!/usr/bin/env python3
"""The banner shown while the Manager starts.

Branding, not a progress indicator, and the distinction matters. A single-file exe spends
several seconds unpacking itself before Python exists, and Tk cannot draw until after
that - so this appears once the app is essentially ready, not during the wait anyone
actually notices. Covering that gap needs PyInstaller's own bootloader splash, which is a
separate thing and deliberately not mixed in here.

Kept out of App so the window class stays unchanged and the GUI tests do not have to
dismiss a splash they never asked for. The timing is a plain function for the same
reason: a test that waits five real seconds is a test people stop running.
"""

from __future__ import annotations

import os
import sys
import time

try:
    import tkinter as tk
except ImportError:                     # a Python built without Tk, or a headless box
    # Not an error here. image_path() is pure path arithmetic and is needed by the
    # packaging test, which runs where there is no Tk; show() treats a missing Tk as
    # one more reason to carry on without a splash.
    tk = None

IMAGE_NAME = "ATCAI_Splash.png"

# "At least five seconds", taken literally - see remaining_ms.
MINIMUM_MS = 5000


def resource_dir():
    """Where bundled files are: the exe's extraction folder, or the repo.

    The "assets" segment is added by the caller, matching what build_exe's BUNDLED
    declares. Getting this level wrong is what made the 1.7.0 exe load an empty phrase
    list, so test_wiring checks this path alongside the others.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return bundled
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def image_path():
    return os.path.join(resource_dir(), "assets", IMAGE_NAME)


def centred_geometry(screen, width, height):
    """A Tk geometry string putting a width x height window in the middle of the screen.

    Takes anything with winfo_screenwidth/winfo_screenheight so it can be tested without
    a display. Shared by the splash and the main window: they appear one after the other
    in the same place, and two copies of this arithmetic would eventually disagree.

    Offsets are clamped at zero. On a screen smaller than the window, centring would
    otherwise give a negative offset and push the title bar off the top, leaving a window
    that cannot be moved.
    """
    x = max(0, (screen.winfo_screenwidth() - width) // 2)
    y = max(0, (screen.winfo_screenheight() - height) // 2)
    return "%dx%d+%d+%d" % (width, height, x, y)


def remaining_ms(elapsed_ms, minimum=MINIMUM_MS):
    """How much longer the splash should stay up, given how long startup has taken.

    "At least five seconds" cuts both ways: a fast start is held to the full five, and a
    slow one is never cut short to meet it. So a seven-second startup shows the banner
    for seven seconds, not five, and never five-plus-seven.
    """
    return max(0, int(minimum - elapsed_ms))


class Splash:
    """The borderless banner window. Every failure path ends in "no splash, carry on".

    A splash screen that can stop the Manager opening would be worse than no splash
    screen, so a missing file, an image Tk cannot decode and a machine with no display
    all degrade to the same thing: show() returns False and the caller goes straight to
    the main window.
    """

    def __init__(self, master, path=None, clock=time.monotonic, on_log=None):
        self.master = master
        self.path = path or image_path()
        self.clock = clock
        self.on_log = on_log or (lambda message: None)
        self.window = None
        self.image = None
        self.started_at = None
        self._dismissed = False
        self.on_dismiss = None          # set by the caller; fired by a click or Esc

    def show(self):
        """True if the banner is up. False means carry on without it."""
        self.started_at = self.clock()
        if tk is None:
            self.on_log("splash skipped: this Python has no tkinter")
            return False
        if not os.path.isfile(self.path):
            self.on_log("no splash image at %s" % self.path)
            return False
        try:
            self.image = tk.PhotoImage(master=self.master, file=self.path)
            self.window = self._build(self.image)
        except Exception as exc:                        # unreadable image, no display
            self.on_log("splash skipped: %r" % exc)
            self.window = None
            self.image = None
            return False
        return True

    def _build(self, image):
        window = tk.Toplevel(self.master)
        window.overrideredirect(True)                   # the window is the image
        window.attributes("-topmost", True)

        window.geometry(centred_geometry(window, image.width(), image.height()))

        # The banner is dark, and with no title bar it would otherwise bleed into a dark
        # desktop and read as a floating sprite rather than a window.
        frame = tk.Frame(window, highlightthickness=1, highlightbackground="#555",
                         bd=0)
        frame.pack(fill="both", expand=True)
        label = tk.Label(frame, image=image, bd=0)
        label.pack()

        # Three ways out, because the button is discoverable and the others are what
        # people actually try.
        close = tk.Button(frame, text="Dismiss", command=self._request_dismiss,
                          bd=0, padx=10, pady=2, highlightthickness=0,
                          cursor="hand2")
        # Placed rather than packed, so adding it cannot change the window's size away
        # from the image's own.
        close.place(relx=1.0, rely=1.0, x=-10, y=-8, anchor="se")

        for widget in (window, frame, label):
            widget.bind("<Button-1>", lambda _: self._request_dismiss())
        window.bind("<Escape>", lambda _: self._request_dismiss())
        window.bind("<Key>", lambda _: self._request_dismiss())
        window.focus_set()

        window.update_idletasks()
        window.update()                                 # paint before the app is built
        return window

    def elapsed_ms(self):
        if self.started_at is None:
            return 0
        return (self.clock() - self.started_at) * 1000.0

    def remaining_ms(self):
        """What to hand tk's after(). Zero once five seconds have already passed."""
        return remaining_ms(self.elapsed_ms())

    def _request_dismiss(self):
        if self.on_dismiss:
            self.on_dismiss()
        else:
            self.dismiss()

    def dismiss(self):
        """Idempotent: a click and the timer both arrive, in either order."""
        if self._dismissed:
            return
        self._dismissed = True
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        self.window = None
        self.image = None

    @property
    def dismissed(self):
        return self._dismissed
