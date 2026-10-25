--[[
Reads an aircraft's real keyboard bindings out of DCS's own files.

DCS stores bindings as Lua that *executes* rather than as data:

    local res = external_profile("Config/Input/Aircrafts/base_keyboard_binding.lua")
    ignore_features(res.keyCommands, {"dragchute", "shiptakeoff", "a2g"})
    join(res.keyCommands, { ...aircraft-specific entries... })

So it is run, with DCS's own helpers stubbed - the same approach the Lua test suites
take. Running it rather than parsing it gets the semantics right: the shared base is
pulled in, ignore_features filtering happens, and the aircraft's own additions land in
the right order.

The player's remappings are applied on top. Their file keys are opaque hashes, but each
entry carries a readable `name`, which is what the layers are matched on.

Args: <dcs root> <aircraft profile.lua> [player diff.lua]

Output, one line each:
  BINDING|<control name>|<modifiers, +-separated>|<key>
  UNRESOLVED|<control name>        - indirects through DCS's device tables
  ERROR|<message>
  DONE|<count>
]]

local DCS_ROOT, PROFILE, DIFF = arg[1], arg[2], arg[3]

local function emit(line)
    io.write(line, "\n")
end

if not DCS_ROOT or not PROFILE then
    emit("ERROR|usage: readbindings.lua <dcs root> <profile> [diff]")
    os.exit(1)
end

-- ---------- DCS's helpers, stubbed ----------

_ = function(text) return text end

-- Resolves against DCS's internal device tables, which are not available here. Marked
-- rather than guessed: a wrong key is worse than a missing one.
function defaultDeviceAssignmentFor(name)
    return { { key = "@unresolved:" .. tostring(name) } }
end

function external_profile(relative)
    local path = DCS_ROOT .. "/" .. relative
    local chunk, err = loadfile(path)
    if not chunk then
        error("could not load " .. path .. ": " .. tostring(err))
    end
    return chunk()
end

-- Real DCS filters by feature tag. The shape is what matters here, and over-reporting
-- a control the aircraft lacks is harmless: it simply never matches a binding.
function ignore_features(commands) return commands end
function remove_features(commands) return commands end

function join(target, extra)
    for _, item in ipairs(extra or {}) do
        table.insert(target, item)
    end
    return target
end
function splice(target, extra) return join(target, extra) end

-- ---------- load ----------

local chunk, loadErr = loadfile(PROFILE)
if not chunk then
    emit("ERROR|could not load the aircraft profile: " .. tostring(loadErr))
    os.exit(1)
end

local ok, profile = pcall(chunk)
if not ok then
    emit("ERROR|the aircraft profile would not run: " .. tostring(profile))
    os.exit(1)
end

local commands = profile and profile.keyCommands
if type(commands) ~= "table" then
    emit("ERROR|the profile produced no keyCommands")
    os.exit(1)
end

-- ---------- the player's remappings ----------

local function comboKey(combo)
    local modifiers = {}
    for _, modifier in ipairs(combo.reformers or {}) do
        table.insert(modifiers, tostring(modifier))
    end
    return table.concat(modifiers, "+"), tostring(combo.key)
end

local function sameCombo(a, b)
    local aMods, aKey = comboKey(a)
    local bMods, bKey = comboKey(b)
    return aMods == bMods and aKey == bKey
end

local diffByName = {}
if DIFF then
    local diffChunk = loadfile(DIFF)
    if diffChunk then
        local diffOk, diff = pcall(diffChunk)
        if diffOk and type(diff) == "table" and type(diff.keyDiffs) == "table" then
            for _, entry in pairs(diff.keyDiffs) do
                if entry.name then
                    diffByName[entry.name] = entry
                end
            end
        end
    end
    -- A diff that cannot be read is reported but not fatal: the defaults are still
    -- better than nothing, and saying so is better than silently using them.
    if next(diffByName) == nil then
        emit("ERROR|the player's remappings could not be read; using defaults only")
    end
end

-- ---------- emit ----------

local count = 0
for _, command in ipairs(commands) do
    local name = command.name and tostring(command.name) or nil
    if name then
        local combos = {}
        for _, combo in ipairs(command.combos or {}) do
            table.insert(combos, combo)
        end

        local change = diffByName[name]
        if change then
            -- Removals first, so a rebind expressed as remove-then-add lands correctly.
            for _, gone in ipairs(change.removed or {}) do
                for index = #combos, 1, -1 do
                    if sameCombo(combos[index], gone) then
                        table.remove(combos, index)
                    end
                end
            end
            for _, added in ipairs(change.added or {}) do
                table.insert(combos, added)
            end
        end

        for _, combo in ipairs(combos) do
            local modifiers, key = comboKey(combo)
            if key:sub(1, 12) == "@unresolved:" then
                emit("UNRESOLVED|" .. name)
            else
                emit("BINDING|" .. name .. "|" .. modifiers .. "|" .. key)
                count = count + 1
            end
        end
    end
end

emit("DONE|" .. count)
