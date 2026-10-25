r"""The gate's comment-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.comment_ratchet_gate

`scripts/comment_ratchet.py` is vendored and never edited here. It exits 0 when no
file has more issue references in its comments than the baseline allows, and 1 when
a count rose. Exit 2 is a bad table, baseline or argument. Exit 3 means the tracked
source tree was never fully scanned (git unusable, a file with an unterminated
string or comment, bytes that are not UTF-8), which is its own failure state here --
NOT CONFIRMED, never a pass or a skip: the unscanned file may hold the reference. The
mapping lives only in this wrapper so a test can pin it, and `verify-before-ship.ps1`
calls the wrapper, not the script.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "comment_ratchet.py"

# Scanning the tracked tree takes about a second; the bound only turns a hung child
# into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a file has more issue references in its comments than the baseline allows",
    2: "bad [comment_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- a source file could not be scanned, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no comment issue reference above the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The comment-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "comment ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
