"""Batch archiving (#157) â€” the state machine, the subprocess boundary, the ranking.

Nothing here reaches Outlook or the real email-archiver checkout: every test
runs against ``tests/fixtures/archiver_fake``, a **real** stand-in checkout
spawned as a **real** subprocess with ``sys.executable``. That is the point â€”
the service's whole contract is what it puts on a command line, what it writes
into the decisions file and how it reads the child's exit code and stdout back,
and a monkeypatched ``subprocess.run`` would prove none of it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from src import archive_store
from src.ai import AIClient
from src.archive_batch import ArchiveBatchService, ArchiveError
from src.config import AIConfig, AppConfig, ArchiveConfig
from tests.archive._support import (
    ARCHIVED_FILE,
    OLDER_FILE,
    OLDER_FOLDER,
    OLDER_RENUMBERED,
    _reused_result,
    _three_mail_plan,
    _two_candidate_mail,
    service_for,
)
from tests.archive.test_archive_rank import FakeHub, pick_for, picks_doc
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
    renumbered,
    revert_doc,
    revert_result,
)

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

    # Every key the Settings card reads (#167) — the card renders "unknown"
    # for a key it cannot find, so a rename here has to be seen here.
    assert set(status) >= {
        "configured", "reason", "running", "repo", "candidates", "confidence_threshold",
        "model", "batch_size", "examples", "last_run", "last_error",
    }
    assert status["repo"] == str(repo) and status["last_error"] is None
    assert status["candidates"] > 0 and isinstance(status["model"], str)

    svc.run_now()
    last = svc.status(conn)["last_run"]
    assert last["status"] == "done"
    # …and of the run row too: the card's Last run line is built from these.
    assert set(last) >= {
        "id", "status", "started_at", "finished_at", "planned", "archived",
        "needs_review", "failed", "agreement", "error",
    }


def test_a_run_files_reviews_and_records_every_mail(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[_three_mail_plan()],
        apply=[apply_doc([
            apply_result("confident@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
            _reused_result(),
        ])],
    )
    run = service_for(repo).run_now()

    # With no model reachable the archiver's own ranking stands — and the run
    # says so rather than presenting a fallback as a considered decision (#158).
    assert run["status"] == "done" and "ai_disabled" in run["error"]
    assert run["agreement"] is None
    assert (run["planned"], run["archived"], run["needs_review"], run["failed"]) == (3, 2, 1, 0)

    items = {i["message_id"]: i for i in archive_store.list_items(conn, run["id"])}
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

    # A mail whose file is on disk *and* which is still in the Inbox is finished
    # rather than recorded as done (#174): the folder is the one its file lives
    # in, nothing was ranked, and the file it already had is what it keeps.
    already = items["filed@example.invalid"]
    assert already["status"] == "archived" and already["files"] == [OLDER_FILE]
    assert already["chosen_folder"] == OLDER_FOLDER and already["chosen_rank"] is None
    assert already["confidence"] is None
    assert "finished a mail already on disk" in already["reason"]
    # A reuse allocates no sequence number, and the row says so rather than
    # inventing one.
    assert already["sequence"] is None

    # Both went to ``apply``, each with the naming form the archiver itself
    # inferred — the confident mail's candidate, and nothing at all for a folder
    # the plan never ranked.
    applied = [c for c in calls(repo) if c["verb"] == "apply"]
    assert applied[0]["payload"] == [
        {"message_id": "confident@example.invalid", "folder_path": FOLDER_HOUSE,
         "date_prefix": True},
        {"message_id": "filed@example.invalid", "folder_path": OLDER_FOLDER,
         "date_prefix": False},
    ]
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply"]


def test_a_second_run_over_the_same_message_id_writes_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Idempotency is the Message-ID: a filed mail is never offered twice."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[_three_mail_plan(), _three_mail_plan()],
        apply=[apply_doc([
            apply_result("confident@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
            _reused_result(),
        ])],
    )
    svc = service_for(repo)
    svc.run_now()
    second = svc.run_now()

    # Neither filed mail is offered again — not the one this run wrote, not the
    # one the archiver's index already had. The mail left in the Inbox is, which
    # is the whole point of leaving it there.
    assert (second["planned"], second["archived"], second["needs_review"]) == (1, 0, 1)
    assert [i["message_id"] for i in archive_store.list_items(conn, second["id"])] == [
        "unsure@example.invalid"
    ]
    # And nothing was filed a second time: one ``apply``, from the first run.
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply", "plan"]


def test_the_unique_index_refuses_a_second_filed_row(conn: sqlite3.Connection) -> None:
    """The DB has the last word, whatever the archiver's index believes."""
    run = archive_store.create_run(conn)
    fields = {"message_id": "dupe@example.invalid", "status": "archived"}
    archive_store.insert_item(conn, run["id"], **fields)
    with pytest.raises(sqlite3.IntegrityError):
        archive_store.insert_item(conn, run["id"], **fields)
    # A reverted mail leaves the index and may be archived again.
    archive_store.insert_item(conn, run["id"], message_id="dupe@example.invalid", status="reverted")


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
    assert [i["message_id"] for i in archive_store.list_items(conn, run["id"])] == ["m0@example.invalid"]


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

    item = archive_store.list_items(conn, run["id"])[0]
    assert item["status"] == "failed" and item["files"] == [ARCHIVED_FILE]
    assert "move_failed" in item["error"] and "still in the Inbox" in item["error"]

    reverted = svc.revert(conn, item["id"])
    assert reverted["status"] == "reverted" and reverted["files"] == []


def test_a_whole_apply_failure_leaves_no_mail_claimed_as_filed(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A raised ``apply`` confirms nothing, so no row may say ``archived`` (#440).

    Rows are inserted before ``apply`` runs; if the call raises as a whole
    (timeout, exit-2 error document, unreadable output) they used to stay
    ``archived`` with no files — and ``filed_message_ids`` then skipped those
    mails on every later run while they sat in the Inbox.
    """
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[_three_mail_plan(), _three_mail_plan()],
        apply=[
            error_doc("apply", "outlook_unavailable", "Outlook went away"),
            apply_doc([
                apply_result("confident@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
                _reused_result(),
            ]),
        ],
    )
    svc = service_for(repo)
    failed_run = svc.run_now()
    assert failed_run["status"] == "failed" and "Outlook went away" in failed_run["error"]

    # Both apply-bound mails (a fresh filing and a finish of a file already on
    # disk) are recorded as what happened to them: failed, not filed. The one
    # that never went to ``apply`` keeps its own state, and the finish row keeps
    # the file it already knew.
    by_message = {i["message_id"]: i for i in archive_store.list_items(conn, failed_run["id"])}
    assert by_message["confident@example.invalid"]["status"] == "failed"
    assert "Outlook went away" in by_message["confident@example.invalid"]["error"]
    assert by_message["unsure@example.invalid"]["status"] == "needs_review"
    assert by_message["filed@example.invalid"]["status"] == "failed"
    assert by_message["filed@example.invalid"]["files"] == [OLDER_FILE]
    assert archive_store.filed_message_ids(conn) == set()

    # So the next run offers them again and files them for real.
    second = svc.run_now()
    assert second["status"] == "done"
    assert {i["message_id"]: i["status"] for i in archive_store.list_items(conn, second["id"])} == {
        "confident@example.invalid": "archived",
        "unsure@example.invalid": "needs_review",
        "filed@example.invalid": "archived",
    }


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
    item = archive_store.list_items(conn, svc.run_now()["id"])[0]
    with pytest.raises(ArchiveError) as caught:
        svc.revert(conn, item["id"])
    assert caught.value.http_status == 409 and caught.value.code == "archive_bad_state"


def test_an_apply_that_names_no_file_leaves_the_one_the_row_knows(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Naming no file is not "the file is gone".

    A finish (#174) is answered for a row that was inserted already knowing
    where its ``.msg`` is; blanking that on an answer which simply omits
    ``files`` would make a mail that *is* on disk look unrevertible. The name
    the row kept still goes through the renumber map (#176): it sits in the
    folder that was just re-sequenced, so it may be one of the files that moved.
    """
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("terse@example.invalid", already_archived=OLDER_FILE, in_inbox=True),
        ])],
        apply=[apply_doc(
            [apply_result(
                "terse@example.invalid", OLDER_FOLDER, files=[], sequence="", reused=True,
            )],
            renumbered_map=renumbered(
                OLDER_FOLDER, old=OLDER_FILE, new=OLDER_RENUMBERED,
                message_id="terse@example.invalid",
            ),
        )],
    )
    svc = service_for(repo)
    item = archive_store.list_items(conn, svc.run_now()["id"])[0]
    assert item["status"] == "archived" and item["files"] == [OLDER_RENUMBERED]
    # …and it is still undoable, which is the thing blanking it would have cost.
    svc._require_revertible(item)


@pytest.mark.parametrize("in_inbox", [None, False])
def test_a_mail_on_disk_not_stated_in_the_inbox_stays_a_no_op(
    conn: sqlite3.Connection, tmp_path: Path, in_inbox: bool | None
) -> None:
    """``in_inbox`` is additive, so anything but a literal true keeps the old shape.

    An older archiver states nothing at all; a false would say the mail is
    properly filed and gone. Finishing either would send a decision for a mail
    that is not in the Inbox — which is how a mail gets filed a second time.
    """
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("gone@example.invalid", already_archived=OLDER_FILE, in_inbox=in_inbox),
        ])],
    )
    item = archive_store.list_items(conn, service_for(repo).run_now()["id"])[0]
    assert item["status"] == "archived" and item["files"] == [OLDER_FILE]
    assert item["chosen_folder"] is None
    assert "already has this mail filed" in item["reason"]
    # Nothing beyond the plan reached Outlook: nothing written, nothing moved.
    assert [c["verb"] for c in calls(repo)] == ["plan"]


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

    items = {i["message_id"]: i for i in archive_store.list_items(conn, run["id"])}
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

    item = archive_store.list_items(conn, run["id"])[0]
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

    item = archive_store.list_items(conn, run["id"])[0]
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
    item = archive_store.list_items(conn, svc.run_now()["id"])[0]

    svc.move(conn, item["id"], "{archive}/admin/bills", hint="bills from this sender go to admin")

    stored = archive_store.recent_corrections(conn)
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
    items = {i["message_id"]: i for i in archive_store.list_items(conn, svc.run_now()["id"])}

    svc.accept(conn, items["shy@example.invalid"]["id"], hint="always the heating folder")
    svc.accept(conn, items["broken@example.invalid"]["id"])

    stored = archive_store.recent_corrections(conn)
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
        archive_store.record_correction(
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
