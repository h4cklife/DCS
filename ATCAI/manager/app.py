#!/usr/bin/env python3
"""ATCAI Manager — install, enable, configure and run ATCAI without a command line.

Everything here is a thin layer over installer.py and the two voice bridges; the
interesting logic lives there and is tested separately.

Written for people who have never opened a terminal, so: no jargon in the interface,
every failure says what to do about it, and nothing silently assumes where DCS lives.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "voice-bridge"))

import installer  # noqa: E402
import prefs  # noqa: E402
import single_instance  # noqa: E402
import splash  # noqa: E402
import atcai_listen  # noqa: E402
import atcai_tts  # noqa: E402
import atcai_mictest  # noqa: E402
import atcai_micselect  # noqa: E402
import atcai_bindings  # noqa: E402
import atcai_cockpit  # noqa: E402
import atcai_keys  # noqa: E402
import atcai_phrases  # noqa: E402
import atcai_sendkeys  # noqa: E402

VERSION = "1.8.0"
PAD = 8


class Bridge:
    """A background worker (voice input or spoken replies) with a start/stop button."""

    def __init__(self, name, target, log):
        self.name = name
        self.target = target          # (options, on_log, should_stop) -> None
        self.log = log
        self.thread = None
        self.stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, options):
        if self.running:
            return
        self.stop_event.clear()

        def work():
            try:
                self.target(options, lambda m: self.log(self.name, m), self.stop_event.is_set)
            except Exception as exc:                      # never take the GUI down
                self.log(self.name, "! stopped unexpectedly: %r" % exc)

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=PAD)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.installation: installer.Installation | None = None
        self.messages: queue.Queue = queue.Queue()
        self.mic_events: queue.Queue = queue.Queue()
        self.prefs = prefs.load()
        self.ptt_key_name = str(self.prefs.get("ptt_key_name", "Ctrl"))
        # Phrase changes live in their own file rather than in prefs: they are a
        # difference against the shipped list, not a setting. See atcai_phrases.
        self.phrase_overlay, self._phrase_problems = atcai_phrases.load_overlay()
        self.phrase_switches = {}
        # Saving is suppressed until start-up finishes: _detect() runs before the
        # controls are seeded, and would otherwise write defaults over saved settings.
        self._ready = False

        self.listener = Bridge("voice", self._run_listener, self._enqueue)
        self.speaker = Bridge("replies", self._run_speaker, self._enqueue)

        self._build()
        self._enqueue("app", "ATCAI Manager %s started." % VERSION)
        self._detect()
        self._restore_voice_preferences()
        self.after(150, self._drain)

    # ---------- layout ----------

    def _build(self):
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="DCS folder:").grid(row=0, column=0, sticky="w")
        self.folder_choice = ttk.Combobox(header, state="readonly", width=60)
        self.folder_choice.grid(row=0, column=1, sticky="ew", padx=(PAD, PAD))
        self.folder_choice.bind("<<ComboboxSelected>>", lambda _: self._choose_detected())
        ttk.Button(header, text="Choose folder...", command=self._browse).grid(row=0, column=2)

        self.warning = ttk.Label(header, foreground="#b45309", wraplength=760, justify="left")
        self.warning.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tabs = ttk.Notebook(self)
        tabs.grid(row=1, column=0, sticky="nsew", pady=(PAD, 0))
        # One job per tab. The Voice tab used to carry all three of these plus the
        # microphone test, and had grown taller than the window.
        self._build_setup(tabs)
        self._build_talking(tabs)
        self._build_mic(tabs)
        self._build_hearing(tabs)
        self._build_comms(tabs)
        self._build_cockpit(tabs)
        self._build_voice_commands(tabs)
        self._build_settings(tabs)
        self._build_log(tabs)

    def _build_setup(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Setup")
        tab.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(tab, justify="left", wraplength=760)
        self.status_label.grid(row=0, column=0, sticky="w")

        buttons = ttk.Frame(tab)
        buttons.grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        self.install_button = ttk.Button(buttons, text="Install", command=self._install)
        self.install_button.grid(row=0, column=0, padx=(0, PAD))
        self.enable_button = ttk.Button(buttons, text="Turn off", command=self._toggle_enabled)
        self.enable_button.grid(row=0, column=1, padx=(0, PAD))
        self.uninstall_button = ttk.Button(buttons, text="Remove", command=self._uninstall)
        self.uninstall_button.grid(row=0, column=2)

        ttk.Label(tab, wraplength=760, justify="left", text=(
            "Install copies ATCAI into DCS. It then works in every mission you fly - "
            "nothing to set up per mission.\n"
            "DCS only loads it at startup, so restart DCS after installing or turning "
            "it on or off.\n\n"
            "In the cockpit, open the comms menu with the \\ key, then choose "
            "'Other' and 'ATCAI'."
        )).grid(row=2, column=0, sticky="w", pady=(PAD, 0))

        self.voice_hint = ttk.Label(tab, foreground="#b45309", wraplength=760,
                                    justify="left")
        self.voice_hint.grid(row=3, column=0, sticky="w", pady=(PAD, 0))

    def _build_talking(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Talking to ATC")
        tab.columnconfigure(0, weight=1)

        talk = ttk.LabelFrame(tab, text="Talking to ATC", padding=PAD)
        talk.grid(row=0, column=0, sticky="ew")
        self.listen_button = ttk.Button(talk, text="Start listening",
                                        command=lambda: self._toggle(self.listener))
        self.listen_button.grid(row=0, column=0, sticky="w")
        self.listen_state = ttk.Label(talk, text="Not listening", foreground="#b45309")
        self.listen_state.grid(row=0, column=1, sticky="w", padx=(PAD, 0))

        ttk.Label(talk, text="How sure it must be:").grid(row=1, column=0, sticky="w",
                                                          pady=(PAD, 0))
        self.confidence = tk.DoubleVar(value=0.6)
        ttk.Scale(talk, from_=0.3, to=0.95, variable=self.confidence,
                  orient="horizontal", length=240).grid(row=1, column=1, sticky="w",
                                                        pady=(PAD, 0))
        self.strict = tk.BooleanVar(value=False)
        ttk.Checkbutton(talk, variable=self.strict,
                        text="Only react to the exact request, with nothing else said"
                        ).grid(row=2, column=0, columnspan=2, sticky="w")
        self.auto_voice = tk.BooleanVar(value=False)
        ttk.Checkbutton(talk, variable=self.auto_voice, command=self._remember,
                        text="Start this automatically when the app opens"
                        ).grid(row=3, column=0, columnspan=2, sticky="w")

        ptt = ttk.Frame(talk)
        ptt.grid(row=5, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        self.ptt_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(ptt, variable=self.ptt_enabled, command=self._on_ptt_toggled,
                        text="Only listen while I hold a key (push-to-talk)"
                        ).grid(row=0, column=0, sticky="w")

        self.ptt_key_code = 0x11
        self.ptt_key_label = ttk.Label(ptt, text="Key: Ctrl")
        self.ptt_key_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.ptt_button = ttk.Button(ptt, text="Change key...", command=self._capture_ptt_key)
        self.ptt_button.grid(row=1, column=1, sticky="w", padx=(PAD, 0), pady=(4, 0))
        ttk.Label(ptt, wraplength=700, justify="left", foreground="#555", text=(
            "Leave this off to have ATC listen all the time. Turn it on if you talk on "
            "Discord or TeamSpeak while flying, so ATC only hears you when you mean it."
        )).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(talk, wraplength=700, justify="left", text=(
            'Say things like "Chevy 81, requesting taxi" or "ready for takeoff". '
            "Raise the slider if it reacts when you did not mean it to."
        )).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _build_mic(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Test Microphone")
        tab.columnconfigure(0, weight=1)

        mic = ttk.LabelFrame(tab, text="Test microphone", padding=PAD)
        mic.grid(row=0, column=0, sticky="ew")
        mic.columnconfigure(1, weight=1)

        mic_buttons = ttk.Frame(mic)
        mic_buttons.grid(row=0, column=0, columnspan=2, sticky="w")
        self.mic_button = ttk.Button(mic_buttons, text="Test microphone",
                                     command=self._start_mic_test)
        self.mic_button.grid(row=0, column=0, sticky="w")
        self.mic_list_button = ttk.Button(mic_buttons, text="Show microphones",
                                          command=self._refresh_inputs)
        self.mic_list_button.grid(row=0, column=1, sticky="w", padx=(PAD, 0))
        self.mic_settings_button = ttk.Button(mic_buttons, text="Windows sound settings...",
                                              command=self._open_sound_settings)
        self.mic_settings_button.grid(row=0, column=2, sticky="w", padx=(PAD, 0))

        chooser = ttk.Frame(mic)
        chooser.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        ttk.Label(chooser, text="Use this microphone:").grid(row=0, column=0, sticky="w")
        self.mic_choice = ttk.Combobox(chooser, state="readonly", width=44)
        self.mic_choice.grid(row=0, column=1, sticky="w", padx=(PAD, 0))
        self.mic_choice.bind("<<ComboboxSelected>>", lambda _: self._choose_microphone())
        ttk.Button(chooser, text="Refresh", command=self._refresh_microphones
                   ).grid(row=0, column=2, sticky="w", padx=(PAD, 0))

        ttk.Label(mic, wraplength=700, justify="left", foreground="#555", text=(
            "This sets the microphone for speech programs only - Windows' own default "
            "recording device is left alone, so Discord, SRS and everything else are "
            "unaffected. Restart listening after changing it."
        )).grid(row=2, column=0, columnspan=2, sticky="w")

        self.mic_device = ttk.Label(mic, text="Press to check what ATCAI can hear.",
                                    foreground="#555", wraplength=700, justify="left")
        self.mic_device.grid(row=3, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        self.mic_inputs = ttk.Label(mic, text="", foreground="#555", wraplength=700,
                                    justify="left")
        self.mic_inputs.grid(row=4, column=0, columnspan=2, sticky="w")

        ttk.Label(mic, text="Input level:").grid(row=5, column=0, sticky="w",
                                                 pady=(PAD, 0))
        self.mic_level = tk.IntVar(value=0)
        ttk.Progressbar(mic, orient="horizontal", length=240, mode="determinate",
                        maximum=100, variable=self.mic_level
                        ).grid(row=5, column=1, sticky="w", pady=(PAD, 0))

        self.mic_results = tk.Text(mic, height=8, wrap="word", state="disabled")
        self.mic_results.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))

        ttk.Label(mic, wraplength=700, justify="left", foreground="#555", text=(
            "Runs for 15 seconds. Say a request you would use in the air, like "
            '"Chevy 81, requesting taxi". It reports which microphone is in use, '
            "whether any sound is arriving, and what it heard - including anything it "
            "heard but could not match, which is invisible while flying."
        )).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._refresh_microphones()

    def _build_hearing(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Hearing ATC")
        tab.columnconfigure(0, weight=1)

        reply = ttk.LabelFrame(tab, text="Hearing ATC", padding=PAD)
        reply.grid(row=0, column=0, sticky="ew")
        self.speak_button = ttk.Button(reply, text="Start replies",
                                       command=lambda: self._toggle(self.speaker))
        self.speak_button.grid(row=0, column=0, sticky="w")
        self.speak_state = ttk.Label(reply, text="Not running - you will hear nothing",
                                     foreground="#b45309")
        self.speak_state.grid(row=0, column=1, sticky="w", padx=(PAD, 0))

        self.tts_mode = tk.StringVar(value="local")
        ttk.Radiobutton(reply, text="Play on this PC's speakers", value="local",
                        variable=self.tts_mode).grid(row=1, column=0, sticky="w",
                                                     pady=(PAD, 0))
        ttk.Radiobutton(reply, text="Send over the radio using SRS", value="srs",
                        variable=self.tts_mode).grid(row=2, column=0, sticky="w")
        self.auto_replies = tk.BooleanVar(value=False)
        ttk.Checkbutton(reply, variable=self.auto_replies, command=self._remember,
                        text="Start this automatically when the app opens"
                        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(reply, wraplength=700, justify="left", text=(
            "SRS needs the SimpleRadio server and client running, and your aircraft "
            "radio tuned to the frequency on the Settings tab. If in doubt, use the "
            "speakers option - it always works."
        )).grid(row=4, column=0, sticky="w", pady=(4, 0))

    def _build_comms(self, tabs):
        """DCS's own comms menus, driven by keystrokes. Dry run only for now."""
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Comms Keys")
        tab.columnconfigure(0, weight=1)

        box = ttk.LabelFrame(tab, text="DCS comms menu commands (experimental)",
                             padding=PAD)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        self.comms_keys_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, variable=self.comms_keys_enabled,
                        command=lambda: self._on_voice_switch_toggled(
                            "comms menu commands", self.comms_keys_enabled.get()),
                        text="Listen for comms menu commands"
                        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(box, text="Aircraft:").grid(row=1, column=0, sticky="w",
                                              pady=(PAD, 0))
        self.comms_aircraft = ttk.Label(box, text="not in a mission yet",
                                        foreground="#555")
        self.comms_aircraft.grid(row=1, column=1, sticky="w", padx=(PAD, 0),
                                 pady=(PAD, 0))

        ttk.Label(box, text="Key maps:").grid(row=2, column=0, sticky="w")
        maps_row = ttk.Frame(box)
        maps_row.grid(row=2, column=1, sticky="w", padx=(PAD, 0))
        self.comms_maps = ttk.Label(maps_row, text="", foreground="#555",
                                    wraplength=520, justify="left")
        self.comms_maps.grid(row=0, column=0, sticky="w")
        ttk.Button(maps_row, text="Use shipped maps",
                   command=self._reset_comms_maps).grid(row=0, column=1, sticky="w",
                                                        padx=(PAD, 0))
        self.comms_maps_path = ttk.Label(box, text="", foreground="#555",
                                         wraplength=700, justify="left")
        self.comms_maps_path.grid(row=3, column=0, columnspan=2, sticky="w")
        self._refresh_comms_maps()

        ttk.Label(box, wraplength=700, justify="left", text=(
            'Say things like "two rejoin", "flight engage", "awacs picture" or '
            '"bogey dope". These work the comms menu DCS already has — ATCAI cannot '
            "reach it any other way."
        )).grid(row=3, column=0, columnspan=2, sticky="w", pady=(PAD, 0))

        self.send_keys_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, variable=self.send_keys_enabled,
                        command=self._on_send_keys_toggled,
                        text="Actually press the keys (otherwise dry run)"
                        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(PAD, 0))

        ttk.Label(box, text="How sure before pressing:").grid(row=6, column=0,
                                                               sticky="w",
                                                               pady=(PAD, 0))
        self.comms_confidence = tk.DoubleVar(value=0.70)
        confidence_row = ttk.Frame(box)
        confidence_row.grid(row=6, column=1, sticky="w", padx=(PAD, 0), pady=(PAD, 0))
        ttk.Scale(confidence_row, from_=0.3, to=0.95,
                  variable=self.comms_confidence, orient="horizontal", length=200,
                  command=lambda _: self._refresh_comms_confidence()).grid(row=0,
                                                                           column=0)
        self.comms_confidence_label = ttk.Label(confidence_row, foreground="#555")
        self.comms_confidence_label.grid(row=0, column=1, padx=(PAD, 0))
        ttk.Label(box, wraplength=700, justify="left", foreground="#555", text=(
            "Separate from ATC's slider, and only applied when the keys are pressed for "
            "real. These commands act on your flight, so a false one costs more than a "
            "missed radio call — background noise ordered a test flight home nine times "
            "at 0.65 to 0.93. Raising this helps a little; it is not a substitute for "
            "push-to-talk in a noisy room."
        )).grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))

        keys_test = ttk.Frame(box)
        keys_test.grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Button(keys_test, text="Test keys in Notepad",
                   command=self._test_keys_in_notepad).grid(row=0, column=0, sticky="w")
        self.keys_focus = ttk.Label(keys_test, text="", foreground="#555")
        self.keys_focus.grid(row=0, column=1, sticky="w", padx=(PAD, 0))

        ttk.Label(box, wraplength=700, justify="left", foreground="#555", text=(
            "The Notepad test types F-keys into Notepad instead of DCS. If nothing "
            "arrives there, Windows is refusing the synthetic keystrokes and no key "
            "map will help — which is worth knowing separately from a wrong sequence."
        )).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(box, wraplength=700, justify="left", foreground="#b45309", text=(
            "Keys are only ever sent while DCS is the active window. If you alt-tab "
            "away mid-command the rest of the sequence is dropped rather than typed "
            "into whatever you switched to.\n"
            "Unlike the rest of ATCAI, this works the game rather than only reading "
            "it, so it can affect what your flight does and therefore how a mission "
            "turns out."
        )).grid(row=8, column=0, columnspan=2, sticky="w", pady=(PAD, 0))

    def _on_voice_switch_toggled(self, what, now_on):
        """Every voice switch only takes effect when listening restarts.

        The recogniser builds its grammar and reads its settings once, at start. A
        switch that silently does nothing until then is indistinguishable from a broken
        feature - which is how the cockpit switch cost a test flight.
        """
        self._remember()
        state = "on" if now_on else "off"
        if self.listener.running:
            self._enqueue("voice", "%s %s - restart listening (Stop then Start on "
                                   "Talking to ATC) for this to take effect"
                                   % (what, state))
        else:
            self._enqueue("voice", "%s %s - takes effect when you start listening"
                                   % (what, state))

    def _refresh_comms_confidence(self):
        self.comms_confidence_label.config(text="%.2f" % self.comms_confidence.get())
        self._remember()

    def _on_send_keys_toggled(self):
        """Pressing keys for real is a different proposition from logging them, so it
        says so plainly rather than flipping silently."""
        if self.send_keys_enabled.get():
            self._on_voice_switch_toggled("comms keys: PRESSING FOR REAL", True)
        else:
            self._on_voice_switch_toggled("comms keys: back to dry run", False)

    def _test_keys_in_notepad(self):
        """Prove synthetic keystrokes reach a window at all, without involving DCS.

        If this works and DCS still does nothing, the problem is DirectInput rather
        than our sequences - two failures that are otherwise indistinguishable.
        """
        if not atcai_sendkeys.available():
            self._enqueue("voice", "sending keys needs Windows")
            return

        try:
            subprocess.Popen(["notepad.exe"], **atcai_listen.no_window())
        except OSError as exc:
            self._enqueue("voice", "could not start Notepad: %s" % exc)
            return

        self._enqueue("voice", "Notepad opening - typing 'dcs' into it in 3 seconds. "
                               "Leave it focused.")

        def work():
            time.sleep(3)
            sender = atcai_sendkeys.SendKeys(target_process="notepad.exe")
            where = sender._focus() or "unknown"
            ok = sender.send(["d", "c", "s"], delay_ms=120)
            self.mic_events.put(("KEYTEST", (ok, where, sender.last_error)))

        threading.Thread(target=work, daemon=True).start()

    def _reset_comms_maps(self):
        """Replace the player's maps with the shipped ones, discarding local edits."""
        if not messagebox.askyesno(
                "Use shipped maps",
                "Replace your key maps with the versions that came with this build?\n\n"
                "Any phrasings or sequences you changed yourself will be lost."):
            return
        replaced = atcai_keys.refresh_user_keymaps()
        self._enqueue("app", "key maps reset to the shipped versions: %s"
                      % (", ".join(replaced) or "none"))
        self._refresh_comms_maps()

    def _refresh_comms_maps(self):
        try:
            # Seeded on first run so the maps are somewhere the player can actually
            # edit them - the shipped copies live inside the exe.
            copied = atcai_keys.seed_user_keymaps()
            if copied:
                self._enqueue("app", "key maps for %s copied to %s - edit them there"
                              % (", ".join(copied), atcai_keys.user_keymap_dir()))
            maps = atcai_keys.available_maps()
            folder = atcai_keys.keymap_dir()
            stale = atcai_keys.stale_user_keymaps()
        except Exception:                                  # never take the GUI down
            maps, folder, stale = [], "", []

        if stale:
            # Reading prefers the player's folder, so a shipped correction would be
            # silently ignored. Saying so is better than leaving it a mystery.
            self.comms_maps_path.config(
                text="Reading from %s. Your copy of %s differs from the shipped one - "
                     "press \"Use shipped maps\" to discard those edits."
                     % (folder, ", ".join(stale)),
                foreground="#b45309")
        else:
            self.comms_maps_path.config(text="Reading from %s" % folder,
                                        foreground="#555")
        if maps:
            labelled = []
            for aircraft in maps:
                try:
                    verified = atcai_keys.load_keymap(aircraft).get("verified")
                except Exception:
                    verified = False
                labelled.append(aircraft if verified else "%s (unverified)" % aircraft)
            self.comms_maps.config(text=", ".join(labelled))
        else:
            self.comms_maps.config(text="none found")

    def _build_log(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Log")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        ttk.Label(tab, wraplength=700, justify="left", foreground="#555", text=(
            "Everything the manager does, and everything the voice bridges report. "
            "This is the first place to look when something isn't working, and the most "
            "useful thing to include if you report a problem."
        )).grid(row=0, column=0, sticky="w")

        self.log_view = tk.Text(tab, height=10, wrap="word", state="disabled")
        self.log_view.grid(row=1, column=0, sticky="nsew", pady=(PAD, 0))

    def _build_cockpit(self, tabs):
        """Cockpit controls by voice. The keys come from DCS, not from here."""
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="AI Cockpit")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)

        box = ttk.LabelFrame(tab, text="Cockpit controls by voice (experimental)",
                             padding=PAD)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        self.cockpit_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, variable=self.cockpit_enabled,
                        command=lambda: self._on_voice_switch_toggled(
                            "cockpit commands", self.cockpit_enabled.get()),
                        text="Listen for cockpit commands"
                        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self.cockpit_send = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, variable=self.cockpit_send,
                        command=self._on_cockpit_send_toggled,
                        text="Actually press the keys (otherwise dry run)"
                        ).grid(row=1, column=0, columnspan=3, sticky="w")

        ttk.Label(box, text="How sure it must be:").grid(row=2, column=0, sticky="w",
                                                         pady=(PAD, 0))
        self.cockpit_confidence = tk.DoubleVar(value=0.70)
        ttk.Scale(box, from_=0.5, to=0.95, variable=self.cockpit_confidence,
                  orient="horizontal", length=220, command=lambda _: self._remember()
                  ).grid(row=2, column=1, sticky="w", padx=(PAD, 0), pady=(PAD, 0))
        ttk.Label(box, foreground="#555", text="separate from ATC's - a wrong cockpit "
                  "command costs more than a wrong request"
                  ).grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(box, text="Aircraft:").grid(row=4, column=0, sticky="w",
                                              pady=(PAD, 0))
        self.cockpit_aircraft = ttk.Label(box, text="not in a mission yet",
                                          foreground="#555")
        self.cockpit_aircraft.grid(row=4, column=1, sticky="w", padx=(PAD, 0),
                                   pady=(PAD, 0))
        ttk.Button(box, text="Re-read bindings", command=self._reread_bindings
                   ).grid(row=4, column=2, sticky="w", padx=(PAD, 0), pady=(PAD, 0))

        ttk.Label(tab, wraplength=740, justify="left", text=(
            "ATCAI does not decide the key combinations - DCS does, and this reads them "
            "from your own binding files, including anything you have rebound. If you "
            "change a control in DCS's options, press Re-read bindings."
        )).grid(row=1, column=0, sticky="w", pady=(PAD, 0))

        self.cockpit_controls = tk.Text(tab, height=10, wrap="none", state="disabled")
        self.cockpit_controls.grid(row=3, column=0, sticky="nsew", pady=(PAD, 0))

        self.cockpit_path = ttk.Label(tab, text="", foreground="#555", wraplength=740,
                                      justify="left")
        self.cockpit_path.grid(row=4, column=0, sticky="w")
        ttk.Button(tab, text="Use shipped controls", command=self._reset_cockpit_controls
                   ).grid(row=5, column=0, sticky="w", pady=(4, 0))

        ttk.Label(tab, wraplength=740, justify="left", foreground="#b45309", text=(
            "Keys are only sent while DCS is the active window. Destructive controls - "
            "eject, jettison, engine shutdown, weapons, countermeasures - are refused "
            "in code and cannot be enabled by editing the file."
        )).grid(row=6, column=0, sticky="w", pady=(PAD, 0))

        self._refresh_cockpit_controls()

    def _bindings(self):
        """The binding cache, built once the DCS folders are known.

        The game folder holds the profiles and luae.exe; the writedir holds the
        player's remappings. Both are needed, and neither is known until a DCS folder
        has been chosen.
        """
        if getattr(self, "_bindings_cache", None):
            return self._bindings_cache

        game = None
        try:
            installs = installer.find_dcs_installs()
            game = installs[0] if installs else None
        except Exception:
            game = None
        if not game:
            return None

        self._bindings_cache = atcai_bindings.Cache(
            dcs_install=game,
            dcs_writedir=self.installation.path if self.installation else None,
            on_log=lambda message: self._enqueue("voice", message))
        return self._bindings_cache

    def _on_cockpit_send_toggled(self):
        if self.cockpit_send.get():
            self._on_voice_switch_toggled("cockpit keys: PRESSING FOR REAL", True)
        else:
            self._on_voice_switch_toggled("cockpit keys: back to dry run", False)

    def _cockpit_write(self, text):
        self.cockpit_controls.config(state="normal")
        self.cockpit_controls.delete("1.0", "end")
        self.cockpit_controls.insert("end", text)
        self.cockpit_controls.config(state="disabled")

    def _refresh_cockpit_controls(self):
        """Show each command: the control, the chord DCS gave it, and the phrases.

        One screen answering both "what do I say" and "what will it press", which are
        the two questions anyone actually has.
        """
        try:
            copied = atcai_cockpit.seed_user_controls()
            if copied:
                self._enqueue("app", "control list copied to %s - edit it there"
                              % atcai_cockpit.user_dir())
            controls = atcai_cockpit.load_controls()
            folder = atcai_cockpit.controls_dir()
            missing = atcai_cockpit.missing_user_controls()
        except Exception as exc:                          # never take the GUI down
            self._cockpit_write("could not read the control list: %r" % exc)
            return

        if missing:
            # Seeding never merges into an existing file, so a copy made when the list
            # was shorter keeps the shorter list for ever - and the only symptom is a
            # command that does nothing, which looks exactly like a recognition problem.
            self._enqueue("app",
                          "! your control list is missing %d shipped control(s): %s. "
                          "Press \"Use shipped controls\" to get them - it replaces "
                          "your copy, so note any phrases you have changed first."
                          % (len(missing), ", ".join(missing)))

        bindings = {}
        aircraft = getattr(self, "_cockpit_last_aircraft", None)
        if aircraft and getattr(self, "_bindings_cache", None):
            try:
                bindings = self._bindings_cache.get(aircraft)
            except Exception:
                bindings = {}

        lines = []
        for intent, entry in sorted(controls.items()):
            control = entry.get("control", "?")
            chords = bindings.get(control)
            chord = chords[0] if chords else ("?" if aircraft else "-")
            phrases = ", ".join('"%s"' % p for p in entry.get("phrases", []))
            lines.append("%-22s %-10s %s" % (control, chord, phrases))

        if not lines:
            lines = ["no controls configured"]
        elif not aircraft:
            lines.append("")
            lines.append("Key combinations appear once a mission reports your aircraft.")
        self._cockpit_write("\n".join(lines))
        self.cockpit_path.config(text="Reading the control list from %s" % folder)

    def _reread_bindings(self):
        """After rebinding something in DCS's own options."""
        if getattr(self, "_bindings_cache", None):
            self._bindings_cache.forget()
            self._enqueue("voice", "bindings will be re-read on the next command")
        self._refresh_cockpit_controls()

    def _reset_cockpit_controls(self):
        if not messagebox.askyesno(
                "Use shipped controls",
                "Replace your control list with the version that came with this "
                "build?\n\nAny phrases you changed yourself will be lost."):
            return
        atcai_cockpit.refresh_user_controls()
        self._enqueue("app", "control list reset to the shipped version")
        self._refresh_cockpit_controls()

    # ---------- voice commands ----------

    def _build_voice_commands(self, tabs):
        """Which commands exist, and what you say for each.

        The player's room is the one thing this project cannot measure from here. A dog,
        a TV or a jet engine will trip some phrase, and which one is nobody's guess - so
        the switch belongs to them. The same list doubles as "say it the way I say it",
        because both are the same edit underneath: a phrase added, a phrase removed.
        """
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Voice Commands")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        head = ttk.Frame(tab)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, wraplength=700, justify="left", text=(
            "Untick a command to stop ATCAI listening for it at all, or edit what you "
            "say. A command you untick is removed from the recogniser's vocabulary, so "
            "background noise cannot trigger it."
        )).grid(row=0, column=0, columnspan=3, sticky="w")

        self.phrase_counts = ttk.Label(head, text="", foreground="#555")
        self.phrase_counts.grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        ttk.Button(head, text="Restore all defaults",
                   command=self._restore_all_phrases).grid(row=1, column=1, sticky="e",
                                                           pady=(PAD, 0))
        ttk.Button(head, text="Restart listening",
                   command=self._restart_listening).grid(row=1, column=2, sticky="e",
                                                         padx=(PAD, 0), pady=(PAD, 0))

        # A canvas rather than a plain frame: thirty-odd commands do not fit, and options
        # below the fold are invisible, which is the mistake the old Voice tab made.
        frame = ttk.Frame(tab)
        frame.grid(row=1, column=0, sticky="nsew", pady=(PAD, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.phrase_canvas = tk.Canvas(frame, highlightthickness=0, height=320)
        self.phrase_canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical",
                            command=self.phrase_canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.phrase_canvas.configure(yscrollcommand=bar.set)

        self.phrase_body = ttk.Frame(self.phrase_canvas, padding=(0, 0, PAD, 0))
        self.phrase_window = self.phrase_canvas.create_window(
            (0, 0), window=self.phrase_body, anchor="nw")
        self.phrase_body.bind(
            "<Configure>",
            lambda _: self.phrase_canvas.configure(
                scrollregion=self.phrase_canvas.bbox("all")))
        self.phrase_canvas.bind(
            "<Configure>",
            lambda event: self.phrase_canvas.itemconfigure(self.phrase_window,
                                                           width=event.width))

        ttk.Label(tab, foreground="#b45309", wraplength=700, justify="left", text=(
            "Changes take effect when listening restarts — the recogniser builds its "
            "vocabulary once, at start. Use Restart listening above, or Stop then Start "
            "on Talking to ATC."
        )).grid(row=2, column=0, sticky="w", pady=(PAD, 0))

        self.phrase_path = ttk.Label(tab, foreground="#555", wraplength=700,
                                     justify="left")
        self.phrase_path.grid(row=3, column=0, sticky="w", pady=(4, 0))

        self._refresh_voice_commands()

    def _phrase_groups(self):
        """[(group name, note, {intent: [effective phrase, ...]}), ...].

        Effective, so the tab shows what the recogniser will actually hear. The note is
        how the player learns that a whole source is switched off on a different tab -
        otherwise "why isn't my cockpit command working" has two answers in two places.
        """
        notes = {
            "Comms menu": (None if self.comms_keys_enabled.get()
                           else "currently off — enable on the Comms Keys tab"),
            "Cockpit controls": (None if self.cockpit_enabled.get()
                                 else "currently off — enable on the AI Cockpit tab"),
        }
        groups = []
        for name, shipped in atcai_listen.command_sources():
            groups.append((name, notes.get(name),
                           atcai_phrases.effective(shipped, self.phrase_overlay),
                           shipped))
        return groups

    def _phrases_in_force(self):
        """Every phrase currently in force, as {intent: [phrase, ...]}.

        The whole set, not one group: a new ATC phrase can collide with a cockpit one,
        and the editor has to catch that before the recogniser silently drops one of them.
        """
        in_force = {}
        for _, _, effective, _ in self._phrase_groups():
            in_force.update(effective)
        return in_force

    def _refresh_voice_commands(self):
        for child in self.phrase_body.winfo_children():
            child.destroy()

        self.phrase_switches = {}
        row = 0
        commands = disabled = edited = 0

        for name, note, effective, shipped in self._phrase_groups():
            title = name if not note else "%s  (%s)" % (name, note)
            ttk.Label(self.phrase_body, text=title, font=("", 9, "bold"),
                      foreground="#555" if note else "").grid(
                row=row, column=0, columnspan=3, sticky="w",
                pady=(PAD if row else 0, 2))
            row += 1

            if not shipped:
                ttk.Label(self.phrase_body, foreground="#555",
                          text="   nothing available").grid(row=row, column=0,
                                                            sticky="w")
                row += 1
                continue

            for intent in sorted(shipped):
                commands += 1
                on = intent in effective
                if not on:
                    disabled += 1
                changed = bool(self.phrase_overlay.get(intent, {}).get("add")
                               or self.phrase_overlay.get(intent, {}).get("remove"))
                if changed:
                    edited += 1

                switch = tk.BooleanVar(value=on)
                self.phrase_switches[intent] = switch
                ttk.Checkbutton(
                    self.phrase_body, variable=switch, text=intent,
                    command=lambda i=intent: self._on_command_toggled(i)
                ).grid(row=row, column=0, sticky="w", padx=(PAD, 0))

                said = " · ".join(effective.get(intent) or []) or "—"
                ttk.Label(self.phrase_body, text=said + ("   (edited)" if changed else ""),
                          foreground="#555" if on else "#999",
                          wraplength=420, justify="left").grid(row=row, column=1,
                                                               sticky="w", padx=(PAD, 0))
                ttk.Button(self.phrase_body, text="Edit...", width=8,
                           command=lambda i=intent: self._edit_command(i)).grid(
                    row=row, column=2, sticky="e")
                row += 1

        self.phrase_body.columnconfigure(1, weight=1)
        self.phrase_counts.config(text="%d commands · %d disabled · %d edited"
                                       % (commands, disabled, edited))
        path = atcai_phrases.overlay_path()
        self.phrase_path.config(
            text="Your changes: %s" % path if self.phrase_overlay
            else "No changes yet. Anything you change is saved to %s" % path)

    def _entry_for(self, intent):
        return self.phrase_overlay.setdefault(intent, {})

    def _tidy_overlay(self):
        """Drop entries that no longer say anything, so the file stays a record of real
        changes and "restore defaults" leaves no trace."""
        for intent in list(self.phrase_overlay):
            entry = self.phrase_overlay[intent]
            if entry.get("enabled") is False:
                continue
            entry.pop("enabled", None)
            if not entry.get("add") and not entry.get("remove"):
                del self.phrase_overlay[intent]

    def _save_phrase_overlay(self, what):
        self._tidy_overlay()
        path = atcai_phrases.save_overlay(self.phrase_overlay)
        if path is None:
            messagebox.showerror("Could not save that",
                                 "ATCAI could not write %s. Your change is active for "
                                 "now but will be lost when the manager closes."
                                 % atcai_phrases.overlay_path())
        self._refresh_voice_commands()
        self._on_voice_switch_toggled(what, True)

    def _on_command_toggled(self, intent):
        on = self.phrase_switches[intent].get()
        if on:
            self._entry_for(intent).pop("enabled", None)
        else:
            self._entry_for(intent)["enabled"] = False
        self._save_phrase_overlay("%s %s" % (intent, "on" if on else "off"))

    def _add_phrase(self, intent, text):
        """Returns an atcai_phrases.Check. Only writes when it passes."""
        result = atcai_phrases.check_phrase(text, intent, self._phrases_in_force(),
                                           variants=atcai_listen.expand_phrases)
        if not result.ok:
            return result

        phrase = atcai_phrases.normalise(text)
        entry = self._entry_for(intent)
        removed = entry.get("remove") or []
        if phrase in removed:
            # Putting back a shipped phrase they had removed. Dropping the removal is
            # the same thing as adding it, and leaves a cleaner file.
            entry["remove"] = [p for p in removed if p != phrase]
        else:
            entry["add"] = sorted(set((entry.get("add") or []) + [phrase]))
        self._save_phrase_overlay('%s: added "%s"' % (intent, phrase))
        return result

    def _remove_phrase(self, intent, phrase, shipped):
        phrase = atcai_phrases.normalise(phrase)
        entry = self._entry_for(intent)
        added = entry.get("add") or []
        if phrase in added:
            entry["add"] = [p for p in added if p != phrase]
        if phrase in [atcai_phrases.normalise(p) for p in shipped]:
            entry["remove"] = sorted(set((entry.get("remove") or []) + [phrase]))
        self._save_phrase_overlay('%s: removed "%s"' % (intent, phrase))

    def _restore_command(self, intent):
        self.phrase_overlay.pop(intent, None)
        self._save_phrase_overlay("%s back to its shipped phrases" % intent)

    def _restore_all_phrases(self):
        if not self.phrase_overlay:
            self._enqueue("voice", "nothing to restore - no commands have been changed")
            return
        if not messagebox.askyesno(
                "Restore all defaults",
                "Undo every change on this tab, for all %d commands you have changed?"
                % len(self.phrase_overlay)):
            return
        self.phrase_overlay = {}
        self._save_phrase_overlay("all commands back to their shipped phrases")

    def _restart_listening(self):
        if not self.listener.running:
            self._enqueue("voice", "not listening - press Start on Talking to ATC")
            return
        self._enqueue("voice", "restarting so the vocabulary is rebuilt...")
        self.listener.stop()
        self._await_restart(0)

    def _await_restart(self, attempts):
        # stop() only asks; the recogniser notices at its next loop. Starting before the
        # old thread has gone would be ignored - Bridge.start refuses while one is
        # running - and the player would be left on the old vocabulary believing it had
        # been rebuilt. So wait for it, and say so if it never goes.
        if self.listener.running and attempts < 25:
            self.after(200, lambda: self._await_restart(attempts + 1))
            return
        if self.listener.running:
            self._enqueue("voice", "! the old recogniser has not stopped - press Stop "
                                   "then Start on Talking to ATC")
            return
        self.listener.start(None)
        self._enqueue("voice", "listening again, with your current commands")
        self._refresh_bridge_buttons()

    def _edit_command(self, intent):
        """One command's phrases. Deliberately a dialog: the list is long enough already
        without every row carrying an expanded editor."""
        shipped = {}
        for _, _, _, source in self._phrase_groups():
            if intent in source:
                shipped = source
                break

        dialog = tk.Toplevel(self)
        dialog.title("What you say for: %s" % intent)
        dialog.transient(self.winfo_toplevel())
        dialog.columnconfigure(0, weight=1)
        body = ttk.Frame(dialog, padding=PAD)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)

        ttk.Label(body, wraplength=460, justify="left", text=(
            "Any of these works. The leading verb is expanded for you — "
            '"request taxi" also matches "requesting taxi".'
        )).grid(row=0, column=0, columnspan=2, sticky="w")

        rows = ttk.Frame(body)
        rows.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        rows.columnconfigure(0, weight=1)

        message = ttk.Label(body, wraplength=460, justify="left")
        message.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        entry_var = tk.StringVar()

        def redraw():
            for child in rows.winfo_children():
                child.destroy()
            in_force = self._phrases_in_force().get(intent) or []
            for i, phrase in enumerate(in_force):
                ttk.Label(rows, text=phrase).grid(row=i, column=0, sticky="w")
                ttk.Button(rows, text="Remove", width=8,
                           command=lambda p=phrase: (
                               self._remove_phrase(intent, p, shipped.get(intent) or []),
                               redraw())).grid(row=i, column=1, sticky="e")
            if not in_force:
                ttk.Label(rows, foreground="#b45309",
                          text="No phrases — this command cannot be spoken.").grid(
                    row=0, column=0, sticky="w")

        def add():
            result = self._add_phrase(intent, entry_var.get())
            if result.ok:
                entry_var.set("")
                redraw()
            colour = {"refuse": "#b91c1c", "duplicate": "#b45309",
                      "warn": "#b45309", "ok": "#15803d"}[result.level]
            message.config(text=result.message or "Added.", foreground=colour)

        add_row = ttk.Frame(body)
        add_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        add_row.columnconfigure(0, weight=1)
        field = ttk.Entry(add_row, textvariable=entry_var)
        field.grid(row=0, column=0, sticky="ew")
        field.bind("<Return>", lambda _: add())
        ttk.Button(add_row, text="Add", command=add).grid(row=0, column=1,
                                                          padx=(PAD, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        ttk.Button(buttons, text="Restore shipped phrases",
                   command=lambda: (self._restore_command(intent), redraw())).grid(
            row=0, column=0, sticky="w")
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=1,
                                                                      sticky="e",
                                                                      padx=(PAD, 0))
        redraw()
        return dialog

    def _build_settings(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Settings")
        tab.columnconfigure(1, weight=1)

        self.fields: dict[str, tk.StringVar] = {}
        rows = [
            ("tts_frequency", "Radio frequencies ATC uses",
             "Comma separated, in MHz. ATC talks on all of them."),
            ("airbase_search_radius", "How close you must be on the ground (metres)",
             "Below this, the nearest airfield answers you."),
            ("airbase_air_radius", "How far out ATC answers in the air (metres)",
             "92600 is about 50 miles. Raise it to call in earlier."),
        ]
        for index, (key, label, hint) in enumerate(rows):
            ttk.Label(tab, text=label).grid(row=index * 2, column=0, sticky="w",
                                            pady=(PAD if index else 0, 0))
            var = tk.StringVar(value=self._default_for(key))
            self.fields[key] = var
            ttk.Entry(tab, textvariable=var, width=40).grid(
                row=index * 2, column=1, sticky="ew", padx=(PAD, 0),
                pady=(PAD if index else 0, 0))
            default = self._default_for(key)
            ttk.Label(tab, text="%s  Default: %s" % (hint, default) if default else hint,
                      foreground="#555").grid(
                row=index * 2 + 1, column=1, sticky="w", padx=(PAD, 0))

        atis = ttk.LabelFrame(tab, text="Repeating airfield information (ATIS)", padding=PAD)
        atis.grid(row=50, column=0, columnspan=2, sticky="ew", pady=(PAD * 2, 0))
        atis.columnconfigure(1, weight=1)

        self.atis_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(atis, variable=self.atis_enabled, command=self._on_atis_changed,
                        text="Broadcast airfield information on a loop"
                        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(atis, text="Frequency (MHz):").grid(row=1, column=0, sticky="w",
                                                      pady=(PAD, 0))
        self.atis_frequency = tk.StringVar(value="380.000")
        self.atis_entry = ttk.Entry(atis, textvariable=self.atis_frequency, width=14)
        self.atis_entry.grid(row=1, column=1, sticky="w", padx=(PAD, 0), pady=(PAD, 0))

        self.atis_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(atis, variable=self.atis_auto, command=self._on_atis_auto_toggled,
                        text="Pick one for me").grid(row=1, column=2, sticky="w",
                                                     padx=(PAD, 0), pady=(PAD, 0))

        self.atis_note = ttk.Label(atis, wraplength=700, justify="left", foreground="#555")
        self.atis_note.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(tab)
        buttons.grid(row=99, column=0, columnspan=2, sticky="w", pady=(PAD * 2, 0))
        ttk.Button(buttons, text="Save settings", command=self._save_settings).grid(row=0, column=0)
        ttk.Button(buttons, text="Back to defaults", command=self._reset_settings).grid(
            row=0, column=1, padx=(PAD, 0))

    def _restore_voice_preferences(self):
        self.tts_mode.set(self.prefs["tts_mode"])
        self.confidence.set(float(self.prefs["min_confidence"]))
        self.strict.set(bool(self.prefs["strict"]))
        self.auto_voice.set(bool(self.prefs["auto_start_voice"]))
        self.auto_replies.set(bool(self.prefs["auto_start_replies"]))
        self.ptt_enabled.set(bool(self.prefs["ptt_enabled"]))
        self.ptt_key_code = int(self.prefs["ptt_key_code"])
        self.ptt_key_name = str(self.prefs["ptt_key_name"])
        self._refresh_ptt()

        self.atis_enabled.set(bool(self.prefs["atis_enabled"]))
        self.atis_auto.set(bool(self.prefs["atis_auto_frequency"]))
        self.atis_frequency.set(str(self.prefs["atis_frequency"]))
        self.comms_keys_enabled.set(bool(self.prefs["comms_keys_enabled"]))
        self.send_keys_enabled.set(bool(self.prefs["send_keys_enabled"]))
        self.comms_confidence.set(float(self.prefs["comms_confidence"]))
        self._refresh_comms_confidence()
        self.cockpit_enabled.set(bool(self.prefs["cockpit_keys_enabled"]))
        self.cockpit_send.set(bool(self.prefs["cockpit_send_enabled"]))
        self.cockpit_confidence.set(float(self.prefs["cockpit_confidence"]))
        self._on_atis_changed()

        started = []
        if self.auto_voice.get():
            self.listener.start(None)
            started.append("listening")
        if self.auto_replies.get():
            self.speaker.start(None)
            started.append("replies")

        for problem in self._phrase_problems:
            self._enqueue("voice", "! %s" % problem)

        if started:
            self._enqueue("app", "started %s automatically" % " and ".join(started))
        else:
            self._enqueue("app", "Voice is off until you press Start on the Voice tab.")

        self._ready = True

    def _remember(self):
        """Save preferences after anything the user would expect to stick."""
        if not self._ready:
            return
        self.prefs.update({
            "dcs_path": str(self.installation.path) if self.installation else "",
            "tts_mode": self.tts_mode.get(),
            "min_confidence": round(float(self.confidence.get()), 2),
            "strict": bool(self.strict.get()),
            "auto_start_voice": bool(self.auto_voice.get()),
            "auto_start_replies": bool(self.auto_replies.get()),
            "ptt_enabled": bool(self.ptt_enabled.get()),
            "ptt_key_code": int(self.ptt_key_code),
            "ptt_key_name": str(self.ptt_key_name),
            "atis_enabled": bool(self.atis_enabled.get()),
            "atis_auto_frequency": bool(self.atis_auto.get()),
            "atis_frequency": self.atis_frequency.get().strip() or "380.000",
            "comms_keys_enabled": bool(self.comms_keys_enabled.get()),
            "send_keys_enabled": bool(self.send_keys_enabled.get()),
            "comms_confidence": round(float(self.comms_confidence.get()), 2),
            "cockpit_keys_enabled": bool(self.cockpit_enabled.get()),
            "cockpit_send_enabled": bool(self.cockpit_send.get()),
            "cockpit_confidence": round(float(self.cockpit_confidence.get()), 2),
        })
        prefs.save(self.prefs)

    def _terrain_frequencies(self):
        """Airfield frequencies across every terrain installed, for collision checks."""
        try:
            import frequencies as freq_reader
            install = next(iter(installer.find_dcs_installs()), None)
            return freq_reader.read_terrains(install) if install else {}
        except Exception:
            return {}

    def _on_atis_auto_toggled(self):
        if self.atis_auto.get():
            import frequencies as freq_reader
            terrains = self._terrain_frequencies()
            picked = freq_reader.pick_atis_frequency(terrains)
            # The field always shows what is actually configured, whether typed or picked.
            self.atis_frequency.set(picked)
            self._enqueue("setup", "picked %s MHz for the ATIS broadcast" % picked)
        self._on_atis_changed()

    def _on_atis_changed(self):
        on = bool(self.atis_enabled.get())
        auto = bool(self.atis_auto.get())
        self.atis_entry.state(["!disabled" if (on and not auto) else "disabled"])

        if not on:
            self.atis_note.config(text="Airfield information is only given when you ask "
                                       "for it.", foreground="#555")
        else:
            self.atis_note.config(text=self._atis_advice(), foreground=self._atis_colour)
        self._remember()

    def _atis_advice(self):
        """Warn when the chosen frequency clashes with a real airfield."""
        self._atis_colour = "#555"
        raw = self.atis_frequency.get().strip()
        try:
            mhz = float(raw)
        except ValueError:
            self._atis_colour = "#b45309"
            return "That is not a frequency. Use a number like 380.000."

        if not (225.0 <= mhz <= 399.975):
            self._atis_colour = "#b45309"
            return ("Most DCS aircraft radios only tune 225-400 MHz (UHF). Outside that "
                    "you may not be able to hear the broadcast from the cockpit.")

        import frequencies as freq_reader
        clash = freq_reader.frequency_conflict(mhz, self._terrain_frequencies())
        if clash is not None:
            self._atis_colour = "#b45309"
            return ("%.3f MHz is used by an airfield - the broadcast would talk over it. "
                    "Pick something further away." % clash)
        return "Tune your radio to this frequency to hear the field information repeat."

    def _on_ptt_toggled(self):
        self._remember()
        self._refresh_ptt()
        if self.listener.running:
            self._enqueue("voice", "restart listening for the new push-to-talk setting")

    def _refresh_ptt(self):
        on = bool(self.ptt_enabled.get())
        self.ptt_button.state(["!disabled" if on else "disabled"])
        self.ptt_key_label.config(
            text="Key: %s" % self.ptt_key_name,
            foreground="#000000" if on else "#888888")

    def _capture_ptt_key(self):
        """Grab the next key pressed and use it, rather than making the user find a code."""
        popup = tk.Toplevel(self)
        popup.title("Press a key")
        popup.transient(self.winfo_toplevel())
        popup.grab_set()
        ttk.Label(popup, padding=PAD * 2, justify="center", text=(
            "Press the key you want to hold while talking to ATC.\n\n"
            "Pick something you don't use for flying - the right Ctrl or Alt key\n"
            "works well. Press Escape to cancel."
        )).grid()

        def on_key(event):
            if event.keysym == "Escape":
                popup.destroy()
                return
            # On Windows, Tk reports the virtual-key code, which is exactly what
            # GetAsyncKeyState needs to watch the key globally.
            self.ptt_key_code = int(event.keycode)
            self.ptt_key_name = event.keysym
            self._remember()
            self._refresh_ptt()
            self._enqueue("voice", "push-to-talk key set to %s" % self.ptt_key_name)
            popup.destroy()

        popup.bind("<Key>", on_key)
        popup.focus_force()

    # ---------- finding DCS ----------

    def _detect(self):
        self.found = installer.find_installations()

        remembered = self.prefs.get("dcs_path", "")
        if remembered and not any(str(i.path) == remembered for i in self.found):
            candidate = installer.inspect_path(Path(remembered))
            if candidate.path.is_dir():
                self.found.insert(0, candidate)

        if self.found:
            index = next((n for n, i in enumerate(self.found)
                          if str(i.path) == remembered), 0)
            self.folder_choice["values"] = [str(i.path) for i in self.found]
            self.folder_choice.current(index)
            self._use(self.found[index])
            self._enqueue("app", "using DCS at %s" % self.found[index].path)
            if len(self.found) > 1:
                self._enqueue("app", "Found %d DCS folders. Check the right one is "
                                     "selected above." % len(self.found))
        else:
            self.folder_choice["values"] = []
            self._use(None)
            self.warning.config(
                text="Could not find DCS. Use 'Choose folder...' and pick your "
                     "'Saved Games\\DCS' folder.")

    def _choose_detected(self):
        index = self.folder_choice.current()
        if 0 <= index < len(self.found):
            self._use(self.found[index])

    def _browse(self):
        chosen = filedialog.askdirectory(title="Select your Saved Games\\DCS folder")
        if not chosen:
            return
        candidate = installer.inspect_path(Path(chosen))
        if not candidate.verified and not messagebox.askyesno(
                "Use this folder?",
                "%s\n\n%s\n\nUse it anyway?" % (chosen, " ".join(candidate.notes))):
            return
        values = list(self.folder_choice["values"])
        if chosen not in values:
            values.append(chosen)
            self.folder_choice["values"] = values
            self.found.append(candidate)
        self.folder_choice.set(chosen)
        self._use(candidate)

    def _use(self, installation):
        self.installation = installation
        self._remember()
        if installation and not installation.verified:
            self.warning.config(text="Warning: " + " ".join(installation.notes))
        elif installation:
            self.warning.config(text="")
        self._refresh()

    # ---------- status ----------

    def _refresh(self):
        if not self.installation:
            self.status_label.config(text="No DCS folder selected.")
            for button in (self.install_button, self.enable_button, self.uninstall_button):
                button.state(["disabled"])
            return

        state = installer.status(self.installation)
        if state["installed"]:
            summary = "ATCAI is installed and %s." % ("on" if state["enabled"] else "off")
        elif state["partial"]:
            summary = "ATCAI is partly installed. Press Install to repair it."
        else:
            summary = "ATCAI is not installed yet."
        if state["dcs_running"]:
            summary += "\nDCS is running - restart it for any change to take effect."

        self.status_label.config(text=summary)
        self.install_button.state(["!disabled"])
        self.install_button.config(text="Install" if not state["installed"] else "Reinstall")
        self.uninstall_button.state(["!disabled" if state["installed"] or state["partial"]
                                     else "disabled"])
        if state["installed"]:
            self.enable_button.state(["!disabled"])
            self.enable_button.config(text="Turn off" if state["enabled"] else "Turn on")
        else:
            self.enable_button.state(["disabled"])

        self._load_settings()

    # ---------- actions ----------

    def _install(self):
        try:
            for action in installer.install(self.installation):
                self._enqueue("setup", action)
        except (OSError, FileNotFoundError) as exc:
            messagebox.showerror("Could not install", str(exc))
            return

        # Real per-airfield frequencies come from the game's own terrain files, so this
        # needs the install directory rather than Saved Games.
        note = ""
        try:
            install_dir = next(iter(installer.find_dcs_installs()), None)
            airfields = installer.write_frequencies(self.installation, install_dir)
        except OSError as exc:
            airfields, install_dir = 0, None
            self._enqueue("setup", "could not read airfield frequencies: %s" % exc)

        if airfields:
            self._enqueue("setup", "read frequencies for %d airfields" % airfields)
        else:
            self._enqueue("setup", "could not find your DCS game folder - ATC will use "
                                   "the frequencies on the Settings tab instead")
            note = ("\n\nATC will use the frequencies on the Settings tab, because the "
                    "DCS game folder could not be found.")

        self._refresh()
        messagebox.showinfo(
            "Installed",
            "ATCAI is installed.\n\nRestart DCS, then fly any mission and open the "
            "comms menu with the \\ key." + note)

    def _uninstall(self):
        if not messagebox.askyesno("Remove ATCAI?",
                                   "This removes ATCAI from DCS. Your settings are kept."):
            return
        try:
            for action in installer.uninstall(self.installation):
                self._enqueue("setup", action)
        except OSError as exc:
            messagebox.showerror("Could not remove", str(exc))
            return
        self._refresh()

    def _toggle_enabled(self):
        state = installer.status(self.installation)
        try:
            for action in installer.set_enabled(self.installation, not state["enabled"]):
                self._enqueue("setup", action)
        except (OSError, FileNotFoundError) as exc:
            messagebox.showerror("Could not change that", str(exc))
            return
        self._refresh()

    # ---------- bridges ----------

    def _toggle(self, bridge: Bridge):
        # Logged from here rather than the worker so there's evidence of the press even
        # if the worker fails to start at all.
        if bridge.running:
            self._enqueue(bridge.name, "stopping...")
            bridge.stop()
        else:
            self._enqueue(bridge.name, "starting...")
            bridge.start(None)
        self._remember()
        self._drain()
        self.after(400, self._refresh_bridge_buttons)

    def _refresh_bridge_buttons(self):
        listening, speaking = self.listener.running, self.speaker.running

        self.listen_button.config(text="Stop listening" if listening else "Start listening")
        self.listen_state.config(
            text="Listening" if listening else "Not listening",
            foreground="#15803d" if listening else "#b45309")

        self.speak_button.config(text="Stop replies" if speaking else "Start replies")
        self.speak_state.config(
            text="Speaking ATC's replies" if speaking
            else "Not running - you will hear nothing",
            foreground="#15803d" if speaking else "#b45309")

        if listening and speaking:
            hint = ""
        elif not listening and not speaking:
            hint = ("Voice is off. ATC replies on screen only. To talk to ATC and hear "
                    "it speak, open the Voice tab and press both Start buttons.")
        elif speaking:
            hint = ("You will hear ATC, but talking to it is off. Start listening on the "
                    "Voice tab.")
        else:
            hint = ("ATC is listening, but you will not hear it. Start replies on the "
                    "Voice tab.")
        self.voice_hint.config(text=hint)

    # ---------- microphone test ----------

    def _start_mic_test(self):
        """Run the diagnostic in the background; results arrive via the event queue."""
        if getattr(self, "_mic_thread", None) and self._mic_thread.is_alive():
            return

        if self.listener.running:
            self._mic_write("Stop listening first - only one thing can hold the "
                            "microphone at a time.\n", clear=True)
            return

        self.mic_button.state(["disabled"])
        self.mic_level.set(0)
        self.mic_device.config(text="Testing...")
        self._mic_write("", clear=True)
        self._mic_heard = 0
        self._mic_rejected = 0
        self._mic_inputs_found = []
        self._mic_signals = []
        self._mic_problems = []
        self._mic_finished = False

        def work():
            try:
                atcai_mictest.run(
                    seconds=atcai_mictest.DEFAULT_SECONDS,
                    on_event=lambda kind, payload: self.mic_events.put(
                        (kind, payload)),
                )
            except Exception as exc:                      # never take the GUI down
                self.mic_events.put(("ERROR", "test failed: %r" % exc))
            finally:
                self.mic_events.put(("DONE", None))

        self._mic_thread = threading.Thread(target=work, daemon=True)
        self._mic_thread.start()

    def _refresh_microphones(self):
        """Fill the chooser from SAPI's device list, marking the current selection."""
        def work():
            try:
                current, resolved, devices = atcai_micselect.list_devices()
            except Exception as exc:                      # never take the GUI down
                self.mic_events.put(("MICLIST", (None, None, [], repr(exc))))
                return
            self.mic_events.put(("MICLIST", (current, resolved, devices, None)))

        threading.Thread(target=work, daemon=True).start()

    def _show_microphone_choices(self, current, resolved, devices, error):
        if error:
            self._enqueue("voice", "could not list microphones: %s" % error)
            return

        self._mic_devices = devices
        following = ("Windows default (%s)" % resolved) if resolved else "Windows default"
        labels = [following] + [name for _, name in devices]
        self.mic_choice.config(values=labels)

        # An explicit choice is shown as itself; following Windows is shown as such,
        # with what it currently resolves to, so the two are never confused.
        if current and current != atcai_micselect.WINDOWS_DEFAULT:
            chosen = atcai_micselect.name_for(current, devices)
            self.mic_choice.set(chosen if chosen in labels else following)
        else:
            self.mic_choice.set(following)

    def _choose_microphone(self):
        index = self.mic_choice.current()
        devices = getattr(self, "_mic_devices", [])

        if index <= 0:
            token, label = atcai_micselect.WINDOWS_DEFAULT, "the Windows default"
        else:
            try:
                token, label = devices[index - 1]
            except IndexError:
                return

        def work():
            ok, message = atcai_micselect.select(token)
            self.mic_events.put(("MICSET", (ok, label, message)))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_inputs(self):
        """List the active recording devices. Safe while listening - it never opens
        the microphone, it only asks Windows what exists."""
        if getattr(self, "_mic_list_thread", None) and self._mic_list_thread.is_alive():
            return
        self.mic_list_button.state(["disabled"])
        self.mic_inputs.config(text="Looking...")
        self._mic_inputs_found = []

        def work():
            try:
                for entry in atcai_mictest.list_devices():
                    self.mic_events.put(("INPUT", entry))
            except Exception as exc:                      # never take the GUI down
                self.mic_events.put(("ERROR", "could not list microphones: %r" % exc))
            finally:
                self.mic_events.put(("INPUTS_DONE", None))

        self._mic_list_thread = threading.Thread(target=work, daemon=True)
        self._mic_list_thread.start()

    def _open_sound_settings(self):
        """One click to the panel that can change the default, since ATCAI can't."""
        if atcai_mictest.open_sound_settings(
                lambda message: self._enqueue("voice", message)):
            self._mic_write(
                "Opened Windows sound settings. On the Recording tab, right-click the "
                "microphone you speak into and choose \"Set as Default Device\", then "
                "press Test microphone again.\n")

    def _show_inputs(self):
        """Render the collected device list, marking the one ATCAI will actually get."""
        found = getattr(self, "_mic_inputs_found", [])
        self.mic_list_button.state(["!disabled"])
        if not found:
            self.mic_inputs.config(text="No active recording devices found.")
            return

        default = [name for is_default, name in found if is_default]
        others = [name for is_default, name in found if not is_default]

        parts = []
        if default:
            parts.append("In use: %s" % default[0])
        if others:
            parts.append("Also available: %s" % ", ".join(others))
        # The point of showing the others at all: if the one in use is wrong, nothing
        # else in ATCAI can tell you, because it never sees the alternatives.
        self.mic_inputs.config(text="   ".join(parts))

    def _mic_write(self, text, clear=False):
        self.mic_results.config(state="normal")
        if clear:
            self.mic_results.delete("1.0", "end")
        if text:
            self.mic_results.insert("end", text)
            self.mic_results.see("end")
        self.mic_results.config(state="disabled")

    def _on_mic_event(self, kind, payload):
        """One line of diagnostic output, translated for someone who isn't debugging."""
        if kind == "DEVICE":
            self.mic_device.config(text="Windows gave ATCAI: %s" % payload)
        elif kind == "READY":
            self._mic_write("Listening for %d seconds - say a request now.\n" % payload)
        elif kind == "LEVEL":
            self.mic_level.set(int(payload))
        elif kind == "PROBLEM":
            self._mic_problems = getattr(self, "_mic_problems", []) + [payload]
        elif kind == "HEARD":
            self._mic_heard = getattr(self, "_mic_heard", 0) + 1
            self._mic_write('-> heard "%s" (%.0f%% sure)\n' % (payload[1], payload[0] * 100))
        elif kind == "REJECTED":
            self._mic_rejected = getattr(self, "_mic_rejected", 0) + 1
            self._mic_write('~ heard something that matched no request'
                            '%s\n' % (' - closest was "%s"' % payload[1] if payload[1] else ""))
        elif kind == "INPUT":
            self._mic_inputs_found = getattr(self, "_mic_inputs_found", []) + [payload]
        elif kind == "SIGNAL":
            self._mic_signals = getattr(self, "_mic_signals", []) + [payload]
        elif kind == "MICLIST":
            self._show_microphone_choices(*payload)
        elif kind == "MICSET":
            ok, label, message = payload
            if ok:
                self._enqueue("voice", "microphone set to %s - restart listening for "
                                       "it to take effect" % label)
            else:
                self._enqueue("voice", "could not set the microphone: %s" % message)
            self._refresh_microphones()
        elif kind == "KEYTEST":
            ok, where, error = payload
            self.keys_focus.config(
                text="keys arrived" if ok else "nothing sent",
                foreground="#15803d" if ok else "#b45309")
            if ok:
                self._enqueue("voice", "key test: 'dcs' typed into %s - synthetic "
                                       "keystrokes work on this machine" % where)
            else:
                self._enqueue("voice", "key test failed (%s was focused): %s"
                                       % (where, error))
        elif kind == "INPUTS_DONE":
            self._show_inputs()
        elif kind == "ERROR":
            self._mic_write("! %s\n" % payload)
        elif kind == "DONE":
            self.mic_button.state(["!disabled"])
            self.mic_level.set(0)
            # The script says DONE and so does the worker's finally; only the first
            # one is a result, the second would print the verdict twice.
            if getattr(self, "_mic_finished", True):
                return
            self._mic_finished = True
            self._show_inputs()
            for line in self._mic_problem_lines():
                self._mic_write("! %s\n" % line)
            self._mic_write("\n" + self._mic_verdict())

    def _mic_problem_lines(self):
        """The signal complaints worth passing on.

        The recogniser reports NoSignal during ordinary pauses in speech, so on a
        working microphone it fires between every sentence. Once something has been
        understood - or the device itself measured sound - "no audio at all" is simply
        false, and the quality complaints are the only ones left worth hearing.
        """
        problems = list(dict.fromkeys(getattr(self, "_mic_problems", [])))
        heard = getattr(self, "_mic_heard", 0) or getattr(self, "_mic_rejected", 0)
        measured = any(is_default and level > 0
                       for is_default, level, _ in getattr(self, "_mic_signals", []))

        if heard or measured:
            problems = [p for p in problems if p != "NoSignal"]
        return [atcai_mictest.describe_problem(p) for p in problems]

    def _mic_verdict(self):
        """Say what the result means, rather than leaving the player to interpret it."""
        heard = getattr(self, "_mic_heard", 0)
        rejected = getattr(self, "_mic_rejected", 0)

        if heard:
            return ("Test finished. Your microphone works and ATCAI understood you - "
                    "if it still misses you in the air, raise your voice slightly or "
                    "turn on push-to-talk.\n")
        if rejected:
            return ("Test finished. Sound is reaching ATCAI, but nothing matched a "
                    "request. Check the wording on the Voice tab, or lower "
                    '"How sure it must be".\n')
        signals = getattr(self, "_mic_signals", [])
        live = [(level, name) for is_default, level, name in signals
                if not is_default and level > 0]
        in_use_flat = any(is_default and level == 0 for is_default, level, name in signals)

        if in_use_flat and live:
            # Measured at the device, so this is not a guess: one microphone produced
            # nothing and another produced sound while the test ran.
            best = max(live)[1]
            return ("Test finished. The microphone in use produced no sound at all, but "
                    "%s did. That's almost certainly the one you're speaking into - set "
                    "it as default under Recording in Windows sound settings (set it as "
                    "the default communications device too) and test again.\n" % best)
        if in_use_flat:
            return ("Test finished. The microphone in use produced no sound at all, and "
                    "no other microphone did either. Check it's switched on, the boom "
                    "isn't muted, and nothing else has taken it.\n")

        others = [name for is_default, name in getattr(self, "_mic_inputs_found", [])
                  if not is_default]
        if others:
            return ("Test finished. Nothing was heard at all. ATCAI gets whichever "
                    "microphone Windows marks as default, and you also have %s. If "
                    "that's the one you speak into, set it as default under Recording "
                    "in Windows sound settings and test again.\n"
                    % " and ".join(others))
        return ("Test finished. Nothing was heard at all. Check the microphone named "
                "above is the one you speak into - Windows picks it, not ATCAI - and "
                "that it isn't muted.\n")

    def _run_listener(self, _options, on_log, should_stop):
        options = atcai_listen.build_options(
            inbox=str(self.installation.scripts_dir / "inbox.lua") if self.installation else None,
            min_confidence=round(self.confidence.get(), 2),
            strict=bool(self.strict.get()),
            ptt_enabled=bool(self.ptt_enabled.get()),
            ptt_key_code=int(self.ptt_key_code),
            ptt_key_name=str(self.ptt_key_name),
            comms_keys=bool(self.comms_keys_enabled.get()),
            send_keys=bool(self.send_keys_enabled.get()),
            comms_confidence=round(self.comms_confidence.get(), 2),
            cockpit_keys=bool(self.cockpit_enabled.get()),
            cockpit_send=bool(self.cockpit_send.get()),
            cockpit_confidence=round(self.cockpit_confidence.get(), 2),
            bindings_cache=self._bindings(),
            dcs_log=(str(self.installation.path / "Logs" / "dcs.log")
                     if self.installation else None),
        )
        atcai_listen.run(options, on_log=on_log, should_stop=should_stop)

    def _run_speaker(self, _options, on_log, should_stop):
        log_path = None
        if self.installation:
            log_path = str(self.installation.path / "Logs" / "dcs.log")
        options = atcai_tts.build_options(mode=self.tts_mode.get(), log=log_path)
        atcai_tts.run(options, on_log=on_log, should_stop=should_stop)

    # ---------- settings ----------

    @staticmethod
    def _default_for(key):
        """What a setting is when nothing overrides it, as text for an entry box."""
        value = installer.CONFIG_DEFAULTS.get(key)
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)

    def _load_settings(self):
        if not self.installation:
            return
        saved = installer.read_config(self.installation)
        if "atis_frequency" in saved:
            self.atis_frequency.set(str(saved["atis_frequency"]))
        if "atis_enabled" in saved:
            self.atis_enabled.set(bool(saved["atis_enabled"]))
        for key, var in self.fields.items():
            if key in saved:
                var.set(str(saved[key]))
            else:
                var.set(self._default_for(key))

    def _save_settings(self):
        settings, problems = {}, []
        for key, var in self.fields.items():
            raw = var.get().strip()
            if not raw:
                continue
            if installer.CONFIG_FIELDS[key] is str:
                settings[key] = raw
                continue
            try:
                number = float(raw)
            except ValueError:
                problems.append("%s must be a number." % key.replace("_", " "))
                continue
            if number <= 0:
                problems.append("%s must be greater than zero." % key.replace("_", " "))
                continue
            settings[key] = int(number) if number.is_integer() else number

        settings["atis_enabled"] = bool(self.atis_enabled.get())
        settings["atis_frequency"] = self.atis_frequency.get().strip() or "380.000"
        try:
            float(settings["atis_frequency"])
        except ValueError:
            problems.append("The ATIS frequency must be a number, like 380.000.")

        if problems:
            messagebox.showerror("Check those settings", "\n".join(problems))
            return
        try:
            path = installer.write_config(self.installation, settings)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self._enqueue("setup", "saved settings to %s" % path)
        messagebox.showinfo("Saved", "Settings saved.\n\nRestart the mission to use them.")

    def _reset_settings(self):
        for key, var in self.fields.items():
            var.set(self._default_for(key))
        if self.installation and self.installation.config_path.is_file():
            self.installation.config_path.unlink()
            self._enqueue("setup", "settings back to defaults")

    # ---------- log ----------

    def _enqueue(self, source, message):
        self.messages.put("[%s] %s" % (source, message))

    def _drain(self):
        """Background threads can't touch widgets, so they queue and the GUI drains."""
        while True:
            try:
                line = self.messages.get_nowait()
            except queue.Empty:
                break
            self.log_view.configure(state="normal")
            self.log_view.insert("end", line + "\n")
            self.log_view.see("end")
            self.log_view.configure(state="disabled")

        while True:
            try:
                kind, payload = self.mic_events.get_nowait()
            except queue.Empty:
                break
            self._on_mic_event(kind, payload)

        self._refresh_bridge_buttons()
        self.after(150, self._drain)


def main():
    # Two Managers each start their own voice bridges: both would transmit every ATC
    # reply and both would reach for the microphone. Those symptoms look like faults in
    # the module, so a second copy surfaces the first instead of starting.
    lock = single_instance.Lock()
    if not lock.acquire():
        if not single_instance.show_existing_window():
            # Could not find the window to raise, so say something rather than vanish.
            try:
                messagebox.showinfo(
                    "ATCAI Manager",
                    "ATCAI Manager is already running.\n\n"
                    "Look for it in the taskbar. Running two copies would make ATC "
                    "speak twice and both would fight for the microphone.")
            except Exception:
                pass
        return 0

    root = tk.Tk()
    root.title("ATCAI Manager %s" % VERSION)
    # Centred, and by the same arithmetic as the splash - the banner appears in the
    # middle and the Manager replaces it there, rather than jumping to wherever Windows
    # would have cascaded it.
    root.geometry(splash.centred_geometry(root, 900, 700))
    # Below this the tab contents start clipping, which is how the Voice tab's options
    # went unnoticed in the first place.
    root.minsize(820, 600)

    # Hidden until the splash has had its five seconds, so a half-built window never
    # shows behind it. The splash comes *after* the single-instance check above: were it
    # first, a second copy would flash a banner and vanish, which reads as a crash
    # rather than as "already running".
    banner = splash.Splash(root)
    showing = banner.show()
    if showing:
        root.withdraw()

    app = App(root)

    def reveal():
        banner.dismiss()
        root.deiconify()
        root.lift()
        root.focus_force()

    if showing:
        # Both paths call the same idempotent reveal, so a click and the timer arriving
        # in either order is fine.
        banner.on_dismiss = reveal
        root.after(banner.remaining_ms(), reveal)

    def on_close():
        app._remember()
        app.listener.stop()
        app.speaker.stop()
        lock.release()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
