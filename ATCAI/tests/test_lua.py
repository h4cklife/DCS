"""The Lua suites, run on DCS's own bundled Lua 5.1 interpreter.

Lua has no pytest, so each suite stays a Lua script under tools/ and is reported here as
one pytest case. Running them on DCS's interpreter rather than a system Lua means they
execute on exactly the runtime the mission scripts will.
"""

import subprocess

import pytest

from conftest import ROOT, dcs_lua

LUA = dcs_lua()
pytestmark = [
    pytest.mark.lua,
    pytest.mark.skipif(LUA is None,
                       reason="DCS's Lua interpreter not found; set DCS_BIN"),
]

ATC = ROOT / "lua" / "atc"
SUITES = {
    "config": ("test_atc_config.lua", [ATC / "atc_config.lua", ATC / "atc_core.lua"]),
    "core": ("test_atc_core.lua", [ATC / "atc_core.lua"]),
    "inbox": ("test_atc_inbox.lua", [ATC / "atc_core.lua", ATC / "atc_inbox.lua"]),
    "traffic": ("test_atc_traffic.lua", [ATC / "atc_core.lua", ATC / "atc_traffic.lua"]),
    "hook": ("test_hook_injection.lua", [ROOT / "lua" / "hooks" / "atcai_autoload.lua"]),
}


def windows_path(path) -> str:
    """luae.exe is a Windows binary, so it needs Windows-style paths."""
    try:
        return subprocess.run(["wslpath", "-w", str(path)], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return str(path)


def run_lua(script, args):
    result = subprocess.run(
        [str(LUA), windows_path(script)] + [windows_path(a) for a in args],
        capture_output=True, cwd=str(LUA.parent), timeout=180,
    )
    return result.returncode, (result.stdout + result.stderr).decode("cp1252",
                                                                    errors="replace")


@pytest.mark.parametrize("name", sorted(SUITES))
def test_lua_suite(name):
    script, args = SUITES[name]
    code, output = run_lua(ROOT / "tools" / script, args)
    assert code == 0, output
    assert "0 failed" in output, output


def test_inbox_round_trip(tmp_path):
    """The whole point of the inbound bridge: Python writes, DCS's Lua reads it back."""
    import atcai_listen

    inbox = tmp_path / "inbox.lua"
    atcai_listen.write_inbox(str(inbox), "taxi")

    code, output = run_lua(ROOT / "tools" / "test_inbox_file.lua", [
        ATC / "atc_core.lua", ATC / "atc_inbox.lua", inbox, "taxi",
    ])
    assert code == 0, output
    assert "0 failed" in output, output
