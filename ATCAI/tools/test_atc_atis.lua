--[[
Unit tests for lua/atc/atc_atis.lua — the repeating airfield information broadcast.

Args: <atc_core.lua> <atc_atis.lua>
]]

local CORE_PATH, ATIS_PATH = arg[1], arg[2]

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

local function contains(haystack, needle, label)
    check(haystack and haystack:find(needle, 1, true) ~= nil, label,
        string.format("%q does not contain %q", tostring(haystack), needle))
end

-- ---------- stubs ----------

local logged = {}
local onScreen = {}
local scheduled = nil

env = { info = function(msg) table.insert(logged, msg) end }
trigger = { action = { outTextForGroup = function(_, t) table.insert(onScreen, t) end } }
atmosphere = {
    getWind = function() return { x = -5, y = 0, z = -5 } end,
    getTemperatureAndPressure = function() return 294.15, 101325 end,
}

local airbaseInRange = true
local fakeAirbase = {
    getPoint = function() return { x = airbaseInRange and 100 or 500000, y = 0, z = 0 } end,
    getName = function() return "Vaziani" end,
    getCallsign = function() return "Vaziani Tower" end,
    getRunways = function() return { { Name = "13" } } end,
}
world = { getAirbases = function() return { fakeAirbase } end }
timer = {
    getTime = function() return 0 end,
    getAbsTime = function() return 3600 * 3 end,     -- 03:00, information Delta
    scheduleFunction = function(fn) scheduled = fn end,
}

local unitExists = true
local fakeUnit = {
    getName = function() return "Chevy 81" end,
    getPoint = function() return { x = 0, y = 0, z = 0 } end,
    inAir = function() return false end,
    isExist = function() return unitExists end,
    getAmmo = function() return {} end,
    getGroup = function() return { getID = function() return 42 end } end,
}

dofile(CORE_PATH)
dofile(ATIS_PATH)
ATC.players = { [42] = fakeUnit }

local function lastBroadcast()
    for i = #logged, 1, -1 do
        if logged[i]:find("ATCAI_TTS|", 1, true) then
            return logged[i]
        end
    end
    return nil
end

-- ---------- tests ----------

print("the broadcast schedules itself")
do
    check(scheduled ~= nil, "a repeating broadcast was scheduled")
    eq(ATC.ATIS_INTERVAL, 60, "it repeats every 60 seconds by default")
    eq(ATC.ATIS_FREQUENCY, "380.000", "on 380.000 by default")
    eq(ATC.ATIS_MODULATION, "AM", "in AM")
    eq(ATC.ATIS_ENABLED, true, "and is on by default")
end

print("what goes out")
do
    logged, onScreen = {}, {}
    eq(ATC.broadcastAtis(), true, "it transmits when a player is near a field")

    local line = lastBroadcast()
    contains(line, "ATCAI_TTS|380.000|AM|", "goes out on the ATIS frequency, not the tower's")
    contains(line, "Vaziani Tower information Delta", "carries the field's information")
    contains(line, "runway 13 in use", "names the runway in use")
    contains(line, "temperature 21", "reports the temperature")

    eq(#onScreen, 0, "nothing is written on screen - a minute-by-minute caption would nag")
end

print("it stays quiet when there's nobody to hear it")
do
    logged = {}
    airbaseInRange = false
    eq(ATC.broadcastAtis(), false, "no transmission when no airfield is in range")
    eq(lastBroadcast(), nil, "and nothing reaches the log")
    airbaseInRange = true

    logged = {}
    ATC.players = {}
    eq(ATC.broadcastAtis(), false, "no transmission when no player is flying")
    ATC.players = { [42] = fakeUnit }
end

print("it can be turned off")
do
    logged = {}
    ATC.ATIS_ENABLED = false
    eq(ATC.broadcastAtis(), false, "disabled means silent")
    eq(lastBroadcast(), nil, "nothing is transmitted")
    ATC.ATIS_ENABLED = true
end

print("settings drive it")
do
    logged = {}
    ATC.ATIS_FREQUENCY = "251.000"
    ATC.ATIS_MODULATION = "FM"
    ATC.broadcastAtis()
    contains(lastBroadcast(), "ATCAI_TTS|251.000|FM|", "a configured frequency is used")
    ATC.ATIS_FREQUENCY, ATC.ATIS_MODULATION = "380.000", "AM"
end

print("stale players are cleaned up")
do
    unitExists = false
    logged = {}
    eq(ATC.broadcastAtis(), false, "a unit that no longer exists produces no broadcast")
    eq(ATC.players[42], nil, "and is dropped from the registry")
    unitExists = true
end

print("the scheduled tick keeps going")
do
    ATC.players = { [42] = fakeUnit }
    local nextTime = scheduled()
    check(nextTime and nextTime > 0, "the tick reschedules itself")
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
