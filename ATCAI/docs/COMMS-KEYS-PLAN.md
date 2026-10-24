# Voice control of DCS's own comms menus — design plan

**Status: proposed, not built.** Written for review before any code exists. Intended to
live on a branch (`comms-keys`) that can be deleted without trace if it doesn't work out.

Goal: say *"Two, rejoin"* or *"AWACS, picture"* and have it happen, without taking a hand
off the stick to dive through the comms menu.

## Why this needs its own plan

Everything ATCAI does today is either a **read** of the mission world or a message to the
player. It cannot break a mission, which is why the Hook loads it into every mission with
no setup — see *Possible, and deliberately not done* in [PLAN.md](PLAN.md).

This feature is different in kind. It **writes to the game**, by sending keystrokes to the
DCS window from outside the sim. It cannot corrupt mission state the way `setUserFlag`
could, but it can make your wingmen do things, and that affects mission outcomes.

The accepted trade, stated plainly: **this is a single-player module, and the worst
realistic failure is that a command doesn't land and the player uses the comms menu by
hand.** That is a tolerable failure. The plan is built around making it the *only* likely
failure.

## The two things that make it possible

**1. Mission scripting cannot touch the comms menu — but it can see everything that
shapes it.** `missionCommands` only adds and removes ATCAI's own entries; the engine's
tree is not exposed, to scripting or to the Export API. There is no enumerate. But every
condition that changes the tree is readable, and ATCAI already makes each of these calls:

| What varies the menu | Call | Already used in |
|---|---|---|
| Aircraft type | `unit:getTypeName()` | `atc_traffic.lua` |
| AI wingmen, and how many | `getGroup():getUnits()` + `getPlayerName()` | `atc_menu.lua` |
| Ground crew entries present | `unit:inAir()` | `atc_core.lua` |
| AWACS or tanker alive and near | `ATC.aircraftNear()` | `atc_traffic.lua` |

**2. The voice bridge already runs outside DCS**, and already talks to the Windows API
(`GetAsyncKeyState` for push-to-talk). Sending keys is the same kind of call in the other
direction.

So the design is: **the mission side publishes the situation; the outside side chooses the
key sequence for that situation.** No screen reading, no guessing.

## Architecture

```
  you speak
      |
  atcai_listen.py  ---- ATC intent (taxi, mayday, ...) ----> inbox.lua  (unchanged)
      |
      \---- comms intent (flight_rejoin, awacs_picture) ----> atcai_keys.py
                                                                  |
                                          reads: live state + aircraft key map
                                                                  |
                                          guard: is DCS the foreground window?
                                                                  |
                                                            SendInput
```

And in the other direction, over the channel spoken replies already use:

```
  atc_state.lua  --env.info-->  dcs.log  --tailed by-->  atcai_listen.py
  ATCAI_STATE|aircraft=F-15C|wingmen=3|onGround=0|awacs=1|tanker=0
```

Nothing in the existing recognition or ATC path changes. `recognize.ps1` is untouched.

### New files

| File | Job |
|---|---|
| `lua/atc/atc_state.lua` | Publishes `ATCAI_STATE` on a timer. Read-only, ~60 lines. |
| `voice-bridge/atcai_keys.py` | Resolves an intent + state to a key sequence, sends it. |
| `voice-bridge/keymaps/<aircraft>.json` | One data file per aircraft. No code. |
| `tests/test_keys.py` | Map parsing, condition matching, sequence resolution, guards. |

### Changed files

| File | Change |
|---|---|
| `voice-bridge/atcai_listen.py` | Split dispatch: ATC intents to the inbox, comms intents to `atcai_keys`. Tail `dcs.log` for `ATCAI_STATE`. |
| `lua/hooks/atcai_autoload.lua` | Add `atc_state.lua` to the file list. |
| `manager/installer.py` | Add it to `SCRIPT_FILES`. |
| `manager/app.py` | A "Comms keys" tab: on/off, aircraft status, dry-run, test button. |
| `manager/build_exe.py` | Bundle the keymaps directory. |

## Aircraft maps are data, not code

Adding a module you've just bought must not mean writing Python or rebuilding the exe.
One JSON file per aircraft, keyed by the exact DCS `typeName`:

```json
{
  "aircraft": "F-15C",
  "comms_key": "backslash",
  "delay_ms": 90,
  "commands": {
    "flight_rejoin":   { "keys": ["comms", "F1", "F1", "F1"], "requires": ["wingmen>=1"] },
    "flight_engage":   { "keys": ["comms", "F1", "F2", "F1"], "requires": ["wingmen>=1"] },
    "flight_rtb":      { "keys": ["comms", "F1", "F4", "F1"], "requires": ["wingmen>=1"] },
    "awacs_picture":   { "keys": ["comms", "F6", "F1"],       "requires": ["awacs"] },
    "awacs_bogey_dope":{ "keys": ["comms", "F6", "F2"],       "requires": ["awacs"] }
  }
}
```

- `requires` is checked against the published state. A command whose conditions aren't met
  is **refused with a spoken reason**, not fired blindly — "no wingmen" is a better
  outcome than pressing F1 into whatever occupies that slot single-ship.
- `delay_ms` is per aircraft because menu responsiveness varies.
- Unknown aircraft means no map, which means the feature stays quiet for that airframe
  rather than guessing. The Manager says so.

**The sequences above are placeholders.** Establishing the real trees per aircraft is part
of the work, done with dry-run mode (below) rather than by firing keys and seeing what
breaks.

## Keystrokes: the mechanics that actually matter

- **Scan codes, not virtual keys.** DCS reads the keyboard through DirectInput, which
  commonly ignores virtual-key `SendInput`. Sequences must be sent with
  `KEYEVENTF_SCANCODE`. This is the single most likely reason a first attempt appears to
  do nothing, and it is worth proving before anything else.
- **Foreground guard, mandatory.** `GetForegroundWindow` plus `GetWindowThreadProcessId`,
  compared against the DCS process. If DCS is not focused, **send nothing** and say so.
  Without this, a misfire types into whatever window is focused — a browser, an editor,
  a Discord message box. This is the one failure mode that could do real harm outside the
  game, and it is fully preventable.
- **Aircraft match, mandatory.** If the published aircraft has no map, refuse.
- **Menu reset is an open question.** Ideally each sequence starts from a known root. It
  is not yet established whether re-pressing the comms key reliably returns to the top, or
  whether Escape is safe (Escape with no comms menu open may open the game menu). Until
  settled, sequences assume **no menu currently open**, and a failed command is retried by
  the player. See *Experiments* below.

## Manager UI

A new **Comms keys** tab, following the Test Microphone pattern:

- **Enable comms key commands** — off by default.
- **Aircraft**: what the mission last reported, and whether a map exists for it. Auto-
  detected via `getTypeName()`; a manual override for when detection is wrong.
- **Dry run** — recognise, resolve, and log the sequence *without sending it*. The default
  while mapping a new aircraft.
- **Test keys** — send a harmless sequence to Notepad rather than DCS, to prove keystrokes
  are being delivered at all. This separates "keys don't work" from "the map is wrong",
  which are otherwise indistinguishable.
- Live log of every resolution: intent, state, chosen sequence, and whether it was sent,
  refused, or dry-run.

## Testing

The hard part is that the feature has **no feedback**: nothing tells us the keypress did
what we wanted. So the testable surface is everything up to the send, and the send itself
is mocked.

Unit tests, no DCS and no keyboard needed:

- Map files parse; a malformed map is reported, not crashed on.
- `ATCAI_STATE` parsing, including missing and junk fields.
- Condition evaluation: `wingmen>=1`, `awacs`, `onGround` — true, false, and absent.
- Sequence resolution: right sequence for the right aircraft and state.
- **Refusals**: unknown aircraft, unmet `requires`, DCS not foreground, feature disabled.
  Each must refuse *and say why*.
- The exact scancode sequence and inter-key delays handed to a mocked `SendInput`.
- Dry run sends nothing — asserted against the mock.

GUI tests for the tab, as with Test Microphone. Manual verification is the last step and
is explicitly a fly-test, not a substitute for the above.

## Phases, and where the branch can be abandoned

**A — State and dry run.** `atc_state.lua`, state tailing, map format, resolution,
refusals, dry-run logging, tests. **No key is ever sent.** Zero risk to anything.
*Decision point: does the bridge correctly know what aircraft, wingmen and AWACS you have,
and pick sensibly?* If not, stop here having touched nothing.

**B — Prove keystrokes reach DCS.** Scancode `SendInput`, foreground guard, the Notepad
test. One aircraft (F-15C), two commands (`awacs_picture`, `flight_rejoin`).
*Decision point: do the keys land in the cockpit and do the right thing?* **This is where
the branch lives or dies.** If DirectInput won't take synthetic input, delete the branch —
the plan above is sound but the foundation isn't there, and no amount of design fixes it.

**C — Make it usable.** Manager tab, off-by-default wiring, maps for the modules you own,
documentation including a plain statement that it can affect mission outcomes.

**D — Optional, later.** Crude confirmation: after `flight_rejoin`, watch the wingman's
heading and speed and report "acknowledged" if it changed. Read-only. Probably
over-engineering, and the only honest way to close the loop.

## Experiments to run before writing much

1. **Does DCS accept synthetic scancode input at all?** Send the comms key alone and see
   if the menu opens. Everything depends on this; it should be question one.
2. **What safely returns the menu to its root?** Comms key again, Escape, or nothing.
   Determines whether sequences can be self-normalising.
3. **Is the top-level tree stable across your aircraft?** Compare F-15C and whatever else
   you own, single-ship versus with wingmen, airborne versus on the ground.

## What this will not do

- Work in multiplayer against other human clients.
- Confirm a command was carried out (except the optional Phase D heuristic).
- Cover aircraft with no map — it stays silent rather than guessing.
- Survive DCS moving menu entries in a patch without the map being updated.
- Touch the built-in ATC, which remains unreachable by any route.

## How we decide it worked

Phase B succeeds if, in the cockpit, *"AWACS, picture"* produces the AWACS picture call
and *"Two, rejoin"* makes the wingman rejoin, **repeatably**, across at least ten
attempts, with no stray keystrokes reaching other windows. Anything less than repeatable
is a no: an unreliable voice command is worse than no voice command, because you have to
check whether it worked before you can rely on it.
