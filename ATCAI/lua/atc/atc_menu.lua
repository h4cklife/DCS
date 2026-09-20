--[[
ATCAI - atc_menu.lua
Builds an "ATCAI" comms-menu submenu for each player-controlled aircraft, wired to the
functions in atc_core.lua. This is the Phase 1 stand-in for voice input — the same
ATC.request* functions will be called by the voice bridge later.

Load order matters: atc_core.lua must be loaded before this file.
]]

env.info("ATCAI: atc_menu.lua executing")

ATC = ATC or {}
ATC.menuBuiltForGroup = ATC.menuBuiltForGroup or {}
-- Which unit each player is flying, so the inbound bridge (atc_inbox.lua) knows who to
-- deliver voice commands to.
ATC.players = ATC.players or {}

local function buildMenuForUnit(unit)
    local ok, err = pcall(function()
        local groupId = unit:getGroup():getID()
        -- Re-register even if the menu already exists: on respawn the unit object is
        -- new, and the stale one would no longer be valid for voice commands.
        ATC.players[groupId] = unit
        if ATC.menuBuiltForGroup[groupId] then
            return
        end
        ATC.menuBuiltForGroup[groupId] = true

        local params = { groupId = groupId, unit = unit }
        -- Named "ATCAI" (not "ATC") to stay distinct from DCS's own built-in ATC
        -- submenu, which already occupies the "ATC" label in the comms menu.
        local root = missionCommands.addSubMenuForGroup(groupId, "ATCAI")

        -- Ordered as a sortie runs: check in, depart, arrive, then utility.
        missionCommands.addCommandForGroup(groupId, "Request radio check", root, ATC.requestRadioCheck, params)
        missionCommands.addCommandForGroup(groupId, "Request startup", root, ATC.requestStartup, params)
        missionCommands.addCommandForGroup(groupId, "Request taxi", root, ATC.requestTaxi, params)
        missionCommands.addCommandForGroup(groupId, "Request takeoff", root, ATC.requestTakeoff, params)
        missionCommands.addCommandForGroup(groupId, "Report inbound", root, ATC.requestInbound, params)
        missionCommands.addCommandForGroup(groupId, "Request landing", root, ATC.requestLanding, params)
        missionCommands.addCommandForGroup(groupId, "Request taxi to parking", root, ATC.requestParking, params)
        missionCommands.addCommandForGroup(groupId, "Request loadout status", root, ATC.requestLoadout, params)

        env.info("ATCAI: menu built for group " .. tostring(groupId) ..
            " (" .. tostring(unit:getName()) .. ")")
        trigger.action.outTextForGroup(groupId, "ATCAI ready - see ATCAI in the comms menu", 15, false)
    end)
    if not ok then
        env.info("ATCAI: buildMenuForUnit error: " .. tostring(err))
    end
end

local atcMenuEventHandler = {}
function atcMenuEventHandler:onEvent(event)
    if event.id == world.event.S_EVENT_BIRTH and event.initiator then
        local unit = event.initiator
        -- getPlayerName() is non-nil only for player-controlled units
        if unit.getPlayerName and unit:getPlayerName() then
            buildMenuForUnit(unit)
        end
    end
end

world.addEventHandler(atcMenuEventHandler)

-- Catch players already in an aircraft when this runs — the mission-start trigger can
-- fire after the player's S_EVENT_BIRTH has already gone out, which would otherwise be
-- missed entirely.
for _, side in pairs({ coalition.side.BLUE, coalition.side.RED }) do
    for _, unit in ipairs(coalition.getPlayers(side)) do
        buildMenuForUnit(unit)
    end
end

-- Load the inbound voice bridge if the mission's trigger didn't list it. Missions built
-- before atc_inbox.lua existed would otherwise accept voice commands into the inbox file
-- with nothing ever reading them.
if not ATC.pollInbox and ATCAI_SCRIPT_DIR then
    local ok, err = pcall(dofile, ATCAI_SCRIPT_DIR .. "atc_inbox.lua")
    if not ok then
        env.info("ATCAI: could not auto-load atc_inbox.lua: " .. tostring(err))
    end
end

env.info("ATCAI: atc_menu.lua finished")
