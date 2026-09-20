#!/usr/bin/env python3
"""Inject an ATCAI bootstrap trigger into a copy of a DCS .miz mission.

A .miz is a zip archive whose "mission" entry is a Lua table. This adds one
MISSION START trigger that dofile()s the ATCAI scripts from disk, so editing those
.lua files and re-flying picks up changes without touching the Mission Editor.

dofile() works because DCS's MissionScripting.lua sanitizes only os/io/lfs/require/
loadlib/package — dofile and loadfile are left available.

Usage: build_test_mission.py <source.miz> <output.miz> <script.lua> [script.lua ...]
"""

import argparse
import re
import sys
import zipfile


def inbox_path_for(script_paths):
    """The voice inbox lives beside the scripts; both sides must agree on the path."""
    first = script_paths[0]
    separator = "\\" if "\\" in first else "/"
    return first.rsplit(separator, 1)[0] + separator + "inbox.lua"


def mission_lua(script_paths):
    """The Lua the mission runs at start: set the inbox path, then load each script."""
    # [[...]] keeps Windows backslashes literal, so no escaping is needed.
    preamble = "ATCAI_INBOX_PATH = [[%s]] " % inbox_path_for(script_paths)
    return preamble + " ".join("dofile([[%s]])" % p for p in script_paths)


def build_action_code(script_paths, trig_index):
    """Lua that a_do_script()s the loader, running once."""
    # [==[...]==] nests safely around the inner [[...]] path literals.
    return "a_do_script([==[%s]==]); mission.trig.func[%d]=nil;" % (
        mission_lua(script_paths), trig_index)


def lua_quote(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def append_entry(block, table_name, index, value_text):
    """Append `[index] = value` just before `}, -- end of ["table_name"]`."""
    marker = '\t\t}, -- end of ["%s"]' % table_name
    if marker not in block:
        raise SystemExit("could not find end of [%r] in trig block" % table_name)
    entry = "\t\t\t[%d] = %s,\n" % (index, value_text)
    return block.replace(marker, entry + marker, 1)


def inject(mission_text, script_paths):
    trig_match = re.search(
        r'\t\["trig"\] = \n\t\{\n.*?\n\t\}, -- end of \["trig"\]', mission_text, re.S
    )
    if not trig_match:
        raise SystemExit('could not locate ["trig"] block in mission')
    trig = trig_match.group(0)

    existing = re.findall(r'^\t\t\t\[(\d+)\] = ', trig, re.M)
    idx = max(int(n) for n in existing) + 1 if existing else 1

    trig = append_entry(trig, "actions", idx, lua_quote(build_action_code(script_paths, idx)))
    trig = append_entry(
        trig, "func", idx,
        lua_quote("if mission.trig.conditions[%d]() then mission.trig.actions[%d]() end" % (idx, idx)),
    )
    trig = append_entry(trig, "flag", idx, "true")
    trig = append_entry(trig, "conditions", idx, lua_quote("return(true)"))
    mission_text = mission_text.replace(trig_match.group(0), trig, 1)

    # Editor-side representation, so the trigger is visible//editable in the ME too.
    rules_match = re.search(
        r'(\t\["trigrules"\] = \n\t\{\n)(.*?)(\n\t\}, -- end of \["trigrules"\])',
        mission_text, re.S,
    )
    if rules_match:
        existing_rules = re.findall(r'^\t\t\[(\d+)\] = $', rules_match.group(2), re.M)
        ridx = max(int(n) for n in existing_rules) + 1 if existing_rules else 1
        dofiles = mission_lua(script_paths)
        rule = (
            '\n\t\t[%d] = \n\t\t{\n'
            '\t\t\t["rules"] = {},\n'
            '\t\t\t["eventlist"] = "",\n'
            '\t\t\t["comment"] = "ATCAI - load ATC scripts",\n'
            '\t\t\t["predicate"] = "triggerStart",\n'
            '\t\t\t["actions"] = \n\t\t\t{\n'
            '\t\t\t\t[1] = \n\t\t\t\t{\n'
            '\t\t\t\t\t["text"] = %s,\n'
            '\t\t\t\t\t["predicate"] = "a_do_script",\n'
            '\t\t\t\t\t["ai_task"] = \n\t\t\t\t\t{\n'
            '\t\t\t\t\t\t[1] = "",\n\t\t\t\t\t\t[2] = "",\n'
            '\t\t\t\t\t}, -- end of ["ai_task"]\n'
            '\t\t\t\t}, -- end of [1]\n'
            '\t\t\t}, -- end of ["actions"]\n'
            '\t\t}, -- end of [%d]'
        ) % (ridx, lua_quote(dofiles), ridx)
        mission_text = (
            mission_text[:rules_match.end(2)] + rule + mission_text[rules_match.end(2):]
        )

    return mission_text, idx


def parse_clock(text):
    """'12:00' -> seconds since midnight, which is how a .miz stores start_time."""
    match = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
    if not match:
        raise SystemExit("start time must look like HH:MM, got %r" % text)
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        raise SystemExit("start time out of range: %r" % text)
    return hours * 3600 + minutes * 60


def set_start_time(mission_text, seconds):
    updated, count = re.subn(r'(\["start_time"\] = )\d+', r"\g<1>%d" % seconds,
                            mission_text, count=1)
    if not count:
        raise SystemExit('could not find ["start_time"] in mission')
    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Inject an ATCAI bootstrap trigger into a copy of a DCS mission.")
    parser.add_argument("source", help="mission to copy from")
    parser.add_argument("output", help="mission to write")
    parser.add_argument("scripts", nargs="+", help="absolute paths the mission will dofile()")
    parser.add_argument("--start-time", metavar="HH:MM",
                        help="override the mission start time, e.g. 12:00 for daylight")
    args = parser.parse_args()
    source, output, scripts = args.source, args.output, args.scripts

    with zipfile.ZipFile(source) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]

    new_entries = []
    injected_index = None
    for info, data in entries:
        if info.filename == "mission":
            text, injected_index = inject(data.decode("utf-8"), scripts)
            if args.start_time:
                text = set_start_time(text, parse_clock(args.start_time))
            data = text.encode("utf-8")
        new_entries.append((info, data))

    if injected_index is None:
        raise SystemExit("no 'mission' entry found in %s" % source)

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in new_entries:
            z.writestr(info.filename, data)

    print("wrote %s (trigger index %d, %d script(s))" % (output, injected_index, len(scripts)))


if __name__ == "__main__":
    main()
