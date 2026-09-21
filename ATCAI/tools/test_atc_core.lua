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
    unitSide = 2,             -- BLUE
    airbaseSide = 2,
    otherSide = 2,
    otherDistance = 40000,
}

-- What actually goes over the radio: "ATCAI_TTS|<freqs>|<modulations>|<text>".
-- Checking only the on-screen text let a reply ship that was visible and inaudible.
-- Declared before the stub that appends to it: a local declared later would leave the
-- closure reading a nil global instead.
local transmissions = {}

env = { info = function(message)
    if tostring(message):find("ATCAI_TTS|", 1, true) then
        table.insert(transmissions, message)
    end
end }

trigger = {
    action = {
        outTextForGroup = function(_, text) table.insert(spoken, text) end,
    },
}

atmosphere = {
    getWind = function() return scenario.windVector end,
    getTemperatureAndPressure = function() return 288, scenario.pressure end,
}

coalition = { side = { NEUTRAL = 0, RED = 1, BLUE = 2 } }

local fakeAirbase = {
    getPoint = function() return { x = scenario.airbaseDistance, y = 0, z = 0 } end,
    getName = function() return "Vaziani" end,
    getCallsign = function() return "Vaziani Tower" end,
    getRunways = function() return scenario.runways end,
    getCoalition = function() return scenario.airbaseSide end,
}

-- A second field, used by the divert tests. Placed east so the bearing to it is 090.
local otherAirbase = {
    getPoint = function() return { x = 0, y = 0, z = scenario.otherDistance or 40000 } end,
    getName = function() return "Kobuleti" end,
    getCallsign = function() return "Kobuleti Tower" end,
    getRunways = function() return scenario.runways end,
    getCoalition = function() return scenario.otherSide end,
}

world = { getAirbases = function() return scenario.airbases or { fakeAirbase } end }
timer = { getAbsTime = function() return scenario.missionTime or 0 end }

local fakeUnit = {
    getName = function() return "- Chevy 81 (Player)" end,
    getPoint = function() return { x = 0, y = 0, z = 0 } end,
    inAir = function() return scenario.airborne end,
    getAmmo = function() return scenario.ammo end,
    getGroup = function() return { getID = function() return 42 end } end,
    getCoalition = function() return scenario.unitSide end,
}

local params = { groupId = 42, unit = fakeUnit }

local function lastSpoken()
    return spoken[#spoken]
end

local function lastTransmission()
    return transmissions[#transmissions]
end

local function transmittedOn(frequency)
    local line = lastTransmission()
    if not line then
        return false
    end
    local freqs = line:match("^ATCAI_TTS|([^|]*)|")
    for value in tostring(freqs):gmatch("[^,]+") do
        if tonumber(value) == tonumber(frequency) then
            return true
        end
    end
    return false
end

local function reset(phase)
    spoken = {}
    transmissions = {}
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

-- ---------- emergencies and diverts ----------

print("bearings")
do
    local origin = { x = 0, y = 0, z = 0 }
    near(ATC.bearingBetween(origin, { x = 100, z = 0 }), 0, 0.01, "north is 000")
    near(ATC.bearingBetween(origin, { x = 0, z = 100 }), 90, 0.01, "east is 090")
    near(ATC.bearingBetween(origin, { x = -100, z = 0 }), 180, 0.01, "south is 180")
    near(ATC.bearingBetween(origin, { x = 0, z = -100 }), 270, 0.01, "west is 270")
    eq(ATC.bearingBetween(origin, origin), nil, "no bearing to where you already are")
    eq(ATC.bearingBetween(nil, origin), nil, "a missing point yields no bearing")

    eq(ATC.headingText(5), "005", "headings are spoken as three digits")
    eq(ATC.headingText(359.6), "000", "359.6 rounds to 360, which is spoken as 000")
    eq(ATC.headingText(nil), "unknown", "a missing heading says so")
end

print("which fields a coalition may use")
do
    local friendly = { getCoalition = function() return 2 end }
    local hostile = { getCoalition = function() return 1 end }
    local neutral = { getCoalition = function() return 0 end }
    local unknown = {}

    eq(ATC.usableByCoalition(friendly, 2), true, "your own side's field is usable")
    eq(ATC.usableByCoalition(neutral, 2), true, "a neutral field is usable")
    eq(ATC.usableByCoalition(hostile, 2), false, "the enemy's field is not")
    eq(ATC.usableByCoalition(unknown, 2), true,
        "a field that won't say is offered anyway - withholding a runway is the worse error")
    eq(ATC.usableByCoalition(friendly, nil), true, "an unknown own-side offers everything")
end

print("finding somewhere to divert")
do
    scenario.airbases = { fakeAirbase, otherAirbase }
    scenario.airbaseDistance = 10000      -- Vaziani, north, closer
    scenario.otherDistance = 40000        -- Kobuleti, east, further

    scenario.airbaseSide, scenario.otherSide = 2, 2
    local field, distance, bearing = ATC.findDivertField(fakeUnit)
    eq(field and field:getName(), "Vaziani", "the nearest friendly field wins")
    near(distance, 10000, 1, "and its distance is reported")
    near(bearing, 0, 0.01, "with the bearing to it")

    -- The point of the coalition filter: the closest runway may be the enemy's.
    scenario.airbaseSide = 1
    field, distance, bearing = ATC.findDivertField(fakeUnit)
    eq(field and field:getName(), "Kobuleti", "a closer hostile field is skipped")
    near(bearing, 90, 0.01, "bearing points at the field actually chosen")

    scenario.airbaseSide, scenario.otherSide = 2, 2
    scenario.airbases = nil
    scenario.airbaseDistance = 100
end

print("declaring an emergency")
do
    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)
    ATC.declareEmergency(params)

    local said = lastSpoken()
    contains(said, "roger your emergency", "the call is acknowledged as an emergency")
    contains(said, "cleared to land", "and comes with a clearance, unasked")
    contains(said, "emergency vehicles standing by", "with the fire trucks rolling")
    eq(ATC.getState(fakeUnit:getName()).emergency, true, "the aircraft is flagged")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.INBOUND, "and put on approach")
end

print("an emergency is heard from outside normal ATC range")
do
    -- The situation the call exists for: too far out for anyone to be talking to you.
    scenario.airborne = true
    scenario.airbaseDistance = 400000      -- far beyond AIRBASE_AIR_RADIUS
    reset(ATC.PHASE.AIRBORNE)
    ATC.declareEmergency(params)

    local said = lastSpoken()
    check(said and not said:find("no ATC in range", 1, true),
        "a distress call is not refused for being out of range", tostring(said))
    contains(said, "roger your emergency", "a distant field still takes the call")
    contains(said, "steer ", "and gives a heading to reach it")

    -- A routine request at that range is still refused, as before.
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestRadioCheck(params)
    contains(lastSpoken(), "no ATC in range", "ordinary calls keep the range limit")
    scenario.airbaseDistance = 100
end

print("declaring on the ground")
do
    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.declareEmergency(params)

    local said = lastSpoken()
    contains(said, "shut down", "on the ground you are told to stop, not to land")
    check(said and not said:find("cleared to land", 1, true),
        "no landing clearance for an aircraft already down", tostring(said))
end

print("vectors to the nearest friendly field")
do
    scenario.airborne = true
    scenario.airbases = { fakeAirbase, otherAirbase }
    scenario.airbaseSide = 1              -- nearest field is hostile
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestVectors(params)

    local said = lastSpoken()
    contains(said, "Kobuleti", "names the field you can actually use")
    contains(said, "steer 090", "gives a heading to it")
    contains(said, "miles", "and how far it is")
    check(said and not said:find("is Vaziani", 1, true),
        "the hostile field is never offered as the divert", tostring(said))

    scenario.airbaseSide = 2
    scenario.airbases = nil

    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.requestVectors(params)
    contains(lastSpoken(), "still on the ground", "vectors are refused on the ground")
end

print("an emergency outranks the traffic pattern")
do
    -- Stand in for atc_traffic.lua: someone is on short final ahead of us.
    ATC.runwayConflict = function()
        return { kind = "final", typeName = "Su-25T", distance = 5000 }
    end

    scenario.airborne = true
    reset(ATC.PHASE.INBOUND)
    ATC.requestLanding(params)
    contains(lastSpoken(), "number two", "normally you are sequenced behind them")

    reset(ATC.PHASE.INBOUND)
    ATC.getState(fakeUnit:getName()).emergency = true
    ATC.requestLanding(params)
    local said = lastSpoken()
    contains(said, "cleared to land", "an emergency is cleared regardless")
    contains(said, "you have priority", "and told so explicitly")
    check(said and not said:find("number two", 1, true),
        "an emergency is never sequenced behind anyone", tostring(said))

    -- Even an occupied runway does not send an emergency around.
    ATC.runwayConflict = function()
        return { kind = "runway", typeName = "Su-25T", distance = 200 }
    end
    reset(ATC.PHASE.INBOUND)
    ATC.requestLanding(params)
    contains(lastSpoken(), "go around", "normal traffic is sent around")

    reset(ATC.PHASE.INBOUND)
    ATC.getState(fakeUnit:getName()).emergency = true
    ATC.requestLanding(params)
    local emergencySaid = lastSpoken()
    check(emergencySaid and not emergencySaid:find("go around", 1, true),
        "an emergency is never sent around", tostring(emergencySaid))

    ATC.runwayConflict = nil
end

print("the emergency ends when you park")
do
    scenario.airborne = false
    reset(ATC.PHASE.LANDING)
    ATC.getState(fakeUnit:getName()).emergency = true
    ATC.requestParking(params)

    contains(lastSpoken(), "emergency services are meeting you", "the reply reflects it")
    eq(ATC.getState(fakeUnit:getName()).emergency, false, "the flag is cleared")

    -- A routine arrival still gets the routine reply.
    reset(ATC.PHASE.LANDING)
    ATC.requestParking(params)
    local said = lastSpoken()
    check(said and not said:find("emergency", 1, true),
        "an ordinary landing is not met by fire trucks", tostring(said))
end

print("straight-in approach")
do
    scenario.airborne = true
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestStraightIn(params)

    local said = lastSpoken()
    contains(said, "cleared straight-in", "the approach is approved")
    contains(said, "runway 13", "and names the runway in use")
    eq(ATC.getState(fakeUnit:getName()).phase, ATC.PHASE.INBOUND, "phase moves to inbound")
    eq(ATC.getState(fakeUnit:getName()).straightIn, true, "and the request is remembered")

    -- Traffic delays a straight-in rather than refusing it outright.
    ATC.runwayConflict = function()
        return { kind = "final", typeName = "Su-25T", distance = 5000 }
    end
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestStraightIn(params)
    contains(lastSpoken(), "expect delay", "traffic is mentioned, not used as a refusal")
    ATC.runwayConflict = nil

    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.requestStraightIn(params)
    contains(lastSpoken(), "still on the ground", "refused before takeoff")
end

-- ---------- what gets transmitted, not just what gets written on screen ----------

print("replies you must not miss go out on every plausible frequency")
do
    -- The bug this guards: with ATCAI_FREQUENCIES loaded, an in-range reply goes out on
    -- the field's own frequency (Vaziani 269.0) while anything falling back went out on
    -- the default list, which shares no frequency with it. The text appeared on screen
    -- and nothing came over the radio.
    ATCAI_FREQUENCIES = {
        ["vaziani tower"] = { { mhz = 269.0, modulation = "AM" } },
        ["vaziani"] = { { mhz = 269.0, modulation = "AM" } },
    }

    local wide, modes = ATC.wideFrequencies(fakeAirbase)
    check(wide:find("269", 1, true) ~= nil, "a wide call keeps the field's frequency", wide)
    check(wide:find("251", 1, true) ~= nil, "and adds the fallback list", wide)

    local freqCount, modeCount = 0, 0
    for _ in wide:gmatch("[^,]+") do freqCount = freqCount + 1 end
    for _ in modes:gmatch("[^,]+") do modeCount = modeCount + 1 end
    eq(freqCount, modeCount, "every frequency has a modulation beside it")

    -- SRS pairs the two lists by position, so a duplicate would shift them apart.
    local twice = ATC.wideFrequencies(fakeAirbase)
    local seen = {}
    for value in twice:gmatch("[^,]+") do
        check(not seen[value], "no frequency is listed twice: " .. value)
        seen[value] = true
    end
end

print("loadout is answered anywhere")
do
    scenario.airborne = true
    scenario.airbaseDistance = 400000        -- far outside ATC range
    scenario.ammo = { { count = 4, desc = { displayName = "AIM-120C" } } }
    reset(ATC.PHASE.AIRBORNE)
    ATC.requestLoadout(params)

    local said = lastSpoken()
    contains(said, "4 AIM-120C", "your own stores are reported however far out you are")
    check(said and not said:find("no ATC in range", 1, true),
        "counting your own pylons never needed a control tower", tostring(said))
    check(transmittedOn(269.0), "goes out on the field frequency you may be tuned to",
        tostring(lastTransmission()))
    check(transmittedOn(251.0), "and on the fallback list as well",
        tostring(lastTransmission()))

    scenario.airbaseDistance = 100
end

print("an emergency is transmitted where you can hear it")
do
    scenario.airborne = true
    scenario.airbaseDistance = 400000
    reset(ATC.PHASE.AIRBORNE)
    ATC.declareEmergency(params)

    contains(lastSpoken(), "roger your emergency", "the call is answered")
    check(transmittedOn(251.0),
        "a distant field answers on the fallback list too, not only its own frequency",
        tostring(lastTransmission()))
    check(transmittedOn(269.0), "while keeping its own frequency in the list",
        tostring(lastTransmission()))

    reset(ATC.PHASE.AIRBORNE)
    ATC.requestVectors(params)
    check(transmittedOn(251.0), "vectors are audible the same way",
        tostring(lastTransmission()))

    scenario.airbaseDistance = 100
end

print("refusals are audible")
do
    -- "No ATC in range" that you cannot hear reads as the module being broken.
    scenario.airborne = false
    scenario.airbaseDistance = 400000
    reset(ATC.PHASE.PARKED)
    ATC.requestRadioCheck(params)

    contains(lastSpoken(), "no ATC in range", "the refusal is still given")
    check(transmittedOn(251.0), "and it is actually transmitted",
        tostring(lastTransmission()))
    check(transmittedOn(269.0),
        "including the nearest field's frequency, the likeliest one you're tuned to",
        tostring(lastTransmission()))

    scenario.airbaseDistance = 100
    scenario.airborne = true
    reset(ATC.PHASE.PARKED)
    ATC.requestParking(params)
    contains(lastSpoken(), "unable", "a phase refusal is spoken")
    check(transmittedOn(251.0), "and transmitted wide as well",
        tostring(lastTransmission()))
end

print("routine clearances stay on the field frequency")
do
    -- Wide transmission is for the exceptions. If everything went out on every
    -- frequency, the real-frequency feature would mean nothing.
    scenario.airborne = false
    reset(ATC.PHASE.PARKED)
    ATC.requestStartup(params)

    check(transmittedOn(269.0), "startup is on the field's frequency",
        tostring(lastTransmission()))
    check(not transmittedOn(251.0),
        "and not on the fallback list - tuning in still has to matter",
        tostring(lastTransmission()))

    ATCAI_FREQUENCIES = nil
end

-- ---------- summary ----------

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
