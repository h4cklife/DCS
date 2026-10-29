# Startup splash screen — plan

Status: **built and tested 2026-10-29**, shipped in 1.8.0. Not yet seen on screen by
anyone - the window tests assert its size, position and dismissal, but only a launch
confirms it looks right.

Built as planned, with two decisions settled during the work:

- **The resize became a build step, not a runtime subsample.** The plan had the full
  banner bundled and shrunk by Tk at startup. Tk can only shrink by dropping pixels, so
  at 3x it discards eight of every nine and leaves text ragged. `tools/make_splash.py`
  averages each 3x3 block instead - a real resample - and bundling only the result keeps
  2 MB of banner out of the exe in favour of 382 KB. Stdlib only; no Pillow is installed
  anywhere, and adding it would have cost ~10 MB for one picture.
- **Both ways out, as asked:** a Dismiss button, a click anywhere, and Escape, alongside
  the five-second timer.

A borderless window showing the ATCAI banner, centred on screen, for **at least five
seconds**, then the Manager appears.

## Three facts that decide the design

### 1. No new dependency is needed

Tk 8.6.15 (what the Windows Python ships) reads PNG natively, and `PhotoImage.subsample()`
shrinks by whole-number factors. So **no Pillow** — which would have added roughly 10 MB
to a 10.7 MB exe for one image.

The banner is **2172 x 724**, a 3:1 strip. Whole-number factors give:

| Factor | Size |
|---|---|
| 2 | 1086 x 362 |
| **3** | **724 x 242** |
| 4 | 543 x 181 |
| 5 | 435 x 145 |

**724 x 242 recommended** — it reads as deliberate against the 900 x 700 main window,
where 1086 is wider than the app and 543 looks incidental.

That answers the "exact size or shrunk to something acceptable" question: the splash is
sized **exactly** to the subsampled image, so there is no letterboxing and no stretching.
Subsampling is a clean integer decimation, not a resample, so the strip stays sharp.

### 2. The image is outside the module, and git does not know about it

`assets/ATCAI_Banner.png` sits at the **DCS repo root**, not inside `ATCAI/`. And
`git status` reports `?? assets/` — the whole folder is **untracked**.

Two consequences, one of them already live:

- **The banner at the top of `ATCAI/README.md` is broken on GitHub right now.** The file
  has never been pushed, so `../assets/ATCAI_Banner.png` resolves to nothing. It renders
  locally only because the file is on this machine.
- **Bundling it from `../assets/` would build fine here and fail in CI.** `atcai-ci.yml`
  and `atcai-release.yml` trigger on `paths: ["ATCAI/**"]` and check out only tracked
  files, so the released exe would be built without an image that works perfectly on this
  machine — exactly the shape of the 1.7.0 packaging bug, where everything passed from
  source and the exe was broken.

**So: copy the banner to `ATCAI/assets/ATCAI_Banner.png` and commit it.** The module stays
self-contained, the file sits inside its own CI path filter, and `README.md` can then point
at `assets/ATCAI_Banner.png` — which fixes the broken image as a side effect and drops the
parent-directory dependency.

2 MB on a 10.7 MB exe is the cost. The alternative is bundling a pre-shrunk 724 x 242 copy
(tens of KB) and keeping the full one for the README, but that is two files to keep in step
and they will drift. **One file, subsampled at runtime, is the recommendation.**

### 3. This splash cannot cover the real wait — and should not pretend to

A onefile exe spends several seconds unpacking itself before Python exists. Tk cannot draw
until after that. So a Tk splash appears **once the app is already ready**, not during the
delay you actually notice.

That makes this **branding, not a loading indicator**, and the plan treats it as such.
PyInstaller's own `--splash` is the only thing that covers the unpack gap, because it runs
in the bootloader before Python starts. It is a separate, later option and is deliberately
not mixed in here: two splash mechanisms for one feature is how a simple thing becomes
confusing to debug.

## Design

### Where it lives

In `main()` ([app.py:1827](../manager/app.py#L1827)), **not** in `App.__init__`.

`test_gui.py` builds `App` against its own `tk_root`, so a splash inside `App` would appear
in every GUI test and in anything that ever embeds the app. Keeping it in the launcher
leaves the window class untouched and makes the splash independently testable.

### Order of operations

**After the single-instance lock, never before.** The lock is the first thing `main()` does
today, and that must not change: if the splash came first, launching a second copy would
flash a banner and then vanish, which reads as a crash rather than as "already running".

```
lock.acquire()            -> second copy still exits quietly, as now
  show splash
  build the main window, withdrawn
  wait out the remainder of 5s
  destroy splash, deiconify main window
```

The main window is hidden until the reveal, so a half-built window never shows behind the
splash.

### Timing

"At least five seconds" taken literally: wait `max(0, 5000ms - elapsed)` after the window
is built. If the build takes seven seconds, the splash stays seven — it never cuts the
banner short, and it never adds five seconds on top of a slow start.

### Appearance

- `overrideredirect(True)` — no title bar, so the window is the image and nothing else.
- `-topmost` so it is not buried by whatever has focus.
- Centred with `winfo_screenwidth()` / `winfo_screenheight()`.
- A one-pixel border, so a dark banner on a dark desktop still reads as a window rather
  than a floating sprite.

### Click to dismiss

**Recommended.** Any click or key press skips the remaining wait.

The reason is practical: a hard five seconds on every launch will slow down *your* test
cycles, and you restart the Manager constantly while testing. Five seconds stays the
default for everyone else; you get to skip it.

### Failure is never fatal

Missing file, a PNG Tk cannot decode, no display: log one line and show the main window
immediately. A splash screen that can stop the app starting is strictly worse than no
splash screen.

## Bundling

`BUNDLED` in `build_exe.py` gains `(ROOT / "assets", "assets")`.

The `_MEIPASS` test added in 1.7.1 gains the splash image, so the thing that broke the
1.7.0 exe — code looking in a different folder from where the packager puts the file —
cannot happen here silently.

## Tests

| What | Test |
|---|---|
| The image ships and loads | the file exists, is a PNG, and `PhotoImage` reads it |
| Size is as intended | 2172 x 724 subsampled by 3 is 724 x 242, and the window matches it |
| No new dependency | nothing in `manager/` imports PIL |
| Lock comes first | a second instance shows no splash and still exits quietly |
| The five seconds | reveal is not called early, against an injected clock |
| A slow build wins | a seven-second build keeps the splash seven seconds |
| Dismissal | a click reveals the main window immediately |
| Failure paths | missing file, undecodable image, no display → the Manager still opens |
| Packaging | the `_MEIPASS` test covers `assets/` |

Timing and dismissal are tested against an injected clock and a directly-invoked handler,
not by sleeping — a suite that waits five real seconds per case is a suite people stop
running.

## What I need from you

1. **Run `git add ATCAI/assets/ATCAI_Banner.png`** once I copy it there — you own git. CI
   cannot build the splash until that file is committed.
2. **Size:** 724 x 242 (recommended) or 543 x 181.
3. **Dismissal:** click-to-skip (recommended) or a hard five seconds.

Nothing else; the rest is decided above.
