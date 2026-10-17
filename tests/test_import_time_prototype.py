"""``scripts/import_time_prototype.py`` (#457) against a synthetic export.

The export here is made up in a temp folder — the placeholder people ``p1`` /
``p2`` of the sample config, invented ids and minutes. The real export never
enters the repo or its tests.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from scripts import import_time_prototype as importer
from src import db as dbmod
from src import time_repo as repo

AT = int(datetime(2026, 10, 16, 18, 0).timestamp() * 1000)


def write_export(root: Path, entries: dict[str, Any], guesses: dict[str, Any] | None = None,
                 timers: dict[str, Any] | None = None) -> Path:
    for folder, docs in (("entries", entries), ("guesses", guesses or {}), ("timers", timers or {})):
        (root / folder).mkdir(parents=True, exist_ok=True)
        for doc_id, doc in docs.items():
            (root / folder / f"{doc_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def entry(who: str, cat: str, minutes: Any, date: str = "2026-10-16", note: str = "", at: int = AT) -> dict[str, Any]:
    return {"who": who, "cat": cat, "min": minutes, "date": date, "note": note, "at": at}


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "scratch.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    return path


def rows(path: Path, sql: str) -> list[sqlite3.Row]:
    conn = dbmod.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def prototype_totals(entries: dict[str, Any], people: tuple[str, ...]) -> dict[str, int]:
    """The prototype's own arithmetic: ``validEntries`` then ``sums``."""
    out = dict.fromkeys(people, 0)
    for e in entries.values():
        if e["who"] in people and isinstance(e["min"], (int, float)) and e["min"] > 0 \
                and importer._DAY_RE.match(str(e["date"])):
            out[e["who"]] += e["min"]
    return out


def test_import_is_idempotent_duration_only_and_matches_the_prototype_totals(tmp_path: Path, db: Path) -> None:
    entries = {
        "docA": entry("p1", "cooking", 45, note="soup"),
        "docB": entry("p2", "laundry", 30, date="2026-10-15"),
        "docC": entry("p2", "kids-care", 90, date="2026-10-14"),
        "docD": entry("p1", "cooking", 0),                       # the prototype ignores it
        "docE": entry("p1", "cooking", 20, date="16/10/2026"),   # and this one
    }
    export = write_export(tmp_path / "export", entries, guesses={"p1": {"pct": 60, "at": AT}})
    assert importer.main([str(export)]) == 0
    imported = rows(db, "SELECT * FROM time_entries ORDER BY source_id")
    assert [r["source_id"] for r in imported] == ["docA", "docB", "docC"]
    assert all(r["started_at"] is None and r["ended_at"] is None for r in imported)
    assert imported[0]["note"] == "soup" and imported[0]["created_at"].startswith("2026-10-16T18:00:00")
    conn = dbmod.connect(db)
    try:
        s = repo.summary(conn, people=("p1", "p2"), period="all", area="home")
    finally:
        conn.close()
    assert s["by_person"] == prototype_totals(entries, ("p1", "p2"))
    assert rows(db, "SELECT person, pct FROM time_guesses")[0]["pct"] == 60
    # a second run inserts nothing
    assert importer.main([str(export)]) == 0
    assert len(rows(db, "SELECT id FROM time_entries")) == 3
    assert len(rows(db, "SELECT person FROM time_guesses")) == 1


def test_a_guess_changed_after_the_import_survives_a_re_run(tmp_path: Path, db: Path) -> None:
    export = write_export(tmp_path / "export", {}, guesses={"p1": {"pct": 60, "at": AT}})
    assert importer.main([str(export)]) == 0
    conn = dbmod.connect(db)
    try:
        repo.set_guess(conn, "p1", 45, people=("p1", "p2"))
    finally:
        conn.close()
    assert importer.main([str(export)]) == 0
    assert rows(db, "SELECT pct FROM time_guesses WHERE person = 'p1'")[0]["pct"] == 45


def test_an_unknown_person_refuses_the_whole_import(tmp_path: Path, db: Path, caplog: pytest.LogCaptureFixture) -> None:
    export = write_export(tmp_path / "export", {
        "docA": entry("p1", "cooking", 45),
        "docB": entry("stranger", "cooking", 30),
    }, guesses={"other": {"pct": 50, "at": AT}})
    with caplog.at_level(logging.ERROR):
        assert importer.main([str(export)]) == importer.REFUSED
    assert "other, stranger" in caplog.text
    assert rows(db, "SELECT id FROM time_entries") == [] and rows(db, "SELECT person FROM time_guesses") == []


def test_skip_unknown_people_imports_the_rest_and_counts_them(tmp_path: Path, db: Path,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    export = write_export(tmp_path / "export", {
        "docA": entry("p1", "cooking", 45),
        "docB": entry("stranger", "cooking", 30),
    })
    with caplog.at_level(logging.INFO):
        assert importer.main([str(export), "--skip-unknown-people"]) == 0
    assert [r["source_id"] for r in rows(db, "SELECT source_id FROM time_entries")] == ["docA"]
    assert "skipped 1 row(s): unknown person" in caplog.text


def test_an_unknown_category_refuses_the_whole_import(tmp_path: Path, db: Path) -> None:
    export = write_export(tmp_path / "export", {
        "docA": entry("p1", "cooking", 45),
        "docB": entry("p1", "gardening", 30),
    })
    assert importer.main([str(export)]) == importer.REFUSED
    assert rows(db, "SELECT id FROM time_entries") == []


def test_duplicates_are_reported_by_id_and_never_deleted(tmp_path: Path, db: Path,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    export = write_export(tmp_path / "export", {
        "docA": entry("p1", "cooking", 45, at=AT),
        "docB": entry("p1", "cooking", 45, at=AT + 4_000),        # a save retry, seconds later
        "docC": entry("p1", "cooking", 45, at=AT + 3_600_000),    # the same again an hour later: real
    }, timers={"p2": {"cat": "laundry", "start": AT}})
    with caplog.at_level(logging.WARNING):
        assert importer.main([str(export)]) == 0
    assert "possible duplicate entries (imported as they are; delete in History if so): docA, docB" in caplog.text
    assert "docC" not in caplog.text.split("possible duplicate")[1].splitlines()[0]
    assert "1 running timer(s) in the export were not imported" in caplog.text
    assert len(rows(db, "SELECT id FROM time_entries")) == 3
    assert rows(db, "SELECT person FROM time_timers") == []


def test_a_folder_that_is_not_an_export_is_refused(tmp_path: Path, db: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert importer.main([str(tmp_path / "empty")]) == importer.REFUSED
