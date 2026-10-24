r"""The gate's conventions-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.conventions_ratchet_gate

`scripts/conventions_ratchet.py` is vendored and never edited here. It exits 0 when
no enabled rule has more hits in a file than the baseline allows, and 1 when a
count rose. Exit 2 is a bad table, baseline or argument. Exit 3 means the tracked
source tree was never fully read (git unusable, a file that cannot be read or does
not parse), which is its own failure state here -- NOT CONFIRMED, never a pass or
a skip: the unparsed file may hold the violation. The mapping lives only in this
wrapper so a test can pin it, and `verify-before-ship.ps1` calls the wrapper, not
the script.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "conventions_ratchet.py"

# Parsing the tracked tree takes a second or two; the bound only turns a hung
# child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a convention rule has more hits in a file than the baseline allows",
    2: "bad [conventions_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- a source file could not be read or parsed, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no convention hit above the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The conventions-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "conventions ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
