--[[
ATCAI - atc_inbox.lua
Inbound bridge: lets an external process (the voice recogniser) drive ATC requests.

The mission-scripting sandbox has no io/socket access, but dofile() survives
sanitisation. So the external process writes a tiny Lua file:

    ATCAI_INBOX = { seq = 7, intent = "taxi" }

and this polls it, running any command whose sequence number it hasn't seen yet.
The sequence number is what stops a command being re-run on every poll.

Load order: after atc_core.lua (for the request functions) and atc_menu.lua (which
registers which unit each player is flying). ATCAI_INBOX_PATH must be set before load —
tools/build_test_mission.py emits it alongside the dofile chain.
]]

-- Loading is idempotent: the hook lists this file explicitly and atc_menu.lua also
-- auto-loads it as a fallback, so it can legitimately be asked for twice.
if ATC and ATC.pollInbox then return end

ATC = ATC or {}
ATC.players = ATC.players or {}
ATC.inboxLastSeq = ATC.inboxLastSeq or 0
ATC.INBOX_POLL_SECONDS = ATC.INBOX_POLL_SECONDS or 0.3

-- Looked up by name at call time so load order within a phase can't strand us with a
-- nil handler captured at definition time.
local INTENT_HANDLERS = {
    radio_check = "requestRadioCheck",
    startup = "requestStartup",
    taxi = "requestTaxi",
    takeoff = "requestTakeoff",
    inbound = "requestInbound",
    landing = "requestLanding",
    parking = "requestParking",
    loadout = "requestLoadout",
}

function ATC.inboxIntents()
    local names = {}
    for intent in pairs(INTENT_HANDLERS) do
        table.insert(names, intent)
    end
    table.sort(names)
    return names
end

-- Runs one inbox command against every player currently in an aircraft.
-- Returns true if it reached at least one.
function ATC.handleInboxCommand(command)
    if type(command) ~= "table" then
        return false
    end
    local handlerName = INTENT_HANDLERS[tostring(command.intent)]
    if not handlerName then
        env.info("ATCAI: ignoring unknown inbox intent " .. tostring(command.intent))
        return false
    end
    local handler = ATC[handlerName]
    if type(handler) ~= "function" then
        return false
    end

    local delivered = false
    for groupId, unit in pairs(ATC.players) do
        -- Units go stale across respawns; skip any that no longer exist.
        if unit and unit.isExist and unit:isExist() then
            handler({ groupId = groupId, unit = unit })
            delivered = true
        else
            ATC.players[groupId] = nil
        end
    end

    if not delivered then
        env.info("ATCAI: inbox command '" .. tostring(command.intent) .. "' had no player to deliver to")
    end
    return delivered
end

-- Reads the inbox file and runs anything new. Safe to call when the file is missing,
-- half-written, or unchanged.
function ATC.pollInbox()
    local path = ATCAI_INBOX_PATH
    if not path then
        return false
    end

    -- A partially written file is a parse error, not a crash: just try again next tick.
    if not pcall(dofile, path) then
        return false
    end
    if type(ATCAI_INBOX) ~= "table" then
        return false
    end

    local seq = tonumber(ATCAI_INBOX.seq) or 0
    if seq <= ATC.inboxLastSeq then
        return false
    end
    ATC.inboxLastSeq = seq

    return ATC.handleInboxCommand(ATCAI_INBOX)
end

-- Adopts whatever sequence number is already on disk without acting on it, so a command
-- left over from a previous session doesn't fire the instant a new mission starts.
function ATC.primeInbox()
    local path = ATCAI_INBOX_PATH
    if path and pcall(dofile, path) and type(ATCAI_INBOX) == "table" then
        ATC.inboxLastSeq = tonumber(ATCAI_INBOX.seq) or ATC.inboxLastSeq
    end
    return ATC.inboxLastSeq
end

local function tick()
    pcall(ATC.pollInbox)
    return timer.getTime() + ATC.INBOX_POLL_SECONDS
end

ATC.primeInbox()

-- Guard against loading twice (mission trigger plus atc_menu.lua's fallback), which
-- would otherwise leave two poll loops running against the same inbox.
if not ATC.inboxScheduled then
    ATC.inboxScheduled = true
    timer.scheduleFunction(tick, nil, timer.getTime() + ATC.INBOX_POLL_SECONDS)
end

env.info("ATCAI: atc_inbox.lua loaded, polling " .. tostring(ATCAI_INBOX_PATH))
