# ATCAI — talk to air traffic control in DCS

[![Download](https://img.shields.io/github/v/release/h4cklife/DCS?filter=atcai-v*&label=download&color=2ea44f)](https://github.com/h4cklife/DCS/releases)
[![Licence](https://img.shields.io/github/license/h4cklife/DCS)](../LICENSE)
![DCS World](https://img.shields.io/badge/DCS%20World-single--player-2ea44f)

ATCAI gives DCS an air traffic controller you can actually talk to. Ask for startup,
taxi, takeoff, a circuit join or landing clearance, and it answers out loud — with the
real wind, the real altimeter setting, and the runway that actually suits the weather.

Works in **every mission you fly**: Instant Action, your own missions, campaigns. There
is nothing to set up per mission.

Single-player only for now.

---

## Setting it up

1. **Close DCS** if it's running.
2. Run **ATCAI-Manager.exe**. Nothing to install — it's one file.

   Windows may warn you about it, or your antivirus may quarantine it. That's expected
   and explained in [Is it safe?](#is-it-safe) below — it happens to nearly every app
   packaged this way.
3. Check the folder at the top says your DCS folder. It usually finds it by itself. If it
   warns you, press **Choose folder…** and pick your `Saved Games\DCS` folder.
4. Press **Install**.
5. **Start DCS.**

That's it. Fly any mission, press the **`\`** key to open the comms menu, then choose
**Other → ATCAI**.

> The `\` key is the comms menu. The F10 key opens the map — a common mix-up.

At this point ATC replies as text on screen. To hear it speak, and to talk to it, see
below.

## Talking to ATC, and hearing it

Open the **Voice** tab in the manager and press both **Start** buttons. The labels turn
green when they're running.

- **Start listening** lets you speak to ATC.
- **Start replies** makes ATC speak back.

Tick **"Start this automatically when the app opens"** on each and you won't have to
press them again.

Leave the manager running while you fly. It can sit minimised.

### What to say

Speak like you would on a real radio:

> *"Chevy 81, requesting taxi"*
> *"Vaziani Tower, Chevy 81, request startup"*
> *"Ready for takeoff"*
> *"Reporting inbound"*
> *"Requesting landing"*
> *"Request loadout"*

Your callsign, the tower's name and a runway can all be in there — ATCAI picks the
request out of whatever you say. "Request" and "requesting" both work everywhere.

The **Voice** tab shows everything it heard, so if something isn't being picked up you
can see why.

### Hearing ATC on the radio instead of your speakers

By default ATC comes out of your PC speakers. If you use
[SimpleRadio Standalone](http://dcssimpleradio.com/), pick **"Send over the radio using
SRS"** instead, and tune your aircraft radio to one of the frequencies on the Settings
tab.

SRS needs its server *and* client running. If it isn't working, switch back to the
speakers option — that always works.

## What ATC can do

| Ask for | You get |
|---|---|
| Radio check | Confirmation it can hear you |
| Startup | Approval, the runway in use, wind and altimeter |
| Taxi | Taxi to the holding point, with the altimeter setting |
| Takeoff | Clearance with the current wind — or a hold if the runway is busy |
| Inbound | A circuit join, your distance from the field, wind and altimeter |
| Landing | Clearance — or a go-around, or sequencing behind other traffic |
| Taxi to parking | Sent to vacate and taxi in after landing |
| Loadout | Your remaining weapons read back |

ATC also refuses things that don't make sense: no takeoff clearance from your parking
spot, no landing clearance while you're sitting on the ramp.

## Settings

The **Settings** tab has the few things worth changing — the radio frequencies ATC uses,
and how far out it will answer you. Everything else has a sensible default.

Changes apply next time you start a mission.

## Turning it off

- **Turn off** in the manager stops ATCAI without removing anything. Restart DCS.
- **Remove** takes it out of DCS entirely. Your settings are kept.

Neither touches your missions or your DCS install.

## If something isn't working

**No ATCAI in the comms menu.**
Restart DCS — it only loads ATCAI at startup. Check the manager says "installed and on".
Remember it's under **Other**, not the top level, and that `\` is the comms key. Don't
confuse it with DCS's own **ATC** entry, which lists airports and frequencies — that's a
stock game feature, nothing to do with this.

**ATC replies on screen but I can't hear it.**
Press **Start replies** on the Voice tab. If you're using SRS, check the SRS server and
client are running and your radio is on one of the frequencies from the Settings tab; the
speakers option avoids all of that.

**Talking to ATC does nothing.**
Press **Start listening**. Watch the Voice tab while you speak — if it shows what you
said but didn't act, the wording wasn't recognised; if it shows nothing at all, Windows
isn't hearing your microphone.

**It reacts when I wasn't talking to it.**
Drag the "How sure it must be" slider right, or tick "Only react to the exact request".

**Windows says the app is unsafe / my antivirus flagged it.**
See [Is it safe?](#is-it-safe).

**Something else.**
The box at the bottom of the manager logs everything it does. That's the first place to
look, and the most useful thing to include if you report a problem.

## Is it safe?

**Your antivirus may flag ATCAI-Manager.exe, and Windows may warn before running it.**
This happens to most small tools packaged this way: the app bundles its own Python
runtime into a single file, and that packaging pattern is one scanners treat as
suspicious regardless of what the program does. It is a false positive, but it is a
*common* one, so expect it rather than being alarmed by it.

What ATCAI actually does on your machine:

- Writes only into your `Saved Games\DCS` folder (the scripts and their settings) and a
  small preferences file in your user profile.
- Never touches your DCS installation, your missions, or anything else.
- **Remove** puts it all back as it was.

If you would rather not take that on trust, you don't have to:

- The complete source is public — every line the app runs is readable.
- You can build the executable yourself with `python manager/build_exe.py` rather than
  downloading it.
- Downloads come only from the project's releases page. Don't run a copy from anywhere
  else.

### How releases are tested

Each release is built automatically on a clean Windows machine and must pass the full
test suite before the file is published.

One honest gap: the tests that exercise the in-game ATC logic need DCS's own Lua
interpreter, which isn't present on a build server, so **those particular tests are
skipped during the automated build** and are run by hand against a real DCS install
before a release goes out. Everything else — the installer, the voice bridges, the
manager window — is covered automatically on every build.

## What it doesn't do

- Multiplayer. Voice commands would reach every aircraft.
- Taxiway names — DCS doesn't expose them to scripts, so instructions stay general.
- Per-airfield tower frequencies. ATC transmits on a fixed list rather than the real
  frequency for the field you're at.
- Understand free-form speech. It knows a fixed set of requests, though you can wrap
  anything around them.
