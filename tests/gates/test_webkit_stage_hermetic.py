"""The gate's WebKit request-budget stage never writes into the tracked gallery.

The stage reruns the open story on WebKit, whose rendering differs from the
committed Chromium shots. Letting it save into ``docs/screenshots/`` and
restoring afterwards leaves the tree dirty whenever the run is cut short, and a
dirty tree cannot carry a gate evidence record. The stage therefore points the
``shots`` fixture at a temp folder and only checks that the gallery's own state
did not move.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.e2e._shots_dir import SHOTS_DIR_ENV, resolve_shots_dir

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GATE = REPO_ROOT / "scripts" / "verify-before-ship.ps1"


def _webkit_stage() -> str:
    text = GATE.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r">> request budget on webkit(.*?)# Runtime write probe, second half", text, re.DOTALL)
    assert match, "the gate lost its WebKit request-budget stage"
    return match.group(1)


def test_shots_fixture_honours_the_override(tmp_path: Path) -> None:
    default = tmp_path / "gallery"
    assert resolve_shots_dir({}, default) == default
    assert resolve_shots_dir({SHOTS_DIR_ENV: ""}, default) == default
    elsewhere = tmp_path / "scratch"
    assert resolve_shots_dir({SHOTS_DIR_ENV: str(elsewhere)}, default) == elsewhere


def test_webkit_stage_writes_its_shots_outside_the_tracked_gallery() -> None:
    stage = _webkit_stage()
    assert SHOTS_DIR_ENV in stage, "the WebKit stage must point the shots fixture at a temp folder"
    assert "checkout -- docs/screenshots" not in stage, (
        "restoring the gallery after the run destroys a deliberate re-baseline and leaves the tree "
        "dirty when the run is cut short; write elsewhere instead")
