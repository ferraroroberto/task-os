"""The hand-drawn architecture diagram names only modules and services that exist.

``docs/architecture.mmd`` is Mermaid, outside the markdown doc-refs ratchet, so
a module or service that was deleted kept being drawn until a reader noticed.
This reads the diagram and fails on a ``name.py`` file or a ``...Service`` /
``...Client`` / ``...Scheduler`` class that is nowhere in the tree. Read-only.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIAGRAM = REPO_ROOT / "docs" / "architecture.mmd"
_ROOTS = ("src", "app", "scripts", "assets/opener", "tests/fixtures")
_MODULE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*\.py)\b")
_CLASS_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Service|Client|Scheduler))\b")


def _python_files() -> list[Path]:
    files = list(REPO_ROOT.glob("*.py"))
    for root in _ROOTS:
        files.extend((REPO_ROOT / root).rglob("*.py"))
    return files


def test_diagram_names_only_existing_modules_and_classes() -> None:
    text = DIAGRAM.read_text(encoding="utf-8")
    files = _python_files()
    file_names = {p.name for p in files}
    sources = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)

    missing_modules = sorted(m for m in set(_MODULE_RE.findall(text)) if m not in file_names)
    missing_classes = sorted(
        c for c in set(_CLASS_RE.findall(text)) if not re.search(rf"^class {c}\b", sources, re.MULTILINE)
    )

    assert not missing_modules, f"docs/architecture.mmd names modules that do not exist: {missing_modules}"
    assert not missing_classes, f"docs/architecture.mmd names classes that do not exist: {missing_classes}"
