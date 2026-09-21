# ATCAI

[![ATCAI build](https://img.shields.io/github/actions/workflow/status/h4cklife/DCS/atcai-ci.yml?branch=main&label=build&logo=github)](https://github.com/h4cklife/DCS/actions/workflows/atcai-ci.yml)
[![Latest release](https://img.shields.io/github/v/release/h4cklife/DCS?filter=atcai-v*&label=release)](https://github.com/h4cklife/DCS/releases)
[![Downloads](https://img.shields.io/github/downloads/h4cklife/DCS/total?label=downloads)](https://github.com/h4cklife/DCS/releases)
[![Licence](https://img.shields.io/github/license/h4cklife/DCS)](../LICENSE)
[![Tests](https://img.shields.io/badge/tests-243-brightgreen)](#tests)
![Platform](https://img.shields.io/badge/platform-Windows-0078d4?logo=windows)
![DCS World](https://img.shields.io/badge/DCS%20World-single--player-2ea44f)
![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?logo=python&logoColor=white)
[![Bitcoin](https://img.shields.io/badge/Bitcoin-donate-f7931a?logo=bitcoin&logoColor=white)](#support-the-project)
[![Ethereum](https://img.shields.io/badge/Ethereum-donate-3c3c3d?logo=ethereum&logoColor=white)](#support-the-project)

An AI air traffic controller for DCS World single-player: startup, taxi, takeoff,
circuit joins, landing and loadout callouts. You can talk to it and it talks back —
speech recognition for your requests, text-to-speech for ATC's replies — or drive the
whole thing from the in-game comms menu instead.

**Just want to use it?** Read [GETTING-STARTED.md](GETTING-STARTED.md) instead — this
file is about how it works and how to develop it.

**A note on DCS terminology:** what the community calls the "F10 menu" is not opened
with the literal F10 key — F10 is bound to the map view. The comms menu's default key
is **`\`** (backslash). This trips up a lot of people the first time; see "Test / run for
actual gameplay" below for exact navigation.

Not built for multiplayer. See [docs/PLAN.md](docs/PLAN.md) for the full architecture
and roadmap.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Lua ATC core, comms-menu input | **Done** — verified in-game |
| 2 | Bridge (external process \<-> DCS) | **Done** — outbound via dcs.log, inbound via a Lua inbox file polled with `dofile` |
| 3 | Voice input | **Done** — verified in-game, Windows offline speech recognition |
| 4 | Spoken ATC replies (SRS TTS, or local Windows TTS) | **Done** — verified in-game, both `--mode srs` and `--mode local` audible |
| 5 | Richer ATC behaviour — wind-selected runway, live weather, phase enforcement, arrivals | **Done** — verified in-game |
| 6 | Traffic awareness — holds, sequencing, go-arounds | **Done** — verified in-game against AI traffic |
| 7 | Loads into every mission automatically | **Done** — verified in a stock mission |
| 8 | Settings file, so nothing needs Lua editing | **Done** |
| 9 | Installer core (detect DCS, install/remove/enable/disable/settings) | **Done** — `manager/installer.py` |
| 10 | Manager app + single-file .exe | **Done** — `ATCAI-Manager.exe`, GUI verified on Windows |
| 11 | Release readiness — remembered settings, player guide, clean-install testing | **Done** — v1.0.0 published; the released .exe installed from scratch and flown |
| 12 | Real radio — per-airfield frequencies, ATIS on request and on a loop | **Done** — verified in-game, frequencies and the ATIS loop both |
| 13 | Push-to-talk, configurable in the manager | **Done** — verified in-game; off by default, key chosen in the app |
| 14 | Verify traffic awareness in flight | **Done** — flown against `--traffic` AI using the player's field |
| 15 | Emergency and divert handling — mayday, vectors home, straight-in | **Done** — verified in-game |

ATCAI loads into **every mission you fly** — stock missions, Instant Action, campaigns —
with no mission editing at all. See Install.

## What works right now

Once loaded into a mission (see Install), spawn into a player-controlled aircraft parked
at an airbase. Open the comms menu (`\` by default) and navigate **F10 (Other...) →
F1 (ATCAI)** for:

- **Request radio check** — ATC confirms it hears you.
- **Request airfield information** — a spoken ATIS: information letter, time, runway in
  use, wind, temperature and altimeter.

There's also a **repeating ATIS broadcast** on its own frequency (380.000 AM by default,
every 60s), carrying the information for whichever field you're nearest. Tune in and
listen rather than asking. Configurable in the manager's Settings tab, including letting
it pick an unused frequency for you.
- **Request startup** — approves startup, names the runway in use, gives wind and QNH.
- **Request taxi** — taxi to the holding point for the active runway, with QNH.
- **Request takeoff** — takeoff clearance with current wind, or a hold if the runway is
  occupied or someone's on final.
- **Report inbound** — circuit join for the active runway, with your range from the
  field, wind and QNH.
- **Request landing** — landing clearance with wind, a go-around if the runway is
  occupied, or sequencing behind traffic ahead of you.
- **Request taxi to parking** — after landing, vacate and taxi in.
- **Request loadout status** — reads back your current weapon/store loadout.
- **Request straight-in approach** — skip the circuit when flying a full pattern isn't
  realistic. Traffic ahead delays you rather than refusing the approach.
- **Request vectors to nearest field** — the nearest field *your coalition can use*, with
  a heading and distance to it. Answered at any range, because being out of ATC range is
  the situation the call exists for.
- **Declare emergency** — or just say "mayday". See below.

**Declaring an emergency changes how ATC treats you.** Once declared, and until you're
parked:

- You're cleared to land immediately, without asking, with runway, wind and altimeter.
- You are never sequenced behind other traffic and never sent around — the aircraft in
  your way is the one that gets moved.
- The call is answered from outside normal ATC range, unlike every other request. A field
  200 miles away still takes a mayday and gives you a heading to reach it.
- On the ground you're told to shut down where you are rather than given a clearance.
- Taxiing to parking ends it, and the reply says so.

Spoken distress calls outrank anything else in the same transmission: "mayday mayday,
Chevy 81, request landing" is heard as a mayday, not as a request for landing.

**ATC uses each airfield's real frequencies.** The manager reads them from the game's
own terrain files at install time, so Batumi answers on Batumi's frequencies and Vaziani
on Vaziani's — the same numbers DCS's built-in ATC menu shows. Tune to one of them and
you hear ATC; don't, and you won't, which is how a radio should behave.

**Some replies deliberately ignore that.** A refusal, your loadout, and anything said
during an emergency or a divert go out on the field's frequencies *and* the configured
fallback list at the same time. Those are the calls that matter when you're away from a
field, so transmitting them on one field's frequency is self-defeating — you'd be least
likely to be tuned to it. Routine clearances stay on the field's own frequency, so
tuning in still means something.

This applies to **what you hear, not to what ATC hears.** Speech recognition runs in an
external Windows process that has no access to your aircraft's radio state, so a spoken
request reaches ATC whichever frequency you're tuned to — or none at all. Push-to-talk
gates the microphone, not the radio. See Known limitations.

**Active runway follows the wind.** ATC reads the live wind at the field and picks
whichever runway end has the best headwind, so the runway in use changes with the
weather rather than being fixed. Altimeter (QNH) is read from the sim too.

**ATC watches the runway.** Before clearing you it checks for aircraft on the runway or
on final, and will hold you at the holding point, sequence you behind landing traffic
("number two behind the F-16C"), or send you around rather than clearing you into a
conflict.

**Requests are checked against your situation.** You can't get takeoff clearance straight
from parking, can't taxi while airborne, and can't get landing clearance sitting on the
ramp — ATC refuses with a reason. Phases run
`parked → startup → holding_short → takeoff → airborne → inbound → cleared_to_land →
parked`, and a refused request leaves your phase unchanged.

ATC finds "your" airfield by proximity — a tight radius on the ground so it's
unambiguously the field you're on, and a much wider one airborne so inbound calls work
from a realistic distance. No per-mission configuration needed.

## Requirements

- DCS World (any recent version with the standard scripting engine).
- No MissionScripting.lua edits and no Mission Editor work — the mission is built for you.
- Voice input and spoken replies need Python 3 and Windows' built-in speech engines;
  spoken replies over the radio additionally need SRS. Everything works without them,
  just as on-screen text driven from the comms menu.

## Install

**The easy way: run `ATCAI-Manager.exe`.** One file, nothing else to install — no Python,
no command line. It finds DCS, installs ATCAI, turns it on and off, changes settings, and
starts voice input and spoken replies with buttons. Build it with
`python manager/build_exe.py` (see "Building the app" below), or use the copy in `dist/`.

The manager needs the same restart of DCS that a manual install does, and it says so.

### Installing by hand

If you'd rather not use the app, it's two copies and a restart. Nothing per-mission.

1. Copy everything in `lua/atc/` into `<Saved Games>\DCS\Scripts\ATCAI\`
   (`atc_config.lua`, `atc_core.lua`, `atc_traffic.lua`, `atc_atis.lua`,
   `atc_menu.lua`, `atc_inbox.lua`). The voice inbox, settings and generated frequency
   files are created in that same folder.
2. Copy `lua/hooks/atcai_autoload.lua` into `<Saved Games>\DCS\Scripts\Hooks\`.
3. Restart DCS. Hooks are only read at startup.

That's it — fly anything and ATCAI is there. To remove it, delete the hook from
`Scripts\Hooks\`; to disable temporarily, rename it.

### How it loads into any mission

Hook scripts run in DCS's GUI Lua state, which has file access but none of the mission
API. The mission state has the API but no file access. `net.dostring_in("mission", ...)`
bridges them, but drops code into a bare state where `env`, `world` and `coalition` are
all nil — so the code must be handed to a function that runs *inside* the real sandbox.
`a_do_script(<lua source>)` is that function, and the hook asks the mission to run a
`dofile` chain through it.

An earlier attempt used `a_do_script_file(<path>)`, which reported success and silently
did nothing — almost certainly because "DO SCRIPT FILE" embeds scripts into the `.miz` as
mission resources, so it wants a resource key rather than a filesystem path. That cost a
lot of debugging; the injected Lua is now covered by tests that execute it against
stand-in `a_do_script`/`dofile` implementations, so malformed strings fail locally rather
than silently in the sim.

### Optional: building a self-contained mission

`tools/build_test_mission.py` still exists and injects the loader directly into a `.miz`.
It's no longer needed for normal use — it's useful for a mission that should carry ATCAI
without the hook installed, and for setting a mission's start time:
   ```
   tools/build_test_mission.py <source.miz> ATCAI-test.miz \
       'C:\Users\<you>\Saved Games\DCS\Scripts\ATCAI\atc_core.lua' \
       'C:\Users\<you>\Saved Games\DCS\Scripts\ATCAI\atc_traffic.lua' \
       'C:\Users\<you>\Saved Games\DCS\Scripts\ATCAI\atc_atis.lua' \
       'C:\Users\<you>\Saved Games\DCS\Scripts\ATCAI\atc_menu.lua' \
       'C:\Users\<you>\Saved Games\DCS\Scripts\ATCAI\atc_inbox.lua' \
       --start-time 12:00
   ```
   `--start-time HH:MM` overrides the mission clock — worth setting, since many stock
   missions start at midnight and testing an airfield in the dark gets old.

   `--traffic N` adds N AI flights that take off from the player's own airfield and come
   straight back to land, which is the only practical way to exercise traffic awareness:
   flying alone, nothing ever occupies the runway or turns up on final. `--traffic-type`
   picks the aircraft (Su-25T by default, since it ships with every DCS install) and
   `--traffic-spacing` sets the gap between flights.

   `--ground N` scatters N enemy vehicle groups around the airfields the mission uses,
   so the test mission is worth flying for its own sake. `--ground-defended` gives them
   anti-aircraft cover, and `--ground-radius` sets how far out they sit. Targets go on
   the coalition the player isn't on, using core DCS vehicles so the mission works
   without owning extra modules.

   `--enemy-air N` adds hostile fighter flights that are airborne, tasked to engage, and
   active from the moment the mission starts. Stock missions commonly leave their enemy
   flights on `lateActivation`, waiting for triggers tied to that mission's own
   objectives, so a mission reused for testing can look fully populated and still never
   produce a fight. `--enemy-air-type`, `--enemy-air-size`, `--enemy-air-radius` and
   `--enemy-air-altitude` tune them.

   The tool refuses to overwrite an existing mission unless you pass `--force`, so
   building a new variant never costs you the last one.
   `<source.miz>` can be any existing mission with a ramp-parked player aircraft — a
   stock Instant Action mission works well. The tool copies it and injects a MISSION
   START trigger that sets the inbox path and `dofile()`s each script in order.

   Listing `atc_traffic.lua` and `atc_inbox.lua` is optional: the scripts locate their
   own directory (via `debug.getinfo`) and load those two themselves if the mission
   didn't.
   That means a mission built before a script existed keeps working without a rebuild —
   worth knowing, because DCS flies an editor-held mission from a temp copy, so a stale
   trigger can otherwise silently skip a script.

### Why dofile instead of DO SCRIPT FILE

The Mission Editor's "DO SCRIPT FILE" action **embeds a copy** of the script into the
.miz, so edits on disk wouldn't be picked up without re-adding the file each time. A
`dofile()` on an absolute path reads from disk on every mission start instead, so the
edit → re-fly loop needs no editor interaction at all.

This works because DCS's `MissionScripting.lua` sanitizes only `os`, `io`, `lfs`,
`require`, `loadlib` and `package` — `dofile` and `loadfile` are left available. No
modification of that file is needed.

## Configure

Settings live in `<Saved Games>\DCS\Scripts\ATCAI\config.lua`, which the manager app
will write. It's a plain Lua table and can be hand-written today:

```lua
ATCAI_CONFIG = {
    tts_frequency = "251.0",
    airbase_air_radius = 120000,
}
```

Anything absent keeps the script default, an unknown key is ignored, and a bad value is
ignored on its own rather than discarding the rest of the file — so a typo can't stop ATC
working. Recognised keys are listed in `ATC.CONFIG_FIELDS` in `lua/atc/atc_config.lua`:
`tts_frequency`, `tts_modulation`, `airbase_search_radius`, `airbase_air_radius`,
`inbox_poll_seconds`, `traffic_field_radius`, `traffic_roll_speed`,
`traffic_final_range`, `traffic_final_height`, `traffic_final_arc`, `atis_enabled`,
`atis_frequency`, `atis_modulation`, `atis_interval`.

The defaults these override, in `lua/atc/atc_core.lua`:

- `ATC.AIRBASE_SEARCH_RADIUS` (default `6000` m, ~3 nm) — how far from an airbase you can
  be **on the ground** and still be treated as "at" it.
- `ATC.AIRBASE_AIR_RADIUS` (default `92600` m, 50 nm) — the equivalent **airborne**, so
  inbound calls work from a realistic distance. Raise it if you want to check in earlier.
- `ATC.TTS_FREQUENCY` / `ATC.TTS_MODULATION` — the radio channels ATC transmits on.
- `ATC.INBOX_POLL_SECONDS` in `atc_inbox.lua` (default `0.3`) — voice command latency.

The repeating ATIS broadcast is configured on the manager's Settings tab, or via
`atis_enabled`, `atis_frequency`, `atis_modulation` and `atis_interval` in `config.lua`.

In `lua/atc/atc_traffic.lua`, if ATC is too cautious or not cautious enough:

- `ATC.TRAFFIC_ROLL_SPEED` (default `15` m/s) — above this, a ground aircraft counts as
  using the runway rather than taxiing.
- `ATC.TRAFFIC_FINAL_RANGE` / `ATC.TRAFFIC_FINAL_HEIGHT` / `ATC.TRAFFIC_FINAL_ARC` —
  how close, low and aligned an aircraft must be to count as being on final.

## Test / run for actual gameplay

1. Launch DCS and fly **any** mission with a player-controlled aircraft — Instant Action
   is fine. ATCAI is loaded by the hook, so no particular mission is needed. On spawn you
   should see an on-screen **"ATCAI ready"** message.
2. Once control is handed to you, press **`\`** to open the comms menu (not the F10 key —
   that's the map view).
3. Navigate **F10 (Other...) → F1 (ATCAI)**. Custom mission menus always live under the
   "Other" submenu, not at the top level. Don't confuse this with the stock **ATC**
   entry on the main comms list — that's a built-in DCS feature (airport list,
   frequencies, "Request Start-Up") and unrelated to this project.
4. Press the number for the option you want to try — this sends the request and closes
   the menu; watch the top-left of the screen for ATC's reply as on-screen text:
   - Request radio check → expect a "read you five by five" message.
   - Request startup → expect the runway in use, wind and QNH.
   - Request takeoff *before* requesting taxi → expect ATC to refuse and tell you to
     request taxi first.
   - Request taxi, then request takeoff → expect a takeoff clearance naming a runway.
   - Request landing while parked → expect a refusal, since you're on the ground.
   - Request loadout status → expect your current stores listed back to you.
5. To try another option, press `\` again to reopen the comms menu — it doesn't stay
   open between requests.
6. To confirm everything loaded, open the DCS log
   (`%USERPROFILE%\Saved Games\DCS\Logs\dcs.log`) and look for:
   ```
   ATCAI: hook injected from ... (ok=true, result=)
   ATCAI: atc_core.lua loaded
   ATCAI: atc_traffic.lua loaded
   ATCAI: atc_menu.lua executing
   ATCAI: menu built for group ...
   ATCAI: atc_inbox.lua loaded, polling ...
   ```
   No `hook injected` line means the hook isn't installed or DCS wasn't restarted after
   installing. The line present but the rest missing means the injection was rejected —
   the `result=` field carries the reason.

## Voice input

Speak your requests instead of using the comms menu. Uses the speech recogniser built
into Windows — no models to download, no extra packages.

**Players use the Start button on the manager's Voice tab.** The command below runs the
same code directly, which is what you want while developing:

```
python3 voice-bridge/atcai_listen.py
```

Then talk to it the way you'd actually work a radio:

> *"Chevy 81, requesting radio check"*
> *"Vaziani Tower, Chevy 81, requesting taxi to one three"*
> *"Chevy 81, ready for departure"*

"request" and "requesting" are interchangeable everywhere, as are "report" and
"reporting" — only one form of each is written down, and the alternates are generated
(`VERB_VARIANTS` in `atcai_listen.py`), so the two can't drift apart. A test enforces it.

The request itself has to be one of the phrasings it knows (`--list-phrases` shows all
48 across the 9 requests), but **anything can surround it** — your callsign, the tower's
name, a runway, "over". The recogniser is given a wildcard either side of the request, so
it doesn't have to match your whole transmission; the request is then picked out of the
recognised text, longest match first (so "requesting taxi to parking" is parking, not
taxi).

Recognised commands appear in the terminal as they're picked up, along with anything it
heard but couldn't find a request in — useful for learning what it responds to.

If it triggers on things you didn't mean as requests, `--strict` turns the wildcards off
and requires the request to be the entire utterance (the original, less natural
behaviour), and `--min-confidence` raises the bar.

Pair it with the reply bridge in another terminal to get a full conversation:

```
python3 voice-bridge/atcai_tts.py --mode local
```

**How it works:** the mission sandbox has no sockets or file reads, but `dofile`
survives sanitisation. So the listener writes a one-line Lua file:

```lua
ATCAI_INBOX = { seq = 1758300000123, intent = "taxi" }
```

and `lua/atc/atc_inbox.lua` polls it (every 0.3s) with `dofile`, running anything whose
sequence number it hasn't seen. The sequence is epoch milliseconds, so it keeps rising
across restarts. Writes are atomic (temp file + replace) and the Lua side wraps the read
in `pcall`, so a half-written file is just retried rather than breaking anything. On
mission start the sequence is primed from whatever is already on disk, so a command left
over from a previous session can't fire the moment you spawn in.

Because the listener drives the same `ATC.request*` functions the menu does, the menu
keeps working exactly as before — voice is additive.

Options: `--min-confidence` (default 0.6) filters shaky recognitions; anything below the
threshold is reported but ignored, which is useful for tuning. `--strict` disables the
surrounding wildcards. `--inbox` overrides the inbox path if your DCS lives somewhere
unusual.

Every helper process (the speech recogniser, Windows text-to-speech, SRS) is launched
with `CREATE_NO_WINDOW`. Without it Windows pops a console over the game for each
spoken reply, which is unusable in a full-screen sim.

## Spoken ATC replies (SRS TTS)

ATC replies can be spoken over the radio instead of only appearing as on-screen text,
using SRS's text-to-speech.

**Players use the Start button on the manager's Voice tab**, which runs this in-process.
The commands below are the same code run directly, for development.

**How it works:** the mission sandbox can't launch processes or write files, so
`atc_core.lua` emits each reply to `dcs.log` as `ATCAI_TTS|<freq>|<modulation>|<text>`.
`voice-bridge/atcai_tts.py` tails the log and hands matching lines to SRS's
`DCS-SR-ExternalAudio.exe`, which transmits them as speech on that frequency.

**To use it:**

1. Start **SRS-Server.exe** (`DCS-SimpleRadio-Standalone\Server\`) — without it you'll
   get `SRS server not reachable on port 5002`.
2. Start the **SRS client** and connect it to `127.0.0.1`.
3. Start the bridge and leave it running:
   ```
   python3 voice-bridge/atcai_tts.py
   ```
   It prints each transmission it sends, and says plainly if SRS can't be reached.
4. Fly the mission. You tune the **aircraft** radio, not SRS — SRS mirrors whatever
   your aircraft is set to. To avoid needing to retune at all, ATC transmits on several
   common DCS defaults at once (`251.0, 305.0, 124.0, 127.5` AM — see
   `ATC.TTS_FREQUENCY`), so a default-configured aircraft should hear it as-is.

   To see which frequencies your radios are actually on, toggle the SRS radio overlay
   in-game (default **LEFT CTRL + LEFT SHIFT + ESC**).

Useful flags: `--gender`, `--culture` (voice), `--coalition`, `--port`, `--log`,
`--srs-exe`. It auto-detects WSL vs native Windows paths; the SRS binary is a Windows
process either way, so running the bridge from WSL works fine.

### Fallback: `--mode local` (no SRS)

```
python3 voice-bridge/atcai_tts.py --mode local
```

Speaks ATC through Windows' built-in TTS on your desktop audio instead of over the
in-game radio. No SRS server, client, or radio tuning involved — useful when SRS's DCS
integration isn't cooperating, or for quick iteration. `--local-rate` (-10..10) adjusts
speech speed.

### If SRS produces no audio: the port 7080 conflict

SRS's DCS export sends your radio state to UDP **7080**, which the SRS *client* must be
bound to in order to receive. If DCS grabs that port first, the client silently degrades
— the client log fills with:

```
DCSRadioSyncManager | Reset Radio state - no longer connected
```

and you hear nothing, even though transmissions are being accepted by the server. Check
with:

```
netstat.exe -ano | grep 7080      # note the owning PID
tasklist.exe /FI "PID eq <pid>"   # if this is DCS.exe, that's the conflict
```

Fix is start order: have the SRS client running *before* launching DCS, so the client
owns 7080. This is an SRS/DCS integration issue, independent of ATCAI.

## Tests

The ATC logic has unit tests that run outside DCS, against **DCS's own bundled Lua 5.1
interpreter** (`bin/luae.exe`) with the mission-scripting API stubbed out — same runtime
as the real thing, no sim launch required:

```
tools/run_tests.sh
```

One pytest run covers everything:

- **Lua** (marked `lua`) — the ATC core, inbound bridge, traffic awareness, config
  overrides and hook injection, each executed on DCS's own Lua 5.1 interpreter, plus a
  round-trip where the Python bridge writes a real inbox file and DCS's `dofile` reads it
  back.
- **Python** — installer (detection, install/enable/remove, settings), preferences, and
  the voice bridges (phrase coverage, intent matching, inbox format, SRS failure modes).
- **Wiring** (`tests/test_wiring.py`) — cross-checks the four files a request has to be
  listed in: the handler in `atc_core.lua`, the comms-menu entry in `atc_menu.lua`, the
  intent map in `atc_inbox.lua` and the spoken phrases in `atcai_listen.py`. DCS says
  nothing when these drift — a menu entry naming a function that doesn't exist is just a
  dead line in the comms menu — so nothing else would notice.
- **GUI** (marked `gui`) — the manager window built and driven for real.

Set `DCS_BIN` if your DCS install isn't at the default Steam path.

Run these before flying — flying is then just the integration check, rather than the
only way to find out something broke.

`tools/run_tests.sh` picks Windows Python when it can find it, because the manager's GUI
tests need tkinter and a display; WSL's Python usually has neither. Set `ATCAI_PYTHON` to
override, or run `pytest` directly.

**Two gaps worth knowing before you trust a green run:**

- **The Lua suites skip on CI.** They run on DCS's own `luae.exe`, which isn't present on
  a GitHub runner, so `.github/workflows/build.yml` covers only the Python and GUI
  suites. Anything touching in-game ATC behaviour has to be run locally, and a release
  should be flown once before it ships.
- **GUI tests skip without a display.** They're marked `gui` and skip cleanly, so a green
  run in a headless environment may have tested less than it appears. Check the skip
  count.

Select subsets with the markers: `pytest -m lua`, `pytest -m gui`, `pytest -m "not lua"`.

### Quick iteration while developing

Edit the `.lua` files in `<Saved Games>\DCS\Scripts\ATCAI\` (or edit in the repo and
re-copy), then just re-fly the mission — `dofile()` re-reads from disk on every mission
start. The mission itself only needs rebuilding if the script *paths* or *file list*
change.

### Troubleshooting

- **Bridge prints transmissions but you hear nothing** — the bridge only knows SRS
  accepted the audio; it can't tell whether anything played it. Two usual causes:
  (1) frequency mismatch — check your aircraft radio and make sure that frequency is in
  `ATC.TTS_FREQUENCY`; (2) SRS's radio integration is down — see "the port 7080
  conflict" above. `--mode local` sidesteps both.
- **No ATCAI entry in the comms menu** — don't confuse it with DCS's own stock **ATC**
  entry (airport list, frequencies, "Request Start-Up") which is unrelated to this
  project. Check the dcs.log lines from step 6 above first; if the scripts didn't load,
  the menu code never ran. Also confirm you're flying the mission (not just viewing the
  briefing) and are in full control of the aircraft.
- **No Triggers tab in the Mission Editor** — you likely have a campaign open instead of
  a standalone mission; use File → New instead. If still missing on a blank mission,
  maximize the editor window.

## Known limitations

- Airbase detection is proximity-only — no concept of which parking spot you're in, and
  no disambiguation if two fields are both in range.
- **Clearances aren't coalition-checked.** Diverts and vectors are — they only ever offer
  a field your side can use — but ordinary requests answer from whichever field is
  nearest, including an enemy one. In a combat mission you can be cleared to land at a
  field you'd be shot down over.
- A wide transmission covers the answering field plus the fallback list. If you're
  tuned to some *third* field's frequency it still won't reach you — keep one of the
  fallback frequencies on a second radio if you want a guarantee.
- Bearings given with vectors and emergency clearances are **true, not magnetic**. DCS
  exposes no magnetic variation to scripts. Runway designators come from DCS already
  magnetic, so the two don't match on maps with significant declination.
- Traffic awareness is inferred, not measured: DCS doesn't expose runway geometry to
  scripts, so "on the runway" means *on the ground, near the field, moving faster than
  taxi speed*, and "on final" means *low, close, and tracking the landing heading*. An
  aircraft holding on a fast taxiway could in principle be misread.
- Taxi instructions don't name taxiways, and circuit joins don't specify a direction
  (left/right downwind) or your position relative to the field.
- The comms menu always shows every request; invalid ones are refused when used rather
  than hidden.
- Voice input listens continuously unless you turn on push-to-talk in the manager.
  Push-to-talk is Windows-only (it needs `GetAsyncKeyState` to see the key while DCS has
  focus); elsewhere the setting is ignored and it keeps listening.
- **Transmitting isn't frequency-checked.** ATC replies on the field's real frequency, so
  hearing it requires being tuned in — but it will answer a request made on any frequency,
  or with the radio off. The recogniser is an external process and can't see the
  aircraft's radio; closing that gap would mean reading radio state from the sim side and
  gating requests on it.
- Voice commands are delivered to every player aircraft registered in the mission. Fine
  for single-player, wrong for multiplayer (which is out of scope anyway).
- The *request* must be one of the known phrasings, even though anything may surround it.
  It isn't free-form speech.
- Callsigns, airfield names and runway numbers you speak are matched loosely and then
  discarded — ATC doesn't check that the runway you asked for is the one in use, and it
  always answers as if the call were addressed to it.
- If the manager can't find your DCS **game** folder (as opposed to Saved Games), the
  real frequency table can't be generated and ATC falls back to the fixed list in
  `ATC.TTS_FREQUENCY`.
- Spoken replies over the radio need the SRS server and client running. The
  speakers option (`--mode local`) has no such dependency.
- Your ATC phase resets when a mission restarts; ATC won't remember that you were
  already cleared to taxi.
- Voice input and spoken replies only work while the manager app is running. ATC's
  on-screen text works without it.

## Repo layout

```
ATCAI/
├── GETTING-STARTED.md      the guide for players
├── README.md               this file — for developers
├── CHANGELOG.md            what changed, written for players
├── docs/
│   ├── PLAN.md             architecture, and why it's built this way
│   └── INSTALLER-PLAN.md   how the manager app came about
├── lua/atc/                the ATC itself, loaded into every mission
│   ├── atc_config.lua      applies user settings over script defaults
│   ├── atc_core.lua        phases, phraseology, wind/runway/weather logic
│   ├── atc_traffic.lua     who else is using the runway
│   ├── atc_atis.lua        the repeating airfield information broadcast
│   ├── atc_menu.lua        comms menu + player registry
│   └── atc_inbox.lua       polls the voice inbox file via dofile
├── lua/hooks/
│   └── atcai_autoload.lua  loads all of the above into every mission
├── manager/                the app users run
│   ├── app.py              the window: install, enable, settings, voice buttons
│   ├── installer.py        finds DCS, installs/removes/enables, writes settings
│   ├── prefs.py            the app's own remembered settings
│   └── build_exe.py        packages it into one self-contained executable
├── voice-bridge/
│   ├── atcai_listen.py     speech recognition -> the mission's inbox
│   ├── recognize.ps1       the Windows recogniser itself
│   └── atcai_tts.py        dcs.log -> spoken replies (SRS or local audio)
├── tests/                  pytest: installer, prefs, voice bridge, GUI, and the
│                           Lua suites run on DCS's own interpreter
└── tools/
    ├── run_tests.sh        runs everything
    ├── test_*.lua          the Lua suites themselves
    └── build_test_mission.py   makes a .miz carrying ATCAI, and can add AI
                                traffic and ground targets for testing
```

## Support the project

ATCAI is free and open source, and built in spare time. If it added something to your
flying, a donation is a genuine help — it pays for the DCS modules and terrains used to
test against, and it buys the time to keep the project maintained as DCS updates break
things.

There's no obligation and nothing is held back: every feature works for everyone.

**Bitcoin (BTC)**

```
bc1q0mp57a896yqcsvnnvrrnygelpg4yw6rs6wfcgj
```

**Ethereum (ETH)**

```
0x310965c1cecb8e79e9afba219a6b8c4b2887851f
```

Not in a position to donate? Starring the repository, reporting a bug clearly, or
telling another DCS player about it all help just as much.
