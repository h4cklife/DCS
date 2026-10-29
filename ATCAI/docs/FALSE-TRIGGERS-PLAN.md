# False triggers on high-consequence commands — design plan

**Status: proposed, nothing changed.** Written in response to ATCAI repeatedly hearing
"mayday" from music playing in one earbud, 2026-10-28.

## What a false mayday actually costs

More than a spurious transmission, which is why this is worth fixing rather than living
with.

`ATC.declareEmergency` does three things, and only the first is visible:

1. **Transmits a reply** - "roger your emergency, cleared to land, emergency vehicles
   standing by" - and because emergencies transmit *wide*, it goes out on every
   plausible frequency at once.
2. **Sets `state.emergency = true`** and the phase to INBOUND.
3. **That state persists**, and while it is set, landing skips the traffic check
   entirely:

   ```lua
   local conflict
   if not ctx.state.emergency then
       conflict = ATC.checkRunway(ctx)
   end
   ```

   So an aircraft in a falsely-declared emergency is **never sequenced behind arriving
   traffic and never sent around** - the traffic awareness that is otherwise the point
   of the module is switched off, silently, for the rest of the sortie.

**The only way out is to taxi to parking.** `requestParking` is the single place that
clears the flag. There is no way to say "disregard that".

And `PRIORITY_INTENTS` makes it worse: a mayday heard inside another utterance **beats**
the real request. "Mayday" misheard inside "request landing" gives you an emergency, not
a landing clearance. That rule is right for a genuine distress call and actively harmful
for a false one.

## Measured, 2026-10-28

A single session with the jet running, typing, and ATCAI's own replies audible produced
**22 false emergency declarations**:

| | |
|---|---|
| Confidence | min 0.76, **median 0.92**, max 0.95 |
| At or above 0.88 | **17 of 22** |
| Phrase | **"pan pan" 20, "mayday" 2** |
| With noise absorbed around the match (`...`) | 10 of 22 |

ATC answered about eight times, each a *wide* transmission on five frequencies, and the
aircraft sat in emergency state - traffic checks disabled - throughout.

**This data overturns two things in the first draft of this plan.**

**A confidence threshold is useless here.** The median false positive is 0.92. Blocking
these would mean a bar above 0.95, which would reject genuine calls. Option 4 below is
dead, not merely insufficient.

**Requiring repetition is weaker than I claimed.** "mayday mayday" **false-fired at
0.83** in this very log. Doubling the phrase did not prevent it. Tripling may still
help, but the evidence no longer supports repetition as the primary fix.

**"pan pan" is the overwhelming culprit** - 20 of 22. Two short plosive syllables is
close to what a jet engine and a keyboard produce. "mayday" barely features, and both
instances were at the low end of the confidence range.

**The wildcards are visibly implicated.** Ten of the 22 recognitions show `...` around
the phrase, meaning the optional wildcards absorbed surrounding noise and the short
phrase landed inside it. That is direct evidence for option 3, which the first draft
under-weighted.

**And nothing stops a repeat.** `declareEmergency` sets `state.emergency = true`
unconditionally - it never checks whether the aircraft is already in one. That is why 22
triggers produced eight separate transmissions instead of one.

## Why noise triggers it

Three things compound:

- **The phrases are tiny.** "mayday" is six characters, one word. "pan pan" is two short
  identical syllables - close to what music incidentally produces.
- **The grammar wraps every phrase in optional wildcards** (`AppendWildcard` in
  `recognize.ps1`), so a request may be embedded in anything else. That is what makes
  natural speech work - "Chevy 81, requesting taxi, over" - and it is also what lets
  background audio match: the wildcards absorb the noise and the short phrase lands.
- **Push-to-talk is off**, by preference, so the recogniser hears everything the room
  produces.

**Raising the confidence threshold will not fix this on its own.** Earlier logs show
"pan pan" recognised at 0.93-0.95. A false positive can be entirely confident, so the
bar is not what is failing.

## Options

**1. Drop the bare one- and two-word phrases.** Remove "mayday" and "pan pan" alone,
keep "mayday mayday", "declare an emergency" and the rest. Minutes of work, immediate
effect, costs the shortest form.

**2. Require repetition.** "mayday mayday mayday", "pan pan pan". **Real procedure
already demands this** - a distress call is repeated three times precisely so it cannot
be mistaken - so the realistic phrasing is also the robust one. Three repetitions of a
word is far less likely in noise than one. No new machinery: it is a phrase-list change.

**3. Strict matching for this intent only.** Require the recognised text to *be* the
phrase rather than contain it, bypassing the wildcards for emergency alone. This attacks
the actual mechanism rather than its symptoms, but needs a per-intent flag through
`match_intent`, and it costs the natural "mayday mayday, Chevy 81, engine fire" phrasing
that works today.

**4. A separate, higher confidence floor for the emergency intent**, as the cockpit
commands already have. Cheap and worth having, but the evidence above says it is not
sufficient alone.

**5. Add a cancel command.** "cancel emergency", "disregard my emergency", "cancel
mayday". **This should happen regardless of what else is chosen**: today a genuine
emergency you change your mind about is equally stuck until you park, which is its own
bug. It also turns a false trigger from a ruined sortie into an annoyance.

**6. Confirmation handshake** - ATC asks "confirm you are declaring an emergency" and
waits. Safest against false positives, and I would argue against it: it adds a round
trip to the one call where speed is the whole point.

**7. Push-to-talk.** The only *complete* answer - the recogniser cannot mishear a room
it is not listening to. Rejected as a default because the operator prefers it off, but
worth stating plainly: everything else here reduces the rate, and this eliminates it.

## Revised recommendation, after measuring

**0. Make a repeat declaration a no-op.** `declareEmergency` should notice it is already
in an emergency and stay quiet, or at most re-acknowledge briefly. This does not stop the
first false trigger, but it turns a cascade of eight transmissions into one. Cheap,
obviously correct, and beneficial for genuine calls too - saying "mayday" twice should
not produce two clearances.

**1. Drop "pan pan" entirely.** 20 of 22 false triggers. It is also the least useful
phrase in the list: *pan-pan* is the urgency call, not distress, and ATCAI treats it
identically to a mayday anyway. Removing it is one line and removes 90% of the problem.

**2. Drop the bare "mayday"**, keep "mayday mayday mayday" and the longer "declare an
emergency" forms. Tripling is real procedure and is three times harder to hit by
accident than the doubling that demonstrably failed.

**3. Strict matching for this intent. Now argued against.** It looked like the strongest
structural fix - ten of the false matches had something absorbed by the wildcards. But
the tripling run showed the absorbed material is not always noise: speak a real mayday
fast and the recogniser's segmentation puts the tail of one attempt in front of the next,
producing exactly the `... mayday mayday mayday` shape.

**Strict matching would reject that.** And fast, repeated, slightly panicked delivery is
precisely the circumstance of a genuine emergency. It would trade false positives for
false negatives *in the one case where a false negative is worst*, which is the wrong
direction for this particular command. Keep it as a last resort for some other intent,
not this one.

It would also cost "mayday mayday, Chevy 81, engine fire", which is how a real call
sounds.

**4. A higher confidence floor. Dead.** Median false positive 0.92.

**5. The cancel command**, still worth doing on its own merits.

Order: **0 and 1 together** - they are both one-liners and should remove nearly all of
it. Measure again. Then 2, then 5, and 3 only if it is still leaking.

## Tripling measured, 2026-10-28 — and a matcher bug it exposed

`tools/phrase_separability.py "mayday mayday mayday" "gear down"`:

```
10/10  "mayday mayday mayday"   0.91 - 0.95
10/10  "gear down"              0.88 - 0.95
 !!    "mayday mayday"          0.93   (said deliberately, to see what happened)
 !!    "... mayday mayday mayday" 0.94  routed to emergency, not the candidate
 !!    "... mayday mayday mayday" 0.93  same
```

**The tool's verdict of "not separable" was wrong, and so was the conclusion it invited.**
The recogniser heard every one of those twelve utterances correctly. What diverted three
of them was `match_intent`, not the recogniser.

**And the `...` was not noise.** The operator was saying "mayday mayday mayday" on all
three attempts, but speaking them too close together: the recogniser segments on
end-of-speech, so the tail of one attempt landed in the same utterance as the head of the
next. The leading wildcard then absorbed the leftover fragment. Same mechanism as the
noise case - the wildcard swallows whatever precedes the phrase - but a different source:
**your own previous sentence**.

That matters more than it first appears, and is taken up under "Strict matching" below.

**The mechanism.** `match_intent` checks for an exact match first, then scans for the
longest contained phrase - except that a hit on a `PRIORITY_INTENTS` phrase returns
**immediately**:

```python
if intent in PRIORITY_INTENTS:
    return intent
```

So `"mayday mayday mayday"` exactly matches the candidate and wins. But
`"... mayday mayday mayday"` misses the exact lookup, the scan then finds the existing
`"mayday"` or `"mayday mayday"` phrase, and priority returns emergency before the longer
candidate is ever considered.

Two conclusions, in order of importance:

**1. Tripling works, and better than the raw numbers suggest. 12 of 12 utterances were
heard correctly, at 0.91-0.95**, including the three the tool flagged - those were
mis-segmented, not misheard. That is the measurement recommendation 2 was waiting on, and
it passes. The shorter forms must be removed at the same time, or the priority
short-circuit matches them first and the longer phrase never gets a chance - which is
exactly what this run demonstrated.

It also **degrades gracefully**, which is the property that matters for a distress call:
when fast delivery split the phrase, every fragment still matched `emergency`. A mayday
chopped in half still declares one. That is the right failure direction.

**2. `PRIORITY_INTENTS` ignores longest-match, and is order-dependent.** With both
`"mayday"` and `"mayday mayday"` in the list, whichever the dict happens to yield first
wins. Today every emergency phrase maps to the same intent so nothing user-visible
breaks, but it is latent: a second priority intent, or any wish to distinguish the
tripled call from the single one, would break on it. The fix is for priority to prefer
the **longest** matching priority phrase rather than the first one found.

## The measurement tool misreports this case

`phrase_separability.py` counts "matched a different intent" as a failure and prints
"Pick longer, less similar phrasings". Here the words were heard perfectly and the
routing was deliberate, so the advice was the opposite of what the data supported.

It needs to distinguish **"the recogniser heard the wrong words"** from **"the matcher
routed it elsewhere"** - the first is a phrasing problem, the second is ours. Until it
does, its verdict cannot be trusted for any candidate that overlaps an existing phrase,
which is precisely the case anyone would want to test.

There is a second blind spot behind it. The tool reads one recognition event at a time,
so it cannot see that two events were one intended utterance split by fast delivery -
which is what produced all three flagged lines. A run where the operator speaks quickly
will look like misrecognition when nothing was misrecognised. Printing the gap between
consecutive events would make that visible; without it, the tool needs the operator to
pause deliberately between repetitions for its output to mean anything.

## Implementation

**Built 2026-10-28, not yet flown.** Recommendations 0, 1, 2 and 5 are in, along with
both bugs this document exposed. Strict matching (3) was not built and is argued against
above; the confidence floor (4) was already dead.

This document is the measurement record. The work it recommends is planned in
[VOICE-COMMANDS-PLAN.md](VOICE-COMMANDS-PLAN.md), together with a Manager tab that lets a
player disable any command their own room sets off.

## What to measure next

Both baselines now exist: the false-positive rate, and that tripling is recognised
reliably. What is still unknown:

1. **Does dropping "pan pan" and making re-declaration a no-op actually stop it?** That
   is recommendations 0 and 1, and they are two one-liners. Measure the same way: jet
   running, typing, replies audible, Log tab open, ten minutes.
2. **Do the one-word cockpit commands leak the same way?** "flaps" and "canopy" are one
   word each, with the same exposure, and they move control surfaces. They carry their
   own higher confidence floor, but 0.92 medians suggest a floor is not much protection.
   Nothing in the logs so far shows one firing - but nothing has been looking for it
   either. Watch for them during the same ten minutes.

That second point may matter more than the mayday itself: the cockpit commands are newer,
equally short, and they act on the aircraft rather than on ATC.
