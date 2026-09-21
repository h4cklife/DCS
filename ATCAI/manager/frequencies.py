#!/usr/bin/env python3
"""Read each terrain's real airfield radio frequencies out of the DCS install.

Every terrain ships Mods/terrains/<Terrain>/Radio.lua listing, per airfield, the tower
frequencies across HF / UHF / VHF bands and the callsigns ATC answers to. That's the same
data DCS's own ATC menu shows, so using it means ATCAI talks on the frequency the field
really uses instead of a fixed guess.

The mission sandbox can't read that file itself - it calls require(), which DCS strips -
so the manager parses it here and writes a clean Lua table the mission can dofile().
"""

from __future__ import annotations

import re
from pathlib import Path

# [UHF] = {MODULATIONTYPE_AM, 250000000.000000}
FREQUENCY_RE = re.compile(
    r"\[(HF|UHF|VHF_HI|VHF_LOW)\]\s*=\s*\{\s*MODULATIONTYPE_(\w+)\s*,\s*([\d.]+)\s*\}")
# callsign = {{["nato"] = {_("Batumi"), "Batumi"}}, ...}
CALLSIGN_RE = re.compile(r'\["(\w+)"\]\s*=\s*\{[^}]*?"([^"]+)"\s*\}')
RADIO_ID_RE = re.compile(r"radioId\s*=\s*'([^']+)'")
ROLE_RE = re.compile(r'role\s*=\s*\{([^}]*)\}')

# Which callsign flavour to prefer when a field has several.
CALLSIGN_PREFERENCE = ("common", "nato", "ussr")


def parse_radio_lua(text: str) -> list[dict]:
    """Every airfield entry in a terrain's Radio.lua."""
    airfields = []
    # Entries are brace-delimited blocks containing a radioId.
    for block in re.split(r"\n\t\}\s*;", text):
        if "radioId" not in block:
            continue

        roles = ROLE_RE.search(block)
        role_list = re.findall(r'"(\w+)"', roles.group(1)) if roles else []
        # Only fields that actually run a tower are of interest.
        if role_list and "tower" not in role_list:
            continue

        names = dict(CALLSIGN_RE.findall(block))
        name = next((names[k] for k in CALLSIGN_PREFERENCE if k in names), None)
        if not name and names:
            name = sorted(names.values())[0]
        if not name:
            continue

        frequencies = []
        for band, modulation, hertz in FREQUENCY_RE.findall(block):
            frequencies.append({
                "band": band,
                "modulation": "FM" if modulation.upper() == "FM" else "AM",
                "mhz": round(float(hertz) / 1_000_000, 3),
            })
        if not frequencies:
            continue

        radio_id = RADIO_ID_RE.search(block)
        airfields.append({
            "name": name,
            "aliases": sorted(set(names.values())),
            "radio_id": radio_id.group(1) if radio_id else None,
            "frequencies": frequencies,
        })
    return airfields


def terrain_radio_files(install_dir: Path) -> dict[str, Path]:
    """Terrain name -> its Radio.lua, for every terrain installed."""
    terrains = {}
    root = Path(install_dir) / "Mods" / "terrains"
    if not root.is_dir():
        return terrains
    for entry in sorted(root.iterdir()):
        radio = entry / "Radio.lua"
        if radio.is_file():
            terrains[entry.name] = radio
    return terrains


def read_terrains(install_dir: Path) -> dict[str, list[dict]]:
    """Airfields per terrain. Unreadable terrains are skipped, not fatal."""
    result = {}
    for terrain, path in terrain_radio_files(install_dir).items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        airfields = parse_radio_lua(text)
        if airfields:
            result[terrain] = airfields
    return result


# The UHF air band. Picking inside it matters: a broadcast on a frequency the aircraft
# radio can't tune is one nobody can listen to.
UHF_MIN, UHF_MAX = 225.0, 399.975
DEFAULT_ATIS_FREQUENCY = "380.000"
ATIS_GUARD_MHZ = 0.5          # keep this clear of anything else in use


def used_frequencies(terrains: dict[str, list[dict]]) -> set[float]:
    """Every frequency any airfield uses, across all terrains installed."""
    return {channel["mhz"]
            for fields in terrains.values()
            for field in fields
            for channel in field["frequencies"]}


def frequency_conflict(mhz: float, terrains: dict[str, list[dict]]) -> float | None:
    """The nearest airfield frequency within the guard band, or None if clear."""
    nearest, distance = None, ATIS_GUARD_MHZ
    for used in used_frequencies(terrains):
        gap = abs(used - mhz)
        if gap < distance:
            nearest, distance = used, gap
    return nearest


def pick_atis_frequency(terrains: dict[str, list[dict]]) -> str:
    """An unused UHF frequency for the ATIS loop.

    Works downward from the top of the band, because terrains put airfields near the
    bottom of it, so the high end is reliably free.
    """
    candidate = 380.0
    while candidate >= UHF_MIN:
        if frequency_conflict(candidate, terrains) is None:
            return "%.3f" % candidate
        candidate -= 1.0
    return DEFAULT_ATIS_FREQUENCY


def lua_quote(value: str) -> str:
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def render_lua(terrains: dict[str, list[dict]]) -> str:
    """The table atc_core.lua reads to find the frequency for the field you're at.

    Keyed by lower-cased airfield name, and by every alias, because DCS reports airbase
    names in a few different flavours depending on terrain and coalition.
    """
    lines = [
        "-- Generated by the ATCAI manager from each terrain's Radio.lua.",
        "-- Do not edit: reinstalling or changing DCS terrains regenerates it.",
        "ATCAI_FREQUENCIES = {",
    ]
    for terrain in sorted(terrains):
        lines.append("    -- %s" % terrain)
        for field in terrains[terrain]:
            entries = ", ".join(
                '{ mhz = %.3f, modulation = %s, band = %s }'
                % (f["mhz"], lua_quote(f["modulation"]), lua_quote(f["band"]))
                for f in field["frequencies"])
            for alias in field["aliases"]:
                lines.append("    [%s] = { %s }," % (lua_quote(alias.lower()), entries))
    lines.append("}")
    return "\n".join(lines) + "\n"
