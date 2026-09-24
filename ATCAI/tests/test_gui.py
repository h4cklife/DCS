"""The manager window itself.

Needs tkinter and a display, so in practice this runs under Windows Python; it skips
cleanly elsewhere. The event loop is never entered — widgets are built, driven directly,
and torn down.
"""

import pytest

tk = pytest.importorskip("tkinter", reason="tkinter is not available in this Python")
from tkinter import ttk  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except Exception as exc:                       # no display
        pytest.skip("no display available (%s)" % exc)
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def gui(tk_root, prefs_file):
    import app
    window = app.App(tk_root)
    yield window
    window.listener.stop()
    window.speaker.stop()
    window.destroy()


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """Capture message boxes instead of blocking on them."""
    import app
    errors, infos = [], []
    monkeypatch.setattr(app.messagebox, "showerror", lambda t, m: errors.append(m))
    monkeypatch.setattr(app.messagebox, "showinfo", lambda t, m: infos.append(m))
    return errors, infos


class TestWindow:
    def test_builds(self, gui):
        for name in ("install_button", "enable_button", "uninstall_button",
                     "listen_button", "speak_button", "status_label", "log_view"):
            assert hasattr(gui, name)

    def test_has_settings_fields(self, gui):
        assert len(gui.fields) >= 3

    def test_logs_what_it_did_at_startup(self, gui):
        gui._drain()
        assert "started" in gui.log_view.get("1.0", "end").lower()


class TestInstallFlow:
    def test_reports_a_fresh_folder_as_not_installed(self, gui, installation):
        gui._use(installation)
        assert "not installed" in gui.status_label.cget("text").lower()
        assert gui.warning.cget("text") == ""
        assert "disabled" in str(gui.uninstall_button.state())

    def test_reports_installed_and_on(self, gui, installed):
        gui._use(installed)
        text = gui.status_label.cget("text").lower()
        assert "installed" in text and "on" in text
        assert gui.enable_button.cget("text") == "Turn off"

    def test_reflects_being_turned_off(self, gui, installed):
        import installer
        installer.set_enabled(installed, False)
        gui._use(installed)
        assert gui.enable_button.cget("text") == "Turn on"
        assert "off" in gui.status_label.cget("text").lower()

    def test_warns_about_a_folder_that_is_not_dcs(self, gui, tmp_path):
        import installer
        stranger = tmp_path / "Downloads"
        stranger.mkdir()
        gui._use(installer.inspect_path(stranger))
        assert gui.warning.cget("text").startswith("Warning:")


class TestSettingsTab:
    def test_saves_and_reloads(self, gui, installed, quiet_dialogs):
        import installer
        gui._use(installed)
        gui.fields["tts_frequency"].set("251.0,305.0")
        gui.fields["airbase_air_radius"].set("120000")
        gui._save_settings()

        saved = installer.read_config(installed)
        assert saved["tts_frequency"] == "251.0,305.0"
        assert saved["airbase_air_radius"] == 120000

        gui.fields["tts_frequency"].set("")
        gui._load_settings()
        assert gui.fields["tts_frequency"].get() == "251.0,305.0"

    def test_reset_clears_the_file(self, gui, installed, quiet_dialogs):
        gui._use(installed)
        gui.fields["tts_frequency"].set("251.0")
        gui._save_settings()
        gui._reset_settings()
        assert not installed.config_path.is_file()

    @pytest.mark.parametrize("value,complaint", [
        ("not a number", "number"),
        ("-5", "greater than zero"),
    ])
    def test_bad_input_is_refused_before_writing(self, gui, installed, quiet_dialogs,
                                                 value, complaint):
        errors, _ = quiet_dialogs
        gui._use(installed)
        gui.fields["airbase_air_radius"].set(value)
        gui._save_settings()

        assert errors and complaint in errors[-1].lower()
        assert not installed.config_path.is_file()


class TestTabLayout:
    """The Voice tab carried talking, the mic test and hearing at once, and had grown
    taller than the window - options below the fold were simply invisible."""

    def _tab_names(self, gui):
        notebook = None
        for child in gui.winfo_children():
            if isinstance(child, ttk.Notebook):
                notebook = child
        assert notebook is not None, "no notebook in the window"
        return [notebook.tab(i, "text") for i in range(notebook.index("end"))]

    def test_each_job_has_its_own_tab(self, gui):
        assert self._tab_names(gui) == [
            "Setup", "Talking to ATC", "Test Microphone", "Hearing ATC",
            "Settings", "Log",
        ]

    def test_the_log_lives_in_a_tab_not_under_every_tab(self, gui):
        """It used to sit below the notebook, taking height from every other tab."""
        parent = gui.log_view.winfo_parent()
        assert parent != str(gui), "the log is still a direct child of the window"

    def test_the_controls_survived_the_split(self, gui):
        for name in ("listen_button", "speak_button", "mic_button", "mic_list_button",
                     "mic_settings_button", "log_view", "ptt_button"):
            assert hasattr(gui, name), "%s was lost in the split" % name


class TestSettingsShowTheirValues:
    """An empty box reads as "unset", not as "using the default", which left players
    with no idea what a setting actually was."""

    def test_boxes_start_at_the_stock_values(self, gui):
        import installer
        for key, expected in installer.CONFIG_DEFAULTS.items():
            if key not in gui.fields:
                continue
            assert gui.fields[key].get() == str(expected)

    def test_none_of_the_boxes_are_empty(self, gui):
        for key, var in gui.fields.items():
            assert var.get().strip(), "%s shows nothing at all" % key

    def test_a_saved_setting_replaces_the_default(self, gui, installed, quiet_dialogs):
        gui._use(installed)
        gui.fields["airbase_air_radius"].set("120000")
        gui._save_settings()

        gui.fields["airbase_air_radius"].set("")
        gui._load_settings()
        assert gui.fields["airbase_air_radius"].get() == "120000"

    def test_an_unsaved_setting_falls_back_to_the_default(self, gui, installed):
        gui._use(installed)
        gui.fields["airbase_air_radius"].set("")
        gui._load_settings()
        assert gui.fields["airbase_air_radius"].get() == "92600"

    def test_back_to_defaults_shows_the_defaults(self, gui, installed, quiet_dialogs):
        gui._use(installed)
        gui.fields["tts_frequency"].set("251.0")
        gui._save_settings()
        gui._reset_settings()
        assert gui.fields["tts_frequency"].get() == \
            installer_defaults()["tts_frequency"]
        assert not installed.config_path.is_file()

    def test_the_atis_box_also_shows_its_value(self, gui):
        assert gui.atis_frequency.get().strip()


def installer_defaults():
    import installer
    return {k: str(v) for k, v in installer.CONFIG_DEFAULTS.items()}


class TestVoiceControls:
    def test_start_stopped_and_labelled(self, gui):
        assert not gui.listener.running and not gui.speaker.running
        assert gui.listen_button.cget("text") == "Start listening"
        assert gui.speak_button.cget("text") == "Start replies"

    def test_state_is_visible_without_reading_the_log(self, gui):
        """Voice being off silently is what made this look broken the first time."""
        gui._refresh_bridge_buttons()
        assert "not listening" in gui.listen_state.cget("text").lower()
        assert "hear nothing" in gui.speak_state.cget("text").lower()

    def test_setup_tab_says_voice_is_off(self, gui, installed):
        gui._use(installed)
        gui._refresh_bridge_buttons()
        assert "Voice tab" in gui.voice_hint.cget("text")


class TestMicrophoneTest:
    """The panel that turns "I don't think it hears me" into a specific answer."""

    def _results(self, gui):
        return gui.mic_results.get("1.0", "end")

    def test_the_panel_exists(self, gui):
        for name in ("mic_button", "mic_device", "mic_level", "mic_results"):
            assert hasattr(gui, name)

    def test_names_the_device_windows_chose(self, gui):
        """Which microphone is in use is the thing ATCAI can't choose and won't say."""
        gui._on_mic_event("DEVICE", "Razer BlackShark V2")
        assert "Razer BlackShark V2" in gui.mic_device.cget("text")

    def test_level_drives_the_bar(self, gui):
        gui._on_mic_event("LEVEL", 73)
        assert gui.mic_level.get() == 73

    def _finish(self, gui):
        """Run the end-of-test handling the way a real test does."""
        gui._mic_finished = False
        gui._on_mic_event("DONE", None)

    def test_a_signal_problem_is_explained_not_named(self, gui):
        gui._mic_problems, gui._mic_signals = ["NoSignal"], []
        gui._mic_heard = gui._mic_rejected = 0
        self._finish(gui)
        shown = self._results(gui)
        assert "NoSignal" not in shown, "the raw enum name is not useful to a player"
        assert "no sound reached the recogniser" in shown
        assert "switched on" in shown

    def test_no_signal_is_not_reported_when_speech_was_understood(self, gui):
        """The bug: the recogniser fires NoSignal during ordinary pauses, so a working
        microphone warned about the signal between every
        sentence it had just understood."""
        gui._mic_problems = ["NoSignal", "NoSignal", "NoSignal"]
        gui._mic_signals = []
        gui._mic_heard, gui._mic_rejected = 3, 0
        self._finish(gui)
        shown = self._results(gui)
        assert "no sound reached" not in shown
        assert "understood you" in shown

    def test_no_signal_is_not_reported_when_the_device_measured_sound(self, gui):
        gui._mic_problems = ["NoSignal"]
        gui._mic_signals = [(True, 12, "Working Mic")]
        gui._mic_heard = gui._mic_rejected = 0
        self._finish(gui)
        assert "no sound reached" not in self._results(gui)

    def test_quality_complaints_survive_a_successful_test(self, gui):
        """Too quiet or too noisy still matter when the words got through."""
        gui._mic_problems = ["NoSignal", "TooSoft"]
        gui._mic_signals = []
        gui._mic_heard, gui._mic_rejected = 2, 0
        self._finish(gui)
        shown = self._results(gui)
        assert "too quiet" in shown
        assert "no sound reached" not in shown

    def test_a_repeated_problem_is_stated_once(self, gui):
        gui._mic_problems = ["TooNoisy", "TooNoisy", "TooNoisy"]
        gui._mic_signals = []
        gui._mic_heard = gui._mic_rejected = 0
        self._finish(gui)
        assert self._results(gui).count("background noise") == 1

    def test_the_verdict_is_printed_once(self, gui):
        """DONE arrives from the script and again from the worker's finally."""
        gui._mic_problems, gui._mic_signals = [], []
        gui._mic_heard, gui._mic_rejected = 1, 0
        gui._mic_finished = False
        gui._on_mic_event("DONE", None)
        gui._on_mic_event("DONE", None)
        assert self._results(gui).count("Test finished") == 1

    def test_a_recognition_shows_its_confidence(self, gui):
        gui._on_mic_event("HEARD", (0.87, "request taxi"))
        assert "request taxi" in self._results(gui)
        assert "87" in self._results(gui)

    def test_a_rejection_is_reported_at_all(self, gui):
        """The whole point: speech that matched nothing is invisible while flying."""
        gui._on_mic_event("REJECTED", (0.3, "request tax return"))
        shown = self._results(gui)
        assert "matched no request" in shown
        assert "request tax return" in shown

    def test_a_rejection_without_words_still_reports(self, gui):
        gui._on_mic_event("REJECTED", (0.0, ""))
        assert "matched no request" in self._results(gui)

    def test_the_verdict_distinguishes_the_three_outcomes(self, gui):
        gui._mic_signals = []
        gui._mic_heard, gui._mic_rejected = 0, 0
        assert "Nothing was heard" in gui._mic_verdict()

        gui._mic_heard, gui._mic_rejected = 0, 2
        verdict = gui._mic_verdict()
        assert "nothing matched" in verdict, "sound arriving but not matching is its own case"

        gui._mic_heard, gui._mic_rejected = 1, 0
        assert "understood you" in gui._mic_verdict()

    def test_finishing_re_enables_the_button(self, gui):
        gui.mic_button.state(["disabled"])
        gui._mic_finished = False
        gui._on_mic_event("DONE", None)
        assert "disabled" not in gui.mic_button.state()

    def test_the_device_list_shows_what_is_in_use_and_what_else_exists(self, gui):
        gui._mic_inputs_found = [(True, "Scarlett 2i2"), (False, "Razer BlackShark"),
                                 (False, "Steam Streaming Microphone")]
        gui._show_inputs()
        shown = gui.mic_inputs.cget("text")
        assert "In use: Scarlett 2i2" in shown
        assert "Razer BlackShark" in shown
        assert "Steam Streaming Microphone" in shown

    def test_an_empty_list_says_so(self, gui):
        gui._mic_inputs_found = []
        gui._show_inputs()
        assert "No active recording devices" in gui.mic_inputs.cget("text")

    def test_a_silent_test_names_the_microphone_it_could_have_used(self, gui):
        """The whole point of listing: ATCAI can't see the alternatives, the player can."""
        gui._mic_heard, gui._mic_rejected = 0, 0
        gui._mic_signals = []
        gui._mic_inputs_found = [(True, "Scarlett 2i2"), (False, "Razer BlackShark")]
        verdict = gui._mic_verdict()
        assert "Razer BlackShark" in verdict
        assert "Scarlett 2i2" not in verdict, "naming the dead device again helps nobody"

    def test_a_flat_device_beside_a_live_one_names_the_live_one(self, gui):
        """The situation that actually bit: the default microphone was dead while
        another had signal, and the verdict could only say "nothing was heard"."""
        gui._mic_heard, gui._mic_rejected = 0, 0
        gui._mic_signals = [
            (True, 0, "Microphone (Razer BlackShark V2 HS 2.4)"),
            (False, 0, "Microphone (Steam Streaming Microphone)"),
            (False, 4, "Microphone (Scarlett 2i2 USB)"),
        ]
        verdict = gui._mic_verdict()
        assert "Scarlett 2i2 USB" in verdict
        assert "Steam Streaming" not in verdict, "only the device with signal is useful"
        assert "communications device" in verdict, \
            "Windows keeps two defaults and setting one is not enough"

    def test_everything_flat_does_not_invent_a_culprit(self, gui):
        gui._mic_heard, gui._mic_rejected = 0, 0
        gui._mic_signals = [(True, 0, "Mic A"), (False, 0, "Mic B")]
        verdict = gui._mic_verdict()
        assert "Mic B" not in verdict
        assert "switched on" in verdict

    def test_measured_signal_outranks_the_older_guess(self, gui):
        """With measurements available, the verdict must not fall back to listing
        devices it knows nothing about."""
        gui._mic_heard, gui._mic_rejected = 0, 0
        gui._mic_inputs_found = [(True, "Mic A"), (False, "Mic B")]
        gui._mic_signals = [(True, 0, "Mic A"), (False, 12, "Mic C")]
        assert "Mic C" in gui._mic_verdict()

    def test_a_silent_test_with_no_alternatives_still_advises(self, gui):
        gui._mic_heard, gui._mic_rejected = 0, 0
        gui._mic_signals = []
        gui._mic_inputs_found = [(True, "Scarlett 2i2")]
        assert "muted" in gui._mic_verdict()

    def test_sound_settings_button_explains_what_to_do_there(self, gui, monkeypatch):
        import app
        monkeypatch.setattr(app.atcai_mictest, "open_sound_settings",
                            lambda say=None: True)
        gui._open_sound_settings()
        shown = gui.mic_results.get("1.0", "end")
        assert "Set as Default Device" in shown
        assert "Test microphone again" in shown

    def test_sound_settings_failure_is_not_claimed_as_success(self, gui, monkeypatch):
        import app
        monkeypatch.setattr(app.atcai_mictest, "open_sound_settings",
                            lambda say=None: False)
        gui._open_sound_settings()
        assert "Set as Default Device" not in gui.mic_results.get("1.0", "end")

    def test_listing_is_allowed_while_listening(self, gui, monkeypatch):
        """Unlike the full test, listing never opens the microphone."""
        import app
        monkeypatch.setattr(type(gui.listener), "running", property(lambda self: True))
        monkeypatch.setattr(app.atcai_mictest, "list_devices", lambda: [(True, "Mic")])
        gui._refresh_inputs()
        gui._mic_list_thread.join(timeout=5)
        assert not gui._mic_list_thread.is_alive()

    def test_it_refuses_to_fight_the_listener_for_the_microphone(self, gui, monkeypatch):
        """Both would open the same device; the test would report a dead mic."""
        monkeypatch.setattr(type(gui.listener), "running", property(lambda self: True))
        gui._start_mic_test()
        assert "Stop listening first" in self._results(gui)
        assert not getattr(gui, "_mic_thread", None)


class TestPreferences:
    def test_restored_into_the_window(self, tk_root, prefs_file):
        import app
        import prefs
        prefs.save({"tts_mode": "srs", "min_confidence": 0.85, "strict": True}, prefs_file)

        window = app.App(tk_root)
        try:
            assert window.tts_mode.get() == "srs"
            assert round(window.confidence.get(), 2) == 0.85
            assert window.strict.get() is True
        finally:
            window.destroy()

    def test_startup_does_not_overwrite_saved_settings(self, tk_root, prefs_file):
        """_detect() runs before the controls are seeded, so saving must be suppressed."""
        import app
        import prefs
        prefs.save({"tts_mode": "srs"}, prefs_file)

        window = app.App(tk_root)
        try:
            assert prefs.load(prefs_file)["tts_mode"] == "srs"
        finally:
            window.destroy()

    def test_changes_are_written_back(self, gui, prefs_file):
        import prefs
        gui.tts_mode.set("srs")
        gui._remember()
        assert prefs.load(prefs_file)["tts_mode"] == "srs"


def test_log_messages_reach_the_pane(gui):
    gui._enqueue("test", "hello from the test")
    gui._drain()
    assert "hello from the test" in gui.log_view.get("1.0", "end")


class TestPushToTalkControls:
    """Configurable and off by default, because most people prefer open-mic."""

    def test_off_by_default(self, gui):
        assert gui.ptt_enabled.get() is False
        assert "disabled" in str(gui.ptt_button.state()), \
            "the key cannot be changed while push-to-talk is off"

    def test_shows_the_current_key(self, gui):
        assert "Ctrl" in gui.ptt_key_label.cget("text")

    def test_enabling_lets_you_change_the_key(self, gui):
        gui.ptt_enabled.set(True)
        gui._refresh_ptt()
        assert "disabled" not in str(gui.ptt_button.state())

    def test_setting_is_remembered(self, gui, prefs_file):
        import prefs
        gui.ptt_enabled.set(True)
        gui.ptt_key_code = 0xA3           # Right Ctrl
        gui.ptt_key_name = "Control_R"
        gui._remember()

        saved = prefs.load(prefs_file)
        assert saved["ptt_enabled"] is True
        assert saved["ptt_key_code"] == 0xA3
        assert saved["ptt_key_name"] == "Control_R"

    def test_restored_on_restart(self, tk_root, prefs_file):
        import app
        import prefs
        prefs.save({"ptt_enabled": True, "ptt_key_code": 0xA3,
                    "ptt_key_name": "Control_R"}, prefs_file)

        window = app.App(tk_root)
        try:
            assert window.ptt_enabled.get() is True
            assert window.ptt_key_code == 0xA3
            assert "Control_R" in window.ptt_key_label.cget("text")
        finally:
            window.destroy()

    def test_passed_through_to_the_listener(self, gui, installed, monkeypatch):
        """What the window shows must be what the recogniser actually uses."""
        gui._use(installed)
        gui.ptt_enabled.set(True)
        gui.ptt_key_code = 0xA3
        gui.ptt_key_name = "Control_R"

        captured = {}
        import atcai_listen
        monkeypatch.setattr(atcai_listen, "run",
                            lambda options, on_log=None, should_stop=None:
                            captured.update(vars(options)))
        gui._run_listener(None, lambda m: None, lambda: True)

        assert captured["ptt_enabled"] is True
        assert captured["ptt_key_code"] == 0xA3
        assert captured["ptt_key_name"] == "Control_R"


class TestAtisControls:
    """The field must always show what is actually configured, typed or auto-picked."""

    def test_defaults_to_the_recommended_frequency(self, gui):
        assert gui.atis_enabled.get() is True
        assert gui.atis_frequency.get() == "380.000"
        assert gui.atis_auto.get() is False

    def test_typing_is_allowed_until_auto_is_chosen(self, gui):
        assert "disabled" not in str(gui.atis_entry.state())
        gui.atis_auto.set(True)
        gui._on_atis_changed()
        assert "disabled" in str(gui.atis_entry.state()), \
            "the field is read-only while the manager is choosing"

    def test_auto_fills_the_field_with_its_choice(self, gui):
        gui.atis_frequency.set("111.111")
        gui.atis_auto.set(True)
        gui._on_atis_auto_toggled()
        # Whatever it picked, the field must show it rather than the stale value.
        assert gui.atis_frequency.get() != "111.111"
        assert 225.0 <= float(gui.atis_frequency.get()) <= 399.975

    def test_warns_about_a_frequency_aircraft_cannot_tune(self, gui):
        gui.atis_frequency.set("162.400")
        gui._on_atis_changed()
        assert "225-400" in gui.atis_note.cget("text")

    def test_warns_about_a_frequency_an_airfield_uses(self, gui):
        # Only meaningful with real terrain data available.
        import frequencies as freq_reader
        terrains = gui._terrain_frequencies()
        if not terrains:
            pytest.skip("no DCS terrain data available")
        clash = next(f for f in freq_reader.used_frequencies(terrains) if 225 <= f <= 400)
        gui.atis_frequency.set("%.3f" % clash)
        gui._on_atis_changed()
        assert "talk over" in gui.atis_note.cget("text")

    def test_rejects_nonsense(self, gui):
        gui.atis_frequency.set("banana")
        gui._on_atis_changed()
        assert "not a frequency" in gui.atis_note.cget("text")

    def test_turning_it_off_says_so(self, gui):
        gui.atis_enabled.set(False)
        gui._on_atis_changed()
        assert "only given when you ask" in gui.atis_note.cget("text")

    def test_settings_reach_the_mission_config(self, gui, installed, quiet_dialogs):
        import installer
        gui._use(installed)
        gui.atis_enabled.set(True)
        gui.atis_frequency.set("377.500")
        gui._save_settings()

        saved = installer.read_config(installed)
        assert saved["atis_enabled"] is True
        assert saved["atis_frequency"] == "377.500"

    def test_remembered_across_restarts(self, tk_root, prefs_file):
        import app
        import prefs
        prefs.save({"atis_frequency": "355.000", "atis_auto_frequency": True}, prefs_file)

        window = app.App(tk_root)
        try:
            assert window.atis_frequency.get() == "355.000"
            assert window.atis_auto.get() is True
        finally:
            window.destroy()
