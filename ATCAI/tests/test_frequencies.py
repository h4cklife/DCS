"""Reading real airfield frequencies out of DCS's terrain files."""

import pytest

import frequencies

# A faithful slice of Mods/terrains/Caucasus/Radio.lua, including the awkward bits:
# two callsign flavours, an FM entry, and an entry with no tower role.
SAMPLE = """
dofile('Scripts/World/Radio/ModulationTypes.lua')
radio = {
\t{
\t\t-- Anapa
\t\tradioId = 'airfield12_0';
\t\trole = {"ground", "tower", "approach"};
\t\tcallsign = {{["common"] = {_("Anapa"), "Anapa"}}};
\t\tfrequency = {[HF] = {MODULATIONTYPE_AM, 3750000.000000}, [UHF] = {MODULATIONTYPE_AM, 250000000.000000}};
\t};
\t{
\t\t-- Batumi
\t\tradioId = 'airfield22_0';
\t\trole = {"ground", "tower", "approach"};
\t\tcallsign = {{["nato"] = {_("Batumi"), "Batumi"}}, {["ussr"] = {_("Druzhinnik"), "Druzhinnik"}}};
\t\tfrequency = {[UHF] = {MODULATIONTYPE_AM, 260000000.000000}, [VHF_LOW] = {MODULATIONTYPE_FM, 40400000.000000}};
\t};
\t{
\t\t-- A beacon, not a tower
\t\tradioId = 'beacon_1';
\t\trole = {"beacon"};
\t\tcallsign = {{["common"] = {_("Kutaisi"), "Kutaisi"}}};
\t\tfrequency = {[UHF] = {MODULATIONTYPE_AM, 999000000.000000}};
\t};
}
"""


@pytest.fixture
def parsed():
    return frequencies.parse_radio_lua(SAMPLE)


class TestParsing:
    def test_finds_each_airfield(self, parsed):
        assert [f["name"] for f in parsed] == ["Anapa", "Batumi"]

    def test_skips_entries_without_a_tower(self, parsed):
        assert "Kutaisi" not in [f["name"] for f in parsed]

    def test_converts_hertz_to_megahertz(self, parsed):
        anapa = parsed[0]
        assert {f["mhz"] for f in anapa["frequencies"]} == {3.75, 250.0}

    def test_keeps_the_modulation(self, parsed):
        batumi = parsed[1]
        modulations = {f["band"]: f["modulation"] for f in batumi["frequencies"]}
        assert modulations == {"UHF": "AM", "VHF_LOW": "FM"}

    def test_keeps_every_callsign_a_field_answers_to(self, parsed):
        assert parsed[1]["aliases"] == ["Batumi", "Druzhinnik"]

    def test_prefers_the_common_name(self, parsed):
        # NATO before USSR, so a field reads as the name players know.
        assert parsed[1]["name"] == "Batumi"

    def test_empty_input_is_not_an_error(self):
        assert frequencies.parse_radio_lua("") == []


class TestGeneratedLua:
    def test_every_alias_is_addressable(self, parsed):
        lua = frequencies.render_lua({"Caucasus": parsed})
        # DCS reports airbase names inconsistently, so both names must resolve.
        assert '["batumi"]' in lua
        assert '["druzhinnik"]' in lua

    def test_keys_are_lowercased_for_lookup(self, parsed):
        lua = frequencies.render_lua({"Caucasus": parsed})
        assert '["Batumi"]' not in lua

    def test_says_it_is_generated(self, parsed):
        assert frequencies.render_lua({"Caucasus": parsed}).startswith("--")

    def test_quotes_cannot_break_the_table(self):
        assert frequencies.lua_quote('a"b') == '"a\\"b"'


class TestAgainstTheRealInstall:
    """Skips cleanly where DCS isn't installed, e.g. on a CI runner."""

    @pytest.fixture
    def install(self):
        import installer
        found = installer.find_dcs_installs()
        if not found:
            pytest.skip("no DCS install found")
        return found[0]

    def test_reads_at_least_one_terrain(self, install):
        terrains = frequencies.read_terrains(install)
        assert terrains, "no terrain Radio.lua parsed"
        assert all(fields for fields in terrains.values())

    def test_matches_frequencies_dcs_itself_reports(self, install):
        """Ground truth taken from DCS's own in-game ATC menu."""
        terrains = frequencies.read_terrains(install)
        fields = {f["name"]: f for group in terrains.values() for f in group}
        if "Vaziani" not in fields:
            pytest.skip("Caucasus not installed")

        vaziani = {f["mhz"] for f in fields["Vaziani"]["frequencies"]}
        assert {4.7, 140.0, 42.2, 269.0} <= vaziani


class TestAtisFrequencyChoice:
    """The ATIS loop needs a frequency nobody else uses, in a band aircraft can tune."""

    @pytest.fixture
    def terrains(self, parsed):
        return {"Caucasus": parsed}

    def test_default_is_in_the_uhf_band(self):
        mhz = float(frequencies.DEFAULT_ATIS_FREQUENCY)
        assert frequencies.UHF_MIN <= mhz <= frequencies.UHF_MAX

    def test_picks_something_clear(self, terrains):
        picked = float(frequencies.pick_atis_frequency(terrains))
        assert frequencies.frequency_conflict(picked, terrains) is None
        assert frequencies.UHF_MIN <= picked <= frequencies.UHF_MAX

    def test_detects_a_direct_clash(self, terrains):
        # Anapa is on 250.000 in the sample.
        assert frequencies.frequency_conflict(250.0, terrains) == 250.0

    def test_detects_a_near_miss(self, terrains):
        """Landing next to an airfield frequency would still talk over it."""
        assert frequencies.frequency_conflict(250.2, terrains) == 250.0

    def test_allows_a_frequency_outside_the_guard_band(self, terrains):
        assert frequencies.frequency_conflict(251.0, terrains) is None

    def test_avoids_a_clash_when_the_default_is_taken(self, parsed):
        """If a terrain ever used 380, the picker must move rather than collide."""
        crowded = dict(parsed[0])
        crowded["frequencies"] = [{"band": "UHF", "modulation": "AM", "mhz": 380.0}]
        terrains = {"Busy": [crowded]}

        picked = float(frequencies.pick_atis_frequency(terrains))
        assert picked != 380.0
        assert frequencies.frequency_conflict(picked, terrains) is None

    def test_no_terrains_still_gives_a_usable_frequency(self):
        picked = float(frequencies.pick_atis_frequency({}))
        assert frequencies.UHF_MIN <= picked <= frequencies.UHF_MAX
