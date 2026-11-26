"""The gate's e2e timing record lands in the primary checkout, from any checkout."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.e2e_record_path import record_path
from src.no_window import NO_WINDOW

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

RECORD = "data/e2e-junit.xml"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "core.hooksPath=", *args],
        cwd=cwd, capture_output=True, check=True, creationflags=NO_WINDOW, timeout=60,
    )


def test_a_linked_worktree_records_into_the_primary_checkout(tmp_path: Path) -> None:
    primary = (tmp_path / "repo").resolve()
    primary.mkdir()
    (primary / ".fleet.toml").write_text(f'[e2e]\njunit_xml = "{RECORD}"\n', encoding="utf-8")
    _git(primary, "init", "-q")
    _git(primary, "add", ".fleet.toml")
    _git(primary, "commit", "-q", "-m", "one")
    linked = (tmp_path / "repo-wt").resolve()
    _git(primary, "worktree", "add", "-q", "-b", "lane", str(linked))

    assert record_path(linked) == (primary / RECORD, "")
    assert record_path(primary) == (primary / RECORD, "")
    # the override keeps a run's writes inside its own tree
    assert record_path(linked, "data/own.xml") == (linked / "data" / "own.xml", "")


def test_without_a_primary_the_record_stays_local_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".fleet.toml").write_text(f'[e2e]\njunit_xml = "{RECORD}"\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))   # not a repository, whatever is above

    path, note = record_path(tmp_path)

    assert path == tmp_path / RECORD
    assert "not established" in note
