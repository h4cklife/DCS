"""Working cockpit controls by voice.

The map here names DCS **control names**, never key combinations: the keys come from
DCS's own binding files via atcai_bindings, so a player who rebinds gear to K needs no
change to this file.

Two things make this different from the comms-menu commands, and both shape the code:

  * **A mistake can be worse.** A wrong comms-menu press asks AWACS the wrong question.
    A wrong cockpit press might retract the gear on short final. So destructive controls
    are refused in code rather than merely left out of the map, and conditions on the
    live mission state are used where they exist.
  * **The phrases are adjacent.** "gear up" and "gear down" differ by one word and have
    opposite effects. Measured on 2026-10-25 across twenty utterances with zero
    confusions, but the confidence threshold for these is still kept separate from ATC's.
"""

import json
import os
import re

import atcai_keys

# Controls that are never operated by voice, however a map names them. Matched against
# the DCS control name, case-insensitively.
#
# Refused in code rather than simply omitted from the shipped map, because the map is
# editable: "out" has to mean out, not "out until someone adds it back". The failures
# here are unrecoverable in a way a wrong menu press is not.
DENY_PATTERNS = (
    r"eject",
    r"jettison",
    r"engine.*(start|stop|shut)",
    r"(start|stop|shut).*engine",
    r"fuel dump",
    r"master arm",
    r"weapon.*release",
    r"release.*weapon",
    r"\bfire\b.*(weapon|missile|gun)",
    r"countermeasure",
    r"chaff",
    r"flare",
    r"canopy.*jettison",
    r"\bsalvo\b",
)

_DENY = [re.compile(pattern, re.IGNORECASE) for pattern in DENY_PATTERNS]

# Separate from ATC's threshold. The cost of a miss here is saying it again; the cost of
# a false positive is a control moving when you did not ask. Measured floor was 0.73.
DEFAULT_CONFIDENCE = 0.70


def is_denied(control_name):
    """True when a control must never be operated by voice."""
    text = str(control_name or "")
    return any(pattern.search(text) for pattern in _DENY)


def denied_reason(control_name):
    return ("%s is not available by voice - destructive controls are deliberately "
            "excluded" % control_name)


# ---------- the map ----------

def bundled_dir():
    import atcai_listen
    return os.path.join(atcai_listen.resource_dir(), "cockpit")


def user_dir():
    """Where a player's own copy lives, beside their other settings.

    Same arrangement as the comms-menu maps: the shipped copy is inside the exe and
    cannot be edited, so it is seeded out to somewhere writable and read from there.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ATCAI", "cockpit")
    base = (os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "atcai", "cockpit")


def seed_user_controls(directory=None, bundled=None):
    """Copy the shipped file out if the player has none. Only ever adds."""
    import shutil

    directory = directory or user_dir()
    bundled = bundled or bundled_dir()
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
            copied.append(name)
        except OSError:
            continue
    return copied


def refresh_user_controls(directory=None, bundled=None):
    """Overwrite the player's copy with the shipped one, discarding local edits."""
    import shutil

    directory = directory or user_dir()
    bundled = bundled or bundled_dir()
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
            replaced.append(name)
        except OSError:
            continue
    return replaced


def controls_dir():
    """Read from the player's folder when it has a file, else the shipped one."""
    user = user_dir()
    try:
        if any(n.endswith(".json") for n in os.listdir(user)):
            return user
    except OSError:
        pass
    return bundled_dir()


def missing_user_controls(directory=None, bundled=None):
    """Controls the shipped list has that the player's copy does not.

    Seeding only ever *adds a file*, never merges into one that already exists, so a
    player who got their copy when the list held two controls keeps two controls for
    ever. That is not hypothetical: it hid four shipped controls - flaps, airbrake,
    canopy and lights - from a tester for weeks, and the only symptom was that saying
    "flaps" did nothing, which is indistinguishable from a recognition problem.

    Reported rather than merged, because the player's file is theirs: they may have
    deleted a control deliberately. "Use shipped controls" is the fix, and it asks first.
    """
    try:
        theirs = set(load_controls(directory or user_dir()))
        ours = set(load_controls(bundled or bundled_dir()))
    except Exception:
        return []
    if not theirs or not ours:
        return []                       # nothing seeded yet, or no shipped list to compare
    return sorted(ours - theirs)


def load_controls(directory=None):
    """{intent: entry} from controls.json, or {} if it cannot be read."""
    directory = directory or controls_dir()
    path = os.path.join(directory, "controls.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    controls = data.get("controls")
    if not isinstance(controls, dict):
        return {}
    return {name: entry for name, entry in controls.items()
            if isinstance(entry, dict) and entry.get("control")}


def all_phrases(directory=None):
    """{phrase: intent} from the map, plus conflicts found."""
    lookup, conflicts = {}, []
    for intent, entry in sorted(load_controls(directory).items()):
        for phrase in entry.get("phrases", []) or []:
            phrase = " ".join(str(phrase).lower().split())
            if not phrase:
                continue
            existing = lookup.get(phrase)
            if existing and existing != intent:
                conflicts.append((phrase, existing, intent))
                continue
            lookup[phrase] = intent
    return lookup, conflicts


def cockpit_intents(directory=None):
    return set(load_controls(directory))


# ---------- resolution ----------

class Resolution(object):
    def __init__(self, ok, keys=None, reason=None, control=None, display=None):
        self.ok = ok
        self.keys = keys or []
        self.display = display or list(self.keys)
        self.reason = reason
        self.control = control

    def __repr__(self):
        if self.ok:
            return "<Cockpit %s %s>" % (self.control, " ".join(self.display))
        return "<Cockpit refused: %s>" % self.reason


def resolve(intent, state, bindings, enabled=True, directory=None):
    """What a cockpit command means now. Every refusal carries a sayable reason."""
    if not enabled:
        return Resolution(False, reason="cockpit commands are turned off")

    entry = load_controls(directory).get(intent)
    if not entry:
        return Resolution(False, reason="%s is not in the control list" % intent)

    control = entry["control"]

    # Before anything else, and regardless of what the map asked for.
    if is_denied(control):
        return Resolution(False, control=control, reason=denied_reason(control))

    if not state:
        return Resolution(False, control=control,
                          reason="no mission state yet - start a mission and spawn in")

    for condition in entry.get("requires", []) or []:
        if not atcai_keys.check_condition(condition, state):
            reason = entry.get("refusal") or ("condition not met: %s" % condition)
            return Resolution(False, control=control, reason=reason)

    chords = (bindings or {}).get(control)
    if not chords:
        return Resolution(False, control=control,
                          reason="this aircraft has no %s binding" % control)

    # The first binding, when a control has several. Reported so the log can show which.
    return Resolution(True, keys=[chords[0]], display=[chords[0]], control=control)


def describe(resolution):
    if not resolution.ok:
        return "refused: %s" % resolution.reason
    return "%s: %s" % (resolution.control, " ".join(resolution.display))
