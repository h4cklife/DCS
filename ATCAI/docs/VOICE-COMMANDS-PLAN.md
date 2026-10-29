# Voice commands: false-trigger fixes, and making commands customisable — plan

Status: **built and tested 2026-10-28. Not yet flown.** Written and revised the same day;
implemented against the plan below with no changes to the design.

What is done: every step of Phases 1, 2 and 3, their tests (655 passing on Windows
Python, 539 on Linux where the GUI tests skip), and the documentation. `ATCAI/dist/`
holds the rebuilt manager.

**What remains is the measurement this whole exercise was for** - see "Then measure" at
the foot of this document. Ten minutes with the jet running, typing, replies audible and
the Log tab open answers the open question from
[FALSE-TRIGGERS-PLAN.md](FALSE-TRIGGERS-PLAN.md): do the changes actually stop it? And
watch for "flaps" and "canopy" in the same run, which nothing has ever looked for.

**First flight test, 2026-10-28: it found a bug that invalidated the run.** The ATC phrase
list resolved to the wrong folder inside the packaged exe, so it loaded empty and **no ATC
command existed in the recogniser's vocabulary at all**. The Log tab said "38 phrasings"
where it should have said 128; the missing 76 were every ATC request. Nothing about the
emergency changes was exercised. Fixed in 1.7.1, with a test that builds a fake extraction
folder from the packaging list and makes every module find its own bundled files there.

The run was not wasted, though. With the vocabulary accidentally cut to 38, three short
comms phrases absorbed background noise nine times and **pressed keys into DCS** - which
withdrew a claim this plan had made (see "What it is for" above) and exposed that
comms-menu commands had no confidence floor of their own despite pressing keys exactly as
cockpit commands do. Both addressed in 1.7.1.

Two things found during the build that the plan did not anticipate, both now done:

- **The comms menu had no way to cancel an emergency**, only to declare one. That matters
  more than it first looks: if the recogniser declares an emergency the pilot did not,
  the menu is the way out of it - including for someone who has switched the cancel
  command off, or who cannot speak over what is happening. Added, with a test.
- **The GUI tests would have written to the real `%LOCALAPPDATA%\ATCAI`** - a developer's
  own customisations - as soon as one toggled a command. The `gui` fixture now depends on
  a sandboxed overlay path, so no GUI test can reach the real file by omission.

Three phases that are all the same mechanism:

- **Phase 1** fixes the commands that misfired, as measured in
  [FALSE-TRIGGERS-PLAN.md](FALSE-TRIGGERS-PLAN.md).
- **Phase 2** moves phrases somewhere a player can own them, without losing shipped
  corrections.
- **Phase 3** puts a tab on top of that: enable, disable, and re-word any command.

Phase 1 picks the defaults everyone gets. Phases 2 and 3 let one player differ from them.

## The thing that makes this cheap

The recogniser's grammar is built **once**, when voice starts, in `phrase_to_intent()`
([atcai_listen.py:170](../voice-bridge/atcai_listen.py#L170)). Every phrase from all three
sources — ATC requests, comms-menu commands, cockpit controls — merges into one dictionary
there, and `run()` hands the keys to `recognize.ps1` as the grammar.

So "disabled" does not mean "recognised, then ignored." It means **the phrase is never in
the grammar**, and Windows has nothing to match the noise against. There is no confidence
check to tune and no wildcard to absorb a dog barking, because as far as the recogniser is
concerned the phrase does not exist.

That is the only form of disable that actually works. A post-recognition filter still lets
a one-word phrase soak up noise and still burns the recognition event. And the same
chokepoint is where a *renamed* phrase has to be applied, which is why disabling and
re-wording are one feature, not two.

## Phase 1 — the measured fixes

Six changes. The first four are the recommendation already agreed; the last two are bugs
the measurement exposed.

### 1.1 A repeat declaration becomes a no-op

`declareEmergency` in [atc_core.lua](../lua/atc/atc_core.lua) never checks whether an
emergency is already running. That is why 22 triggers produced 8 transmissions and a tower
that kept re-clearing you.

Guard it: if `ctx.state.emergency` is already set, return without transmitting. The
emergency stays declared — this suppresses the *noise*, not the emergency.

**The single highest-value fix.** Even with every false trigger left in place, one spurious
mayday would cost one transmission instead of a loop.

### 1.2 Drop "pan pan"

20 of the 22 false triggers, and ATCAI does not treat a pan-pan differently from a mayday,
so it buys nothing.

### 1.3 Drop bare "mayday" and "mayday mayday"; add "mayday mayday mayday"

The triple is **not in the list today** — it was only ever tested as a candidate. Phase 1
adds it and removes the two shorter forms in one edit. They have to move together: leaving
a shorter form in means the priority short-circuit (1.5) matches it first and the triple
never gets a chance, which is exactly what the test run showed.

Real procedure is to say it three times, so this is also the more correct phrasing.

The longer phrasings — "declare an emergency", "request emergency landing" — stay. They
never false-fired.

### 1.4 Add a cancel command

"cancel emergency", "cancel my emergency", "disregard my emergency" → clears
`ctx.state.emergency` and has the tower acknowledge.

Worth doing on its own merits: there is currently no way to un-declare, which is wrong even
when every declaration is deliberate.

### 1.5 Fix the `PRIORITY_INTENTS` short-circuit

[atcai_listen.py:255](../voice-bridge/atcai_listen.py#L255) returns the moment it sees any
priority phrase:

```python
if intent in PRIORITY_INTENTS:
    return intent
```

Two faults: it ignores longest-match **within** the priority intent, so a shorter emergency
phrase can beat a longer one; and because it scans a dict, which one it finds is
order-dependent.

Correct rule, and what the comment already claims: a priority intent beats a non-priority
one, and among priority matches the longest wins. A few lines, and it preserves the
behaviour the comment was written for ("mayday, Chevy 81, request landing" → the mayday).

### 1.6 Fix `tools/phrase_separability.py`

Two blind spots, both of which made it advise the opposite of its own data:

- It counts "the matcher routed this elsewhere" as misrecognition. Different problems — the
  second is a phrasing problem, the first is ours.
- It reads one recognition event at a time, so it cannot see that two events were one
  utterance split by fast delivery. That produced all three flagged lines in the last run.
  Printing the gap between consecutive events makes it visible.

Until both are fixed its verdict cannot be trusted for any candidate that overlaps an
existing phrase — which is every candidate worth testing.

### Not doing: strict matching

Argued against in FALSE-TRIGGERS-PLAN.md: it would reject a real mayday spoken fast, which
is how a real mayday is spoken.

## Phase 2 — where phrases live

### The problem to avoid

The obvious way to make phrases editable is to ship a JSON file and copy it into
`%LOCALAPPDATA%` on first run, the way key maps and cockpit controls work. That has a flaw
this project has already hit. From `stale_user_keymaps`
([atcai_keys.py:124](../voice-bridge/atcai_keys.py#L124)):

> Reported rather than acted on: a difference is usually the player's own edit, which must
> be left alone. It only matters because it means a shipped correction is not in effect.

It can only *detect* drift, never resolve it, because once the user's copy is the whole
list, "your edit" and "the old default" are the same bytes in the same place. So if 1.8
adds a weather request, or fixes a phrase that turns out to false-fire, anyone who has
touched their copy silently does not get it.

### The fix: defaults and changes in different files

Keep them as separate data, and the ambiguity disappears.

**Defaults — bundled, read-only, never seeded.** `voice-bridge/phrases/atc_defaults.json`,
holding what `INTENT_PHRASES` holds today. This is the "preparation for ATC phrase text":
the list stops being Python, becomes readable and diff-able, and is symmetric with the
comms and cockpit maps. Nothing ever writes to it, so it is always the running release's
own list and there is nothing to go stale.

**Changes — one writable file.** `%LOCALAPPDATA%\ATCAI\phrases.json`, holding *only* what
you have changed:

```json
{
  "version": 1,
  "commands": {
    "taxi":      { "add": ["ready to roll"], "remove": ["ready to taxi"] },
    "emergency": { "enabled": false },
    "atis":      { "enabled": true, "add": ["weather please"] }
  }
}
```

A command you have never touched does not appear, and gets its shipped defaults. That makes
staleness **structurally impossible** rather than merely detected: a new release's new
commands and corrected phrasings arrive intact, because your file never claimed to be the
whole list.

`version` is there so a later format change can migrate instead of guess.

### Why this is one feature and not two

The overlay is the reason disabling and re-wording collapse into one mechanism:

| What you do in the tab | What lands in the file |
|---|---|
| Switch a command off | `"enabled": false` |
| Delete one phrasing | `"remove": [...]` |
| Change a phrasing | `"remove"` the old, `"add"` the new |
| Add your own phrasing | `"add": [...]` |
| Restore defaults | the command's entry is deleted |

"Restore defaults" being a *deletion* is what makes it trivially correct — there is no
remembered original to get wrong.

This replaces the two `manager.json` keys the earlier draft proposed. All phrase and
command customisation lives in one file; `manager.json` keeps app preferences only.

### How it is wired

A new module, `voice-bridge/atcai_phrases.py`, owns all of it: reading the defaults,
reading and writing the overlay, merging, and validating. `phrase_to_intent()` asks it for
the effective list instead of reading `INTENT_PHRASES`; the Manager asks the same module
and writes through it.

**One implementation, two callers.** Two readers of the same format is how formats drift,
and the Manager and the listener must agree exactly or the tab shows something other than
what the recogniser hears.

Order matters in one place: the overlay applies **after** all three sources merge, keyed by
intent. So it covers comms and cockpit phrases too, without the tab having to decide which
of four aircraft key maps to write to — a comms phrase can be defined in all of them at
once, and intents are global where files are not. Hand-editing a key map still works for
anyone who prefers it; the overlay simply wins.

### Two guards

**An empty grammar.** Disable everything and `spec["requests"]` is an empty list, which
`recognize.ps1` has never been handed. `run()` should check: if the effective lookup is
empty, log "every voice command is disabled — nothing to listen for" and return without
starting. A clear refusal beats finding out. The check belongs in `run()` and not only in
the tab, because the file is hand-editable.

**A malformed overlay.** Same rule as `prefs.load`: anything unrecognised or invalid is
dropped with a note, never fatal. A bad `phrases.json` must not stop voice working, it
must fall back to defaults and say so in the Log tab.

### The property that keeps this safe

**The overlay can change the words for a command that exists; it cannot create a command.**
An unknown intent name in the file is ignored.

That is worth stating because it bounds the whole feature. `atcai_cockpit.DENY_PATTERNS`
blocks eject, jettison, engine shutdown, master arm, weapons and countermeasures by
*control name*, before anything else is considered. No amount of phrase editing can reach
them, because there is no command there to re-word. Phrase editing changes what you say,
never what gets pressed.

## Phase 3 — the Voice Commands tab

### What it is for

Phase 1 picks defaults for everybody. It cannot know that your neighbour's dog says
"flaps", that a TV in the next room says "taxi", or that you would rather say "wheels up"
than "landing gear up". The player's room and the player's habits are the two things we
cannot measure from here, so the player gets the switch and the text box.

~~Switching off whole sources also shrinks the grammar, which makes everything left
slightly more reliable — fewer things to confuse.~~

**Withdrawn 2026-10-28**, the same day, by the first session that could test it. Written
as though established, on no evidence at all. At 38 phrases instead of 128 — the
accidental experiment created by the `_MEIPASS` bug below — three short comms phrases
absorbed background noise nine times in one session. Windows returns the best match among
what is in the grammar, so removing competitors can **concentrate** noise on the survivors
rather than dilute it.

Not disproven either: one run, with music and a door opening in it. Treat vocabulary size
as unmeasured, and do not sell shrinking it as a benefit.

### What you see

A new tab, **Voice Commands**, after "AI Cockpit". Three groups, matching the three
sources:

```
Voice Commands                             [ Enable all ]  [ Restore all defaults ]

ATC requests
  [x] taxi                 request taxi · request taxi clearance · ready to taxi     [ Edit ]
  [x] emergency            mayday mayday mayday · declare an emergency · ...         [ Edit ]
      ...
Comms menu  (currently off — enable on the Comms Keys tab)
  [x] awacs_picture        picture · request picture                                 [ Edit ]
      ...
Cockpit controls  (currently off — enable on the AI Cockpit tab)
  [x] cockpit_gear_up      landing gear up · gear up                                 [ Edit ]
      ...

  12 ATC · 11 comms · 7 cockpit commands · 2 disabled · 3 edited
  Changes take effect when you next start listening.      [ Restart listening ]
```

A checkbox per command with its effective phrases beside it, so you can see what you are
switching off. **Edit** opens the phrase editor for that one command: its phrases as a
list, each removable, plus a box to add one, plus **Restore defaults** for that command.
Edited commands are marked in the list so you can tell at a glance what you have changed.

Group headers say plainly when a whole source is switched off elsewhere, because otherwise
"why isn't my cockpit command working" has two answers in two different tabs.

### The editor's checks

This is the part worth getting right. A free-text phrase box is a footgun, and the
measured history of this project says exactly which ways.

Normalise first — lowercase and collapse whitespace, matching what `phrase_to_intent` does
— then:

**Refuse, with the reason:**
- Empty, or anything but letters, digits and spaces. The grammar takes words; punctuation
  is at best ignored and at worst breaks the build.
- A phrase that already belongs to a **different** command, naming which one. This is the
  collision `phrase_to_intent` currently logs at startup and then silently drops — catching
  it in the editor, where the person can fix it, is strictly better than reporting it in a
  log after the fact.

**Warn, but allow:**
- **One word, or shorter than about eight characters.** This is the shape that caused the
  mayday investigation, and the warning should say so rather than just "short phrase". The
  player should be able to make that trade knowingly; what they should not do is make it
  unknowingly.
- A phrase that **contains, or is contained by**, another phrase. Longest-match makes one of
  them unreachable in some utterances. A warning and not a refusal, because
  "request taxi" / "request taxi clearance" is a legitimate pair that ships today.

**Collapse quietly:** a leading-verb variant of a phrase that already exists.
`expand_phrases` generates "requesting taxi" from "request taxi" already, so adding it by
hand is a no-op — say so instead of storing a duplicate.

### Non-goals, deliberately

**No key or sequence editing.** The tab changes what you *say*. What gets *pressed* —
comms key sequences, cockpit control names, their conditions — stays in the key maps and
`controls.json`. Different risk, different file, and the keys were verified by dry run
against DCS rather than typed into a box.

**No phrase tester in this tab.** The Test Microphone tab already shows recognitions *and*
rejections live. The path is: edit, restart listening, say it on the Test Microphone tab.
Building a second recogniser harness here would duplicate that, and
`tools/phrase_separability.py` already exists for measuring a candidate properly once 1.6
makes its output trustworthy.

## Order of work, and what to test

Phase 1 first — six small edits, and it is what the measurement supports. Phase 2 next,
since Phase 3 is a view onto it. Phase 3 last.

| Step | Change | Test |
|---|---|---|
| 1.1 | `declareEmergency` no-op on repeat | `test_lua.py` — declare twice, assert one transmission |
| 1.2-1.3 | emergency phrase list | `test_voice_bridge.py` — "pan pan" matches nothing; triple matches `emergency` |
| 1.4 | cancel command | `test_lua.py` — declare, cancel, assert state cleared and tower acknowledges |
| 1.5 | priority longest-match | `test_voice_bridge.py` — triple beats a contained shorter form; priority still beats a longer non-priority phrase |
| 1.6 | separability tool | no test (a tool, not shipped) — verify by re-running it |
| 2.1 | `atc_defaults.json` + `atcai_phrases.py` | new `test_phrases.py` — the JSON reproduces today's `INTENT_PHRASES` exactly, so the move changes nothing |
| 2.2 | overlay merge | `test_phrases.py` — add, remove, disable, unknown intent ignored, malformed file falls back to defaults |
| 2.3 | bundling | existing `test_wiring.py` catches it automatically: it walks `voice-bridge/` and fails on any non-Python entry missing from `BUNDLED` |
| 2.4 | filtering in `phrase_to_intent` | `test_voice_bridge.py` — disabled command gone with its verb variants; removed phrase gone, siblings kept; empty-grammar refusal |
| 3.1 | editor validation | `test_phrases.py` — each refusal and each warning, as plain functions with no GUI |
| 3.2 | the tab | `test_gui.py` — tab exists, checkboxes and phrase lists reflect the overlay, edits write it, restore deletes the entry |
| 3.3 | docs | `ATCAI/README.md` voice-command table notes the tab and the overlay file; `GETTING-STARTED.md` covers it for noisy rooms; bundled-files list gains `phrases/` |

Validation lives in `atcai_phrases.py` as plain functions, not in the GUI, so 3.1 is a
normal unit test and the same checks apply to a hand-edited file.

**Then measure.** The same ten minutes as before — jet running, typing, replies audible,
Log tab open. That answers the open question from FALSE-TRIGGERS-PLAN.md: does dropping
"pan pan" and the no-op actually stop it? And watch for "flaps" and "canopy" in the same
run, which has never been looked for.
