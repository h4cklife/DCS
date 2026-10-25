"""Sending keystrokes, and refusing to.

The guard matters more than the sending. Keys go to whatever window has focus, so a
misfire types F-keys and backslashes into a browser or a chat box — the one way this
feature could do harm outside the game. Every test here runs with the real SendInput
replaced, so nothing presses anything.
"""

import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "voice-bridge"))

import atcai_sendkeys as sendkeys  # noqa: E402


@pytest.fixture
def sender(monkeypatch):
    """A SendKeys with the OS stubbed out: DCS focused, every keystroke accepted."""
    monkeypatch.setattr(sendkeys, "available", lambda: True)
    pressed = []
    made = sendkeys.SendKeys(
        sender=lambda modifiers, key: pressed.append((list(modifiers), key)) or True,
        focus=lambda: "dcs.exe",
        sleep=lambda seconds: None,
    )
    made.pressed = pressed
    return made


class TestScancodes:
    def test_the_function_keys_are_set_one_codes(self):
        """DCS reads DirectInput, which wants scan codes - virtual keys are commonly
        ignored, and that is the usual reason a first attempt does nothing."""
        assert sendkeys.scancode_for("F1") == 0x3B
        assert sendkeys.scancode_for("F9") == 0x43
        assert sendkeys.scancode_for("F12") == 0x58

    def test_the_comms_keys_people_actually_bind(self):
        assert sendkeys.scancode_for("backslash") == 0x2B
        assert sendkeys.scancode_for("\\") == 0x2B
        assert sendkeys.scancode_for("grave") == 0x29
        assert sendkeys.scancode_for("ralt") == 0x38

    def test_names_are_case_insensitive(self):
        """A hand-edited key map may say "f5" or "BACKSLASH"."""
        assert sendkeys.scancode_for("f5") == sendkeys.scancode_for("F5") == 0x3F
        assert sendkeys.scancode_for("BACKSLASH") == 0x2B
        assert sendkeys.is_extended("f12") is True
        assert sendkeys.is_extended("F10") is False

    def test_an_unknown_name_has_no_code(self):
        assert sendkeys.scancode_for("F13") is None
        assert sendkeys.scancode_for("{wingman}") is None
        assert sendkeys.scancode_for(None) is None

    def test_unknown_keys_reports_what_cannot_be_sent(self):
        assert sendkeys.unknown_keys(["backslash", "F2", "F9"]) == []
        assert sendkeys.unknown_keys(["backslash", "{wingman}"]) == ["{wingman}"]

    def test_the_extended_keys_are_flagged(self):
        """F11 and F12 arrive as something else without the extended flag."""
        assert "F11" in sendkeys.EXTENDED and "F12" in sendkeys.EXTENDED
        assert "F10" not in sendkeys.EXTENDED


class TestTheForegroundGuard:
    def test_it_sends_when_dcs_is_focused(self, sender):
        assert sender.send(["backslash", "F2", "F9"]) is True
        assert sender.pressed == [([], "backslash"), ([], "F2"), ([], "F9")]
        assert sender.last_error is None

    def test_it_sends_nothing_when_another_window_is_focused(self, monkeypatch):
        """The failure that could type into a browser or a Discord box."""
        monkeypatch.setattr(sendkeys, "available", lambda: True)
        pressed = []
        guarded = sendkeys.SendKeys(
            sender=lambda modifiers, key: pressed.append(key) or True,
            focus=lambda: "chrome.exe", sleep=lambda s: None)

        assert guarded.send(["backslash", "F2"]) is False
        assert pressed == [], "a keystroke escaped to another window"
        assert "chrome.exe" in guarded.last_error

    def test_an_unknown_focus_counts_as_not_dcs(self, monkeypatch):
        """If we cannot tell what has focus, we must not type into it."""
        monkeypatch.setattr(sendkeys, "available", lambda: True)
        pressed = []
        guarded = sendkeys.SendKeys(
            sender=lambda modifiers, key: pressed.append(key) or True,
            focus=lambda: None, sleep=lambda s: None)

        assert guarded.send(["backslash"]) is False
        assert pressed == []

    def test_losing_focus_mid_sequence_stops_it(self, monkeypatch):
        """Alt-tabbing away part-way must drop the rest, not deliver it elsewhere."""
        monkeypatch.setattr(sendkeys, "available", lambda: True)
        pressed = []
        windows = iter(["dcs.exe", "dcs.exe", "chrome.exe", "chrome.exe"])
        guarded = sendkeys.SendKeys(
            sender=lambda modifiers, key: pressed.append(key) or True,
            focus=lambda: next(windows, "chrome.exe"), sleep=lambda s: None)

        assert guarded.send(["backslash", "F2", "F9"]) is False
        assert len(pressed) == 1, "only the keys sent before focus left"
        assert "part-way" in guarded.last_error

    def test_the_guard_is_rechecked_not_cached(self, sender):
        """Checked immediately before each key, which is what makes the previous
        test possible at all."""
        calls = []
        sender._focus = lambda: calls.append(1) or "dcs.exe"
        sender.send(["backslash", "F2", "F9"])
        assert len(calls) > 3, "focus was checked once and trusted"


class TestChords:
    """Cockpit controls are modifier chords: LCtrl+G, LShift+G. A sequence of taps
    cannot express them, because the modifier has to be held across the key."""

    @pytest.mark.parametrize("spec,expected", [
        ("LCtrl+G", (["lctrl"], "G")),
        ("LShift+G", (["lshift"], "G")),
        ("LCtrl+LShift+C", (["lctrl", "lshift"], "C")),
        ("G", ([], "G")),
        ("F7", ([], "F7")),
    ])
    def test_it_reads_dcs_spelling_directly(self, spec, expected):
        """DCS writes chords this way in its binding files, so they need no
        translation on the way through."""
        assert sendkeys.parse_chord(spec) == expected

    def test_an_empty_spec_has_no_key(self):
        assert sendkeys.parse_chord("") == ([], None)
        assert sendkeys.parse_chord(None) == ([], None)

    def test_a_chord_is_sent_as_one_action(self, sender):
        assert sender.send(["LCtrl+G"]) is True
        assert sender.pressed == [(["lctrl"], "G")]

    def test_modifier_scancodes_exist(self):
        for name in ("lshift", "lctrl", "lalt", "rshift"):
            assert sendkeys.scancode_for(name) is not None, name

    def test_dcs_spellings_of_modifiers_resolve(self):
        """The binding files say LShift and LCtrl; both must map without rewriting."""
        assert sendkeys.scancode_for("LShift") == sendkeys.scancode_for("lshift")
        assert sendkeys.scancode_for("LCtrl") == sendkeys.scancode_for("lctrl")
        assert sendkeys.scancode_for("LAlt") == sendkeys.scancode_for("lalt")

    def test_an_unknown_part_is_reported_not_the_whole_chord(self):
        """"LCtrl+F13" must name F13, not fail opaquely as an unfamiliar chord."""
        assert sendkeys.unknown_keys(["LCtrl+F13"]) == ["F13"]
        assert sendkeys.unknown_keys(["Bogus+G"]) == ["bogus"]

    def test_a_chord_with_an_unknown_part_is_refused_whole(self, sender):
        assert sender.send(["LCtrl+F13"]) is False
        assert sender.pressed == [], "nothing partial was sent"

    def test_plain_sequences_still_work(self, sender):
        """The comms menus send sequences of single keys; chords must not change that."""
        assert sender.send(["backslash", "F7", "F5"]) is True
        assert [key for _, key in sender.pressed] == ["backslash", "F7", "F5"]
        assert all(mods == [] for mods, _ in sender.pressed)

    def test_modifiers_are_released_even_if_the_key_fails(self, monkeypatch):
        """A stuck Ctrl or Shift would affect every keystroke the player makes
        afterwards, in or out of the game, so release happens in a finally."""
        events = []

        def record(scancode, extended, up=False):
            events.append((scancode, "up" if up else "down"))
            # Let the modifier go down, then fail the plain key.
            return scancode != sendkeys.scancode_for("g")

        monkeypatch.setattr(sendkeys, "_press", record)
        assert sendkeys._chord(["lctrl"], "g", hold_ms=1) is False

        released = [code for code, action in events if action == "up"]
        assert sendkeys.scancode_for("lctrl") in released, "LCtrl was left held down"

    def test_modifiers_are_released_in_reverse_order(self, monkeypatch):
        events = []
        monkeypatch.setattr(sendkeys, "_press",
                            lambda scancode, extended, up=False:
                            events.append((scancode, up)) or True)
        sendkeys._chord(["lctrl", "lshift"], "c", hold_ms=1)

        order = [code for code, up in events if up]
        assert order[-2:] == [sendkeys.scancode_for("lshift"),
                              sendkeys.scancode_for("lctrl")]


class TestRefusals:
    def test_it_refuses_a_sequence_it_cannot_send(self, sender):
        assert sender.send(["backslash", "{wingman}", "F9"]) is False
        assert sender.pressed == [], "nothing partial was sent"
        assert "{wingman}" in sender.last_error

    def test_it_refuses_off_windows(self, monkeypatch):
        monkeypatch.setattr(sendkeys, "available", lambda: False)
        off = sendkeys.SendKeys(sender=lambda m, k: True, focus=lambda: "dcs.exe")
        assert off.send(["backslash"]) is False
        assert "Windows" in off.last_error

    def test_a_refused_keystroke_stops_the_sequence(self, monkeypatch):
        """If Windows rejects one key, carrying on would leave the menu half-navigated
        and the next command would start from the wrong place."""
        monkeypatch.setattr(sendkeys, "available", lambda: True)
        attempts = []

        def flaky(modifiers, key):
            attempts.append(key)
            return len(attempts) < 2

        stopped = sendkeys.SendKeys(sender=flaky, focus=lambda: "dcs.exe",
                                    sleep=lambda s: None)
        assert stopped.send(["backslash", "F2", "F9"]) is False
        assert len(attempts) == 2
        assert "refused" in stopped.last_error

    def test_an_empty_sequence_is_harmless(self, sender):
        assert sender.send([]) is True
        assert sender.pressed == []


class TestTiming:
    def test_it_waits_between_keys_but_not_after_the_last(self, monkeypatch):
        monkeypatch.setattr(sendkeys, "available", lambda: True)
        waits = []
        timed = sendkeys.SendKeys(sender=lambda m, k: True, focus=lambda: "dcs.exe",
                                  sleep=waits.append)
        timed.send(["backslash", "F2", "F9"], delay_ms=90)
        assert waits == [0.09, 0.09], "one gap between each pair, none trailing"

    def test_a_different_target_can_be_named(self, monkeypatch):
        """The Notepad test proves keystrokes work at all without involving DCS."""
        monkeypatch.setattr(sendkeys, "available", lambda: True)
        pressed = []
        notepad = sendkeys.SendKeys(
            target_process="notepad.exe",
            sender=lambda modifiers, key: pressed.append(key) or True,
            focus=lambda: "notepad.exe", sleep=lambda s: None)
        assert notepad.send(["d", "c", "s"]) is True
        assert len(pressed) == 3
