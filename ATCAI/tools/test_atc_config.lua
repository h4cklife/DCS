--[[
Tests for lua/atc/atc_config.lua — user settings applied over script defaults.

This is what the manager app will write, so the important properties are: a good setting
takes effect, a bad one is ignored individually rather than taking the rest down with it,
and a missing file is simply the default case.

Args: <atc_config.lua> <atc_core.lua>
]]

local CONFIG_PATH, CORE_PATH = arg[1], arg[2]

local failures, checks = 0, 0

local function check(ok, label, detail)
    checks = checks + 1
    if ok then
        print(string.format("  ok   %s", label))
    else
        failures = failures + 1
        print(string.format("  FAIL %s%s", label, detail and ("  -> " .. detail) or ""))
    end
end

local function eq(actual, expected, label)
    check(actual == expected, label,
        string.format("expected %s, got %s", tostring(expected), tostring(actual)))
end

env = { info = function() end }

dofile(CONFIG_PATH)

print("valid settings are applied")
do
    ATC.TTS_FREQUENCY, ATC.AIRBASE_AIR_RADIUS = nil, nil
    local applied, rejected = ATC.applyConfig({
        tts_frequency = "251.0",
        airbase_air_radius = 120000,
    })
    eq(applied, 2, "both settings were applied")
    eq(#rejected, 0, "nothing was rejected")
    eq(ATC.TTS_FREQUENCY, "251.0", "the frequency reached the right field")
    eq(ATC.AIRBASE_AIR_RADIUS, 120000, "the radius reached the right field")
end

print("bad settings are rejected individually")
do
    ATC.AIRBASE_AIR_RADIUS = 92600
    local applied, rejected = ATC.applyConfig({
        airbase_air_radius = "not a number",
        tts_frequency = "251.0",
    })
    eq(applied, 1, "the good setting still applied")
    eq(#rejected, 1, "only the bad one was rejected")
    eq(ATC.AIRBASE_AIR_RADIUS, 92600, "the bad value did not overwrite the default")

    applied, rejected = ATC.applyConfig({ made_up_setting = 5 })
    eq(applied, 0, "unknown settings are not applied")
    eq(#rejected, 1, "unknown settings are reported")

    applied, rejected = ATC.applyConfig({ traffic_roll_speed = -5 })
    eq(applied, 0, "a negative distance is refused")
    eq(#rejected, 1, "the negative value is reported")

    eq(ATC.applyConfig(nil), 0, "no config at all is harmless")
    eq(ATC.applyConfig("garbage"), 0, "a non-table config is harmless")
end

print("loading from disk")
do
    eq(ATC.loadConfig(nil), 0, "no path means nothing to load")
    eq(ATC.loadConfig("Z:\\definitely\\not\\here\\config.lua"), 0,
        "a missing file is the normal case, not an error")
end

print("config wins over script defaults")
do
    -- Simulate the real load order: config is applied, then atc_core sets its defaults.
    for key in pairs(package and package.loaded or {}) do end
    ATC = { state = {} }
    dofile(CONFIG_PATH)
    ATC.applyConfig({ airbase_air_radius = 150000, tts_frequency = "133.0" })

    -- Stub just enough for atc_core to load.
    trigger = { action = { outTextForGroup = function() end } }
    world = { getAirbases = function() return {} end }
    atmosphere = { getWind = function() return { x = 0, y = 0, z = 0 } end,
                   getTemperatureAndPressure = function() return 288, 101325 end }
    ATCAI_SCRIPT_DIR = false      -- stop atc_core auto-loading siblings during the test
    dofile(CORE_PATH)

    eq(ATC.AIRBASE_AIR_RADIUS, 150000, "a configured radius survives atc_core loading")
    eq(ATC.TTS_FREQUENCY, "133.0", "a configured frequency survives atc_core loading")
    eq(ATC.AIRBASE_SEARCH_RADIUS, 6000, "an unconfigured setting still gets its default")
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
