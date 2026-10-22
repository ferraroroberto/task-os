r"""The gate's docs-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.docs_ratchet_gate

`scripts/docs_ratchet.py` (vendored, never edited here) exits 0 on a pass, 1 when
a history marker or the README size rose above the baseline, 2 on a bad table or
baseline and 3 when it could not establish the count (git unusable, a file that
is not UTF-8, a fence or comment that never closes). Exit 3 means nothing was
checked, so it fails the gate as its own state and never reads as a pass or a
skip. This wrapper is the one place that mapping lives, so a test can pin it;
`verify-before-ship.ps1` calls the wrapper, never the script.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "docs_ratchet.py"

# A Markdown line scan over a few dozen files takes under a second; the bound
# only turns a hung child into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 120

_FAIL_LABELS = {
    1: "a history marker or the README size rose above the baseline",
    2: "bad [docs_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- the count could not be established, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no new history marker and the README within budget"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The docs-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "docs ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
