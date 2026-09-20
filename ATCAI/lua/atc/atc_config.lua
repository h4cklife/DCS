--[[
ATCAI - atc_config.lua
Applies user settings over the defaults baked into the scripts.

The manager app writes <Saved Games>\DCS\Scripts\ATCAI\config.lua as a plain Lua table:

    ATCAI_CONFIG = { tts_frequency = "251.0", airbase_air_radius = 120000 }

Keeping settings in a separate generated file means the app never has to parse or
rewrite Lua source, and hand-edited scripts keep working when no config is present.

Loaded by atc_core.lua after its defaults are set. Unknown keys are ignored; bad values
are ignored individually rather than discarding the whole file, so one bad setting can't
stop ATC working.
]]

if ATC and ATC.applyConfig then return end

ATC = ATC or {}

-- setting name -> { field on ATC, expected Lua type }
ATC.CONFIG_FIELDS = {
    tts_frequency         = { "TTS_FREQUENCY", "string" },
    tts_modulation        = { "TTS_MODULATION", "string" },
    airbase_search_radius = { "AIRBASE_SEARCH_RADIUS", "number" },
    airbase_air_radius    = { "AIRBASE_AIR_RADIUS", "number" },
    inbox_poll_seconds    = { "INBOX_POLL_SECONDS", "number" },
    traffic_field_radius  = { "TRAFFIC_FIELD_RADIUS", "number" },
    traffic_roll_speed    = { "TRAFFIC_ROLL_SPEED", "number" },
    traffic_final_range   = { "TRAFFIC_FINAL_RANGE", "number" },
    traffic_final_height  = { "TRAFFIC_FINAL_HEIGHT", "number" },
    traffic_final_arc     = { "TRAFFIC_FINAL_ARC", "number" },
}

-- Returns the number of settings applied, and a list of anything rejected.
function ATC.applyConfig(config)
    local applied, rejected = 0, {}
    if type(config) ~= "table" then
        return 0, rejected
    end

    for key, value in pairs(config) do
        local field = ATC.CONFIG_FIELDS[key]
        if not field then
            table.insert(rejected, tostring(key) .. " (unknown setting)")
        elseif type(value) ~= field[2] then
            table.insert(rejected, string.format("%s (expected %s, got %s)",
                tostring(key), field[2], type(value)))
        elseif field[2] == "number" and value <= 0 then
            table.insert(rejected, tostring(key) .. " (must be positive)")
        else
            ATC[field[1]] = value
            applied = applied + 1
        end
    end
    return applied, rejected
end

-- Reads the generated config file, if there is one, and applies it.
function ATC.loadConfig(path)
    if not path then
        return 0
    end
    -- A missing file is the normal case, not an error.
    if not pcall(dofile, path) then
        return 0
    end
    if type(ATCAI_CONFIG) ~= "table" then
        return 0
    end

    local applied, rejected = ATC.applyConfig(ATCAI_CONFIG)
    if #rejected > 0 then
        env.info("ATCAI: ignored settings: " .. table.concat(rejected, ", "))
    end
    env.info(string.format("ATCAI: applied %d setting(s) from %s", applied, tostring(path)))
    return applied
end
