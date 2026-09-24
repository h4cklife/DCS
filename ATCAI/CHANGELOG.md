# Changelog

## 1.3.0 - 2026-09-23

### For players

- **A Test Microphone tab.** Press the button and it listens for fifteen seconds, then
  tells you what ATCAI can actually hear: which microphone Windows handed it, a live
  input level, any complaint the recogniser has about the signal (too quiet, too loud,
  too much background noise, no signal at all), and everything it heard — **including
  speech it heard but couldn't match**, which is invisible while flying. It ends with a
  plain verdict instead of leaving you to interpret the output.

  Those two cases being told apart is the point. "It can't hear me" and "it hears me but
  the words don't match" look identical in the air, and they need opposite fixes.

- **It names the microphone in use, and lists the others.** ATCAI can't choose the
  recording device — Windows does — so the wrong one being selected was both a likely
  cause of silence and completely invisible. **Show microphones** lists the devices that
  are actually active, marking the one ATCAI will get. If a test hears nothing and
  another microphone is available, the verdict names it.

- **Windows sound settings...** opens Windows' Recording tab directly, which is where the
  default device is changed.

- The test no longer contradicts itself. The recogniser reports "no signal" during
  ordinary pauses in speech, so a perfectly good microphone produced *"no audio at all
  from the microphone"* between every sentence it had just understood. Signal complaints
  are now judged at the end, against whether anything was actually heard, and each is
  stated once. Complaints that still matter when the words got through — too quiet, too
  noisy — are kept.
- The verdict is printed once, not twice.
- The "no signal" message no longer claims the microphone is broken. It fires whenever
  the room goes quiet, so it now says as much and only suggests checking the microphone
  if you were actually speaking — including the headset's own mute switch, which is what
  caused it in practice.

- **The level meter is measured at the device, not inferred from the recogniser**, and
  every active microphone is measured, not just the one in use. So instead of "nothing
  was heard at all", a dead default microphone now reads as *"the microphone in use
  produced no sound at all, but Microphone (Scarlett 2i2 USB) did"* — which names the one
  to switch to. It also points out that Windows keeps a separate **default
  communications device**, so setting only the default device may not be enough.

### Changed

- **The Voice tab is now three tabs** — *Talking to ATC*, *Test Microphone* and *Hearing
  ATC* — and **the log has a tab of its own**. Everything had been stacked on one tab
  taller than the window, and the log sat below it taking height from every tab whether
  you were reading it or not, so controls below the fold were invisible unless you
  resized. The window now opens at 900x700 and won't shrink below the point where tab
  contents start clipping.
- **Settings boxes show what each setting actually is**, with the stock value named
  underneath, instead of sitting blank until you type in them. A blank box read as "not
  set" when it meant "using the default", so there was no way to tell what ATC was using.
  **Back to defaults** now fills the boxes rather than emptying them.

### Known limitations

- **ATCAI still follows the Windows default microphone.** It can report and advise, but
  not choose. `System.Speech` has no way to select a device, and the private interface
  other tools use to change the Windows default is not a trade worth making here — see
  `docs/PLAN.md`. Making ATCAI capture from a device of its own choosing is written up
  there as the next substantial piece of work.

### For developers

- `voice-bridge/mictest.ps1` and `voice-bridge/atcai_mictest.py`, deliberately separate
  from the recognition path so a diagnostic can't break it. Device name and enumeration
  come from a small Core Audio COM interop; both are best-effort and the test still runs
  if they fail.
- `tests/test_wiring.py` gained two guards for failures that are silent by nature: every
  `.ps1` used at runtime is in the exe's bundle list (missing only in the built exe, never
  from source), and the manager's copy of the Lua config defaults still matches
  `atc_core.lua` (a drifted copy would display a value ATC isn't using).
- A test asserts the manager's tab set, since nothing errors when a panel is off-screen.

## 1.2.0 - 2026-09-21

### For players

- **Declare an emergency** — say "mayday", or use the comms menu. ATC clears you to land
  immediately without being asked, stops sequencing you behind other traffic, never sends
  you around, and answers from any distance rather than the usual 50-mile ATC range. It
  ends when you taxi to parking. A mayday is heard even when there's another request in
  the same transmission.
- **Request vectors** — a heading and distance to the nearest field your coalition can
  actually use. Enemy fields are never offered, and a closer hostile field is skipped in
  favour of a friendly one further away.
- **Request a straight-in approach** — skip the circuit. Traffic ahead delays it rather
  than refusing it.

### Fixed

- **Replies you couldn't hear.** Anything answered away from a field went out on the
  fallback frequency list only, which shares no frequency with the field you were
  actually tuned to - so a refusal, a loadout check or an emergency call appeared as
  on-screen text with nothing over the radio. Those replies now transmit on the field's
  frequencies *and* the fallback list at once. Routine clearances are unchanged and stay
  on the field's own frequency.
- **Loadout is no longer refused for being out of range.** It reports your own aircraft's
  stores, so it never needed a control tower in the first place.
- Refusals are now transmitted as well as shown on screen. "No ATC in range" that you
  couldn't hear was indistinguishable from the module being broken.

### Verified in flight

Emergencies, vectors and the straight-in approach have all been flown, as has the fix
that made those replies audible.

### Known limitations

- Ordinary clearances still aren't coalition-checked: only diverts and vectors are, so a
  routine request can be answered by whichever field is nearest, enemy included.
- Bearings are true, not magnetic — DCS exposes no magnetic variation to scripts.

## 1.1.0 - 2026-09-20

### For players

- **ATC uses each airfield's real frequencies.** Read from DCS's own terrain files when
  you install, so Batumi answers on Batumi's frequencies and Vaziani on Vaziani's - the
  same numbers DCS's built-in ATC menu shows. Tune in and you hear ATC; don't and you
  won't, the way a radio should behave.
- **Ask for airfield information.** A spoken ATIS: information letter, time, runway in
  use, wind, temperature and altimeter.
- **A repeating ATIS broadcast** on its own frequency (380.000 AM by default, once a
  minute), carrying the information for whichever field you're nearest. Change the
  frequency on the Settings tab, let the manager pick an unused one, or turn the loop off.
- **Push-to-talk, if you want it.** Off by default, so ATC keeps listening all the time
  unless you choose otherwise. Turn it on in the manager and pick any key - useful if
  you're on Discord or TeamSpeak while flying.

### Fixed

- The manager warns when an ATIS frequency clashes with a real airfield, or falls outside
  the band most aircraft radios can tune.
- `build_test_mission.py --start-time` now actually sets the mission clock. It was
  matching the first `["start_time"]` anywhere in the file, which in a stock mission
  belongs to some ground group rather than the mission - so it quietly shifted that
  group's spawn delay and left the mission at whatever hour it shipped with. Every test
  mission built so far started at 19:40 regardless of what was asked for; rebuild one to
  get the daylight you wanted.

### For developers

- `tools/build_test_mission.py` can populate a mission: `--traffic N` adds AI flights
  operating from the player's own field (the only practical way to exercise traffic
  awareness solo), `--ground N` scatters enemy vehicle groups around the airfields with
  optional `--ground-defended` AA cover, and `--enemy-air N` adds hostile fighter flights
  that are airborne, tasked to engage and active from the moment the mission starts.
  It refuses to overwrite an existing mission without `--force`.

### Verified in flight

Everything in this release has been flown: per-airfield frequencies, the ATIS loop on
380.000, traffic awareness (holds and sequencing against AI flights using the same
runway), and push-to-talk.

### Known limitations

- **Transmitting isn't frequency-checked.** ATC answers on the field's real frequency, so
  you have to be tuned in to hear it — but it will take a request made on any frequency,
  or with the radio off entirely. Speech recognition runs outside the sim and can't see
  your radio, so push-to-talk gates the microphone rather than the radio.

## 1.0.0

First release.

### For players

- **Talk to ATC by voice, and hear it answer.** Ask for a radio check, startup, taxi,
  takeoff, a circuit join, landing, taxi to parking, or your remaining weapons.
- **Works in every mission** — Instant Action, your own missions, campaigns. Nothing to
  set up per mission.
- **ATC uses the real weather.** The runway in use follows the wind, and clearances carry
  the current wind and altimeter setting.
- **Requests are checked against your situation** — no takeoff clearance from a parking
  spot, no landing clearance while parked. Refusals say why.
- **ATC watches the runway** and will hold you, sequence you behind landing traffic, or
  send you around rather than clearing you into a conflict.
- **Speak naturally.** "Chevy 81, requesting taxi to one three" works as well as
  "request taxi"; your callsign, the tower's name and a runway can all be in the call.
- **One program does everything** — `ATCAI-Manager.exe` installs it, turns it on and off,
  changes settings, and starts voice. No command line, nothing else to install.
- ATC replies can come out of your speakers, or over the radio through SimpleRadio
  Standalone.

### Known limitations

- Single-player only. In multiplayer, voice commands would reach every aircraft.
- Taxi instructions don't name taxiways — DCS doesn't expose them to scripts.
- Speech recognition knows a fixed set of requests, though you can say anything around
  them.
