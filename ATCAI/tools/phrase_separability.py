#!/usr/bin/env python3
"""Measure whether the recogniser reliably tells two phrases apart.

Written for a specific worry: "gear up" and "gear down" differ by one word and have
opposite effects. For an ATC request a misrecognition costs you an odd reply; for a
cockpit control it could retract the gear on short final. Confidence alone does not
answer it, because a confident wrong answer is the dangerous case.

The candidates are tested against the **real grammar**, not in isolation. In the air the
recogniser is choosing between a hundred phrases, and competition is what makes confusion
likely - testing two phrases alone would flatter them.

Usage, from the ATCAI directory:

    python tools/phrase_separability.py "gear up" "gear down"

Say each phrase when prompted. Ctrl-C to stop early; the tally prints either way.
"""

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "voice-bridge"))

import atcai_listen  # noqa: E402


def build_grammar(candidates):
    """The real phrase set plus the candidates, so competition is realistic."""
    lookup = dict(atcai_listen.phrase_to_intent())
    for phrase in candidates:
        lookup[phrase.lower()] = "CANDIDATE:%s" % phrase.lower()
    return lookup


def listen(lookup, rounds, candidates, say=print):
    script = os.path.join(os.path.dirname(HERE), "voice-bridge", "recognize.ps1")
    if not os.path.exists(script):
        say("! recognize.ps1 not found at %s" % script)
        return None

    spec = {"requests": sorted(lookup), "wildcards": True}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as handle:
        json.dump(spec, handle)
        spec_path = handle.name

    heard = collections.defaultdict(list)
    failed = []
    wanted = [c.lower() for c in candidates]
    target = len(wanted) * rounds

    try:
        # Both paths need converting: powershell.exe is a Windows process and cannot
        # see a Linux path like /tmp/tmpXXXX.json when this runs under WSL.
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", atcai_listen.windows_path(script),
             atcai_listen.windows_path(spec_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            **atcai_listen.no_window())
    except OSError as exc:
        say("! could not start the recogniser: %s" % exc)
        return None

    say("%d phrases in the grammar, including the %d candidates."
        % (len(lookup), len(wanted)))
    say("Say each of these %d times, in any order:" % rounds)
    for phrase in wanted:
        say('   "%s"' % phrase)
    say("")

    count = 0
    try:
        for raw in process.stdout:
            line = raw.decode("cp1252", errors="replace").strip()
            if line.startswith("READY|"):
                say("Listening - go ahead.")
                continue
            if line.startswith("ERROR|"):
                say("! %s" % line[6:])
                failed.append(line[6:])
                break
            if "|" not in line:
                continue

            confidence, text = line.split("|", 1)
            try:
                confidence = float(confidence)
            except ValueError:
                continue

            matched = atcai_listen.match_intent(text, lookup)
            label = None
            if matched and matched.startswith("CANDIDATE:"):
                label = matched.split(":", 1)[1]

            if label:
                heard[label].append(confidence)
                count += 1
                say('  %2d/%d  heard "%s" -> %s (%.2f)'
                    % (count, target, text, label, confidence))
            else:
                # A candidate that resolved to something else entirely is the worst
                # outcome, so it is recorded rather than ignored.
                heard["OTHER: %s" % matched].append(confidence)
                say('  !!     heard "%s" -> %s (%.2f) - NOT a candidate'
                    % (text, matched, confidence))

            if count >= target:
                break
    except KeyboardInterrupt:
        say("\nstopped early")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            os.unlink(spec_path)
        except OSError:
            pass

    if failed:
        return None
    return heard


def report(heard, candidates, rounds, say=print):
    say("")
    say("%-28s %5s  %8s  %8s" % ("outcome", "count", "min conf", "mean conf"))
    say("-" * 56)
    for key in sorted(heard):
        values = heard[key]
        say("%-28s %5d  %8.2f  %8.2f"
            % (key, len(values), min(values), sum(values) / len(values)))

    strays = [k for k in heard if k.startswith("OTHER")]
    expected = len(candidates) * rounds
    got = sum(len(v) for k, v in heard.items() if not k.startswith("OTHER"))

    say("")
    if strays:
        say("VERDICT: not separable - %d utterance(s) matched something else entirely."
            % sum(len(heard[k]) for k in strays))
        say("Pick longer, less similar phrasings.")
    elif got < expected:
        say("VERDICT: inconclusive - only %d of %d expected utterances were captured."
            % (got, expected))
    else:
        lowest = min(min(v) for k, v in heard.items() if not k.startswith("OTHER"))
        say("VERDICT: each utterance matched a candidate. Lowest confidence %.2f."
            % lowest)
        say("Set the cockpit threshold below that, but only if you are satisfied none")
        say("of them was heard as the *wrong* candidate - check the lines above.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("candidates", nargs="+", help="the phrases to compare")
    parser.add_argument("--rounds", type=int, default=10,
                        help="how many times to say each (default: 10)")
    args = parser.parse_args()

    if len(args.candidates) < 2:
        print("give at least two phrases to compare")
        return 1

    lookup = build_grammar(args.candidates)
    heard = listen(lookup, args.rounds, args.candidates)
    if heard is None:
        return 1
    report(heard, args.candidates, args.rounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
