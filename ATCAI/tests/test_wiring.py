"""The four places a request has to be listed, checked against each other.

A request reaches the player through separate files that must agree: the handler in
atc_core.lua, the comms-menu entry in atc_menu.lua, the intent map in atc_inbox.lua and
the spoken phrases in atcai_listen.py. Nothing in DCS complains when they drift - a menu
entry naming a function that doesn't exist is simply a dead line in the comms menu, and
an intent with no handler is a request that is heard and then ignored. These tests are
the only thing that notices.
"""

import os
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

    def test_an_emergency_can_be_cancelled_without_voice(self, menu):
        """The one that matters most. If the recogniser declares an emergency the pilot
        did not, the menu is how they get out of it - including if they have switched the
        cancel command off, or cannot speak over what is happening."""
        assert "cancelEmergency" in menu


class TestIntents:
    def test_every_intent_has_a_handler_that_exists(self, handlers, core):
        missing = set(handlers.values()) - defined_functions(core)
        assert not missing, "intents map to undefined functions: %s" % sorted(missing)

    def test_every_spoken_atc_intent_is_mapped(self, handlers):
        """Comms-menu intents are handled outside the mission, so they are excluded -
        but every ATC request must still reach a handler, and the filter must not
        quietly empty the set."""
        atc_intents = {i for i in listen.INTENT_PHRASES
                       if not listen.is_comms_intent(i)}
        assert atc_intents, "filtered everything away - the invariant would be vacuous"
        assert atc_intents == set(handlers)

    def test_comms_intents_are_deliberately_absent_from_the_mission(self, handlers):
        for intent in listen.INTENT_PHRASES:
            if listen.is_comms_intent(intent):
                assert intent not in handlers

    def test_comms_intents_have_phrases_too(self):
        """A comms intent with no phrasing could never be triggered by voice, which is
        its only route - there is no menu entry for these."""
        for intent in listen.INTENT_PHRASES:
            if listen.is_comms_intent(intent):
                assert listen.INTENT_PHRASES[intent], "%s has no phrases" % intent

    def test_no_intent_is_silently_unspeakable(self, handlers):
        """A handler in the map with no phrases can only ever be reached by menu."""
        for intent in handlers:
            assert listen.INTENT_PHRASES.get(intent), "intent %r has no phrases" % intent


class TestPackaging:
    """A helper script that isn't bundled is missing only in the built exe - the one
    place it can't be checked by running from source."""

    @staticmethod
    def _bundled_names():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_exe", ROOT / "manager" / "build_exe.py")
        build_exe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_exe)
        return {src.name for src, _ in build_exe.BUNDLED}

    def test_every_non_python_runtime_file_is_bundled(self):
        """Not just the .ps1 files. PyInstaller picks up imported Python by itself;
        everything else - scripts, Lua, the JSON maps - has to be listed by hand, and
        forgetting one fails only in the built exe.

        Deliberately broad rather than a list of known files, so a new runtime file
        added later is covered without anyone remembering to extend this.
        """
        bundled = self._bundled_names()
        missing = []
        for entry in sorted((ROOT / "voice-bridge").iterdir()):
            if entry.name in ("__pycache__",) or entry.suffix == ".py":
                continue
            if entry.name not in bundled:
                missing.append(entry.name)
        assert not missing, (
            "used at runtime but would be missing from the exe: %s" % missing)

    def test_every_module_finds_its_bundled_files_under_meipass(self, tmp_path,
                                                                monkeypatch):
        """Being in BUNDLED is only half of it: the code also has to look where
        PyInstaller actually puts it.

        This is the test that was missing, and it cost a flight test. atcai_phrases
        resolved its defaults to <_MEIPASS>/phrases/ while BUNDLED lands them at
        <_MEIPASS>/voice-bridge/phrases/, so in the built exe the ATC phrase list came
        back empty and ATCAI was deaf to every ATC request - while every test passed,
        because from source the path happens to be right.

        So: build a fake extraction tree laid out exactly as BUNDLED declares, point
        _MEIPASS at it, and make each module prove it can find its own file there. The
        layout comes from BUNDLED itself, so this cannot drift from the real build.
        """
        import importlib.util
        import shutil
        spec = importlib.util.spec_from_file_location(
            "build_exe", ROOT / "manager" / "build_exe.py")
        build_exe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_exe)

        # Reproduce the exe's extraction folder. PyInstaller's --add-data target is
        # always a DIRECTORY: a file entry lands inside it under its own name, and a
        # directory entry has its contents copied into it.
        for source, target in build_exe.BUNDLED:
            destination = tmp_path / target
            destination.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination / source.name)

        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        import atcai_cockpit
        import atcai_keys
        import atcai_phrases
        sys.path.insert(0, str(ROOT / "manager"))
        import splash

        checks = {
            "the ATC phrase list": atcai_phrases.defaults_path(),
            "the splash image": splash.image_path(),
            "recognize.ps1": os.path.join(listen.resource_dir(), "recognize.ps1"),
            "the shipped key maps": atcai_keys.bundled_keymap_dir(),
            "the shipped cockpit controls": os.path.join(atcai_cockpit.bundled_dir(), "controls.json"),
        }
        missing = ["%s (looked in %s)" % (what, where)
                   for what, where in checks.items() if not os.path.exists(where)]
        assert not missing, (
            "would not be found inside the built exe: %s" % "; ".join(missing))

        # And the content really loads, not just the path resolving.
        assert atcai_phrases.load_defaults(), "the ATC phrase list came back empty"

    def test_no_tracked_path_is_illegal_on_windows(self):
        """The release is built on windows-latest, so a path Windows cannot create stops
        the build before a single test runs.

        It already did: two `*.png:Zone.Identifier` files - Windows mark-of-the-web
        leftovers that WSL materialises as real files - were committed, and
        actions/checkout failed with "invalid path" and exit code 128. Nothing about the
        code was wrong and no test could have failed, because the checkout never
        finished.

        Checks the same three things Windows itself rejects: the illegal characters,
        trailing dots or spaces, and the reserved device names.
        """
        import subprocess
        try:
            # From the repository root, not ATCAI's folder: checkout fails on an illegal
            # path anywhere in the tree, and the two that broke the build lived in the
            # parent repo's assets/ - so a listing scoped to ATCAI/ saw nothing wrong,
            # which is how this test passed on its first run while the build was failing.
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(ROOT),
                                 capture_output=True, text=True, timeout=60)
            if top.returncode != 0:
                pytest.skip("not a git checkout")
            listing = subprocess.run(
                ["git", "ls-files", "-z"], cwd=top.stdout.strip(),
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pytest.skip("git is not available here")
        if listing.returncode != 0:
            pytest.skip("not a git checkout")

        illegal = re.compile(r'[<>:"|?*\x00-\x1f]')
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved |= {"COM%d" % n for n in range(1, 10)}
        reserved |= {"LPT%d" % n for n in range(1, 10)}

        bad = []
        for path in filter(None, listing.stdout.split("\0")):
            for part in path.split("/"):
                if illegal.search(part):
                    bad.append("%s (illegal character)" % path)
                elif part.rstrip() != part or part.rstrip(".") != part:
                    bad.append("%s (trailing space or dot)" % path)
                elif part.split(".")[0].upper() in reserved:
                    bad.append("%s (reserved device name)" % path)
                else:
                    continue
                break
        assert not bad, (
            "these cannot be checked out on Windows, so the release build will fail "
            "before it starts: %s" % bad)

    def test_the_lua_the_bindings_reader_needs_is_bundled(self):
        """Named explicitly as well: without it, cockpit commands cannot find a single
        key combination, and the only symptom is every control reading as unknown."""
        assert "readbindings.lua" in self._bundled_names()


class TestConfigDefaults:
    """The manager shows these to the player as "what it is now", so a copy that has
    drifted from the Lua is worse than no copy at all."""

    # Function-scoped: a class-scoped fixture defined as an instance method is
    # deprecated and becomes an error in pytest 10. Re-reading one Lua file per test
    # costs nothing worth optimising.
    @pytest.fixture
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


class TestKeymapPackaging:
    def test_the_keymaps_directory_is_bundled(self):
        """Maps missing from the exe would make comms commands refuse for every
        aircraft - a failure that only appears in the built app."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_exe", ROOT / "manager" / "build_exe.py")
        build_exe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_exe)

        bundled = {str(src) for src, _ in build_exe.BUNDLED}
        assert str(ROOT / "voice-bridge" / "keymaps") in bundled


class TestTestHarnessStaysOut:
    """tools/test_kill_wingman.lua destroys units - the one thing ATCAI never does. It
    must not be able to reach a player's install."""

    def test_it_is_not_installed_with_the_module(self):
        import installer
        assert "test_kill_wingman.lua" not in installer.SCRIPT_FILES
        assert "kill_wingman.lua" not in installer.SCRIPT_FILES

    def test_it_is_not_loaded_by_the_hook(self):
        hook = (ROOT / "lua" / "hooks" / "atcai_autoload.lua").read_text(
            encoding="utf-8")
        assert "kill_wingman" not in hook

    def test_it_is_not_bundled_into_the_exe(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_exe", ROOT / "manager" / "build_exe.py")
        build_exe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_exe)
        for source, _ in build_exe.BUNDLED:
            assert "kill_wingman" not in str(source)

    def test_it_lives_outside_the_module_source(self):
        """In tools/, not lua/atc/, so it cannot be mistaken for part of ATCAI."""
        assert (ROOT / "tools" / "test_kill_wingman.lua").is_file()
        assert not (ROOT / "lua" / "atc" / "test_kill_wingman.lua").exists()


class TestPriority:
    def test_priority_intents_are_real_intents(self):
        unknown = set(listen.PRIORITY_INTENTS) - set(listen.INTENT_PHRASES)
        assert not unknown, "PRIORITY_INTENTS names intents that don't exist: %s" % unknown

    def test_a_distress_call_is_priority(self):
        assert "emergency" in listen.PRIORITY_INTENTS
