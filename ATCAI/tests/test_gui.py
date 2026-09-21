"""The manager window itself.

Needs tkinter and a display, so in practice this runs under Windows Python; it skips
cleanly elsewhere. The event loop is never entered — widgets are built, driven directly,
and torn down.
"""

import pytest

tk = pytest.importorskip("tkinter", reason="tkinter is not available in this Python")

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
