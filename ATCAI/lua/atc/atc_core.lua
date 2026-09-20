--[[
ATCAI - atc_core.lua
Core ATC state machine, DCS World API queries, and phraseology. No menu/input handling
here — see lua/atc/atc_menu.lua for how players trigger these functions.

Load order matters: this file must be loaded before atc_menu.lua.

The pure helpers (wind/runway/formatting) take plain data rather than DCS objects so
they can be unit-tested outside the sim — see tools/test_atc_core.lua.
]]

ATC = ATC or {}
ATC.state = ATC.state or {}
ATC.METRES_PER_NAUTICAL_MILE = 1852

-- Where these scripts live, so siblings and the voice inbox can be found without the
-- mission having to inject absolute paths. DCS doesn't sanitise `debug`, and this keeps
-- missions built before a script was added from silently missing it.
local function scriptDirectory()
    -- Must not be wrapped in pcall: that adds a stack frame, so level 1 would resolve
    -- to pcall's C frame rather than this function's own chunk.
    if type(debug) ~= "table" or type(debug.getinfo) ~= "function" then
        return nil
    end
    local info = debug.getinfo(1, "S")
    if not info or not info.source then
        return nil
    end
    return (tostring(info.source):gsub("^@", "")):match("^(.*[\\/])")
end

ATCAI_SCRIPT_DIR = ATCAI_SCRIPT_DIR or scriptDirectory()
if ATCAI_SCRIPT_DIR then
    ATCAI_INBOX_PATH = ATCAI_INBOX_PATH or (ATCAI_SCRIPT_DIR .. "inbox.lua")
    ATCAI_CONFIG_PATH = ATCAI_CONFIG_PATH or (ATCAI_SCRIPT_DIR .. "config.lua")
end

-- User settings are applied BEFORE the defaults below, which are all written as
-- "keep what's there, otherwise use this" — so a configured value survives and an
-- absent one falls back. That keeps load order from mattering.
if not ATC.applyConfig and ATCAI_SCRIPT_DIR then
    pcall(dofile, ATCAI_SCRIPT_DIR .. "atc_config.lua")
end
if ATC.loadConfig then
    ATC.loadConfig(ATCAI_CONFIG_PATH)
end

-- How close you must be for a field to answer. Ground operations want a tight radius so
-- "your" airfield is unambiguously the one you're sitting on; airborne calls are made
-- from far further out, so inbound reports need a much wider net.
ATC.AIRBASE_SEARCH_RADIUS = ATC.AIRBASE_SEARCH_RADIUS or 6000     -- metres, on the ground (~3 nm)
ATC.AIRBASE_AIR_RADIUS = ATC.AIRBASE_AIR_RADIUS or 92600          -- metres, airborne (50 nm)

-- 276.375 is the F-15C's default UHF preset (CHAN 06) in the test mission; the rest are
-- common DCS defaults. If you don't hear ATC, check the frequency on your radio and add
-- it here — the two lists must stay the same length.
ATC.TTS_FREQUENCY = ATC.TTS_FREQUENCY or "276.375,251.0,305.0,124.0,127.5"
ATC.TTS_MODULATION = ATC.TTS_MODULATION or "AM,AM,AM,AM,AM"

-- Flight phases, in the order a sortie normally moves through them.
ATC.PHASE = {
    PARKED = "parked",
    STARTUP = "startup",
    HOLDING_SHORT = "holding_short",
    TAKEOFF = "takeoff_cleared",
    AIRBORNE = "airborne",
    INBOUND = "inbound",
    LANDING = "cleared_to_land",
}

-- ---------- pure helpers ----------

local function normalizeHeading(deg)
    deg = deg % 360
    if deg < 0 then
        deg = deg + 360
    end
    return deg
end

-- Runway designators are magnetic heading / 10, with 36 rather than 0 for north.
function ATC.headingToRunwayName(heading)
    local num = math.floor(normalizeHeading(heading) / 10 + 0.5)
    if num == 0 then
        num = 36
    elseif num > 36 then
        num = num - 36
    end
    return string.format("%02d", num)
end

-- DCS wind vectors point the way the air is moving; aviation quotes the direction it
-- comes FROM. x is north, z is east. Returns (degrees-from, knots).
function ATC.windFromVector(wind)
    if not wind then
        return 0, 0
    end
    local speedMs = math.sqrt((wind.x or 0) ^ 2 + (wind.z or 0) ^ 2)
    local towardDeg = math.deg(math.atan2(wind.z or 0, wind.x or 0))
    return normalizeHeading(towardDeg + 180), speedMs * 1.94384
end

-- A physical runway serves two opposing ends; ATC picks whichever suits the wind.
function ATC.runwayEnds(runway)
    local ends = {}
    if not runway then
        return ends
    end

    local name = tostring(runway.Name or runway.name or "")
    local digits = name:match("^%s*(%d+)")
    local num = tonumber(digits)
    if num and num >= 1 and num <= 36 then
        local recip = num + 18
        if recip > 36 then
            recip = recip - 36
        end
        ends[1] = { name = string.format("%02d", num), heading = normalizeHeading(num * 10) }
        ends[2] = { name = string.format("%02d", recip), heading = normalizeHeading(recip * 10) }
        return ends
    end

    -- Name wasn't a designator, so fall back to the reported course (radians).
    if runway.course then
        local heading = normalizeHeading(-math.deg(runway.course))
        local recip = normalizeHeading(heading + 180)
        ends[1] = { name = ATC.headingToRunwayName(heading), heading = heading }
        ends[2] = { name = ATC.headingToRunwayName(recip), heading = recip }
    end
    return ends
end

-- Picks the end with the strongest headwind component.
function ATC.selectRunwayEnd(runways, windFromDeg)
    local best, bestScore
    for _, runway in ipairs(runways or {}) do
        for _, candidate in ipairs(ATC.runwayEnds(runway)) do
            local score = math.cos(math.rad(candidate.heading - windFromDeg))
            if not bestScore or score > bestScore then
                best, bestScore = candidate, score
            end
        end
    end
    return best
end

function ATC.formatWind(fromDeg, speedKts)
    if not speedKts or speedKts < 1 then
        return "wind calm"
    end
    return string.format("wind %03d at %d", math.floor(fromDeg + 0.5), math.floor(speedKts + 0.5))
end

function ATC.distanceText(metres)
    if not metres then
        return "position unknown"
    end
    local miles = metres / ATC.METRES_PER_NAUTICAL_MILE
    if miles < 1 then
        return "overhead the field"
    end
    return string.format("%d miles", math.floor(miles + 0.5))
end

function ATC.formatQNH(pressurePa)
    if not pressurePa or pressurePa <= 0 then
        return "QNH unavailable"
    end
    return string.format("QNH %.2f", pressurePa / 3386.389)
end

-- Unit names carry Mission Editor decoration ("- Chevy 81 (Player)") that reads badly
-- over TTS. Reduce to just the callsign.
function ATC.callsign(unit)
    local raw = unit:getName() or "Unknown"
    local name = raw:gsub("%b()", ""):gsub("^[%s%-%*#]+", ""):gsub("[%s%-]+$", "")
    if name == "" then
        return raw
    end
    return name
end

-- ---------- state ----------

function ATC.getState(unitName)
    if not ATC.state[unitName] then
        ATC.state[unitName] = { phase = ATC.PHASE.PARKED }
    end
    return ATC.state[unitName]
end

-- ---------- DCS-facing lookups ----------

local function get2DDistance(p1, p2)
    local dx = p1.x - p2.x
    local dz = p1.z - p2.z
    return math.sqrt(dx * dx + dz * dz)
end

function ATC.findNearestAirbase(unit)
    local unitPos = unit:getPoint()
    local nearest, nearestDist = nil, math.huge

    for _, airbase in pairs(world.getAirbases()) do
        local dist = get2DDistance(unitPos, airbase:getPoint())
        if dist < nearestDist then
            nearest, nearestDist = airbase, dist
        end
    end

    local limit = ATC.AIRBASE_SEARCH_RADIUS
    if unit.inAir and unit:inAir() then
        limit = ATC.AIRBASE_AIR_RADIUS
    end

    if nearest and nearestDist <= limit then
        return nearest, nearestDist
    end
    -- Hand back the distance even on a miss, so the refusal can say how far out you are.
    return nil, nearestDist
end

-- Wind, altimeter and the runway in use, as reported by the field.
function ATC.getFieldConditions(airbase)
    local point = airbase:getPoint()
    -- Sample wind slightly above the surface; at ground level DCS reports zero.
    local windPoint = { x = point.x, y = (point.y or 0) + 10, z = point.z }
    local windFrom, windKts = ATC.windFromVector(atmosphere.getWind(windPoint))
    local _, pressure = atmosphere.getTemperatureAndPressure(point)

    return {
        windFrom = windFrom,
        windKts = windKts,
        windText = ATC.formatWind(windFrom, windKts),
        qnhText = ATC.formatQNH(pressure),
        runway = ATC.selectRunwayEnd(airbase:getRunways(), windFrom),
    }
end

function ATC.towerName(airbase)
    return airbase:getCallsign() or airbase:getName()
end

local function runwayText(conditions)
    if conditions.runway then
        return "runway " .. conditions.runway.name
    end
    return "the active runway"
end

local function say(groupId, text)
    trigger.action.outTextForGroup(groupId, text, 15, false)
    -- Mission Lua can't launch processes or write files, so dcs.log is the outbound
    -- channel: voice-bridge/atcai_tts.py tails it for this prefix and speaks the line
    -- over SRS.
    env.info(string.format("ATCAI_TTS|%s|%s|%s",
        tostring(ATC.TTS_FREQUENCY), tostring(ATC.TTS_MODULATION), text))
end

-- ---------- request plumbing ----------

-- Resolves the common preamble every request needs, or explains why it can't proceed.
-- Returns nil plus a spoken refusal when the request doesn't fit the situation.
local function begin(params, opts)
    local unit = params.unit
    local callsign = ATC.callsign(unit)
    local state = ATC.getState(unit:getName())
    local airborne = unit:inAir()

    if opts.requireAirborne and not airborne then
        return nil, string.format("%s, unable, you're still on the ground.", callsign)
    end
    if opts.requireGround and airborne then
        return nil, string.format("%s, unable, you're airborne.", callsign)
    end

    if opts.phases then
        local allowed = false
        for _, phase in ipairs(opts.phases) do
            if state.phase == phase then
                allowed = true
                break
            end
        end
        if not allowed then
            return nil, string.format("%s, unable, %s", callsign, opts.denial)
        end
    end

    local airbase, distance = ATC.findNearestAirbase(unit)
    if not airbase then
        if distance and distance < math.huge then
            return nil, string.format("%s, no ATC in range, nearest field is %d miles.",
                callsign, math.floor(distance / ATC.METRES_PER_NAUTICAL_MILE + 0.5))
        end
        return nil, string.format("%s, no ATC in range.", callsign)
    end

    return {
        unit = unit,
        callsign = callsign,
        state = state,
        airbase = airbase,
        distance = distance,
        tower = ATC.towerName(airbase),
        conditions = ATC.getFieldConditions(airbase),
    }
end

-- Traffic checking lives in atc_traffic.lua. If that file isn't loaded, clearances carry
-- on without it rather than failing.
function ATC.checkRunway(ctx)
    if type(ATC.runwayConflict) ~= "function" then
        return nil
    end
    local ok, conflict = pcall(ATC.runwayConflict, ctx.airbase, ctx.conditions, ctx.unit)
    if not ok then
        env.info("ATCAI: traffic check failed: " .. tostring(conflict))
        return nil
    end
    return conflict
end

-- ---------- requests ----------

function ATC.requestRadioCheck(params)
    local ctx, refusal = begin(params, {})
    if not ctx then
        say(params.groupId, refusal)
        return
    end
    say(params.groupId, string.format("%s, %s, read you five by five.", ctx.callsign, ctx.tower))
end

function ATC.requestStartup(params)
    local ctx, refusal = begin(params, {
        requireGround = true,
        phases = { ATC.PHASE.PARKED },
        denial = "you've already started up.",
    })
    if not ctx then
        say(params.groupId, refusal)
        return
    end

    ctx.state.phase = ATC.PHASE.STARTUP
    say(params.groupId, string.format("%s, %s, startup approved, %s in use, %s, %s.",
        ctx.callsign, ctx.tower, runwayText(ctx.conditions),
        ctx.conditions.windText, ctx.conditions.qnhText))
end

function ATC.requestTaxi(params)
    local ctx, refusal = begin(params, {
        requireGround = true,
        phases = { ATC.PHASE.PARKED, ATC.PHASE.STARTUP },
        denial = "you're already taxiing.",
    })
    if not ctx then
        say(params.groupId, refusal)
        return
    end

    ctx.state.phase = ATC.PHASE.HOLDING_SHORT
    say(params.groupId, string.format("%s, %s, taxi to holding point %s, %s, hold short.",
        ctx.callsign, ctx.tower, runwayText(ctx.conditions), ctx.conditions.qnhText))
end

function ATC.requestTakeoff(params)
    local ctx, refusal = begin(params, {
        requireGround = true,
        phases = { ATC.PHASE.HOLDING_SHORT, ATC.PHASE.TAKEOFF },
        denial = "request taxi first.",
    })
    if not ctx then
        say(params.groupId, refusal)
        return
    end

    local conflict = ATC.checkRunway(ctx)
    if conflict then
        -- Stay at the holding point: the phase is deliberately left alone so the pilot
        -- can simply ask again once the runway clears.
        if conflict.kind == "runway" then
            say(params.groupId, string.format("%s, %s, hold position, traffic on the runway.",
                ctx.callsign, ctx.tower))
        else
            say(params.groupId, string.format("%s, %s, hold short, landing traffic %s.",
                ctx.callsign, ctx.tower, ATC.distanceText(conflict.distance)))
        end
        return
    end

    ctx.state.phase = ATC.PHASE.TAKEOFF
    say(params.groupId, string.format("%s, %s, %s, %s, cleared for takeoff.",
        ctx.callsign, ctx.tower, runwayText(ctx.conditions), ctx.conditions.windText))
end

function ATC.requestInbound(params)
    local ctx, refusal = begin(params, { requireAirborne = true })
    if not ctx then
        say(params.groupId, refusal)
        return
    end

    ctx.state.phase = ATC.PHASE.INBOUND
    say(params.groupId, string.format("%s, %s, %s, join the circuit for %s, %s, %s, report final.",
        ctx.callsign, ctx.tower, ATC.distanceText(ctx.distance), runwayText(ctx.conditions),
        ctx.conditions.windText, ctx.conditions.qnhText))
end

function ATC.requestLanding(params)
    local ctx, refusal = begin(params, { requireAirborne = true })
    if not ctx then
        say(params.groupId, refusal)
        return
    end

    local conflict = ATC.checkRunway(ctx)
    if conflict then
        ctx.state.phase = ATC.PHASE.INBOUND
        if conflict.kind == "runway" then
            say(params.groupId, string.format("%s, %s, go around, traffic on the runway.",
                ctx.callsign, ctx.tower))
        else
            say(params.groupId, string.format(
                "%s, %s, continue approach, number two behind the %s, %s ahead.",
                ctx.callsign, ctx.tower, conflict.typeName,
                ATC.distanceText(conflict.distance)))
        end
        return
    end

    ctx.state.phase = ATC.PHASE.LANDING
    say(params.groupId, string.format("%s, %s, %s, %s, cleared to land.",
        ctx.callsign, ctx.tower, runwayText(ctx.conditions), ctx.conditions.windText))
end

function ATC.requestParking(params)
    local ctx, refusal = begin(params, {
        requireGround = true,
        phases = { ATC.PHASE.LANDING, ATC.PHASE.INBOUND, ATC.PHASE.TAKEOFF },
        denial = "you haven't landed.",
    })
    if not ctx then
        say(params.groupId, refusal)
        return
    end

    ctx.state.phase = ATC.PHASE.PARKED
    say(params.groupId, string.format("%s, %s, vacate the runway and taxi to parking.",
        ctx.callsign, ctx.tower))
end

function ATC.requestLoadout(params)
    local unit = params.unit
    local ammo = unit:getAmmo()

    if not ammo or #ammo == 0 then
        say(params.groupId, string.format("%s, no stores remaining.", ATC.callsign(unit)))
        return
    end

    local parts = {}
    for _, item in ipairs(ammo) do
        local name = item.desc and (item.desc.displayName or item.desc.typeName) or "unknown store"
        table.insert(parts, string.format("%d %s", item.count, name))
    end

    say(params.groupId, string.format("%s loadout: %s.",
        ATC.callsign(unit), table.concat(parts, ", ")))
end

-- Load traffic awareness if the mission didn't list it explicitly, the same way
-- atc_menu.lua picks up the voice inbox.
if not ATC.runwayConflict and ATCAI_SCRIPT_DIR then
    local ok, err = pcall(dofile, ATCAI_SCRIPT_DIR .. "atc_traffic.lua")
    if not ok then
        env.info("ATCAI: could not auto-load atc_traffic.lua: " .. tostring(err))
    end
end

env.info("ATCAI: atc_core.lua loaded")
