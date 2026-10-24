"""Comms-menu key commands: everything up to the keypress.

The feature has no feedback — nothing tells us a keypress did what we meant. So the
whole testable surface is the decision: which sequence, for which aircraft, in which
situation, and every reason to refuse. Phase A has no transport but DryRun, so these
tests also pin down that nothing can be pressed yet.
"""

import json
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "voice-bridge"))

import atcai_keys as keys  # noqa: E402
import atcai_listen as listen  # noqa: E402

REAL_MAPS = str(ROOT / "voice-bridge" / "keymaps")

STATE_LINE = ("2026-10-24 19:04:11.123 INFO    SCRIPTING: ATCAI_STATE|aircraft=F-15C"
              "|wingmen=3|onGround=0|awacs=1|awacsnm=42|tanker=1"
              "|slot2=1|slot3=1|slot4=1")


@pytest.fixture
def state():
    return keys.parse_state(STATE_LINE)


class TestStateParsing:
    def test_reads_a_line_out_of_a_log_entry(self, state):
        assert state["aircraft"] == "F-15C"
        assert state["wingmen"] == 3
        assert state["slot2"] == 1
        assert state["onGround"] == 0
        assert state["awacs"] == 1
        assert state["awacsnm"] == 42
        assert state["tanker"] == 1

    def test_numbers_become_numbers(self, state):
        """Conditions compare numerically; strings would silently never match."""
        assert isinstance(state["wingmen"], int)
        assert isinstance(state["aircraft"], str)

    @pytest.mark.parametrize("line", ["", "no state here", "ATCAI_TTS|251|AM|hello"])
    def test_other_log_lines_are_ignored(self, line):
        assert keys.parse_state(line) is None

    def test_an_unknown_field_is_kept(self):
        """A newer mission script may publish something this build never heard of."""
        parsed = keys.parse_state("ATCAI_STATE|aircraft=F-15C|newthing=7")
        assert parsed["newthing"] == 7

    def test_a_malformed_pair_does_not_lose_the_rest(self):
        parsed = keys.parse_state("ATCAI_STATE|aircraft=F-15C|=5|wingmen=2")
        assert parsed["aircraft"] == "F-15C" and parsed["wingmen"] == 2


class TestConditions:
    @pytest.mark.parametrize("condition,expected", [
        ("wingmen>=1", True), ("wingmen>=4", False), ("wingmen==3", True),
        ("wingmen!=3", False), ("wingmen>0", True), ("wingmen<1", False),
        ("onGround==0", True), ("awacs", True), ("slot2", True), ("slot4", True),
    ])
    def test_evaluates_against_the_state(self, state, condition, expected):
        assert keys.check_condition(condition, state) is expected

    def test_a_zero_flag_is_false(self):
        assert keys.check_condition("awacs", {"awacs": 0}) is False

    def test_a_missing_field_is_false_never_assumed(self):
        """Guessing here would fire a sequence into a menu that isn't there."""
        assert keys.check_condition("awacs", {"aircraft": "F-15C"}) is False
        assert keys.check_condition("wingmen>=1", {}) is False

    @pytest.mark.parametrize("condition", ["", "   ", "wingmen >>> 1", "1>=wingmen"])
    def test_nonsense_is_false_not_an_error(self, condition):
        assert keys.check_condition(condition, {"wingmen": 4}) is False


class TestKeymaps:
    def test_the_f15c_map_loads(self):
        keymap = keys.load_keymap("F-15C", REAL_MAPS)
        assert keymap is not None
        assert keymap["aircraft"] == "F-15C"
        assert "awacs_picture" in keymap["commands"]

    def test_the_shipped_map_declares_whether_it_is_verified(self):
        """Guessed sequences and walked-through ones must be distinguishable, so nobody
        treats the first as established fact. The F-15C map was confirmed in the
        cockpit; every one of the originally guessed sequences turned out wrong."""
        keymap = keys.load_keymap("F-15C", REAL_MAPS)
        assert keymap["verified"] is True
        assert keymap.get("verified_notes"), "a verified map should say how"

    def test_an_unknown_aircraft_has_no_map(self):
        assert keys.load_keymap("MiG-21Bis", REAL_MAPS) is None
        assert keys.load_keymap(None, REAL_MAPS) is None

    def test_a_broken_map_reads_as_missing_rather_than_raising(self, tmp_path):
        """A bad file should make the feature decline for that airframe, not kill
        voice input altogether."""
        (tmp_path / "Broken.json").write_text("{not json", encoding="utf-8")
        (tmp_path / "NoCommands.json").write_text('{"aircraft": "X"}', encoding="utf-8")
        assert keys.load_keymap("Broken", str(tmp_path)) is None
        assert keys.load_keymap("NoCommands", str(tmp_path)) is None

    def test_available_maps_lists_only_usable_ones(self, tmp_path):
        (tmp_path / "Good.json").write_text(
            json.dumps({"aircraft": "Good", "commands": {"a": {"keys": ["F1"]}}}),
            encoding="utf-8")
        (tmp_path / "Broken.json").write_text("{nope", encoding="utf-8")
        assert keys.available_maps(str(tmp_path)) == ["Good"]

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert keys.available_maps(str(tmp_path / "nothing-here")) == []


class TestResolution:
    def test_resolves_a_command_for_the_current_aircraft(self, state):
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS)
        assert resolved.ok
        # display keeps the readable form; keys carry the real key the map binds
        # the comms menu to, ready to send.
        assert resolved.display == ["comms", "F7", "F5"]
        assert resolved.keys == ["backslash", "F7", "F5"]
        assert resolved.aircraft == "F-15C"
        assert resolved.delay_ms == 90

    def test_refuses_when_the_condition_is_unmet_and_says_why(self, state):
        state["wingmen"] = 0
        resolved = keys.resolve("flight_rejoin", state, directory=REAL_MAPS)
        assert not resolved.ok
        assert "wingmen" in resolved.reason

    def test_refuses_without_an_awacs(self, state):
        state["awacs"] = 0
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS)
        assert not resolved.ok
        assert "AWACS" in resolved.reason

    def test_refuses_an_aircraft_with_no_map(self, state):
        state["aircraft"] = "Su-27"
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS)
        assert not resolved.ok
        assert "Su-27" in resolved.reason

    def test_refuses_a_command_the_map_does_not_define(self, state):
        resolved = keys.resolve("flight_do_a_barrel_roll", state, directory=REAL_MAPS)
        assert not resolved.ok
        assert "key map" in resolved.reason

    def test_refuses_before_any_mission_state_arrives(self):
        """Pressing keys based on no knowledge of the situation is the thing to avoid."""
        resolved = keys.resolve("awacs_picture", None, directory=REAL_MAPS)
        assert not resolved.ok
        assert "state" in resolved.reason

    def test_refuses_while_the_feature_is_off(self, state):
        resolved = keys.resolve("awacs_picture", state, enabled=False,
                                directory=REAL_MAPS)
        assert not resolved.ok
        assert resolved.reason == keys.REFUSAL_DISABLED

    def test_every_refusal_carries_a_reason(self, state):
        """A refusal the player can't explain is indistinguishable from a broken
        feature - which is how the microphone saga went."""
        cases = [
            ("awacs_picture", None, True),
            ("awacs_picture", dict(state, aircraft="Su-27"), True),
            ("nope", state, True),
            ("flight_rejoin", dict(state, wingmen=0), True),
        ]
        for intent, st, _ in cases:
            resolved = keys.resolve(intent, st, directory=REAL_MAPS)
            assert not resolved.ok
            assert resolved.reason and len(resolved.reason) > 5


class TestDecisionsStayFreeOfTheOS:
    """The module that decides what a command means must not be the module that
    presses keys. Keeping them apart is what makes the decisions testable anywhere and
    confines the dangerous part to one small file."""

    def test_the_decision_module_touches_no_os_api(self):
        source = (ROOT / "voice-bridge" / "atcai_keys.py").read_text(encoding="utf-8")
        for forbidden in ("ctypes", "SendInput", "windll", "WinDLL"):
            assert forbidden not in source, \
                "%s belongs in atcai_sendkeys.py, not here" % forbidden

    def test_the_decision_module_cannot_press_anything(self):
        for name in ("SendInput", "SendKeys", "press"):
            assert not hasattr(keys, name)

    def test_dry_run_records_without_sending(self, state):
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS)
        transport = keys.DryRun()
        assert transport.send(resolved.keys, resolved.delay_ms) is True
        assert transport.sent == [["backslash", "F7", "F5"]]
        assert transport.name == "dry-run"


class TestMapsAreEditable:
    """The shipped maps live inside the exe, so "edit the phrases" would be a lie
    without copying them somewhere writable."""

    def test_the_user_folder_is_beside_the_settings(self):
        assert "keymaps" in keys.user_keymap_dir()
        assert keys.user_keymap_dir() != keys.bundled_keymap_dir()

    def test_seeding_copies_the_shipped_maps(self, tmp_path):
        copied = keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        assert set(copied) == {"F-15C", "A-10A", "Su-25T", "TF-51D"}
        assert keys.load_keymap("F-15C", str(tmp_path))["verified"] is True

    def test_seeding_twice_copies_nothing_the_second_time(self, tmp_path):
        keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        assert keys.seed_user_keymaps(str(tmp_path), REAL_MAPS) == []

    def test_an_edited_map_is_never_overwritten(self, tmp_path):
        """An update bringing a new aircraft must not discard the phrasings someone
        chose for the old ones."""
        keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        edited = tmp_path / "F-15C.json"
        edited.write_text(json.dumps({
            "aircraft": "F-15C", "verified": True,
            "commands": {"awacs_picture": {"keys": ["comms", "F7", "F5"],
                                           "phrases": ["my own words"]}},
        }), encoding="utf-8")

        keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        after = keys.load_keymap("F-15C", str(tmp_path))
        assert after["commands"]["awacs_picture"]["phrases"] == ["my own words"]

    def test_an_unwritable_folder_is_not_an_error(self, tmp_path):
        """Seeding failing must not stop voice input; the bundled maps still work."""
        assert keys.seed_user_keymaps(str(tmp_path / "x"), str(tmp_path / "missing")) == []

    def test_reading_falls_back_to_the_shipped_maps(self, monkeypatch, tmp_path):
        """A fresh install works before anything has been seeded."""
        monkeypatch.setattr(keys, "user_keymap_dir", lambda: str(tmp_path / "empty"))
        monkeypatch.setattr(keys, "bundled_keymap_dir", lambda: REAL_MAPS)
        assert keys.keymap_dir() == REAL_MAPS

    def test_the_user_folder_wins_once_it_has_maps(self, monkeypatch, tmp_path):
        keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        monkeypatch.setattr(keys, "user_keymap_dir", lambda: str(tmp_path))
        monkeypatch.setattr(keys, "bundled_keymap_dir", lambda: REAL_MAPS)
        assert keys.keymap_dir() == str(tmp_path)


class TestShippedMapsCanWin:
    """Reading prefers the player's folder, so a corrected map shipped in an update
    would be silently ignored. That has to be both visible and fixable."""

    def test_a_local_edit_is_reported_as_differing(self, tmp_path):
        keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        assert keys.stale_user_keymaps(str(tmp_path), REAL_MAPS) == []

        (tmp_path / "A-10A.json").write_text('{"aircraft":"A-10A","commands":{}}',
                                             encoding="utf-8")
        assert keys.stale_user_keymaps(str(tmp_path), REAL_MAPS) == ["A-10A"]

    def test_refreshing_overwrites_local_edits(self, tmp_path):
        keys.seed_user_keymaps(str(tmp_path), REAL_MAPS)
        (tmp_path / "F-15C.json").write_text('{"aircraft":"F-15C","commands":{}}',
                                             encoding="utf-8")
        replaced = keys.refresh_user_keymaps(str(tmp_path), REAL_MAPS)
        assert "F-15C" in replaced
        assert keys.load_keymap("F-15C", str(tmp_path))["verified"] is True
        assert keys.stale_user_keymaps(str(tmp_path), REAL_MAPS) == []

    def test_a_map_the_player_does_not_have_is_not_called_stale(self, tmp_path):
        assert keys.stale_user_keymaps(str(tmp_path), REAL_MAPS) == []

    def test_an_unreadable_folder_is_not_an_error(self, tmp_path):
        missing = str(tmp_path / "nope")
        assert keys.stale_user_keymaps(missing, missing) == []
        assert keys.refresh_user_keymaps(str(tmp_path / "a"), missing) == []


class TestUnverifiedMapsCannotBePressed:
    """A map's sequences are guesswork until someone has walked the menu. Dry-running
    guesswork is how you verify it; pressing guesswork is how you trigger something you
    did not mean to."""

    def test_an_unverified_map_dry_runs(self, state):
        state["aircraft"] = "A-10A"
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS,
                                sending=False)
        assert resolved.ok, "dry running is how a map gets verified"
        assert resolved.verified is False

    def test_an_unverified_map_refuses_to_be_sent(self, state):
        state["aircraft"] = "A-10A"
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS,
                                sending=True)
        assert not resolved.ok
        assert "not been checked" in resolved.reason
        assert "A-10A" in resolved.reason

    def test_a_verified_map_sends(self, state):
        resolved = keys.resolve("awacs_picture", state, directory=REAL_MAPS,
                                sending=True)
        assert resolved.ok and resolved.verified is True

    def test_only_the_f15c_ships_verified(self):
        """Every other map is a copy of it and has not been flown. If one is marked
        verified without that happening, this is the test that should have stopped it."""
        verified = [a for a in keys.available_maps(REAL_MAPS)
                    if keys.load_keymap(a, REAL_MAPS).get("verified")]
        assert verified == ["F-15C"]

    def test_every_installed_module_has_a_map(self):
        """A missing map is not dangerous - it refuses by name - but these four are
        the modules that ship with DCS, so they are worth covering."""
        maps = set(keys.available_maps(REAL_MAPS))
        assert {"F-15C", "A-10A", "Su-25T", "TF-51D"} <= maps

    def test_the_copies_kept_the_f15c_commands(self):
        expected = set(keys.load_keymap("F-15C", REAL_MAPS)["commands"])
        for aircraft in ("A-10A", "Su-25T", "TF-51D"):
            assert set(keys.load_keymap(aircraft, REAL_MAPS)["commands"]) == expected

    def test_an_unverified_map_says_so_in_its_notes(self):
        for aircraft in ("A-10A", "Su-25T", "TF-51D"):
            notes = " ".join(keys.load_keymap(aircraft, REAL_MAPS)["verified_notes"])
            assert "UNVERIFIED" in notes
            assert "verified" in notes, "it must say how to verify it"


class TestPhrasesLiveInTheMaps:
    """Players customise what they say by editing the key map, not the source."""

    def test_phrases_are_collected_from_every_map(self):
        lookup, conflicts = keys.all_phrases(REAL_MAPS)
        assert conflicts == []
        assert lookup["two rejoin"] == "wingman2_rejoin"
        assert lookup["bogey dope"] == "awacs_bogey_dope"

    def test_phrases_are_lowercased_and_whitespace_normalised(self, tmp_path):
        (tmp_path / "X.json").write_text(json.dumps({
            "aircraft": "X",
            "commands": {"a": {"keys": ["F1"], "phrases": ["  Two   REJOIN  "]}},
        }), encoding="utf-8")
        lookup, _ = keys.all_phrases(str(tmp_path))
        assert lookup == {"two rejoin": "a"}

    def test_the_same_phrase_in_two_maps_is_fine_when_it_means_the_same_thing(
            self, tmp_path):
        """Every aircraft map will define "bogey dope" for awacs_bogey_dope."""
        for name in ("A", "B"):
            (tmp_path / ("%s.json" % name)).write_text(json.dumps({
                "aircraft": name,
                "commands": {"awacs_picture": {"keys": ["F1"],
                                               "phrases": ["say picture"]}},
            }), encoding="utf-8")
        lookup, conflicts = keys.all_phrases(str(tmp_path))
        assert conflicts == []
        assert lookup["say picture"] == "awacs_picture"

    def test_a_genuine_conflict_is_reported_not_silently_resolved(self, tmp_path):
        """Picking one at random would make a command work or not depending on which
        file happened to load first."""
        (tmp_path / "A.json").write_text(json.dumps({
            "aircraft": "A",
            "commands": {"one": {"keys": ["F1"], "phrases": ["go home"]}},
        }), encoding="utf-8")
        (tmp_path / "B.json").write_text(json.dumps({
            "aircraft": "B",
            "commands": {"two": {"keys": ["F2"], "phrases": ["go home"]}},
        }), encoding="utf-8")
        lookup, conflicts = keys.all_phrases(str(tmp_path))
        assert conflicts and conflicts[0][0] == "go home"
        assert lookup["go home"] == "one", "the first wins, and the clash is reported"

    def test_a_map_with_no_phrases_contributes_none(self, tmp_path):
        (tmp_path / "X.json").write_text(json.dumps({
            "aircraft": "X", "commands": {"a": {"keys": ["F1"]}},
        }), encoding="utf-8")
        assert keys.all_phrases(str(tmp_path)) == ({}, [])

    def test_an_atc_request_keeps_its_words_if_a_map_claims_them(self, monkeypatch):
        """ATC is the module's own function, so it wins - and the clash is logged
        rather than one of them quietly disappearing."""
        said = []
        monkeypatch.setattr(keys, "all_phrases",
                            lambda directory=None: ({"request taxi": "flight_rtb"}, []))
        lookup = listen.phrase_to_intent(on_log=said.append)
        assert lookup["request taxi"] == "taxi"
        assert said and "claimed by both" in said[0]


class TestPositionalWingmanKeys:
    """DCS numbers the per-wingman entries by position among the survivors, not by the
    aircraft's slot. Observed in the cockpit 2026-10-24: with two dead, three and four
    moved to F2 and F3. A fixed key addresses the wrong aircraft after any loss."""

    @staticmethod
    def _slots(*alive):
        return {"slot%d" % n: (1 if n in alive else 0) for n in (2, 3, 4)}

    def test_an_intact_flight_sits_where_you_would_expect(self):
        st = self._slots(2, 3, 4)
        assert keys.wingman_key(2, st) == "F2"
        assert keys.wingman_key(3, st) == "F3"
        assert keys.wingman_key(4, st) == "F4"

    def test_survivors_move_up_when_two_dies(self):
        """The observed case: this is the behaviour the whole mechanism exists for."""
        st = self._slots(3, 4)
        assert keys.wingman_key(2, st) is None
        assert keys.wingman_key(3, st) == "F2"
        assert keys.wingman_key(4, st) == "F3"

    def test_survivors_move_up_when_three_dies(self):
        st = self._slots(2, 4)
        assert keys.wingman_key(2, st) == "F2"
        assert keys.wingman_key(3, st) is None
        assert keys.wingman_key(4, st) == "F3"

    def test_a_lone_survivor_is_first(self):
        st = self._slots(4)
        assert keys.wingman_key(4, st) == "F2"

    def test_nobody_left_means_no_key(self):
        st = self._slots()
        assert all(keys.wingman_key(n, st) is None for n in (2, 3, 4))

    def test_absent_slot_fields_are_never_read_as_alive(self):
        """An older mission script publishing no slots must not have its silence taken
        for a full flight."""
        assert keys.wingman_key(2, {"aircraft": "F-15C", "wingmen": 3}) is None

    def test_resolution_uses_the_computed_key(self, state):
        state.update(wingmen=2, slot2=0, slot3=1, slot4=1)
        resolved = keys.resolve("wingman3_rejoin", state, directory=REAL_MAPS)
        assert resolved.ok
        assert resolved.display == ["comms", "F2", "F9"], \
            "three must be addressed where it now sits, not where it started"

        engage = keys.resolve("wingman3_engage", state, directory=REAL_MAPS)
        assert engage.display == ["comms", "F2", "F1", "F3"]

    def test_a_dead_slot_refuses_even_though_others_are_alive(self, state):
        state.update(wingmen=2, slot2=0, slot3=1, slot4=1)
        refused = keys.resolve("wingman2_rejoin", state, directory=REAL_MAPS)
        assert not refused.ok
        assert "two" in refused.reason

    def test_no_placeholder_ever_reaches_a_key_sequence(self, state):
        """A sequence containing "{wingman}" would be pressed literally, or crash the
        sender. Refusing is the only safe outcome."""
        for intent in sorted(keys.comms_intents(REAL_MAPS)):
            resolved = keys.resolve(intent, state, directory=REAL_MAPS)
            if resolved.ok:
                assert not any("{" in part for part in resolved.keys), intent

    def test_an_unresolvable_placeholder_is_refused_not_sent(self, tmp_path):
        (tmp_path / "X.json").write_text(json.dumps({
            "aircraft": "X",
            "commands": {"odd": {"keys": ["comms", "{mystery}"], "phrases": ["odd"]}},
        }), encoding="utf-8")
        resolved = keys.resolve("odd", {"aircraft": "X"}, directory=str(tmp_path))
        assert not resolved.ok
        assert "placeholder" in resolved.reason

    def test_flight_commands_still_use_the_count(self, state):
        state.update(wingmen=2, slot2=0, slot3=1, slot4=1)
        assert keys.resolve("flight_rejoin", state, directory=REAL_MAPS).ok

        state.update(wingmen=0, slot2=0, slot3=0, slot4=0)
        assert not keys.resolve("flight_rejoin", state, directory=REAL_MAPS).ok

    def test_a_state_without_slots_refuses_a_wingman_command(self):
        """An older mission script that publishes no slots must not have its silence
        read as "all present"."""
        state = keys.parse_state("ATCAI_STATE|aircraft=F-15C|wingmen=3")
        assert not keys.resolve("wingman2_rejoin", state, directory=REAL_MAPS).ok


class TestStateSummary:
    def test_the_log_line_names_which_slots_are_alive(self, tmp_path):
        """The slots decide every per-wingman refusal, so a summary that showed only
        the count hid the deciding fact - which is how the last test round came to be
        unreadable."""
        import time
        log = tmp_path / "dcs.log"
        log.write_text("", encoding="utf-8")

        said = []
        watcher = listen.StateWatcher(str(log), on_log=said.append)
        watcher.start()
        time.sleep(0.3)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("INFO SCRIPTING: ATCAI_STATE|aircraft=F-15C|wingmen=2"
                         "|onGround=0|awacs=1|tanker=0|slot2=0|slot3=1|slot4=1\n")
        time.sleep(0.6)
        watcher.stop()

        assert said, "nothing was logged"
        line = said[-1]
        assert "slots 3,4" in line, line
        assert "2 wingmen" in line
        assert "awacs=1" in line

    def test_a_flight_with_nothing_left_says_so(self, tmp_path):
        import time
        log = tmp_path / "dcs.log"
        log.write_text("", encoding="utf-8")
        said = []
        watcher = listen.StateWatcher(str(log), on_log=said.append)
        watcher.start()
        time.sleep(0.3)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("INFO SCRIPTING: ATCAI_STATE|aircraft=F-15C|wingmen=0"
                         "|slot2=0|slot3=0|slot4=0\n")
        time.sleep(0.6)
        watcher.stop()
        assert "slots none" in said[-1]


class TestVoiceRouting:
    @pytest.mark.parametrize("spoken,expected", [
        ("two rejoin", "wingman2_rejoin"),
        ("three engage bandits", "wingman3_engage"),
        ("four rejoin", "wingman4_rejoin"),
        ("flight rejoin", "flight_rejoin"),
        ("flight engage bandits", "flight_engage"),
        ("flight return to base", "flight_rtb"),
        ("awacs picture", "awacs_picture"),
        ("request bogey dope", "awacs_bogey_dope"),
    ])
    def test_the_phrases_are_recognised(self, spoken, expected):
        assert listen.match_intent(spoken, listen.phrase_to_intent()) == expected

    def test_comms_intents_are_told_apart_from_atc_requests(self):
        assert listen.is_comms_intent("wingman2_rejoin")
        assert listen.is_comms_intent("awacs_picture")
        assert not listen.is_comms_intent("taxi")
        assert not listen.is_comms_intent("emergency")
        assert not listen.is_comms_intent(None)

    def test_comms_intents_come_from_the_maps_not_the_source(self):
        """Phrases are the player's to customise, so they live in the key map. Nothing
        in INTENT_PHRASES may claim a comms intent any more."""
        mapped = keys.comms_intents(REAL_MAPS)
        assert "wingman2_rejoin" in mapped and "awacs_picture" in mapped
        for intent in listen.INTENT_PHRASES:
            assert intent not in mapped, \
                "%s is hardcoded as well as mapped" % intent

    def test_comms_intents_never_reach_the_mission_inbox(self):
        """Nothing in the mission can act on them, so routing one there would be a
        command heard and then lost."""
        import re
        source = (ROOT / "lua" / "atc" / "atc_inbox.lua").read_text(encoding="utf-8")
        block = re.search(r"local INTENT_HANDLERS = \{(.*?)\}", source, re.S).group(1)
        handled = set(re.findall(r"(\w+)\s*=\s*\"", block))
        for intent in listen.INTENT_PHRASES:
            if listen.is_comms_intent(intent):
                assert intent not in handled
