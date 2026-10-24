r"""The gate's structure-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.structure_ratchet_gate

`scripts/structure_ratchet.py` (vendored, never edited here) exits 0 on a pass
and 1 when a file, function or directory grew past the baseline, a `src/` file
imported `app/`, or a root folder is undeclared. It exits 2 on a bad table or
baseline, and 3 when it could not measure the tree: git unusable, a file it
cannot read or parse, or a `shape` it does not know. A 3 is "nothing was
checked", so the gate reports it as its own failure state, never as a pass or a
skip. The exit-code mapping lives only here so a test can pin it, and
`verify-before-ship.ps1` calls this wrapper instead of the script.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "structure_ratchet.py"

# Parsing a few hundred tracked files takes seconds; the bound only turns a
# hung child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a file, function or directory rose above the baseline, or the layout broke",
    2: "bad [structure_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- the tree could not be measured, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "nothing above the baseline and the layout matches the shape"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The structure-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "structure ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
