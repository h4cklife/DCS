# AI ATC Module — Design Plan

Single-player DCS World addon: an AI air traffic controller players can talk to by voice
for radio checks, taxi/takeoff clearance, and loadout callouts. Multiplayer is explicitly
out of scope for now.

## Architecture

Two processes, one bridge:

```
[Player mic]
     |
     v
+-------------------------+      commands       +---------------------------+
| voice-bridge/ (Python)  | -------------------> | lua/ (DCS mission/export) |
| Vosk offline STT        |   file or socket     | ATC state machine          |
| phrase -> command parse |                      | Airbase/Unit API queries   |
+-------------------------+ <------------------- | radio/text responses       |
     ^                         status/TTS text    +---------------------------+
     |                                                       |
     +--- (optional) TTS playback for ATC voice lines <------+
```

DCS's mission-scripting Lua sandbox has no file/socket/OS access by default. This is
intentional (security) and shared by every DCS scripting mod that talks to the outside
world (VAICOM, MOOSE, SimShaker, hardware cockpit integrations). Two ways around it,
to decide between when we build:

1. **Export.lua environment** — already less sandboxed, designed for external I/O.
   Preferred if the ATC only needs to *read* state and *send* responses out, since it
   runs alongside the mission rather than inside it.
2. **Unsanitized MissionScripting.lua** — edit the two `sanitizeModule` lines DCS ships
   with, to allow `io`/`lfs`/`socket` inside mission scripts. Needed if the ATC logic
   has to directly call mission-side APIs like `Airbase.getParking()` or
   `trigger.action.radioTransmission()` from the same script that talks to Python.

**Attempted, currently parked (not working):** a Hooks script
(`lua/hooks/atcai_autoload.lua`) was meant to avoid per-mission setup by using
`net.dostring_in` on mission load. Findings:

- Raw `net.dostring_in("mission", <code>)` does not run in DCS's real sandboxed mission
  environment — `env`, `world`, etc. are nil there.
- Routing through `a_do_script_file(path)` (same call the Mission Editor's own "DO
  SCRIPT FILE" trigger action makes) reports success but the target file still never
  actually executes, from either `onMissionLoadEnd` or `onSimulationStart` — root cause
  not yet found. See README.md's "Parked: Hooks-based autoloader" section for details
  and the next diagnostic step if this gets picked back up.

**Current approach — and the bridge solution.** Two findings closed this out:

- **Inbound (external → DCS):** `MissionScripting.lua` sanitizes only
  `os`/`io`/`lfs`/`require`/`loadlib`/`package` — **`dofile` survives**. So mission Lua
  can read from disk after all, indirectly: an external process writes a small Lua file,
  and a `timer.scheduleFunction` loop `dofile`s it (in `pcall`) to pick up commands. A
  sequence number keeps commands from being replayed. This is also how the scripts
  themselves load (a mission-start trigger running `a_do_script` + `dofile`), which is
  what `tools/build_test_mission.py` injects.
- **Outbound (DCS → external):** mission Lua can't write files, but `env.info()` reaches
  `dcs.log`, which any external process can tail. This is live and in use by
  `voice-bridge/atcai_tts.py` for SRS text-to-speech.

Neither needs Hooks, sockets, or an unsanitized sandbox.

## Components

- `lua/atc/` — the ATC logic itself: per-airbase state machine (idle → radio check →
  taxi clearance → hold short → takeoff clearance → handoff), Airbase/Unit API queries
  (parking, runways, loadout via `Unit:getAmmo()`), response generation.
- `lua/hooks/` — DCS Hook/Export scripts responsible only for the bridge: reading
  commands from the voice-bridge process, handing them to `lua/atc/`, sending responses
  back out (text and/or audio trigger).
- `voice-bridge/` — Python process: mic capture, Vosk offline speech-to-text, command
  phrase parsing (callsign + intent, e.g. "Viper one one, request taxi"), writes parsed
  commands for the DCS side to pick up.
- `assets/audio/` — pre-recorded or TTS-generated ATC voice lines, if we go that route
  instead of/alongside text responses.
- `docs/` — design notes, open questions, DCS API reference snippets as we accumulate
  them.

## Phased build order

1. **Lua ATC core, F10-menu-driven** — build and test the state machine and
   Airbase/Unit queries using the existing F10 radio menu as input, no voice yet. Gives
   a working, testable core before the harder bridge/voice piece.
2. **Bridge** — outbound (dcs.log tailing) is built and in use. Inbound (Lua inbox file
   + `dofile` poll loop) is designed but not yet built; it's the remaining prerequisite
   for voice input.
3. **Voice input** — Vosk integration, phrase parsing into commands written to the
   inbox file, so the ATC core's `ATC.request*` functions stay unchanged.
4. **Audio responses** — done via SRS text-to-speech
   (`voice-bridge/atcai_tts.py`), which replaced the original pre-recorded-clip plan.

## Proposed next: one-click installation

Installing ATCAI currently means copying Lua files, running a build script with absolute
paths, launching two Python processes by hand, and editing Lua source to change a
setting. [INSTALLER-PLAN.md](INSTALLER-PLAN.md) proposes a single cross-platform program
that does all of it — install/remove, enable/disable, settings, and running the voice
bridges — and identifies the one unanswered technical question (can a Hook script load
ATCAI into *any* mission?) that decides its shape. Proposal only; not started.

## Open decisions (revisit before coding starts)

- Per-airbase ATC frequencies — the scripting API doesn't expose them, so ATC currently
  transmits on one fixed frequency. Would need a per-terrain lookup table to fix.
- Recorded audio clips vs TTS for ATC responses.
- Which airbases/aircraft to target first for testing.
