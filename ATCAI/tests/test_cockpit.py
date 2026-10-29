"""Working cockpit controls by voice.

Two things carry the weight here and get the most tests: the deny list, because a wrong
cockpit press can be unrecoverable in a way a wrong menu press is not, and the state
conditions, because retracting the gear on the ground is the obvious self-inflicted
injury.
"""

import json
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "voice-bridge"))

import atcai_bindings as bindings_mod  # noqa: E402
import atcai_cockpit as cockpit  # noqa: E402
import atcai_keys as keys  # noqa: E402

REAL = str(ROOT / "voice-bridge" / "cockpit")
BINDINGS = {"Landing Gear Up": ["LCtrl+G"], "Landing Gear Down": ["LShift+G"]}


@pytest.fixture
def airborne():
    return keys.parse_state("ATCAI_STATE|aircraft=F-15C|wingmen=0|onGround=0")


@pytest.fixture
def grounded():
    return keys.parse_state("ATCAI_STATE|aircraft=F-15C|wingmen=0|onGround=1")


class TestTheDenyList:
    """Refused in code, not merely absent from the shipped map - because the map is
    editable, so "out" has to mean out."""

    @pytest.mark.parametrize("control", [
        "Eject", "EJECT", "Eject (3 times)",
        "Jettison Fuel Tanks", "Jettison All Stores",
        "Engine Start", "Engine Stop", "Left Engine Shutdown",
        "Master Arm", "Master Arm On/Off",
        "Weapon Release", "Release Weapon",
        "Countermeasures Dispense", "Chaff Dispense", "Flare Dispense",
        "Canopy Jettison", "Salvo",
        "Fuel Dump",
    ])
    def test_destructive_controls_are_denied(self, control):
        assert cockpit.is_denied(control) is True

    @pytest.mark.parametrize("control", [
        "Landing Gear Up", "Landing Gear Down", "Flaps Up/Down",
        "Canopy Open/Close", "Air Brake On", "Navigation Lights",
        "Wheel Brake Left On/Off",
    ])
    def test_reversible_controls_are_allowed(self, control):
        assert cockpit.is_denied(control) is False

    def test_a_map_cannot_add_a_denied_control_back(self, tmp_path):
        """The whole point of enforcing it in code: someone editing the file, or a
        downloaded file, must not be able to make this possible."""
        (tmp_path / "controls.json").write_text(json.dumps({
            "controls": {"cockpit_eject": {"control": "Eject",
                                           "phrases": ["eject eject eject"]}}}),
            encoding="utf-8")
        resolved = cockpit.resolve("cockpit_eject",
                                   {"aircraft": "F-15C", "onGround": 0},
                                   {"Eject": ["LCtrl+E"]}, directory=str(tmp_path))
        assert not resolved.ok
        assert "deliberately excluded" in resolved.reason

    def test_the_deny_check_happens_before_anything_else(self, tmp_path):
        """Not after the conditions or the binding lookup - a denied control must be
        refused even when everything else about the request is wrong too."""
        (tmp_path / "controls.json").write_text(json.dumps({
            "controls": {"cockpit_eject": {"control": "Eject",
                                           "requires": ["onGround==99"],
                                           "phrases": ["x"]}}}),
            encoding="utf-8")
        resolved = cockpit.resolve("cockpit_eject", None, {}, directory=str(tmp_path))
        assert "deliberately excluded" in resolved.reason

    def test_the_shipped_map_names_nothing_denied(self):
        for intent, entry in cockpit.load_controls(REAL).items():
            assert not cockpit.is_denied(entry["control"]), intent


class TestResolution:
    def test_it_resolves_to_the_chord_dcs_gave(self, airborne):
        resolved = cockpit.resolve("cockpit_gear_up", airborne, BINDINGS,
                                   directory=REAL)
        assert resolved.ok
        assert resolved.keys == ["LCtrl+G"]
        assert resolved.control == "Landing Gear Up"

    def test_gear_up_is_refused_on_the_ground(self, grounded):
        resolved = cockpit.resolve("cockpit_gear_up", grounded, BINDINGS,
                                   directory=REAL)
        assert not resolved.ok
        assert "on the ground" in resolved.reason

    def test_gear_down_is_allowed_on_the_ground(self, grounded):
        """Lowering gear you already have down is harmless; refusing it would be
        surprising."""
        assert cockpit.resolve("cockpit_gear_down", grounded, BINDINGS,
                               directory=REAL).ok

    def test_an_absent_state_field_refuses_rather_than_assumes(self):
        """A mission script that publishes no onGround must not have its silence read
        as airborne."""
        resolved = cockpit.resolve("cockpit_gear_up", {"aircraft": "F-15C"}, BINDINGS,
                                   directory=REAL)
        assert not resolved.ok

    def test_it_refuses_before_any_state_arrives(self, ):
        resolved = cockpit.resolve("cockpit_gear_up", None, BINDINGS, directory=REAL)
        assert not resolved.ok and "state" in resolved.reason

    def test_it_refuses_when_the_aircraft_has_no_such_binding(self, airborne):
        """A TF-51D has no air brake; the control simply is not in its bindings."""
        resolved = cockpit.resolve("cockpit_gear_up", airborne, {}, directory=REAL)
        assert not resolved.ok
        assert "no Landing Gear Up binding" in resolved.reason

    def test_it_refuses_while_disabled(self, airborne):
        resolved = cockpit.resolve("cockpit_gear_up", airborne, BINDINGS,
                                   enabled=False, directory=REAL)
        assert not resolved.ok and "turned off" in resolved.reason

    def test_an_unknown_intent_is_refused(self, airborne):
        assert not cockpit.resolve("cockpit_nonsense", airborne, BINDINGS,
                                   directory=REAL).ok

    def test_every_refusal_carries_a_reason(self, grounded):
        for intent, state, binds in (("cockpit_gear_up", grounded, BINDINGS),
                                     ("cockpit_gear_up", None, BINDINGS),
                                     ("cockpit_gear_up", grounded, {}),
                                     ("nope", grounded, BINDINGS)):
            resolved = cockpit.resolve(intent, state, binds, directory=REAL)
            assert not resolved.ok
            assert resolved.reason and len(resolved.reason) > 5


class TestThePhrases:
    def test_the_shipped_phrases_load(self):
        lookup, conflicts = cockpit.all_phrases(REAL)
        assert conflicts == []
        assert lookup["gear up"] == "cockpit_gear_up"
        assert lookup["gear down"] == "cockpit_gear_down"

    def test_up_and_down_never_share_a_phrase(self):
        """The one confusion that must be impossible by construction, not just
        unlikely in the recogniser."""
        lookup, _ = cockpit.all_phrases(REAL)
        ups = {p for p, i in lookup.items() if i == "cockpit_gear_up"}
        downs = {p for p, i in lookup.items() if i == "cockpit_gear_down"}
        assert ups and downs
        assert ups.isdisjoint(downs)

    def test_a_conflict_is_reported_not_silently_resolved(self, tmp_path):
        (tmp_path / "controls.json").write_text(json.dumps({"controls": {
            "a": {"control": "Landing Gear Up", "phrases": ["gear"]},
            "b": {"control": "Landing Gear Down", "phrases": ["gear"]},
        }}), encoding="utf-8")
        lookup, conflicts = cockpit.all_phrases(str(tmp_path))
        assert conflicts and conflicts[0][0] == "gear"

    def test_a_broken_file_reads_as_empty_rather_than_raising(self, tmp_path):
        (tmp_path / "controls.json").write_text("{not json", encoding="utf-8")
        assert cockpit.load_controls(str(tmp_path)) == {}
        assert cockpit.all_phrases(str(tmp_path)) == ({}, [])

    def test_an_entry_without_a_control_is_ignored(self, tmp_path):
        (tmp_path / "controls.json").write_text(json.dumps({"controls": {
            "a": {"phrases": ["x"]}}}), encoding="utf-8")
        assert cockpit.load_controls(str(tmp_path)) == {}


class TestEditability:
    def test_seeding_copies_the_shipped_file(self, tmp_path):
        assert cockpit.seed_user_controls(str(tmp_path), REAL) == ["controls.json"]
        assert cockpit.load_controls(str(tmp_path))

    def test_an_edited_file_is_never_overwritten_by_seeding(self, tmp_path):
        cockpit.seed_user_controls(str(tmp_path), REAL)
        (tmp_path / "controls.json").write_text(json.dumps({"controls": {
            "cockpit_gear_up": {"control": "Landing Gear Up",
                                "phrases": ["my own words"]}}}), encoding="utf-8")
        cockpit.seed_user_controls(str(tmp_path), REAL)
        lookup, _ = cockpit.all_phrases(str(tmp_path))
        assert "my own words" in lookup

    def test_refreshing_restores_the_shipped_file(self, tmp_path):
        cockpit.seed_user_controls(str(tmp_path), REAL)
        (tmp_path / "controls.json").write_text('{"controls":{}}', encoding="utf-8")
        assert cockpit.refresh_user_controls(str(tmp_path), REAL) == ["controls.json"]
        assert cockpit.load_controls(str(tmp_path))

    def test_the_user_folder_is_not_the_bundled_one(self):
        assert cockpit.user_dir() != cockpit.bundled_dir()


class TestKeyboardDefaultsAreResolved:
    """readbindings.lua used to stub out DCS's default-assignment table.

    The belief was that it lived in DCS's internals and could not be read. It does not:
    Scripts/Input/DefaultAssignments.lua loads standalone and returns a plain table
    keyed by device. Stubbing it marked 29 F-15C controls as having no key - including
    "Flaps Up" (LCtrl+F) and "Flaps Landing Position" (LShift+F), which are bound by
    default and work in the game. ATCAI reported them as unbound, and the player was
    told their flaps could not be driven directionally when they always could.

    Needs a real DCS install, so it skips where there isn't one. Checked by running the
    reader itself rather than re-implementing it, because the bug was in the reader.
    """

    GAME = ROOT_DCS = None

    @staticmethod
    def _install():
        """The DCS game folder, or None. dcs_lua() finds bin/luae.exe inside it."""
        from conftest import dcs_lua
        exe = dcs_lua()
        return exe.parent.parent if exe else None

    @pytest.fixture
    def resolved(self):
        import os
        import subprocess
        import atcai_listen
        install = self._install()
        if not install:
            pytest.skip("DCS's Lua interpreter not found; set DCS_BIN")
        table = install / "Scripts" / "Input" / "DefaultAssignments.lua"
        if not table.is_file():
            pytest.skip("this DCS install has no DefaultAssignments.lua")

        luae, profile, diff = bindings_mod.paths_for("F-15C", str(install), None)
        if not profile:
            pytest.skip("the F-15C module is not installed")

        command = [luae, atcai_listen.windows_path(bindings_mod._script()),
                   atcai_listen.windows_path(str(install)).replace("\\", "/"),
                   atcai_listen.windows_path(profile)]
        result = subprocess.run(command, capture_output=True, timeout=120,
                                cwd=os.path.dirname(luae))
        return result.stdout.decode("cp1252", errors="replace")

    def test_the_flap_commands_resolve_to_their_real_keys(self, resolved):
        assert "BINDING|Flaps Up|LCtrl|F" in resolved
        assert "BINDING|Flaps Landing Position|LShift|F" in resolved

    def test_they_are_no_longer_reported_as_keyless(self, resolved):
        unresolved = [line.split("|", 1)[1] for line in resolved.splitlines()
                      if line.startswith("UNRESOLVED|")]
        assert "Flaps Up" not in unresolved
        assert "Flaps Landing Position" not in unresolved

    def test_a_joystick_default_is_still_not_faked(self, resolved):
        """Only the Keyboard device is read. A stick axis is not a key ATCAI can press,
        so it must stay unresolved rather than be turned into a plausible-looking key."""
        for line in resolved.splitlines():
            if line.startswith("BINDING|"):
                _, _, _, key = line.split("|", 3)
                assert not key.startswith("JOY_"), line

    def test_the_commands_the_deny_list_covers_are_still_refused(self, resolved):
        """Making a control readable must not make it reachable. Eject, weapon release
        and countermeasures are in that default table too."""
        for name in ("Eject (3 times)", "Weapon Release", "Countermeasures Release"):
            assert cockpit.is_denied(name), name


class TestBindingParsing:
    def test_it_reads_a_binding_line(self):
        assert bindings_mod.parse_line("BINDING|Landing Gear Up|LCtrl|G") == (
            "BINDING", ("Landing Gear Up", ["LCtrl"], "G"))

    def test_a_binding_with_no_modifier(self):
        assert bindings_mod.parse_line("BINDING|Flaps Up/Down||F") == (
            "BINDING", ("Flaps Up/Down", [], "F"))

    def test_several_modifiers(self):
        kind, payload = bindings_mod.parse_line("BINDING|Something|LCtrl+LShift|C")
        assert payload[1] == ["LCtrl", "LShift"]

    def test_unresolved_and_done_and_error(self):
        assert bindings_mod.parse_line("UNRESOLVED|Landing Gear Up/Down") == (
            "UNRESOLVED", "Landing Gear Up/Down")
        assert bindings_mod.parse_line("DONE|293") == ("DONE", 293)
        assert bindings_mod.parse_line("ERROR|nope") == ("ERROR", "nope")

    @pytest.mark.parametrize("line", ["", "no pipes", "BINDING|only|two",
                                      "BINDING||LCtrl|G", "BINDING|Name|LCtrl|"])
    def test_malformed_lines_are_ignored(self, line):
        assert bindings_mod.parse_line(line) is None

    def test_chords_are_built_in_the_spelling_the_sender_accepts(self):
        assert bindings_mod.chord_for(["LCtrl"], "G") == "LCtrl+G"
        assert bindings_mod.chord_for([], "F") == "F"

    def test_a_chord_it_builds_is_sendable(self):
        """The two halves must agree: a chord read from DCS has to be one the sender
        can actually press."""
        import atcai_sendkeys
        chord = bindings_mod.chord_for(["LCtrl"], "G")
        assert atcai_sendkeys.unknown_keys([chord]) == []


class TestTheCache:
    def test_it_reads_once_per_aircraft(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bindings_mod, "read",
                            lambda aircraft, install, writedir=None, on_log=None:
                            (calls.append(aircraft) or ({"X": ["G"]}, [])))
        cache = bindings_mod.Cache("install")
        cache.get("F-15C")
        cache.get("F-15C")
        assert calls == ["F-15C"], "bindings do not change mid-flight"

    def test_forgetting_makes_it_read_again(self, monkeypatch):
        """The manager's re-read button, for after rebinding in DCS's own options."""
        calls = []
        monkeypatch.setattr(bindings_mod, "read",
                            lambda aircraft, install, writedir=None, on_log=None:
                            (calls.append(aircraft) or ({"X": ["G"]}, [])))
        cache = bindings_mod.Cache("install")
        cache.get("F-15C")
        cache.forget()
        cache.get("F-15C")
        assert calls == ["F-15C", "F-15C"]

    def test_no_aircraft_reads_nothing(self):
        assert bindings_mod.Cache("install").get(None) == {}


class TestMissingShippedControls:
    """Seeding only ever adds a file, never merges into one that exists. A player whose
    copy was made when the list held two controls keeps two for ever - which hid flaps,
    airbrake, canopy and lights from a tester, with no symptom but a command that did
    nothing."""

    def _write(self, path, intents):
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"controls": {
            i: {"control": i, "phrases": [i.replace("_", " ")]} for i in intents}}),
            encoding="utf-8")

    def test_it_names_what_the_players_copy_is_missing(self, tmp_path):
        theirs, ours = tmp_path / "theirs", tmp_path / "ours"
        self._write(theirs / "controls.json", ["cockpit_gear_up", "cockpit_gear_down"])
        self._write(ours / "controls.json", ["cockpit_gear_up", "cockpit_gear_down",
                                             "cockpit_flaps", "cockpit_canopy"])
        assert cockpit.missing_user_controls(str(theirs), str(ours)) == [
            "cockpit_canopy", "cockpit_flaps"]

    def test_an_up_to_date_copy_reports_nothing(self, tmp_path):
        theirs, ours = tmp_path / "theirs", tmp_path / "ours"
        self._write(theirs / "controls.json", ["cockpit_gear_up"])
        self._write(ours / "controls.json", ["cockpit_gear_up"])
        assert cockpit.missing_user_controls(str(theirs), str(ours)) == []

    def test_a_control_they_added_themselves_is_not_a_problem(self, tmp_path):
        """Their file is theirs; extras are not drift."""
        theirs, ours = tmp_path / "theirs", tmp_path / "ours"
        self._write(theirs / "controls.json", ["cockpit_gear_up", "cockpit_mine"])
        self._write(ours / "controls.json", ["cockpit_gear_up"])
        assert cockpit.missing_user_controls(str(theirs), str(ours)) == []

    def test_nothing_seeded_yet_is_not_a_problem(self, tmp_path):
        """A fresh install reads the shipped list directly, so there is no drift to
        report - and reporting one would be the first thing a new user saw."""
        ours = tmp_path / "ours"
        self._write(ours / "controls.json", ["cockpit_gear_up"])
        assert cockpit.missing_user_controls(str(tmp_path / "nothing"), str(ours)) == []

    def test_the_shipped_list_really_has_all_eight(self):
        """The count the warning is measured against, asserted so it cannot quietly
        shrink."""
        shipped = cockpit.load_controls(cockpit.bundled_dir())
        assert len(shipped) == 8, sorted(shipped)


class TestFlapsAreDirectional:
    """The flap toggle was replaced by two directional commands.

    A toggle's result depends on current flap position, which DCS does not publish - so
    "flaps up" driving a toggle would *lower* flaps that were already up, which is both
    the opposite of the request and the exact moment someone would say it. Two commands
    that name a direction cannot do that.
    """

    def test_there_is_no_toggle_left(self):
        shipped = cockpit.load_controls(cockpit.bundled_dir())
        assert "cockpit_flaps" not in shipped
        controls = {e.get("control") for e in shipped.values()}
        assert "Flaps Up/Down" not in controls, (
            "the toggle is back; a directional phrase on it can do the opposite")

    def test_both_directions_exist_and_name_dcs_controls(self):
        shipped = cockpit.load_controls(cockpit.bundled_dir())
        assert shipped["cockpit_flaps_up"]["control"] == "Flaps Up"
        assert shipped["cockpit_flaps_down"]["control"] == "Flaps Landing Position"

    def test_no_phrase_implies_a_direction_the_command_cannot_deliver(self):
        """Every flap phrase must belong to a command that moves flaps one way only."""
        shipped = cockpit.load_controls(cockpit.bundled_dir())
        for intent, entry in shipped.items():
            if "flap" not in intent:
                continue
            assert entry["control"] in ("Flaps Up", "Flaps Landing Position"), entry
            for phrase in entry["phrases"]:
                assert "toggle" not in phrase, phrase

    def test_the_bare_one_word_phrase_is_gone(self):
        """It false-fired on game audio over desktop speakers and pressed F in flight -
        the only false trigger measured that reached an aircraft control."""
        shipped = cockpit.load_controls(cockpit.bundled_dir())
        every = [p for e in shipped.values() for p in e["phrases"]]
        assert "flaps" not in every
        assert "flaps now" not in every
