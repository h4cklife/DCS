# Changelog

## 1.8.0 - 2026-10-29

### For players

- **A startup splash screen.** The ATCAI banner shows for at least five seconds while the
  Manager opens, centred and borderless at its exact size. Click it, press **Dismiss** or
  hit Escape to skip the rest of the wait.

  "At least five seconds" cuts both ways: a fast start is held to the full five, and a
  slow one is never cut short — nor does it wait five seconds *on top* of a slow start.

- **The Manager window now opens centred too**, by the same arithmetic as the splash, so
  the banner is replaced where it stood instead of the window jumping to wherever Windows
  would have cascaded it.

  Being straight about what it is: **branding, not a progress indicator.** A single-file
  exe spends several seconds unpacking before Python exists, and nothing drawn by the app
  can appear during that. Covering that gap needs PyInstaller's bootloader splash, which
  is a different mechanism and was deliberately left out rather than bolted alongside.

- **The README banner now displays on GitHub.** It pointed at `../assets/ATCAI_Banner.png`
  — outside the module, at a path that had never been committed — so it had only ever
  rendered on the author's machine. It now points inside `ATCAI/`.

### For developers

- `assets/ATCAI_Splash.png` (724x242) is generated from the 2172x724 banner by
  `tools/make_splash.py`, and is the only one of the two bundled into the exe.

  It is a build step rather than a runtime resize for two reasons. Tk can only shrink by
  dropping pixels, which at 3x discards eight of every nine and leaves text ragged; this
  averages each 3x3 block instead, which is a real resample. And it keeps 2 MB of banner
  out of a 10.7 MB exe in favour of 382 KB.

  Standard library only — no Pillow, which would have added roughly 10 MB for one image.
  A test asserts nothing under `manager/` imports it, and another asserts the splash still
  matches the banner's aspect ratio, which is the one way the two files can drift.

- The splash lives in `manager/splash.py` and is driven from `main()`, not `App`, so the
  GUI tests do not have to dismiss a banner they never asked for. It is shown **after**
  the single-instance check: were it first, a second copy would flash a banner and vanish,
  which reads as a crash rather than as "already running".

- Every failure path ends in "no splash, carry on" — missing file, undecodable image, a
  Python with no tkinter, no display. A splash screen that can stop the Manager opening
  would be worse than no splash screen.

## 1.7.2 - 2026-10-29

### Fixed

- **ATCAI could not see most of DCS's default keyboard bindings.** `readbindings.lua`
  stubbed out `defaultDeviceAssignmentFor` on the belief that it resolved against DCS's
  internals. It does not — `Scripts/Input/DefaultAssignments.lua` loads standalone and
  returns a plain table keyed by device. **29 controls on the F-15C were reported as
  having no key when they were bound all along**, including `Flaps Up` (LCtrl+F) and
  `Flaps Landing Position` (LShift+F). Resolving the table properly takes that count to
  **zero**.

  Only the Keyboard device is read. A control bound to a stick axis or button stays
  unresolved rather than being turned into a plausible-looking key, and the log now says
  that is what happened instead of "no literal key", which read as "unbound".

  Making those controls *readable* does not make them *reachable*: `Eject (3 times)`,
  `Weapon Release`, `Weapon Fire` and `Countermeasures Release` are in the same table and
  are still refused by control name, with a test asserting it.

### Changed

- **Flaps are now "flaps up" and "flaps down" instead of a toggle.** The bare phrase
  "flaps" is gone, and so are "toggle flaps" and "flaps now".

  "flaps" was one word with no state condition, and it was the **only false trigger ever
  measured that reached an aircraft control** — game audio over desktop speakers pressed
  `F` in flight. The toggle went too, for a separate reason: its result depends on where
  the flaps are now, which DCS does not publish, so "flaps up" driving a toggle *lowers*
  flaps that are already up. That is the opposite of the request, at the one moment
  someone would make it. Two commands that name a direction cannot do that.

  An airframe that only binds the toggle will refuse both directional commands with a
  reason; `cockpit/controls.json` says how to add it back if you need it.

## 1.7.1 - 2026-10-28

Fixes for 1.7.0, found in the first flight test.

### Fixed

- **ATC voice commands did not work at all in the 1.7.0 exe.** The new phrase list
  resolved to the wrong folder inside the packaged build — `<extraction>/phrases/`
  instead of `<extraction>/voice-bridge/phrases/` — so it loaded as empty and **every
  ATC request was missing from the recogniser's vocabulary**: no mayday, no taxi, no
  landing, nothing. Running from source was unaffected, which is why the whole test
  suite passed.

  The symptom to recognise, if it ever happens again: the Log tab reports the size of the
  vocabulary when listening starts. It should say **128 phrasings**. 1.7.0 said 38.

  A test now builds a fake extraction folder from the packaging list itself and makes
  every module find its own bundled files there, so this class of bug cannot pass again
  for any file, not just this one.

- **Comms-menu commands now have their own confidence floor** (0.70 by default, adjustable
  on the Comms Keys tab), applied only when the keys are pressed for real. They had been
  sharing ATC's lower threshold of 0.60 despite pressing keys into DCS exactly as cockpit
  commands do — and a false "flight return to base" costs more than a missed radio call.
  Measured: background noise ordered a test flight home nine times, two of those at 0.65
  and 0.67.

  Worth being plain about the limits — the other seven were 0.84 to 0.93, so a floor
  catches the tail and nothing more. In a room with other people or music in it,
  **push-to-talk** is the only complete answer.

- **The Manager now says when your cockpit control list is missing shipped controls.**
  Seeding only ever adds a file; it never merges into one that already exists. So a copy
  made when the list held two controls kept two for ever, and four shipped controls —
  flaps, airbrake, canopy, lights — were silently absent, with no symptom but a command
  that did nothing. The AI Cockpit tab names what is missing and what to press.

### Changed

- **A claim withdrawn from the 1.7.0 docs**: that switching a source off makes the
  remaining commands more reliable because there is less to confuse. It was written as
  though established, on no evidence. The accidental 38-phrase vocabulary above was the
  first test of it and pointed the other way — Windows returns the best match among the
  phrases available, so removing competitors can concentrate noise on the survivors
  instead of spreading it thin. One run with music and a door opening in it is not proof
  either; vocabulary size is now documented as unmeasured. Switch a command off because
  *it* misfires, not to improve the others.

## 1.7.0 - 2026-10-28

### Changed — read this one

- **Distress calls are now "mayday mayday mayday". A single "mayday" and "pan pan" no
  longer work.** Real procedure says three times, and measurement says the same thing
  for a blunter reason: with a jet running, a keyboard in use and ATCAI's own replies
  audible, the short forms produced **22 false emergency declarations in ten minutes**,
  at a median confidence of 0.92 — so raising the confidence bar could never have caught
  them. 20 of the 22 were "pan pan", which ATCAI did not treat differently from a mayday
  anyway. The three-repetition form measured 12 for 12 at 0.91–0.95.

  The cost is real and accepted: *"mayday mayday, Chevy 81, engine fire"* no longer
  registers. Say it three times. Full measurements in
  [docs/FALSE-TRIGGERS-PLAN.md](docs/FALSE-TRIGGERS-PLAN.md).

### For players

- **New: the Voice Commands tab.** Every command ATCAI knows, grouped by source, with a
  tick box and an editor. Untick one and it is **removed from the recogniser's
  vocabulary entirely** — not heard and then ignored, which is the difference between
  noise having nothing to match and noise still being able to match. Press **Edit...**
  to change what you say: "wheels up" instead of "gear up", or whatever you reach for.

  This exists because your room is the one thing that cannot be measured from here. A
  dog, a television, a passenger or a fan will trip some phrase, and which one is nobody's
  guess. Switching off a command you never use costs nothing.

  It does **not** reliably improve the commands you keep — an earlier draft of this entry
  said it did, and the first run that could test the idea suggested the opposite. See
  1.7.1.

  The editor refuses a phrase the grammar cannot carry, or one that already means
  something else — naming what — and warns about a phrase under about eight characters,
  because that is the shape that caused the emergency problem above.

- **Say "cancel emergency"** to lift one, or use **Cancel emergency** in the comms menu.
  There was previously no way to un-declare at all.

- **Your phrase changes survive updates properly.** They are stored as *differences* in
  `%LOCALAPPDATA%\ATCAI\phrases.json`, not as a copy of the whole list — so a new
  release's new commands and corrected phrasings still reach you even for commands you
  have customised. A whole copy could not do that: your edit and an out-of-date default
  would be indistinguishable.

### Fixed

- **A false mayday no longer snowballs.** Nothing checked whether an emergency was
  already running, so each repeat triggered another transmission — 22 triggers produced
  8 of them, and a tower that kept re-clearing a pilot who was already cleared. A repeat
  declaration is now silent. ("cancel emergency" exists partly because of this: without
  it, one stray call would have suppressed a real one for the rest of the sortie.)

- **Which emergency phrase won depended on dictionary order.** The matcher returned on
  the first priority phrase it happened to scan instead of the longest, so a shorter
  distress phrase could beat a longer one. Harmless while every emergency phrase meant
  the same thing; not harmless now the list has both a triple mayday and
  "emergency landing" in it.

- **`tools/phrase_separability.py` gave advice opposite to its own data.** It counted
  "the matcher routed this elsewhere" as a misrecognition and told you to re-phrase,
  when the words had been heard perfectly. It also read one recognition at a time, so it
  could not see that two events were one utterance the recogniser split because the
  phrases were said too fast — which is what produced every flagged line in the run that
  exposed this. It now separates the two outcomes, gives different advice for each, and
  warns when recognitions arrive too close together to trust.

### For developers

- The ATC phrase list moved out of `atcai_listen.py` into
  `voice-bridge/phrases/atc_defaults.json`, so it can be read and diffed without reading
  Python and sits alongside the comms and cockpit maps. It is **shipped defaults,
  read-only, and deliberately never copied into the player's folder** — see
  `atcai_phrases.py` for why that matters.
- New `atcai_phrases.py` owns the defaults, the player's overlay, the merge and the
  phrase validation, and is used by **both** the listener and the manager: two readers of
  one format is how formats drift, and the tab must not be able to disagree with the
  recogniser about what will be heard.
- The overlay can re-word a command that exists but **cannot create one**, which is what
  keeps phrase editing away from the controls `DENY_PATTERNS` refuses.
- `run()` now refuses to start on an empty vocabulary rather than handing
  `recognize.ps1` an empty grammar.

## 1.6.1 - 2026-10-26

### For players

- **Documented where your files are.** One place in the guide listing everything the exe
  copies out and where it puts it, so the editable command lists are findable without
  hunting: `%LOCALAPPDATA%\ATCAI\keymaps\` and `...\cockpit\`. Also says which tab
  creates them, that your edits survive updates, and that uninstalling leaves them alone.

### Fixed

- **A packaging test that only covered half the files it claimed to.** It checked that
  every `.ps1` helper was bundled into the exe, but nothing covered `readbindings.lua`
  or the JSON command lists — so either could have been dropped from the build with no
  test failing, and the only symptom would have been every cockpit control reading as
  unknown in the released exe. It now asserts every non-Python runtime file is bundled,
  as a directory scan rather than a list, so files added later are covered without
  anyone remembering to extend it.

  Nothing was actually missing from 1.6.0 — this closes the gap that would have let it
  happen unnoticed.

## 1.6.0 - 2026-10-25

### For players

- **Work cockpit controls by voice.** Say "gear up", "gear down", "flaps", "airbrake
  out", "canopy" or "nav lights" and ATCAI presses the key for you. A new **AI Cockpit**
  tab, off by default behind two switches like the comms keys.

- **The key combinations come from DCS, not from ATCAI.** They are read out of your own
  binding files, including anything you have rebound — so if you have gear on a different
  key than standard, it already works. Change a binding in DCS's options and press
  **Re-read bindings**.

- **It knows when not to.** "Gear up" is refused while you are on the ground, and
  "canopy" is refused in flight. "Gear down" is allowed on the ground, because lowering
  gear you already have down is harmless.

- **Destructive controls are refused in code** — eject, jettison, engine shutdown,
  weapons release, master arm, countermeasures. Not merely left out of the list: they
  cannot be enabled by editing it, because the failure is unrecoverable in a way a wrong
  menu press is not.

- **Its own confidence setting**, separate from ATC's. "Gear up" and "gear down" differ
  by one word and have opposite effects, so the bar for acting on them is set apart from
  the bar for answering a radio call.

- Phrases are yours to change, in `%LOCALAPPDATA%\ATCAI\cockpit\controls.json`.

### Fixed

- **Every voice switch now says when it takes effect.** The recogniser reads its
  settings once, when listening starts, so ticking a box did nothing until you stopped
  and started — and said nothing about it, which is indistinguishable from a broken
  feature. All four switches now report the change and whether a restart is needed.

### Known limitations

- Wheel brakes were dropped. DCS exposes them as separate left/right toggles, which
  reads badly as speech, and brakes belong under your hand rather than your voice.
- Nothing confirms a control actually moved. DCS reports neither, so the log can only
  say the keystroke was accepted.

## 1.5.0 - 2026-10-25

### For players

- **Pick your microphone.** The Test Microphone tab now has a dropdown listing every
  microphone available, so ATCAI no longer has to use whichever one Windows happens to
  have as default. Choose *Windows default* to behave as before — it shows you which
  device that currently means.

  This sets the microphone for **speech programs only**. Windows' own default recording
  device is left alone, so Discord, SRS and everything else are unaffected. Restart
  listening after changing it.

### Fixed

- **Only one Manager can run at a time.** Starting a second copy now brings the first to
  the front instead of opening another window. Two copies each started their own voice
  bridges, so ATC replies were spoken twice and both fought over the microphone —
  symptoms that looked like faults in the module rather than like two copies running.

## 1.4.0 - 2026-10-24

### For players

- **Talk to your wingmen and to AWACS.** Say "two rejoin", "three engage bandits",
  "flight return to base", "awacs picture" or "bogey dope" and ATCAI works DCS's own
  comms menu for you. Eleven commands for the F-15C.

  This is different from everything else ATCAI does: it **presses keys in the game**
  rather than only reading it, so it can change what your flight does. It is **off by
  default**, behind two separate switches on the new **Comms Keys** tab — one to listen
  for the commands, another to actually send them.

- **Keys are only ever sent while DCS is the active window.** Alt-tab away mid-command
  and the rest of the sequence is dropped rather than typed into your browser.

- **It knows who is still flying.** "Two rejoin" is refused with *"two is not with you"*
  if two is gone. And because DCS renumbers its wingman menu entries by position among
  the survivors — with two dead, three moves to F2 — the key is worked out from who is
  actually left, not assumed.

- **A Test keys in Notepad button**, which types into Notepad instead of DCS. If nothing
  arrives there, Windows is refusing synthetic keystrokes and no key map will help —
  worth knowing separately from a wrong sequence.

- **What you say is yours to change.** Each command's phrases live in a plain text file
  under `%LOCALAPPDATA%\ATCAI\keymaps\`, put there the first time you open the Comms
  Keys tab. Edit the phrases, restart listening, done — and your edits are never
  overwritten by an update.

- **Maps for all four stock modules** — F-15C, A-10A, Su-25T, TF-51D. Only the F-15C has
  been flown; the others are copies of it, so they **dry-run only and refuse to press
  anything** until you've checked them against the real menu and marked them verified.
  An aircraft with no map is refused by name rather than guessed at.

### Known limitations

- Only the F-15C is verified. The other three ship unverified and cannot press keys
  until you confirm them. Menu trees differ per module, so each needs its own map.
- Nothing confirms a command was carried out. DCS reports nothing about AI tasking or
  comms selections, so the log can only say the keystroke was accepted by Windows.
- A DCS patch that moves menu entries would need the map updating.
- Multiplayer is unaffected — this cannot command other humans.

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
