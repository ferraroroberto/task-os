"""The archive lifecycle's declared states: the derive tables, the guards that
refuse an illegal move, and the restart that used to leave a run open forever.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import archive_store
from src import db as dbmod
from src.archive_batch import ArchiveBatchService, ArchiveError
from src.archive_state import (
    INTERRUPTED_ERROR,
    ItemState,
    ItemStatus,
    RunState,
    RunStatus,
    annotate_run,
    derive_item_state,
    derive_run_state,
)
from src.config import AIConfig, AppConfig
from tests.archive._support import _finished_run, client_for
from tests.fixtures.archiver_fake import build_fake_archiver

STATIC_JS = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "js"


def _service() -> ArchiveBatchService:
    """A service with no archiver behind it: enough for the guards and the sweep."""
    return ArchiveBatchService(AppConfig(ai=AIConfig(enabled=False)))


def _item(conn: sqlite3.Connection, run_id: int, status: ItemStatus, *, n: int = 1,
          files: list[str] | None = None, decided: bool = False,
          folder: str | None = "E:/archive/house") -> int:
    return archive_store.insert_item(
        conn, run_id, message_id=f"<{status.value}-{n}@example.invalid>", status=status.value,
        files_json=json.dumps(files or []), chosen_folder=folder,
        decided_at="2026-11-01T10:00:00" if decided else None,
    )


# ----------------------------------------------------------- the derive tables


@pytest.mark.parametrize(("status", "worker_alive", "expected"), [
    (RunStatus.RUNNING, True, RunState.RUNNING),
    # The honest new state: the row is open and nothing is going to close it.
    (RunStatus.RUNNING, False, RunState.INTERRUPTED),
    (RunStatus.DONE, False, RunState.DONE),
    (RunStatus.FAILED, False, RunState.FAILED),
    # The service closes the row a moment before it lets go of its lock.
    (RunStatus.DONE, True, RunState.DONE),
    (RunStatus.FAILED, True, RunState.FAILED),
])
def test_a_run_row_and_a_worker_derive_one_state(
    status: RunStatus, worker_alive: bool, expected: RunState
) -> None:
    assert derive_run_state({"status": status.value}, worker_alive) is expected


@pytest.mark.parametrize(("row", "expected"), [
    ({"status": "archived", "files": ["a.msg"]}, ItemState.ARCHIVED),
    ({"status": "moved", "files": ["a.msg"]}, ItemState.MOVED),
    ({"status": "needs_review", "files": [], "decided_at": None}, ItemState.NEEDS_REVIEW),
    ({"status": "needs_review", "files": [], "decided_at": "2026-11-01T10:00:00"}, ItemState.REVIEWED),
    ({"status": "failed", "files": ["a.msg"], "decided_at": None}, ItemState.FAILED_ON_DISK),
    # A failed row that was also accepted is still a failure; "seen" is not a state of its own here.
    ({"status": "failed", "files": ["a.msg"], "decided_at": "2026-11-01T10:00:00"}, ItemState.FAILED_ON_DISK),
    ({"status": "failed", "files": [], "decided_at": None}, ItemState.FAILED_CLEAN),
    ({"status": "failed", "files": ["a.msg"], "chosen_folder": None}, ItemState.FAILED_ON_DISK),
    ({"status": "reverted", "files": []}, ItemState.REVERTED),
])
def test_an_item_row_derives_one_state(row: dict[str, Any], expected: ItemState) -> None:
    assert derive_item_state(row) is expected


def test_annotate_run_adds_the_state_and_its_reason_and_keeps_every_field() -> None:
    stored = {"id": 3, "status": "running", "error": None, "planned": 0}
    live = annotate_run(stored, worker_alive=True)
    assert live == {**stored, "state": "running", "state_reason": None}
    dead = annotate_run(stored, worker_alive=False)
    assert dead["state"] == "interrupted" and dead["state_reason"] == INTERRUPTED_ERROR
    failed = annotate_run({"id": 4, "status": "failed", "error": "outlook is closed"}, worker_alive=False)
    assert (failed["state"], failed["state_reason"]) == ("failed", "outlook is closed")


# ------------------------------------------------- illegal moves are refused
# state-machine-proof: archive-run
def test_a_run_cannot_be_closed_in_a_state_the_table_does_not_store(conn: sqlite3.Connection) -> None:
    run = archive_store.create_run(conn)
    with pytest.raises(ValueError):
        archive_store.finish_run(conn, run["id"], status="interrupted")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        derive_run_state({"status": "interrupted"}, worker_alive=False)
    assert archive_store.get_run(conn, run["id"])["status"] == "running"


# state-machine-proof: archive-item
def test_an_action_a_state_does_not_allow_is_refused(conn: sqlite3.Connection) -> None:
    service = _service()
    run = archive_store.create_run(conn)
    clean = _item(conn, run["id"], ItemStatus.FAILED, n=1)
    waiting = _item(conn, run["id"], ItemStatus.NEEDS_REVIEW, n=2)
    gone = _item(conn, run["id"], ItemStatus.REVERTED, n=3)
    filed = _item(conn, run["id"], ItemStatus.ARCHIVED, n=4, files=["E:/archive/house/0001.msg"])

    def refused(call: Any, *args: Any) -> None:
        with pytest.raises(ArchiveError) as caught:
            call(conn, *args)
        assert caught.value.code == "archive_bad_state" and caught.value.http_status == 409

    refused(service.retry, clean)         # nothing on disk: re-deciding is a run's job
    refused(service.revert, clean)        # nothing to undo
    refused(service.revert, waiting)
    refused(service.revert, gone)
    refused(service.move, gone, "E:/archive/house")   # back in the Inbox: a fresh run owns it
    refused(service.accept, filed)        # finished, not reviewed
    refused(service.accept, gone)
    with pytest.raises(ValueError):
        derive_item_state({"status": "wiped", "files": []})


# ----------------------------------------------------------- the restart sweep


def test_a_restart_closes_the_run_it_interrupted_and_every_reader_agrees(
    conn: sqlite3.Connection,
) -> None:
    run = archive_store.create_run(conn)
    _item(conn, run["id"], ItemStatus.ARCHIVED, n=1, files=["E:/archive/house/0001.msg"])
    _item(conn, run["id"], ItemStatus.NEEDS_REVIEW, n=2)
    assert archive_store.get_run(conn, run["id"])["needs_review"] == 0   # the dead row's stale counter

    restarted = _service()   # the process came back; nothing drives the row
    before = restarted.annotate(archive_store.get_run(conn, run["id"]))
    assert before["state"] == "interrupted" and before["state_reason"] == INTERRUPTED_ERROR

    assert restarted.close_interrupted_runs() == [run["id"]]

    row = archive_store.get_run(conn, run["id"])
    assert (row["status"], row["error"]) == ("failed", INTERRUPTED_ERROR) and row["finished_at"]
    # The counters are the items' own, so the palette hint and the Settings head see them.
    assert (row["planned"], row["archived"], row["needs_review"], row["failed"]) == (2, 1, 1, 0)

    status_run = restarted.status(conn)["last_run"]
    listed = restarted.annotate(archive_store.list_runs(conn)[0])
    assert status_run == listed
    assert (listed["state"], listed["state_reason"]) == ("failed", INTERRUPTED_ERROR)
    assert restarted.status(conn)["running"] is False
    assert restarted.close_interrupted_runs() == []   # nothing left open


def test_the_sweep_leaves_a_live_run_alone_and_is_never_the_constructors_job(
    conn: sqlite3.Connection,
) -> None:
    run = archive_store.create_run(conn)
    # A CLI building the service to read a status must not close the app's live run.
    _service()
    assert archive_store.get_run(conn, run["id"])["status"] == "running"

    live = _service()
    assert live._lock.acquire(blocking=False)   # a worker holds the archiver
    live._active_run_id = run["id"]
    try:
        assert live.close_interrupted_runs() == []
        assert live.annotate(archive_store.get_run(conn, run["id"]))["state"] == "running"
    finally:
        live._active_run_id = None
        live._lock.release()
    assert archive_store.get_run(conn, run["id"])["status"] == "running"


def test_the_app_closes_a_run_the_last_process_left_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    dbmod.init_db()
    seed = dbmod.connect()
    try:
        run = archive_store.create_run(seed)   # the previous process died right here
    finally:
        seed.close()
    with client_for(tmp_path, monkeypatch, build_fake_archiver()) as api:
        runs = api.get("/api/archive/runs").json()["runs"]
        assert runs[0]["id"] == run["id"] and runs[0]["status"] == "failed"
        assert runs[0]["state"] == "failed" and runs[0]["state_reason"] == INTERRUPTED_ERROR
        status = api.get("/api/status").json()["archive"]
        assert status["running"] is False and status["last_run"]["state"] == "failed"


def test_the_api_adds_state_to_runs_and_items_and_keeps_every_field(api: TestClient) -> None:
    detail = _finished_run(api)
    assert (detail["status"], detail["state"], detail["state_reason"]) == ("done", "done", None)
    assert {i["status"]: i["state"] for i in detail["items"]} == {
        "archived": "archived", "needs_review": "needs_review",
    }
    unsure = next(i for i in detail["items"] if i["status"] == "needs_review")
    accepted = api.post(f"/api/archive/items/{unsure['id']}/accept").json()
    assert (accepted["status"], accepted["state"]) == ("needs_review", "reviewed")
    listed = api.get("/api/archive/runs").json()["runs"][0]
    assert listed["state"] == "done" and listed["planned"] == 2


# ------------------------------------------------------------ the JS mirror


def _js_table() -> dict[str, dict[str, str]]:
    source = (STATIC_JS / "archive" / "state.js").read_text(encoding="utf-8")
    table: dict[str, dict[str, str]] = {}
    for group in ("run", "item"):
        body = re.search(rf"\b{group}: \{{(.*?)\}}", source, re.DOTALL)
        assert body, f"state.js has no {group} table"
        table[group] = dict(re.findall(r"([A-Z_]+): '([a-z_]+)'", body.group(1)))
    return table


# state-machine-proof: archive-ui-state
def test_the_js_mirror_names_exactly_the_states_the_table_declares() -> None:
    """A state the mirror invents, or one it forgets, is drift this test refuses."""
    table = _js_table()
    assert table["run"] == {s.name: s.value for s in RunState}
    assert table["item"] == {s.name: s.value for s in ItemState}
