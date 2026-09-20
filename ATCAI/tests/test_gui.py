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
