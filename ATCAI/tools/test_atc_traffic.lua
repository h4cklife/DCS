--[[
Unit tests for lua/atc/atc_traffic.lua and the clearance gating it drives.
Runs on DCS's bundled Lua with the sim API stubbed out.

Run:  tools/run_tests.sh
]]

local CORE_PATH, TRAFFIC_PATH = arg[1], arg[2]

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

local spoken = {}
local traffic = {}

env = { info = function() end }
trigger = { action = { outTextForGroup = function(_, t) table.insert(spoken, t) end } }
atmosphere = {
    -- Wind from ~045, so runway 13 is never the favoured end by accident; tests that
    -- care about the runway set it explicitly.
    getWind = function() return { x = -5, y = 0, z = -5 } end,
    getTemperatureAndPressure = function() return 288, 101325 end,
}

local FIELD = { x = 0, y = 100, z = 0 }

local fakeAirbase = {
    getPoint = function() return FIELD end,
    getName = function() return "Vaziani" end,
    getCallsign = function() return "Vaziani Tower" end,
    getRunways = function() return { { Name = "13" } } end,
}
world = { getAirbases = function() return { fakeAirbase } end }
timer = { getTime = function() return 0 end, scheduleFunction = function() end }

Group = { Category = { AIRPLANE = 0, HELICOPTER = 1 } }

-- Builds a stub aircraft. Distances are metres from the field along +x.
local function aircraft(opts)
    return {
        getName = function() return opts.name end,
        getTypeName = function() return opts.type or "Su-27" end,
        getPoint = function()
            return { x = opts.distance or 0, y = (FIELD.y + (opts.height or 0)), z = 0 }
        end,
        getVelocity = function() return opts.velocity or { x = 0, y = 0, z = 0 } end,
        inAir = function() return opts.airborne == true end,
        isExist = function() return true end,
        getGroup = function() return { getID = function() return 99 end } end,
        getAmmo = function() return {} end,
    }
end

coalition = {
    side = { RED = 1, BLUE = 2, NEUTRAL = 0 },
    getGroups = function(side)
        -- Report all traffic once, under a single side, to keep the stub simple.
        if side ~= 2 then return {} end
        return { {
            isExist = function() return true end,
            getUnits = function() return traffic end,
        } }
    end,
    getPlayers = function() return {} end,
}

local player = aircraft({ name = "Chevy 81", distance = 50 })
local params = { groupId = 42, unit = player }

local function lastSpoken() return spoken[#spoken] end

dofile(CORE_PATH)
dofile(TRAFFIC_PATH)

-- Runway 13 points 130 degrees; heading east (+z) is 090.
local RUNWAY_13 = { name = "13", heading = 130 }
local conditions13 = { runway = RUNWAY_13 }

-- ---------- geometry helpers ----------

print("heading maths")
do
    eq(ATC.headingDifference(130, 130), 0, "identical headings differ by nothing")
    eq(ATC.headingDifference(350, 10), 20, "differences wrap around north")
    eq(ATC.headingDifference(130, 310), 180, "reciprocals are 180 apart")
    eq(ATC.groundSpeed({ x = 3, y = 99, z = 4 }), 5, "ground speed ignores vertical motion")
    eq(ATC.travelHeading({ x = 0, y = 0, z = 0 }), nil, "a stationary aircraft has no heading")
    eq(ATC.travelHeading({ x = 10, y = 0, z = 0 }), 0, "moving north is heading 000")
    eq(ATC.travelHeading({ x = 0, y = 0, z = 10 }), 90, "moving east is heading 090")
end

print("classifying traffic")
do
    local rolling = aircraft({ name = "roll", distance = 300, velocity = { x = 60, y = 0, z = 0 } })
    local kind = ATC.classifyTraffic(rolling, FIELD, 130)
    eq(kind, "runway", "a fast-moving aircraft on the ground is using the runway")

    local taxiing = aircraft({ name = "taxi", distance = 300, velocity = { x = 4, y = 0, z = 0 } })
    eq(ATC.classifyTraffic(taxiing, FIELD, 130), nil, "taxi speed is not a runway conflict")

    local parked = aircraft({ name = "parked", distance = 300 })
    eq(ATC.classifyTraffic(parked, FIELD, 130), nil, "a parked aircraft is not a conflict")

    local distant = aircraft({ name = "far", distance = 40000, velocity = { x = 80, y = 0, z = 0 } })
    eq(ATC.classifyTraffic(distant, FIELD, 130), nil, "a rolling aircraft at another field is ignored")

    -- On final: airborne, close, low, tracking 130 (velocity mostly +x and +z).
    local onFinal = aircraft({
        name = "final", distance = 3000, height = 200, airborne = true,
        velocity = { x = -64, y = 0, z = 77 },   -- heading ~130
    })
    eq(ATC.classifyTraffic(onFinal, FIELD, 130), "final", "a low, close, aligned aircraft is on final")

    local highOverhead = aircraft({
        name = "high", distance = 3000, height = 6000, airborne = true,
        velocity = { x = -64, y = 0, z = 77 },
    })
    eq(ATC.classifyTraffic(highOverhead, FIELD, 130), nil, "traffic passing high overhead is ignored")

    local crossing = aircraft({
        name = "crossing", distance = 3000, height = 200, airborne = true,
        velocity = { x = 100, y = 0, z = 0 },    -- heading 000, across the approach
    })
    eq(ATC.classifyTraffic(crossing, FIELD, 130), nil, "traffic not tracking the runway is ignored")
end

print("picking the most pressing conflict")
do
    traffic = {}
    eq(ATC.runwayConflict(fakeAirbase, conditions13, player), nil, "an empty circuit is clear")

    traffic = { aircraft({ name = "roll", distance = 300, velocity = { x = 60, y = 0, z = 0 } }) }
    local conflict = ATC.runwayConflict(fakeAirbase, conditions13, player)
    eq(conflict and conflict.kind, "runway", "runway traffic is reported")

    -- Runway traffic outranks traffic on final even when the latter is closer.
    traffic = {
        aircraft({ name = "roll", distance = 2000, velocity = { x = 60, y = 0, z = 0 } }),
        aircraft({ name = "final", distance = 1000, height = 100, airborne = true,
                   velocity = { x = -64, y = 0, z = 77 } }),
    }
    conflict = ATC.runwayConflict(fakeAirbase, conditions13, player)
    eq(conflict and conflict.kind, "runway", "an occupied runway outranks landing traffic")

    -- The player is excluded from its own traffic scan.
    traffic = { aircraft({ name = "Chevy 81", distance = 100, velocity = { x = 60, y = 0, z = 0 } }) }
    eq(ATC.runwayConflict(fakeAirbase, conditions13, player), nil,
        "your own aircraft is not treated as conflicting traffic")
end

print("takeoff clearance is gated on traffic")
do
    traffic = {}
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.HOLDING_SHORT
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "cleared for takeoff", "a clear runway gets a takeoff clearance")

    traffic = { aircraft({ name = "roll", distance = 300, velocity = { x = 60, y = 0, z = 0 } }) }
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.HOLDING_SHORT
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "hold position", "an occupied runway holds you at the point")
    eq(ATC.getState("Chevy 81").phase, ATC.PHASE.HOLDING_SHORT,
        "being held leaves you holding short, free to ask again")

    traffic = { aircraft({ name = "final", distance = 2000, height = 150, airborne = true,
                           velocity = { x = -64, y = 0, z = 77 } }) }
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.HOLDING_SHORT
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "hold short", "landing traffic holds you short")
    contains(lastSpoken(), "landing traffic", "the hold explains what you're waiting for")
end

print("landing clearance is gated on traffic")
do
    -- Player is airborne on approach, 5000 m out.
    local inbound = aircraft({ name = "Chevy 81", distance = 5000, height = 300, airborne = true,
                               velocity = { x = -64, y = 0, z = 77 } })
    local inboundParams = { groupId = 42, unit = inbound }

    traffic = {}
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.INBOUND
    ATC.requestLanding(inboundParams)
    contains(lastSpoken(), "cleared to land", "a clear runway gets a landing clearance")

    traffic = { aircraft({ name = "roll", distance = 300, velocity = { x = 60, y = 0, z = 0 } }) }
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.INBOUND
    ATC.requestLanding(inboundParams)
    contains(lastSpoken(), "go around", "an occupied runway sends you around")
    eq(ATC.getState("Chevy 81").phase, ATC.PHASE.INBOUND, "a go-around leaves you inbound")

    -- Traffic ahead of us on final: closer to the field than the player.
    traffic = { aircraft({ name = "ahead", type = "F-16C", distance = 2000, height = 150,
                           airborne = true, velocity = { x = -64, y = 0, z = 77 } }) }
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.INBOUND
    ATC.requestLanding(inboundParams)
    contains(lastSpoken(), "number two", "traffic ahead makes you number two")
    contains(lastSpoken(), "F-16C", "the sequencing call names the traffic type")

    -- Traffic behind us is not our problem.
    traffic = { aircraft({ name = "behind", distance = 8000, height = 300, airborne = true,
                           velocity = { x = -64, y = 0, z = 77 } }) }
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.INBOUND
    ATC.requestLanding(inboundParams)
    contains(lastSpoken(), "cleared to land", "traffic further out does not delay you")
end

print("missing traffic module degrades gracefully")
do
    local saved = ATC.runwayConflict
    ATC.runwayConflict = nil
    traffic = {}
    spoken = {}
    ATC.state = {}
    ATC.getState("Chevy 81").phase = ATC.PHASE.HOLDING_SHORT
    ATC.requestTakeoff(params)
    contains(lastSpoken(), "cleared for takeoff",
        "clearances still work without traffic awareness loaded")
    ATC.runwayConflict = saved
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
