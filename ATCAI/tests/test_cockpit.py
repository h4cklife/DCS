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
