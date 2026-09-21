--[[
Unit tests for lua/atc/atc_inbox.lua — the inbound bridge that lets an external process
drive ATC requests. Runs on DCS's bundled Lua with the sim API stubbed out.

Run:  tools/run_tests.sh
]]

local CORE_PATH = arg[1]
local INBOX_PATH = arg[2]

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

-- ---------- stubs ----------

local spoken = {}
local scheduled = nil
local now = 0

env = { info = function() end }
trigger = { action = { outTextForGroup = function(_, text) table.insert(spoken, text) end } }
atmosphere = {
    getWind = function() return { x = -5, y = 0, z = -5 } end,
    getTemperatureAndPressure = function() return 288, 101325 end,
}

local fakeAirbase = {
    getPoint = function() return { x = 10, y = 0, z = 0 } end,
    getName = function() return "Vaziani" end,
    getCallsign = function() return "Vaziani Tower" end,
    getRunways = function() return { { Name = "13" } } end,
}
world = { getAirbases = function() return { fakeAirbase } end }

timer = {
    getTime = function() return now end,
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

-- The inbox file is read via dofile; stub it so tests control what "arrives".
local inboxContent = nil
local dofileCalls = 0
local realDofile = dofile
dofile = function(path)
    if path == "INBOX" then
        dofileCalls = dofileCalls + 1
        if inboxContent == "BROKEN" then
            error("syntax error: partially written file")
        end
        ATCAI_INBOX = inboxContent
        return
    end
    return realDofile(path)
end

ATCAI_INBOX_PATH = "INBOX"

realDofile(CORE_PATH)
realDofile(INBOX_PATH)

ATC.players[42] = fakeUnit

local function lastSpoken()
    return spoken[#spoken]
end

local function send(intent, seq)
    inboxContent = { seq = seq, intent = intent }
    return ATC.pollInbox()
end

-- ---------- tests ----------

print("inbox polling registers itself")
do
    check(scheduled ~= nil, "a polling function was scheduled")
    eq(type(scheduled), "function", "the scheduled item is callable")
    local nextTime = scheduled()
    check(nextTime and nextTime > now, "polling reschedules itself into the future")
end

print("commands dispatch to the player")
do
    spoken = {}
    eq(send("radio_check", 1), true, "a radio check is delivered")
    check(lastSpoken() and lastSpoken():find("five by five", 1, true) ~= nil,
        "radio check produced the expected reply")

    spoken = {}
    eq(send("taxi", 2), true, "a taxi request is delivered")
    check(lastSpoken() and lastSpoken():find("hold short", 1, true) ~= nil,
        "taxi request produced a taxi instruction")
end

print("sequence numbers prevent repeats")
do
    spoken = {}
    eq(send("radio_check", 2), false, "a sequence number already seen is ignored")
    eq(#spoken, 0, "nothing is spoken for a stale command")

    eq(send("radio_check", 10), true, "a higher sequence number runs")
    eq(send("radio_check", 5), false, "going backwards is ignored")
end

print("bad input is survivable")
do
    spoken = {}
    inboxContent = "BROKEN"
    eq(ATC.pollInbox(), false, "a half-written file does not raise")

    inboxContent = nil
    eq(ATC.pollInbox(), false, "a missing table does not raise")

    eq(send("not_a_real_intent", 20), false, "unknown intents are ignored")
    eq(#spoken, 0, "unknown intents say nothing")
end

print("stale units are dropped")
do
    unitExists = false
    eq(send("radio_check", 30), false, "a command with no live player is not delivered")
    eq(ATC.players[42], nil, "the stale unit was removed from the registry")

    unitExists = true
    ATC.players[42] = fakeUnit
    eq(send("radio_check", 31), true, "delivery resumes once a player is registered again")
end

print("stale commands don't fire on mission start")
do
    spoken = {}
    -- Simulate the recogniser having left a command on disk from a previous session.
    inboxContent = { seq = 500, intent = "takeoff" }
    ATC.primeInbox()
    eq(ATC.inboxLastSeq, 500, "priming adopts the sequence already on disk")
    eq(ATC.pollInbox(), false, "the leftover command is not executed")
    eq(#spoken, 0, "nothing is spoken for a leftover command")

    eq(send("radio_check", 501), true, "the next genuinely new command still runs")
end

print("intent coverage")
do
    local intents = ATC.inboxIntents()
    eq(#intents, 12, "every ATC request is reachable by voice")
    local seen = {}
    for _, name in ipairs(intents) do seen[name] = true end
    for _, expected in ipairs({ "radio_check", "atis", "startup", "taxi", "takeoff",
                                "inbound", "landing", "parking", "loadout",
                                "emergency", "vectors", "straight_in" }) do
        check(seen[expected] == true, "intent '" .. expected .. "' is mapped")
    end
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
