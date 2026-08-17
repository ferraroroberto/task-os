"""Quick-add parser — the one syntax the UI bar and the API's ``/api/parse`` share."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src import tasks_repo as repo
from src.db import connect, init_db
from src.quick_add import parse, resolve_parent

MONDAY = date(2026, 8, 17)


@pytest.mark.parametrize(
    ("text", "title", "due", "phrase", "parent_ref"),
    [
        ("renew passport next friday", "renew passport", "2026-08-28", "next friday", None),
        ("pay water bill by tomorrow", "pay water bill", "2026-08-18", "by tomorrow", None),
        ("write sensor driver in 2 weeks", "write sensor driver", "2026-08-31", "in 2 weeks", None),
        ("call fri", "call", "2026-08-21", "fri", None),
        ("x 2026-09-01", "x", "2026-09-01", "2026-09-01", None),
        ("order sensor #12", "order sensor", None, None, {"id": 12}),
        ("order sensor tomorrow #12", "order sensor", "2026-08-18", "tomorrow", {"id": 12}),
        ("order sensor › garden-bot", "order sensor", None, None, {"title": "garden-bot"}),
        ("fix tap > Bathroom tomorrow", "fix tap", "2026-08-18", "tomorrow", {"title": "Bathroom"}),
        ("buy milk", "buy milk", None, None, None),
        # a lone date word is a title, never an empty task with a due
        ("tomorrow", "tomorrow", None, None, None),
        ("   spaced   out   text  ", "spaced out text", None, None, None),
    ],
)
def test_parse(text: str, title: str, due: str | None, phrase: str | None, parent_ref: dict | None) -> None:
    got = parse(text, MONDAY)
    assert got == {"title": title, "due": due, "due_phrase": phrase, "parent_ref": parent_ref}


def test_resolve_parent(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    init_db(path)
    conn = connect(path)
    try:
        home = repo.create_task(conn, "Home renovation")["id"]
        kitchen = repo.create_task(conn, "Kitchen", parent_id=home)["id"]
        repo.create_task(conn, "Kitchen table", status="done")
        assert resolve_parent(conn, None) is None
        assert resolve_parent(conn, {"id": home}) == {"id": home, "title": "Home renovation"}
        assert resolve_parent(conn, {"id": 999}) is None
        # exact (case-insensitive) title wins over a substring hit
        assert resolve_parent(conn, {"title": "kitchen"}) == {"id": kitchen, "title": "Kitchen"}
        # substring match works, closed tasks are never picked
        assert resolve_parent(conn, {"title": "renov"}) == {"id": home, "title": "Home renovation"}
        assert resolve_parent(conn, {"title": "nothing like this"}) is None
    finally:
        conn.close()
