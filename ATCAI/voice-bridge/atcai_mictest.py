"""Microphone diagnostic: is ATCAI hearing you, and if not, why not.

Drives voice-bridge/mictest.ps1 for a fixed number of seconds and turns its output into
events the manager can display: the recording device Windows actually handed us, a live
input level, the recogniser's own complaints, and everything it heard - including the
utterances it rejected.

The rejections are the reason this exists. The real recognition loop in atcai_listen.py
is synchronous, and a synchronous Recognize() returns nothing both for silence and for
speech that matched no phrase. So "it isn't hearing me" and "it hears me but the words
don't match" look identical while flying. Here they don't.

Runs the same grammar as the real recogniser, built from the same phrase spec, so a
phrase that matches here matches in the air.
"""

import json
import os
import subprocess
import sys
import tempfile

import atcai_listen

DEFAULT_SECONDS = 15

# Plain-English readings of System.Speech's AudioSignalProblem values. The enum names
# are terse and a player shouldn't have to look them up.
PROBLEM_ADVICE = {
    # NoSignal means no sound reached the recogniser, which is also what a quiet room
    # sounds like - it fires in the gaps between sentences on a perfectly good
    # microphone. So the wording must not assert a fault, and the advice is conditional
    # on the player actually having spoken.
    "NoSignal": "no sound reached the recogniser. If the room was quiet that's "
                "expected; if you were speaking, check the microphone is switched on, "
                "not muted in Windows, and not muted on the headset itself",
    "TooSoft": "your voice is too quiet - move closer, or raise the level in "
               "Windows sound settings",
    "TooLoud": "your voice is clipping - lower the level in Windows sound settings",
    "TooNoisy": "too much background noise - this is what game audio through "
                "speakers sounds like to the recogniser; push-to-talk fixes it",
    "TooFast": "speaking too quickly to follow",
    "TooSlow": "speaking too slowly to follow",
}


def parse_line(line):
    """One line of mictest.ps1 output -> (kind, payload), or None if unrecognised.

    Kept free of any Windows dependency so it can be tested anywhere.
    """
    line = (line or "").strip()
    if not line or "|" not in line:
        return None

    kind, _, rest = line.partition("|")
    kind = kind.strip().upper()

    if kind in ("DEVICE", "PROBLEM", "STATE", "ERROR"):
        return kind, rest.strip()
    if kind == "DONE":
        return kind, None
    if kind == "READY":
        try:
            return kind, int(rest.strip())
        except ValueError:
            return None
    if kind == "LEVEL":
        try:
            level = int(rest.strip())
        except ValueError:
            return None
        return kind, max(0, min(100, level))
    if kind in ("HEARD", "REJECTED"):
        confidence, _, text = rest.partition("|")
        try:
            confidence = float(confidence)
        except ValueError:
            return None
        return kind, (confidence, text.strip())
    if kind == "SIGNAL":
        flag, _, rest = rest.partition("|")
        level, _, name = rest.partition("|")
        name = name.strip()
        if not name:
            return None
        try:
            level = int(level)
        except ValueError:
            return None
        return kind, (flag.strip() == "1", max(0, min(100, level)), name)
    if kind == "INPUT":
        flag, _, name = rest.partition("|")
        name = name.strip()
        if not name:
            return None
        return kind, (flag.strip() == "1", name)
    return None


def describe_problem(name):
    """A signal problem in words a player can act on."""
    return PROBLEM_ADVICE.get(name, name)


def write_spec(path=None):
    """The same grammar spec the real recogniser uses, so results transfer."""
    spec = {"requests": sorted(atcai_listen.phrase_to_intent()), "wildcards": True}
    if path is None:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8")
        path = handle.name
    else:
        handle = open(path, "w", encoding="utf-8")
    with handle:
        json.dump(spec, handle)
    return path


# Opens Windows' own Recording tab. mmsys.cpl lands directly on it; ms-settings:sound
# only reaches the general Sound page, so it is the fallback rather than the first
# choice. ATCAI cannot set the default device itself - there is no public API for it -
# so the most honest thing it can do is put the player one click from the panel that can.
SOUND_PANEL = ["rundll32.exe", "shell32.dll,Control_RunDLL", "mmsys.cpl,,1"]
SOUND_PANEL_FALLBACK = ["cmd.exe", "/c", "start", "", "ms-settings:sound"]


def open_sound_settings(say=None):
    """Show Windows' recording device panel. Returns True if something opened."""
    report = say or (lambda message: None)
    for command in (SOUND_PANEL, SOUND_PANEL_FALLBACK):
        try:
            subprocess.Popen(command, **atcai_listen.no_window())
            return True
        except OSError:
            continue
    report("could not open Windows sound settings")
    return False


def list_devices(should_stop=None):
    """The active recording devices, as [(is_default, name), ...].

    Runs the same script in -ListOnly mode, which never opens the microphone, so this
    is safe to call while something else is listening.
    """
    found = []
    run(seconds=0, list_only=True, should_stop=should_stop,
        on_event=lambda kind, payload: found.append(payload) if kind == "INPUT" else None)
    return found


def run(seconds=DEFAULT_SECONDS, on_event=None, should_stop=None, list_only=False):
    """Run the diagnostic, calling on_event(kind, payload) as results arrive.

    Returns 0 when the test completed, non-zero when it could not run.
    """
    emit = on_event or (lambda kind, payload: None)
    stop = should_stop or (lambda: False)

    script = os.path.join(atcai_listen.resource_dir(), "mictest.ps1")
    if not os.path.exists(script):
        emit("ERROR", "microphone test script missing: %s" % script)
        return 1

    spec_path = write_spec()
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", script, "-SpecFile", spec_path, "-Seconds", str(int(seconds)),
    ]
    if list_only:
        command.append("-ListOnly")

    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            **atcai_listen.no_window())
    except OSError as exc:
        emit("ERROR", "could not start the microphone test: %s" % exc)
        _discard(spec_path)
        return 1

    # A signal problem repeats for as long as it lasts - "NoSignal" arrives about once a
    # second. Collapsing only *consecutive* duplicates wasn't enough: a recognition in
    # between resets the run, so a normal test came out as a wall of identical warnings
    # interleaved with the speech it had just understood. Each distinct problem is now
    # reported once for the whole test.
    seen_problems = set()
    last_state = None

    try:
        for raw in process.stdout:
            if stop():
                process.terminate()
                break
            # PowerShell writes cp1252; a device name with a non-ASCII character would
            # otherwise kill the reader mid-test.
            text = raw.decode("cp1252", errors="replace")
            parsed = parse_line(text)
            if not parsed:
                continue
            kind, payload = parsed
            if kind == "PROBLEM":
                if payload in seen_problems:
                    continue
                seen_problems.add(payload)
            elif kind == "STATE":
                if payload == last_state:
                    continue
                last_state = payload
            emit(kind, payload)
    finally:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        _discard(spec_path)

    return 0


def _discard(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def main():
    """Standalone use, for when there's no manager running."""
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SECONDS

    def show(kind, payload):
        if kind == "DEVICE":
            print("microphone: %s" % payload)
        elif kind == "READY":
            print("listening for %d seconds - say a request, e.g. \"request taxi\"" % payload)
        elif kind == "LEVEL":
            print("level %3d %s" % (payload, "#" * (payload // 5)))
        elif kind == "PROBLEM":
            print("! %s" % describe_problem(payload))
        elif kind == "HEARD":
            print("-> heard \"%s\" (%.2f)" % (payload[1], payload[0]))
        elif kind == "REJECTED":
            print("~ rejected \"%s\" (%.2f)" % (payload[1], payload[0]))
        elif kind == "ERROR":
            print("! %s" % payload)

    return run(seconds, on_event=show)


if __name__ == "__main__":
    sys.exit(main())
