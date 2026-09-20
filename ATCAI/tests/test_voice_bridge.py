"""Speech recognition phrases, intent matching, and the inbox the mission reads."""

import subprocess

import pytest

import atcai_listen as listen
import atcai_tts as tts


@pytest.fixture
def lookup():
    return listen.phrase_to_intent()


class TestPhraseCoverage:
    """People say "request" and "requesting" interchangeably; both must always work."""

    def test_every_leading_verb_has_both_forms(self, lookup):
        for phrase, intent in lookup.items():
            verb, _, rest = phrase.partition(" ")
            if not rest:
                continue
            for first, second in listen.VERB_VARIANTS:
                if verb == first:
                    twin = "%s %s" % (second, rest)
                elif verb == second:
                    twin = "%s %s" % (first, rest)
                else:
                    continue
                assert lookup.get(twin) == intent, "%r has no counterpart %r" % (phrase, twin)

    def test_every_intent_is_reachable(self, lookup):
        assert sorted(set(lookup.values())) == sorted(listen.INTENT_PHRASES)

    def test_intents_match_what_the_mission_understands(self, repo_root):
        """An intent the Lua side doesn't know would be silently ignored in game."""
        lua = (repo_root / "lua" / "atc" / "atc_inbox.lua").read_text(encoding="utf-8")
        block = lua.split("INTENT_HANDLERS = {", 1)[1].split("}", 1)[0]
        import re
        assert set(re.findall(r"^\s+(\w+)\s*=", block, re.M)) == set(listen.INTENT_PHRASES)

    def test_expansion_is_idempotent(self):
        once = listen.expand_phrases(["request taxi"])
        assert listen.expand_phrases(once) == once


class TestIntentMatching:
    @pytest.mark.parametrize("spoken,expected", [
        ("radio check", "radio_check"),
        ("Chevy 8 1 requesting radio check", "radio_check"),
        ("Chevy 8 1 request radio check", "radio_check"),
        ("Chevy 8 1 requesting taxi to 1 3", "taxi"),
        ("Vaziani Tower Chevy 81 request taxi clearance", "taxi"),
        ("Chevy 81 ready for departure runway 13", "takeoff"),
        ("Chevy 81 requesting departure", "takeoff"),
        ("Chevy 81 reporting inbound", "inbound"),
        ("Chevy 81 report inbound", "inbound"),
        ("Tower Chevy 81 on final runway 13", "landing"),
        ("Chevy 81 requesting weapons status", "loadout"),
    ])
    def test_finds_the_request_inside_a_transmission(self, lookup, spoken, expected):
        assert listen.match_intent(spoken, lookup) == expected

    @pytest.mark.parametrize("spoken", [
        "nice weather today",
        "I would like to request a coffee",
        "",
    ])
    def test_ignores_speech_that_is_not_a_request(self, lookup, spoken):
        assert listen.match_intent(spoken, lookup) is None

    @pytest.mark.parametrize("spoken,expected", [
        ("requesting taxi to parking", "parking"),
        ("requesting landing clearance", "landing"),
    ])
    def test_longest_match_wins(self, lookup, spoken, expected):
        assert listen.match_intent(spoken, lookup) == expected

    def test_matching_ignores_case_and_spacing(self, lookup):
        assert listen.match_intent("  REQUEST   TAXI  ", lookup) == "taxi"


class TestInbox:
    def test_writes_the_lua_the_mission_expects(self, tmp_path):
        path = tmp_path / "inbox.lua"
        seq = listen.write_inbox(str(path), "taxi")
        assert path.read_text(encoding="utf-8").strip() == (
            'ATCAI_INBOX = { seq = %d, intent = "taxi" }' % seq)

    def test_sequence_is_a_rising_timestamp(self, tmp_path):
        path = tmp_path / "inbox.lua"
        first = listen.write_inbox(str(path), "taxi")
        second = listen.write_inbox(str(path), "takeoff")
        # Epoch milliseconds, so it keeps rising across restarts of the listener and the
        # mission never replays an old command.
        assert first > 1_700_000_000_000
        assert second >= first

    def test_no_temporary_file_is_left_behind(self, tmp_path):
        path = tmp_path / "inbox.lua"
        listen.write_inbox(str(path), "taxi")
        assert not (tmp_path / "inbox.lua.tmp").exists()


class TestConsoleWindows:
    """Without these flags Windows pops a console over the game for every reply."""

    CREATE_NO_WINDOW = 0x08000000

    @pytest.mark.parametrize("module", [listen, tts])
    def test_hidden_on_windows(self, monkeypatch, module):
        monkeypatch.setattr("os.name", "nt")
        assert module.no_window()["creationflags"] == self.CREATE_NO_WINDOW

    @pytest.mark.parametrize("module", [listen, tts])
    def test_no_windows_only_flags_elsewhere(self, monkeypatch, module):
        monkeypatch.setattr("os.name", "posix")
        assert module.no_window() == {}


class TestSpeechOutput:
    """The bridge must survive SRS misbehaving rather than going silently dead."""

    def _result(self, stdout=b"", returncode=0):
        return type("R", (), {"stdout": stdout, "stderr": b"", "returncode": returncode})()

    def test_reports_srs_server_not_running(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **k: self._result(b"|INFO|Could not connect to server"))
        messages = []
        tts.speak("srs.exe", tts.build_options(), "251.0", "AM", "hello", messages.append)
        assert any("SRS server not reachable" in m for m in messages)

    def test_reports_a_timeout(self, monkeypatch):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="srs", timeout=1)
        monkeypatch.setattr(subprocess, "run", timeout)
        messages = []
        tts.speak("srs.exe", tts.build_options(), "251.0", "AM", "hello", messages.append)
        assert any("timed out" in m for m in messages)

    def test_reports_a_missing_binary(self, monkeypatch):
        def missing(*args, **kwargs):
            raise OSError("not found")
        monkeypatch.setattr(subprocess, "run", missing)
        messages = []
        tts.speak("srs.exe", tts.build_options(), "251.0", "AM", "hello", messages.append)
        assert any("could not run" in m.lower() for m in messages)

    def test_quotes_in_speech_cannot_break_the_powershell_command(self, monkeypatch):
        captured = {}

        def capture(cmd, **kwargs):
            captured["cmd"] = cmd
            return self._result()

        monkeypatch.setattr(subprocess, "run", capture)
        tts.speak_local("Chevy 81's clearance", tts.build_options(), lambda m: None)
        # Passed as base64 to -EncodedCommand, so no quoting can escape into the shell.
        assert "-EncodedCommand" in captured["cmd"]


class TestLogParsing:
    @pytest.mark.parametrize("line,expected", [
        ("INFO SCRIPTING: ATCAI_TTS|251.0|AM|Cleared for takeoff.",
         ("251.0", "AM", "Cleared for takeoff.")),
        ("ATCAI_TTS|276.375,251.0|AM,AM|Taxi to holding point.",
         ("276.375,251.0", "AM,AM", "Taxi to holding point.")),
    ])
    def test_extracts_transmissions(self, line, expected):
        match = tts.LINE_RE.search(line)
        assert match and tuple(g.strip() for g in match.groups()) == expected

    @pytest.mark.parametrize("line", [
        "INFO SCRIPTING: ATCAI: atc_core.lua loaded",
        "unrelated log line",
    ])
    def test_ignores_everything_else(self, line):
        assert tts.LINE_RE.search(line) is None
