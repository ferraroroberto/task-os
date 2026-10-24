r"""The gate's doc-refs-ratchet stage: run the vendored script, map its exit code.

    & .\.venv\Scripts\python.exe -m scripts.doc_refs_ratchet_gate

`scripts/doc_refs_ratchet.py` is vendored and never edited here. It exits 0 when
every path, module, relative link and loopback port that `README.md`,
`CLAUDE.md` and `docs/**/*.md` name resolves or is baselined, and 1 when a
dangling one is new. Exit 2 is a bad table, baseline or argument. Exit 3 means
the docs were never read (git unusable, a non-UTF-8 file, a fence that does not
close), which is its own failure state here -- NOT CONFIRMED, never a pass or a
skip. The mapping lives only in this wrapper so a test can pin it, and
`verify-before-ship.ps1` calls the wrapper, not the script.

Exit 0 only when the script exited 0; every other outcome exits 1 with its
reason on the last line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.static_ratchet_gate import REPO_ROOT, run_script

SCRIPT = REPO_ROOT / "scripts" / "doc_refs_ratchet.py"

# Reading the tracked docs takes a second; the bound only turns a hung child
# into NOT CONFIRMED instead of a stuck gate.
RUN_TIMEOUT_S = 300

_FAIL_LABELS = {
    1: "a doc names a path, module, link or port that does not exist",
    2: "bad [doc_refs_ratchet] table, baseline or arguments",
    3: "NOT CONFIRMED -- the docs could not be read, so nothing was checked",
}


def classify_exit(code: int) -> tuple[bool, str]:
    """`(ok, label)` for one script exit code. Only 0 passes."""
    if code == 0:
        return True, "no dangling doc reference above the baseline"
    return False, _FAIL_LABELS.get(code, f"unexpected exit {code}")


def run(script: Path = SCRIPT) -> int:
    """The doc-refs-ratchet stage: `script` judged by `classify_exit`."""
    return run_script(script, "doc-refs ratchet", classify_exit, RUN_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(run())
