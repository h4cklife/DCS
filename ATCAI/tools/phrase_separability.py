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

Say each phrase when prompted, and **pause between repetitions**. The recogniser splits
utterances on silence, so running them together makes it emit the tail of one attempt and
the head of the next as a single event - which looks exactly like a misrecognition and is
not one. The report calls out any pair that arrived too close together.
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "voice-bridge"))

import atcai_listen  # noqa: E402


def build_grammar(candidates):
    """The real phrase set plus the candidates, so competition is realistic."""
    lookup = dict(atcai_listen.phrase_to_intent())
    for phrase in candidates:
        lookup[phrase.lower()] = CANDIDATE + phrase.lower()
    return lookup


CANDIDATE = "CANDIDATE:"

# Two recognitions closer together than this are very likely one intended utterance that
# the recogniser split, rather than two attempts. Measured on a run where the operator
# said "mayday mayday mayday" three times in quick succession: the words were right every
# time, but the boundaries fell mid-phrase and three events looked like failures.
FAST_GAP_SECONDS = 1.2


def classify(spoken, matched, wanted):
    """Which of three different things happened. The tool used to conflate the last two.

    - ("candidate", phrase)  the candidate was heard and matched. What we want.
    - ("routed", phrase)     the words were heard correctly, but something already in the
                             grammar claimed them first. A phrase-overlap problem in the
                             grammar, ours to fix - *not* an argument for re-phrasing the
                             candidate, which is what the old wording advised.
    - ("misheard", intent)   the recogniser produced different words. The only outcome
                             that actually says the phrasing is too confusable.
    """
    if matched and matched.startswith(CANDIDATE):
        return "candidate", matched.split(":", 1)[1]

    present = [c for c in wanted if re.search(r"\b%s\b" % re.escape(c), spoken)]
    if present:
        return "routed", max(present, key=len)
    return "misheard", matched


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
    fast = []
    last_at = None
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
    say("Pause about a second between repetitions, or the recogniser will run them")
    say("together and the result will be meaningless.")
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

            spoken = " ".join(text.lower().split())
            matched = atcai_listen.match_intent(text, lookup)
            kind, detail = classify(spoken, matched, wanted)

            now = time.monotonic()
            gap = None if last_at is None else now - last_at
            last_at = now
            note = ""
            if gap is not None and gap < FAST_GAP_SECONDS:
                fast.append(gap)
                note = "  [%.1fs after the last one]" % gap

            if kind == "candidate":
                heard[detail].append(confidence)
                count += 1
                say('  %2d/%d  heard "%s" -> %s (%.2f)%s'
                    % (count, target, text, detail, confidence, note))
            elif kind == "routed":
                heard["ROUTED to %s" % matched].append(confidence)
                say('  ??     heard "%s" (%.2f)%s' % (text, confidence, note))
                say('         the words were right - "%s" is in there - but the grammar'
                    % detail)
                say('         matched %s first. Grammar problem, not a phrasing problem.'
                    % matched)
            else:
                heard["MISHEARD as %s" % matched].append(confidence)
                say('  !!     heard "%s" -> %s (%.2f)%s - no candidate in the text'
                    % (text, matched, confidence, note))

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
    return heard, fast


def report(heard, fast, candidates, rounds, say=print):
    say("")
    say("%-32s %5s  %8s  %8s" % ("outcome", "count", "min conf", "mean conf"))
    say("-" * 60)
    for key in sorted(heard):
        values = heard[key]
        say("%-32s %5d  %8.2f  %8.2f"
            % (key, len(values), min(values), sum(values) / len(values)))

    routed = [k for k in heard if k.startswith("ROUTED")]
    misheard = [k for k in heard if k.startswith("MISHEARD")]
    good = [k for k in heard if not k.startswith(("ROUTED", "MISHEARD"))]
    expected = len(candidates) * rounds
    got = sum(len(heard[k]) for k in good)

    say("")
    if fast:
        # Said before any verdict, because it can invalidate one.
        say("NOTE: %d recognition(s) arrived within %.1fs of the previous one (closest"
            % (len(fast), FAST_GAP_SECONDS))
        say("      %.1fs). Those are probably one utterance the recogniser split, not"
            % min(fast))
        say("      separate attempts. Re-run with a clear pause between repetitions")
        say("      before trusting anything below.")
        say("")

    if misheard:
        say("VERDICT: not separable - %d utterance(s) came back as different words."
            % sum(len(heard[k]) for k in misheard))
        say("Pick longer, less similar phrasings.")
    elif routed:
        # Deliberately not the same advice. The old version printed "pick longer, less
        # similar phrasings" here too, which was the opposite of what the data said: the
        # words had been heard perfectly.
        say("VERDICT: heard correctly, but %d utterance(s) were claimed by a phrase"
            % sum(len(heard[k]) for k in routed))
        say("already in the grammar. The phrasing is fine; the grammar overlaps.")
        say("Either remove the shorter competing phrase or accept the existing routing.")
        say("This is not a reason to re-phrase the candidate.")
    elif got < expected:
        say("VERDICT: inconclusive - only %d of %d expected utterances were captured."
            % (got, expected))
    else:
        lowest = min(min(heard[k]) for k in good)
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
    result = listen(lookup, args.rounds, args.candidates)
    if result is None:
        return 1
    heard, fast = result
    report(heard, fast, args.candidates, args.rounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
