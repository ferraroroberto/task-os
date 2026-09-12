"""The story tests' shot lists have to match the shots they actually save.

Every story e2e test opens with a module docstring listing the numbered proof
screenshots it produces, and the matching ``docs/validation/story-*.md``
record links them. Both are *claims*: nothing enforced that a listed file is
still written by a ``shot()`` call, so when #48 removed the per-hit Attach /
New-task buttons it silently orphaned ``story-10-search-3-desktop.png`` — the
step that produced it went away, the docstring line and the validation row
stayed, and the committed PNG kept its checkout mtime for a month while every
other shot in that story was regenerated (#184).

Three hermetic checks, no browser and no app:

* every shot a story docstring lists is produced by a ``shot()`` call in that
  same file — an orphan is a stale proof claim;
* every screenshot a validation record links exists on disk — retiring a shot
  has to take its rows with it;
* every committed screenshot is either produced by a ``shot()`` call or
  declared manual below — the direction the first two structurally cannot
  see (#216). A PNG nothing regenerates is invisible to them both: no
  docstring names it, its link resolves, and ``shot_determinism.py
  --check-tree`` only ever compares the files a run *rewrote*, so a shot
  frozen at its checkout mtime compares against nothing at all. That is how
  story 17's shots 2 and 3 sat in the gallery from the day they landed
  (``e8ccc86``) while shot 1 beside them was regenerated eight times.

Hand-captured evidence is legitimate and stays: a real-Chrome ``taskos://``
click, an editor window beside the app, a state a retired walk used to reach.
What is not legitimate is leaving it indistinguishable from what a run
reproduces — so it is declared here, with the reason, and the record that
links it says which of its shots a test writes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"
VALIDATION_DIR = REPO_ROOT / "docs" / "validation"

# docstrings write runs and alternatives in brace shorthand, e.g.
# "story-04-triage-{1..8}-desktop.png" and "story-01-open-{1,2}-phone.png".
_BRACE = re.compile(r"^(.*?)\{([^}]*)\}(.*)$")
_SHOT_TOKEN = re.compile(r"story-[\w{}.,-]*\.png")
_MD_IMAGE_LINK = re.compile(r"\]\(([^)]*screenshots/[^)]+\.png)\)")

#: Committed shots no ``shot()`` call produces, each with the reason the walk
#: cannot take it. The reason is the point: an entry here is a statement that
#: a human captured this once, not a way to silence the check.
MANUAL_SHOTS = {
    # Story 06 — the editor half of the mirror story: a text editor and the
    # app side by side in one 1920-wide screen capture, which no browser
    # context can frame.
    "story-06-mirror-6-desktop.png": "headed walk — Notepad beside the drawer, before the file save",
    "story-06-mirror-7-desktop.png": "headed walk — Notepad beside the drawer, after the file save",
    "story-06-mirror-8-desktop.png": "headed walk — the Settings card after the conflicting edit",
    # Story 09 — the `taskos://` hand-off leaves the browser entirely; an
    # automation-controlled session never reaches ShellExecute at all.
    "story-09-folders-8-desktop.png": "real Chrome on PC #1 — the page right after the chip click",
    "story-09-folders-9-desktop.png": "real Chrome on PC #1 — the Explorer window the opener opened",
    # Story 10 — the unconfigured-issues state, walked in real Chrome against
    # an instance whose `issues.provider` is blank.
    "story-10-search-8-desktop.png": "real Chrome — Issues 'not configured' under three populated groups",
    "story-10-search-9-desktop.png": "real Chrome — Settings → Search, 3 of 4 indexes",
    # Story 17 — `_walk_recurrence_anchor` rides inside the story-04 triage
    # test and saves shot 1 only; 2 and 3 are the headed walk's, and were
    # never produced by a test (`e8ccc86` added them alongside it).
    "story-17-recurrence-anchor-2-desktop.png": "headed walk — the monthly picker after switching the cadence",
    "story-17-recurrence-anchor-3-phone.png": "headed walk — the two controls at 390×844",
    # Story 21 — the file that produced these was retired in #159 when the
    # Archive tab landed and the on-screen half moved into story 24; the
    # record says so, and these stay as the 2026-09-07 evidence.
    "story-21-capture-1-desktop.png": "retired walk (#159) — the 2026-09-07 evidence, kept",
    "story-21-capture-2-desktop.png": "retired walk (#159) — the 2026-09-07 evidence, kept",
    "story-21-capture-3-desktop.png": "retired walk (#159) — the 2026-09-07 evidence, kept",
    "story-21-capture-4-desktop.png": "retired walk (#159) — the 2026-09-07 evidence, kept",
    "story-21-capture-5-phone.png": "retired walk (#159) — the 2026-09-07 evidence, kept",
    "story-21-capture-6-desktop.png": "retired walk (#159) — the 2026-09-07 evidence, kept",
}

#: Whole families that are manual by construction, so a new member needs no
#: edit here. `ux-round-*` records a design round: the shots are the judgement
#: being recorded, taken at the width and theme the owner reported, and the
#: tests each round adds live in the story files under their own names.
MANUAL_PREFIXES = {
    "ux-round-": "design-round records — hand-captured judgement shots, not story proof",
}


def _expand(token: str) -> set[str]:
    """Expand one brace shorthand token into the filenames it stands for."""
    m = _BRACE.match(token)
    if not m:
        return {token}
    pre, body, post = m.groups()
    if ".." in body:
        first, last = body.split("..", 1)
        parts = [str(n) for n in range(int(first), int(last) + 1)]
    else:
        parts = [p.strip() for p in body.split(",")]
    return {name for p in parts for name in _expand(pre + p + post)}


def _listed_shots(tree: ast.Module) -> set[str]:
    doc = ast.get_docstring(tree) or ""
    return {name for tok in _SHOT_TOKEN.findall(doc) for name in _expand(tok)}


def _saved_shots(tree: ast.Module) -> set[str]:
    """Filenames passed to a ``shot(...)`` call anywhere in the module."""
    saved: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "shot":
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                if inner.value.endswith(".png"):
                    saved.add(inner.value)
    return saved


def _all_saved_shots() -> set[str]:
    """Every filename any e2e module saves — helpers and sweeps included.

    Wider than ``STORY_TESTS`` on purpose: the question this answers is "does
    *anything* in the suite write this file", so a shot moved into a shared
    helper must not read as an orphan.
    """
    saved: set[str] = set()
    for path in sorted(E2E_DIR.glob("*.py")):
        saved |= _saved_shots(ast.parse(path.read_text(encoding="utf-8")))
    return saved


STORY_TESTS = sorted(E2E_DIR.glob("test_story_*.py"))


def test_story_tests_exist() -> None:
    """Guard the guard: a glob that matches nothing would pass vacuously."""
    assert STORY_TESTS, f"no story tests under {E2E_DIR}"


@pytest.mark.parametrize("path", STORY_TESTS, ids=lambda p: p.name)
def test_docstring_shot_list_is_produced(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    orphans = sorted(_listed_shots(tree) - _saved_shots(tree))
    assert not orphans, (
        f"{path.name}'s docstring lists {orphans}, which no shot() call in that "
        "file produces: either the step that saved it is gone (retire the line, "
        "the committed PNG and the validation row) or a shot() call was lost."
    )


def test_validation_records_link_existing_screenshots() -> None:
    records = sorted(VALIDATION_DIR.glob("*.md")) + [REPO_ROOT / "docs" / "validation.md"]
    missing = [
        f"{record.relative_to(REPO_ROOT)} → {link}"
        for record in records
        for link in _MD_IMAGE_LINK.findall(record.read_text(encoding="utf-8"))
        if not (record.parent / link).resolve().exists()
    ]
    assert not missing, f"validation records link screenshots that are not committed: {missing}"


def test_every_committed_shot_is_produced_or_declared_manual() -> None:
    """No committed shot may be silently unregenerated (#216)."""
    committed = {path.name for path in SHOTS_DIR.glob("*.png")}
    assert committed, f"no screenshots under {SHOTS_DIR}"
    unaccounted = sorted(
        name
        for name in committed - _all_saved_shots()
        if name not in MANUAL_SHOTS
        and not any(name.startswith(prefix) for prefix in MANUAL_PREFIXES)
    )
    assert not unaccounted, (
        f"committed screenshots that no shot() call produces: {unaccounted}. "
        "Either the walk that saved them was lost (restore the step), or they "
        "are hand-captured evidence — in which case declare each in "
        "MANUAL_SHOTS with the reason, and say so in the validation record "
        "that links them, so a reader can tell proof a run reproduces from "
        "proof a human took once."
    )


def test_manual_shot_declarations_are_current() -> None:
    """A declaration outliving what it describes is the same stale claim."""
    saved = _all_saved_shots()
    gone = sorted(name for name in MANUAL_SHOTS if not (SHOTS_DIR / name).exists())
    now_automated = sorted(name for name in MANUAL_SHOTS if name in saved)
    empty_prefixes = sorted(
        prefix
        for prefix in MANUAL_PREFIXES
        if not any(path.name.startswith(prefix) for path in SHOTS_DIR.glob("*.png"))
    )
    assert not gone, f"MANUAL_SHOTS names screenshots that are not committed: {gone}"
    assert not now_automated, (
        f"MANUAL_SHOTS still calls these hand-captured, but a shot() call now "
        f"writes them: {now_automated} — drop the entry."
    )
    assert not empty_prefixes, (
        f"MANUAL_PREFIXES covers nothing on disk: {empty_prefixes} — the family "
        "is gone, so the exemption should be too."
    )
