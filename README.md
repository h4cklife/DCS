# DCS modules

Modules and tools for [DCS World](https://www.digitalcombatsimulator.com/), developed by
[h4cklife](https://github.com/h4cklife).

Each module lives in its own folder with its own documentation, tests and releases.

## [ATCAI](ATCAI/) — talk to DCS, and have it talk back

[![ATCAI build](https://img.shields.io/github/actions/workflow/status/h4cklife/DCS/atcai-ci.yml?branch=main&label=build&logo=github)](https://github.com/h4cklife/DCS/actions/workflows/atcai-ci.yml)
[![Latest release](https://img.shields.io/github/v/release/h4cklife/DCS?filter=atcai-v*&label=release)](https://github.com/h4cklife/DCS/releases)
[![Licence](https://img.shields.io/github/license/h4cklife/DCS)](LICENSE)
[![Bitcoin](https://img.shields.io/badge/Bitcoin-donate-f7931a?logo=bitcoin&logoColor=white)](#support-the-project)
[![Ethereum](https://img.shields.io/badge/Ethereum-donate-3c3c3d?logo=ethereum&logoColor=white)](#support-the-project)

A voice interface for single-player DCS. It began as an air traffic controller and grew
outwards: it now also commands your flight, queries AWACS, and works your own cockpit
switches.

**The ATC is ATCAI's own.** Ask for startup, taxi, takeoff, a circuit join or landing and
hear it answer — using the real wind, the real altimeter, and whichever runway suits the
weather. Each airfield replies on its own real frequencies, read from DCS's terrain files.
There's a spoken ATIS and a looping broadcast, traffic awareness that holds and sequences
you, and emergencies that get you priority and an answer from any distance.

**The rest is DCS's, driven for you.** Say *"two rejoin"*, *"flight engage bandits"*,
*"awacs picture"* or *"gear up"* and it works the menus and switches you would otherwise
reach for by hand. Mission scripting cannot touch those, so this part presses keys — it
is off by default, and cockpit key combinations are read from your own DCS bindings
rather than assumed. Eject, jettison, engine shutdown and weapons release are refused in
code and cannot be turned on.

Everything works from the comms menu too, so voice is a convenience rather than a
requirement. Loads into every mission — stock, custom or campaign — with nothing to set
up per mission.

- **[Getting started](ATCAI/GETTING-STARTED.md)** — for players. Download, install, fly.
- **[Developer README](ATCAI/README.md)** — the full command list, how it works, how to
  build and test it.

Single-player only. One program installs and configures it; no command line.

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

## Licence

[MIT](LICENSE).
