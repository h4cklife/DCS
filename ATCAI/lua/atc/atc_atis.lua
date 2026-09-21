--[[
ATCAI - atc_atis.lua
The looping ATIS broadcast: field information repeated on its own frequency, so you can
tune in and listen rather than asking for it.

Two things differ from a real ATIS, both forced by what DCS exposes:

  * Real fields each broadcast on their own ATIS frequency. DCS's terrain data gives
    airfields only ground/tower/approach roles, so there is no ATIS frequency to read.
    Instead there's one ATIS channel, carrying the information for whichever field the
    player is nearest.
  * Nothing is broadcast when no player is near an airfield, rather than transmitting
    into an empty sky every minute.

Unlike the on-request version this only goes out over the radio - it deliberately does
not write on-screen text, which would be intrusive once a minute.
]]

if ATC and ATC.broadcastAtis then return end

ATC = ATC or {}

-- Default 380.000 AM: inside the 225-400 UHF band nearly every DCS military aircraft
-- tunes, and clear of the frequencies terrains give their airfields. The manager can
-- override this, including picking an unused frequency automatically.
ATC.ATIS_ENABLED = ATC.ATIS_ENABLED ~= false
ATC.ATIS_FREQUENCY = ATC.ATIS_FREQUENCY or "380.000"
ATC.ATIS_MODULATION = ATC.ATIS_MODULATION or "AM"
ATC.ATIS_INTERVAL = ATC.ATIS_INTERVAL or 60      -- seconds between repeats

-- The information for whichever field a player is closest to, or nil if nobody is
-- near one.
function ATC.atisBroadcastText()
    if type(ATC.findNearestAirbase) ~= "function" or type(ATC.atisReport) ~= "function" then
        return nil
    end

    for groupId, unit in pairs(ATC.players or {}) do
        if unit and unit.isExist and unit:isExist() then
            local airbase = ATC.findNearestAirbase(unit)
            if airbase then
                local clock = (timer and timer.getAbsTime) and timer.getAbsTime() or 0
                return ATC.atisReport(ATC.towerName(airbase),
                                      ATC.getFieldConditions(airbase), clock)
            end
        else
            ATC.players[groupId] = nil
        end
    end
    return nil
end

-- Returns true when something was actually transmitted.
function ATC.broadcastAtis()
    if not ATC.ATIS_ENABLED then
        return false
    end
    local text = ATC.atisBroadcastText()
    if not text then
        return false
    end
    -- Straight to the log rather than through say(): this is a radio broadcast, so the
    -- TTS bridge picks it up but nothing appears on screen.
    env.info(string.format("ATCAI_TTS|%s|%s|%s",
        tostring(ATC.ATIS_FREQUENCY), tostring(ATC.ATIS_MODULATION), text))
    return true
end

local function tick()
    pcall(ATC.broadcastAtis)
    return timer.getTime() + ATC.ATIS_INTERVAL
end

if not ATC.atisScheduled then
    ATC.atisScheduled = true
    timer.scheduleFunction(tick, nil, timer.getTime() + ATC.ATIS_INTERVAL)
end

env.info(string.format("ATCAI: atc_atis.lua loaded, broadcasting on %s %s every %ds",
    tostring(ATC.ATIS_FREQUENCY), tostring(ATC.ATIS_MODULATION), ATC.ATIS_INTERVAL))
