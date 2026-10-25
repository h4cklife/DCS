# Voice control of cockpit controls — design plan

**Status: built and verified in the cockpit, 2026-10-25.** Gear up and gear down were
confirmed both in the log and visually from an external view, and the ground refusal
held. Flaps, airbrake, canopy and navigation lights followed once chords were proven.

**DCS honours a modified chord.** That was the last unknown - single keys were proven by
the comms-menu work, chords only at the OS level.

Goal: say *"Chevy 81, gear up"* and have the landing gear retract, without taking a hand
off the stick. Same for flaps, airbrake, lights, canopy and brakes.

## How it will work, end to end

```
  you speak
      │
  recognize.ps1            Windows speech recognition, unchanged
      │
  atcai_listen.py          matches the phrase to an intent, e.g. cockpit_gear_up
      │
  atcai_cockpit.py         looks up the control, checks it is allowed right now
      │                    using the live state atc_state.lua publishes
      │
  atcai_sendkeys.py        holds LCtrl, taps G, releases LCtrl
      │                    (refuses unless DCS is the active window)
      ▼
   DCS
```

Nothing new reaches into the sim. The mission-side Lua stays read-only, exactly as it is
today; the keypress happens from outside, as it already does for the comms menu.

## Why this is easier than the comms menu — and why it is riskier

**Easier, because there is no state.** A cockpit binding is one chord, always.
`LCtrl+G` means gear up whatever else is happening. There is no menu level to track, no
normalisation, and nothing that renumbers when a wingman dies. The hardest problems in
`COMMS-KEYS-PLAN.md` simply do not exist here.

**Riskier, because the consequences are worse.** A wrong comms-menu press is recoverable
- you asked AWACS for the wrong thing. A wrong cockpit press may not be: jettisoned
stores, a shut-down engine, an ejection. And the phrases are adjacent in a way ATC
requests are not: **"gear up" and "gear down" differ by one word and have opposite
effects.** Mishearing "request taxi" as "request takeoff" gets you an odd reply;
mishearing "gear down" as "gear up" on short final does not.

Everything in the scope and safety sections below follows from that asymmetry.

## Where the key combinations come from

**Not from a table we maintain.** DCS already knows them, and the player may have
changed them.

Bindings live in Lua files that **execute** rather than being data:

```lua
-- Mods/aircraft/F-15C/Input/keyboard/default.lua
local res = external_profile("Config/Input/Aircrafts/base_keyboard_binding.lua")
ignore_features(res.keyCommands, {"dragchute", "shiptakeoff", "a2g"})
join(res.keyCommands, { ...aircraft-specific entries... })
```

So they are read by **running them on DCS's own `luae.exe` with `external_profile`,
`join`, `ignore_features`, `defaultDeviceAssignmentFor` and `_()` stubbed** - the same
technique the Lua test suites already use. Proven on 2026-10-25: the F-15C profile
executed cleanly and produced 375 key commands with their real names and combos.

```
  Landing Gear Up          LCtrl+G
  Landing Gear Down        LShift+G
  Canopy Open/Close        LCtrl+C
  Flaps Up/Down            F
```

This is deliberately *not* the regex approach `frequencies.py` uses for `Radio.lua`.
That file calls `require`, which cannot be stubbed usefully, so it had to be parsed.
These files run, so they should be run - executing them gets the semantics right,
including the `ignore_features` filtering and the aircraft-specific `join`.

### Three layers, in precedence order

| Layer | Path | What it is |
|---|---|---|
| Shared defaults | `Config/Input/Aircrafts/base_keyboard_binding.lua` | where gear, flaps and canopy actually live |
| Aircraft defaults | `Mods/aircraft/<A>/Input/keyboard/default.lua` | loads the above, filters it, adds its own |
| **The player's own changes** | `Saved Games/DCS/Config/Input/<A>/keyboard/*.diff.lua` | remappings, as `added` / `removed` per command |

**The third layer is why this must read real files rather than ship a table.** On this
machine the player has already remapped bank to rudder on the arrow keys and put radio
frequency on RCtrl+arrows. A hardcoded default table would be wrong for them on day one.

The diff file keys are opaque hashes (`d1741pnilunilcdnilvd0.1vpnilvu0`) but each entry
carries a readable `name`, so the layers are matched by name.

### What cannot be resolved

Some entries indirect through `defaultDeviceAssignmentFor("plane_gear")`, which resolves
against DCS's internal device tables. Those come back unresolved and are **skipped, not
guessed**. In practice this costs nothing: the toggles are the unresolvable ones, and
explicit `Landing Gear Up` / `Landing Gear Down` are better for voice anyway - a toggle
requires knowing the current state, which we cannot read.

## Scope: what is in, and what is deliberately left out

**In - reversible controls, where a mistake is an inconvenience:**

| Spoken | DCS command |
|---|---|
| "gear up" / "gear down" | Landing Gear Up / Down |
| "flaps up" / "flaps down" | Flaps Up / Landing Position |
| "airbrake out" / "airbrake in" | Air Brake On / Off |
| "canopy open" / "canopy close" | Canopy Open/Close |
| "lights on" / "lights off" | Navigation Lights |
| "wheel brakes on" / "off" | Wheel Brakes |

**Out - and out entirely, not merely gated:**

- **Eject.** No convenience justifies a voice command that can eject you.
- **Jettison** stores or fuel tanks.
- **Engine start and shutdown.**
- **Weapons release, master arm, countermeasures.**
- Anything whose name matches a configurable deny list, so a hand-edited map cannot
  quietly add one back.

"Out" rather than "gated" because a guard is a thing that can be got wrong, and the
failure is unrecoverable. A control that is absent cannot be mis-triggered.

## Safety design

1. **A deny list, enforced in code.** Controls whose DCS name matches the patterns above
   are refused even if a map names them. The map is data; this is not.
2. **A higher confidence threshold than ATC requests.** ATC runs at 0.6, which is right
   for a request that produces a spoken reply. A cockpit action gets its own, higher
   setting - the cost of a miss is retrying, the cost of a false positive is gear
   retracting on the runway.
3. **State conditions, reusing what exists.** `atc_state.lua` already publishes
   `onGround`, so `requires: ["onGround==0"]` refuses gear-up on the ground through
   machinery that is already built and tested.
4. **Opposite-action phrases must not be confusable.** "gear up" and "gear down" differ
   by one word, so the recogniser's own confidence is not enough on its own. Worth
   considering a longer required phrasing for these specifically - "gear coming up"
   versus "gear up" - and testing which the recogniser separates reliably.
5. **The foreground guard, already built.** Nothing is sent unless DCS is the active
   window, rechecked before every key.
6. **Off by default**, like the comms keys, with its own switch.

## How the Manager ties into DCS's keyboard controls

This is the part a player needs to understand, so it gets its own tab and its own
explanation in `GETTING-STARTED.md`.

**The Manager does not define key combinations. DCS does, and the Manager reads them.**

An **AI Cockpit** tab showing:

- **Enable cockpit commands** - off by default.
- **Aircraft** - detected from what the mission publishes, as the comms keys already do.
- **Controls found** - the list read out of DCS's own binding files, each with the combo
  it resolved to **and the phrases that trigger it**:
  `Landing Gear Up  →  LCtrl+G  →  "gear up", "gear coming up"`. This is the screen that
  answers both "what do I say" and "why did it press that", because it shows exactly
  what DCS told us alongside what you configured.
- **Re-read bindings** - for after changing a control in DCS's own options screen.
- **Confidence** - its own threshold, separate from ATC's.
- **A log** of every command: what was heard, which control it matched, which keys would
  be or were sent, and the reason for any refusal.

The documentation has to make three things unambiguous, because each has already caused
confusion in this project:

1. **If you rebind a control in DCS, press Re-read bindings.** The Manager reads the
   files at startup, not continuously.
2. **Which aircraft the bindings came from**, since they are per-module.
3. **That a control not in the list cannot be commanded** - and that this is the deny
   list working, not a bug, for anything on it.

## Architecture

### New files

| File | Job |
|---|---|
| `voice-bridge/readbindings.lua` | stubs + executes DCS's binding profiles, emits `BINDING\|name\|mods\|key` |
| `voice-bridge/atcai_bindings.py` | runs the above on `luae.exe`, applies the player's diff, caches the result |
| `voice-bridge/atcai_cockpit.py` | phrase → control → chord, deny list, state conditions |
| `voice-bridge/cockpit/controls.json` | which spoken phrases map to which DCS control *names* - not to keys. **One shared file, not one per aircraft** - see below |
| `tests/test_bindings.py`, `tests/test_cockpit.py` | parsing, deny list, conditions, refusals |

**The map holds DCS control names, not key combinations.** That is the whole point: the
keys come from DCS, so a player who rebinds gear to `K` needs no map change.

### One shared phrase file, unlike the comms keys

The comms-menu maps are per aircraft because the menu *trees* genuinely differ between
modules. Cockpit controls do not: "Landing Gear Up" is the same DCS control name in every
aircraft that has one, because it comes from the shared `base_keyboard_binding.lua`.

Per-aircraft phrase files would therefore duplicate identical content and drift apart.
**One `controls.json` is safe, because the binding lookup is already per aircraft:** if
an aircraft has no "Air Brake On" - the TF-51D does not - that control simply is not in
its bindings, and the command refuses itself with "this aircraft has no air brake". No
per-aircraft phrase list is needed to express that.

A per-aircraft override file remains possible later if some module turns out to need
different phrasing, but shipping one would be inventing a problem.

### Editing the phrases

Exactly as the comms keys work, because that pattern is now established and understood:

- The shipped file is compiled into the exe and copied to
  `%LOCALAPPDATA%\ATCAI\cockpit\controls.json` on first use, which is what gets read.
- Edits there survive updates; **Use shipped controls** restores the originals.
- **A player never rebuilds anything.** The exe is read-only internally, so the copy
  under `%LOCALAPPDATA%` is the one that counts. Edit it, restart listening, done - no
  Python, no repo, no build step. Rebuilding is only relevant to whoever edits the
  *source* copy, which is a developer concern.
- **Changing a phrase needs listening stopped and started**, not merely saved. The
  recogniser builds its grammar once when it starts, so a new phrase does not exist
  until it rebuilds. True however the file was edited.
- **The tab must name the folder it is reading from, and warn when the two copies
  differ**, exactly as the Comms Keys tab already does, with a reset button. This is a
  requirement, not a nicety: the two-copies arrangement has already caused real
  confusion once in this project, and one consistent explanation across both features is
  worth more than two half-remembered ones.
- The **AI Cockpit** tab shows each control's phrases **read-only**, next to the key
  combination DCS gave it:

```
  Landing Gear Up      LCtrl+G    "gear up", "gear coming up"
  Landing Gear Down    LShift+G   "gear down", "gear coming down"
  Flaps Up/Down        F          "flaps"
```

That one screen answers both questions a player actually has - *what do I say* and *what
will it press* - and it is the screen to look at when something presses the wrong thing.

Editing phrases **in** the tab was considered and deferred: it needs a table editor with
validation and save, which is a lot of GUI for something a text file already does, and
the file is the thing the documentation can point at. Showing them in the tab gets most
of the benefit for none of the cost.

### Changed files

| File | Change |
|---|---|
| `voice-bridge/atcai_sendkeys.py` | **chords** - hold modifiers, tap the key, release. Plus LShift/LCtrl/LAlt scan codes |
| `voice-bridge/atcai_listen.py` | route `cockpit_*` intents to the new module |
| `manager/app.py` | the AI Cockpit tab |
| `manager/prefs.py`, `manager/build_exe.py` | the new setting; bundle the new files |

`recognize.ps1` is untouched again.

## Phases

**A — Experiments. DONE, 2026-10-25.** All three answered before any feature code was
written: bindings can be read by executing DCS's own profiles, the player's remappings
match by name, chords hold at the OS level, and the short gear phrasings are separable.

Then: `readbindings.lua`, `atcai_bindings.py`, diff application, caching, tests. Output
only: a list of controls and their chords, shown in the Manager. **No key is sent, and no
phrase is recognised yet.** Zero risk.
*Decision point: does it find your real bindings, including your remappings?*

**B — Chords.** Teach `atcai_sendkeys.py` to hold modifiers. Prove it with the existing
Notepad test by typing a capital letter, which needs a held Shift.
*Decision point: do modified keys arrive correctly?*

**C — One control, airborne only. DONE, verified 2026-10-25.** `cockpit_gear_up` /
`cockpit_gear_down`, the deny list, the separate threshold, and the `onGround`
conditions.

*Decision point: does the gear actually move, and does gear-up refuse on the ground?*
**Both confirmed.** Dry run first showed the right chords; then for real:

```
~ "gear up"  -> cockpit_gear_up: not while you're on the ground
-> "gear up" (0.97) -> cockpit_gear_up | pressed: Landing Gear Up: LCtrl+G
-> "gear down" (0.95) -> cockpit_gear_down | pressed: Landing Gear Down: LShift+G
```

**D — The rest of the scope. DONE.** Flaps, airbrake in/out, canopy and navigation
lights, plus the AI Cockpit tab and documentation.

Control names were **read out of the bindings rather than guessed**, which mattered:
DCS spells it `Navigation lights` with a lowercase L and `Airbrake` as one word. A
guessed name is not an error - it simply never matches a binding and the command refuses
itself - so it would have failed quietly.

Two controls are toggles rather than explicit pairs, because a toggle is all DCS gives a
literal key for. That is acceptable only where the result is visible: **flaps and canopy
you can see; the gear you cannot reliably, which is why gear stayed explicit.**

**Wheel brakes were dropped** from the planned scope. DCS exposes them as separate
left/right on-off toggles, which reads badly as speech, and brakes are something you want
under your hand rather than your voice.

`cockpit_canopy` carries the mirror of the gear condition - `onGround==1`, refusing in
flight - because an open canopy at speed is its own kind of self-inflicted injury.

## Experiments

**1. Does the diff file apply cleanly by name? PASSED, 2026-10-25.** The diff keys are
opaque hashes but each entry carries a readable `name`, and all **6 of 6** of this
machine's real remappings matched their defaults by name:

```
MATCHED  Aircraft Bank Left     default=[<default:roll_left>]  removed=[Left]
MATCHED  Aircraft Rudder Left   default=[<default:rudder_left>]  added=[Left]
MATCHED  r.1 Frequency up       default=[]  added=[RCtrl+Up]
```

Note the third: a command with no default binding that the player added one to. So the
merge has to handle additions to empty as well as replacements.

**2. Does the recogniser reliably separate "gear up" from "gear down"? PASSED,
2026-10-25.** Twenty utterances, **zero confusions in either direction**, and nothing
matched a non-candidate:

```
gear down     9 utterances   min 0.95   mean 0.95
gear up      11 utterances   min 0.73   mean 0.92
```

Nineteen of twenty landed at 0.92 or above; a single "gear up" came in at 0.73. So the
short phrasings are safe and no longer, clumsier wording is needed.

**On the threshold.** The floor to guard is not "up versus down" - that was clean - but
some *unrelated* utterance being heard as a gear command. A margin just under the
observed floor (0.70) accepts everything seen here. A stricter 0.85 would have rejected
one correct command in twenty, costing a retry, in exchange for a much wider margin
against a false positive. Default 0.70 per the operator's stated preference, configurable,
with that trade written down so it can be revisited.

`tools/phrase_separability.py` remains for testing any future phrase pair:

```
python tools/phrase_separability.py "gear up" "gear down"
```

It tests the candidates **against the full real grammar**, not in isolation, because in
the air the recogniser is choosing between a hundred phrases and competition is what
causes confusion. It reports per-phrase confidence and, crucially, flags any utterance
that matched something *else* - a confident wrong answer being the dangerous case rather
than a low-confidence one.

**3. Do chords work when sent as scan codes? PASSED, 2026-10-25.** Reading Notepad was
abandoned as a check - the Store version exposes no classic edit control, and it only
reveals what one app made of the input. Asking Windows whether the key is actually held
tests the mechanism, and the OS keyboard state is what DirectInput reads:

```
modifier    before   while held   after release
LSHIFT      False    True         False
LCONTROL    False    True         False
LMENU       False    True         False
```

All three hold and release cleanly with a letter tapped in between. What this does *not*
prove is that DCS itself honours a modified chord - single keys were proven in the
cockpit, chords only at the OS level. That is Phase C's decision point.

## Testing

Everything up to the keypress is testable without DCS: binding execution on `luae.exe`
with fixtures, diff application, deny list, state conditions, chord construction against
a mocked `SendInput`. The deny list deserves adversarial tests - a map that tries to name
"Eject", one that names it with different capitalisation, one that reaches it through a
synonym.

What needs a flight: that the gear actually moves, and that gear-up refuses on the
ground. As with the comms keys, the dry run exists so the chords can be read and checked
before anything is pressed.

## How we decide it worked

Phase C succeeds if, in the cockpit, *"gear up"* retracts the gear and *"gear down"*
lowers it, **repeatably over ten attempts**, with gear-up refused while on the ground,
and with no misrecognition between the two in either direction. A single confusion
between up and down is a failure, not a tuning problem.
