"""``scripts/import_notion.py`` on the synthetic export ``tests/fixtures/notion_export.json``.

Eight invented pages cover every mapping rule (status × priority × recurrence,
null status → todo / inbox, backlog → priority none, Date with a time and a
range, link, body blocks of every handled kind + one unknown, comments out of
created order + an empty one + one without ``display_name``, one / three
relations, an unresolved person). No API call is made anywhere in this file.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import import_notion as imp
from src import db as dbmod
from src import schema
from src import tasks_repo as repo

FIXTURE = Path(__file__).parent / "fixtures" / "notion_export.json"
P = {n: f"page-000{n}-0000-0000-0000-00000000000{n}" for n in range(1, 9)}


@pytest.fixture
def export() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    return path


def _counts(path: Path) -> dict[str, int]:
    conn = dbmod.connect(path)
    try:
        return repo.counts(conn)
    finally:
        conn.close()


def _run(*argv: str) -> int:
    return imp.main(list(argv))


def _by_ext(conn: sqlite3.Connection, n: int) -> dict:
    row = repo.find_by_external_id(conn, "tasks", P[n])
    assert row is not None
    return repo.get_task(conn, row["id"])


# ----------------------------------------------------------------- mapping


@pytest.mark.parametrize(
    ("status", "priority", "expected"),
    [
        ("not started", None, "todo"),
        ("In progress", None, "doing"),
        ("Done", None, "done"),
        (None, None, "todo"),
        (None, "inbox", "inbox"),
        (None, "high", "todo"),
        ("Blocked", None, "todo"),  # unmapped → default, reported
    ],
)
def test_status_mapping(status: str | None, priority: str | None, expected: str) -> None:
    got, unmapped = imp.map_status(status, priority)
    assert got == expected
    assert (unmapped is not None) == (status == "Blocked")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("high", "high"), ("medium", "medium"), ("low", "low"), ("backlog", "none"), ("inbox", "none"), (None, "none"), ("urgent", "none")],
)
def test_priority_mapping(value: str | None, expected: str) -> None:
    got, unmapped = imp.map_priority(value)
    assert got == expected
    assert (unmapped is not None) == (value == "urgent")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("daily", "daily"), ("weekly", "weekly"), ("monthly", "monthly"), ("three months", "quarterly"), ("yearly", "yearly"), (None, None), ("fortnightly", None)],
)
def test_recurrence_mapping(value: str | None, expected: str | None) -> None:
    got, unmapped = imp.map_recurrence(value)
    assert got == expected
    assert (unmapped is not None) == (value == "fortnightly")


def test_blocks_to_markdown(export: dict) -> None:
    blocks = export["pages"][4]["blocks"]  # the sailing book page
    text, seen = imp.blocks_to_markdown(blocks)
    assert text.splitlines() == [
        "1. chapter one", "2. chapter two", "- [x] take notes", "- [ ] lend it on",
        "> the sea is calm", "  said the skipper", "```python", "print('ahoy')", "```",
        "![cover](https://example.com/cover.png)", "[image]", "---", "> remember the tide tables",
        "| chapter | pages |", "| --- | --- |", "| one | 12 |",
    ]
    assert seen["unknown:video"] == 1
    assert seen["image"] == 2 and seen["table"] == 1 and seen["paragraph"] == 1  # nested child counted


def test_map_export_covers_every_rule(export: dict) -> None:
    mapped = {m.external_id: m for m in imp.map_export(export)}
    assert len(mapped) == 8

    hose = mapped[P[1]]
    assert (hose.status, hose.priority, hose.recurrence, hose.due) == ("todo", "high", None, "2026-09-01")
    assert hose.link == "https://example.com/hose"
    assert hose.person == ("person-aaaa-0000-0000-0000-000000000001", "Sam Rivera")
    assert [c.body for c in hose.comments] == [
        "Measured the garden: 22 m", "Compare prices at the two shops", "Ordered the 25 m one",
    ]  # sorted by created_time although the API returned them out of order
    assert hose.description.startswith("## Why\n")

    assert (mapped[P[2]].status, mapped[P[2]].recurrence) == ("todo", "weekly")
    assert (mapped[P[3]].status, mapped[P[3]].priority) == ("inbox", "none")

    door = mapped[P[4]]
    assert (door.status, door.priority) == ("done", "low")
    assert door.done_at == imp.local_iso("2026-05-20T18:45:00.000Z")
    assert door.created_at == imp.local_iso("2026-05-02T07:00:00.000Z")
    assert [c.author for c in door.comments] == ["Sam Rivera", "notion"]  # no display_name → "notion"

    sailing = mapped[P[5]]
    assert (sailing.status, sailing.priority, sailing.recurrence) == ("doing", "none", "quarterly")

    picnic = mapped[P[6]]
    assert picnic.person[1] == "Sam Rivera"
    assert [n for _, n in picnic.also_linked] == ["Alex Chen", "Jordan Lee"]
    assert picnic.recurrence == "daily"

    untitled = mapped[P[7]]
    assert untitled.title == "(untitled)"
    assert (untitled.status, untitled.priority, untitled.recurrence) == ("todo", "none", None)
    kinds = {k for k, _ in untitled.notes}
    assert {"empty title", "unmapped status", "unmapped priority", "unmapped recurrent", "empty comment"} <= kinds
    assert untitled.comments == []  # the empty comment is skipped

    yearly = mapped[P[8]]
    assert (yearly.due, yearly.recurrence) == ("2026-12-01", "yearly")  # time + range → date part
    assert yearly.person is None and ("person unresolved", "GET /pages/… → 404: object_not_found") in yearly.notes
    assert yearly.comments[0].body == "[See the comparison table](https://example.com/compare)"

    summary = imp.summarize(mapped.values())
    assert summary["pages"] == 8
    assert summary["status"] == {"todo": 5, "doing": 1, "done": 1, "inbox": 1}
    assert summary["priority"] == {"none": 5, "high": 1, "low": 1, "medium": 1}
    assert summary["recurrence"] == {"none": 4, "weekly": 1, "quarterly": 1, "daily": 1, "yearly": 1}
    assert summary["comments_total"] == 6 and summary["longest_thread"] == 3
    assert summary["unmapped_values"] == {
        "unmapped status": ["Blocked"], "unmapped priority": ["urgent"],
        "unmapped recurrent": ["fortnightly"], "unknown block": ["video"],
    }
    # counts only — nothing from the pages leaks into the report
    assert "garden" not in json.dumps(summary) and "Sam" not in json.dumps(summary)


# ------------------------------------------------------------------- write


def test_import_writes_tasks_comments_people_links(db: Path) -> None:
    assert _run("--from-json", str(FIXTURE), "--db", str(db)) == 0
    assert _counts(db) == {"tasks": 8, "people": 1, "comments": 8, "links": 2, "activity": 8, "issue_refs": 0}
    conn = dbmod.connect(db)
    try:
        hose = _by_ext(conn, 1)
        assert hose["status"] == "todo" and hose["priority"] == "high" and hose["due"] == "2026-09-01"
        assert hose["person"]["name"] == "Sam Rivera"
        assert hose["created_at"] == imp.local_iso("2026-06-01T08:00:00.000Z")
        assert hose["updated_at"] == imp.local_iso("2026-06-10T09:30:00.000Z")
        assert [link["url"] for link in hose["links"]] == ["https://example.com/hose"]
        assert [(c["author"], c["body"], c["origin"]) for c in hose["comments"]] == [
            ("Sam Rivera", "Measured the garden: 22 m", "notion"),
            ("Alex Chen", "Compare prices at the two shops", "notion"),
            ("Sam Rivera", "Ordered the 25 m one", "notion"),
        ]
        assert [c["ts"] for c in hose["comments"]] == sorted(c["ts"] for c in hose["comments"])
        assert [(a["actor"], a["field"], a["new_value"]) for a in hose["activity"]] == [
            ("notion-import", "imported", P[1]),
        ]  # ONE row per task, not one per field
        assert hose["external_id"] == P[1]

        door = _by_ext(conn, 4)
        assert door["status"] == "done" and door["done_at"] == imp.local_iso("2026-05-20T18:45:00.000Z")

        picnic = _by_ext(conn, 6)
        assert picnic["person"]["name"] == "Sam Rivera"
        assert [c["body"] for c in picnic["comments"]] == ["also linked: Alex Chen", "also linked: Jordan Lee"]
        assert {c["author"] for c in picnic["comments"]} == {"notion-import"}

        person = repo.find_by_external_id(conn, "people", "person-aaaa-0000-0000-0000-000000000001")
        assert person and person["name"] == "Sam Rivera"
        assert repo.list_people(conn)[0]["open_tasks"] == 2
        assert conn.execute("SELECT COUNT(*) FROM activity WHERE actor != 'notion-import'").fetchone()[0] == 0
    finally:
        conn.close()


def test_import_is_idempotent(db: Path) -> None:
    _run("--from-json", str(FIXTURE), "--db", str(db))
    first = _counts(db)
    conn = dbmod.connect(db)
    snapshot = conn.execute("SELECT id, title, status, priority, due, updated_at, done_at FROM tasks ORDER BY id").fetchall()
    conn.close()

    assert _run("--from-json", str(FIXTURE), "--db", str(db)) == 0
    assert _counts(db) == first
    conn = dbmod.connect(db)
    try:
        assert conn.execute("SELECT id, title, status, priority, due, updated_at, done_at FROM tasks ORDER BY id").fetchall() == snapshot
        assert conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 8
    finally:
        conn.close()


def test_reimport_applies_source_changes_without_duplicates(db: Path, export: dict, tmp_path: Path) -> None:
    _run("--from-json", str(FIXTURE), "--db", str(db))

    hose = export["pages"][0]
    hose["page"]["properties"]["status"]["status"] = {"id": "x", "name": "Done", "color": "green"}
    hose["page"]["last_edited_time"] = "2026-07-01T10:00:00.000Z"
    hose["comments"].append({
        "object": "comment", "id": "c1-4", "parent": {"type": "page_id", "page_id": P[1]},
        "created_time": "2026-06-04T10:00:00.000Z", "last_edited_time": "2026-06-04T10:00:00.000Z",
        "created_by": {"object": "user", "id": "user-1"},
        "rich_text": [{"type": "text", "plain_text": "Installed, works", "href": None, "text": {"content": "Installed, works", "link": None}}],
        "display_name": {"type": "user", "resolved_name": "Sam Rivera"},
    })
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(export), encoding="utf-8")

    assert _run("--from-json", str(changed), "--db", str(db)) == 0
    assert _counts(db)["tasks"] == 8 and _counts(db)["comments"] == 9
    conn = dbmod.connect(db)
    try:
        t = _by_ext(conn, 1)
        assert t["status"] == "done"
        assert t["done_at"] == imp.local_iso("2026-07-01T10:00:00.000Z")
        assert [c["body"] for c in t["comments"]][-1] == "Installed, works"
        fields = [(a["field"], a["old_value"], a["new_value"]) for a in t["activity"]]
        assert fields[0] == ("status", "todo", "done")  # a genuine change is logged per field
        assert fields[-1] == ("imported", None, P[1])
    finally:
        conn.close()


def test_dry_run_writes_nothing(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert not db.exists()
    assert _run("--from-json", str(FIXTURE), "--db", str(db), "--dry-run") == 0
    assert not db.exists()  # not even created / migrated
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "tasks create 8" in out

    _run("--from-json", str(FIXTURE), "--db", str(db))
    before = _counts(db)
    mtime = db.stat().st_mtime_ns
    assert _run("--from-json", str(FIXTURE), "--db", str(db), "--dry-run") == 0
    out = capsys.readouterr().out
    assert "unchanged 8" in out and "comments add 0" in out
    assert _counts(db) == before and db.stat().st_mtime_ns == mtime


def test_limit_and_json_dump_roundtrip(db: Path, tmp_path: Path, export: dict) -> None:
    dump = tmp_path / "dump.json"
    assert _run("--from-json", str(FIXTURE), "--db", str(db), "--limit", "3", "--json-dump", str(dump)) == 0
    assert _counts(db)["tasks"] == 3
    assert json.loads(dump.read_text(encoding="utf-8")) == export


# --------------------------------------------------------------- migration


def test_migration_v3_upgrades_v2_and_is_idempotent(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript("BEGIN;" + schema.MIGRATIONS[1] + schema.MIGRATIONS[2] + "INSERT INTO settings VALUES ('schema_version', '2'); COMMIT;")
    conn.execute("INSERT INTO tasks(title, created_at, updated_at) VALUES ('old', 't', 't')")
    conn.commit()
    conn.close()

    assert dbmod.init_db(db) == schema.SCHEMA_VERSION
    conn = dbmod.connect(db)
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert "external_id" in cols
        assert "external_id" in {r["name"] for r in conn.execute("PRAGMA table_info(comments)")}
        assert conn.execute("SELECT external_id FROM tasks WHERE title = 'old'").fetchone()[0] is None
        n = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        assert schema.migrate(conn) == schema.SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == n
        conn.execute("INSERT INTO tasks(title, created_at, updated_at, external_id) VALUES ('a', 't', 't', 'x')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks(title, created_at, updated_at, external_id) VALUES ('b', 't', 't', 'x')")
    finally:
        conn.close()
