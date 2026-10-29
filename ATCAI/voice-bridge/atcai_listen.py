#!/usr/bin/env python3
"""Drive ATCAI by voice.

Listens for spoken ATC requests using the speech recogniser built into Windows, and
writes recognised intents to a Lua "inbox" file that the running mission polls
(lua/atc/atc_inbox.lua). Nothing to install: no models to download, no extra packages.

    ATCAI_INBOX = { seq = 1758300000123, intent = "taxi" }

The sequence number is milliseconds since the epoch, so it keeps rising across restarts
of this script and the mission never re-runs an old command.

Pair it with atcai_tts.py to hear the replies:

    python3 voice-bridge/atcai_listen.py
    python3 voice-bridge/atcai_tts.py --mode local
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

import atcai_phrases

# Base phrasings per intent, mapped to the intents lua/atc/atc_inbox.lua understands.
#
# The list itself lives in voice-bridge/phrases/atc_defaults.json now, so it can be read
# and diffed without reading Python, and so it sits alongside the comms and cockpit maps
# instead of being the one phrase list that was different. Loaded here rather than
# inlined so existing callers still find INTENT_PHRASES where they always have.
#
# Only one form of each leading verb is listed: VERB_VARIANTS generates the rest, so
# "request taxi" and "requesting taxi" can never drift apart by hand.
#
# What the *player* has changed is a separate file. See atcai_phrases for why.
INTENT_PHRASES = atcai_phrases.load_defaults()

# Intents handled outside the mission, by pressing keys in DCS's comms menu, rather
# than by writing to the inbox the mission polls. The authority is the key maps
# themselves: an intent is a comms command because some map defines it, not because of
# how its name happens to be spelled.
def comms_intents():
    try:
        import atcai_keys
        return atcai_keys.comms_intents()
    except Exception:                                    # no maps, or unreadable
        return set()


def is_comms_intent(intent):
    return bool(intent) and intent in comms_intents()


def cockpit_intents():
    try:
        import atcai_cockpit
        return atcai_cockpit.cockpit_intents()
    except Exception:                                    # no map, or unreadable
        return set()


def is_cockpit_intent(intent):
    return bool(intent) and intent in cockpit_intents()

def _by_intent(mapping):
    """{phrase: intent} -> {intent: [phrase, ...]}, which is how a person reads it."""
    out = {}
    for phrase, intent in sorted(mapping.items()):
        out.setdefault(intent, []).append(phrase)
    return out


def command_sources():
    """Every command there is, grouped by where it comes from, as
    [(group name, {intent: [shipped phrase, ...]}), ...].

    The recogniser does not care which source a phrase came from - phrase_to_intent
    flattens all three. This exists for the Voice Commands tab, where the grouping is
    how a person finds the command they want, and where "this whole source is switched
    off on another tab" needs saying.

    Shipped phrases, not effective ones: the tab applies the player's overlay itself so
    it can show what has been changed.
    """
    groups = [("ATC requests", dict(INTENT_PHRASES))]

    try:
        import atcai_keys
        comms, _ = atcai_keys.all_phrases()
        groups.append(("Comms menu", _by_intent(comms)))
    except Exception:                                    # no maps, or unreadable
        groups.append(("Comms menu", {}))

    try:
        import atcai_cockpit
        controls, _ = atcai_cockpit.all_phrases()
        groups.append(("Cockpit controls", _by_intent(controls)))
    except Exception:                                    # no map, or unreadable
        groups.append(("Cockpit controls", {}))

    return groups


# Leading verbs people swap between without thinking. Each pair is expanded both ways.
VERB_VARIANTS = (("request", "requesting"), ("report", "reporting"),
                 ("declare", "declaring"))


def expand_phrases(phrases):
    """Add the alternate form of any leading verb, e.g. request <-> requesting."""
    expanded = set()
    for phrase in phrases:
        expanded.add(phrase)
        verb, _, rest = phrase.partition(" ")
        if not rest:
            continue
        for first, second in VERB_VARIANTS:
            if verb == first:
                expanded.add("%s %s" % (second, rest))
            elif verb == second:
                expanded.add("%s %s" % (first, rest))
    return sorted(expanded)


def no_window():
    """Stop Windows flashing a console window for each helper process we launch.

    Without this a console pops up over the game for every spoken reply and every
    recognised phrase. Windows-only; harmless everywhere else.
    """
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def phrase_to_intent(on_log=None, overlay=None):
    """Every phrase the recogniser should listen for, mapped to its intent.

    ATC requests come from INTENT_PHRASES. Comms-menu commands come from the per-aircraft
    key maps and cockpit controls from controls.json, so a player can change what they say
    by editing a JSON file rather than the source.

    `overlay` is the player's own changes (atcai_phrases.load_overlay). It is applied here
    and nowhere else, because this is the one place all three sources meet - and because
    the result becomes the recogniser's grammar, so a disabled phrase is not recognised
    and then ignored, it simply does not exist. That is the only form of disable that
    works: a phrase still in the grammar can soak up a dog barking through the leading
    wildcard whatever we do with the result afterwards.

    Filtering happens on the base phrases, before expand_phrases, so switching off
    "request taxi" also switches off "requesting taxi". They are one command said two
    ways, and the tab shows the base form.
    """
    if overlay is None:
        overlay, problems = atcai_phrases.load_overlay()
        if problems and on_log:
            for problem in problems:
                on_log("! %s" % problem)

    atc = [(phrase, intent)
           for intent, phrases in INTENT_PHRASES.items()
           for phrase in phrases]
    lookup = {}
    for phrase, intent in atcai_phrases.apply_overlay(atc, overlay):
        for variant in expand_phrases([phrase]):
            lookup.setdefault(variant, intent)

    try:
        import atcai_keys
        comms, conflicts = atcai_keys.all_phrases()
    except Exception:
        return lookup

    # Map phrases get the same verb expansion ATC phrases do, so "request picture" and
    # "requesting picture" both work without every map having to list both.
    expanded = {}
    for phrase, intent in atcai_phrases.apply_overlay(sorted(comms.items()), overlay):
        for variant in expand_phrases([phrase]):
            expanded.setdefault(variant, intent)

    for phrase, intent in expanded.items():
        if phrase in lookup and lookup[phrase] != intent:
            # An ATC request and a comms command wanting the same words. ATC wins,
            # because it is the module's own function; the clash is worth reporting
            # rather than quietly losing one of them.
            if on_log:
                on_log('! "%s" is claimed by both %s and %s - keeping %s'
                       % (phrase, lookup[phrase], intent, lookup[phrase]))
            continue
        lookup[phrase] = intent

    if conflicts and on_log:
        for phrase, first, second in conflicts:
            on_log('! "%s" means %s in one key map and %s in another - ignoring it'
                   % (phrase, first, second))

    try:
        import atcai_cockpit
        cockpit_phrases, cockpit_conflicts = atcai_cockpit.all_phrases()
    except Exception:
        return lookup

    for phrase, intent in atcai_phrases.apply_overlay(sorted(cockpit_phrases.items()),
                                                      overlay):
        for variant in expand_phrases([phrase]):
            if variant in lookup and lookup[variant] != intent:
                if on_log:
                    on_log('! "%s" is claimed by both %s and %s - keeping %s'
                           % (variant, lookup[variant], intent, lookup[variant]))
                continue
            lookup[variant] = intent

    if cockpit_conflicts and on_log:
        for phrase, first, second in cockpit_conflicts:
            on_log('! "%s" means both %s and %s in the control list - ignoring it'
                   % (phrase, first, second))
    return lookup


# Intents that win over anything else said in the same breath, longest match or not.
# "Mayday, Chevy 81, request landing" is a declaration with a request attached, and
# resolving it to "landing" would answer the calm half of a distress call.
PRIORITY_INTENTS = ("emergency",)


def match_intent(text, lookup):
    """Find the request inside a longer transmission.

    With wildcard matching the recognised text can carry a callsign, the tower's name,
    a runway and so on around the request itself, so an exact lookup isn't enough.
    Longest phrase wins, so "request taxi clearance" beats "request taxi". A priority
    intent beats a non-priority one whatever their lengths - and among priority matches
    the longest still wins.

    That last clause used to be missing: the loop returned on the first priority phrase
    it happened to scan, which made the result depend on dict order and let a shorter
    distress phrase beat a longer one. Harmless while "mayday" was in the list and every
    emergency phrase meant the same thing; not harmless once the list has both
    "mayday mayday mayday" and "emergency landing" in it.
    """
    spoken = " ".join(text.lower().split())
    # An utterance that is exactly one phrase has no room for a second command, so the
    # priority rule cannot change the answer here. The one way it could - a non-priority
    # phrase whose own words contain a distress call - is what the phrase editor's
    # containment check exists to stop anyone creating.
    exact = lookup.get(spoken)
    if exact:
        return exact

    best, best_len = None, 0
    priority, priority_len = None, 0
    for phrase, intent in lookup.items():
        if not re.search(r"\b%s\b" % re.escape(phrase), spoken):
            continue
        if intent in PRIORITY_INTENTS:
            if len(phrase) > priority_len:
                priority, priority_len = intent, len(phrase)
        elif len(phrase) > best_len:
            best, best_len = intent, len(phrase)
    return priority or best


class StateWatcher(object):
    """Keeps the latest ATCAI_STATE the mission published.

    Only needed for comms-menu commands, which must know what aircraft you are in and
    whether you have wingmen. Starts lazily and fails quiet: if the log cannot be read,
    comms commands refuse with "no mission state yet" rather than guessing.
    """

    def __init__(self, log_path=None, on_log=None):
        self.log_path = log_path
        self.state = None
        self.on_log = on_log or (lambda message: None)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread or not self.log_path:
            return
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _watch(self):
        try:
            import atcai_keys
            import atcai_tts
        except ImportError as exc:
            self.on_log("! cannot watch mission state: %s" % exc)
            return

        last = None
        for line in atcai_tts.follow(self.log_path, should_stop=self._stop.is_set):
            if atcai_keys.STATE_PREFIX not in line:
                continue
            parsed = atcai_keys.parse_state(line)
            if not parsed:
                continue
            self.state = parsed
            # The slots matter more than the count now: they decide whether a
            # per-wingman command is refused, so they have to be visible. Showing only
            # the count made the deciding fact invisible in the log.
            alive = [str(n) for n in (2, 3, 4) if parsed.get("slot%d" % n)]
            summary = "%s, %d wingmen (slots %s), awacs=%s, tanker=%s" % (
                parsed.get("aircraft"), parsed.get("wingmen", 0),
                ",".join(alive) if alive else "none",
                parsed.get("awacs"), parsed.get("tanker"))
            if summary != last:
                last = summary
                self.on_log("mission state: %s" % summary)


def _handle_cockpit(intent, text, confidence, watcher, args, say):
    """A cockpit control. Its own confidence floor, and dry run unless told otherwise."""
    try:
        import atcai_cockpit
    except ImportError as exc:
        say("! cockpit commands unavailable: %s" % exc)
        return

    if not getattr(args, "cockpit_keys", False):
        say('~ "%s" -> %s: cockpit commands are turned off' % (text, intent))
        return

    # Checked separately from ATC's threshold: a miss here costs a retry, a false
    # positive moves a control you did not ask about.
    floor = getattr(args, "cockpit_confidence", atcai_cockpit.DEFAULT_CONFIDENCE)
    if confidence < floor:
        say('~ heard "%s" (%.2f) - below the cockpit threshold of %.2f, ignoring'
            % (text, confidence, floor))
        return

    state = watcher.state or {}
    bindings = {}
    cache = getattr(args, "bindings_cache", None)
    if cache is not None:
        try:
            bindings = cache.get(state.get("aircraft"))
        except Exception as exc:
            say("! could not read the bindings: %r" % exc)
            return

    resolution = atcai_cockpit.resolve(intent, watcher.state, bindings, enabled=True)
    if not resolution.ok:
        say('~ "%s" -> %s: %s' % (text, intent, resolution.reason))
        return

    described = atcai_cockpit.describe(resolution)

    if not getattr(args, "cockpit_send", False):
        say('-> "%s" (%.2f) -> %s | would press: %s'
            % (text, confidence, intent, described))
        return

    try:
        import atcai_sendkeys
    except ImportError as exc:
        say("! cannot send keys: %s" % exc)
        return

    sender = atcai_sendkeys.SendKeys()
    if sender.send(resolution.keys, 90):
        say('-> "%s" (%.2f) -> %s | pressed: %s'
            % (text, confidence, intent, described))
    else:
        say('~ "%s" -> %s not sent: %s' % (text, intent, sender.last_error))


# Comms-menu commands press keys into DCS exactly as cockpit commands do, so they get
# the same floor rather than ATC's. They had been sharing ATC's lower one, which is an
# asymmetry with nothing behind it: a missed radio call costs a repeat, a false
# "flight return to base" sends your flight home.
COMMS_CONFIDENCE = 0.70


def _handle_comms(intent, text, confidence, watcher, args, say):
    """A comms-menu command: resolve it, then press the keys if sending is on."""
    try:
        import atcai_keys
    except ImportError as exc:
        say("! comms keys unavailable: %s" % exc)
        return

    # Only when the keys will actually be pressed. In dry run the whole point is to see
    # what a command would do, so a marginal recognition is worth reporting.
    sending = bool(getattr(args, "send_keys", False))
    floor = getattr(args, "comms_confidence", COMMS_CONFIDENCE)
    if sending and confidence < floor:
        say('~ heard "%s" (%.2f) - below the comms threshold of %.2f, ignoring'
            % (text, confidence, floor))
        return

    resolution = atcai_keys.resolve(
        intent, watcher.state, enabled=getattr(args, "comms_keys", False),
        sending=sending)

    if not resolution.ok:
        say('~ "%s" -> %s: %s' % (text, intent, resolution.reason))
        return

    described = atcai_keys.describe(resolution)

    # Sending for real is a separate opt-in from listening for these commands at all,
    # so the dry run stays available as the safe default and as the way to check a map.
    if not sending:
        atcai_keys.DryRun().send(resolution.keys, resolution.delay_ms)
        say('-> "%s" (%.2f) -> %s | would press: %s' % (
            text, confidence, intent, described))
        return

    try:
        import atcai_sendkeys
    except ImportError as exc:
        say("! cannot send keys: %s" % exc)
        return

    sender = atcai_sendkeys.SendKeys()
    if sender.send(resolution.keys, resolution.delay_ms):
        say('-> "%s" (%.2f) -> %s | pressed: %s' % (
            text, confidence, intent, described))
    else:
        say('~ "%s" -> %s not sent: %s' % (text, intent, sender.last_error))


def default_inbox_path(windows_user):
    """Where the mission expects the inbox, as a path this script can write to."""
    if running_under_wsl():
        return "/mnt/c/Users/%s/Saved Games/DCS/Scripts/ATCAI/inbox.lua" % windows_user
    return r"C:\Users\%s\Saved Games\DCS\Scripts\ATCAI\inbox.lua" % windows_user


def running_under_wsl():
    # os.name first: when Windows Python is launched from a \\wsl.localhost\... path,
    # a rooted read of /proc/version resolves onto the WSL share and reports microsoft.
    if os.name == "nt":
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def write_inbox(path, intent):
    """Atomically publish one command for the mission to pick up."""
    seq = int(time.time() * 1000)
    body = 'ATCAI_INBOX = { seq = %d, intent = "%s" }\n' % (seq, intent)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(body)
    # Replace rather than rewrite in place: the mission may dofile() this at any moment
    # and must never see a half-written file.
    os.replace(tmp, path)
    return seq


def windows_path(path):
    if running_under_wsl():
        return subprocess.run(["wslpath", "-w", path], capture_output=True,
                              text=True, check=True, **no_window()).stdout.strip()
    return path


# Push-to-talk. Recognition finishes *after* you stop speaking, so the key is not
# usually still down when a result arrives — instead a watcher records when it was last
# held, and a result counts if the key was down at any point during the utterance.
PTT_GRACE_SECONDS = 2.5


class PushToTalk:
    """Watches a key globally, so it works while DCS has focus.

    Disabled (or off Windows) it reports every moment as talking, which is the
    listen-all-the-time behaviour.
    """

    def __init__(self, enabled=False, key_code=0x11, poll=0.05):
        self.enabled = bool(enabled) and os.name == "nt"
        self.key_code = int(key_code or 0x11)
        self.poll = poll
        self.last_down = 0.0
        self._stop = threading.Event()
        self._thread = None

    def available(self):
        return os.name == "nt"

    def start(self):
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _watch(self):
        import ctypes
        user32 = ctypes.windll.user32
        while not self._stop.is_set():
            # High bit set means the key is currently down.
            if user32.GetAsyncKeyState(self.key_code) & 0x8000:
                self.last_down = time.time()
            time.sleep(self.poll)

    def was_talking(self):
        if not self.enabled:
            return True
        return (time.time() - self.last_down) <= PTT_GRACE_SECONDS


def resource_dir():
    """Where recognize.ps1 lives, whether running from source or a packaged binary."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return os.path.join(bundled, "voice-bridge")
    return os.path.dirname(os.path.abspath(__file__))


def build_options(**overrides):
    """Default settings, so callers (like the manager app) don't need argparse."""
    defaults = dict(
        windows_user=os.environ.get("DCS_WINDOWS_USER", ""),
        inbox=None, min_confidence=0.6, strict=False,
        ptt_enabled=False, ptt_key_code=0x11, ptt_key_name="Left Ctrl",
        comms_keys=False, send_keys=False, dcs_log=None,
        comms_confidence=COMMS_CONFIDENCE,
        cockpit_keys=False, cockpit_send=False, cockpit_confidence=0.70,
        bindings_cache=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run(args, on_log=None, should_stop=None):
    """Listen for ATC requests and write them to the inbox the mission polls.

    Returns when should_stop() goes true. on_log receives plain sentences so a GUI can
    show what was heard.
    """
    say = on_log or (lambda message: print(message, flush=True))
    # Always read the player's changes from disk here rather than taking them from the
    # caller: the manager writes the file and restarts listening, so the file is the one
    # source of truth and the tab cannot show something the recogniser disagrees with.
    lookup = phrase_to_intent(on_log=say)
    if not lookup:
        # Reachable by disabling everything in the Voice Commands tab, or by a
        # hand-edited phrases.json. recognize.ps1 has never been handed an empty
        # grammar, and a clear refusal beats finding out what it does.
        say("! every voice command is disabled - nothing to listen for.")
        say("  Re-enable something on the Voice Commands tab.")
        return 1

    inbox = args.inbox or default_inbox_path(args.windows_user or "")
    try:
        os.makedirs(os.path.dirname(inbox), exist_ok=True)
    except OSError as exc:
        say("! cannot write to %s (%s)" % (inbox, exc))
        return 1

    script = os.path.join(resource_dir(), "recognize.ps1")
    if not os.path.exists(script):
        say("! speech recogniser script missing: %s" % script)
        return 1

    spec = {"requests": sorted(lookup), "wildcards": not args.strict}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as handle:
        json.dump(spec, handle)
        phrase_file = handle.name

    ptt = PushToTalk(getattr(args, "ptt_enabled", False),
                     getattr(args, "ptt_key_code", 0x11))
    ptt.start()

    watcher = StateWatcher(getattr(args, "dcs_log", None), on_log=say)
    if getattr(args, "comms_keys", False):
        watcher.start()
        if getattr(args, "send_keys", False):
            say("Comms key commands: SENDING KEYS to DCS when it has focus.")
        else:
            say("Comms key commands: dry run only - nothing will be pressed.")

    say("Commands go to %s" % inbox)
    say("%d phrasings, %s matching." % (
        len(lookup), "strict" if args.strict else "flexible"))
    if ptt.enabled:
        say("Push-to-talk on: hold %s while speaking."
            % getattr(args, "ptt_key_name", "your key"))
    elif getattr(args, "ptt_enabled", False):
        say("! push-to-talk needs Windows; listening continuously instead")

    try:
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", windows_path(script), windows_path(phrase_file)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **no_window(),
        )
    except OSError as exc:
        say("! could not start the speech recogniser: %s" % exc)
        os.unlink(phrase_file)
        return 1

    # Popen.stdout.readline blocks, so a stop request is noticed by killing the process
    # rather than by the loop checking a flag.
    stopper = None
    if should_stop:
        def watch():
            while not should_stop():
                time.sleep(0.2)
            if proc.poll() is None:
                proc.terminate()
        stopper = threading.Thread(target=watch, daemon=True)
        stopper.start()

    try:
        for raw in proc.stdout:
            line = raw.decode("cp1252", errors="replace").strip()
            if not line:
                continue
            if line.startswith("ERROR|"):
                say("! %s" % line[6:])
                return 1
            if line.startswith("READY|"):
                say("Listening.")
                continue
            if "|" not in line:
                continue

            confidence, text = line.split("|", 1)
            try:
                confidence = float(confidence)
            except ValueError:
                continue

            intent = match_intent(text, lookup)
            if not intent:
                say('~ heard "%s" but found no request in it' % text)
                continue
            if confidence < args.min_confidence:
                say('~ heard "%s" (%.2f) - too unclear, ignoring' % (text, confidence))
                continue
            if not ptt.was_talking():
                say('~ heard "%s" but the push-to-talk key was not held' % text)
                continue

            if is_cockpit_intent(intent):
                _handle_cockpit(intent, text, confidence, watcher, args, say)
                continue

            if is_comms_intent(intent):
                _handle_comms(intent, text, confidence, watcher, args, say)
                continue

            write_inbox(inbox, intent)
            say('-> "%s" (%.2f) -> %s' % (text, confidence, intent))
    finally:
        ptt.stop()
        watcher.stop()
        if proc.poll() is None:
            proc.terminate()
        try:
            os.unlink(phrase_file)
        except OSError:
            pass
    say("Stopped.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-user", default=os.environ.get("DCS_WINDOWS_USER", ""))
    parser.add_argument("--inbox", help="path to the Lua inbox file the mission polls")
    parser.add_argument("--min-confidence", type=float, default=0.6,
                        help="ignore recognitions below this confidence (0-1)")
    parser.add_argument("--comms-confidence", type=float, default=COMMS_CONFIDENCE,
                        help="separate floor for comms-menu commands, which press keys")
    parser.add_argument("--list-phrases", action="store_true",
                        help="print the phrases ATC understands and exit")
    parser.add_argument("--ptt-key-code", type=lambda v: int(v, 0), default=0x11,
                        help="virtual-key code to hold for push-to-talk, e.g. 0x11 for Ctrl")
    parser.add_argument("--ptt", dest="ptt_enabled", action="store_true",
                        help="only act on speech while the push-to-talk key is held")
    parser.add_argument("--comms-keys", dest="comms_keys", action="store_true",
                        help="enable DCS comms-menu commands. Phase A: dry run only, "
                             "nothing is pressed")
    parser.add_argument("--send-keys", dest="send_keys", action="store_true",
                        help="actually press the keys rather than only logging them. "
                             "Requires --comms-keys, and refuses unless DCS has focus")
    parser.add_argument("--dcs-log", dest="dcs_log", default=None,
                        help="path to dcs.log, where the mission publishes the state "
                             "comms-menu commands need")
    parser.add_argument("--strict", action="store_true",
                        help="require the request to be the whole utterance, with no "
                             "callsign or other words around it. Less natural, but "
                             "harder to trigger by accident")
    args = parser.parse_args()
    args.ptt_key_name = "key 0x%02X" % args.ptt_key_code

    if args.list_phrases:
        for intent in sorted(INTENT_PHRASES):
            for phrase in expand_phrases(INTENT_PHRASES[intent]):
                print("%-12s %s" % (intent, phrase))
        return 0

    print("ATCAI voice input")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
