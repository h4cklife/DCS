"""Choosing which microphone ATCAI listens to.

System.Speech has no device API; it opens whatever SAPI's default input token points at.
Verified 2026-10-25 that it genuinely honours that token, so selection is a matter of
writing it — and of only ever writing a device that actually exists, because SAPI
silently substitutes a different one for an id it doesn't recognise.
"""

import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "voice-bridge"))

import atcai_micselect as micselect  # noqa: E402

TOKEN = (r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\AudioInput\TokenEnums"
         r"\MMAudioIn\{0.0.1.00000000}.{b1b3e45b-3291-40fc-911e-3b168f5d266e}")


class TestParsing:
    def test_reads_a_device_row(self):
        kind, payload = micselect.parse_line("INPUT|%s|Microphone (Scarlett 2i2 USB)"
                                             % TOKEN)
        assert kind == "INPUT"
        assert payload == (TOKEN, "Microphone (Scarlett 2i2 USB)")

    def test_reads_the_current_selection(self):
        assert micselect.parse_line("CURRENT|windows-default") == (
            "CURRENT", "windows-default")
        assert micselect.parse_line("CURRENT|%s" % TOKEN) == ("CURRENT", TOKEN)

    def test_reads_what_following_windows_resolves_to(self):
        assert micselect.parse_line("WINDOWS_DEFAULT|Microphone (PS VR2 Audio)") == (
            "WINDOWS_DEFAULT", "Microphone (PS VR2 Audio)")

    def test_reads_results(self):
        assert micselect.parse_line("OK|done") == ("OK", "done")
        assert micselect.parse_line("ERROR|nope") == ("ERROR", "nope")

    @pytest.mark.parametrize("line", ["", "   ", "no pipe", "INPUT|only-an-id",
                                      "INPUT||a name", "WAT|something"])
    def test_ignores_what_it_cannot_read(self, line):
        assert micselect.parse_line(line) is None


class TestListing:
    def _canned(self, monkeypatch, lines):
        monkeypatch.setattr(micselect, "_run", lambda args, timeout=30: lines)

    def test_returns_current_resolved_and_devices(self, monkeypatch):
        self._canned(monkeypatch, [
            ("CURRENT", "windows-default"),
            ("WINDOWS_DEFAULT", "Microphone (PS VR2 Audio)"),
            ("INPUT", (TOKEN, "Microphone (Scarlett 2i2 USB)")),
            ("OK", "listed"),
        ])
        current, resolved, devices = micselect.list_devices()
        assert current == "windows-default"
        assert resolved == "Microphone (PS VR2 Audio)"
        assert devices == [(TOKEN, "Microphone (Scarlett 2i2 USB)")]

    def test_a_failure_yields_no_devices_rather_than_raising(self, monkeypatch):
        self._canned(monkeypatch, [("ERROR", "COM went wrong")])
        current, resolved, devices = micselect.list_devices()
        assert devices == [] and current is None and resolved is None


class TestSelecting:
    def test_an_explicit_device_is_set(self, monkeypatch):
        seen = {}

        def fake(args, timeout=30):
            seen["args"] = args
            return [("OK", "Microphone (Scarlett 2i2 USB)")]

        monkeypatch.setattr(micselect, "_run", fake)
        ok, message = micselect.select(TOKEN)
        assert ok and "Scarlett" in message
        assert seen["args"] == ["-Set", TOKEN]

    def test_choosing_windows_default_uses_the_right_switch(self, monkeypatch):
        seen = {}

        def fake(args, timeout=30):
            seen["args"] = args
            return [("OK", "following the Windows default")]

        monkeypatch.setattr(micselect, "_run", fake)
        assert micselect.select(micselect.WINDOWS_DEFAULT)[0] is True
        assert seen["args"] == ["-UseWindowsDefault"]

    def test_an_empty_token_means_windows_default(self, monkeypatch):
        seen = {}

        def fake(args, timeout=30):
            seen["args"] = args
            return [("OK", "ok")]

        monkeypatch.setattr(micselect, "_run", fake)
        micselect.select(None)
        assert seen["args"] == ["-UseWindowsDefault"]

    def test_an_error_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(micselect, "_run",
                            lambda args, timeout=30:
                            [("ERROR", "that microphone is not available")])
        ok, message = micselect.select(TOKEN)
        assert not ok and "not available" in message

    def test_silence_from_the_script_is_a_failure_not_a_success(self, monkeypatch):
        """Treating no answer as success would report a device set that wasn't."""
        monkeypatch.setattr(micselect, "_run", lambda args, timeout=30: [])
        ok, message = micselect.select(TOKEN)
        assert not ok and message

    def test_an_error_wins_over_a_stray_ok(self, monkeypatch):
        monkeypatch.setattr(micselect, "_run",
                            lambda args, timeout=30: [("OK", "listed"),
                                                      ("ERROR", "then it failed")])
        ok, message = micselect.select(TOKEN)
        assert not ok and "failed" in message


class TestNaming:
    def test_a_known_token_gets_its_name(self):
        assert micselect.name_for(TOKEN, [(TOKEN, "Scarlett")]) == "Scarlett"

    def test_windows_default_is_named_as_such(self):
        assert micselect.name_for(micselect.WINDOWS_DEFAULT, []) == "Windows default"
        assert micselect.name_for(None, []) == "Windows default"

    def test_a_device_that_has_gone_says_so(self):
        """A headset that was selected and is now switched off - better to say that
        than to show a blank or a raw registry path."""
        assert "no longer available" in micselect.name_for(TOKEN, [])


class TestScriptSafety:
    def test_the_script_verifies_the_device_exists_before_writing(self):
        """SAPI silently substitutes a different device for an id it doesn't know, so
        writing blind would report success while selecting something else."""
        source = (ROOT / "voice-bridge" / "micselect.ps1").read_text(encoding="utf-8")
        assert "GetAudioInputs()" in source
        assert "not available" in source

    def test_the_script_reads_back_what_it_wrote(self):
        source = (ROOT / "voice-bridge" / "micselect.ps1").read_text(encoding="utf-8")
        assert "did not keep that choice" in source

    def test_it_is_bundled_into_the_exe(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_exe", ROOT / "manager" / "build_exe.py")
        build_exe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_exe)
        assert any("micselect.ps1" in str(src) for src, _ in build_exe.BUNDLED)
