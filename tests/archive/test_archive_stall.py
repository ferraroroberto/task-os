"""A run always ends, in bounded time, with counters that match its rows.

The re-index after the apply is the one phase that can take minutes per folder,
and the run's lock is held for all of it: while it waits, the next run is
refused and the screen has to show what was filed so far.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import archive_batch, archive_store
from src.archive_batch import ArchiveBatchService
from tests.archive._support import ARCHIVED_FILE, service_for
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


def _one_mail_fake(**kwargs: object):
    return build_fake_archiver(
        plan=[plan_doc([mail("a@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("a@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_stalling_reindex_ends_the_run_and_frees_the_next_one(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    mails = [
        mail("a@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
        mail("b@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.9)]),
    ]
    fake = build_fake_archiver(
        plan=[plan_doc(mails)],
        apply=[apply_doc([apply_result(m["message_id"], m["candidates"][0]["folder_path"], files=[ARCHIVED_FILE])
                          for m in mails])],
        sleep=0.4, sleep_verbs=("index",),
    )
    # raising=False: against the code before the budget existed this must fail
    # on the behaviour (both folders re-indexed), not on a missing name.
    monkeypatch.setattr(archive_batch, "SCAN_BUDGET_S", 0.3, raising=False)
    svc = service_for(fake)

    run = svc.run_now()

    assert run["status"] == "done" and run["archived"] == 2
    assert len(fake.index_calls) == 1, "the folder past the budget is not asked"
    assert "has not confirmed" in run["error"] and "budget" in run["error"]
    assert svc.running is False
    assert svc.run_now()["status"] == "done"


def test_the_counters_match_the_rows_while_the_run_is_still_re_indexing(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[dict] = []
    real = ArchiveBatchService._rescan_index

    def spy(self: ArchiveBatchService, folders: list[str]) -> str | None:
        seen.append(dict(archive_store.list_runs(conn, limit=1)[0]))
        return real(self, folders)

    monkeypatch.setattr(ArchiveBatchService, "_rescan_index", spy)
    run = service_for(_one_mail_fake()).run_now()

    during = seen[0]
    assert during["status"] == "running"
    assert (during["planned"], during["archived"]) == (1, 1)
    assert (run["planned"], run["archived"]) == (1, 1)
