"""The four places a request has to be listed, checked against each other.

A request reaches the player through separate files that must agree: the handler in
atc_core.lua, the comms-menu entry in atc_menu.lua, the intent map in atc_inbox.lua and
the spoken phrases in atcai_listen.py. Nothing in DCS complains when they drift - a menu
entry naming a function that doesn't exist is simply a dead line in the comms menu, and
an intent with no handler is a request that is heard and then ignored. These tests are
the only thing that notices.
"""

import re
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "voice-bridge"))

import atcai_listen as listen  # noqa: E402

ATC_DIR = ROOT / "lua" / "atc"


def read(name):
    return (ATC_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def core():
    return read("atc_core.lua")


@pytest.fixture(scope="module")
def menu():
    return read("atc_menu.lua")


@pytest.fixture(scope="module")
def handlers():
    """intent -> ATC function name, as atc_inbox.lua maps them."""
    block = re.search(r"local INTENT_HANDLERS = \{(.*?)\}", read("atc_inbox.lua"), re.S)
    assert block, "INTENT_HANDLERS table not found in atc_inbox.lua"
    return dict(re.findall(r"(\w+)\s*=\s*\"(\w+)\"", block.group(1)))


def defined_functions(core_text):
    return set(re.findall(r"^function ATC\.(\w+)", core_text, re.M))


class TestMenu:
    def test_every_menu_entry_calls_something_that_exists(self, menu, core):
        referenced = set(re.findall(r"addCommandForGroup\([^)]*?ATC\.(\w+)", menu))
        assert referenced, "no menu entries found"
        missing = referenced - defined_functions(core)
        assert not missing, "menu calls undefined ATC functions: %s" % sorted(missing)

    def test_the_new_requests_are_reachable_without_voice(self, menu):
        """Voice is the fast path for a mayday, but it must not be the only path."""
        for func in ("declareEmergency", "requestVectors", "requestStraightIn"):
            assert func in menu, "%s has no comms-menu entry" % func


class TestIntents:
    def test_every_intent_has_a_handler_that_exists(self, handlers, core):
        missing = set(handlers.values()) - defined_functions(core)
        assert not missing, "intents map to undefined functions: %s" % sorted(missing)

    def test_every_spoken_intent_is_mapped(self, handlers):
        assert set(listen.INTENT_PHRASES) == set(handlers)

    def test_no_intent_is_silently_unspeakable(self, handlers):
        """A handler in the map with no phrases can only ever be reached by menu."""
        for intent in handlers:
            assert listen.INTENT_PHRASES.get(intent), "intent %r has no phrases" % intent


class TestPackaging:
    """A helper script that isn't bundled is missing only in the built exe - the one
    place it can't be checked by running from source."""

    def test_every_powershell_helper_is_bundled(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_exe", ROOT / "manager" / "build_exe.py")
        build_exe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_exe)

        bundled = {src.name for src, _ in build_exe.BUNDLED}
        for script in (ROOT / "voice-bridge").glob("*.ps1"):
            assert script.name in bundled, (
                "%s is used at runtime but would be missing from the exe" % script.name)


class TestConfigDefaults:
    """The manager shows these to the player as "what it is now", so a copy that has
    drifted from the Lua is worse than no copy at all."""

    @pytest.fixture(scope="class")
    def lua_defaults(self):
        core = (ATC_DIR / "atc_core.lua").read_text(encoding="utf-8")
        found = {}
        for name, value in re.findall(
                r"ATC\.(\w+)\s*=\s*ATC\.\w+\s+or\s+([^\n-]+)", core):
            value = value.strip().rstrip(",").strip()
            if value.startswith('"') and value.endswith('"'):
                found[name] = value[1:-1]
            else:
                try:
                    found[name] = float(value)
                except ValueError:
                    pass
        return found

    def test_the_lua_actually_declares_them(self, lua_defaults):
        """Guards the parsing above: if it silently found nothing, every other
        assertion here would pass vacuously."""
        for name in ("TTS_FREQUENCY", "AIRBASE_SEARCH_RADIUS", "AIRBASE_AIR_RADIUS"):
            assert name in lua_defaults, "could not read %s out of atc_core.lua" % name

    def test_each_default_matches_the_lua(self, lua_defaults):
        import installer
        for key, value in installer.CONFIG_DEFAULTS.items():
            lua_name = key.upper()
            if lua_name not in lua_defaults:
                continue
            expected = lua_defaults[lua_name]
            if isinstance(value, str):
                assert value == expected, "%s drifted from atc_core.lua" % key
            else:
                assert float(value) == float(expected), "%s drifted from atc_core.lua" % key

    def test_every_default_is_a_real_setting(self):
        import installer
        unknown = set(installer.CONFIG_DEFAULTS) - set(installer.CONFIG_FIELDS)
        assert not unknown, "defaults for settings that don't exist: %s" % sorted(unknown)


class TestPriority:
    def test_priority_intents_are_real_intents(self):
        unknown = set(listen.PRIORITY_INTENTS) - set(listen.INTENT_PHRASES)
        assert not unknown, "PRIORITY_INTENTS names intents that don't exist: %s" % unknown

    def test_a_distress_call_is_priority(self):
        assert "emergency" in listen.PRIORITY_INTENTS
