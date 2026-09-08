"""AI Inbox triage (#95): context, strict staging and explicit writes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src import tasks_repo as repo
from src.ai import AIClient, AIError
from src.ai.triage import (
    accept_suggestion,
    assemble_context,
    generate_suggestions,
    list_suggestions,
    reject_suggestion,
)
from src.config import AIConfig, AppConfig
from tests.fixtures.anthropic_fake import FakeAnthropic


class FakeAI:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls.append({"system": system, "user": json.loads(user), "max_tokens": max_tokens})
        return "```json\n" + json.dumps(self.payload) + "\n```"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True, "configured": True, "reachable": True,
            "reason": None, "model": "fake", "checked_at": None,
        }


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "tasks.db"
    dbmod.init_db(path)
    connection = dbmod.connect(path)
    try:
        yield connection
    finally:
        connection.close()


def _make_state(conn: sqlite3.Connection) -> dict[str, int]:
    project = repo.create_task(conn, "Home renovation")
    repo.create_task(conn, "Paint samples", parent_id=project["id"])
    person = repo.create_person(conn, "Sam")
    inbox = repo.create_task(
        conn, "Fix the bathroom tap", status="inbox", description="It is dripping."
    )
    return {"project": project["id"], "person": person["id"], "inbox": inbox["id"]}


@pytest.fixture
def triage_state(conn: sqlite3.Connection) -> dict[str, int]:
    return _make_state(conn)


def proposed(ids: dict[str, int]) -> dict[str, Any]:
    return {
        "suggestions": [{
            "task_id": ids["inbox"],
            "parent_id": ids["project"],
            "priority": "medium",
            "due": "2026-09-12",
            "person_id": ids["person"],
            "reason": "A small repair with a clear owner.",
        }]
    }


def test_context_is_compact_and_assembled_separately_from_prose(
    conn: sqlite3.Connection, triage_state: dict[str, int],
) -> None:
    rows, raw = assemble_context(conn)
    context = json.loads(raw)
    assert [row["id"] for row in rows] == [triage_state["inbox"]]
    assert context["inbox_tasks"] == [{
        "id": triage_state["inbox"],
        "title": "Fix the bathroom tap",
        "description": "It is dripping.",
        "current_due": None,
        "current_priority": "none",
        "current_person_id": None,
    }]
    assert context["projects"] == [{
        "id": triage_state["project"], "parent_id": None, "title": "Home renovation",
    }]
    assert context["people"] == [{"id": triage_state["person"], "name": "Sam"}]


def test_generation_stages_without_writing_and_replaces_only_the_pending_row(
    conn: sqlite3.Connection, triage_state: dict[str, int],
) -> None:
    before = repo.get_task(conn, triage_state["inbox"])
    fake = FakeAI(proposed(triage_state))
    first = generate_suggestions(conn, fake)
    after = repo.get_task(conn, triage_state["inbox"])
    assert after["parent_id"] == before["parent_id"]
    assert after["priority"] == before["priority"]
    assert after["due"] == before["due"]
    assert after["status"] == "inbox"
    assert len(first) == 1 and first[0]["parent"]["title"] == "Home renovation"
    fake.payload["suggestions"][0]["priority"] = "high"
    second = generate_suggestions(conn, fake)
    assert len(second) == 1
    assert second[0]["priority"] == "high"
    assert conn.execute("SELECT COUNT(*) FROM ai_suggestions").fetchone()[0] == 1
    assert len(fake.calls) == 2


def test_invalid_output_is_rejected_wholesale(
    conn: sqlite3.Connection, triage_state: dict[str, int],
) -> None:
    bad = proposed(triage_state)
    bad["suggestions"][0]["task_id"] = 999999
    with pytest.raises(AIError) as exc:
        generate_suggestions(conn, FakeAI(bad))
    assert exc.value.code == "ai_invalid_response"
    assert list_suggestions(conn) == []


def test_invalid_retry_does_not_erase_an_existing_pending_suggestion(
    conn: sqlite3.Connection, triage_state: dict[str, int],
) -> None:
    original = generate_suggestions(conn, FakeAI(proposed(triage_state)))[0]
    bad = proposed(triage_state)
    bad["suggestions"][0]["priority"] = "urgent"
    with pytest.raises(AIError):
        generate_suggestions(conn, FakeAI(bad))
    pending = list_suggestions(conn)
    assert len(pending) == 1
    assert pending[0]["id"] == original["id"]
    assert pending[0]["priority"] == "medium"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"extra": True}),
        lambda body: body["suggestions"][0].update(task_id=[]),
        lambda body: body["suggestions"][0].update(parent_id=True),
        lambda body: body["suggestions"][0].update(due="20260912"),
    ],
)
def test_wrong_json_shapes_are_reported_as_invalid_ai_responses(
    conn: sqlite3.Connection, triage_state: dict[str, int], mutate: Any,
) -> None:
    bad = proposed(triage_state)
    mutate(bad)
    with pytest.raises(AIError) as exc:
        generate_suggestions(conn, FakeAI(bad))
    assert exc.value.code == "ai_invalid_response"
    assert list_suggestions(conn) == []


def test_a_proposed_parent_cycle_is_rejected_wholesale(conn: sqlite3.Connection) -> None:
    project = repo.create_task(conn, "Inbox project", status="inbox")
    child = repo.create_task(conn, "Existing child", parent_id=project["id"])
    bad = {
        "suggestions": [{
            "task_id": project["id"], "parent_id": child["id"], "priority": "low",
            "due": None, "person_id": None, "reason": "Move under its own child.",
        }]
    }
    # Make the child a project too, so it is a permitted project id before
    # the ancestry guard proves that using it would form a cycle.
    repo.create_task(conn, "Grandchild", parent_id=child["id"])
    with pytest.raises(AIError) as exc:
        generate_suggestions(conn, FakeAI(bad), [project["id"]])
    assert exc.value.code == "ai_invalid_response"
    assert "cycle" in (exc.value.detail or "")
    assert list_suggestions(conn) == []


def test_accept_applies_every_field_moves_to_todo_and_logs_ai(
    conn: sqlite3.Connection, triage_state: dict[str, int],
) -> None:
    item = generate_suggestions(conn, FakeAI(proposed(triage_state)))[0]
    result = accept_suggestion(conn, item["id"])
    task = result["task"]
    assert (task["parent_id"], task["priority"], task["due"], task["person_id"], task["status"]) == (
        triage_state["project"], "medium", "2026-09-12", triage_state["person"], "todo",
    )
    changed = {row["field"]: row for row in task["activity"]}
    for field in ("parent", "priority", "due", "person_id", "status"):
        assert changed[field]["actor"] == "ai"
    assert result["suggestion"]["status"] == "accepted"


def test_reject_resolves_the_suggestion_without_touching_the_task(
    conn: sqlite3.Connection, triage_state: dict[str, int],
) -> None:
    item = generate_suggestions(conn, FakeAI(proposed(triage_state)))[0]
    before = repo.get_task(conn, triage_state["inbox"])
    rejected = reject_suggestion(conn, item["id"])
    after = repo.get_task(conn, triage_state["inbox"])
    assert rejected["status"] == "rejected"
    assert after["status"] == "inbox"
    assert after["activity"] == before["activity"]


def test_disabled_and_unreachable_are_distinct_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    disabled = AIClient(AppConfig(ai=AIConfig(enabled=False)))
    assert disabled.status()["reason"] == "disabled in config"
    unreachable = AIClient(AppConfig(ai=AIConfig(
        enabled=True, base_url="http://127.0.0.1:1", model="fake", timeout_seconds=1,
    )))
    monkeypatch.setattr("src.ai.client.PROBE_TIMEOUT_SECONDS", 0.01)
    status = unreachable.status()
    assert status["configured"] is True
    assert status["reachable"] is False
    assert status["reason"] == "local AI hub unavailable"


def test_client_uses_one_anthropic_messages_request() -> None:
    with FakeAnthropic(lambda _body: '{"ok":true}') as hub:
        client = AIClient(AppConfig(ai=AIConfig(
            enabled=True, base_url=hub.url, model="configured-model", timeout_seconds=2,
        )))
        assert client.complete(system="system", user="context", max_tokens=90) == '{"ok":true}'
        assert len(hub.requests) == 1
        sent = hub.requests[0]
        assert sent["model"] == "configured-model"
        assert sent["system"] == "system"
        assert sent["messages"] == [{"role": "user", "content": "context"}]
        assert sent["max_tokens"] == 90


def test_api_stages_accepts_and_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "api.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50100)) as client:
        with dbmod.connect(path) as connection:
            ids = _make_state(connection)
        client.app.state.ai = FakeAI(proposed(ids))
        staged = client.post("/api/ai/triage", json={})
        assert staged.status_code == 200
        item = staged.json()["items"][0]
        accepted = client.post(f"/api/ai/suggestions/{item['id']}/accept")
        assert accepted.status_code == 200
        assert accepted.json()["task"]["status"] == "todo"

        with dbmod.connect(path) as connection:
            other = repo.create_task(connection, "Sort the receipts", status="inbox")
        client.app.state.ai = FakeAI({"suggestions": [{
            "task_id": other["id"], "parent_id": None, "priority": "low", "due": None,
            "person_id": None, "reason": "A routine administration task.",
        }]})
        item = client.post("/api/ai/triage", json={}).json()["items"][0]
        rejected = client.post(f"/api/ai/suggestions/{item['id']}/reject")
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
