"""The microphone diagnostic: parsing, and the behaviour that makes it worth having.

None of this needs Windows or a microphone - the line protocol is the seam, so the
parsing and the collapsing logic are testable anywhere.
"""

import sys
import types

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "voice-bridge"))

import atcai_mictest as mictest  # noqa: E402


class TestParsing:
    @pytest.mark.parametrize("line,expected", [
        ("DEVICE|Razer BlackShark V2", ("DEVICE", "Razer BlackShark V2")),
        ("READY|15", ("READY", 15)),
        ("LEVEL|42", ("LEVEL", 42)),
        ("STATE|Speech", ("STATE", "Speech")),
        ("PROBLEM|TooNoisy", ("PROBLEM", "TooNoisy")),
        ("HEARD|0.87|request taxi", ("HEARD", (0.87, "request taxi"))),
        ("REJECTED|0.31|hello there", ("REJECTED", (0.31, "hello there"))),
        ("DONE|", ("DONE", None)),
        ("ERROR|could not open the microphone", ("ERROR", "could not open the microphone")),
    ])
    def test_reads_each_kind(self, line, expected):
        assert mictest.parse_line(line) == expected

    @pytest.mark.parametrize("line", ["", "   ", "no pipe here", "LEVEL|abc",
                                      "READY|soon", "HEARD|notanumber|text",
                                      "WAT|something"])
    def test_ignores_anything_it_cannot_read(self, line):
        assert mictest.parse_line(line) is None

    def test_level_is_clamped(self):
        """A level outside 0-100 would drive the progress bar off its scale."""
        assert mictest.parse_line("LEVEL|500") == ("LEVEL", 100)
        assert mictest.parse_line("LEVEL|-20") == ("LEVEL", 0)

    def test_a_rejection_can_be_empty(self):
        """The recogniser sometimes rejects without offering a guess at the words."""
        assert mictest.parse_line("REJECTED|0.00|") == ("REJECTED", (0.0, ""))

    def test_text_containing_a_pipe_survives(self):
        kind, payload = mictest.parse_line("HEARD|0.90|request taxi | runway 13")
        assert payload == (0.90, "request taxi | runway 13")


class TestDeviceListing:
    def test_reads_a_device_row(self):
        assert mictest.parse_line("INPUT|1|Microphone (Scarlett 2i2 USB)") == (
            "INPUT", (True, "Microphone (Scarlett 2i2 USB)"))
        assert mictest.parse_line("INPUT|0|Razer BlackShark") == (
            "INPUT", (False, "Razer BlackShark"))

    def test_a_nameless_device_is_ignored(self):
        assert mictest.parse_line("INPUT|1|") is None
        assert mictest.parse_line("INPUT|1|   ") is None

    def test_a_name_containing_a_pipe_survives(self):
        kind, payload = mictest.parse_line("INPUT|0|Mic (A|B)")
        assert payload == (False, "Mic (A|B)")

    def test_listing_does_not_hold_the_microphone(self, monkeypatch):
        """It must be safe while the real recogniser is listening, so it runs the
        script in a mode that never opens an audio device."""
        captured = {}

        class FakeProcess:
            def __init__(self, command):
                captured["command"] = command
                self.stdout = iter([b"INPUT|1|Test Mic\n", b"DONE|\n"])

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass

        monkeypatch.setattr(mictest.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mictest.subprocess, "Popen",
                            lambda command, **k: FakeProcess(command))
        monkeypatch.setattr(mictest, "write_spec", lambda path=None: "spec.json")
        monkeypatch.setattr(mictest, "_discard", lambda path: None)

        found = mictest.list_devices()
        assert found == [(True, "Test Mic")]
        assert "-ListOnly" in captured["command"]

    def test_the_full_test_does_not_pass_list_only(self, monkeypatch):
        captured = {}

        class FakeProcess:
            def __init__(self, command):
                captured["command"] = command
                self.stdout = iter([b"DONE|\n"])

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass

        monkeypatch.setattr(mictest.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mictest.subprocess, "Popen",
                            lambda command, **k: FakeProcess(command))
        monkeypatch.setattr(mictest, "write_spec", lambda path=None: "spec.json")
        monkeypatch.setattr(mictest, "_discard", lambda path: None)

        mictest.run(seconds=5)
        assert "-ListOnly" not in captured["command"]


class TestMeasuredSignal:
    """Read from the audio endpoint rather than inferred from the recogniser, so the
    test can report on a device the recogniser isn't using."""

    def test_reads_a_signal_row(self):
        assert mictest.parse_line("SIGNAL|1|0|Microphone (Razer)") == (
            "SIGNAL", (True, 0, "Microphone (Razer)"))
        assert mictest.parse_line("SIGNAL|0|37|Microphone (Scarlett 2i2 USB)") == (
            "SIGNAL", (False, 37, "Microphone (Scarlett 2i2 USB)"))

    def test_level_is_clamped(self):
        assert mictest.parse_line("SIGNAL|0|500|Mic")[1][1] == 100
        assert mictest.parse_line("SIGNAL|0|-5|Mic")[1][1] == 0

    @pytest.mark.parametrize("line", ["SIGNAL|0|x|Mic", "SIGNAL|0|4|", "SIGNAL|0|4"])
    def test_malformed_rows_are_ignored(self, line):
        assert mictest.parse_line(line) is None

    def test_a_name_containing_a_pipe_survives(self):
        assert mictest.parse_line("SIGNAL|0|4|Mic (A|B)")[1][2] == "Mic (A|B)"


class TestSoundSettings:
    def test_opens_the_recording_tab_directly(self, monkeypatch):
        """mmsys.cpl,,1 lands on Recording; ms-settings only reaches the Sound page."""
        launched = []
        monkeypatch.setattr(mictest.subprocess, "Popen",
                            lambda command, **k: launched.append(command))
        assert mictest.open_sound_settings() is True
        assert launched[0] == mictest.SOUND_PANEL
        assert "mmsys.cpl,,1" in launched[0]

    def test_falls_back_when_rundll32_is_missing(self, monkeypatch):
        launched = []

        def popen(command, **kwargs):
            if command is mictest.SOUND_PANEL:
                raise OSError("no rundll32")
            launched.append(command)

        monkeypatch.setattr(mictest.subprocess, "Popen", popen)
        assert mictest.open_sound_settings() is True
        assert launched == [mictest.SOUND_PANEL_FALLBACK]

    def test_reports_when_nothing_opens(self, monkeypatch):
        def popen(command, **kwargs):
            raise OSError("nothing works")

        monkeypatch.setattr(mictest.subprocess, "Popen", popen)
        said = []
        assert mictest.open_sound_settings(say=said.append) is False
        assert said and "sound settings" in said[0]


class TestAdvice:
    def test_every_problem_is_explained_in_plain_words(self):
        for name in ("NoSignal", "TooSoft", "TooLoud", "TooNoisy"):
            advice = mictest.describe_problem(name)
            assert advice != name, "%s is still the raw enum name" % name
            assert len(advice) > 20

    def test_silence_is_not_described_as_a_fault(self):
        """NoSignal fires in the gaps between sentences on a working microphone, so the
        wording must not assert the hardware is broken. The original phrasing - "no audio
        at all from the microphone - check it's plugged in" - sent two debugging sessions
        after the wrong device."""
        advice = mictest.describe_problem("NoSignal")
        assert "expected" in advice, "silence in a quiet room is normal, not a fault"
        assert "if you were speaking" in advice, "the advice must be conditional"
        assert "no audio at all" not in advice

    def test_it_mentions_the_headset_mute_that_actually_caused_it(self):
        assert "headset" in mictest.describe_problem("NoSignal")

    def test_an_unknown_problem_is_passed_through(self):
        assert mictest.describe_problem("SomethingNew") == "SomethingNew"

    def test_noise_advice_mentions_the_fix(self):
        """The speakers-into-the-mic case is the one players actually hit."""
        assert "push-to-talk" in mictest.describe_problem("TooNoisy")


class TestGrammarIsShared:
    def test_the_test_uses_the_same_phrases_as_the_real_recogniser(self, tmp_path):
        """A phrase that matches in the test must match in the air, or the test lies."""
        import json
        import atcai_listen

        path = mictest.write_spec(str(tmp_path / "spec.json"))
        spec = json.loads(open(path, encoding="utf-8").read())
        assert spec["requests"] == sorted(atcai_listen.phrase_to_intent())
        assert spec["wildcards"] is True

    def test_the_spec_includes_the_newer_intents(self, tmp_path):
        import json
        path = mictest.write_spec(str(tmp_path / "spec.json"))
        phrases = json.loads(open(path, encoding="utf-8").read())["requests"]
        assert "mayday" in phrases
        assert any(p.startswith("request vectors") for p in phrases)


class TestStreamHandling:
    """run() drives a subprocess; the parts worth testing are what it does with lines."""

    def _run_with(self, monkeypatch, lines, seen):
        class FakeProcess:
            def __init__(self):
                self.stdout = iter([l.encode("cp1252") for l in lines])
                self.terminated = False

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                self.terminated = True

            def kill(self):
                pass

        monkeypatch.setattr(mictest.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mictest.subprocess, "Popen", lambda *a, **k: FakeProcess())
        monkeypatch.setattr(mictest, "write_spec", lambda path=None: "spec.json")
        monkeypatch.setattr(mictest, "_discard", lambda path: None)
        return mictest.run(seconds=1, on_event=lambda k, p: seen.append((k, p)))

    def test_repeated_problems_are_collapsed(self, monkeypatch):
        """NoSignal repeats once a second for the whole test; saying it once is enough."""
        seen = []
        self._run_with(monkeypatch, [
            "DEVICE|Test Mic\n", "PROBLEM|NoSignal\n", "PROBLEM|NoSignal\n",
            "PROBLEM|NoSignal\n", "DONE|\n",
        ], seen)
        assert [k for k, _ in seen].count("PROBLEM") == 1

    def test_a_problem_that_returns_is_not_repeated(self, monkeypatch):
        """The bug: collapsing only consecutive duplicates meant a recognition in
        between reset the run, so a working microphone produced a wall of identical
        signal warnings interleaved with the speech it had understood."""
        seen = []
        self._run_with(monkeypatch, [
            "PROBLEM|NoSignal\n", "HEARD|0.95|request taxi\n", "PROBLEM|NoSignal\n",
            "HEARD|0.94|request takeoff\n", "PROBLEM|NoSignal\n", "DONE|\n",
        ], seen)
        assert [p for k, p in seen if k == "PROBLEM"] == ["NoSignal"]
        assert [k for k, _ in seen].count("HEARD") == 2, "recognitions are never dropped"

    def test_distinct_problems_are_each_reported(self, monkeypatch):
        seen = []
        self._run_with(monkeypatch, [
            "PROBLEM|NoSignal\n", "PROBLEM|TooSoft\n", "PROBLEM|NoSignal\n", "DONE|\n",
        ], seen)
        assert [p for k, p in seen if k == "PROBLEM"] == ["NoSignal", "TooSoft"]

    def test_recognitions_are_never_collapsed(self, monkeypatch):
        """Saying the same thing twice is a result, not a repeat to be swallowed."""
        seen = []
        self._run_with(monkeypatch, [
            "HEARD|0.90|request taxi\n", "HEARD|0.90|request taxi\n", "DONE|\n",
        ], seen)
        assert [k for k, _ in seen].count("HEARD") == 2

    def test_unreadable_lines_do_not_stop_the_stream(self, monkeypatch):
        seen = []
        self._run_with(monkeypatch, [
            "DEVICE|Test Mic\n", "garbage\n", "HEARD|0.90|request taxi\n", "DONE|\n",
        ], seen)
        assert ("HEARD", (0.9, "request taxi")) in seen

    def test_a_missing_script_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(mictest.os.path, "exists", lambda p: False)
        seen = []
        assert mictest.run(seconds=1, on_event=lambda k, p: seen.append((k, p))) == 1
        assert seen and seen[0][0] == "ERROR"
