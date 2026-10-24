--[[
TEST HARNESS — not part of ATCAI, and never installed by the manager.

Adds a comms submenu that destroys a chosen wingman on demand, so the way DCS renumbers
its per-wingman comms entries can be exercised deliberately instead of waiting for the
right thing to happen in a fight.

This file WRITES to the mission world: it destroys units. That is exactly what ATCAI
itself never does, which is why it lives in tools/ rather than lua/atc/, is not in
installer.SCRIPT_FILES, and is loaded only by a test mission built for the purpose.
Nothing installs it alongside the module.

Usage: pass this file's absolute path to tools/build_test_mission.py along with the
ATCAI scripts. In the cockpit: comms key -> Other -> ATCAI TEST.
]]

local function wingmanByNumber(playerUnit, wanted)
    local group = playerUnit:getGroup()
    if not group then
        return nil
    end
    for _, member in ipairs(group:getUnits() or {}) do
        if member and member:isExist() then
            local isHuman = member.getPlayerName and member:getPlayerName()
            if not isHuman and type(member.getNumber) == "function" then
                local ok, number = pcall(member.getNumber, member)
                if ok and number == wanted then
                    return member
                end
            end
        end
    end
    return nil
end

local function killWingman(params)
    local groupId, number = params.groupId, params.number
    local playerUnit = params.unit
    if not playerUnit or not playerUnit:isExist() then
        return
    end

    local target = wingmanByNumber(playerUnit, number)
    if not target then
        trigger.action.outTextForGroup(groupId,
            string.format("TEST: wingman %d is already gone", number), 10, false)
        return
    end

    local name = target:getName()
    local ok, err = pcall(function() target:destroy() end)
    if ok then
        trigger.action.outTextForGroup(groupId,
            string.format("TEST: destroyed wingman %d (%s) - check how the comms menu "
                .. "renumbers", number, tostring(name)), 15, false)
        env.info(string.format("ATCAI_TEST| destroyed wingman %d (%s)", number,
            tostring(name)))
    else
        trigger.action.outTextForGroup(groupId,
            "TEST: could not destroy it: " .. tostring(err), 15, false)
    end
end

local function reportFlight(params)
    local playerUnit = params.unit
    if not playerUnit or not playerUnit:isExist() then
        return
    end
    local alive = {}
    for number = 2, 4 do
        if wingmanByNumber(playerUnit, number) then
            table.insert(alive, tostring(number))
        end
    end
    local text = #alive > 0 and table.concat(alive, ", ") or "none"
    trigger.action.outTextForGroup(params.groupId,
        "TEST: wingmen still flying: " .. text
        .. "\nThe first of those is now F2 in the comms menu.", 15, false)
end

local built = {}

local function buildMenu(unit)
    local groupId = unit:getGroup():getID()
    if built[groupId] then
        return
    end
    built[groupId] = true

    local root = missionCommands.addSubMenuForGroup(groupId, "ATCAI TEST")
    missionCommands.addCommandForGroup(groupId, "Which wingmen are left?", root,
        reportFlight, { groupId = groupId, unit = unit })
    for number = 2, 4 do
        missionCommands.addCommandForGroup(groupId,
            string.format("Kill wingman %d", number), root,
            killWingman, { groupId = groupId, unit = unit, number = number })
    end
    trigger.action.outTextForGroup(groupId,
        "ATCAI TEST menu ready - Other -> ATCAI TEST", 15, false)
end

local handler = {}
function handler:onEvent(event)
    if event.id == world.event.S_EVENT_BIRTH and event.initiator then
        local unit = event.initiator
        if unit.getPlayerName and unit:getPlayerName() then
            pcall(buildMenu, unit)
        end
    end
end
world.addEventHandler(handler)

-- The player may already be in the aircraft when this loads.
for _, side in pairs({ coalition.side.RED, coalition.side.BLUE }) do
    for _, playerUnit in ipairs(coalition.getPlayers(side) or {}) do
        pcall(buildMenu, playerUnit)
    end
end

env.info("ATCAI TEST: kill-wingman menu loaded")
