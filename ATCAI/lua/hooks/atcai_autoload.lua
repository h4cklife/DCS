--[[
ATCAI - atcai_autoload.lua (Hooks script)

Loads ATCAI into EVERY mission you fly, so no mission needs patching.

Install: copy into <Saved Games>\DCS\Scripts\Hooks\ and restart DCS.
Remove:  delete it from that folder.

How it works
------------
Hooks run in DCS's GUI Lua state, which has io/lfs/net but none of the mission API.
The mission scripting state has the API but no file access. `net.dostring_in("mission",
code)` bridges them — but the state it drops code into does NOT have the mission API
globals bound (env, world, coalition are all nil there), so the code has to be handed to
a function that runs inside the real sandboxed environment.

`a_do_script(<lua source>)` is that function: it's what the Mission Editor's "DO SCRIPT"
trigger action compiles to, and it's exactly what our generated mission trigger already
runs successfully. So we ask the mission state to run a_do_script on a dofile chain.

An earlier version called `a_do_script_file(<path>)` instead, which reported success and
silently did nothing — almost certainly because "DO SCRIPT FILE" embeds the script into
the .miz as a mission resource, so that function wants a resource key rather than a
filesystem path.
]]

ATCAI_HOOK = {}

ATCAI_HOOK.FILES = { "atc_config.lua", "atc_core.lua", "atc_traffic.lua",
                      "atc_menu.lua", "atc_inbox.lua" }

-- The Lua that will run inside the mission: point at the voice inbox, then load each
-- script. [[...]] keeps Windows backslashes literal, so nothing needs escaping.
function ATCAI_HOOK.buildMissionLua(directory, files)
    local parts = { string.format("ATCAI_INBOX_PATH = [[%sinbox.lua]]", directory) }
    for _, name in ipairs(files) do
        table.insert(parts, string.format("dofile([[%s%s]])", directory, name))
    end
    return table.concat(parts, " ")
end

-- Wrapped for net.dostring_in: [==[...]==] nests safely around the inner [[...]] paths.
function ATCAI_HOOK.buildInjection(directory, files)
    return string.format("a_do_script([==[%s]==])",
        ATCAI_HOOK.buildMissionLua(directory, files))
end

function ATCAI_HOOK.scriptDirectory()
    return require("lfs").writedir() .. [[Scripts\ATCAI\]]
end

function ATCAI_HOOK.load()
    local directory = ATCAI_HOOK.scriptDirectory()
    local code = ATCAI_HOOK.buildInjection(directory, ATCAI_HOOK.FILES)

    local ok, result = pcall(net.dostring_in, "mission", code)
    -- net.dostring_in returns an error string rather than raising, so log either way.
    net.log(string.format("ATCAI: hook injected from %s (ok=%s, result=%s)",
        directory, tostring(ok), tostring(result)))
end

-- onSimulationStart fires once the mission is actually running. onMissionLoadEnd is too
-- early: the scripting engine isn't ready to accept work yet.
DCS.setUserCallbacks({ onSimulationStart = ATCAI_HOOK.load })

net.log("ATCAI: autoload hook installed")
