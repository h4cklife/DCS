--[[
Unit tests for lua/atc/atc_core.lua, run against DCS's own Lua 5.1 interpreter with the
mission-scripting API stubbed out. No DCS instance required.

Run:  tools/run_tests.sh
]]

local CORE_PATH = arg[1] or "../lua/atc/atc_core.lua"

-- ---------- test plumbing ----------

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

local function near(actual, expected, tolerance, label)
    local ok = actual and math.abs(actual - expected) <= tolerance
    check(ok, label, string.format("expected ~%s, got %s", tostring(expected), tostring(actual)))
end

local function contains(haystack, needle, label)
    check(haystack and haystack:find(needle, 1, true) ~= nil, label,
        string.format("%q does not contain %q", tostring(haystack), needle))
end

-- ---------- DCS API stubs ----------

local spoken = {}

-- Scenario knobs the tests mutate between cases.
local scenario = {
    windVector = { x = 0, y = 0, z = 0 },
    pressure = 101325,
    runways = { { Name = "13" } },
    airborne = false,
    airbaseDistance = 100,
    ammo = {},
    missionTime = 50400,      -- 14:00
}

env = { info = function() end }

trigger = {
    action = {
        outTextForGroup = function(_, text) table.insert(spoken, text) end,
    },
}

atmosphere = {
    getWind = function() return scenario.windVector end,
    getTemperatureAndPressure = function() return 288, scenario.pressure end,
}

local fakeAirbase = {
    getPoint = function() return { x = scenario.airbaseDistance, y = 0, z = 0 } end,
    getName = function() return "Vaziani" end,
    getCallsign = function() return "Vaziani Tower" end,
    getRunways = function() return scenario.runways end,
}

world = { getAirbases = function() return { fakeAirbase } end }
timer = { getAbsTime = function() return scenario.missionTime or 0 end }

local fakeUnit = {
    getName = function() return "- Chevy 81 (Player)" end,
    getPoint = function() return { x = 0, y = 0, z = 0 } end,
    inAir = function() return scenario.airborne end,
    getAmmo = function() return scenario.ammo end,
    getGroup = function() return { getID = function() return 42 end } end,
}

local params = { groupId = 42, unit = fakeUnit }

local function lastSpoken()
    return spoken[#spoken]
end

local function reset(phase)
    spoken = {}
    ATC.state = {}
    if phase then
        ATC.getState(fakeUnit:getName()).phase = phase
    end
end

-- ---------- load the code under test ----------

dofile(CORE_PATH)

-- ---------- pure helpers ----------

print("wind vector -> direction it comes from")
do
    local from, kts = ATC.windFromVector({ x = 0, y = 0, z = 10 })
    near(from, 270, 0.01, "air moving east means wind from the west")
    near(kts, 19.44, 0.01, "10 m/s is about 19.4 knots")

    from = ATC.windFromVector({ x = 10, y = 0, z = 0 })
    near(from, 180, 0.01, "air moving north means wind from the south")

    from = ATC.windFromVector({ x = -10, y = 0, z = 0 })
    near(from, 0, 0.01, "air moving south means wind from the north")

    local _, calm = ATC.windFromVector({ x = 0, y = 0, z = 0 })
    near(calm, 0, 0.001, "no air movement is zero knots")
end

print("runway designators")
do
    eq(ATC.headingToRunwayName(130), "13", "130 degrees is runway 13")
    eq(ATC.headingToRunwayName(0), "36", "north is runway 36, not 00")
    eq(ATC.headingToRunwayName(355), "36", "355 rounds to runway 36")
    eq(ATC.headingToRunwayName(310), "31", "310 degrees is runway 31")

    local ends = ATC.runwayEnds({ Name = "13" })
    eq(#ends, 2, "a runway has two usable ends")
    eq(ends[1].name, "13", "first end keeps the reported designator")
    eq(ends[2].name, "31", "opposite end is the reciprocal")
    eq(ends[1].heading, 130, "runway 13 points 130 degrees")
    eq(ends[2].heading, 310, "runway 31 points 310 degrees")

    local single = ATC.runwayEnds({ Name = "09L" })
    eq(single[1].name, "09", "suffix letters are ignored")
    eq(single[2].name, "27", "reciprocal of 09 is 27")

    local byCourse = ATC.runwayEnds({ Name = "", course = 0 })
    eq(#byCourse, 2, "falls back to course when the name isn't a designator")
end

print("active runway follows the wind")
do
    local pick = ATC.selectRunwayEnd({ { Name = "13" } }, 150)
    eq(pick.name, "13", "wind from 150 favours runway 13")

    pick = ATC.selectRunwayEnd({ { Name = "13" } }, 320)
    eq(pick.name, "31", "wind from 320 favours runway 31")

    pick = ATC.selectRunwayEnd({ { Name = "13" }, { Name = "04" } }, 40)
    eq(pick.name, "04", "picks the best end across multiple runways")

    eq(ATC.selectRunwayEnd({}, 0), nil, "no runways means no selection")
end

print("formatting")
do
    eq(ATC.formatWind(150, 8.3), "wind 150 at 8", "wind reads as direction and speed")
    eq(ATC.formatWind(5, 12), "wind 005 at 12", "direction is zero padded to three digits")
    eq(ATC.formatWind(150, 0.4), "wind calm", "sub-knot wind is reported as calm")
    eq(ATC.formatQNH(101325), "QNH 29.92", "standard pressure is 29.92 inHg")
    eq(ATC.formatQNH(0), "QNH unavailable", "bad pressure degrades gracefully")
end

print("scripts locate themselves")
do
    check(ATCAI_SCRIPT_DIR ~= nil, "the script worked out its own directory")
    check(ATCAI_SCRIPT_DIR and ATCAI_SCRIPT_DIR:match("[\\/]$") ~= nil,
        "the directory ends with a separator so paths concatenate cleanly")
    check(ATCAI_INBOX_PATH ~= nil, "an inbox path was derived without the mission supplying one")
    check(ATCAI_INBOX_PATH and ATCAI_INBOX_PATH:find("inbox.lua", 1, true) ~= nil,
        "the derived inbox path points at inbox.lua",
        tostring(ATCAI_INBOX_PATH))
end

print("transmits on the field's own frequencies")
do
    -- What the manager generates from the terrain's Radio.lua.
    ATCAI_FREQUENCIES = {
        ["vaziani tower"] = {
            { mhz = 4.700, modulation = "AM", band = "HF" },
            { mhz = 269.000, modulation = "AM", band = "UHF" },
        },
        ["batumi"] = { { mhz = 260.000, modulation = "FM", band = "UHF" } },
    }

    local freqs, modes = ATC.fieldFrequencies(fakeAirbase)
    eq(freqs, "4.700,269.000", "uses the frequencies this field actually broadcasts on")
    eq(modes, "AM,AM", "with a modulation per frequency")

    local byName = { getCallsign = function() return nil end,
                     getName = function() return "Batumi" end }
    freqs, modes = ATC.fieldFrequencies(byName)
    eq(freqs, "260.000", "falls back to the airbase name when there's no callsign")
    eq(modes, "FM", "keeps that field's modulation")

    local unknown = { getCallsign = function() return "Nowhere" end,
                      getName = function() return "Nowhere" end }
    freqs = ATC.fieldFrequencies(unknown)
    eq(freqs, ATC.TTS_FREQUENCY, "an unknown field falls back to the configured list")

    ATCAI_FREQUENCIES = nil
    freqs = ATC.fieldFrequencies(fakeAirbase)
    eq(freqs, ATC.TTS_FREQUENCY, "no generated table at all still works")
end

print("ATIS")
do
    eq(ATC.informationLetter(0), "Alpha", "midnight is information Alpha")
    eq(ATC.informationLetter(3600 * 3), "Delta", "the letter advances each hour")
    eq(ATC.informationLetter(3600 * 25), "Zulu", "hour 25 is still Zulu, the last letter")
    eq(ATC.informationLetter(3600 * 27), "Bravo", "past Zulu it wraps back round")
    eq(ATC.informationLetter(3600 * 14), "Oscar", "14:00 is information Oscar")

    eq(ATC.formatClock(50400), "1400", "14:00 reads as 1400")
    eq(ATC.formatClock(0), "0000", "midnight reads as 0000")
    eq(ATC.formatClock(3600 * 25), "0100", "past midnight wraps to the next day")

    eq(ATC.formatTemperature(20.6), "temperature 21", "temperature rounds to whole degrees")
    eq(ATC.formatTemperature(-4.2), "temperature minus 4", "below zero reads as minus")
    eq(ATC.formatTemperature(nil), "temperature unavailable", "missing data degrades gracefully")

    local conditions = {
        runway = { name = "13" },
        windText = "wind 074 at 6",
        qnhText = "QNH 29.92",
        celsius = 21,
    }
    local report = ATC.atisReport("Vaziani", conditions, 3600 * 3 + 1800)
    contains(report, "Vaziani information Delta", "names the field and the letter")
    contains(report, "time 0330", "gives the time")
    contains(report, "runway 13 in use", "names the runway in use")
    contains(report, "wind 074 at 6", "reports the wind")
    contains(report, "temperature 21", "reports the temperature")
    contains(report, "QNH 29.92", "reports the altimeter")
    contains(report, "you have information Delta", "asks you to acknowledge the letter")
end

print("requesting ATIS")
do
    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.requestATIS(params)
    contains(lastSpoken(), "information", "ATIS can be requested on the ground")

    -- It's information, not a clearance, so it must work at any point in a sortie.
    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestATIS(params)
    contains(lastSpoken(), "information", "and in the air")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.AIRBORNE,
        "asking for information doesn't change your phase")
    scenario.airborne = false
end

print("callsign cleanup")
do
    eq(ATC.callsign(fakeUnit), "Chevy 81", "editor decoration is stripped")
    eq(ATC.callsign({ getName = function() return "Uzi 11" end }), "Uzi 11", "clean names pass through")
    eq(ATC.callsign({ getName = function() return "(Player)" end }), "(Player)",
        "a name that is entirely decoration is left alone rather than blanked")
end

-- ---------- request behaviour ----------

print("departure sequence")
do
    scenario.airborne = false
    scenario.windVector = { x = -5, y = 0, z = -5 }   -- wind from about 045
    scenario.runways = { { Name = "13" } }

    reset(ATC.PHASE.PARKED)
    ATC.requestStartup(params)
    contains(lastSpoken(), "startup approved", "startup is approved when parked")
    contains(lastSpoken(), "QNH", "startup call includes the altimeter")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.STARTUP, "startup advances the phase")

    ATC.requestTaxi(params)
    contains(lastSpoken(), "holding point", "taxi gives a holding point")
    contains(lastSpoken(), "hold short", "taxi instruction ends with hold short")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.HOLDING_SHORT, "taxi advances the phase")

    ATC.requestTakeoff(params)
    contains(lastSpoken(), "cleared for takeoff", "takeoff clearance follows taxi")
    contains(lastSpoken(), "wind", "takeoff clearance reports the wind")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.TAKEOFF, "takeoff advances the phase")
end

print("phase enforcement")
do
    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "request taxi first", "cannot take off straight from parking")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.PARKED, "refused request leaves phase alone")

    reset(ATC.PHASE.PARKED)
    ATC.requestLanding(params)
    contains(lastSpoken(), "still on the ground", "cannot land while parked")

    reset(ATC.PHASE.PARKED)
    ATC.requestParking(params)
    contains(lastSpoken(), "haven't landed", "cannot taxi to parking without having landed")

    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestTaxi(params)
    contains(lastSpoken(), "airborne", "cannot taxi while airborne")

    reset(ATC.PHASE.AIRBORNE)
    ATC.requestStartup(params)
    contains(lastSpoken(), "airborne", "cannot request startup while airborne")
end

print("arrival sequence")
do
    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)

    ATC.requestInbound(params)
    contains(lastSpoken(), "join the circuit", "inbound gets a circuit join")
    contains(lastSpoken(), "report final", "inbound asks for a final call")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.INBOUND, "inbound advances the phase")

    ATC.requestLanding(params)
    contains(lastSpoken(), "cleared to land", "landing clearance follows inbound")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.LANDING, "landing advances the phase")

    scenario.airborne = false
    ATC.requestParking(params)
    contains(lastSpoken(), "taxi to parking", "after landing you get sent to parking")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.PARKED, "parking returns to the start phase")
end

print("runway in use tracks the wind")
do
    scenario.airborne = false
    scenario.runways = { { Name = "13" } }

    scenario.windVector = { x = 5, y = 0, z = 5 }      -- wind from about 225
    reset(ATC.PHASE.HOLDING_SHORT)
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "runway 31", "a southwesterly favours runway 31")

    scenario.windVector = { x = -5, y = 0, z = -5 }    -- wind from about 045
    reset(ATC.PHASE.HOLDING_SHORT)
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "runway 13", "a northeasterly favours runway 13")
end

print("range depends on whether you're airborne")
do
    -- 20 nm out: far beyond the ground radius, well inside the airborne one. This is the
    -- case that used to refuse every inbound call.
    scenario.airbaseDistance = 20 * 1852

    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestInbound(params)
    contains(lastSpoken(), "join the circuit", "an inbound call 20 miles out is answered")
    contains(lastSpoken(), "20 miles", "the inbound call reports how far out you are")

    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.requestStartup(params)
    contains(lastSpoken(), "no ATC in range",
        "the same distance on the ground is still out of range")
    contains(lastSpoken(), "20 miles", "the refusal says how far the nearest field is")

    -- Beyond even the airborne radius.
    scenario.airbaseDistance = 200 * 1852
    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestInbound(params)
    contains(lastSpoken(), "no ATC in range", "200 miles out is beyond any field")

    scenario.airbaseDistance = 100
    scenario.airborne = false
end

print("distance phrasing")
do
    eq(ATC.distanceText(20 * 1852), "20 miles", "metres convert to nautical miles")
    eq(ATC.distanceText(500), "overhead the field", "inside a mile reads as overhead")
    eq(ATC.distanceText(nil), "position unknown", "a missing distance degrades gracefully")
end

print("out of range and loadout")
do
    scenario.airborne = false
    scenario.airbaseDistance = 50000
    reset(ATC.PHASE.PARKED)
    ATC.requestRadioCheck(params)
    contains(lastSpoken(), "no ATC in range", "distant fields do not answer")
    scenario.airbaseDistance = 100

    reset(ATC.PHASE.PARKED)
    scenario.ammo = {}
    ATC.requestLoadout(params)
    contains(lastSpoken(), "no stores remaining", "empty aircraft reports no stores")

    scenario.ammo = { { count = 4, desc = { displayName = "AIM-120C" } } }
    ATC.requestLoadout(params)
    contains(lastSpoken(), "4 AIM-120C", "loadout lists counts and weapon names")
end

-- ---------- summary ----------

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
