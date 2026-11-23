r"""Gate stage for the windows-only ratchet: run the vendored script, label its exit code.

    & .\.venv\Scripts\python.exe -m scripts.windows_only_ratchet_gate

Exit 3 from `scripts/windows_only_ratchet.py` means `git` could not list the tree or a test
module could not be read or parsed, so nothing was checked; it fails here as NOT CONFIRMED,
never a pass or a skip. The runner is `static_ratchet_gate.run_script`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "windows_only_ratchet.py"

# One `git ls-files` and an `ast` pass over the test modules takes seconds; the bound only
# turns a hung child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a file's count for a rule rose above the baseline, or the baseline is missing",
    2: "bad [windows_only_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- a test module could not be listed, read or parsed, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no unmarked Windows-only test beyond the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The windows-only-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "windows only ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
