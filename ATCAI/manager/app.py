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
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "voice-bridge"))

import installer  # noqa: E402
import prefs  # noqa: E402
import atcai_listen  # noqa: E402
import atcai_tts  # noqa: E402

VERSION = "1.2.0"
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
        self.prefs = prefs.load()
        self.ptt_key_name = str(self.prefs.get("ptt_key_name", "Ctrl"))
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
        self._build_setup(tabs)
        self._build_voice(tabs)
        self._build_settings(tabs)

        self.log_view = tk.Text(self, height=10, wrap="word", state="disabled")
        self.log_view.grid(row=2, column=0, sticky="nsew", pady=(PAD, 0))
        self.rowconfigure(2, weight=1)

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

    def _build_voice(self, tabs):
        tab = ttk.Frame(tabs, padding=PAD)
        tabs.add(tab, text="Voice")
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

        reply = ttk.LabelFrame(tab, text="Hearing ATC", padding=PAD)
        reply.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
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
            var = tk.StringVar()
            self.fields[key] = var
            ttk.Entry(tab, textvariable=var, width=40).grid(
                row=index * 2, column=1, sticky="ew", padx=(PAD, 0),
                pady=(PAD if index else 0, 0))
            ttk.Label(tab, text=hint, foreground="#555").grid(
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
        self._on_atis_changed()

        started = []
        if self.auto_voice.get():
            self.listener.start(None)
            started.append("listening")
        if self.auto_replies.get():
            self.speaker.start(None)
            started.append("replies")

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

    def _run_listener(self, _options, on_log, should_stop):
        options = atcai_listen.build_options(
            inbox=str(self.installation.scripts_dir / "inbox.lua") if self.installation else None,
            min_confidence=round(self.confidence.get(), 2),
            strict=bool(self.strict.get()),
            ptt_enabled=bool(self.ptt_enabled.get()),
            ptt_key_code=int(self.ptt_key_code),
            ptt_key_name=str(self.ptt_key_name),
        )
        atcai_listen.run(options, on_log=on_log, should_stop=should_stop)

    def _run_speaker(self, _options, on_log, should_stop):
        log_path = None
        if self.installation:
            log_path = str(self.installation.path / "Logs" / "dcs.log")
        options = atcai_tts.build_options(mode=self.tts_mode.get(), log=log_path)
        atcai_tts.run(options, on_log=on_log, should_stop=should_stop)

    # ---------- settings ----------

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
            elif not var.get():
                var.set("")

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
        for var in self.fields.values():
            var.set("")
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
        self._refresh_bridge_buttons()
        self.after(150, self._drain)


def main():
    root = tk.Tk()
    root.title("ATCAI Manager %s" % VERSION)
    root.geometry("840x680")
    app = App(root)

    def on_close():
        app._remember()
        app.listener.stop()
        app.speaker.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
