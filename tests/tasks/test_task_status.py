"""The declared task status: the value set that refuses an unknown word, and the
browser's mirror of it."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from src import tasks_repo as repo
from src.schema import CLOSED_STATUSES, TASK_STATUSES, TaskStatus

STATIC_JS = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "js"


def test_the_status_tuples_are_derived_from_the_one_enum() -> None:
    assert TASK_STATUSES == tuple(s.value for s in TaskStatus)
    assert CLOSED_STATUSES == ("done", "cancelled")


# state-machine-proof: task-status
def test_a_status_outside_the_declared_set_is_refused_by_the_repo_and_the_column(conn: sqlite3.Connection) -> None:
    task = repo.create_task(conn, "A task")
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "Parked wrongly", status="paused")
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, task["id"], status="paused")
    assert repo.get_task(conn, task["id"])["status"] == TaskStatus.TODO
    # Past the repo, the column's own CHECK is the last guard.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tasks SET status = 'paused' WHERE id = ?", (task["id"],))


def _js_status_table() -> dict[str, str]:
    source = (STATIC_JS / "tasks" / "status.js").read_text(encoding="utf-8")
    body = re.search(r"\bStatus = \{(.*?)\}", source, re.DOTALL)
    assert body, "status.js has no Status table"
    return dict(re.findall(r"([A-Z_]+): '([a-z_]+)'", body.group(1)))


# state-machine-proof: task-status-ui
def test_the_js_mirror_names_exactly_the_statuses_the_enum_declares() -> None:
    """A status the mirror invents, or one it forgets, is drift this test refuses."""
    assert _js_status_table() == {s.name: s.value for s in TaskStatus}
    source = (STATIC_JS / "tasks" / "status.js").read_text(encoding="utf-8")
    closed = re.search(r"CLOSED_STATUSES = \[(.*?)\]", source)
    assert closed and re.findall(r"Status\.([A-Z_]+)", closed.group(1)) == [
        s.name for s in TaskStatus if s.value in CLOSED_STATUSES
    ]
