#!/usr/bin/env python3
"""Speak ATCAI's replies over SRS.

The DCS mission-scripting sandbox can't launch processes or write files, so the ATC
scripts emit their replies to dcs.log as:

    ATCAI_TTS|<freq MHz>|<AM|FM>|<text>

This tails that log and hands each line to SRS's DCS-SR-ExternalAudio.exe, which
transmits it as text-to-speech on the given frequency.

Requires the SRS server and client to be running, and your aircraft radio tuned to the
frequency ATC transmits on (ATC.TTS_FREQUENCY in lua/atc/atc_core.lua).

Runs from WSL or native Windows — the SRS binary is a Windows process either way, so it
reaches the SRS server on Windows localhost regardless.
"""

import argparse
import base64
import os
import queue
import re
import subprocess
import sys
import threading
import time

LINE_RE = re.compile(r"ATCAI_TTS\|([^|]*)\|([^|]*)\|(.*)$")

WSL_DEFAULTS = (
    "/mnt/c/Program Files/DCS-SimpleRadio-Standalone/ExternalAudio/DCS-SR-ExternalAudio.exe",
    "/mnt/c/Users/{user}/Saved Games/DCS/Logs/dcs.log",
)
WIN_DEFAULTS = (
    r"C:\Program Files\DCS-SimpleRadio-Standalone\ExternalAudio\DCS-SR-ExternalAudio.exe",
    r"C:\Users\{user}\Saved Games\DCS\Logs\dcs.log",
)


def running_under_wsl():
    # os.name first: when Windows Python is launched from a \\wsl.localhost\... path,
    # a rooted read of /proc/version resolves onto the WSL share and reports microsoft.
    if os.name == "nt":
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def no_window():
    """Stop Windows flashing a console window for each helper process we launch.

    Without this a console pops up over the game for every spoken reply and every
    recognised phrase. Windows-only; harmless everywhere else.
    """
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def default_paths(windows_user):
    exe, log = WSL_DEFAULTS if running_under_wsl() else WIN_DEFAULTS
    return exe, log.format(user=windows_user)


def follow(path, poll=0.25, should_stop=None):
    """Yield new lines appended to path, surviving DCS restarts recreating the log.

    should_stop lets a GUI shut the loop down; without it this runs forever.
    """
    handle = None
    inode = None
    try:
        while not (should_stop and should_stop()):
            if handle is None:
                try:
                    handle = open(path, "r", encoding="utf-8", errors="replace")
                except OSError:
                    time.sleep(poll)
                    continue
                # Start at the end so an existing log doesn't replay old transmissions.
                handle.seek(0, os.SEEK_END)
                inode = os.fstat(handle.fileno()).st_ino

            line = handle.readline()
            if line:
                yield line
                continue

            # No new data - check whether the log was rotated or truncated out from
            # under us, which happens every time DCS restarts.
            try:
                stat = os.stat(path)
                if stat.st_ino != inode or stat.st_size < handle.tell():
                    handle.close()
                    handle = None
                    continue
            except OSError:
                handle.close()
                handle = None
                continue
            time.sleep(poll)
    finally:
        if handle:
            handle.close()


def speak(exe, args, freq, modulation, text, say=print):
    cmd = [
        exe,
        "-t", text,
        "-f", freq,
        "-m", modulation,
        "-c", str(args.coalition),
        "-p", str(args.port),
        "-n", args.name,
        "-l", args.culture,
        "-g", args.gender,
        "-v", str(args.volume),
    ]
    try:
        # Capture bytes, not text: the Windows binary emits cp1252, so utf-8 decoding
        # of its output blows up on characters like 0xa0.
        result = subprocess.run(cmd, capture_output=True, timeout=args.timeout,
                                **no_window())
    except subprocess.TimeoutExpired:
        say("! SRS transmission timed out")
        return
    except OSError as exc:
        say("! could not run SRS ExternalAudio: %s" % exc)
        return

    output = (result.stdout + result.stderr).decode("cp1252", errors="replace")
    if result.returncode != 0:
        say("! SRS exited %d: %s" % (result.returncode, output.strip()[-300:]))
        return
    # ExternalAudio exits 0 even when it never reached the server, so read its output.
    if "Could not connect to server" in output:
        say("! SRS server not reachable on port %d - is SRS-Server.exe running?" % args.port)
    elif "|ERROR|" in output:
        for line in output.splitlines():
            if "|ERROR|" in line:
                say("! %s" % line.strip())


def speak_local(text, args, say=print):
    """Speak through Windows' built-in TTS, bypassing SRS entirely.

    Useful when SRS's DCS radio integration isn't working — you hear ATC on your
    desktop audio instead of over the in-game radio.
    """
    escaped = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.Rate=%d;"
        "$s.Speak('%s')" % (args.local_rate, escaped)
    )
    # -EncodedCommand takes UTF-16LE base64, which sidesteps shell quoting entirely.
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, timeout=args.timeout, **no_window(),
        )
    except subprocess.TimeoutExpired:
        say("! local speech timed out")
        return
    except OSError as exc:
        say("! could not run powershell: %s" % exc)
        return
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).decode("cp1252", errors="replace")
        say("! local speech failed (%d): %s" % (result.returncode, detail.strip()[:300]))


def transmit_worker(q, exe, args, on_log=None):
    """Transmissions run one at a time so they don't talk over each other."""
    say = on_log or (lambda message: print(message, flush=True))
    while True:
        item = q.get()
        if item is None:
            return
        freq, modulation, text = item
        if args.mode == "local":
            say("-> (local audio): %s" % text)
        else:
            say("-> %s MHz %s: %s" % (freq, modulation, text))
        try:
            if args.mode == "local":
                speak_local(text, args, say)
            else:
                speak(exe, args, freq, modulation, text, say)
        except Exception as exc:  # one bad transmission must not kill the bridge
            say("! transmission failed: %r" % exc)
        q.task_done()


def build_options(**overrides):
    """Default settings, so callers (like the manager app) don't need argparse."""
    defaults = dict(
        windows_user=os.environ.get("DCS_WINDOWS_USER", ""),
        log=None, srs_exe=None, coalition=2, port=5002, name="ATCAI",
        culture="en-US", gender="male", volume=1.0, timeout=60,
        mode="srs", local_rate=0,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run(args, on_log=None, should_stop=None):
    """Watch dcs.log and speak ATC's replies. Returns when should_stop() goes true.

    on_log receives progress as plain sentences so a GUI can show them; without it
    everything goes to stdout.
    """
    say = on_log or (lambda message: print(message, flush=True))

    exe_default, log_default = default_paths(args.windows_user or "")
    exe = args.srs_exe or exe_default
    log = args.log or log_default

    if args.mode == "srs" and not os.path.exists(exe):
        say("! SRS not found at %s" % exe)
        return 1
    if not os.path.exists(log):
        say("! DCS log not found at %s - fly a mission once and it will appear." % log)

    say("Watching %s" % log)
    say("Speaking through %s." % ("SRS" if args.mode == "srs" else "this PC's audio"))

    q = queue.Queue()
    worker = threading.Thread(target=transmit_worker, args=(q, exe, args, say), daemon=True)
    worker.start()

    try:
        for line in follow(log, should_stop=should_stop):
            match = LINE_RE.search(line)
            if match:
                freq, modulation, text = (g.strip() for g in match.groups())
                if text:
                    q.put((freq, modulation, text))
    finally:
        q.put(None)
    say("Stopped.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-user", default=os.environ.get("DCS_WINDOWS_USER", ""),
                        help="Windows username, for locating dcs.log")
    parser.add_argument("--log", help="path to dcs.log")
    parser.add_argument("--srs-exe", help="path to DCS-SR-ExternalAudio.exe")
    parser.add_argument("--coalition", type=int, default=2, help="0 spectator, 1 red, 2 blue")
    parser.add_argument("--port", type=int, default=5002, help="SRS server port")
    parser.add_argument("--name", default="ATCAI", help="transmitter name (no spaces)")
    parser.add_argument("--culture", default="en-US", help="TTS culture, e.g. en-GB")
    parser.add_argument("--gender", default="male", help="TTS voice gender")
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=60, help="seconds per transmission")
    parser.add_argument("--mode", choices=("srs", "local"), default="srs",
                        help="srs: transmit over SRS radio. local: speak on desktop audio, "
                             "bypassing SRS (use if SRS radio integration isn't working)")
    parser.add_argument("--local-rate", type=int, default=0,
                        help="speech rate for --mode local, -10 to 10")
    args = parser.parse_args()

    print("ATCAI TTS bridge [%s]" % args.mode)
    return run(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
