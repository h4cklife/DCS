--[[
ATCAI - atc_traffic.lua
Traffic awareness: works out whether anyone else is using the runway, so clearances can
be held, sequenced, or turned into a go-around.

DCS doesn't hand scripts a runway polygon, so "on the runway" is inferred rather than
measured: an aircraft on the ground, close to the field, moving faster than it would
while taxiing. "On final" is inferred from being low, close, and tracking the landing
heading. Both are deliberately loose — the aim is to stop ATC talking over obvious
traffic, not to model an airport surface.

Loaded automatically by atc_core.lua. If it's missing, clearances simply skip the
traffic checks rather than failing.
]]

-- Loading is idempotent: the hook lists this file explicitly and atc_core.lua also
-- auto-loads it as a fallback, so it can legitimately be asked for twice.
if ATC and ATC.runwayConflict then return end

ATC = ATC or {}

ATC.TRAFFIC_FIELD_RADIUS = ATC.TRAFFIC_FIELD_RADIUS or 2500     -- m from the field a ground aircraft counts as "here"
ATC.TRAFFIC_ROLL_SPEED = ATC.TRAFFIC_ROLL_SPEED or 15         -- m/s (~30 kt); above taxi speed means using the runway
ATC.TRAFFIC_FINAL_RANGE = ATC.TRAFFIC_FINAL_RANGE or 9260      -- m (5 nm) to be considered on final
ATC.TRAFFIC_FINAL_HEIGHT = ATC.TRAFFIC_FINAL_HEIGHT or 450      -- m above the field to still be on final
ATC.TRAFFIC_FINAL_ARC = ATC.TRAFFIC_FINAL_ARC or 45          -- degrees off the runway heading to count as lined up

local function horizontalDistance(a, b)
    local dx, dz = a.x - b.x, a.z - b.z
    return math.sqrt(dx * dx + dz * dz)
end

-- Smallest angle between two headings, 0-180.
function ATC.headingDifference(a, b)
    local diff = math.abs((a - b) % 360)
    if diff > 180 then
        diff = 360 - diff
    end
    return diff
end

function ATC.groundSpeed(velocity)
    if not velocity then
        return 0
    end
    return math.sqrt((velocity.x or 0) ^ 2 + (velocity.z or 0) ^ 2)
end

function ATC.travelHeading(velocity)
    if not velocity then
        return nil
    end
    if ATC.groundSpeed(velocity) < 1 then
        return nil         -- too slow for a direction to mean anything
    end
    return math.deg(math.atan2(velocity.z or 0, velocity.x or 0)) % 360
end

-- Every aircraft near a point, excluding one unit by name (normally the caller).
function ATC.aircraftNear(point, radius, excludeName)
    local found = {}
    local categories = { Group.Category.AIRPLANE, Group.Category.HELICOPTER }

    for _, side in pairs({ coalition.side.RED, coalition.side.BLUE, coalition.side.NEUTRAL }) do
        for _, category in ipairs(categories) do
            for _, group in ipairs(coalition.getGroups(side, category) or {}) do
                if group and group:isExist() then
                    for _, unit in ipairs(group:getUnits() or {}) do
                        if unit and unit:isExist() and unit:getName() ~= excludeName
                            and horizontalDistance(unit:getPoint(), point) <= radius then
                            table.insert(found, unit)
                        end
                    end
                end
            end
        end
    end
    return found
end

-- "runway" | "final" | nil, plus how far out the aircraft is.
function ATC.classifyTraffic(unit, fieldPoint, runwayHeading)
    local point = unit:getPoint()
    local distance = horizontalDistance(point, fieldPoint)
    local airborne = unit.inAir and unit:inAir()

    if not airborne then
        if distance <= ATC.TRAFFIC_FIELD_RADIUS
            and ATC.groundSpeed(unit:getVelocity()) >= ATC.TRAFFIC_ROLL_SPEED then
            return "runway", distance
        end
        return nil, distance
    end

    if distance > ATC.TRAFFIC_FINAL_RANGE then
        return nil, distance
    end
    if (point.y - (fieldPoint.y or 0)) > ATC.TRAFFIC_FINAL_HEIGHT then
        return nil, distance
    end
    -- Only traffic actually tracking the landing runway is in our way; someone
    -- transiting overhead in the opposite direction isn't.
    local heading = ATC.travelHeading(unit:getVelocity())
    if runwayHeading and heading
        and ATC.headingDifference(heading, runwayHeading) > ATC.TRAFFIC_FINAL_ARC then
        return nil, distance
    end
    return "final", distance
end

-- The most pressing conflict for an aircraft wanting the runway, or nil if it's clear.
-- Runway traffic outranks traffic on final, and closer traffic outranks distant.
function ATC.runwayConflict(airbase, conditions, selfUnit)
    local fieldPoint = airbase:getPoint()
    local runwayHeading = conditions and conditions.runway and conditions.runway.heading
    local selfName = selfUnit and selfUnit:getName() or nil
    local selfDistance = selfUnit and horizontalDistance(selfUnit:getPoint(), fieldPoint) or 0

    -- Departing traffic is blocked by anyone on final; arriving traffic only needs to
    -- sequence behind aircraft ahead of it in the approach.
    local departing = not (selfUnit and selfUnit.inAir and selfUnit:inAir())

    local best
    for _, unit in ipairs(ATC.aircraftNear(fieldPoint, ATC.TRAFFIC_FINAL_RANGE, selfName)) do
        local kind, distance = ATC.classifyTraffic(unit, fieldPoint, runwayHeading)
        if kind then
            local relevant = (kind == "runway") or departing or (distance < selfDistance)
            if relevant then
                local rank = (kind == "runway") and 0 or 1
                if not best or rank < best.rank
                    or (rank == best.rank and distance < best.distance) then
                    best = {
                        kind = kind,
                        rank = rank,
                        distance = distance,
                        unit = unit,
                        typeName = unit.getTypeName and unit:getTypeName() or "aircraft",
                    }
                end
            end
        end
    end
    return best
end

env.info("ATCAI: atc_traffic.lua loaded")
