# ATCAI — talk to air traffic control in DCS

[![Download](https://img.shields.io/github/v/release/h4cklife/DCS?filter=atcai-v*&label=download&color=2ea44f)](https://github.com/h4cklife/DCS/releases)
[![Licence](https://img.shields.io/github/license/h4cklife/DCS)](../LICENSE)
![DCS World](https://img.shields.io/badge/DCS%20World-single--player-2ea44f)
[![Bitcoin](https://img.shields.io/badge/Bitcoin-donate-f7931a?logo=bitcoin&logoColor=white)](#support-the-project)
[![Ethereum](https://img.shields.io/badge/Ethereum-donate-3c3c3d?logo=ethereum&logoColor=white)](#support-the-project)

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

Press **Start** on two tabs in the manager. The labels turn green when they're running.

- **Talking to ATC** → **Start listening** lets you speak to ATC.
- **Hearing ATC** → **Start replies** makes ATC speak back.

Tick **"Start this automatically when the app opens"** on each and you won't have to
press them again.

By default ATC listens all the time. If you talk to other people while flying, tick
**"Only listen while I hold a key"** and choose a key — ATC then only hears you when you
hold it. Pick a key DCS isn't already using, and keep holding it until you've finished
the sentence.

The key gates your **microphone**, not your radio: ATC hears a request whatever
frequency you're tuned to, or with the radio off. Tuning matters for hearing the *reply*
— see below.

Leave the manager running while you fly. It can sit minimised.

### What to say

Speak like you would on a real radio:

> *"Chevy 81, requesting taxi"*
> *"Request airfield information"*
> *"Vaziani Tower, Chevy 81, request startup"*
> *"Ready for takeoff"*
> *"Reporting inbound"*
> *"Requesting landing"*
> *"Request loadout"*
> *"Request straight in"*
> *"Request vectors home"*
> *"Mayday mayday, Chevy 81, engine fire"*

Your callsign, the tower's name and a runway can all be in there — ATCAI picks the
request out of whatever you say. "Request" and "requesting" both work everywhere, and so
do "declare" and "declaring".

The **Log** tab shows everything it heard, so if something isn't being picked up you
can see why.

### Hearing ATC on the radio instead of your speakers

By default ATC comes out of your PC speakers. If you use
[SimpleRadio Standalone](http://dcssimpleradio.com/), pick **"Send over the radio using
SRS"** instead, and tune your aircraft radio to the airfield's frequency — ATCAI uses
the real ones, the same numbers DCS's own ATC menu lists for that field.

SRS needs its server *and* client running. If it isn't working, switch back to the
speakers option — that always works.

## What ATC can do

| Ask for | You get |
|---|---|
| Radio check | Confirmation it can hear you |
| Airfield information | An ATIS report: letter, time, runway in use, wind, temperature, altimeter |
| Startup | Approval, the runway in use, wind and altimeter |
| Taxi | Taxi to the holding point, with the altimeter setting |
| Takeoff | Clearance with the current wind — or a hold if the runway is busy |
| Inbound | A circuit join, your distance from the field, wind and altimeter |
| Landing | Clearance — or a go-around, or sequencing behind other traffic |
| Taxi to parking | Sent to vacate and taxi in after landing |
| Loadout | Your remaining weapons read back, from any distance |
| Straight-in approach | Permission to skip the circuit and come straight in |
| Vectors | A heading and distance to the nearest field your side can use |
| Emergency | Priority, an immediate landing clearance, and the fire trucks out |

### When it goes wrong

Say **"mayday"** — that's all it takes. You don't have to be near a field, and you don't
have to finish the sentence tidily; a mayday is heard even if you ask for something else
in the same breath.

Once you've declared, ATC treats you differently until you park:

- You're cleared to land straight away, with the runway, wind and altimeter, without
  having to ask.
- You're never told to go around and never put behind other traffic. Whoever's in the
  way gets moved instead.
- It answers from any distance. Every other request needs you within about 50 miles;
  a mayday doesn't.
- It's transmitted on the field's frequency **and** the standard ATCAI frequencies at
  once, so you hear it whichever of those you're tuned to. The same goes for your
  loadout check and for anything ATC refuses — those are exactly the calls you'd
  otherwise miss.

If you're lost or your home field is gone, ask for **vectors** — "request vectors home".
You'll get the nearest field your own side can use, with a heading and how far it is.
Enemy fields are never offered.

Both are in the comms menu too, at the bottom of the ATCAI list, if you'd rather not
rely on being understood while things are going badly.

ATC also refuses things that don't make sense: no takeoff clearance from your parking
spot, no landing clearance while you're sitting on the ramp.

## Listening to airfield information

As well as asking for it, ATCAI repeats the field information on its own frequency every
minute — like a real ATIS. Tune your radio to **380.000 AM** and you'll hear the runway in
use, wind, temperature and altimeter for whichever field you're nearest.

You can change that frequency on the **Settings** tab, or tick **"Pick one for me"** and
the manager will choose one no airfield is using. It warns you if you pick a frequency
that clashes with an airfield, or one most aircraft radios can't tune.

Turn the loop off there too, if you'd rather only hear it when you ask.

## Settings

The **Settings** tab has the few things worth changing — the radio frequencies ATC uses,
and how far out it will answer you. Everything else has a sensible default.

Each box shows what the setting **is right now**, with the stock value named underneath,
so you can see what you're changing from. **Back to defaults** puts them all back.

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
Press **Start replies** on the "Hearing ATC" tab. If you're using SRS, check the SRS server and
client are running and your radio is on one of the frequencies from the Settings tab; the
speakers option avoids all of that.

**Talking to ATC does nothing.**
Open the **Test Microphone** tab and press **Test microphone**. It listens for fifteen
seconds and tells you
which of three things is wrong:

- *Nothing was heard at all* — Windows is giving ATCAI the wrong microphone, or the one
  it named is muted or switched off. **ATCAI can't pick the microphone; Windows does.**
  Press **Show microphones** to see which ones are available, then **Windows sound
  settings...** to change it: right-click the one you speak into on the Recording tab and
  choose "Set as Default Device". If another microphone is available, the test names it
  for you.
- *Sound arrived but nothing matched* — the mic is fine and the wording is the problem.
  Check the phrasings above, or drag "How sure it must be" left.
- *It understood you* — the mic and the wording are both fine. If it still misses you in
  the air, that's usually game audio drowning you out; turn on push-to-talk.

The test also names any problem the recogniser has with your signal — too quiet, too
loud, too much background noise — and shows a level bar so you can see sound arriving.

Stop listening before testing; only one thing can hold the microphone at a time.

**It hears me on a headset but not through speakers.**
With speakers, the game and ATC's own voice go back into your microphone, and the
recogniser has to pick you out of all of it. Run **Test microphone** while the game is
playing — if it reports too much background noise, that's the cause. Push-to-talk fixes
it outright, because the mic is only open while you hold the key.

**It reacts when I wasn't talking to it.**
Turn on **"Only listen while I hold a key"** on the "Talking to ATC" tab and pick a key — useful if
you're on Discord or TeamSpeak while flying. You can also drag the "How sure it must be"
slider right, or tick "Only react to the exact request".

**Windows says the app is unsafe / my antivirus flagged it.**
See [Is it safe?](#is-it-safe).

**Something else.**
The **Log** tab records everything the manager does. That's the first place to
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

## What it doesn't do

- Multiplayer. Voice commands would reach every aircraft.
- Taxiway names — DCS doesn't expose them to scripts, so instructions stay general.
- Understand free-form speech. It knows a fixed set of requests, though you can wrap
  anything around them.
- Give each airfield its own ATIS frequency. DCS doesn't define one, so there's a single
  ATIS channel carrying the nearest field's information.
- Report visibility or cloud in the ATIS — the sim doesn't expose either to scripts.
- Push-to-talk on anything but Windows.
- Check that you're on the right frequency before accepting a request. ATC replies on the
  field's real frequency, so you need to be tuned in to hear it — but it will answer a
  request made on any frequency at all.
