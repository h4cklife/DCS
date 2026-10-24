"""Voice control of DCS's own comms menus, by sending keystrokes to the game.

Mission scripting cannot touch those menus, and nothing can read them. What it *can*
read is everything that changes their shape - aircraft type, whether you have AI
wingmen, whether you are on the ground, whether an AWACS is up - which atc_state.lua
publishes to dcs.log. This module takes that state plus a per-aircraft key map and works
out which sequence a spoken command corresponds to.

This module decides and never acts. It resolves a spoken command against the published
state and a key map, and hands back a sequence - or a reason it declined. Pressing keys
lives in atcai_sendkeys.py, which is the only file that touches the OS, so the dangerous
part stays small enough to read in full and everything here stays testable anywhere.

DryRun is still the default transport: logging a sequence is how a key map gets checked
against the real menu before anything is pressed.

See docs/COMMS-KEYS-PLAN.md.
"""

import json
import os
import re

# A command is refused rather than guessed at. Each reason is reportable, because a
# refusal the player cannot explain is indistinguishable from the feature being broken.
REFUSAL_DISABLED = "comms key commands are turned off"
REFUSAL_NO_STATE = "no mission state yet - start a mission and spawn in"
REFUSAL_NO_MAP = "no key map for %s"
REFUSAL_UNKNOWN = "%s is not in the key map for %s"
REFUSAL_CONDITION = "%s"
REFUSAL_UNVERIFIED = ("the %s key map has not been checked in the cockpit yet - dry "
                      "run it, confirm the sequences, then set \"verified\": true")

STATE_PREFIX = "ATCAI_STATE|"
STATE_RE = re.compile(r"ATCAI_STATE\|(.+?)\s*$")

# Conditions a map entry can require, e.g. "wingmen>=1", "awacs", "onGround==0".
CONDITION_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)?\s*(-?\d+)?$")


def bundled_keymap_dir():
    """The maps shipped with the program - read-only when packaged into the exe."""
    import atcai_listen
    return os.path.join(atcai_listen.resource_dir(), "keymaps")


def user_keymap_dir():
    """Where a player's own maps live, beside their settings.

    The shipped maps are inside the exe and cannot be edited, which would make
    "the phrases are yours to change" untrue. So the maps are seeded into a writable
    folder on first run and read from there.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ATCAI", "keymaps")
    base = (os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "atcai", "keymaps")


def seed_user_keymaps(directory=None, bundled=None):
    """Copy any shipped map the player doesn't already have into their own folder.

    Only ever adds: a map the player has edited is never overwritten, so an update
    bringing a new aircraft doesn't discard their phrasings for the old ones. Returns
    the names copied.
    """
    import shutil

    directory = directory or user_keymap_dir()
    bundled = bundled or bundled_keymap_dir()
    copied = []
    try:
        os.makedirs(directory, exist_ok=True)
        names = sorted(os.listdir(bundled))
    except OSError:
        return copied

    for name in names:
        if not name.endswith(".json"):
            continue
        target = os.path.join(directory, name)
        if os.path.exists(target):
            continue
        try:
            shutil.copyfile(os.path.join(bundled, name), target)
            copied.append(name[:-5])
        except OSError:
            continue
    return copied


def refresh_user_keymaps(directory=None, bundled=None):
    """Overwrite the player's maps with the shipped ones, discarding local edits.

    The counterpart to seeding, and necessary because reading prefers the player's
    folder: once seeded, a corrected map shipped in an update would be ignored. Without
    a way to force the shipped version, that is a silent staleness bug.
    """
    import shutil

    directory = directory or user_keymap_dir()
    bundled = bundled or bundled_keymap_dir()
    replaced = []
    try:
        os.makedirs(directory, exist_ok=True)
        names = sorted(os.listdir(bundled))
    except OSError:
        return replaced

    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            shutil.copyfile(os.path.join(bundled, name),
                            os.path.join(directory, name))
            replaced.append(name[:-5])
        except OSError:
            continue
    return replaced


def stale_user_keymaps(directory=None, bundled=None):
    """Maps where the player's copy differs from the shipped one.

    Reported rather than acted on: a difference is usually the player's own edit, which
    must be left alone. It only matters because it means a shipped correction is not in
    effect, which is worth being able to see.
    """
    directory = directory or user_keymap_dir()
    bundled = bundled or bundled_keymap_dir()
    differing = []
    try:
        names = sorted(os.listdir(bundled))
    except OSError:
        return differing

    for name in names:
        if not name.endswith(".json"):
            continue
        theirs = os.path.join(directory, name)
        ours = os.path.join(bundled, name)
        if not os.path.exists(theirs):
            continue
        try:
            with open(theirs, "rb") as a, open(ours, "rb") as b:
                if a.read() != b.read():
                    differing.append(name[:-5])
        except OSError:
            continue
    return differing


def keymap_dir():
    """Where maps are read from: the player's folder when it has any, else the
    shipped ones. Falling back means a fresh install works before seeding."""
    user = user_keymap_dir()
    try:
        if any(n.endswith(".json") for n in os.listdir(user)):
            return user
    except OSError:
        pass
    return bundled_keymap_dir()


def parse_state(line):
    """One ATCAI_STATE line from dcs.log -> a dict of facts, or None.

    Values that look like integers become integers so conditions can compare them;
    everything else stays a string. Unknown keys are kept rather than dropped, so a
    newer mission script can publish a field this build has never heard of.
    """
    match = STATE_RE.search(line or "")
    if not match:
        return None

    state = {}
    for pair in match.group(1).split("|"):
        key, _, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        try:
            state[key] = int(value)
        except ValueError:
            state[key] = value
    return state or None


def check_condition(condition, state):
    """Does one `requires` entry hold against the published state?

    A bare name ("awacs") is true when the value is truthy. Absent fields are false,
    never assumed - guessing here would fire a sequence into a menu that isn't there.
    """
    match = CONDITION_RE.match((condition or "").strip())
    if not match:
        return False

    name, operator, number = match.group(1), match.group(2), match.group(3)
    if name not in state:
        return False

    value = state[name]
    if operator is None:
        return bool(value) and value != "0"

    try:
        left, right = int(value), int(number)
    except (TypeError, ValueError):
        return False

    return {
        ">=": left >= right, "<=": left <= right, "==": left == right,
        "!=": left != right, ">": left > right, "<": left < right,
    }[operator]


def load_keymap(aircraft, directory=None):
    """The map for one aircraft type, or None if there isn't one.

    A malformed map is reported as missing rather than raised: a bad file should mean
    the feature declines for that airframe, not that voice input dies.
    """
    if not aircraft:
        return None
    directory = directory or keymap_dir()
    path = os.path.join(directory, "%s.json" % aircraft)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("commands"), dict):
        return None
    return data


def available_maps(directory=None):
    """Aircraft types we have maps for, for the manager to display."""
    directory = directory or keymap_dir()
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    found = []
    for name in names:
        if name.endswith(".json") and load_keymap(name[:-5], directory):
            found.append(name[:-5])
    return found


def all_phrases(directory=None):
    """Every spoken phrase from every key map -> intent, plus any conflicts found.

    Phrases come from all maps, not just the aircraft you happen to be in: the
    recogniser's grammar is built once when listening starts, and reloading it on every
    aircraft change would mean a gap in recognition. An intent the current aircraft has
    no entry for is refused at resolution time instead, with a reason.

    Returns (lookup, conflicts). A conflict is one phrase meaning two different things
    in two maps - reported rather than silently resolved, because picking one at random
    would make a command work or not depending on which file loaded first.
    """
    directory = directory or keymap_dir()
    lookup, conflicts = {}, []

    for aircraft in available_maps(directory):
        keymap = load_keymap(aircraft, directory)
        for intent, command in sorted(keymap["commands"].items()):
            if not isinstance(command, dict):
                continue
            for phrase in command.get("phrases", []) or []:
                phrase = " ".join(str(phrase).lower().split())
                if not phrase:
                    continue
                existing = lookup.get(phrase)
                if existing and existing != intent:
                    conflicts.append((phrase, existing, intent))
                    continue
                lookup[phrase] = intent
    return lookup, conflicts


def comms_intents(directory=None):
    """Every intent any key map defines. Membership here is what makes an intent a
    comms command - more reliable than guessing from its name."""
    directory = directory or keymap_dir()
    found = set()
    for aircraft in available_maps(directory):
        found.update(load_keymap(aircraft, directory)["commands"])
    return found


# DCS numbers the per-wingman comms entries by *position among the survivors*, not by
# the aircraft's slot in the flight. Observed 2026-10-24: with wingman two dead, three
# and four moved to F2 and F3, and the menu even relabelled them "Wingman 2" and
# "Wingman 3" - while the radio still called them Chevy 83 and 84. The menu is purely
# positional; the aircraft keep their identity.
#
# That makes a fixed key wrong the moment anyone dies, and it is why these keys are
# computed at resolution time rather than stored in the map. Everything needed is
# already published: the slot numbers that are still alive.
WINGMAN_SLOTS = (2, 3, 4)

# The first wingman sits at F2, because F1 is the whole flight.
FIRST_WINGMAN_KEY = 2


def living_slots(state):
    """Slots still flying, in flight order. Absent fields count as empty, never alive."""
    return [n for n in WINGMAN_SLOTS if (state or {}).get("slot%d" % n)]


def wingman_key(slot, state):
    """The F-key that currently addresses the aircraft in this slot, or None if gone.

    F-key = its position among the living wingmen, plus one for the Flight entry.
    """
    alive = living_slots(state)
    if slot not in alive:
        return None
    return "F%d" % (alive.index(slot) + FIRST_WINGMAN_KEY)


class Resolution(object):
    """What should happen for one spoken comms command."""

    def __init__(self, ok, keys=None, reason=None, aircraft=None, delay_ms=None,
                 verified=False, display=None):
        self.ok = ok
        # keys are real key names, ready to send. display keeps the readable form, so a
        # log line says "comms F2 F9" rather than "backslash F2 F9".
        self.keys = keys or []
        self.display = display or list(self.keys)
        self.reason = reason
        self.aircraft = aircraft
        self.delay_ms = delay_ms
        self.verified = verified

    def __repr__(self):
        if self.ok:
            return "<Resolution %s %s>" % (self.aircraft, " ".join(self.display))
        return "<Resolution refused: %s>" % self.reason


def resolve(intent, state, enabled=True, directory=None, sending=False):
    """Decide what a comms intent means in the current situation.

    Returns a Resolution. Every refusal carries a reason fit to say out loud.

    sending=True means the caller intends to press the keys for real, which an
    unverified map is not allowed to do: its sequences are guesswork until someone has
    walked the menu, and pressing guesswork is how you trigger something you did not
    mean to. Dry runs are always allowed, because that is how a map gets verified.
    """
    if not enabled:
        return Resolution(False, reason=REFUSAL_DISABLED)
    if not state:
        return Resolution(False, reason=REFUSAL_NO_STATE)

    aircraft = state.get("aircraft")
    keymap = load_keymap(aircraft, directory)
    if not keymap:
        return Resolution(False, reason=REFUSAL_NO_MAP % (aircraft or "this aircraft"),
                          aircraft=aircraft)

    command = keymap["commands"].get(intent)
    if not isinstance(command, dict) or not command.get("keys"):
        return Resolution(False, reason=REFUSAL_UNKNOWN % (intent, aircraft),
                          aircraft=aircraft)

    for condition in command.get("requires", []):
        if not check_condition(condition, state):
            reason = command.get("refusal") or ("condition not met: %s" % condition)
            return Resolution(False, reason=REFUSAL_CONDITION % reason,
                              aircraft=aircraft)

    keys = list(command["keys"])
    slot = command.get("wingman")
    if slot is not None:
        # The map says which aircraft this addresses; the key for it depends on who is
        # still alive, so it is worked out now rather than baked in.
        key = wingman_key(int(slot), state)
        if not key:
            reason = command.get("refusal") or ("wingman %s is not with you" % slot)
            return Resolution(False, reason=reason, aircraft=aircraft)
        keys = [key if part == "{wingman}" else part for part in keys]

    if any(part.startswith("{") for part in keys):
        return Resolution(False, aircraft=aircraft,
                          reason="key map entry for %s has an unresolved placeholder"
                                 % intent)

    # "comms" is symbolic: the real key is whatever this aircraft's map says the player
    # has the menu bound to. Substituted here so nothing downstream needs to know.
    comms_key = keymap.get("comms_key", "backslash")
    sendable = [comms_key if part == "comms" else part for part in keys]

    if sending and not keymap.get("verified"):
        return Resolution(False, aircraft=aircraft,
                          reason=REFUSAL_UNVERIFIED % aircraft)

    return Resolution(True, keys=sendable, display=keys, aircraft=aircraft,
                      delay_ms=command.get("delay_ms", keymap.get("delay_ms", 90)),
                      verified=bool(keymap.get("verified")))


class DryRun(object):
    """Records what would have been pressed. The only transport in Phase A."""

    name = "dry-run"

    def __init__(self):
        self.sent = []

    def send(self, keys, delay_ms=90):
        self.sent.append(list(keys))
        return True


def describe(resolution):
    """One line for the manager's log."""
    if not resolution.ok:
        return "refused: %s" % resolution.reason
    note = "" if resolution.verified else "  (map unverified)"
    return "%s: %s%s" % (resolution.aircraft, " ".join(resolution.display), note)
