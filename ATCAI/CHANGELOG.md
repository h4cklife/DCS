# Changelog

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
- ATC transmits on a fixed list of frequencies rather than each airfield's real one.
- Taxi instructions don't name taxiways — DCS doesn't expose them to scripts.
- Speech recognition knows a fixed set of requests, though you can say anything around
  them.
