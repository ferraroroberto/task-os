"""The story tests' shot lists have to match the shots they actually save.

Every story e2e test opens with a module docstring listing the numbered proof
screenshots it produces, and the matching ``docs/validation/story-*.md``
record links them. Both are *claims*: nothing enforced that a listed file is
still written by a ``shot()`` call, so when #48 removed the per-hit Attach /
New-task buttons it silently orphaned ``story-10-search-3-desktop.png`` — the
step that produced it went away, the docstring line and the validation row
stayed, and the committed PNG kept its checkout mtime for a month while every
other shot in that story was regenerated (#184).

Two hermetic checks, no browser and no app:

* every shot a story docstring lists is produced by a ``shot()`` call in that
  same file — an orphan is a stale proof claim;
* every screenshot a validation record links exists on disk — retiring a shot
  has to take its rows with it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
VALIDATION_DIR = REPO_ROOT / "docs" / "validation"

# docstrings write runs and alternatives in brace shorthand, e.g.
# "story-04-triage-{1..8}-desktop.png" and "story-01-open-{1,2}-phone.png".
_BRACE = re.compile(r"^(.*?)\{([^}]*)\}(.*)$")
_SHOT_TOKEN = re.compile(r"story-[\w{}.,-]*\.png")
_MD_IMAGE_LINK = re.compile(r"\]\(([^)]*screenshots/[^)]+\.png)\)")


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
