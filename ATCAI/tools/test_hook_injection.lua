--[[
Tests for lua/hooks/atcai_autoload.lua — the Hook that loads ATCAI into every mission.

The Hook's whole job is to build a string of Lua that gets executed in two nested
contexts. Escaping or nesting mistakes there fail *silently* inside DCS, which is what
made the first attempt so hard to diagnose. These tests execute the generated code with
stand-ins for a_do_script and dofile, so a malformed string fails here instead.

Args: <atcai_autoload.lua>
]]

local HOOK_PATH = arg[1]

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

local function eq(actual, expected, label)
    check(actual == expected, label,
        string.format("expected %s, got %s", tostring(expected), tostring(actual)))
end

-- ---------- stub the Hooks environment ----------

local logged = {}
local injected = nil
local callbacks = nil

net = {
    log = function(msg) table.insert(logged, msg) end,
    dostring_in = function(state, code)
        injected = { state = state, code = code }
        return ""        -- what DCS returns on success
    end,
}

DCS = { setUserCallbacks = function(cb) callbacks = cb end }

-- The hook calls require("lfs"); give it one.
local realRequire = require
require = function(name)
    if name == "lfs" then
        return { writedir = function() return [[C:\Users\artic\Saved Games\DCS\]] end }
    end
    return realRequire(name)
end

dofile(HOOK_PATH)

-- ---------- tests ----------

print("hook registers itself")
do
    check(callbacks ~= nil, "user callbacks were registered")
    eq(type(callbacks and callbacks.onSimulationStart), "function",
        "it hooks onSimulationStart, not the too-early onMissionLoadEnd")
    check(#logged > 0, "it logs that it installed")
end

print("the mission Lua it builds")
do
    local DIR = [[C:\Users\artic\Saved Games\DCS\Scripts\ATCAI\]]
    local lua = ATCAI_HOOK.buildMissionLua(DIR, { "atc_core.lua", "atc_menu.lua" })

    check(lua:find("ATCAI_INBOX_PATH", 1, true) ~= nil, "it sets the voice inbox path")
    check(lua:find("dofile([[" .. DIR .. "atc_core.lua]])", 1, true) ~= nil,
        "it dofiles each script by absolute path", lua)
    check(lua:find("\\", 1, true) ~= nil, "Windows backslashes survive verbatim")
end

print("the injected string is valid Lua that does the right thing")
do
    local DIR = [[C:\Users\artic\Saved Games\DCS\Scripts\ATCAI\]]
    local code = ATCAI_HOOK.buildInjection(DIR, ATCAI_HOOK.FILES)

    -- Stand in for the mission environment: a_do_script receives Lua source and runs it.
    local loadedFiles = {}
    local sandbox = {}
    sandbox.dofile = function(path) table.insert(loadedFiles, path) end
    sandbox.a_do_script = function(source)
        local chunk, err = loadstring(source, "injected")
        if not chunk then
            error("a_do_script received invalid Lua: " .. tostring(err))
        end
        setfenv(chunk, sandbox)
        chunk()
    end
    sandbox.string = string

    local chunk, err = loadstring(code, "injection")
    check(chunk ~= nil, "the injected string parses as Lua", tostring(err))

    if chunk then
        setfenv(chunk, sandbox)
        local ok, runErr = pcall(chunk)
        check(ok, "running it does not raise", tostring(runErr))

        eq(#loadedFiles, #ATCAI_HOOK.FILES, "every script is loaded")
        eq(loadedFiles[1], DIR .. "atc_config.lua",
            "atc_config loads first, so user settings are in place before any defaults")
        eq(loadedFiles[2], DIR .. "atc_core.lua", "atc_core loads next")
        eq(loadedFiles[#loadedFiles], DIR .. "atc_atis.lua",
            "the ATIS broadcast loads last, once the player registry exists")
        eq(sandbox.ATCAI_INBOX_PATH, DIR .. "inbox.lua",
            "the inbox path is set inside the mission environment")
    end
end

print("load() sends it to the mission state")
do
    injected = nil
    ATCAI_HOOK.load()
    check(injected ~= nil, "something was injected")
    eq(injected and injected.state, "mission", "it targets the mission Lua state")
    check(injected and injected.code:find("a_do_script", 1, true) ~= nil,
        "it calls a_do_script, not the a_do_script_file that silently failed before")
    check(injected and injected.code:find("a_do_script_file", 1, true) == nil,
        "a_do_script_file is not used anywhere")
end

print("paths with spaces are handled")
do
    local DIR = [[C:\Users\some one\Saved Games\DCS\Scripts\ATCAI\]]
    local code = ATCAI_HOOK.buildInjection(DIR, { "atc_core.lua" })
    local chunk = loadstring(code, "spaces")
    check(chunk ~= nil, "a path containing spaces still parses")
end

print(string.format("\n%d checks, %d failed", checks, failures))
os.exit(failures == 0 and 0 or 1)
