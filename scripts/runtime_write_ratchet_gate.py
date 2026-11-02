r"""The gate's runtime-write-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.runtime_write_ratchet_gate

`scripts/runtime_write_ratchet.py` (and the resolver it imports,
`scripts/runtime_write_resolve.py`) is vendored and never edited here. It exits 0
when no file has more write targets resolving under a code folder than the baseline
allows, and 1 when a count rose. Exit 2 is a bad table, baseline or argument. Exit 3
means a write went unplaced (a new target it cannot resolve, git unusable, a file
that does not parse), which is its own failure state here -- NOT CONFIRMED, never a
pass or a skip. The mapping lives only in this wrapper so a test can pin it, and
`verify-before-ship.ps1` calls the wrapper, not the script, for this stage.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "runtime_write_ratchet.py"

# Parsing the tracked tree takes a second or two; the bound only turns a hung
# child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a file has more writes under a code folder than the baseline allows",
    2: "bad [runtime_write_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- a new write target could not be resolved, or a source file could not be read",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no write under a code folder above the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The runtime-write-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "runtime write ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
