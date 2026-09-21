#!/usr/bin/env python3
"""Build an ATCAI test mission from a copy of an existing DCS .miz.

A .miz is a zip archive whose "mission" entry is a Lua table. This adds one
MISSION START trigger that dofile()s the ATCAI scripts from disk, so editing those
.lua files and re-flying picks up changes without touching the Mission Editor.

dofile() works because DCS's MissionScripting.lua sanitizes only os/io/lfs/require/
loadlib/package — dofile and loadfile are left available.

Usage: build_test_mission.py <source.miz> <output.miz> <script.lua> [script.lua ...]
"""

import argparse
import math
import re
import sys
import zipfile
from pathlib import Path


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


# ---------------------------------------------------------------------------
# AI traffic
#
# Traffic awareness is impossible to exercise flying alone: nothing ever occupies the
# runway or turns up on final. --traffic adds AI flights that take off from the player's
# own airfield and come straight back to land, so holds, sequencing and go-arounds
# actually fire.
#
# Groups are written by hand rather than copied from the source mission: a copy drags in
# liveries, payloads and tasking that may not exist for every owner, whereas a minimal
# group is predictable.
# ---------------------------------------------------------------------------

# Free with every DCS install, so a test mission built here works for anyone.
DEFAULT_TRAFFIC_TYPE = "Su-25T"


def find_player_airfield(mission_text):
    """The airfield the player starts at, and its coordinates.

    Taken from the player's own route, so the AI use exactly the field being tested.
    """
    marker = mission_text.find('"skill"] = "Player"')
    if marker < 0:
        return None
    segment = mission_text[max(0, marker - 20000):marker]

    airfield = None
    for match in re.finditer(
            r'\["type"\] = "(TakeOff[^"]*|Land)"[\s\S]{0,600}?'
            r'\["y"\] = ([-\d.]+),\s*\["x"\] = ([-\d.]+)'
            r'[\s\S]{0,300}?\["airdromeId"\] = (\d+)', segment):
        airfield = {
            "y": float(match.group(2)),
            "x": float(match.group(3)),
            "airdrome_id": int(match.group(4)),
        }
    return airfield


def next_ids(mission_text):
    """IDs above anything already in the mission, so nothing collides."""
    group_ids = [int(v) for v in re.findall(r'"groupId"\] = (\d+)', mission_text)]
    unit_ids = [int(v) for v in re.findall(r'"unitId"\] = (\d+)', mission_text)]
    return max(group_ids or [0]) + 1, max(unit_ids or [0]) + 1


def _waypoint(indent, index, kind, action, field, eta):
    pad = "\t" * indent
    return "\n".join([
        '%s[%d] = ' % (pad, index),
        '%s{' % pad,
        '%s\t["alt"] = 13,' % pad,
        '%s\t["type"] = "%s",' % (pad, kind),
        '%s\t["action"] = "%s",' % (pad, action),
        '%s\t["alt_type"] = "BARO",' % pad,
        '%s\t["form"] = "%s",' % (pad, action),
        '%s\t["speed"] = 138.88888888889,' % pad,
        '%s\t["task"] = ' % pad,
        '%s\t{' % pad,
        '%s\t\t["id"] = "ComboTask",' % pad,
        '%s\t\t["params"] = ' % pad,
        '%s\t\t{' % pad,
        '%s\t\t\t["tasks"] = {},' % pad,
        '%s\t\t}, -- end of ["params"]' % pad,
        '%s\t}, -- end of ["task"]' % pad,
        '%s\t["ETA"] = %s,' % (pad, eta),
        '%s\t["ETA_locked"] = %s,' % (pad, "true" if index == 1 else "false"),
        '%s\t["y"] = %s,' % (pad, field["y"]),
        '%s\t["x"] = %s,' % (pad, field["x"]),
        '%s\t["name"] = "",' % pad,
        '%s\t["speed_locked"] = true,' % pad,
        '%s\t["formation_template"] = "",' % pad,
        '%s\t["airdromeId"] = %d,' % (pad, field["airdrome_id"]),
        '%s}, -- end of [%d]' % (pad, index),
    ])


def traffic_group(indent, index, number, group_id, unit_id, field, start_time, aircraft):
    """One AI flight: off the runway, round the circuit, back onto the same runway.

    indent is the tab depth of this entry in the mission's group list, which varies
    between missions - hardcoding it puts the flight in the wrong table entirely.
    """
    pad = "\t" * indent
    # Named by flight number, not by table position: the player usually occupies the
    # first slot, so indices start partway up and would read oddly.
    name = "ATCAI Traffic %d" % number
    return "\n".join([
        '%s[%d] = ' % (pad, index),
        '%s{' % pad,
        '%s\t["modulation"] = 0,' % pad,
        '%s\t["tasks"] = {},' % pad,
        '%s\t["radioSet"] = false,' % pad,
        '%s\t["task"] = "Nothing",' % pad,
        '%s\t["uncontrolled"] = false,' % pad,
        '%s\t["route"] = ' % pad,
        '%s\t{' % pad,
        '%s\t\t["points"] = ' % pad,
        '%s\t\t{' % pad,
        _waypoint(indent + 3, 1, "TakeOff", "From Runway", field, 0),
        _waypoint(indent + 3, 2, "Land", "Landing", field, 600),
        '%s\t\t}, -- end of ["points"]' % pad,
        '%s\t}, -- end of ["route"]' % pad,
        '%s\t["groupId"] = %d,' % (pad, group_id),
        '%s\t["hidden"] = false,' % pad,
        '%s\t["units"] = ' % pad,
        '%s\t{' % pad,
        '%s\t\t[1] = ' % pad,
        '%s\t\t{' % pad,
        '%s\t\t\t["alt"] = 13,' % pad,
        '%s\t\t\t["alt_type"] = "BARO",' % pad,
        '%s\t\t\t["skill"] = "High",' % pad,
        '%s\t\t\t["speed"] = 138.88888888889,' % pad,
        '%s\t\t\t["AddPropAircraft"] = {},' % pad,
        '%s\t\t\t["type"] = "%s",' % (pad, aircraft),
        '%s\t\t\t["unitId"] = %d,' % (pad, unit_id),
        '%s\t\t\t["psi"] = 0,' % pad,
        '%s\t\t\t["y"] = %s,' % (pad, field["y"]),
        '%s\t\t\t["x"] = %s,' % (pad, field["x"]),
        '%s\t\t\t["name"] = "%s-1",' % (pad, name),
        '%s\t\t\t["payload"] = ' % pad,
        '%s\t\t\t{' % pad,
        '%s\t\t\t\t["pylons"] = {},' % pad,
        '%s\t\t\t\t["fuel"] = "3000",' % pad,
        '%s\t\t\t\t["flare"] = 0,' % pad,
        '%s\t\t\t\t["chaff"] = 0,' % pad,
        '%s\t\t\t\t["gun"] = 100,' % pad,
        '%s\t\t\t}, -- end of ["payload"]' % pad,
        '%s\t\t\t["heading"] = 0,' % pad,
        '%s\t\t\t["onboard_num"] = "%03d",' % (pad, 500 + number),
        '%s\t\t}, -- end of [1]' % pad,
        '%s\t}, -- end of ["units"]' % pad,
        '%s\t["y"] = %s,' % (pad, field["y"]),
        '%s\t["x"] = %s,' % (pad, field["x"]),
        '%s\t["name"] = "%s",' % (pad, name),
        '%s\t["communication"] = true,' % pad,
        '%s\t["start_time"] = %d,' % (pad, start_time),
        '%s\t["frequency"] = 251,' % pad,
        '%s}, -- end of [%d]' % (pad, index),
    ])


def group_list_at(mission_text, key_position):
    """Given the position of a ["group"] key, describe the list it opens.

    Returns (entry_indent, insert_at, existing_indices) or None. Everything is derived
    from the file: assuming a fixed indentation once put AI flights in the country list
    instead of the group list, which silently removed the player from the mission.
    """
    line_start = mission_text.rfind("\n", 0, key_position) + 1
    list_indent = mission_text[line_start:key_position].count("\t")

    closing = "\n" + ("\t" * list_indent) + '}, -- end of ["group"]'
    end = mission_text.find(closing, key_position)
    if end < 0:
        return None

    entry_indent = list_indent + 1
    # Tolerant of trailing whitespace: DCS writes "[1] = " with a space, hand-made
    # fixtures often don't.
    entry_pattern = re.compile(r"^%s\[(\d+)\]\s*=\s*$" % ("\t" * entry_indent), re.M)
    indices = [int(m.group(1)) for m in entry_pattern.finditer(mission_text[key_position:end])]
    if not indices:
        return None

    return entry_indent, end + 1, indices


def coalition_bounds(mission_text):
    """Where each side's block starts, and which one holds the player."""
    sides = {}
    for side in ("blue", "red"):
        positions = [m.start() for m in re.finditer(r'\n\t\t\["%s"\] =' % side, mission_text)]
        if positions:
            sides[side] = positions[-1]

    player = mission_text.find('"skill"] = "Player"')
    mine = None
    for side, start in sides.items():
        if start < player and (mine is None or start > sides[mine]):
            mine = side
    return sides, mine


def enemy_group_list(mission_text, category):
    """A group list of the given category belonging to the side the player isn't on.

    category is "vehicle" or "plane". Enemies have to be on the opposing coalition or
    they can't be fought.
    """
    sides, mine = coalition_bounds(mission_text)
    if not mine:
        return None
    enemy = "red" if mine == "blue" else "blue"
    if enemy not in sides:
        return None

    start = sides[enemy]
    # Where the enemy block ends: the next side key at the same depth, or end of file.
    later = [p for p in sides.values() if p > start]
    end = min(later) if later else len(mission_text)

    key = mission_text.find('["%s"] =' % category, start, end)
    if key < 0:
        return None
    group_key = mission_text.find('["group"] =', key, end)
    if group_key < 0:
        return None
    return group_list_at(mission_text, group_key)


def enemy_vehicle_list(mission_text):
    return enemy_group_list(mission_text, "vehicle")


def target_anchors(mission_text):
    """Points worth putting targets near: every airfield the mission references."""
    anchors = {}
    for match in re.finditer(
            r'\["y"\] = ([-\d.]+),\s*\n\s*\["x"\] = ([-\d.]+)'
            r'[\s\S]{0,300}?\["airdromeId"\] = (\d+)', mission_text):
        anchors.setdefault(match.group(3), (float(match.group(2)), float(match.group(1))))
    return list(anchors.values())


def player_group_list(mission_text):
    """The group list the player's aircraft sits in."""
    player = mission_text.find('"skill"] = "Player"')
    if player < 0:
        return None
    key = mission_text.rfind('["group"] =', 0, player)
    if key < 0:
        return None
    return group_list_at(mission_text, key)


def add_traffic(mission_text, count, aircraft=DEFAULT_TRAFFIC_TYPE, spacing=180):
    """Add AI flights operating from the player's field. Returns (text, added)."""
    field = find_player_airfield(mission_text)
    if not field:
        return mission_text, 0

    located = player_group_list(mission_text)
    if not located:
        return mission_text, 0
    entry_indent, insert_at, indices = located

    next_index = max(indices) + 1
    group_id, unit_id = next_ids(mission_text)

    blocks = []
    for offset in range(count):
        blocks.append(traffic_group(
            entry_indent, next_index + offset, offset + 1,
            group_id + offset, unit_id + offset, field,
            # Staggered so there is traffic coming and going rather than one burst.
            60 + offset * spacing, aircraft))

    addition = "\n".join(blocks) + "\n"
    return mission_text[:insert_at] + addition + mission_text[insert_at:], count


# ---------------------------------------------------------------------------
# Ground targets
#
# Nothing to do with ATC: --ground scatters enemy vehicles around the airfields the
# mission uses, so the test mission is also worth flying for its own sake.
# ---------------------------------------------------------------------------

# Core DCS assets, so a mission built here works without owning any extra module.
TARGET_VEHICLES = ("T-72B", "BTR-80", "Ural-375", "BMP-2")
# Added with --ground-defended. These shoot back.
TARGET_DEFENCES = ("ZSU-23-4 Shilka",)

GROUND_RING_METRES = 12000        # how far from a field targets sit
GROUND_SPREAD_METRES = 60         # spacing between vehicles within a group


def ground_positions(anchors, count, radius=GROUND_RING_METRES):
    """Spread groups around the given points, so they're findable but not stacked."""
    if not anchors:
        return []
    placements = []
    for n in range(count):
        base_x, base_y = anchors[n % len(anchors)]
        # Rotate around each anchor so successive groups sit at different bearings.
        angle = (2 * math.pi / max(count, 1)) * n + (n % len(anchors))
        placements.append((base_x + radius * math.cos(angle),
                           base_y + radius * math.sin(angle)))
    return placements


def vehicle_group(indent, index, number, group_id, unit_id, x, y, vehicles):
    """A cluster of enemy vehicles sitting still, waiting to be shot at."""
    pad = "\t" * indent
    name = "ATCAI Target %d" % number

    lines = [
        '%s[%d] = ' % (pad, index),
        '%s{' % pad,
        '%s\t["visible"] = false,' % pad,
        '%s\t["lateActivation"] = false,' % pad,
        '%s\t["tasks"] = {},' % pad,
        '%s\t["uncontrollable"] = false,' % pad,
        '%s\t["task"] = "Ground Nothing",' % pad,
        '%s\t["taskSelected"] = true,' % pad,
        '%s\t["route"] = ' % pad,
        '%s\t{' % pad,
        '%s\t\t["spans"] = {},' % pad,
        '%s\t\t["points"] = ' % pad,
        '%s\t\t{' % pad,
        '%s\t\t\t[1] = ' % pad,
        '%s\t\t\t{' % pad,
        '%s\t\t\t\t["alt"] = 100,' % pad,
        '%s\t\t\t\t["type"] = "Turning Point",' % pad,
        '%s\t\t\t\t["ETA"] = 0,' % pad,
        '%s\t\t\t\t["alt_type"] = "BARO",' % pad,
        '%s\t\t\t\t["formation_template"] = "",' % pad,
        '%s\t\t\t\t["y"] = %.2f,' % (pad, y),
        '%s\t\t\t\t["x"] = %.2f,' % (pad, x),
        '%s\t\t\t\t["name"] = "",' % pad,
        '%s\t\t\t\t["ETA_locked"] = true,' % pad,
        '%s\t\t\t\t["speed"] = 0,' % pad,
        '%s\t\t\t\t["action"] = "Off Road",' % pad,
        '%s\t\t\t\t["task"] = ' % pad,
        '%s\t\t\t\t{' % pad,
        '%s\t\t\t\t\t["id"] = "ComboTask",' % pad,
        '%s\t\t\t\t\t["params"] = ' % pad,
        '%s\t\t\t\t\t{' % pad,
        '%s\t\t\t\t\t\t["tasks"] = {},' % pad,
        '%s\t\t\t\t\t}, -- end of ["params"]' % pad,
        '%s\t\t\t\t}, -- end of ["task"]' % pad,
        '%s\t\t\t\t["speed_locked"] = true,' % pad,
        '%s\t\t\t}, -- end of [1]' % pad,
        '%s\t\t}, -- end of ["points"]' % pad,
        '%s\t}, -- end of ["route"]' % pad,
        '%s\t["groupId"] = %d,' % (pad, group_id),
        '%s\t["hidden"] = false,' % pad,
        '%s\t["units"] = ' % pad,
        '%s\t{' % pad,
    ]

    for slot, vehicle in enumerate(vehicles, start=1):
        # Spread them out a little so they aren't stacked in one spot.
        offset = (slot - 1) * GROUND_SPREAD_METRES
        lines += [
            '%s\t\t[%d] = ' % (pad, slot),
            '%s\t\t{' % pad,
            '%s\t\t\t["type"] = "%s",' % (pad, vehicle),
            '%s\t\t\t["transportable"] = ' % pad,
            '%s\t\t\t{' % pad,
            '%s\t\t\t\t["randomTransportable"] = false,' % pad,
            '%s\t\t\t}, -- end of ["transportable"]' % pad,
            '%s\t\t\t["unitId"] = %d,' % (pad, unit_id + slot - 1),
            '%s\t\t\t["skill"] = "Average",' % pad,
            '%s\t\t\t["y"] = %.2f,' % (pad, y + offset),
            '%s\t\t\t["x"] = %.2f,' % (pad, x + offset),
            '%s\t\t\t["name"] = "%s-%d",' % (pad, name, slot),
            '%s\t\t\t["heading"] = 0,' % pad,
            '%s\t\t\t["playerCanDrive"] = true,' % pad,
            '%s\t\t}, -- end of [%d]' % (pad, slot),
        ]

    lines += [
        '%s\t}, -- end of ["units"]' % pad,
        '%s\t["y"] = %.2f,' % (pad, y),
        '%s\t["x"] = %.2f,' % (pad, x),
        '%s\t["name"] = "%s",' % (pad, name),
        '%s\t["start_time"] = 0,' % pad,
        '%s}, -- end of [%d]' % (pad, index),
    ]
    return "\n".join(lines)


def add_ground_targets(mission_text, count, defended=False, radius=GROUND_RING_METRES,
                       per_group=3):
    """Place enemy vehicle groups around the mission's airfields. Returns (text, added)."""
    located = enemy_vehicle_list(mission_text)
    if not located:
        return mission_text, 0
    entry_indent, insert_at, indices = located

    anchors = target_anchors(mission_text)
    placements = ground_positions(anchors, count, radius)
    if not placements:
        return mission_text, 0

    next_index = max(indices) + 1
    group_id, unit_id = next_ids(mission_text)

    blocks = []
    for offset, (x, y) in enumerate(placements):
        vehicles = [TARGET_VEHICLES[(offset + n) % len(TARGET_VEHICLES)]
                    for n in range(per_group)]
        if defended:
            vehicles += list(TARGET_DEFENCES)
        blocks.append(vehicle_group(
            entry_indent, next_index + offset, offset + 1,
            group_id + offset, unit_id, x, y, vehicles))
        unit_id += len(vehicles)

    addition = "\n".join(blocks) + "\n"
    return mission_text[:insert_at] + addition + mission_text[insert_at:], len(placements)


# ---------------------------------------------------------------------------
# Enemy aircraft
#
# Stock missions often leave their enemy flights on lateActivation, waiting for triggers
# tied to that mission's own objectives - so a mission reused for testing can look fully
# populated and yet never produce a fight. --enemy-air adds fighters that are airborne,
# hostile and active from the moment the mission starts, with no conditions attached.
# ---------------------------------------------------------------------------

# Core DCS AI assets, so no extra module is needed.
ENEMY_AIR_TYPES = ("Su-27", "MiG-29S")
ENEMY_AIR_RADIUS = 40000          # metres from the field they orbit
ENEMY_AIR_ALTITUDE = 6000         # metres


def enemy_air_group(indent, index, number, group_id, unit_id, x, y,
                    altitude, aircraft, flight_size=2):
    """A hostile fighter flight, airborne and looking for you from the start."""
    pad = "\t" * indent
    name = "ATCAI Bandit %d" % number

    lines = [
        '%s[%d] = ' % (pad, index),
        '%s{' % pad,
        '%s\t["modulation"] = 0,' % pad,
        '%s\t["tasks"] = {},' % pad,
        '%s\t["radioSet"] = false,' % pad,
        '%s\t["task"] = "CAP",' % pad,
        '%s\t["uncontrolled"] = false,' % pad,
        # Explicitly not late-activated: that is the whole point of this option.
        '%s\t["lateActivation"] = false,' % pad,
        '%s\t["taskSelected"] = true,' % pad,
        '%s\t["route"] = ' % pad,
        '%s\t{' % pad,
        '%s\t\t["points"] = ' % pad,
        '%s\t\t{' % pad,
        '%s\t\t\t[1] = ' % pad,
        '%s\t\t\t{' % pad,
        '%s\t\t\t\t["alt"] = %d,' % (pad, altitude),
        '%s\t\t\t\t["type"] = "Turning Point",' % pad,
        '%s\t\t\t\t["action"] = "Turning Point",' % pad,
        '%s\t\t\t\t["alt_type"] = "BARO",' % pad,
        '%s\t\t\t\t["form"] = "Turning Point",' % pad,
        '%s\t\t\t\t["speed"] = 220,' % pad,
        '%s\t\t\t\t["task"] = ' % pad,
        '%s\t\t\t\t{' % pad,
        '%s\t\t\t\t\t["id"] = "ComboTask",' % pad,
        '%s\t\t\t\t\t["params"] = ' % pad,
        '%s\t\t\t\t\t{' % pad,
        '%s\t\t\t\t\t\t["tasks"] = ' % pad,
        '%s\t\t\t\t\t\t{' % pad,
        '%s\t\t\t\t\t\t\t[1] = ' % pad,
        '%s\t\t\t\t\t\t\t{' % pad,
        '%s\t\t\t\t\t\t\t\t["number"] = 1,' % pad,
        '%s\t\t\t\t\t\t\t\t["auto"] = true,' % pad,
        '%s\t\t\t\t\t\t\t\t["id"] = "EngageTargets",' % pad,
        '%s\t\t\t\t\t\t\t\t["enabled"] = true,' % pad,
        '%s\t\t\t\t\t\t\t\t["key"] = "CAP",' % pad,
        '%s\t\t\t\t\t\t\t\t["params"] = ' % pad,
        '%s\t\t\t\t\t\t\t\t{' % pad,
        '%s\t\t\t\t\t\t\t\t\t["targetTypes"] = ' % pad,
        '%s\t\t\t\t\t\t\t\t\t{' % pad,
        '%s\t\t\t\t\t\t\t\t\t\t[1] = "Air",' % pad,
        '%s\t\t\t\t\t\t\t\t\t}, -- end of ["targetTypes"]' % pad,
        '%s\t\t\t\t\t\t\t\t\t["priority"] = 0,' % pad,
        '%s\t\t\t\t\t\t\t\t}, -- end of ["params"]' % pad,
        '%s\t\t\t\t\t\t\t}, -- end of [1]' % pad,
        '%s\t\t\t\t\t\t}, -- end of ["tasks"]' % pad,
        '%s\t\t\t\t\t}, -- end of ["params"]' % pad,
        '%s\t\t\t\t}, -- end of ["task"]' % pad,
        '%s\t\t\t\t["ETA"] = 0,' % pad,
        '%s\t\t\t\t["ETA_locked"] = true,' % pad,
        '%s\t\t\t\t["y"] = %.2f,' % (pad, y),
        '%s\t\t\t\t["x"] = %.2f,' % (pad, x),
        '%s\t\t\t\t["name"] = "",' % pad,
        '%s\t\t\t\t["speed_locked"] = true,' % pad,
        '%s\t\t\t\t["formation_template"] = "",' % pad,
        '%s\t\t\t}, -- end of [1]' % pad,
        '%s\t\t}, -- end of ["points"]' % pad,
        '%s\t}, -- end of ["route"]' % pad,
        '%s\t["groupId"] = %d,' % (pad, group_id),
        '%s\t["hidden"] = false,' % pad,
        '%s\t["units"] = ' % pad,
        '%s\t{' % pad,
    ]

    for slot in range(1, flight_size + 1):
        lines += [
            '%s\t\t[%d] = ' % (pad, slot),
            '%s\t\t{' % pad,
            '%s\t\t\t["alt"] = %d,' % (pad, altitude),
            '%s\t\t\t["alt_type"] = "BARO",' % pad,
            '%s\t\t\t["skill"] = "High",' % pad,
            '%s\t\t\t["speed"] = 220,' % pad,
            '%s\t\t\t["AddPropAircraft"] = {},' % pad,
            '%s\t\t\t["type"] = "%s",' % (pad, aircraft),
            '%s\t\t\t["unitId"] = %d,' % (pad, unit_id + slot - 1),
            '%s\t\t\t["psi"] = 0,' % pad,
            # Spread the flight out so they don't start stacked on one point.
            '%s\t\t\t["y"] = %.2f,' % (pad, y + (slot - 1) * 200),
            '%s\t\t\t["x"] = %.2f,' % (pad, x + (slot - 1) * 200),
            '%s\t\t\t["name"] = "%s-%d",' % (pad, name, slot),
            '%s\t\t\t["payload"] = ' % pad,
            '%s\t\t\t{' % pad,
            '%s\t\t\t\t["pylons"] = {},' % pad,
            '%s\t\t\t\t["fuel"] = "5000",' % pad,
            '%s\t\t\t\t["flare"] = 60,' % pad,
            '%s\t\t\t\t["chaff"] = 60,' % pad,
            '%s\t\t\t\t["gun"] = 100,' % pad,
            '%s\t\t\t}, -- end of ["payload"]' % pad,
            '%s\t\t\t["heading"] = 0,' % pad,
            '%s\t\t\t["onboard_num"] = "%03d",' % (pad, 700 + number * 10 + slot),
            '%s\t\t}, -- end of [%d]' % (pad, slot),
        ]

    lines += [
        '%s\t}, -- end of ["units"]' % pad,
        '%s\t["y"] = %.2f,' % (pad, y),
        '%s\t["x"] = %.2f,' % (pad, x),
        '%s\t["name"] = "%s",' % (pad, name),
        '%s\t["communication"] = true,' % pad,
        '%s\t["start_time"] = 0,' % pad,
        '%s\t["frequency"] = 124,' % pad,
        '%s}, -- end of [%d]' % (pad, index),
    ]
    return "\n".join(lines)


def add_enemy_air(mission_text, count, aircraft=None, radius=ENEMY_AIR_RADIUS,
                  altitude=ENEMY_AIR_ALTITUDE, flight_size=2):
    """Add hostile fighter flights airborne near the mission's airfields."""
    located = enemy_group_list(mission_text, "plane")
    if not located:
        return mission_text, 0
    entry_indent, insert_at, indices = located

    anchors = target_anchors(mission_text)
    placements = ground_positions(anchors, count, radius)
    if not placements:
        return mission_text, 0

    next_index = max(indices) + 1
    group_id, unit_id = next_ids(mission_text)

    blocks = []
    for offset, (x, y) in enumerate(placements):
        chosen = aircraft or ENEMY_AIR_TYPES[offset % len(ENEMY_AIR_TYPES)]
        blocks.append(enemy_air_group(
            entry_indent, next_index + offset, offset + 1,
            group_id + offset, unit_id, x, y, altitude, chosen, flight_size))
        unit_id += flight_size

    addition = "\n".join(blocks) + "\n"
    return mission_text[:insert_at] + addition + mission_text[insert_at:], len(placements)


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
    """Set the mission clock.

    Only the mission's own key counts. Groups carry a ["start_time"] of their own, and
    a stock mission usually has dozens of them before the mission-level one - matching
    the first occurrence anywhere rewrote some ground unit's spawn delay and left the
    clock untouched, silently, so every mission stayed at whatever hour it shipped with.
    The mission-level key is the one at a single tab of indentation.
    """
    updated, count = re.subn(r'^\t(\["start_time"\] = )\d+',
                             lambda m: "\t%s%d" % (m.group(1), seconds),
                             mission_text, count=1, flags=re.M)
    if not count:
        raise SystemExit('could not find the mission-level ["start_time"]')
    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Inject an ATCAI bootstrap trigger into a copy of a DCS mission.")
    parser.add_argument("source", help="mission to copy from")
    parser.add_argument("output", help="mission to write")
    parser.add_argument("scripts", nargs="+", help="absolute paths the mission will dofile()")
    parser.add_argument("--start-time", metavar="HH:MM",
                        help="override the mission start time, e.g. 12:00 for daylight")
    parser.add_argument("--traffic", type=int, default=0, metavar="N",
                        help="add N AI flights operating from the player's airfield, so "
                             "traffic awareness can be exercised")
    parser.add_argument("--traffic-type", default=DEFAULT_TRAFFIC_TYPE,
                        help="aircraft to use for the AI traffic (default: %s)"
                             % DEFAULT_TRAFFIC_TYPE)
    parser.add_argument("--traffic-spacing", type=int, default=180, metavar="SECONDS",
                        help="seconds between each AI flight starting (default: 180)")
    parser.add_argument("--ground", type=int, default=0, metavar="N",
                        help="scatter N enemy vehicle groups around the mission's "
                             "airfields, to give you something to shoot at")
    parser.add_argument("--ground-defended", action="store_true",
                        help="add anti-aircraft cover to each ground group, so they "
                             "shoot back")
    parser.add_argument("--ground-radius", type=int, default=GROUND_RING_METRES,
                        metavar="METRES",
                        help="how far from each airfield to place them (default: %d)"
                             % GROUND_RING_METRES)
    parser.add_argument("--enemy-air", type=int, default=0, metavar="N",
                        help="add N hostile fighter flights, airborne and active from "
                             "the start (stock missions often leave theirs waiting on "
                             "triggers that never fire outside their own objectives)")
    parser.add_argument("--enemy-air-type", default=None,
                        help="aircraft for the hostile flights (default: alternates %s)"
                             % ", ".join(ENEMY_AIR_TYPES))
    parser.add_argument("--enemy-air-size", type=int, default=2, metavar="N",
                        help="aircraft per hostile flight (default: 2)")
    parser.add_argument("--enemy-air-radius", type=int, default=ENEMY_AIR_RADIUS,
                        metavar="METRES",
                        help="how far from each airfield they orbit (default: %d)"
                             % ENEMY_AIR_RADIUS)
    parser.add_argument("--enemy-air-altitude", type=int, default=ENEMY_AIR_ALTITUDE,
                        metavar="METRES",
                        help="altitude for the hostile flights (default: %d)"
                             % ENEMY_AIR_ALTITUDE)
    parser.add_argument("--force", action="store_true",
                        help="overwrite the output file if it already exists")
    args = parser.parse_args()

    # Missions are worth keeping: refuse to clobber one unless told to.
    if Path(args.output).exists() and not args.force:
        raise SystemExit(
            "%s already exists. Choose another name, or pass --force to overwrite it."
            % args.output)
    source, output, scripts = args.source, args.output, args.scripts
    traffic_added = 0
    ground_added = 0
    air_added = 0

    with zipfile.ZipFile(source) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]

    new_entries = []
    injected_index = None
    for info, data in entries:
        if info.filename == "mission":
            text, injected_index = inject(data.decode("utf-8"), scripts)
            if args.start_time:
                text = set_start_time(text, parse_clock(args.start_time))
            if args.traffic > 0:
                text, traffic_added = add_traffic(
                    text, args.traffic, args.traffic_type, args.traffic_spacing)
            if args.ground > 0:
                text, ground_added = add_ground_targets(
                    text, args.ground, args.ground_defended, args.ground_radius)
            if args.enemy_air > 0:
                text, air_added = add_enemy_air(
                    text, args.enemy_air, args.enemy_air_type, args.enemy_air_radius,
                    args.enemy_air_altitude, args.enemy_air_size)
            data = text.encode("utf-8")
        new_entries.append((info, data))

    if injected_index is None:
        raise SystemExit("no 'mission' entry found in %s" % source)

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in new_entries:
            z.writestr(info.filename, data)

    summary = "wrote %s (trigger index %d, %d script(s)" % (
        output, injected_index, len(scripts))
    if args.traffic > 0:
        if traffic_added:
            summary += ", %d AI flight(s) of %s every %ds" % (
                traffic_added, args.traffic_type, args.traffic_spacing)
        else:
            summary += ", NO traffic added - could not find the player's airfield"
    if args.ground > 0:
        if ground_added:
            summary += ", %d ground target group(s)%s within %dm of the airfields" % (
                ground_added, " with AA cover" if args.ground_defended else "",
                args.ground_radius)
        else:
            summary += ", NO ground targets added - no enemy vehicle list in the mission"
    if args.enemy_air > 0:
        if air_added:
            summary += ", %d hostile flight(s) of %d airborne at %dm" % (
                air_added, args.enemy_air_size, args.enemy_air_altitude)
        else:
            summary += ", NO enemy air added - no enemy plane list in the mission"
    print(summary + ")")


if __name__ == "__main__":
    main()
