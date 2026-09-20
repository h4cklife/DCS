"""The manager's own remembered settings."""

import json

import pytest

import prefs


def test_defaults_when_nothing_saved(tmp_path):
    assert prefs.load(tmp_path / "absent.json") == prefs.DEFAULTS


@pytest.mark.parametrize("key,value", [
    ("tts_mode", "srs"),
    ("min_confidence", 0.8),
    ("strict", True),
    ("auto_start_voice", True),
    ("auto_start_replies", True),
    ("dcs_path", "C:/Games/DCS"),
])
def test_settings_round_trip(tmp_path, key, value):
    store = tmp_path / "manager.json"
    prefs.save({key: value}, store)
    assert prefs.load(store)[key] == value


def test_unsaved_settings_keep_their_defaults(tmp_path):
    store = tmp_path / "manager.json"
    prefs.save({"tts_mode": "srs"}, store)
    assert prefs.load(store)["auto_start_replies"] is False


class TestBadInput:
    """A hand-edited or corrupted file must never stop the app opening."""

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        store = tmp_path / "manager.json"
        store.write_text("{ this is not json", encoding="utf-8")
        assert prefs.load(store) == prefs.DEFAULTS

    def test_wrong_shape_falls_back_to_defaults(self, tmp_path):
        store = tmp_path / "manager.json"
        store.write_text('["not", "a", "mapping"]', encoding="utf-8")
        assert prefs.load(store) == prefs.DEFAULTS

    @pytest.mark.parametrize("key,bad", [
        ("tts_mode", "carrier pigeon"),
        ("min_confidence", 99),
        ("min_confidence", 0),
        ("min_confidence", "loud"),
        ("strict", "yes"),
        ("dcs_path", 42),
    ])
    def test_individual_bad_values_are_discarded(self, tmp_path, key, bad):
        store = tmp_path / "manager.json"
        store.write_text(json.dumps({key: bad}), encoding="utf-8")
        assert prefs.load(store)[key] == prefs.DEFAULTS[key]

    def test_one_bad_value_does_not_discard_the_others(self, tmp_path):
        store = tmp_path / "manager.json"
        store.write_text(json.dumps({"tts_mode": "srs", "min_confidence": 99}),
                         encoding="utf-8")
        loaded = prefs.load(store)
        assert loaded["tts_mode"] == "srs"
        assert loaded["min_confidence"] == prefs.DEFAULTS["min_confidence"]

    def test_unknown_keys_are_not_written_back(self, tmp_path):
        store = tmp_path / "manager.json"
        prefs.save({"tts_mode": "srs", "nonsense": "dropped"}, store)
        assert "nonsense" not in store.read_text(encoding="utf-8")

    def test_saving_somewhere_unwritable_fails_quietly(self, tmp_path, monkeypatch):
        def explode(*args, **kwargs):
            raise OSError("read-only")
        monkeypatch.setattr("pathlib.Path.mkdir", explode)
        assert prefs.save({"tts_mode": "srs"}, tmp_path / "x" / "manager.json") is None


def test_stored_outside_the_dcs_folder():
    """Removing ATCAI from DCS must not wipe the user's preferences."""
    assert "Saved Games" not in str(prefs.prefs_path())
    assert prefs.prefs_path().name == prefs.FILENAME
