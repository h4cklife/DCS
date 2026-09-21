# ATCAI — architecture and decisions

How ATCAI is built and why it's built that way. Written after the fact: everything here
describes what exists and ships in v1.2.0, not what is planned.

For the feature-by-feature state of the project see the status table in
[README.md](../README.md). For the manager app specifically see
[INSTALLER-PLAN.md](INSTALLER-PLAN.md).

Single-player DCS World addon: an air traffic controller players talk to by voice, which
answers out loud. Multiplayer is out of scope.

## The constraint everything else follows from

DCS runs mission scripts in a sandbox with **no file, socket or OS access**. That's
deliberate, and it applies to every DCS mod that talks to the outside world. Meanwhile
the things ATCAI needs — the microphone, speech synthesis, SRS — all live outside DCS.

So the shape of the project is fixed by one question: how does code outside DCS exchange
information with code inside a sandbox that can't open a file or a socket?

Three findings answer it, and all three were discovered the hard way:

**`dofile` survives sanitisation.** `MissionScripting.lua` strips `os`, `io`, `lfs`,
`require`, `loadlib` and `package` — but not `dofile` or `loadfile`. Mission Lua can
therefore read from disk indirectly: an external process writes a small Lua file, and the
mission `dofile`s it. No sandbox modification, no unsanitising, nothing for the user to
edit.

**`env.info()` reaches `dcs.log`.** Mission Lua can't write files, but anything it logs
lands in a file an external process can tail. That's the outbound channel.

**`a_do_script` works from a Hook; `a_do_script_file` does not.** Hook scripts run in
DCS's GUI Lua state (file access, no mission API); the mission runs in the sandbox
(mission API, no file access). `net.dostring_in("mission", ...)` bridges them — but drops
code into a *bare* state where `env`, `world` and `coalition` are all nil, so the code
must be handed to a function that executes inside the real sandboxed environment.
`a_do_script(<lua source>)` is that function. An earlier attempt used
`a_do_script_file(<path>)`, which reported success and silently did nothing — almost
certainly because "DO SCRIPT FILE" embeds scripts into the `.miz` as mission resources,
so it wants a resource key, not a filesystem path. That cost days of debugging, which is
why the injected Lua is now covered by tests that execute it against stand-in
`a_do_script`/`dofile` implementations.

## Architecture

```
  microphone                                    DCS
      |  (optional push-to-talk gate)             |
      v                                   Scripts/Hooks/atcai_autoload.lua
  Windows speech recognition                     |  (GUI Lua state: file access)
  (manager app, background thread)               |
      |                                          |  net.dostring_in -> a_do_script
      |  writes inbox.lua                        v
      +----------------------------> Scripts/ATCAI/*.lua
                (dofile poll,          (sandbox: Airbase/Unit/trigger API)
                 sequence-numbered)             |
                                                |  env.info("ATCAI_TTS|freqs|...")
  Windows TTS or SRS  <-------------------------+    replies on the field's own
  (manager app, tailing dcs.log)                     frequencies; the ATIS loop on
                                                     its own, once a minute
```

Nothing here needs Hooks *and* an unsanitised sandbox, or sockets, or a modified DCS
install. Everything ATCAI writes lives under `Saved Games\DCS`.

**Loading.** The hook injects a `dofile` chain into every mission as it starts, so ATCAI
is present in stock missions and campaigns with no mission editing. Scripts locate their
own directory via `debug.getinfo`, so they find their siblings and the inbox without the
mission having to inject absolute paths, and each is idempotent so double-loading is
harmless.

**Inbound.** The recogniser writes `ATCAI_INBOX = { seq = <epoch ms>, intent = "taxi" }`
atomically; a `timer.scheduleFunction` loop `dofile`s it inside `pcall` every 0.3s and
acts on any sequence number it hasn't seen. Epoch milliseconds keep rising across
restarts, and the sequence is primed from disk at mission start so a command left over
from a previous session can't fire on spawn.

**Outbound.** Replies are logged as `ATCAI_TTS|<freqs>|<modulations>|<text>` and spoken
either through Windows' own synthesiser (no dependencies) or SRS's `ExternalAudio` so it
arrives over the in-game radio.

## Components

- `lua/atc/` — the ATC itself. `atc_core.lua` holds the phase machine, phraseology and
  the wind/runway/weather/frequency logic; `atc_traffic.lua` decides who else is using
  the runway; `atc_atis.lua` repeats the field information on its own frequency;
  `atc_menu.lua` builds the comms menu and tracks which unit each player is flying;
  `atc_inbox.lua` polls for voice commands; `atc_config.lua` applies user settings over
  the defaults.
- `lua/hooks/atcai_autoload.lua` — loads all of the above into every mission.
- `voice-bridge/` — `atcai_listen.py` (speech recognition → inbox) and `atcai_tts.py`
  (dcs.log → speech). Both run as threads inside the manager, and standalone for
  development.
- `manager/` — the app users actually run: `installer.py` finds DCS and installs,
  `frequencies.py` reads real airfield frequencies out of the terrain files, `app.py` is
  the window, `prefs.py` remembers settings, `build_exe.py` packages it.
- `tests/` — pytest, including the Lua suites run on DCS's own interpreter.
- `tools/` — the Lua test suites themselves, plus `build_test_mission.py`, which makes a
  mission carrying ATCAI without the hook installed and can inject AI traffic at the
  player's airfield, and enemy ground targets around it, for testing and for fun.

  Everything it inserts is located by reading the mission's own structure rather than
  assuming a layout: an early version hardcoded the indentation of the group list, put
  AI flights in the country list instead, and silently deleted the player from the
  mission. Tests now assert the player survives.

## Decisions worth remembering

**Speech recognition uses Windows' built-in engine, not Vosk.** The original plan was
Vosk: a model download, extra packages, and no microphone access from WSL. Windows ships
an offline recogniser that needs none of that, and a *constrained grammar* built from the
known request phrases is far more accurate for radio calls than free dictation would be.
Wildcards either side of the request let you say anything around it.

**ATC replies are synthesised, not pre-recorded.** The original plan was a clip bank.
TTS handles variable runways, winds and altimeters without recording anything, and SRS
makes it arrive over the radio. `assets/audio/` is a leftover of the clip-bank plan and
is unused.

**Airfield frequencies are read from DCS, not hand-listed.** Every terrain ships
`Mods/terrains/<Terrain>/Radio.lua` with each field's real tower frequencies and
callsigns — the data DCS's own ATC menu displays. The mission sandbox can't read it
(the file calls `require`, which DCS strips), so the manager parses it at install time
and generates `frequencies.lua` for the mission to `dofile`. That works for any terrain
the player owns, with no per-terrain table to maintain.

**Settings live in a generated `config.lua`, not in the scripts.** The manager writes a
plain Lua table that `atc_config.lua` applies over the defaults, so the app never has to
parse or rewrite Lua source, and hand-edited scripts still work with no config present.

**Push-to-talk watches the key, rather than hooking the keyboard.** `GetAsyncKeyState`
sees the key even while DCS has focus, which a normal key handler would not. Recognition
only returns after you stop speaking, so the check isn't "is the key down now" but "was
it down during the utterance" — a watcher records when it was last held and a result
counts within a short grace period.

**The ATC core doesn't know voice exists.** Voice commands call the same `ATC.request*`
functions the comms menu does, so the menu keeps working and voice was additive rather
than a rewrite.

**An emergency is a flag on the aircraft's state, not a separate mode.** Declaring sets
`state.emergency`, and the existing request handlers consult it: landing skips the
traffic check entirely rather than being handed a softer one, and parking clears the
flag. Keeping it as state rather than a parallel set of handlers means an emergency
arrival still goes through the same clearance path as any other, so the two can't drift
apart.

**Distress calls bypass the range limit, and only they do.** `begin()` normally refuses a
request made outside ATC range, which is right for asking to taxi and wrong for a mayday.
Rather than lifting the limit, the emergency and vectors calls pass `anyDistance` and
fall back to the nearest field the player's coalition can use. Every other request keeps
the limit, and a test asserts that it does - the easy mistake here is relaxing the rule
for everyone while fixing it for one caller.

**A mayday outranks whatever else was said.** Voice matching normally takes the longest
phrase, which quietly resolved "mayday mayday, Chevy 81, request landing" to a routine
landing request - the calm half of a distress call winning because it happened to be
longer. `PRIORITY_INTENTS` returns the emergency regardless of length. This was found by
a test written to assert the intended behaviour, not by flying.

**A few replies transmit wide; most don't.** ATC normally answers on the field's own
frequency, which is the point of reading real frequencies out of the terrain. But the
calls that matter when you're away from a field - a refusal, a loadout check, an
emergency, a divert - were going out on the fallback list alone, and the fallback list
shares no frequency with any real field (Vaziani is on 269.0; the fallback list starts at
276.375). The result was a reply visible on screen and silent on the radio. Those calls
now transmit on the union of the field's frequencies and the fallback list.
`wideFrequencies` de-duplicates because SRS pairs the frequency and modulation lists by
position, so a repeat would shift them out of step.

This was invisible to the tests because they only ever asserted on the on-screen text,
which is written unconditionally. The suite now captures the `ATCAI_TTS` lines as well
and asserts which frequencies each reply actually goes out on - including that routine
clearances *stay* narrow, since making everything wide would quietly undo the
real-frequency feature.

**Diverts are coalition-filtered; ordinary clearances are not.** `findDivertField` skips
fields the player's side can't use, because sending a damaged aircraft to an enemy runway
is worse than sending it further. `findNearestAirbase`, which every routine request uses,
still answers from whichever field is closest - so in a combat mission an enemy tower will
clear you to land. That is a real gap rather than a decision, left alone here because
changing it alters the behaviour of every existing request and deserves its own change.

**A field that won't report its coalition is offered anyway.** `usableByCoalition`
defaults to true when `getCoalition` is missing or errors. Guessing wrong in that
direction offers a runway that might be hostile; guessing the other way withholds one
from a pilot who needs it.

## Still open

- **One ATIS channel, not one per field.** DCS's terrain data gives airfields only
  ground/tower/approach roles, so there is no per-field ATIS frequency to read. The
  looping broadcast therefore uses a single configurable frequency (380.000 AM by
  default, chosen to sit inside the UHF band aircraft can tune and clear of the
  frequencies terrains assign) and carries the information for whichever field the player
  is nearest.
- **No visibility or cloud in the ATIS.** The scripting API exposes wind, temperature and
  pressure, but not visibility or cloud cover.
- **Push-to-talk is Windows-only.** It watches the key with `GetAsyncKeyState` so it
  works while DCS has focus; there's no equivalent elsewhere, so the setting is ignored
  off Windows and listening stays continuous.
- **Transmitting isn't gated on the radio.** Output is frequency-correct - ATC replies on
  the field's own frequency, so you must be tuned in to hear it - but input isn't gated
  at all. Recognition happens in an external Windows process that has no access to the
  aircraft's radio, so a request is accepted on any frequency, or with the radio off.
  Push-to-talk gates the microphone, not the radio, which is why holding the key works
  regardless of what the radio is set to.

  **An earlier version of this note called closing the gap "cheap to do". That was
  wrong.** The mission scripting API does not expose the player's tuned frequency at all.
  `Unit` gives position, fuel, ammo and so on, but nothing about radio state, so there is
  no mission-side value to compare the field's frequency against. The only way to read it
  is DCS's **Export** layer - the same route SimpleRadio Standalone takes - which reaches
  into the cockpit device itself via `GetDevice()`.

  That makes it expensive for three reasons:

  1. **It is per aircraft module.** Every cockpit exposes its radios differently, with
     its own device ids and argument layout. SRS carries a separate integration per
     airframe, which is why its aircraft support is a list rather than a guarantee. ATCAI
     would need the same, and would work only for airframes someone had written up.
  2. **It is a new integration surface.** ATCAI currently touches no Export API
     whatsoever - the whole design runs on mission scripting plus a Hook. Adding an
     `Export.lua` path means a third execution context, its own install step, and its own
     conflict risk with other exporters the player already runs (SRS itself, TacView,
     streaming overlays), all of which chain through the same file.
  3. **The payoff is a refusal.** Success means ATC saying nothing when the radio is
     mis-set. That is more realistic, but it removes the ability to diagnose a problem by
     talking to ATC, which is exactly how ATCAI gets debugged.

  So if this is ever built it belongs behind an off-by-default "realistic radio" setting,
  scoped to whichever airframes are actually verified, and it should not be mistaken for
  a small job. The cheap approximation, if the realism matters more than the accuracy, is
  to gate on *something the sim does expose* - that the aircraft is powered and the
  player is in a cockpit rather than external view - which catches the "radio off" case
  without touching Export at all.
- **Ordinary clearances ignore coalition.** See the divert note above: routine requests
  answer from the nearest field regardless of whose it is. Fixing it means deciding what
  an enemy tower should do - stay silent, or refuse - and it changes every request, not
  just the new ones.
- **Bearings are true, not magnetic.** The scripting API exposes no magnetic variation,
  so headings given with vectors and emergency clearances are true bearings, while runway
  designators come from DCS already magnetic. On terrains with significant declination
  the two disagree by several degrees.
- **Taxiways and circuit direction.** DCS doesn't expose taxiway layouts, so instructions
  stay general and circuit joins don't specify left or right.
- **Multiplayer.** Voice commands are delivered to every registered player aircraft,
  which is correct for single-player and wrong for anything else.
