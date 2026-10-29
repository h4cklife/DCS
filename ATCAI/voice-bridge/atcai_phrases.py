#!/usr/bin/env python3
"""What the player says, and the changes they have made to it.

Two files, deliberately separate:

  voice-bridge/phrases/atc_defaults.json   shipped, read-only, never copied out
  %LOCALAPPDATA%\\ATCAI\\phrases.json       the player's changes, and only those

The split is the whole point. The obvious design - copy the defaults into the player's
folder on first run, the way key maps work - cannot survive an update. Once their copy is
the whole list, "their edit" and "last release's default" are the same bytes in the same
place, so a shipped correction either overwrites their work or never reaches them.
`atcai_keys.stale_user_keymaps` exists only because of that, and all it can do is report
the problem.

Storing just the differences makes it go away. A command nobody has touched is absent
from the overlay and gets whatever the running release ships, so new commands and
corrected phrasings arrive on their own.

The overlay can re-word a command that exists. It cannot create one: an unknown intent
name is ignored. That is what keeps phrase editing away from the controls
`atcai_cockpit.DENY_PATTERNS` refuses - eject, jettison, engine shutdown, master arm,
weapons, countermeasures - because there is no command there to re-word.

Both the listener and the manager use this module. Two readers of one format is how
formats drift, and the tab must show exactly what the recogniser will hear.
"""

from __future__ import annotations

import json
import os
import re

VERSION = 1
OVERLAY_FILENAME = "phrases.json"

# Only what a speech grammar can actually take. Punctuation is at best ignored by SAPI
# and at worst stops the grammar building, and the failure is silent either way.
VALID_PHRASE = re.compile(r"^[a-z0-9 ]+$")

# Below this, a phrase is the shape that caused the mayday investigation: short enough
# for a dog, a TV or a jet to produce by accident. A warning, not a refusal - the player
# is allowed to make the trade, but not to make it unknowingly.
SHORT_PHRASE_CHARS = 8


def normalise(phrase):
    """Lowercased, whitespace collapsed - the same form match_intent compares against."""
    return " ".join(str(phrase).lower().split())


# ---------- the shipped defaults ----------

def resource_dir():
    """Where the bundled files are: the exe's extraction folder, or the source tree.

    The "voice-bridge" segment is not optional. PyInstaller extracts to _MEIPASS and
    `build_exe.BUNDLED` puts this package's files under `voice-bridge/` inside it, so
    _MEIPASS alone points at the wrong level. Getting that wrong made load_defaults()
    return {} in the built exe - no ATC phrases at all, silently, while running from
    source worked perfectly because there `__file__` already sits in voice-bridge/.

    Duplicated from atcai_listen.resource_dir rather than called: atcai_listen imports
    this module and reads the defaults at import time, so this would be re-entering a
    half-initialised module. test_wiring's _MEIPASS test is what keeps the two honest.
    """
    import sys
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return os.path.join(bundled, "voice-bridge")
    return os.path.dirname(os.path.abspath(__file__))


def defaults_path():
    return os.path.join(resource_dir(), "phrases", "atc_defaults.json")


def load_defaults(path=None):
    """The shipped ATC phrases as {intent: [phrase, ...]}.

    Returns an empty dict rather than raising: a missing or broken defaults file means
    no ATC requests, which the caller reports, rather than a manager that will not open.
    """
    try:
        with open(path or defaults_path(), encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}

    commands = doc.get("commands")
    if not isinstance(commands, dict):
        return {}

    out = {}
    for intent, entry in commands.items():
        if not isinstance(entry, dict):
            continue
        phrases = [normalise(p) for p in entry.get("phrases") or []
                   if normalise(p)]
        if phrases:
            out[str(intent)] = phrases
    return out


# ---------- the player's changes ----------

def overlay_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ATCAI")
    base = (os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "atcai")


def overlay_path():
    return os.path.join(overlay_dir(), OVERLAY_FILENAME)


def load_overlay(path=None):
    """The player's changes as ({intent: {enabled, add, remove}}, problems).

    Never raises and never fatal. A malformed overlay falls back to the defaults with
    its problems reported, because a hand-edited file with a trailing comma must not be
    able to stop voice control working.
    """
    target = path or overlay_path()
    problems = []
    if not os.path.exists(target):
        return {}, problems

    try:
        with open(target, encoding="utf-8") as handle:
            doc = json.load(handle)
    except OSError as exc:
        return {}, ["cannot read %s (%s)" % (target, exc)]
    except ValueError as exc:
        return {}, ["%s is not valid JSON (%s) - using the shipped phrases"
                    % (target, exc)]

    if not isinstance(doc, dict):
        return {}, ["%s should contain a JSON object - using the shipped phrases" % target]

    version = doc.get("version")
    if version is not None and version != VERSION:
        problems.append("%s is version %s, this build expects %d - reading what it can"
                        % (target, version, VERSION))

    commands = doc.get("commands")
    if commands is None:
        return {}, problems
    if not isinstance(commands, dict):
        return {}, problems + ["%s: 'commands' should be an object - ignoring it" % target]

    out = {}
    for intent, entry in commands.items():
        if not isinstance(entry, dict):
            problems.append("%s: ignoring '%s', which is not an object" % (target, intent))
            continue
        clean = {}
        if "enabled" in entry:
            if isinstance(entry["enabled"], bool):
                clean["enabled"] = entry["enabled"]
            else:
                problems.append("%s: '%s' has a non-true/false 'enabled' - ignoring it"
                                % (target, intent))
        for key in ("add", "remove"):
            if key not in entry:
                continue
            value = entry[key]
            if not isinstance(value, list):
                problems.append("%s: '%s' has a '%s' that is not a list - ignoring it"
                                % (target, intent, key))
                continue
            clean[key] = [normalise(p) for p in value if normalise(p)]
        if clean:
            out[str(intent)] = clean
    return out, problems


def save_overlay(overlay, path=None):
    """Write the player's changes. Returns the path, or None if it couldn't be written.

    Entries that say nothing are dropped on the way out, so "restore defaults" leaves no
    trace and the file stays a record of real changes only.
    """
    target = path or overlay_path()
    keep = {}
    for intent, entry in (overlay or {}).items():
        clean = {}
        if entry.get("enabled") is False:
            clean["enabled"] = False
        for key in ("add", "remove"):
            values = [normalise(p) for p in entry.get(key) or [] if normalise(p)]
            if values:
                clean[key] = sorted(set(values))
        if clean:
            keep[intent] = clean

    doc = {"version": VERSION, "commands": keep}
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temp = target + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp, target)
    except OSError:
        return None            # read-only home, locked file: not worth failing over
    return target


# ---------- applying one to the other ----------

def is_disabled(intent, overlay):
    entry = (overlay or {}).get(intent) or {}
    return entry.get("enabled") is False


def apply_overlay(pairs, overlay):
    """Filter one source's (phrase, intent) pairs through the player's changes.

    Applied per source - ATC requests, comms-menu commands, cockpit controls - because
    each is enumerated separately, and keyed by intent because intents are global where
    files are not: one comms phrase can be defined in four aircraft key maps at once, so
    there is no single file for the tab to write to.

    Additions are honoured only for an intent this source already defines, which is what
    stops the overlay inventing a command.
    """
    overlay = overlay or {}
    pairs = list(pairs)
    known = set(intent for _, intent in pairs)

    kept = []
    for phrase, intent in pairs:
        entry = overlay.get(intent) or {}
        if entry.get("enabled") is False:
            continue
        if normalise(phrase) in set(entry.get("remove") or []):
            continue
        kept.append((normalise(phrase), intent))

    for intent, entry in sorted(overlay.items()):
        if intent not in known or entry.get("enabled") is False:
            continue
        for phrase in entry.get("add") or []:
            pair = (normalise(phrase), intent)
            if pair not in kept:
                kept.append(pair)
    return kept


def effective(defaults, overlay):
    """The phrases actually in force, as {intent: [phrase, ...]}.

    What the Voice Commands tab displays, and what it must agree with the recogniser
    about. A disabled command is absent, not empty, so callers cannot mistake one for a
    command that merely lost all its phrases.
    """
    pairs = [(p, intent) for intent, phrases in defaults.items() for p in phrases]
    out = {}
    for phrase, intent in apply_overlay(pairs, overlay):
        out.setdefault(intent, []).append(phrase)
    return out


# ---------- checking a phrase the player typed ----------

class Check(object):
    """The verdict on a phrase: ok, a refusal, or something allowed with a warning."""

    def __init__(self, ok, level="ok", message="", duplicate_of=None):
        self.ok = ok
        self.level = level             # "ok", "refuse", "warn", "duplicate"
        self.message = message
        self.duplicate_of = duplicate_of

    def __repr__(self):
        return "Check(%s, %s, %r)" % (self.ok, self.level, self.message)


def check_phrase(phrase, intent, in_force, variants=None):
    """Whether `phrase` can be added to `intent`, given everything else in force.

    `in_force` is {intent: [phrase, ...]} - the effective list, so the answer accounts
    for the player's other changes. `variants` expands a leading verb, normally
    atcai_listen.expand_phrases; passing it keeps this module free of that import.

    Refusals are things the grammar cannot carry or that would silently break another
    command. Warnings are judgement calls the player is entitled to make - but not to
    make by accident, which is how this project got 22 false maydays in ten minutes.
    """
    spoken = normalise(phrase)
    if not spoken:
        return Check(False, "refuse", "Type a phrase first.")
    if not VALID_PHRASE.match(spoken):
        return Check(False, "refuse",
                     "Letters, digits and spaces only - the speech grammar cannot "
                     "carry punctuation, and it fails silently if you give it any.")

    owners = {}
    for other, phrases in (in_force or {}).items():
        for existing in phrases:
            owners[normalise(existing)] = other

    owner = owners.get(spoken)
    if owner == intent:
        return Check(False, "duplicate", "%s already has that phrase." % intent,
                     duplicate_of=intent)
    if owner:
        # Reported at startup today, and then the phrase is silently dropped. Catching
        # it here, where it can be fixed, is strictly better than finding it in a log.
        return Check(False, "refuse",
                     'That is already how you say "%s". One phrase cannot mean two '
                     "things - the recogniser would drop one of them." % owner)

    if variants:
        for variant in variants([spoken]):
            variant = normalise(variant)
            if variant == spoken:
                continue
            if owners.get(variant) == intent:
                return Check(False, "duplicate",
                             '"%s" already covers it - the leading verb is expanded '
                             "automatically, so you do not need both." % variant,
                             duplicate_of=intent)
            if variant in owners:
                return Check(False, "refuse",
                             'Its other form, "%s", is already how you say "%s". '
                             "The leading verb is expanded automatically, so adding "
                             "this would collide." % (variant, owners[variant]))

    warnings = []
    words = spoken.split()
    if len(words) == 1 or len(spoken) < SHORT_PHRASE_CHARS:
        warnings.append(
            "That is very short. Short phrases are what a jet, a keyboard, a TV or a "
            "dog produce by accident - 22 false emergency calls in ten minutes came "
            "from exactly this. It will work; it may also fire when you did not speak.")

    for existing, other in sorted(owners.items()):
        if existing == spoken:
            continue
        if _contains_word_sequence(spoken, existing):
            warnings.append(
                'It contains "%s" (%s). Longest match wins, so this will take '
                "precedence whenever you say it." % (existing, other))
        elif _contains_word_sequence(existing, spoken):
            warnings.append(
                'It is contained in "%s" (%s), which will win whenever both fit - so '
                "this phrase may not be reachable on its own." % (existing, other))

    if warnings:
        return Check(True, "warn", " ".join(warnings))
    return Check(True, "ok", "")


def _contains_word_sequence(haystack, needle):
    """Whole-word containment, matching how match_intent searches."""
    return re.search(r"\b%s\b" % re.escape(needle), haystack) is not None
