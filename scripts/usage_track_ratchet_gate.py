r"""Gate stage for the usage track ratchet: run the vendored script, label its exit code.

    & .\.venv\Scripts\python.exe -m scripts.usage_track_ratchet_gate

Exit 3 from `scripts/usage_track_ratchet.py` (with its reader `usage_track_scan.py`) means a
file was unreadable or its JS never closed, so nothing was checked; it fails here as NOT
CONFIRMED, never a pass or a skip. The runner is `static_ratchet_gate.run_script`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "usage_track_ratchet.py"

# A lexical pass over the tracked HTML and JS takes a few seconds; the bound only turns a
# hung child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a rule's hits rose above the baseline, the app does not reach its usage log, or the baseline is missing",
    2: "bad [usage_track_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- a file could not be read or closed, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no untracked control, sheet or built id beyond the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The usage-track-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "usage track ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
