"""``src/imports/sharepoint.py`` on the synthetic dump ``tests/fixtures/sharepoint_export.json``.

Four invented items cover every rule: a threaded item with out-of-order
comments, an empty comment, an append column that grows over three versions,
a URL in text and an attachment; a done item with a suffix-stacked append
column and two contacts; an item with unmapped status / priority / owner and a
rewritten append column; an item with no title. Nothing here touches a network.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src import db as dbmod
from src import schema
from src import tasks_repo as repo
from src.imports import sharepoint as imp

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "sharepoint_export.json"
MAPPING = ROOT / "config" / "sharepoint-mapping.sample.json"
LIST_ID = "00000000-0000-0000-0000-000000000000"
MEMBERS = ["p1", "p2"]


@pytest.fixture
def dump() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    return path


def _mapped(dump: dict) -> list[imp.MappedTask]:
    return imp.map_dump(dump, imp.load_mapping(MAPPING), MEMBERS)


def _run(db: Path, *extra: str) -> int:
    return imp.main(["--from-json", str(FIXTURE), "--mapping", str(MAPPING), "--db", str(db), *extra])


def _task(conn: sqlite3.Connection, item_id: int) -> dict:
    row = repo.find_by_external_id(conn, "tasks", f"sharepoint:{LIST_ID}:{item_id}")
    assert row is not None
    return repo.get_task(conn, row["id"])


def _snapshot(path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        return {
            t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
            for t in ("tasks", "comments", "links", "activity", "people")
        }
    finally:
        conn.close()


# ----------------------------------------------------------------- mapping


def test_item_fields_map_through_the_mapping_file(dump: dict) -> None:
    first, done, odd, bare = _mapped(dump)
    assert (first.status, first.priority, first.due) == ("todo", "high", "2026-02-01")
    assert first.owner is None                                  # Person A → p1, the install owner: NULL
    assert first.person == (f"sharepoint:{LIST_ID}:person:contact x", "Contact X")
    assert first.description == "Outline first, then review at https://docs.example/plan."
    assert first.external_id == f"sharepoint:{LIST_ID}:1"
    assert (done.status, done.owner, done.done_at) == ("done", "p2", done.updated_at)
    assert ("extra people", "first kept") in done.notes
    assert (odd.status, odd.priority, odd.owner, odd.done_at) == ("todo", "none", None, None)
    assert {("unmapped status", "On hold"), ("unmapped priority", "(9) Odd"), ("unmapped owner", "Person Z")} <= set(odd.notes)
    assert (bare.title, bare.status) == ("(untitled)", "todo")


def test_comments_run_oldest_first_with_each_reply_after_its_parent(dump: dict) -> None:
    first = _mapped(dump)[0]
    ids = [c.external_id.removeprefix(f"sharepoint:{LIST_ID}:1:") for c in first.comments]
    # a SharePoint thread (Jan 10 → its replies by date → Jan 12), version entries interleaved by date
    thread = [i for i in ids if i.startswith("c")]
    assert thread == ["c11", "c11:r13", "c11:r14", "c12"]
    assert [c.ts for c in first.comments] == sorted(c.ts for c in first.comments)
    assert not any(c.body.strip() == "" for c in first.comments)           # the blank comment is skipped
    assert ("empty comment", "skipped") in first.notes


def test_append_column_becomes_one_comment_per_version_holding_only_the_new_text(dump: dict) -> None:
    first, done, odd, _ = _mapped(dump)
    versions = [c for c in first.comments if ":vUpdates:" in c.external_id]
    assert [(c.author, c.body) for c in versions] == [
        ("Person A", "Kicked off."),
        ("Person B", "Reviewed draft, see https://docs.example/review."),
        ("Person A", "Sent for sign-off."),
    ]
    assert [c.external_id.rsplit(":", 1)[1] for c in versions] == ["512", "1024", "1536"]
    # the list may stack new entries on top: a suffix extension follows the same rule
    assert [c.body for c in done.comments] == ["Called the venue.", "Booked."]
    # a version that extends neither way is kept whole and counted
    assert [c.body for c in odd.comments] == ["First note.", "Rewritten from scratch."]
    assert ("append column rewritten", "Updates") in odd.notes


def test_links_cover_the_item_urls_in_text_and_attachments_without_repeats(dump: dict) -> None:
    first = _mapped(dump)[0]
    urls = [url for url, _ in first.links]
    assert urls[0] == f"https://tenant.example/sites/placeholder/_layouts/15/listform.aspx?PageType=4&ListId={LIST_ID}&ID=1"
    assert urls[1:] == [
        "https://docs.example/plan",                 # the trailing full stop is not part of the URL; seen in text and a comment
        "https://docs.example/review",
        "https://tenant.example/sites/placeholder/Lists/Tasks/Attachments/1/spec.pdf",
    ]
    assert first.links[-1][1] == "spec.pdf"


def test_a_dump_without_its_envelope_is_refused(dump: dict) -> None:
    del dump["list"]
    with pytest.raises(imp.DumpError):
        imp.map_dump(dump, imp.Mapping(), MEMBERS)


def test_a_mapped_owner_that_is_not_a_member_is_counted_not_written(dump: dict) -> None:
    mapping = imp.load_mapping(MAPPING)
    mapping.owner_members["Person B"] = "ghost"
    done = imp.map_dump(dump, mapping, MEMBERS)[1]
    assert done.owner is None and ("unknown member", "ghost") in done.notes


# ------------------------------------------------------------------- write


def test_import_writes_tasks_comments_links_and_one_activity_row_each(db: Path) -> None:
    assert _run(db) == 0
    conn = dbmod.connect(db)
    try:
        first, done = _task(conn, 1), _task(conn, 2)
        assert first["status"] == "todo" and first["priority"] == "high" and first["due"] == "2026-02-01"
        assert done["status"] == "done" and done["owner"] == "p2" and done["done_at"] == done["updated_at"]
        assert first["person_id"] is not None and first["person_id"] == done["person_id"]
        origins = {r[0] for r in conn.execute("SELECT DISTINCT origin FROM comments")}
        assert origins == {"sharepoint"}
        bodies = [c["body"] for c in first["comments"]]
        assert bodies[0] == "Kicked off."
        assert bodies[-1] == "Sent for sign-off."
        assert len(first["links"]) == 4
        for task_id in (1, 2, 3, 4):
            rows = conn.execute(
                "SELECT actor, field FROM activity WHERE task_id = ?", (_task(conn, task_id)["id"],)
            ).fetchall()
            assert [tuple(r) for r in rows] == [("sharepoint-import", "imported")]
    finally:
        conn.close()


def test_a_rerun_changes_nothing(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(db) == 0
    before = _snapshot(db)
    capsys.readouterr()
    assert _run(db) == 0
    out = capsys.readouterr().out
    assert "tasks created 0 · updated 0 · unchanged 4" in out
    assert "comments added 0" in out and "links 0" in out
    assert _snapshot(db) == before


def test_a_changed_source_updates_the_task_and_adds_only_what_is_new(db: Path, dump: dict, tmp_path: Path) -> None:
    assert _run(db) == 0
    dump["items"][0]["Status"] = "Completed"
    dump["items"][0]["_comments"].append(
        {"id": "16", "text": "One more.", "createdDate": "2026-01-25T09:00:00Z", "author": {"name": "Person B"}}
    )
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(dump), encoding="utf-8")
    assert imp.main(["--from-json", str(changed), "--mapping", str(MAPPING), "--db", str(db)]) == 0
    conn = dbmod.connect(db)
    try:
        assert _task(conn, 1)["status"] == "done"
        assert conn.execute("SELECT COUNT(*) FROM comments WHERE external_id LIKE '%:c16'").fetchone()[0] == 1
    finally:
        conn.close()


# ----------------------------------------------------------------- dry run


def test_dry_run_writes_nothing_and_reports_the_unmapped_values(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(db, "--dry-run") == 0
    out = capsys.readouterr().out
    assert not db.exists()                                   # not even the file, let alone the migration
    assert "DRY RUN (nothing written)" in out
    assert "unmapped status: On hold" in out and "unmapped priority: (9) Odd" in out
    assert "unmapped owner: Person Z" in out
    assert "items      : 4" in out and "plan       : tasks create 4" in out
    assert "Draft the quarterly plan" not in out             # counts and mapping values, never a title


def test_dry_run_against_an_imported_db_plans_no_change_and_leaves_it_byte_identical(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(db) == 0
    before = db.read_bytes()
    capsys.readouterr()
    assert _run(db, "--dry-run") == 0
    assert "tasks create 0 · update 0 · unchanged 4" in capsys.readouterr().out
    assert db.read_bytes() == before


def test_a_missing_dump_fails_with_a_clear_exit_code(db: Path, tmp_path: Path) -> None:
    assert imp.main(["--from-json", str(tmp_path / "absent.json"), "--db", str(db)]) == 1


# ------------------------------------------------------------------ schema


def test_sharepoint_is_a_comment_origin(db: Path) -> None:
    assert "sharepoint" in schema.COMMENT_ORIGINS
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    try:
        task = repo.create_task(conn, "Any task")
        comment = repo.add_comment(conn, task["id"], "From the list", origin="sharepoint")
        assert comment["origin"] == "sharepoint"
    finally:
        conn.close()


def test_v21_keeps_comments_and_their_search_across_the_rebuild(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    for target in range(1, 21):
        conn.executescript(schema.MIGRATIONS[target])
    conn.execute("INSERT INTO settings(key, value) VALUES ('schema_version', '20')")
    conn.execute("INSERT INTO tasks(id, title, created_at, updated_at) VALUES (1, 'Keep me', 'c', 'u')")
    conn.execute(
        "INSERT INTO comments(id, task_id, author, ts, body, origin, external_id)"
        " VALUES (7, 1, 'sam', '2026-01-01T00:00:00+00:00', 'zebra crossing', 'notion', 'n:7')"
    )
    conn.commit()
    conn.close()

    assert dbmod.init_db(db) == schema.SCHEMA_VERSION == 21
    conn = dbmod.connect(db)
    try:
        kept = conn.execute("SELECT id, author, body, origin, external_id FROM comments").fetchall()
        assert [tuple(r) for r in kept] == [(7, "sam", "zebra crossing", "notion", "n:7")]
        assert [t["id"] for t in repo.search(conn, "zebra")] == [1]            # comments_fts still resolves id 7
        new = repo.add_comment(conn, 1, "quokka sighting", origin="sharepoint", external_id="s:1")
        assert new["origin"] == "sharepoint"
        assert [t["id"] for t in repo.search(conn, "quokka")] == [1]            # the insert trigger was recreated
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO comments(task_id, ts, body, origin) VALUES (1, 't', 'b', 'nope')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO comments(task_id, ts, body, external_id) VALUES (1, 't', 'b', 'n:7')")
    finally:
        conn.close()
