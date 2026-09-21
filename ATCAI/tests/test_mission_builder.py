"""Building a test mission: the loader trigger, the clock, and AI traffic."""

import sys
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))

import build_test_mission as builder  # noqa: E402


# A mission cut down to the parts the builder touches: one player aircraft parked at an
# airfield, with a route that names the field.
MISSION = '''\t["coalition"] =
\t{
\t\t["blue"] =
\t\t{
\t\t\t["country"] =
\t\t\t{
\t\t\t\t[1] =
\t\t\t\t{
\t\t\t\t\t["plane"] =
\t\t\t\t\t{
\t\t\t\t\t\t["group"] =
\t\t\t\t\t\t{
\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t["route"] =
\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t["points"] =
\t\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t\t\t["type"] = "TakeOffParking",
\t\t\t\t\t\t\t\t\t\t\t["y"] = 903148.5,
\t\t\t\t\t\t\t\t\t\t\t["x"] = -319064.8,
\t\t\t\t\t\t\t\t\t\t\t["airdromeId"] = 31,
\t\t\t\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t\t\t\t}, -- end of ["points"]
\t\t\t\t\t\t\t\t}, -- end of ["route"]
\t\t\t\t\t\t\t\t["start_time"] = 70800,
\t\t\t\t\t\t\t\t["groupId"] = 42,
\t\t\t\t\t\t\t\t["units"] =
\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t\t["skill"] = "Player",
\t\t\t\t\t\t\t\t\t\t["type"] = "F-15C",
\t\t\t\t\t\t\t\t\t\t["unitId"] = 51,
\t\t\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t\t\t}, -- end of ["units"]
\t\t\t\t\t\t\t\t["name"] = "Chevy 81",
\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t}, -- end of ["group"]
\t\t\t\t\t}, -- end of ["plane"]
\t\t\t\t}, -- end of [1]
\t\t\t}, -- end of ["country"]
\t\t}, -- end of ["blue"]
\t}, -- end of ["coalition"]
\t["start_time"] = 0,
'''


class TestFindingThePlayersField:
    def test_reads_the_field_from_the_players_route(self):
        field = builder.find_player_airfield(MISSION)
        assert field["airdrome_id"] == 31
        assert field["x"] == pytest.approx(-319064.8)
        assert field["y"] == pytest.approx(903148.5)

    def test_returns_nothing_without_a_player(self):
        assert builder.find_player_airfield("no player here") is None


class TestIdAllocation:
    def test_ids_start_above_everything_in_use(self):
        group_id, unit_id = builder.next_ids(MISSION)
        assert group_id == 43
        assert unit_id == 52

    def test_empty_mission_still_yields_ids(self):
        assert builder.next_ids("") == (1, 1)


class TestPlayerSurvives:
    """The bug this guards against: AI flights inserted at the wrong nesting depth
    landed in the country list instead of the group list, and the player vanished from
    the mission - you could only switch between AI aircraft."""

    def test_finds_the_list_the_player_is_in(self):
        located = builder.player_group_list(MISSION)
        assert located is not None
        entry_indent, _, indices = located
        assert indices == [1], "the player's group is the only entry to start with"
        assert entry_indent > 0

    def test_traffic_is_a_sibling_of_the_player(self):
        import re
        entry_indent, _, _ = builder.player_group_list(MISSION)
        text, _ = builder.add_traffic(MISSION, 2)

        pattern = re.compile(r"^%s\[(\d+)\]\s*=\s*$" % ("\t" * entry_indent), re.M)
        indices = [int(m.group(1)) for m in pattern.finditer(text)]
        assert indices == [1, 2, 3], "traffic must be added beside the player, not elsewhere"

    def test_the_player_is_still_there(self):
        text, _ = builder.add_traffic(MISSION, 3)
        assert text.count('["skill"] = "Player"') == 1
        assert '["name"] = "Chevy 81"' in text

    def test_no_index_collides_with_the_player(self):
        """A duplicate index silently replaces the earlier entry in Lua."""
        import re
        entry_indent, _, _ = builder.player_group_list(MISSION)
        text, _ = builder.add_traffic(MISSION, 4)
        pattern = re.compile(r"^%s\[(\d+)\]\s*=\s*$" % ("\t" * entry_indent), re.M)
        indices = [m.group(1) for m in pattern.finditer(text)]
        assert len(indices) == len(set(indices))

    def test_does_nothing_when_the_list_cannot_be_found(self):
        text, added = builder.add_traffic('["skill"] = "Player"', 2)
        assert added == 0


class TestAddingTraffic:
    def test_adds_the_requested_number(self):
        text, added = builder.add_traffic(MISSION, 3)
        assert added == 3
        # Each flight names both the group and the unit inside it.
        for n in (1, 2, 3):
            assert '["name"] = "ATCAI Traffic %d"' % n in text
            assert '["name"] = "ATCAI Traffic %d-1"' % n in text

    def test_traffic_uses_the_players_own_airfield(self):
        """Traffic at some other field would never conflict with the player."""
        import re
        text, _ = builder.add_traffic(MISSION, 2)
        airfields = set(re.findall(r'"airdromeId"\] = (\d+)', text))
        assert airfields == {"31"}, "traffic must use the player's field, not another"
        # One takeoff and one landing per flight, plus the player's own parking start.
        assert len(re.findall(r'"airdromeId"\] = 31', text)) == 1 + 2 * 2

    def test_ids_do_not_collide_with_the_mission(self):
        import re
        text, _ = builder.add_traffic(MISSION, 4)
        groups = [int(v) for v in re.findall(r'"groupId"\] = (\d+)', text)]
        units = [int(v) for v in re.findall(r'"unitId"\] = (\d+)', text)]
        assert len(groups) == len(set(groups))
        assert len(units) == len(set(units))

    def test_flights_are_staggered(self):
        """All starting at once would give one burst, then an empty circuit."""
        import re
        text, _ = builder.add_traffic(MISSION, 3, spacing=120)
        # Only the flights' own start times; the mission has one of its own.
        starts = [int(v) for v in re.findall(
            r'"name"\] = "ATCAI Traffic \d+",\s*\n\s*\["communication"\] = true,'
            r'\s*\n\s*\["start_time"\] = (\d+)', text)]
        assert len(starts) == 3
        assert starts == sorted(starts)
        assert starts[1] - starts[0] == 120

    def test_each_flight_takes_off_and_lands(self):
        text, _ = builder.add_traffic(MISSION, 1)
        assert '["type"] = "TakeOff"' in text
        assert '["type"] = "Land"' in text

    def test_uses_an_aircraft_everyone_owns_by_default(self):
        text, _ = builder.add_traffic(MISSION, 1)
        assert '"%s"' % builder.DEFAULT_TRAFFIC_TYPE in text

    def test_aircraft_type_can_be_chosen(self):
        text, _ = builder.add_traffic(MISSION, 1, aircraft="F-15C")
        assert '["type"] = "F-15C"' in text

    def test_does_nothing_without_a_player(self):
        text, added = builder.add_traffic("nothing useful here", 3)
        assert added == 0
        assert text == "nothing useful here"

    def test_the_result_is_still_valid_lua(self, tmp_path):
        """A malformed group would make DCS refuse the whole mission."""
        from conftest import dcs_lua
        lua = dcs_lua()
        if lua is None:
            pytest.skip("DCS's Lua interpreter not found")

        text, _ = builder.add_traffic(MISSION, 3)
        mission_file = tmp_path / "mission.lua"
        mission_file.write_text("mission = {\n" + text + "}\n", encoding="utf-8")

        import subprocess
        checker = tmp_path / "check.lua"
        checker.write_text(
            'local c, e = loadfile(arg[1])\n'
            'if not c then print("PARSE ERROR: " .. tostring(e)) os.exit(1) end\n'
            'os.exit(0)\n', encoding="utf-8")

        def win(path):
            try:
                return subprocess.run(["wslpath", "-w", str(path)], capture_output=True,
                                      text=True, check=True).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return str(path)

        result = subprocess.run([str(lua), win(checker), win(mission_file)],
                                capture_output=True, cwd=str(lua.parent), timeout=120)
        output = (result.stdout + result.stderr).decode("cp1252", errors="replace")
        assert result.returncode == 0, output


class TestClock:
    @pytest.mark.parametrize("text,seconds", [
        ("12:00", 43200),
        ("00:00", 0),
        ("23:59", 86340),
    ])
    def test_parses_a_time(self, text, seconds):
        assert builder.parse_clock(text) == seconds

    @pytest.mark.parametrize("bad", ["noon", "25:00", "12:99", "1200"])
    def test_rejects_nonsense(self, bad):
        with pytest.raises(SystemExit):
            builder.parse_clock(bad)

    def test_sets_the_missions_start_time(self):
        text = builder.set_start_time(MISSION, 43200)
        assert '\n\t["start_time"] = 43200' in text

    def test_leaves_group_start_times_alone(self):
        """The bug: the first ["start_time"] in a real .miz belongs to some ground
        group, not the mission. Rewriting that one changed a unit's spawn delay and
        left the mission at whatever hour it shipped with - so --start-time silently
        did nothing, and every mission built this way stayed at dusk."""
        text = builder.set_start_time(MISSION, 43200)
        assert '["start_time"] = 70800' in text, "the group's own start time must survive"
        assert text.count('["start_time"] = 43200') == 1

    def test_the_fixture_keeps_the_realistic_order(self):
        """Guards the fixture itself: with the mission key first, the old bug passes."""
        group_key = MISSION.index('\t\t["start_time"]')
        mission_key = MISSION.index('\n\t["start_time"]')
        assert group_key < mission_key, "a group start_time must come first, as in a real .miz"

    def test_refuses_a_mission_without_one(self):
        with pytest.raises(SystemExit):
            builder.set_start_time('\t\t\t["start_time"] = 5,', 43200)


# The fixture above has no enemy coalition; ground targets need one to sit in.
MISSION_WITH_ENEMY = MISSION.replace(
    '\t}, -- end of ["coalition"]',
    '''\t\t["red"] =
\t\t{
\t\t\t["country"] =
\t\t\t{
\t\t\t\t[1] =
\t\t\t\t{
\t\t\t\t\t["vehicle"] =
\t\t\t\t\t{
\t\t\t\t\t\t["group"] =
\t\t\t\t\t\t{
\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t["groupId"] = 90,
\t\t\t\t\t\t\t\t["units"] =
\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t\t["unitId"] = 99,
\t\t\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t\t\t}, -- end of ["units"]
\t\t\t\t\t\t\t\t["name"] = "Existing Convoy",
\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t}, -- end of ["group"]
\t\t\t\t\t}, -- end of ["vehicle"]
\t\t\t\t}, -- end of [1]
\t\t\t}, -- end of ["country"]
\t\t}, -- end of ["red"]
\t}, -- end of ["coalition"]''')


class TestGroundTargets:
    def test_knows_which_side_the_player_is_on(self):
        sides, mine = builder.coalition_bounds(MISSION_WITH_ENEMY)
        assert mine == "blue"
        assert "red" in sides

    def test_finds_the_enemy_vehicle_list(self):
        """Targets on the player's own side could not be shot at."""
        located = builder.enemy_vehicle_list(MISSION_WITH_ENEMY)
        assert located is not None
        _, _, indices = located
        assert indices == [1]

    def test_anchors_on_the_missions_airfields(self):
        anchors = builder.target_anchors(MISSION_WITH_ENEMY)
        assert anchors == [(pytest.approx(-319064.8), pytest.approx(903148.5))]

    def test_adds_the_requested_number(self):
        text, added = builder.add_ground_targets(MISSION_WITH_ENEMY, 3)
        assert added == 3
        for n in (1, 2, 3):
            assert '["name"] = "ATCAI Target %d"' % n in text

    def test_targets_are_spread_out_not_stacked(self):
        import re
        text, _ = builder.add_ground_targets(MISSION_WITH_ENEMY, 4)
        blocks = re.findall(r'"name"\] = "ATCAI Target \d+",', text)
        assert len(blocks) == 4
        # Group-level coordinates must all differ, or they'd be piled on one spot.
        # The trailing \d+" keeps this off the unit names, which end "Target 1-2".
        coords = re.findall(r'\["y"\] = ([-\d.]+),\s*\n\s*\["x"\] = ([-\d.]+),\s*\n\s*'
                            r'\["name"\] = "ATCAI Target \d+",', text)
        assert len(coords) == 4
        assert len(set(coords)) == 4

    def test_placed_away_from_the_airfield_itself(self):
        """On top of the runway would be no fun and would block operations."""
        import math
        anchors = builder.target_anchors(MISSION_WITH_ENEMY)
        placements = builder.ground_positions(anchors, 3, radius=12000)
        for x, y in placements:
            distance = math.hypot(x - anchors[0][0], y - anchors[0][1])
            assert distance == pytest.approx(12000, rel=0.01)

    def test_ids_do_not_collide(self):
        import re
        text, _ = builder.add_ground_targets(MISSION_WITH_ENEMY, 3)
        groups = [int(v) for v in re.findall(r'"groupId"\] = (\d+)', text)]
        units = [int(v) for v in re.findall(r'"unitId"\] = (\d+)', text)]
        assert len(groups) == len(set(groups))
        assert len(units) == len(set(units))

    def test_uses_core_dcs_vehicles(self):
        """A module-locked vehicle would break the mission for most people."""
        text, _ = builder.add_ground_targets(MISSION_WITH_ENEMY, 2)
        assert any('["type"] = "%s"' % v in text for v in builder.TARGET_VEHICLES)

    def test_undefended_by_default(self):
        text, _ = builder.add_ground_targets(MISSION_WITH_ENEMY, 2)
        assert not any('["type"] = "%s"' % v in text for v in builder.TARGET_DEFENCES)

    def test_can_be_given_air_defence(self):
        text, _ = builder.add_ground_targets(MISSION_WITH_ENEMY, 2, defended=True)
        assert any('["type"] = "%s"' % v in text for v in builder.TARGET_DEFENCES)

    def test_the_player_is_untouched(self):
        text, _ = builder.add_ground_targets(MISSION_WITH_ENEMY, 3)
        assert text.count('["skill"] = "Player"') == 1

    def test_does_nothing_without_an_enemy_coalition(self):
        text, added = builder.add_ground_targets(MISSION, 3)
        assert added == 0
        assert text == MISSION

    def test_traffic_and_targets_coexist(self):
        text, flights = builder.add_traffic(MISSION_WITH_ENEMY, 2)
        text, targets = builder.add_ground_targets(text, 2)
        assert (flights, targets) == (2, 2)
        assert text.count('["skill"] = "Player"') == 1
        import re
        units = [int(v) for v in re.findall(r'"unitId"\] = (\d+)', text)]
        assert len(units) == len(set(units)), "adding both must not reuse ids"


# Enemy aircraft need an enemy plane list to sit in.
MISSION_WITH_ENEMY_AIR = MISSION_WITH_ENEMY.replace(
    '''\t\t\t\t\t["vehicle"] =''',
    '''\t\t\t\t\t["plane"] =
\t\t\t\t\t{
\t\t\t\t\t\t["group"] =
\t\t\t\t\t\t{
\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t["groupId"] = 80,
\t\t\t\t\t\t\t\t["units"] =
\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t[1] =
\t\t\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\t\t\t["unitId"] = 89,
\t\t\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t\t\t}, -- end of ["units"]
\t\t\t\t\t\t\t\t["name"] = "Existing Bandits",
\t\t\t\t\t\t\t}, -- end of [1]
\t\t\t\t\t\t}, -- end of ["group"]
\t\t\t\t\t}, -- end of ["plane"]
\t\t\t\t\t["vehicle"] =''')


class TestEnemyAir:
    """Stock missions often gate their enemy flights behind triggers that never fire
    outside their own objectives, so a reused mission can look populated yet give no
    fight. These flights have no conditions attached."""

    def test_finds_the_enemy_plane_list(self):
        located = builder.enemy_group_list(MISSION_WITH_ENEMY_AIR, "plane")
        assert located is not None
        _, _, indices = located
        assert indices == [1]

    def test_does_not_put_bandits_on_the_players_side(self):
        """The player's own plane list must be left alone."""
        text, added = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 2)
        assert added == 2
        player_indent, _, _ = builder.player_group_list(text)
        import re
        pattern = re.compile(r"^%s\[(\d+)\]\s*=\s*$" % ("\t" * player_indent), re.M)
        player_side = text[:text.index('["red"] =')]
        assert len(pattern.findall(player_side)) == 1, "player's list gained a group"

    def test_adds_the_requested_number(self):
        text, added = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 3)
        assert added == 3
        for n in (1, 2, 3):
            assert '["name"] = "ATCAI Bandit %d"' % n in text

    def test_flights_are_active_from_the_start(self):
        """lateActivation would reproduce the exact problem this option exists to fix."""
        before = MISSION_WITH_ENEMY_AIR.count('["lateActivation"] = false')
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 2)
        assert text.count('["lateActivation"] = false') == before + 2
        assert '["lateActivation"] = true' not in text.split("ATCAI Bandit")[1]
        assert '["start_time"] = 0' in text

    def test_flights_are_airborne(self):
        """Spawning them on a ramp would mean no fight for a long time, if ever."""
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 1, altitude=5000)
        assert '["type"] = "Turning Point"' in text
        assert '["alt"] = 5000' in text
        assert "TakeOffParking" not in text.split("ATCAI Bandit")[1]

    def test_flights_are_told_to_engage(self):
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 1)
        assert '["task"] = "CAP"' in text
        assert '["id"] = "EngageTargets"' in text
        assert '[1] = "Air",' in text

    def test_flight_size_is_configurable(self):
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 1, flight_size=4)
        assert text.count('["name"] = "ATCAI Bandit 1-') == 4

    def test_uses_core_dcs_aircraft(self):
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 2)
        assert any('["type"] = "%s"' % a in text for a in builder.ENEMY_AIR_TYPES)

    def test_aircraft_can_be_chosen(self):
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 1, aircraft="MiG-29S")
        assert '["type"] = "MiG-29S"' in text

    def test_ids_do_not_collide(self):
        import re
        text, _ = builder.add_enemy_air(MISSION_WITH_ENEMY_AIR, 3, flight_size=2)
        groups = [int(v) for v in re.findall(r'"groupId"\] = (\d+)', text)]
        units = [int(v) for v in re.findall(r'"unitId"\] = (\d+)', text)]
        assert len(groups) == len(set(groups))
        assert len(units) == len(set(units))

    def test_does_nothing_without_an_enemy_plane_list(self):
        text, added = builder.add_enemy_air(MISSION, 2)
        assert added == 0

    def test_everything_together_keeps_ids_unique(self):
        """Traffic, ground targets and bandits all allocate from the same pool."""
        import re
        text, a = builder.add_traffic(MISSION_WITH_ENEMY_AIR, 2)
        text, b_ = builder.add_ground_targets(text, 3)
        text, c = builder.add_enemy_air(text, 2)
        assert (a, b_, c) == (2, 3, 2)
        assert text.count('["skill"] = "Player"') == 1
        units = [int(v) for v in re.findall(r'"unitId"\] = (\d+)', text)]
        groups = [int(v) for v in re.findall(r'"groupId"\] = (\d+)', text)]
        assert len(units) == len(set(units))
        assert len(groups) == len(set(groups))
