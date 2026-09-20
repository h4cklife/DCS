--[[
Integration check for the inbound bridge: reads a REAL inbox file off disk with the real
dofile(), rather than a stub. This is what proves the external-process -> mission channel
actually works, since dofile surviving DCS's sandbox is the whole basis for it.

Args: <atc_core.lua> <atc_inbox.lua> <inbox file written by Python> <expected intent>
]]

local CORE_PATH, INBOX_LUA, INBOX_FILE, EXPECTED = arg[1], arg[2], arg[3], arg[4]

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

local spoken = {}
env = { info = function() end }
trigger = { action = { outTextForGroup = function(_, t) table.insert(spoken, t) end } }
atmosphere = {
    getWind = function() return { x = -5, y = 0, z = -5 } end,
    getTemperatureAndPressure = function() return 288, 101325 end,
}
world = { getAirbases = function() return { {
    getPoint = function() return { x = 10, y = 0, z = 0 } end,
    getName = function() return "Vaziani" end,
    getCallsign = function() return "Vaziani Tower" end,
    getRunways = function() return { { Name = "13" } } end,
} } end }
timer = { getTime = function() return 0 end, scheduleFunction = function() end }

local unit = {
    getName = function() return "Chevy 81" end,
    getPoint = function() return { x = 0, y = 0, z = 0 } end,
    inAir = function() return false end,
    isExist = function() return true end,
    getAmmo = function() return {} end,
    getGroup = function() return { getID = function() return 42 end } end,
}

ATCAI_INBOX_PATH = INBOX_FILE

dofile(CORE_PATH)
dofile(INBOX_LUA)
ATC.players[42] = unit

-- primeInbox ran at load and adopted the file's sequence, which is correct for a fresh
-- mission but means we must reset to observe a dispatch here.
check(ATC.inboxLastSeq > 0, "priming read the real file from disk",
    "lastSeq was " .. tostring(ATC.inboxLastSeq))
ATC.inboxLastSeq = 0

local delivered = ATC.pollInbox()
check(delivered == true, "a real on-disk command dispatched")
check(#spoken > 0, "ATC replied to it")
check(ATCAI_INBOX and ATCAI_INBOX.intent == EXPECTED,
    "intent read from disk was '" .. tostring(EXPECTED) .. "'",
    "got " .. tostring(ATCAI_INBOX and ATCAI_INBOX.intent))

if #spoken > 0 then
    print("  ATC said: " .. spoken[#spoken])
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
