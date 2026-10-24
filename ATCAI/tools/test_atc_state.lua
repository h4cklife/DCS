--[[
Tests for lua/atc/atc_state.lua — the facts the voice bridge needs to pick a comms-menu
key sequence. Run on DCS's own Lua with the mission API stubbed.

Args: <atc_core.lua> <atc_state.lua>
]]

local CORE_PATH, STATE_PATH = arg[1], arg[2]

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

local published = {}

env = { info = function(msg)
    if tostring(msg):find("ATCAI_STATE|", 1, true) then
        table.insert(published, msg)
    end
end }

trigger = { action = { outTextForGroup = function() end } }
atmosphere = {
    getWind = function() return { x = 0, y = 0, z = 0 } end,
    getTemperatureAndPressure = function() return 288, 101325 end,
}
world = { getAirbases = function() return {} end }
timer = {
    getTime = function() return 0 end,
    getAbsTime = function() return 0 end,
    scheduleFunction = function() end,
}
coalition = { side = { NEUTRAL = 0, RED = 1, BLUE = 2 } }
Group = { Category = { AIRPLANE = 0, HELICOPTER = 1 } }

-- Scenario knobs.
local scenario = {
    typeName = "F-15C",
    airborne = true,
    groupUnits = nil,     -- set per test
    support = {},         -- friendly units the coalition scan returns
}

local function makeUnit(spec)
    return {
        getName = function() return spec.name end,
        getTypeName = function() return spec.typeName end,
        getPlayerName = function() return spec.player end,
        isExist = function() return spec.exists ~= false end,
        getPoint = function() return spec.point or { x = 0, y = 0, z = 0 } end,
        getCoalition = function() return 2 end,
        inAir = function() return spec.airborne ~= false end,
        hasAttribute = function(_, attribute)
            if spec.attributes == nil then return nil end
            return spec.attributes[attribute] == true
        end,
        getNumber = function() return spec.number end,
        getGroup = function()
            return {
                getID = function() return 42 end,
                isExist = function() return true end,
                getUnits = function() return scenario.groupUnits or {} end,
            }
        end,
    }
end

coalition.getGroups = function(_, category)
    if category ~= Group.Category.AIRPLANE then
        return {}
    end
    return { {
        isExist = function() return true end,
        getUnits = function() return scenario.support end,
    } }
end

local player = makeUnit({ name = "Chevy 81", typeName = "F-15C", player = "artic" })
player.getTypeName = function() return scenario.typeName end
player.inAir = function() return scenario.airborne end

dofile(CORE_PATH)
dofile(STATE_PATH)

ATC.players = { [42] = player }
scenario.groupUnits = { player }

-- ---------- tests ----------

print("counting wingmen")
do
    scenario.groupUnits = { player }
    eq(ATC.countWingmen(player), 0, "a single-ship flight has no wingmen")

    scenario.groupUnits = { player, makeUnit({ name = "Chevy 82", typeName = "F-15C" }) }
    eq(ATC.countWingmen(player), 1, "one AI in the group is one wingman")

    scenario.groupUnits = {
        player,
        makeUnit({ name = "Chevy 82" }),
        makeUnit({ name = "Chevy 83" }),
        makeUnit({ name = "Chevy 84" }),
    }
    eq(ATC.countWingmen(player), 3, "a four-ship has three wingmen")

    -- A dead wingman cannot be commanded, so it must not be counted.
    scenario.groupUnits = {
        player,
        makeUnit({ name = "Chevy 82", exists = false }),
        makeUnit({ name = "Chevy 83" }),
    }
    eq(ATC.countWingmen(player), 1, "a destroyed wingman is not counted")

    -- Another human is not a wingman you can order about either.
    scenario.groupUnits = { player, makeUnit({ name = "Chevy 82", player = "someone" }) }
    eq(ATC.countWingmen(player), 0, "a human in the flight is not an AI wingman")

    scenario.groupUnits = { player }
end

print("which flight slots are alive")
do
    -- The case count alone gets wrong: two is dead, three and four are not. A
    -- count-based check would allow "two, rejoin" and send it to a dead aircraft.
    scenario.groupUnits = {
        player,
        makeUnit({ name = "Chevy 82", number = 2, exists = false }),
        makeUnit({ name = "Chevy 83", number = 3 }),
        makeUnit({ name = "Chevy 84", number = 4 }),
    }
    local slots, count = ATC.flightSlots(player)
    eq(count, 2, "two wingmen are alive")
    eq(slots[2], nil, "slot two is empty")
    eq(slots[3], true, "slot three is filled")
    eq(slots[4], true, "slot four is filled")

    local line = ATC.formatState(ATC.flightState(player))
    contains(line, "slot2=0", "a dead wingman publishes slot2=0")
    contains(line, "slot3=1", "a live one publishes 1")
    contains(line, "slot4=1", "and so does four")

    -- A module that will not report a number must not claim a slot it cannot prove.
    scenario.groupUnits = { player, makeUnit({ name = "Chevy 82" }) }
    slots, count = ATC.flightSlots(player)
    eq(count, 1, "the wingman still counts")
    eq(slots[2], nil, "but no slot is claimed without a number")

    scenario.groupUnits = { player }
end

print("spotting support aircraft")
do
    scenario.support = {}
    eq(ATC.nearestFriendlyRole(player, "AWACS", ATC.AWACS_TYPES), nil,
        "no AWACS in the mission means no range")

    -- By attribute, which is how DCS normally reports it.
    scenario.support = { makeUnit({
        name = "Overlord", typeName = "E-3A", attributes = { AWACS = true },
        point = { x = 92600, y = 0, z = 0 },
    }) }
    eq(ATC.nearestFriendlyRole(player, "AWACS", ATC.AWACS_TYPES), 50,
        "an AWACS 50 miles out is reported as 50")

    -- By type name, for when hasAttribute is unavailable.
    scenario.support = { makeUnit({
        name = "Overlord", typeName = "E-3A", attributes = nil,
        point = { x = 1852, y = 0, z = 0 },
    }) }
    eq(ATC.nearestFriendlyRole(player, "AWACS", ATC.AWACS_TYPES), 1,
        "the type list covers a module that reports no attribute")

    -- Something that is neither.
    scenario.support = { makeUnit({
        name = "Chevy 99", typeName = "F-15C", attributes = { AWACS = false },
    }) }
    eq(ATC.nearestFriendlyRole(player, "AWACS", ATC.AWACS_TYPES), nil,
        "a fighter is not an AWACS")

    scenario.support = { makeUnit({
        name = "Texaco", typeName = "KC-135", attributes = { Tankers = true },
        point = { x = 18520, y = 0, z = 0 },
    }) }
    eq(ATC.nearestFriendlyRole(player, "Tankers", ATC.TANKER_TYPES), 10,
        "a tanker is found the same way")
    eq(ATC.nearestFriendlyRole(player, "AWACS", ATC.AWACS_TYPES), nil,
        "and is not mistaken for an AWACS")

    scenario.support = {}
end

print("the state it publishes")
do
    scenario.typeName = "F-15C"
    scenario.airborne = false
    scenario.groupUnits = { player, makeUnit({ name = "Chevy 82", number = 2 }) }
    scenario.support = { makeUnit({
        name = "Overlord", typeName = "E-3A", attributes = { AWACS = true },
        point = { x = 92600, y = 0, z = 0 },
    }) }

    local state = ATC.flightState(player)
    eq(state.aircraft, "F-15C", "the aircraft type is what the bridge keys off")
    eq(state.wingmen, 1, "wingmen are counted")
    eq(state.onGround, 1, "on the ground is reported as 1")
    eq(state.awacs, 1, "an available AWACS is flagged")
    eq(state.awacsnm, 50, "with its range, for a map that wants to use it")
    eq(state.tanker, 0, "no tanker in this scenario")

    scenario.airborne = true
    eq(ATC.flightState(player).onGround, 0, "airborne is reported as 0")
end

print("the published line")
do
    published = {}
    eq(ATC.publishState(), true, "a player in an aircraft produces a line")

    local line = published[#published]
    contains(line, "ATCAI_STATE|", "it carries the state prefix")
    contains(line, "aircraft=F-15C", "aircraft is key=value")
    contains(line, "wingmen=1", "so is the wingman count")
    contains(line, "onGround=0", "and the ground flag")
    contains(line, "awacs=1", "and the AWACS flag")
    contains(line, "slot2=1", "and which flight slots are filled")
    contains(line, "slot3=0", "including the empty ones, so absence is explicit")

    -- Nothing in this file may write on screen; it is diagnostic plumbing.
    local onScreen = 0
    trigger.action.outTextForGroup = function() onScreen = onScreen + 1 end
    ATC.publishState()
    eq(onScreen, 0, "nothing is written on screen")
end

print("it stays quiet with nobody flying")
do
    published = {}
    ATC.players = {}
    eq(ATC.publishState(), false, "no players means no line")
    eq(#published, 0, "and nothing reaches the log")
    ATC.players = { [42] = player }
end

print("stale players are dropped")
do
    local gone = makeUnit({ name = "Ghost", exists = false })
    ATC.players = { [99] = gone }
    published = {}
    eq(ATC.publishState(), false, "a unit that no longer exists publishes nothing")
    eq(ATC.players[99], nil, "and is removed from the registry")
    ATC.players = { [42] = player }
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
