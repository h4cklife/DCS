--[[
ATCAI - atc_state.lua
Publishes the handful of facts that decide what DCS's own comms menu looks like, so the
voice bridge outside the sim can choose a key sequence for the actual situation instead
of guessing.

Why this exists: mission scripting cannot read the comms menu. missionCommands only adds
and removes ATCAI's own entries, and the engine's tree is exposed neither to scripting
nor to the Export API - there is no enumerate. But everything that *changes* the tree is
readable, so the shape can be derived rather than observed:

  * aircraft type      - different modules, different trees
  * AI wingmen         - no wingmen, no Flight entries
  * on the ground      - ground crew entries come and go
  * AWACS / tanker     - their entries appear only when one is available

Read-only, like the rest of ATCAI: this file issues no orders and changes nothing. It
writes one line to dcs.log, which is the same outbound channel spoken replies use.

Format, deliberately key=value so fields can be added without breaking the parser:

  ATCAI_STATE|aircraft=F-15C|wingmen=1|onGround=0|awacs=1|awacsnm=42|tanker=1
]]

if ATC and ATC.publishState then return end

ATC = ATC or {}

ATC.STATE_INTERVAL = ATC.STATE_INTERVAL or 5     -- seconds between publications

-- Fallbacks for when hasAttribute is unavailable or a module reports nothing useful.
ATC.AWACS_TYPES = ATC.AWACS_TYPES or {
    ["E-3A"] = true, ["E-2C"] = true, ["A-50"] = true, ["KJ-2000"] = true,
}
ATC.TANKER_TYPES = ATC.TANKER_TYPES or {
    ["KC-135"] = true, ["KC135MPRS"] = true, ["KC130"] = true, ["KC130J"] = true,
    ["IL-78M"] = true, ["S-3B Tanker"] = true,
}

local function attributeOf(unit, attribute)
    if type(unit.hasAttribute) ~= "function" then
        return nil
    end
    local ok, value = pcall(unit.hasAttribute, unit, attribute)
    if not ok then
        return nil
    end
    return value
end

-- A unit counts as a role either because DCS says so, or because its type is on the
-- list above. hasAttribute is preferred; the list covers the cases where it isn't there.
function ATC.unitHasRole(unit, attribute, typeTable)
    if not unit or not unit.isExist or not unit:isExist() then
        return false
    end
    local byAttribute = attributeOf(unit, attribute)
    if byAttribute ~= nil then
        if byAttribute then
            return true
        end
    end
    local typeName = unit.getTypeName and unit:getTypeName() or nil
    return typeName ~= nil and typeTable[typeName] == true
end

-- The AI aircraft left in the player's own flight. Wingmen share the player's group in
-- DCS, so this is a group walk with the humans excluded.
--
-- Both a count and the slot numbers are needed, and they answer different questions.
-- "Two, rejoin" addresses the aircraft in slot 2 specifically: if two is dead while
-- three and four are alive, the count is 2 and a count-based check would happily send
-- the sequence to an aircraft that no longer exists. getNumber() gives the slot, so the
-- command can be refused precisely.
function ATC.flightSlots(unit)
    local slots, count = {}, 0

    if not unit or type(unit.getGroup) ~= "function" then
        return slots, count
    end
    local group = unit:getGroup()
    if not group or not group.getUnits then
        return slots, count
    end

    for _, member in ipairs(group:getUnits() or {}) do
        if member and member.isExist and member:isExist() then
            local isHuman = member.getPlayerName and member:getPlayerName()
            if not isHuman then
                count = count + 1
                if type(member.getNumber) == "function" then
                    local ok, number = pcall(member.getNumber, member)
                    if ok and type(number) == "number" then
                        slots[number] = true
                    end
                end
            end
        end
    end
    return slots, count
end

function ATC.countWingmen(unit)
    local _, count = ATC.flightSlots(unit)
    return count
end

-- Nearest friendly unit filling a role, with its distance in nautical miles.
-- Range is reported rather than used: whether DCS shows an AWACS entry at a given
-- distance is engine behaviour we cannot see, so the decision is left to the key map.
function ATC.nearestFriendlyRole(unit, attribute, typeTable)
    if type(coalition) ~= "table" or type(coalition.getGroups) ~= "function" then
        return nil
    end

    local side
    if type(unit.getCoalition) == "function" then
        local ok, value = pcall(unit.getCoalition, unit)
        if ok then side = value end
    end
    if not side then
        return nil
    end

    local from = unit:getPoint()
    local nearest
    local categories = { Group.Category.AIRPLANE, Group.Category.HELICOPTER }

    for _, category in ipairs(categories) do
        for _, group in ipairs(coalition.getGroups(side, category) or {}) do
            if group and group:isExist() then
                for _, member in ipairs(group:getUnits() or {}) do
                    if ATC.unitHasRole(member, attribute, typeTable) then
                        local to = member:getPoint()
                        local dx, dz = to.x - from.x, to.z - from.z
                        local metres = math.sqrt(dx * dx + dz * dz)
                        if not nearest or metres < nearest then
                            nearest = metres
                        end
                    end
                end
            end
        end
    end

    if not nearest then
        return nil
    end
    return math.floor(nearest / ATC.METRES_PER_NAUTICAL_MILE + 0.5)
end

-- The published facts, as a table. Separated from formatting so it can be tested.
function ATC.flightState(unit)
    if not unit or not unit.isExist or not unit:isExist() then
        return nil
    end

    local awacsNm = ATC.nearestFriendlyRole(unit, "AWACS", ATC.AWACS_TYPES)
    local tankerNm = ATC.nearestFriendlyRole(unit, "Tankers", ATC.TANKER_TYPES)
    local slots, wingmen = ATC.flightSlots(unit)

    return {
        aircraft = unit.getTypeName and unit:getTypeName() or "unknown",
        wingmen = wingmen,
        slots = slots,
        onGround = (unit.inAir and unit:inAir()) and 0 or 1,
        awacs = awacsNm and 1 or 0,
        awacsnm = awacsNm,
        tanker = tankerNm and 1 or 0,
    }
end

function ATC.formatState(state)
    if not state then
        return nil
    end
    local parts = {
        "aircraft=" .. tostring(state.aircraft),
        "wingmen=" .. tostring(state.wingmen),
        "onGround=" .. tostring(state.onGround),
        "awacs=" .. tostring(state.awacs),
    }
    if state.awacsnm then
        table.insert(parts, "awacsnm=" .. tostring(state.awacsnm))
    end
    table.insert(parts, "tanker=" .. tostring(state.tanker))

    -- slot2=1 rather than a list, so the key maps can use the existing condition
    -- syntax ("requires": ["slot2"]) with no parser changes.
    for number = 2, 4 do
        table.insert(parts, string.format("slot%d=%d", number,
            (state.slots and state.slots[number]) and 1 or 0))
    end
    return table.concat(parts, "|")
end

-- Returns true when a line was published. Silent when no player is in an aircraft,
-- rather than publishing a state nobody is in.
function ATC.publishState()
    for groupId, unit in pairs(ATC.players or {}) do
        if unit and unit.isExist and unit:isExist() then
            local state = ATC.flightState(unit)
            if state then
                env.info("ATCAI_STATE|" .. ATC.formatState(state))
                return true
            end
        else
            ATC.players[groupId] = nil
        end
    end
    return false
end

local function tick()
    pcall(ATC.publishState)
    return timer.getTime() + ATC.STATE_INTERVAL
end

if not ATC.stateScheduled then
    ATC.stateScheduled = true
    timer.scheduleFunction(tick, nil, timer.getTime() + ATC.STATE_INTERVAL)
end

env.info(string.format("ATCAI: atc_state.lua loaded, publishing every %ds",
    ATC.STATE_INTERVAL))
