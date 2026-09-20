#!/usr/bin/env bash
# Runs the whole test suite: pytest covers the Python side and drives the Lua suites
# through DCS's own Lua interpreter.
#
# Prefers Windows Python when it can find it, because the manager's GUI tests need
# tkinter and a display, which WSL's Python usually lacks. Everything else runs either
# way; GUI tests skip cleanly when they can't run.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
cd "$root" || exit 2

pick_python() {
    if [[ -n "${ATCAI_PYTHON:-}" ]]; then echo "$ATCAI_PYTHON"; return; fi
    local win
    win="$(ls -d /mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe 2>/dev/null | sort -r | head -1)"
    if [[ -n "$win" ]] && "$win" -c "import pytest, tkinter" >/dev/null 2>&1; then
        echo "$win"; return
    fi
    if [[ -x "$root/venv/bin/python" ]]; then echo "$root/venv/bin/python"; return; fi
    echo python3
}

python="$(pick_python)"
echo "running tests with: $python"

target="tests"
if [[ "$python" == *.exe ]]; then
    target="$(wslpath -w "$root/tests" 2>/dev/null || echo tests)"
fi

"$python" -m pytest "$target" "$@" 2>&1 | tr -d '\000'
exit "${PIPESTATUS[0]}"
