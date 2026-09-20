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

# Base phrasings per intent, mapped to the intents lua/atc/atc_inbox.lua understands.
# Only one form of each leading verb is listed: VERB_VARIANTS generates the rest, so
# "request taxi" and "requesting taxi" can never drift apart by hand.
INTENT_PHRASES = {
    "radio_check": [
        "radio check",
        "request radio check",
        "how do you read",
        "how do you hear me",
    ],
    "startup": [
        "request startup",
        "request engine start",
        "ready for startup",
    ],
    "taxi": [
        "request taxi",
        "request taxi clearance",
        "ready to taxi",
    ],
    "takeoff": [
        "request takeoff",
        "request departure",
        "ready for takeoff",
        "ready for departure",
    ],
    "inbound": [
        "report inbound",
        "request inbound",
        "inbound for landing",
    ],
    "landing": [
        "request landing",
        "request landing clearance",
        "on final",
    ],
    "parking": [
        "request parking",
        "request taxi to parking",
    ],
    "loadout": [
        "request loadout",
        "request weapons status",
        "loadout status",
        "say my loadout",
    ],
}

# Leading verbs people swap between without thinking. Each pair is expanded both ways.
VERB_VARIANTS = (("request", "requesting"), ("report", "reporting"))


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


def phrase_to_intent():
    return {p.lower(): intent
            for intent, phrases in INTENT_PHRASES.items()
            for p in expand_phrases(phrases)}


def match_intent(text, lookup):
    """Find the request inside a longer transmission.

    With wildcard matching the recognised text can carry a callsign, the tower's name,
    a runway and so on around the request itself, so an exact lookup isn't enough.
    Longest phrase wins, so "request taxi clearance" beats "request taxi".
    """
    spoken = " ".join(text.lower().split())
    exact = lookup.get(spoken)
    if exact:
        return exact
    best, best_len = None, 0
    for phrase, intent in lookup.items():
        if len(phrase) > best_len and re.search(r"\b%s\b" % re.escape(phrase), spoken):
            best, best_len = intent, len(phrase)
    return best


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
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run(args, on_log=None, should_stop=None):
    """Listen for ATC requests and write them to the inbox the mission polls.

    Returns when should_stop() goes true. on_log receives plain sentences so a GUI can
    show what was heard.
    """
    say = on_log or (lambda message: print(message, flush=True))
    lookup = phrase_to_intent()

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

    say("Commands go to %s" % inbox)
    say("%d phrasings, %s matching." % (
        len(lookup), "strict" if args.strict else "flexible"))

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

            write_inbox(inbox, intent)
            say('-> "%s" (%.2f) -> %s' % (text, confidence, intent))
    finally:
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
    parser.add_argument("--list-phrases", action="store_true",
                        help="print the phrases ATC understands and exit")
    parser.add_argument("--strict", action="store_true",
                        help="require the request to be the whole utterance, with no "
                             "callsign or other words around it. Less natural, but "
                             "harder to trigger by accident")
    args = parser.parse_args()

    if args.list_phrases:
        for intent in sorted(INTENT_PHRASES):
            for phrase in expand_phrases(INTENT_PHRASES[intent]):
                print("%-12s %s" % (intent, phrase))
        return 0

    print("ATCAI voice input")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
