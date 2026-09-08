"""Batch archiving (#157) — the state machine, the subprocess boundary, the API.

Nothing here reaches Outlook or the real email-archiver checkout: every test
runs against ``tests/fixtures/archiver_fake``, a **real** stand-in checkout
spawned as a **real** subprocess with ``sys.executable``. That is the point —
the service's whole contract is what it puts on a command line, what it writes
into the decisions file and how it reads the child's exit code and stdout back,
and a monkeypatched ``subprocess.run`` would prove none of it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import archive_batch
from src import db as dbmod
from src.ai import AIClient
from src.archive_batch import ArchiveBatchService, ArchiveError
from src.config import AIConfig, AppConfig, ArchiveConfig
from tests.conftest import write_test_config
from tests.fixtures.archiver_fake import (
    FOLDER_BILLS,
    FOLDER_HOUSE,
    apply_doc,
    apply_result,
    build_fake_archiver,
    calls,
    candidate,
    error_doc,
    mail,
    plan_doc,
    revert_doc,
    revert_result,
)
from tests.test_archive_rank import FakeHub, pick_for, picks_doc

ARCHIVED_FILE = "E:\\archive\\house\\heating\\0042 - boiler service.msg"
OLDER_FILE = "E:\\archive\\house\\heating\\0011 - an older thread.msg"


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    dbmod.init_db()
    c = dbmod.connect()
    yield c
    c.close()


def service_for(
    repo: Path, *, ai: object | None = None, **archive_kwargs: object
) -> ArchiveBatchService:
    """A service wired to the fake checkout, spawned with this interpreter.

    ``ai`` defaults to a **real** ``AIClient`` over a config with AI switched
    off: no test process may reach the machine's live hub, and the honest
    stand-in for "the model did not answer" is the client's own classified
    ``ai_disabled``, not a mock. The #158 tests pass :class:`FakeHub` instead.
    """
    defaults: dict[str, object] = {
        "enabled": True, "repo": str(repo), "python": sys.executable, "timeout_seconds": 60.0,
    }
    config = AppConfig(
        ai=AIConfig(enabled=False),
        archive=ArchiveConfig(**{**defaults, **archive_kwargs}),  # type: ignore[arg-type]
        placeholders={"archive": "E:/archive"},
    )
    return ArchiveBatchService(config, ai_client=ai if ai is not None else AIClient(config))


# ------------------------------------------------------------------- state


def test_not_configured_names_the_reason_that_actually_applies(tmp_path: Path) -> None:
    """Five failures, five fixes — one flat "not configured" would hide which."""
    def reason(**kw: object) -> str:
        svc = ArchiveBatchService(AppConfig(archive=ArchiveConfig(**kw)))  # type: ignore[arg-type]
        assert svc.enabled is False
        return svc.reason or ""

    assert "disabled in config" in reason(enabled=False, repo=str(tmp_path))
    assert "archive.repo not configured" in reason(enabled=True, repo="")
    assert "not found at" in reason(enabled=True, repo=str(tmp_path / "nope"))

    repo = build_fake_archiver(tmp_path / "archiver")
    assert "archiver's Python is not at" in reason(enabled=True, repo=str(repo))

    empty = tmp_path / "no-batch-mode"
    build_fake_archiver(empty, with_batch=False)
    assert "no main_batch.py" in reason(
        enabled=True, repo=str(empty), python=sys.executable,
    )

    assert service_for(repo).enabled is True


def test_status_carries_the_configured_state_and_the_last_run(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(tmp_path / "archiver", plan=[plan_doc([])])
    svc = service_for(repo, confidence_threshold=0.55)
    status = svc.status(conn)
    assert status["configured"] is True and status["reason"] is None
    assert status["running"] is False and status["last_run"] is None
    assert status["confidence_threshold"] == 0.55

    svc.run_now()
    assert svc.status(conn)["last_run"]["status"] == "done"


# --------------------------------------------------------------------- run


def _three_mail_plan() -> dict:
    return plan_doc([
        mail("confident@example.invalid", subject="Boiler service",
             candidates=[candidate(FOLDER_HOUSE, 0.91, date_prefix=True),
                         candidate(FOLDER_BILLS, 0.40)]),
        mail("unsure@example.invalid", subject="Something ambiguous",
             candidates=[candidate(FOLDER_BILLS, 0.32)]),
        mail("filed@example.invalid", subject="Already on disk",
             already_archived=OLDER_FILE),
    ])


def test_a_run_files_reviews_and_records_every_mail(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[_three_mail_plan()],
        apply=[apply_doc([apply_result("confident@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
    )
    run = service_for(repo).run_now()

    # With no model reachable the archiver's own ranking stands — and the run
    # says so rather than presenting a fallback as a considered decision (#158).
    assert run["status"] == "done" and "ai_disabled" in run["error"]
    assert run["agreement"] is None
    assert (run["planned"], run["archived"], run["needs_review"], run["failed"]) == (3, 2, 1, 0)

    items = {i["message_id"]: i for i in archive_batch.list_items(conn, run["id"])}
    filed = items["confident@example.invalid"]
    assert filed["status"] == "archived" and filed["chosen_folder"] == FOLDER_HOUSE
    assert filed["files"] == [ARCHIVED_FILE] and filed["sequence"] == "0042"
    assert filed["confidence"] == pytest.approx(0.91) and "0.70 threshold" in filed["reason"]
    assert "could not rank this batch" in filed["reason"]
    # ``candidates`` is kept verbatim so #158 can re-rank without re-planning.
    assert [c["folder_path"] for c in filed["candidates"]] == [FOLDER_HOUSE, FOLDER_BILLS]

    unsure = items["unsure@example.invalid"]
    assert unsure["status"] == "needs_review" and unsure["files"] == []
    assert "below the 0.70 threshold" in unsure["reason"]

    already = items["filed@example.invalid"]
    assert already["status"] == "archived" and already["files"] == [OLDER_FILE]
    assert already["chosen_folder"] is None and "already has this mail filed" in already["reason"]

    # Only the one confident mail was ever offered to ``apply`` — and its
    # ``date_prefix`` went back exactly as the archiver inferred it.
    applied = [c for c in calls(repo) if c["verb"] == "apply"]
    assert applied[0]["payload"] == [{
        "message_id": "confident@example.invalid", "folder_path": FOLDER_HOUSE,
        "date_prefix": True,
    }]
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply"]


def test_a_second_run_over_the_same_message_id_writes_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Idempotency is the Message-ID: a filed mail is never offered twice."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[_three_mail_plan(), _three_mail_plan()],
        apply=[apply_doc([apply_result("confident@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    svc.run_now()
    second = svc.run_now()

    # Neither filed mail is offered again — not the one this run wrote, not the
    # one the archiver's index already had. The mail left in the Inbox is, which
    # is the whole point of leaving it there.
    assert (second["planned"], second["archived"], second["needs_review"]) == (1, 0, 1)
    assert [i["message_id"] for i in archive_batch.list_items(conn, second["id"])] == [
        "unsure@example.invalid"
    ]
    # And nothing was filed a second time: one ``apply``, from the first run.
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply", "plan"]


def test_the_unique_index_refuses_a_second_filed_row(conn: sqlite3.Connection) -> None:
    """The DB has the last word, whatever the archiver's index believes."""
    run = archive_batch.create_run(conn)
    fields = {"message_id": "dupe@example.invalid", "status": "archived"}
    archive_batch.insert_item(conn, run["id"], **fields)
    with pytest.raises(sqlite3.IntegrityError):
        archive_batch.insert_item(conn, run["id"], **fields)
    # A reverted mail leaves the index and may be archived again.
    archive_batch.insert_item(conn, run["id"], message_id="dupe@example.invalid", status="reverted")


def test_limit_bounds_what_one_run_touches(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """The first real run is one mail — trust is built on an undo, not a promise."""
    plan = plan_doc([
        mail(f"m{n}@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.95)])
        for n in range(4)
    ])
    repo = build_fake_archiver(
        tmp_path / "archiver", plan=[plan],
        apply=[apply_doc([apply_result("m0@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
    )
    run = service_for(repo).run_now(limit=1)
    assert run["planned"] == 1 and run["archived"] == 1
    assert [i["message_id"] for i in archive_batch.list_items(conn, run["id"])] == ["m0@example.invalid"]


def test_an_apply_failure_is_recorded_and_stays_revertible(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """``files`` is filled before the move, so a move_failed mail is still undoable."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("stuck@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result(
            "stuck@example.invalid", FOLDER_HOUSE, ok=False, files=[ARCHIVED_FILE],
            error={"code": "move_failed", "message": "Outlook refused the move"},
        )])],
        revert=[revert_doc([revert_result("stuck@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    run = svc.run_now()
    assert (run["archived"], run["failed"]) == (0, 1)

    item = archive_batch.list_items(conn, run["id"])[0]
    assert item["status"] == "failed" and item["files"] == [ARCHIVED_FILE]
    assert "move_failed" in item["error"] and "still in the Inbox" in item["error"]

    reverted = svc.revert(conn, item["id"])
    assert reverted["status"] == "reverted" and reverted["files"] == []


def test_an_apply_failure_with_nothing_written_is_not_revertible(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("gone@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result(
            "gone@example.invalid", FOLDER_HOUSE, ok=False,
            error={"code": "not_in_inbox", "message": "no mail with this Message-ID is in the Inbox"},
        )])],
    )
    svc = service_for(repo)
    item = archive_batch.list_items(conn, svc.run_now()["id"])[0]
    with pytest.raises(ArchiveError) as caught:
        svc.revert(conn, item["id"])
    assert caught.value.http_status == 409 and caught.value.code == "archive_bad_state"


# --------------------------------------------------- the ranking (#158)


def test_the_ranking_gets_its_own_client_model_and_request_bound(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Not ``ai.model``, not ``ai.timeout_seconds``, and not triage's lock.

    Ranking a batch of mails is a long request next to one triage, and the two
    features may want different models — so the archive service builds a second
    client of its own rather than sharing the app's.
    """
    repo = build_fake_archiver(tmp_path / "archiver")
    config = AppConfig(
        ai=AIConfig(enabled=True, model="the_triage_model", timeout_seconds=30.0),
        archive=ArchiveConfig(
            enabled=True, repo=str(repo), python=sys.executable,
            model="the_archive_model", ai_timeout_seconds=175.0,
        ),
    )
    svc = ArchiveBatchService(config)
    triage_client = AIClient(config)

    assert svc.ai.model == "the_archive_model" and svc.ai.timeout == pytest.approx(175.0)
    assert triage_client.model == "the_triage_model"
    # Separate in-flight locks: a triage in progress must not make an archiving
    # run wait, or the other way round.
    assert svc.ai._request_lock is not triage_client._request_lock

    status = svc.status(conn)
    assert status["model"] == "the_archive_model"
    assert (status["batch_size"], status["examples"]) == (8, 20)


def _two_candidate_mail(message_id: str, subject: str = "Boiler service") -> dict:
    """One mail the archiver ranks house-first and bills-second."""
    return mail(message_id, subject=subject, candidates=[
        candidate(FOLDER_HOUSE, 0.9), candidate(FOLDER_BILLS, 0.4, date_prefix=True),
    ])


def test_the_model_picks_among_the_candidates_and_the_run_records_it(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The pick is an index; the folder, the naming form and the state follow from it."""
    moved_file = "E:\\archive\\admin\\bills\\0007 - boiler service.msg"
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            _two_candidate_mail("override@example.invalid"),
            _two_candidate_mail("agreed@example.invalid", subject="Radiator"),
        ])],
        apply=[apply_doc([
            apply_result("override@example.invalid", FOLDER_BILLS, files=[moved_file],
                         sequence="0007"),
            apply_result("agreed@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
        ])],
    )
    hub = FakeHub(picks_doc(
        {"message_id": "override@example.invalid", "candidate": 1, "confidence": 0.88,
         "reason": "this is a bill, not a repair thread"},
        pick_for("agreed@example.invalid", 0, 0.95),
    ))
    run = service_for(repo, ai=hub).run_now()

    assert run["status"] == "done" and run["error"] is None
    # One of the two went where the archiver would have put it.
    assert run["agreement"] == pytest.approx(0.5)

    items = {i["message_id"]: i for i in archive_batch.list_items(conn, run["id"])}
    overridden = items["override@example.invalid"]
    assert overridden["status"] == "archived" and overridden["chosen_folder"] == FOLDER_BILLS
    assert overridden["chosen_rank"] == 1 and overridden["confidence"] == pytest.approx(0.88)
    # The report shows the model's own words, not a score comparison.
    assert overridden["reason"] == "this is a bill, not a repair thread"
    # And the destination candidate's own naming form went back to the archiver.
    assert overridden["date_prefix"] is True

    applied = [c for c in calls(repo) if c["verb"] == "apply"][0]["payload"]
    assert {d["message_id"]: d["folder_path"] for d in applied} == {
        "override@example.invalid": FOLDER_BILLS, "agreed@example.invalid": FOLDER_HOUSE,
    }


@pytest.mark.parametrize(
    ("pick", "expected_folder", "expected_reason"),
    [
        (
            {"message_id": "unsure@example.invalid", "candidate": 0, "confidence": 0.4,
             "reason": "could be either folder"},
            FOLDER_HOUSE, "below the 0.70 threshold",
        ),
        (
            {"message_id": "unsure@example.invalid", "candidate": None, "confidence": 0.1,
             "reason": "nothing here matches this topic"},
            None, "none of the ranked folders fits",
        ),
    ],
)
def test_an_unsure_pick_leaves_the_mail_in_the_inbox(
    conn: sqlite3.Connection, tmp_path: Path, pick: dict,
    expected_folder: str | None, expected_reason: str,
) -> None:
    """Below the threshold, or nothing fits: the mail is *needs you*, never guessed at."""
    repo = build_fake_archiver(
        tmp_path / "archiver", plan=[plan_doc([_two_candidate_mail("unsure@example.invalid")])],
    )
    run = service_for(repo, ai=FakeHub(picks_doc(pick))).run_now()

    item = archive_batch.list_items(conn, run["id"])[0]
    assert item["status"] == "needs_review" and item["files"] == []
    assert item["chosen_folder"] == expected_folder
    assert expected_reason in item["reason"]
    # Nothing was filed, so the archiver was never asked to apply anything.
    assert [c["verb"] for c in calls(repo)] == ["plan"]


def test_an_unusable_answer_files_by_the_archiver_and_names_the_failure(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A model that answers junk must not stop the run — nor pass for a decision."""
    repo = build_fake_archiver(
        tmp_path / "archiver", plan=[plan_doc([_two_candidate_mail("junk@example.invalid")])],
        apply=[apply_doc([apply_result("junk@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
    )
    hub = FakeHub(picks_doc({"message_id": "junk@example.invalid", "candidate": 9,
                             "confidence": 0.9, "reason": "out of range"}))
    run = service_for(repo, ai=hub).run_now()

    assert run["status"] == "done" and run["archived"] == 1
    assert "ai_invalid_response" in run["error"] and "outside its 2 candidates" in run["error"]
    assert run["agreement"] is None

    item = archive_batch.list_items(conn, run["id"])[0]
    assert item["chosen_folder"] == FOLDER_HOUSE and item["chosen_rank"] == 0
    assert "could not rank this batch" in item["reason"]


def test_a_move_teaches_the_next_run_and_the_prompt_carries_it(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The whole point of the memory: correct it once, see it in the next prompt."""
    moved_file = "E:\\archive\\admin\\bills\\0007 - boiler service.msg"
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[
            plan_doc([_two_candidate_mail("first@example.invalid")]),
            plan_doc([_two_candidate_mail("second@example.invalid", subject="Another bill")]),
        ],
        apply=[
            apply_doc([apply_result("first@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])]),
            apply_doc([apply_result("first@example.invalid", FOLDER_BILLS, files=[moved_file],
                                    sequence="0007")]),
            apply_doc([apply_result("second@example.invalid", FOLDER_BILLS, files=[moved_file],
                                    sequence="0008")]),
        ],
        revert=[revert_doc([revert_result("first@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    hub = FakeHub(
        picks_doc(pick_for("first@example.invalid", 0, 0.9)),
        picks_doc(pick_for("second@example.invalid", 1, 0.9)),
    )
    svc = service_for(repo, ai=hub)
    item = archive_batch.list_items(conn, svc.run_now()["id"])[0]

    svc.move(conn, item["id"], "{archive}/admin/bills", hint="bills from this sender go to admin")

    stored = archive_batch.recent_corrections(conn)
    assert len(stored) == 1
    assert stored[0]["suggested_folder"] == FOLDER_HOUSE
    assert stored[0]["chosen_folder"] == "E:/archive/admin/bills"
    assert stored[0]["hint"] == "bills from this sender go to admin"
    assert stored[0]["item_id"] == item["id"] and stored[0]["subject"] == "Boiler service"

    svc.run_now()
    assert "bills from this sender go to admin" in hub.prompts[1]
    assert "chosen archive/admin/bills" in hub.prompts[1]
    # …and the first run could not have carried it — it did not exist yet.
    assert json.loads(hub.prompts[0])["corrections"] == []


def test_accepting_a_below_threshold_mail_is_a_correction_too(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """"You were right, just unsure" is a worked example exactly as a move is.

    A ``failed`` row is not: the archiver broke, the ranking did not.
    """
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            _two_candidate_mail("shy@example.invalid"),
            mail("broken@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
        ])],
        apply=[apply_doc([apply_result(
            "broken@example.invalid", FOLDER_HOUSE, ok=False,
            error={"code": "not_in_inbox", "message": "no mail with this Message-ID is in the Inbox"},
        )])],
    )
    hub = FakeHub(picks_doc(
        {"message_id": "shy@example.invalid", "candidate": 0, "confidence": 0.5,
         "reason": "probably the heating thread"},
        pick_for("broken@example.invalid", 0, 0.95),
    ))
    svc = service_for(repo, ai=hub)
    items = {i["message_id"]: i for i in archive_batch.list_items(conn, svc.run_now()["id"])}

    svc.accept(conn, items["shy@example.invalid"]["id"], hint="always the heating folder")
    svc.accept(conn, items["broken@example.invalid"]["id"])

    stored = archive_batch.recent_corrections(conn)
    assert len(stored) == 1 and stored[0]["message_id"] == "shy@example.invalid"
    assert stored[0]["suggested_folder"] == stored[0]["chosen_folder"] == FOLDER_HOUSE
    assert stored[0]["hint"] == "always the heating folder"


def test_the_prompt_carries_only_the_last_configured_number_of_examples(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A growing memory must never grow the prompt without bound."""
    repo = build_fake_archiver(
        tmp_path / "archiver", plan=[plan_doc([_two_candidate_mail("m@example.invalid")])],
        apply=[apply_doc([apply_result("m@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
    )
    for n in range(5):
        archive_batch.record_correction(
            conn, {"id": None, "message_id": f"old{n}@example.invalid", "subject": f"Older {n}",
                   "sender": "someone@example.invalid", "chosen_folder": FOLDER_HOUSE,
                   "candidates": []},
            chosen_folder=FOLDER_BILLS,
        )
    hub = FakeHub(picks_doc(pick_for("m@example.invalid", 0)))
    service_for(repo, ai=hub, examples=2).run_now()

    carried = json.loads(hub.prompts[0])["corrections"]
    assert len(carried) == 2
    # Oldest-first within the window, so the block only ever grows at its tail.
    assert ['Older 3' in c for c in carried] == [True, False]


# ------------------------------------------------------------ the failures


def test_outlook_unreachable_is_its_own_error(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """Exit 2 with the child's own code — not "the Inbox was empty"."""
    repo = build_fake_archiver(
        tmp_path / "archiver", exit_code=2,
        plan=[error_doc("plan", "outlook_unavailable", "Outlook did not answer within 60 s")],
    )
    svc = service_for(repo)
    run = svc.run_now()
    assert run["status"] == "failed"
    assert "Outlook could not be reached" in run["error"]
    assert svc.last_error.startswith("archive_outlook_unavailable")


def test_a_timed_out_child_is_its_own_error(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo = build_fake_archiver(tmp_path / "archiver", plan=[plan_doc([])], sleep=3.0)
    run = service_for(repo, timeout_seconds=0.5).run_now()
    assert run["status"] == "failed" and "did not finish plan within" in run["error"]


def test_an_unknown_document_schema_is_refused_by_name(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A field that silently moved is how a mail lands in the wrong folder."""
    future = {**plan_doc([]), "schema_version": 99}
    repo = build_fake_archiver(tmp_path / "archiver", plan=[future])
    run = service_for(repo).run_now()
    assert run["status"] == "failed" and "schema_version 99" in run["error"]


def test_a_run_in_flight_refuses_the_next_one(tmp_path: Path) -> None:
    repo = build_fake_archiver(tmp_path / "archiver", plan=[plan_doc([])])
    svc = service_for(repo)
    # Standing in for a run already walking the Inbox over COM: one Outlook,
    # one child at a time — the next caller is refused, never queued.
    assert svc._lock.acquire(blocking=False)
    try:
        with pytest.raises(ArchiveError) as caught:
            svc.run_now()
        assert caught.value.http_status == 409 and caught.value.code == "archive_in_flight"
        assert svc.running is True
    finally:
        svc._lock.release()


def test_a_failed_rescan_leaves_the_run_done_and_says_so(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The mails are filed either way — "not confirmed" is its own state."""
    repo = build_fake_archiver(
        tmp_path / "archiver", scan_exit_code=3,
        plan=[plan_doc([mail("ok@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("ok@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
    )
    run = service_for(repo).run_now()
    assert run["status"] == "done" and run["archived"] == 1
    assert "index rescan exited with code 3" in run["error"]


# ------------------------------------------------------- revert · move · accept


def _one_archived_item(conn: sqlite3.Connection, svc: ArchiveBatchService) -> dict:
    return archive_batch.list_items(conn, svc.run_now()["id"])[0]


def test_revert_deletes_the_files_and_puts_the_mail_back(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("undo@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("undo@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
        revert=[revert_doc([revert_result("undo@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    reverted = svc.revert(conn, item["id"])

    assert reverted["status"] == "reverted" and reverted["files"] == []
    assert reverted["error"] is None and reverted["decided_at"]
    sent = [c for c in calls(repo) if c["verb"] == "revert"][0]["payload"]
    assert sent == [{"message_id": "undo@example.invalid", "files": [ARCHIVED_FILE]}]


def test_a_partial_revert_keeps_the_row_and_names_what_happened(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A half-undo is not a revert; the row stays undoable and says why."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("half@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("half@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
        revert=[revert_doc([revert_result(
            "half@example.invalid", ok=False, deleted=[ARCHIVED_FILE],
            error={"code": "not_in_archive_folder", "message": "no mail with this Message-ID is in 'Archive'"},
        )])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    with pytest.raises(ArchiveError) as caught:
        svc.revert(conn, item["id"])
    assert caught.value.code == "archive_revert_failed"

    still = archive_batch.get_item(conn, item["id"])
    assert still["status"] == "archived" and "not_in_archive_folder" in still["error"]


def test_revert_refuses_a_mail_that_was_never_filed(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("shy@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.1)])])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    assert item["status"] == "needs_review"
    with pytest.raises(ArchiveError) as caught:
        svc.revert(conn, item["id"])
    assert caught.value.http_status == 409


def test_move_reverts_then_applies_into_the_folder_you_named(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """And the ref resolves through the same placeholders every folder field uses."""
    moved_file = "E:\\archive\\admin\\bills\\0007 - boiler service.msg"
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("shift@example.invalid", candidates=[
            candidate(FOLDER_HOUSE, 0.9), candidate(FOLDER_BILLS, 0.5, date_prefix=True),
        ])])],
        apply=[
            apply_doc([apply_result("shift@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])]),
            apply_doc([apply_result("shift@example.invalid", FOLDER_BILLS, files=[moved_file],
                                    sequence="0007")]),
        ],
        revert=[revert_doc([revert_result("shift@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)

    moved = svc.move(conn, item["id"], "{archive}/admin/bills")
    assert moved["status"] == "moved" and moved["files"] == [moved_file]
    assert moved["sequence"] == "0007" and moved["decided_at"]
    # The destination was one of the plan's candidates, so its own inferred
    # naming form is what went back to the archiver.
    assert moved["date_prefix"] is True

    verbs = [c["verb"] for c in calls(repo)]
    assert verbs == ["plan", "apply", "revert", "apply"]
    assert calls(repo)[-1]["payload"] == [{
        "message_id": "shift@example.invalid", "folder_path": "E:/archive/admin/bills",
        "date_prefix": True,
    }]


def test_move_refuses_a_folder_this_install_cannot_resolve(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("nowhere@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("nowhere@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    with pytest.raises(ArchiveError) as caught:
        svc.move(conn, item["id"], "{nosuchtoken}/somewhere")
    assert caught.value.http_status == 422 and caught.value.code == "archive_bad_folder"
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply"]


def test_accept_marks_a_reviewable_row_and_refuses_a_finished_one(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("seen@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.2)]),
            mail("done@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
        ])],
        apply=[apply_doc([apply_result("done@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    items = {i["message_id"]: i for i in archive_batch.list_items(conn, svc.run_now()["id"])}

    accepted = svc.accept(conn, items["seen@example.invalid"]["id"])
    assert accepted["status"] == "needs_review" and accepted["decided_at"]

    with pytest.raises(ArchiveError) as caught:
        svc.accept(conn, items["done@example.invalid"]["id"])
    assert caught.value.http_status == 409 and "needs no review" in str(caught.value)


# --------------------------------------------------------------------- API


@contextmanager
def client_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path | None
) -> Iterator[TestClient]:
    """An app wired to ``repo`` — the fake checkout, never the real archiver.

    ``repo=None`` boots the install a fresh clone gets: the block off, and every
    route saying so.
    """
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    block = None if repo is None else {
        "enabled": True, "repo": str(repo), "python": sys.executable, "timeout_seconds": 60,
    }
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(write_test_config(
        tmp_path / "config.json", archive=block,
    )))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """One confident mail and one below the threshold, through the whole app."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("api-filed@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("api-unsure@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.1)]),
        ])],
        apply=[apply_doc([apply_result("api-filed@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
        revert=[revert_doc([revert_result("api-filed@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    with client_for(tmp_path, monkeypatch, repo) as c:
        yield c


def _finished_run(client: TestClient, **body: object) -> dict:
    started = client.post("/api/archive/run", json=body)
    assert started.status_code == 202 and started.json()["status"] == "running"
    client.app.state.archive.stop(timeout=30)
    detail = client.get(f"/api/archive/runs/{started.json()['id']}")
    assert detail.status_code == 200
    return detail.json()


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
        stored = archive_batch.recent_corrections(conn)
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
        (Path(__file__).resolve().parents[1] / "config" / "config.sample.json").read_text("utf-8")
    )
    assert raw["archive"]["enabled"] is False
    assert set(raw["archive"]) == {
        "enabled", "repo", "python", "candidates", "confidence_threshold", "timeout_seconds",
        "model", "batch_size", "examples", "ai_timeout_seconds",
    }
    # The ranking's own model and its own request bound, never ai.model /
    # ai.timeout_seconds: two features, two jobs, two very different request
    # lengths (#158).
    assert raw["archive"]["model"] == "claude_haiku"
    assert (raw["archive"]["batch_size"], raw["archive"]["examples"]) == (8, 20)
    assert raw["archive"]["ai_timeout_seconds"] == 180
