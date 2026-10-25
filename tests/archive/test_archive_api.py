"""Batch archiving's routes: the run, the per-item actions, the unconfigured
install and the sample config, through the real app.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import archive_store
from src import db as dbmod
from tests.archive._support import (
    ARCHIVED_FILE,
    _finished_run,
    client_for,
)
from tests.fixtures.archiver_fake import (
    FOLDER_BILLS,
    FOLDER_HOUSE,
    apply_doc,
    apply_result,
    build_fake_archiver,
    candidate,
    mail,
    plan_doc,
)


def test_the_run_route_answers_202_and_the_work_lands(api: TestClient) -> None:
    run = _finished_run(api)
    assert run["status"] == "done" and (run["planned"], run["archived"]) == (2, 1)
    assert {i["status"] for i in run["items"]} == {"archived", "needs_review"}

    listed = api.get("/api/archive/runs").json()
    assert listed["count"] == 1 and listed["runs"][0]["id"] == run["id"]
    assert api.get("/api/archive/runs/999").status_code == 404


def test_the_item_routes_revert_and_review(api: TestClient) -> None:
    run = _finished_run(api)
    filed = next(i for i in run["items"] if i["status"] == "archived")
    unsure = next(i for i in run["items"] if i["status"] == "needs_review")

    assert api.post(f"/api/archive/items/{unsure['id']}/accept").json()["decided_at"]
    refused = api.post(f"/api/archive/items/{filed['id']}/accept")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "archive_bad_state"

    reverted = api.post(f"/api/archive/items/{filed['id']}/revert")
    assert reverted.status_code == 200 and reverted.json()["status"] == "reverted"

    again = api.post(f"/api/archive/items/{filed['id']}/revert")
    assert again.status_code == 409 and again.json()["error"]["code"] == "archive_bad_state"

    missing = api.post("/api/archive/items/999/revert")
    assert missing.status_code == 404


def test_the_retry_route_finishes_a_stuck_mail_and_refuses_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /api/archive/items/{id}/retry` — the whole route, over the app (#174)."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("api-stuck@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("api-unsure@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.1)]),
        ])],
        apply=[
            apply_doc([apply_result(
                "api-stuck@example.invalid", FOLDER_HOUSE, ok=False, files=[ARCHIVED_FILE],
                error={"code": "move_failed", "message": "the message has been changed"},
            )]),
            apply_doc([apply_result(
                "api-stuck@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE], sequence="",
                reused=True, move_via="saved_retry",
            )]),
        ],
    )
    with client_for(tmp_path, monkeypatch, repo) as client:
        run = _finished_run(client)
        stuck = next(i for i in run["items"] if i["status"] == "failed")
        unsure = next(i for i in run["items"] if i["status"] == "needs_review")

        finished = client.post(f"/api/archive/items/{stuck['id']}/retry")
        assert finished.status_code == 200
        body = finished.json()
        assert body["status"] == "archived" and body["files"] == [ARCHIVED_FILE]
        assert body["error"] is None and body["decided_at"]

        # It is finished now, so the screen stops offering it — and the API
        # agrees, through the one envelope.
        again = client.post(f"/api/archive/items/{stuck['id']}/retry")
        assert again.status_code == 409 and again.json()["error"]["code"] == "archive_bad_state"
        refused = client.post(f"/api/archive/items/{unsure['id']}/retry")
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "archive_bad_state"
        assert client.post("/api/archive/items/999/retry").status_code == 404


@pytest.mark.parametrize("spell", ["body", "query"])
def test_a_bounded_first_run_rides_the_body_or_the_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spell: str
) -> None:
    """Both spellings reach the service: the first real run is one mail."""
    three = plan_doc([
        mail(f"cap{n}@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.95)])
        for n in range(3)
    ])
    repo = build_fake_archiver(
        tmp_path / "archiver", plan=[three],
        apply=[apply_doc([apply_result("cap0@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
    )
    with client_for(tmp_path, monkeypatch, repo) as client:
        if spell == "body":
            started = client.post("/api/archive/run", json={"limit": 1})
        else:
            started = client.post("/api/archive/run?limit=1")
        assert started.status_code == 202
        client.app.state.archive.stop(timeout=30)
        run = client.get(f"/api/archive/runs/{started.json()['id']}").json()
        assert (run["planned"], run["archived"]) == (1, 1)
        assert [i["message_id"] for i in run["items"]] == ["cap0@example.invalid"]

        refused = client.post("/api/archive/run", json={"limit": 0})
        assert refused.status_code == 422


def test_the_hint_rides_the_accept_body_into_the_correction(api: TestClient) -> None:
    """What the report screen (#159) sends when you explain a correction (#158)."""
    run = _finished_run(api)
    unsure = next(i for i in run["items"] if i["status"] == "needs_review")

    accepted = api.post(
        f"/api/archive/items/{unsure['id']}/accept", json={"hint": "utility mail goes here"},
    )
    assert accepted.status_code == 200 and accepted.json()["decided_at"]

    conn = dbmod.connect()
    try:
        stored = archive_store.recent_corrections(conn)
    finally:
        conn.close()
    assert len(stored) == 1 and stored[0]["hint"] == "utility mail goes here"
    assert stored[0]["chosen_folder"] == FOLDER_BILLS

    # Still optional: the body may be absent altogether, as it was before #158.
    assert api.post(f"/api/archive/items/{unsure['id']}/accept").status_code == 200


def test_an_unconfigured_install_says_so_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout without the archiver: 409 with the reason, never a silent no-op."""
    with client_for(tmp_path, monkeypatch, None) as client:
        status = client.get("/api/status").json()["archive"]
        assert status["configured"] is False and "disabled in config" in status["reason"]
        assert status["last_run"] is None

        refused = client.post("/api/archive/run")
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "archive_disabled"
        assert "disabled in config" in refused.json()["error"]["message"]
        # Reading a past run never needs the archiver on this machine.
        assert client.get("/api/archive/runs").json() == {"runs": [], "count": 0}


def test_the_sample_config_never_arms_the_real_archiver() -> None:
    """The committed sample documents the block and keeps it off (#157).

    A fresh clone, a git worktree and the disposable e2e instance all boot on
    this file; none of them may drive this machine's Outlook.
    """
    raw = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "config.sample.json").read_text("utf-8")
    )
    assert raw["archive"]["enabled"] is False
    assert set(raw["archive"]) == {
        "enabled", "repo", "python", "candidates", "confidence_threshold", "timeout_seconds",
        "model", "batch_size", "examples", "ai_timeout_seconds", "renumber",
    }
    # On by default: the renaming is the archiver's repair of a folder this
    # app's own filing left ragged, and every path it renames is healed here.
    assert raw["archive"]["renumber"] is True
    # The ranking's own model and its own request bound, never ai.model /
    # ai.timeout_seconds: two features, two jobs, two very different request
    # lengths (#158).
    assert raw["archive"]["model"] == "claude_haiku"
    assert (raw["archive"]["batch_size"], raw["archive"]["examples"]) == (8, 20)
    assert raw["archive"]["ai_timeout_seconds"] == 180
