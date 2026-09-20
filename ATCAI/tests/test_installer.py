"""Finding DCS, installing into it, and writing settings."""

import re
import subprocess

import pytest

import installer


class TestRecognisingDcs:
    def test_accepts_a_real_looking_folder(self, fake_dcs):
        found = installer.inspect_path(fake_dcs)
        assert found.verified
        assert found.notes == []

    def test_refuses_an_unrelated_folder_but_explains_why(self, tmp_path):
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        found = installer.inspect_path(downloads)
        assert not found.verified
        assert "doesn't look like" in found.notes[0]

    def test_reports_a_folder_that_does_not_exist(self, tmp_path):
        found = installer.inspect_path(tmp_path / "nope")
        assert not found.verified
        assert any("does not exist" in note for note in found.notes)

    @pytest.mark.parametrize("markers", [(), ("Config",)])
    def test_needs_more_than_one_marker(self, tmp_path, markers):
        path = tmp_path / "DCS"
        path.mkdir()
        for marker in markers:
            (path / marker).mkdir()
        assert not installer.inspect_path(path).verified


class TestLocatingSavedGames:
    """Detection has to survive OneDrive moving Saved Games, so the registry wins."""

    def test_reads_the_path_out_of_the_registry(self, monkeypatch, tmp_path, on_windows):
        relocated = tmp_path / "OneDrive" / "Saved Games"
        (relocated / "DCS" / "Config").mkdir(parents=True)
        (relocated / "DCS" / "Logs").mkdir(parents=True)

        class FakeKey:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        fake_winreg = type("winreg", (), {
            "HKEY_CURRENT_USER": 0,
            "OpenKey": staticmethod(lambda *a, **k: FakeKey()),
            "QueryValueEx": staticmethod(lambda key, name: (str(relocated), 1)),
        })
        monkeypatch.setitem(__import__("sys").modules, "winreg", fake_winreg)

        assert installer._registry_saved_games() == str(relocated)
        assert relocated in installer.saved_games_roots()

    def test_parses_reg_exe_output_under_wsl(self, monkeypatch, on_wsl):
        output = (
            "\r\nHKEY_CURRENT_USER\\Software\\...\\User Shell Folders\r\n"
            "    {4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}    REG_EXPAND_SZ    "
            "C:\\Users\\bob\\Saved Games\r\n\r\n"
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: type(
            "R", (), {"stdout": output.encode("cp1252"), "returncode": 0})())
        assert installer._registry_saved_games() == "C:\\Users\\bob\\Saved Games"

    def test_survives_the_registry_being_unreadable(self, monkeypatch, on_wsl):
        def explode(*args, **kwargs):
            raise OSError("no reg.exe here")
        monkeypatch.setattr(subprocess, "run", explode)
        assert installer._registry_saved_games() is None

    def test_finds_every_dcs_variant(self, monkeypatch, tmp_path):
        root = tmp_path / "Saved Games"
        for name in ("DCS", "DCS.openbeta", "DCS.dcs_serverrelease", "NotDcs"):
            for marker in ("Config", "Logs"):
                (root / name / marker).mkdir(parents=True)
        monkeypatch.setattr(installer, "saved_games_roots", lambda: [root])

        names = sorted(found.path.name for found in installer.find_installations())
        assert names == ["DCS", "DCS.dcs_serverrelease", "DCS.openbeta"]

    def test_returns_nothing_rather_than_guessing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(installer, "saved_games_roots", lambda: [tmp_path])
        assert installer.find_installations() == []


class TestPlatformDetection:
    def test_native_windows_is_never_mistaken_for_wsl(self, monkeypatch):
        # Windows Python launched from \\wsl.localhost\... can read /proc/version off
        # the share and see "microsoft", so os.name has to be checked first. Safe to
        # patch os.name here because nothing in this test builds a Path.
        monkeypatch.setattr("os.name", "nt")
        assert installer.running_under_wsl() is False

    def test_windows_paths_are_mapped_under_wsl(self, on_wsl):
        assert installer.windows_to_local("C:\\Users\\bob") == "/mnt/c/Users/bob"

    def test_paths_are_untouched_on_windows(self, on_windows):
        assert installer.windows_to_local("C:\\Users\\bob") == "C:\\Users\\bob"


class TestInstalling:
    def test_starts_out_not_installed(self, installation):
        state = installer.status(installation)
        assert not state["installed"]
        assert state["scripts_missing"] == list(installer.SCRIPT_FILES)

    def test_installs_every_file(self, installation, repo_root):
        installer.install(installation, repo_root)

        state = installer.status(installation)
        assert state["installed"] and state["enabled"]
        assert state["scripts_missing"] == []
        for name in installer.SCRIPT_FILES:
            assert (installation.scripts_dir / name).is_file()
        assert installation.hook_path.is_file()

    def test_installs_the_hook_that_actually_works(self, installed):
        """a_do_script_file reports success but silently does nothing; a_do_script works."""
        code = re.sub(r"--\[\[.*?\]\]", "", installed.hook_path.read_text(encoding="utf-8"),
                      flags=re.S)
        code = "\n".join(line for line in code.splitlines()
                         if not line.lstrip().startswith("--"))
        assert "a_do_script(" in code
        assert "a_do_script_file(" not in code

    def test_refuses_to_install_from_an_incomplete_source(self, installation, tmp_path):
        with pytest.raises(FileNotFoundError, match="missing"):
            installer.install(installation, tmp_path)

    def test_reports_a_partial_install(self, installed):
        (installed.scripts_dir / "atc_core.lua").unlink()
        state = installer.status(installed)
        assert state["partial"] and not state["installed"]


class TestEnablingAndDisabling:
    def test_disabling_keeps_everything(self, installed):
        installer.set_enabled(installed, False)

        assert not installed.hook_path.is_file()
        assert installed.disabled_hook_path.is_file()
        assert (installed.scripts_dir / "atc_core.lua").is_file()

        state = installer.status(installed)
        assert state["installed"] and not state["enabled"]

    def test_enabling_puts_it_back(self, installed):
        installer.set_enabled(installed, False)
        installer.set_enabled(installed, True)
        assert installed.hook_path.is_file()
        assert not installed.disabled_hook_path.is_file()

    @pytest.mark.parametrize("enabled", [True, False])
    def test_asking_twice_is_harmless(self, installed, enabled):
        installer.set_enabled(installed, enabled)
        assert installer.set_enabled(installed, enabled) == []

    def test_cannot_enable_what_is_not_installed(self, installation):
        with pytest.raises(FileNotFoundError, match="not installed"):
            installer.set_enabled(installation, True)

    def test_reinstalling_clears_a_disabled_copy(self, installed, repo_root):
        installer.set_enabled(installed, False)
        installer.install(installed, repo_root)
        assert installed.hook_path.is_file()
        # Otherwise a later disable/enable could resurrect the stale copy.
        assert not installed.disabled_hook_path.is_file()


class TestRemoving:
    def test_removes_what_it_installed(self, installed):
        installer.uninstall(installed)
        assert not installed.hook_path.is_file()
        assert not (installed.scripts_dir / "atc_core.lua").is_file()
        assert not installer.status(installed)["installed"]

    def test_keeps_settings_unless_asked(self, installed):
        installer.write_config(installed, {"tts_frequency": "251.0"})
        installer.uninstall(installed)
        assert installed.config_path.is_file()

        installer.uninstall(installed, remove_config=True)
        assert not installed.config_path.is_file()

    def test_leaves_other_peoples_files_alone(self, installed):
        stranger = installed.scripts_dir / "someone_elses_script.lua"
        stranger.write_text("-- not ours", encoding="utf-8")

        installer.uninstall(installed)
        assert stranger.is_file()
        assert installed.scripts_dir.is_dir()

    def test_tidies_the_folder_when_empty(self, installed):
        installer.uninstall(installed, remove_config=True)
        assert not installed.scripts_dir.exists()


class TestSettings:
    @pytest.mark.parametrize("key,value", [
        ("tts_frequency", "251.0,305.0"),
        ("airbase_air_radius", 120000),
        ("traffic_roll_speed", 12.5),
    ])
    def test_settings_round_trip(self, installation, key, value):
        installer.write_config(installation, {key: value})
        assert installer.read_config(installation)[key] == value

    def test_reading_nothing_is_not_an_error(self, installation):
        assert installer.read_config(installation) == {}

    @pytest.mark.parametrize("bad", [
        {"not_a_setting": 1},
        {"airbase_air_radius": "far"},
        {"traffic_roll_speed": -3},
        {"tts_frequency": 251.0},
        {"airbase_air_radius": True},
    ])
    def test_bad_settings_never_reach_dcs(self, bad):
        with pytest.raises(ValueError):
            installer.render_config(bad)

    @pytest.mark.parametrize("value,expected", [
        ('a"b', '"a\\"b"'),
        ("c:\\path", '"c:\\\\path"'),
    ])
    def test_quoting_cannot_break_the_generated_lua(self, value, expected):
        assert installer.lua_quote(value) == expected

    def test_written_file_is_valid_lua_the_scripts_can_read(self, installation):
        installer.write_config(installation, {"tts_frequency": "251.0"})
        text = installation.config_path.read_text(encoding="utf-8")
        assert text.startswith("--")
        assert "ATCAI_CONFIG = {" in text

    def test_settings_list_matches_the_lua_side(self, repo_root):
        """A setting added on one side only would be silently ignored by DCS."""
        lua = (repo_root / "lua" / "atc" / "atc_config.lua").read_text(encoding="utf-8")
        block = re.search(r"ATC\.CONFIG_FIELDS = \{(.*?)\n\}", lua, re.S).group(1)
        assert set(re.findall(r"^\s+(\w+)\s*=\s*\{", block, re.M)) == set(installer.CONFIG_FIELDS)


class TestPackaging:
    def test_every_file_it_installs_exists_in_the_repo(self, repo_root):
        assert installer.missing_sources(repo_root) == []

    def test_reports_all_missing_files(self, tmp_path):
        missing = installer.missing_sources(tmp_path)
        assert len(missing) == len(installer.SCRIPT_FILES) + 1


class TestDcsRunningCheck:
    """DCS reads hooks only at startup, so the app warns when a restart is needed."""

    def test_notices_dcs(self, monkeypatch, on_wsl):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: type(
            "R", (), {"stdout": b"DCS.exe  1234 Console", "returncode": 0})())
        assert installer.is_dcs_running() is True

    def test_notices_dcs_not_running(self, monkeypatch, on_wsl):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: type(
            "R", (), {"stdout": b"INFO: No tasks are running", "returncode": 0})())
        assert installer.is_dcs_running() is False

    def test_survives_tasklist_being_unavailable(self, monkeypatch, on_wsl):
        def explode(*args, **kwargs):
            raise OSError("no tasklist")
        monkeypatch.setattr(subprocess, "run", explode)
        assert installer.is_dcs_running() is False


class TestConsoleWindows:
    """Without these flags Windows pops a console over the game for every helper call."""

    CREATE_NO_WINDOW = 0x08000000

    def test_hidden_on_windows(self, monkeypatch):
        monkeypatch.setattr("os.name", "nt")
        assert installer.no_window()["creationflags"] == self.CREATE_NO_WINDOW

    def test_no_windows_only_flags_elsewhere(self, monkeypatch):
        monkeypatch.setattr("os.name", "posix")
        assert installer.no_window() == {}
