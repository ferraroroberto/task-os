r"""The gate's dead-code-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.dead_code_ratchet_gate

`scripts/dead_code_ratchet.py` is vendored and never edited here. It exits 0 when
every function, class and method in the tracked Python tree is referenced somewhere
or is baselined, and 1 when an unreferenced one is new. Exit 2 is a bad table,
baseline or argument. Exit 3 means the tree was never fully read (git unusable, a
file that cannot be read or does not parse), which is its own failure state here --
NOT CONFIRMED, never a pass or a skip: the unparsed file may hold the only caller
of a definition elsewhere. The mapping lives only in this wrapper so a test can pin
it, and `verify-before-ship.ps1` calls the wrapper, not the script.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "dead_code_ratchet.py"

# Parsing the tracked Python tree takes a second or two; the bound only turns a
# hung child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a function, class or method nothing references is new",
    2: "bad [dead_code_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- a Python file could not be read or parsed, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no dead definition above the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The dead-code-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "dead-code ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
