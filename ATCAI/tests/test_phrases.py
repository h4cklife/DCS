"""The shipped phrase list, the player's changes to it, and checking a typed phrase.

Two things are being protected here. One is that moving the ATC phrases out of Python
into JSON changed nothing. The other is that the overlay stays a *difference* rather than
a copy - the property that lets a release ship a corrected phrase to someone who has
already customised their own.
"""

import json
import re

import pytest

import atcai_listen as listen
import atcai_phrases as phrases
from conftest import ROOT


class TestShippedDefaults:
    def test_the_json_is_the_phrase_list(self):
        """INTENT_PHRASES is now read from the file, so they cannot drift apart."""
        assert listen.INTENT_PHRASES == phrases.load_defaults()
        assert listen.INTENT_PHRASES, "no ATC phrases loaded at all"

    def test_every_dispatched_intent_has_phrases(self):
        """Cross-file check against the Lua that actually handles the requests.

        A command the mission can run but nobody can say is invisible; a phrase for a
        command the mission does not handle is a silent no-op. Either is easy to create
        by editing one file and not the other, and neither shows up until you fly.
        """
        source = (ROOT / "lua" / "atc" / "atc_inbox.lua").read_text(encoding="utf-8")
        block = re.search(r"local INTENT_HANDLERS = \{(.*?)\n\}", source, re.S)
        assert block, "could not find INTENT_HANDLERS in atc_inbox.lua"
        dispatched = set(re.findall(r"^\s*(\w+)\s*=", block.group(1), re.M))

        assert dispatched, "parsed no intents out of the Lua"
        assert set(phrases.load_defaults()) == dispatched

    def test_the_defaults_are_read_only(self, tmp_path, monkeypatch):
        """It is reference, not a template. If anything ever copies it into the player's
        folder, the staleness problem this whole design exists to avoid comes back: their
        edit and last release's default become the same bytes in the same place.

        Checked by behaviour rather than by name - point the overlay at an empty folder,
        read and write through the module, and the defaults file must be untouched and
        nothing may appear beside it.
        """
        source = ROOT / "voice-bridge" / "phrases" / "atc_defaults.json"
        before = source.read_bytes()
        listing_before = sorted(p.name for p in source.parent.iterdir())

        monkeypatch.setattr(phrases, "overlay_dir", lambda: str(tmp_path))
        monkeypatch.setattr(phrases, "overlay_path",
                            lambda: str(tmp_path / "phrases.json"))
        phrases.load_defaults()
        phrases.load_overlay()
        phrases.save_overlay({"taxi": {"remove": ["ready to taxi"]}})

        assert source.read_bytes() == before, "the shipped defaults were modified"
        assert sorted(p.name for p in source.parent.iterdir()) == listing_before
        # The change went to the player's folder instead.
        assert (tmp_path / "phrases.json").exists()

    def test_it_parses_as_json_with_the_expected_shape(self):
        doc = json.loads((ROOT / "voice-bridge" / "phrases" / "atc_defaults.json")
                         .read_text(encoding="utf-8"))
        assert doc["version"] == phrases.VERSION
        assert isinstance(doc["commands"], dict)
        for intent, entry in doc["commands"].items():
            assert entry["phrases"], "%s has no phrases" % intent

    def test_a_missing_or_broken_file_is_not_fatal(self, tmp_path):
        assert phrases.load_defaults(str(tmp_path / "nope.json")) == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert phrases.load_defaults(str(bad)) == {}


class TestOverlayFile:
    def test_absent_overlay_means_no_changes(self, tmp_path):
        overlay, problems = phrases.load_overlay(str(tmp_path / "phrases.json"))
        assert overlay == {} and problems == []

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "phrases.json")
        phrases.save_overlay({"taxi": {"add": ["ready to roll"],
                                       "remove": ["ready to taxi"]},
                              "emergency": {"enabled": False}}, path)
        overlay, problems = phrases.load_overlay(path)
        assert problems == []
        assert overlay["taxi"]["add"] == ["ready to roll"]
        assert overlay["taxi"]["remove"] == ["ready to taxi"]
        assert overlay["emergency"]["enabled"] is False

    def test_an_entry_that_says_nothing_is_not_written(self, tmp_path):
        """"Restore defaults" is a deletion, so an empty entry must leave no trace -
        otherwise the file slowly fills with commands nobody changed."""
        path = str(tmp_path / "phrases.json")
        phrases.save_overlay({"taxi": {"enabled": True, "add": [], "remove": []}}, path)
        doc = json.loads(open(path, encoding="utf-8").read())
        assert doc["commands"] == {}

    def test_phrases_are_normalised_on_the_way_in_and_out(self, tmp_path):
        path = str(tmp_path / "phrases.json")
        phrases.save_overlay({"taxi": {"add": ["  Ready   To ROLL "]}}, path)
        overlay, _ = phrases.load_overlay(path)
        assert overlay["taxi"]["add"] == ["ready to roll"]

    @pytest.mark.parametrize("content", [
        "{not json at all",
        "[]",
        '{"commands": "nonsense"}',
    ])
    def test_a_malformed_overlay_falls_back_rather_than_failing(self, tmp_path, content):
        """A trailing comma in a hand-edited file must not stop voice control working."""
        path = tmp_path / "phrases.json"
        path.write_text(content, encoding="utf-8")
        overlay, problems = phrases.load_overlay(str(path))
        assert overlay == {}
        assert problems, "a broken file should say so"

    def test_rubbish_inside_a_good_file_is_dropped_per_entry(self, tmp_path):
        path = tmp_path / "phrases.json"
        path.write_text(json.dumps({"version": 1, "commands": {
            "taxi": {"add": ["ready to roll"]},
            "atis": "not an object",
            "landing": {"enabled": "yes please"},
            "startup": {"remove": "not a list"},
        }}), encoding="utf-8")
        overlay, problems = phrases.load_overlay(str(path))
        assert overlay["taxi"]["add"] == ["ready to roll"]
        assert "atis" not in overlay
        assert "enabled" not in overlay.get("landing", {})
        assert "remove" not in overlay.get("startup", {})
        assert len(problems) == 3

    def test_an_unknown_version_is_reported_but_still_read(self, tmp_path):
        path = tmp_path / "phrases.json"
        path.write_text(json.dumps({"version": 99, "commands": {
            "taxi": {"add": ["ready to roll"]}}}), encoding="utf-8")
        overlay, problems = phrases.load_overlay(str(path))
        assert overlay["taxi"]["add"] == ["ready to roll"]
        assert any("version" in p for p in problems)


class TestApplyingTheOverlay:
    PAIRS = [("request taxi", "taxi"), ("ready to taxi", "taxi"),
             ("request landing", "landing")]

    def test_nothing_changes_without_an_overlay(self):
        assert phrases.apply_overlay(self.PAIRS, {}) == [
            (p, i) for p, i in self.PAIRS]

    def test_removing_one_phrase_keeps_its_siblings(self):
        out = dict((p, i) for p, i in
                   phrases.apply_overlay(self.PAIRS, {"taxi": {"remove": ["ready to taxi"]}}))
        assert "ready to taxi" not in out
        assert out["request taxi"] == "taxi"

    def test_disabling_drops_every_phrase_of_the_command(self):
        out = phrases.apply_overlay(self.PAIRS, {"taxi": {"enabled": False}})
        assert [i for _, i in out] == ["landing"]

    def test_adding_a_phrase(self):
        out = dict(phrases.apply_overlay(self.PAIRS, {"taxi": {"add": ["ready to roll"]}}))
        assert out["ready to roll"] == "taxi"

    def test_an_addition_to_a_disabled_command_is_not_resurrected(self):
        out = phrases.apply_overlay(
            self.PAIRS, {"taxi": {"enabled": False, "add": ["ready to roll"]}})
        assert [i for _, i in out] == ["landing"]

    def test_the_overlay_cannot_invent_a_command(self):
        """The property that keeps phrase editing away from the controls
        atcai_cockpit.DENY_PATTERNS refuses: there is no command there to re-word."""
        out = phrases.apply_overlay(self.PAIRS, {"cockpit_eject": {"add": ["bail out"]}})
        assert "bail out" not in dict(out)
        assert len(out) == len(self.PAIRS)

    def test_additions_are_not_duplicated(self):
        out = phrases.apply_overlay(self.PAIRS, {"taxi": {"add": ["request taxi"]}})
        assert len(out) == len(self.PAIRS)

    def test_effective_omits_a_disabled_command_entirely(self):
        """Absent, not empty - so a caller cannot read "disabled" as "lost its phrases"."""
        force = phrases.effective({"taxi": ["request taxi"], "landing": ["on final"]},
                                  {"taxi": {"enabled": False}})
        assert "taxi" not in force
        assert force["landing"] == ["on final"]


class TestTheGrammarHonoursIt:
    """The part that matters: a disabled phrase is not in the recogniser's grammar at
    all, rather than recognised and then discarded."""

    def test_a_disabled_command_leaves_the_grammar(self):
        lookup = listen.phrase_to_intent(overlay={"emergency": {"enabled": False}})
        assert not any(intent == "emergency" for intent in lookup.values())
        assert "mayday mayday mayday" not in lookup

    def test_a_removed_phrase_takes_its_verb_variants_with_it(self):
        """Filtering happens before expansion, so one switch covers both forms."""
        lookup = listen.phrase_to_intent(overlay={"taxi": {"remove": ["request taxi"]}})
        assert "request taxi" not in lookup
        assert "requesting taxi" not in lookup
        assert lookup.get("ready to taxi") == "taxi"

    def test_an_added_phrase_is_expanded_like_a_shipped_one(self):
        lookup = listen.phrase_to_intent(overlay={"taxi": {"add": ["request rolling"]}})
        assert lookup.get("request rolling") == "taxi"
        assert lookup.get("requesting rolling") == "taxi"

    def test_a_comms_phrase_can_be_changed_too(self):
        """Keyed by intent, not by file - one comms phrase can live in four key maps."""
        import atcai_keys
        comms = atcai_keys.comms_intents()
        if not comms:
            pytest.skip("no key maps available")
        intent = sorted(comms)[0]
        lookup = listen.phrase_to_intent(overlay={intent: {"enabled": False}})
        assert not any(i == intent for i in lookup.values())


class TestCheckingATypedPhrase:
    FORCE = {"taxi": ["request taxi", "ready to taxi"],
             "landing": ["request landing clearance"],
             "cockpit_gear_up": ["landing gear up"]}

    def _check(self, phrase, intent="taxi"):
        return phrases.check_phrase(phrase, intent, self.FORCE,
                                    variants=listen.expand_phrases)

    @pytest.mark.parametrize("phrase", ["", "   "])
    def test_empty_is_refused(self, phrase):
        assert self._check(phrase).level == "refuse"

    @pytest.mark.parametrize("phrase", [
        "request taxi, please", "say \"again\"", "gear-up", "100%", "request taxi!",
    ])
    def test_punctuation_is_refused(self, phrase):
        """SAPI either ignores it or fails to build the grammar, silently either way."""
        assert self._check(phrase).level == "refuse"

    def test_a_phrase_belonging_to_another_command_is_refused_by_name(self):
        result = self._check("landing gear up")
        assert result.level == "refuse"
        assert "cockpit_gear_up" in result.message

    def test_a_phrase_this_command_already_has_is_a_duplicate(self):
        result = self._check("request taxi")
        assert result.level == "duplicate"
        assert result.duplicate_of == "taxi"

    def test_a_verb_variant_of_an_existing_phrase_is_a_duplicate(self):
        """expand_phrases already generates it, so adding it by hand is a no-op."""
        result = self._check("requesting taxi")
        assert result.level == "duplicate"

    def test_a_verb_variant_colliding_with_another_command_is_refused(self):
        result = self._check("requesting landing clearance")
        assert result.level == "refuse"
        assert "landing" in result.message

    @pytest.mark.parametrize("phrase", ["flaps", "canopy", "go"])
    def test_a_very_short_phrase_warns_but_is_allowed(self, phrase):
        result = self._check(phrase)
        assert result.ok and result.level == "warn"
        assert "short" in result.message.lower()

    def test_the_short_warning_says_why(self):
        """The player is allowed to make this trade - just not by accident."""
        assert "false emergency" in self._check("flaps").message

    def test_a_phrase_containing_an_existing_one_warns(self):
        result = self._check("request taxi to the ramp")
        assert result.ok and result.level == "warn"
        assert "request taxi" in result.message

    def test_a_phrase_contained_in_an_existing_one_warns(self):
        result = self._check("request landing", intent="landing")
        assert result.ok and result.level == "warn"
        assert "may not be reachable" in result.message

    def test_a_good_phrase_passes_cleanly(self):
        result = self._check("ready to roll out")
        assert result.ok and result.level == "ok" and result.message == ""
