"""An aircraft's real keyboard bindings, read out of DCS's own files.

Why read them rather than ship a table: DCS already knows the combinations, and the
player may have changed them. On the machine this was built against, bank had already
been moved to rudder on the arrow keys and radio frequency onto RCtrl+arrows - a table
of defaults would have been wrong on day one.

The files execute rather than being data, so they are run on DCS's own luae.exe with its
helpers stubbed (see readbindings.lua). That is the same technique the Lua test suites
use, and it gets the semantics right: the shared base profile is pulled in, feature
filtering happens, and the aircraft's own additions land in order.
"""

import os
import subprocess

import atcai_listen

# Where each layer lives, relative to the two DCS folders.
PROFILE_TEMPLATE = "Mods/aircraft/%s/Input/keyboard/default.lua"
DIFF_TEMPLATE = "Config/Input/%s/keyboard/Keyboard.diff.lua"
LUAE = "bin/luae.exe"


def parse_line(line):
    """One line of readbindings.lua output -> (kind, payload), or None.

    BINDING -> (name, modifiers list, key). UNRESOLVED -> name. DONE -> count.
    """
    line = (line or "").strip()
    if not line or "|" not in line:
        return None

    kind, _, rest = line.partition("|")
    kind = kind.strip().upper()

    if kind == "BINDING":
        parts = rest.split("|")
        if len(parts) != 3:
            return None
        name, modifiers, key = (p.strip() for p in parts)
        if not name or not key:
            return None
        mods = [m for m in modifiers.split("+") if m]
        return kind, (name, mods, key)
    if kind in ("UNRESOLVED", "ERROR"):
        return kind, rest.strip()
    if kind == "DONE":
        try:
            return kind, int(rest.strip())
        except ValueError:
            return kind, 0
    return None


def chord_for(modifiers, key):
    """["LCtrl"], "G" -> "LCtrl+G", in the spelling atcai_sendkeys accepts."""
    return "+".join(list(modifiers) + [key])


def _script():
    return os.path.join(atcai_listen.resource_dir(), "readbindings.lua")


def paths_for(aircraft, dcs_install, dcs_writedir):
    """(luae, profile, diff) for one aircraft, or None for any that is missing.

    The diff is optional - a player who has never rebound anything has no such file,
    which is not an error.
    """
    install = str(dcs_install or "")
    luae = os.path.join(install, *LUAE.split("/"))
    profile = os.path.join(install, *(PROFILE_TEMPLATE % aircraft).split("/"))
    diff = None
    if dcs_writedir:
        candidate = os.path.join(str(dcs_writedir),
                                 *(DIFF_TEMPLATE % aircraft).split("/"))
        if os.path.isfile(candidate):
            diff = candidate
    return (luae if os.path.isfile(luae) else None,
            profile if os.path.isfile(profile) else None,
            diff)


def read(aircraft, dcs_install, dcs_writedir=None, on_log=None):
    """{control name: [chord, ...]} for one aircraft, plus a list of problems.

    Returns ({}, [reason]) rather than raising: a missing aircraft profile means the
    feature declines for that airframe, not that voice input dies.
    """
    say = on_log or (lambda message: None)
    problems = []

    script = _script()
    if not os.path.isfile(script):
        return {}, ["readbindings.lua is missing (%s)" % script]

    luae, profile, diff = paths_for(aircraft, dcs_install, dcs_writedir)
    if not luae:
        return {}, ["DCS's Lua interpreter was not found - is the game folder correct?"]
    if not profile:
        return {}, ["no keyboard profile for %s - is the module installed?" % aircraft]

    command = [luae, atcai_listen.windows_path(script),
               # luae wants forward slashes for the root it concatenates onto.
               atcai_listen.windows_path(str(dcs_install)).replace("\\", "/"),
               atcai_listen.windows_path(profile)]
    if diff:
        command.append(atcai_listen.windows_path(diff))

    try:
        result = subprocess.run(command, capture_output=True, timeout=60,
                                cwd=os.path.dirname(luae),
                                **atcai_listen.no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, ["could not read the bindings: %s" % exc]

    bindings, unresolved = {}, []
    for raw in (result.stdout or b"").decode("cp1252", errors="replace").splitlines():
        parsed = parse_line(raw)
        if not parsed:
            continue
        kind, payload = parsed
        if kind == "BINDING":
            name, modifiers, key = payload
            bindings.setdefault(name, []).append(chord_for(modifiers, key))
        elif kind == "UNRESOLVED":
            unresolved.append(payload)
        elif kind == "ERROR":
            problems.append(payload)

    if not bindings:
        problems.append("no bindings were read for %s" % aircraft)
    else:
        say("read %d bindings for %s" % (len(bindings), aircraft))

    # Not a problem worth surfacing per control - these indirect through DCS's device
    # tables and are skipped deliberately rather than guessed at.
    if unresolved:
        # Now that DCS's keyboard defaults are resolved, what is left is genuinely
        # not a key - a joystick axis or button, which ATCAI cannot press. Saying
        # "no literal key" was true but read as "unbound", and that cost a round of
        # debugging when flaps were bound all along.
        say("%d control(s) are bound to a stick or axis rather than a key, so "
            "they cannot be used by voice" % len(unresolved))

    return bindings, problems


class Cache(object):
    """Bindings per aircraft, read once.

    Read once because running luae and executing a profile is not free, and bindings do
    not change mid-flight. A player who rebinds a control in DCS's own options needs to
    ask for a re-read, which is why the Manager has a button for it.
    """

    def __init__(self, dcs_install=None, dcs_writedir=None, on_log=None):
        self.dcs_install = dcs_install
        self.dcs_writedir = dcs_writedir
        self.on_log = on_log
        self._by_aircraft = {}
        self.problems = {}

    def get(self, aircraft):
        if not aircraft:
            return {}
        if aircraft not in self._by_aircraft:
            bindings, problems = read(aircraft, self.dcs_install, self.dcs_writedir,
                                      on_log=self.on_log)
            self._by_aircraft[aircraft] = bindings
            self.problems[aircraft] = problems
        return self._by_aircraft[aircraft]

    def forget(self, aircraft=None):
        """Drop what was read, so the next lookup re-reads. Used by the Manager's
        re-read button after a player changes a binding in DCS."""
        if aircraft:
            self._by_aircraft.pop(aircraft, None)
            self.problems.pop(aircraft, None)
        else:
            self._by_aircraft.clear()
            self.problems.clear()
