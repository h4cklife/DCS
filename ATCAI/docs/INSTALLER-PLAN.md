# ATCAI Manager — design plan

**Status: built and shipped in v1.0.0.** Kept as the record of what was decided and why,
including the question that shaped the whole thing (can ATCAI load into every mission?)
and the answer. Phases are marked done below.

Goal: the user downloads one program, runs it, clicks Install, and ATCAI works. No
copying Lua files, no command lines, no editing scripts to change a setting, no Mission
Editor.

## What installing costs today

Everything below is manual, and every item is a place to get it wrong:

1. Copy four `.lua` files into `<Saved Games>\DCS\Scripts\ATCAI\`.
2. Run `tools/build_test_mission.py` from a shell, passing four absolute Windows paths,
   to produce a playable mission.
3. Run `voice-bridge/atcai_listen.py` in one terminal for voice input.
4. Run `voice-bridge/atcai_tts.py` in another for spoken replies.
5. Know whether to use `--mode srs` or `--mode local`, and why.
6. Edit Lua source to change the radio frequency, ATC ranges, or traffic thresholds.
7. Have Python installed at all.

It also requires understanding things a user shouldn't have to: that DCS flies an
editor-held mission from a temp copy, that SRS needs its client running before DCS, that
the comms menu is `\` and not F10.

## Target experience

1. Download `ATCAI.exe` (Windows) or run `atcai` (Linux). Nothing else to install.
2. It finds the DCS installation itself.
3. One **Install** button. One **Enable/Disable** switch.
4. A settings panel for the things people actually change — radio frequency, how far out
   ATC answers, voice sensitivity — with no Lua editing.
5. Voice input and spoken replies start and stop from the same window, with a visible log
   so it's obvious when something isn't working.
6. **Uninstall** removes everything it added.

## Resolved: ATCAI loads into every mission

**The spike succeeded.** Calling `a_do_script(<lua source>)` from the Hook — rather than
the `a_do_script_file(<path>)` that silently failed — loads ATCAI into any mission,
verified in a stock mission that was never patched. Installation can therefore be a true
one-click affair: copy the scripts, copy the hook, restart DCS. Per-mission patching is
no longer part of the product (the mission builder remains for making self-contained
missions and setting start times).

Phase 2 of the plan below is also done: settings now live in a generated `config.lua`
rather than in Lua source, which is what lets a GUI drive them.

The original analysis is kept below for the record.

## The question that decides the shape of this (resolved — see above)

**Can ATCAI load into any mission automatically, or must each mission be patched?**

Right now the loader trigger is injected into a `.miz`, so ATCAI only exists in missions
built by our tool. For a one-click installer that's a poor fit: "installed" would not
mean "working", and a campaign's stock missions would never have it.

The Hooks-based autoloader was meant to solve exactly this and failed. But the earlier
diagnosis now looks wrong in an informative way:

- We called `a_do_script_file(<filesystem path>)` from the Hook. That silently did
  nothing — most likely because "DO SCRIPT FILE" *embeds* the script into the `.miz` as a
  mission resource, so the function almost certainly wants a resource key, not a path.
- Meanwhile `a_do_script(<lua source>)` **is** known to work: it's exactly what our
  injected mission trigger runs, successfully, every flight.

So the untested combination is calling the *working* function from the Hook:

```lua
net.dostring_in("mission", "a_do_script([==[dofile([[C:\\...\\atc_core.lua]])]==])")
```

If that works, installation becomes genuinely one-click and ATCAI applies to every
mission, including campaign missions we can't modify. **This should be spiked before any
GUI work**, because a negative result changes the product: the installer would instead
have to offer "patch a mission" as an explicit, per-mission action.

Either way the GUI is worth building. The spike decides whether its main verb is
"install" or "install, then patch each mission you want to fly".

## Architecture

**Language: Python + Tkinter, packaged with PyInstaller.**

- Tkinter ships with Python, so there's no GUI dependency to install, and it works on
  both Windows and Linux.
- PyInstaller produces a single `ATCAI.exe` with Python bundled, so the user needs
  nothing preinstalled.
- Most importantly it **reuses the code that already works**: `build_test_mission.py`,
  `atcai_listen.py` and `atcai_tts.py` become modules the GUI calls rather than scripts
  the user runs. A rewrite in C#, Go or Electron would throw that away.

**Settings move out of Lua source.** The GUI writes `Scripts\ATCAI\config.lua`:

```lua
ATCAI_CONFIG = { tts_frequency = "276.375", airbase_air_radius = 92600, ... }
```

`atc_core.lua` loads it if present and applies the overrides, keeping its current values
as defaults. This avoids the GUI having to parse and rewrite Lua source, which would be
fragile, and keeps the scripts usable standalone for anyone who prefers that.

**The bridges run in-process.** Rather than spawning two terminals, the GUI runs the
listener and TTS loops on background threads and pipes their output into a log pane, with
Start/Stop buttons. Their existing structure (a loop over a stream) already suits this.

## What the window contains

- **Status** — DCS found at *path*; installed yes/no; enabled yes/no; SRS server
  running; microphone available. Each with a plain-language fix when it's wrong.
- **Install / Uninstall / Enable / Disable.**
- **Voice** — Start/Stop listening, sensitivity slider (`--min-confidence`), strict-vs-
  flexible matching, and a live list of what it heard, so misrecognition is visible
  rather than mysterious.
- **Replies** — Start/Stop, choice of SRS or local audio, voice and frequency settings.
- **ATC behaviour** — ground and airborne ranges, traffic sensitivity.
- **Missions** — only if the hook spike fails: pick a `.miz`, patch it, set start time.
- **Log** — one place to look when something doesn't work.

## Phases

1. ~~**Spike the Hook loader.**~~ **Done** — works; ATCAI loads into every mission.
2. ~~**Config file support in Lua.**~~ **Done** — `config.lua` overrides, 18 tests.
3. ~~**Installer core, no GUI.**~~ **Done** — `manager/installer.py`, 58 tests. Finds DCS
   via the Windows registry (Saved Games is routinely relocated by OneDrive) with
   fallbacks, refuses to silently accept a folder that doesn't look like DCS, and
   handles install/uninstall/enable/disable and settings.
4. ~~**GUI.**~~ **Done** — `manager/app.py`, 33 smoke-test checks driving the real
   window (install, enable/disable, settings round-trip, input validation, log pane).
5. ~~**Packaging.**~~ **Done** — `manager/build_exe.py` produces a single 10 MB
   `ATCAI-Manager.exe` with Python, Tkinter, the Lua scripts and the speech recogniser
   bundled. Verified to launch.

Phases 2 and 3 carry the real risk of breaking what works today; 4 and 5 are mostly
presentation. The order lets us stop after 3 with a working CLI installer if the GUI
turns out not to be worth it.

## Honest limitations

- **Linux is a partial story.** DCS doesn't run natively on Linux, and the voice
  features depend on Windows components (PowerShell, System.Speech, SRS). A Linux build
  is useful for the WSL-style setup where DCS lives on a mounted Windows drive, but voice
  input and spoken replies will still be driving Windows underneath. This should be
  stated in the UI rather than discovered.
- **PyInstaller executables get flagged by antivirus** with some regularity. It's a known
  false-positive pattern, but it will happen to someone.
- **Uninstall can only remove what we installed.** Missions patched by the old mission
  builder keep their trigger; those calls fail harmlessly once the scripts are gone, but
  the trigger stays in the file. The GUI should say so rather than implying a clean sweep.
  Uninstall deliberately leaves unrelated files in `Scripts/ATCAI/` alone, and keeps the
  folder if any remain.
- **Changes need a DCS restart.** Hooks are read at startup, so installing or enabling
  while DCS is running does nothing until it restarts. The installer reports whether DCS
  is running so the app can say this rather than leaving the user puzzled.

## Answered

1. **Distribution:** a single `.exe`.
2. **Audience:** other DCS players, so detection warns rather than assumes, and errors
   have to be legible to someone who has never read this repo.
3. **Detection:** auto-detect, but show a warning and let the player choose the folder
   when nothing is found or the guess is unverified.

## Build notes

PyInstaller does not cross-compile, so a Windows `.exe` must be built with **Windows**
Python — WSL's Python can only produce a Linux binary. Windows Python 3.12 plus
`pip install pyinstaller` is the only developer dependency; people you give the exe to
install nothing.

One trap worth remembering: Windows Python launched from a `\\wsl.localhost\...` path
resolves a rooted read of `/proc/version` onto the WSL share, so a naive "am I in WSL?"
check reports true while running natively on Windows. Check `os.name` first.

## Open questions
4. ~~If the Hook spike fails...~~ Moot: it succeeded.
