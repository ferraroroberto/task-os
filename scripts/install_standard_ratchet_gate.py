r"""Gate stage for the install standard ratchet: run the vendored script, label its exit code.

    & .\.venv\Scripts\python.exe -m scripts.install_standard_ratchet_gate

Exit 3 from `scripts/install_standard_ratchet.py` means an installer module or the playbook
could not be read, or the migration parser did not load, so the pieces were not established;
it fails here as NOT CONFIRMED, never a pass or a skip. The runner is
`static_ratchet_gate.run_script`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "install_standard_ratchet.py"

# A handful of file reads takes well under a second; the bound only turns a hung child into
# NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a piece of the install standard is missing beyond the baseline, or the baseline is missing",
    2: "bad [install_standard_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- an installer module or the playbook could not be read, so nothing was established",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no missing install-standard piece beyond the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The install-standard-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "install standard ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
