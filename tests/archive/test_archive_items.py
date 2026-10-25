"""Batch archiving's per-mail actions â€” revert Â· move Â· accept Â· retry â€” and the
renumbering that heals stored paths after each, against the same real fake
archiver subprocess as ``test_archive_service.py``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import apply_renumber_map as apply_map
from src import archive_store, email_capture
from src import tasks_repo as repo
from src.archive_batch import ArchiveError
from src.archive_renumber import apply_renumber_map
from tests.archive._support import (
    ARCHIVED_FILE,
    ATTACHMENT_FILE,
    OLDER_FILE,
    OLDER_RENUMBERED,
    RENUMBERED_ATTACHMENT,
    RENUMBERED_FILE,
    _capture_the_email,
    _one_archived_item,
    _stuck_then_finished,
    service_for,
)
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
    renumbered,
    revert_doc,
    revert_result,
)


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

    still = archive_store.get_item(conn, item["id"])
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


def test_a_move_whose_refile_fails_records_the_undo_it_already_did(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The undo leg has deleted the files and returned the mail to the Inbox;
    a row still claiming ``archived`` would keep every later run from filing it."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("lost@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[
            apply_doc([apply_result("lost@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])]),
            error_doc("apply", "outlook_unavailable", "Outlook went away"),
        ],
        revert=[revert_doc([revert_result("lost@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    assert "lost@example.invalid" in archive_store.filed_message_ids(conn)

    with pytest.raises(ArchiveError) as caught:
        svc.move(conn, item["id"], "{archive}/admin/bills")
    assert caught.value.code == "archive_outlook_unavailable"

    after = archive_store.get_item(conn, item["id"])
    assert after["status"] == "reverted" and after["files"] == []
    assert "back in the Inbox" in after["error"] and "Outlook went away" in after["error"]
    assert "lost@example.invalid" not in archive_store.filed_message_ids(conn)
    assert not svc.running


def test_move_files_a_needs_review_mail_that_was_never_archived(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The commonest gesture on the report screen (#159): the ranking would not
    decide, so a human names the folder — and there is nothing to undo first."""
    filed_file = "E:\\archive\\admin\\bills\\0003 - something ambiguous.msg"
    repo = build_fake_archiver(
        tmp_path / "archiver",
        # one candidate, ranked too low to file on its own
        plan=[plan_doc([mail("shy@example.invalid", subject="Something ambiguous",
                             candidates=[candidate(FOLDER_BILLS, 0.2, date_prefix=True)])])],
        apply=[apply_doc([apply_result("shy@example.invalid", FOLDER_BILLS,
                                       files=[filed_file], sequence="0003")])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    assert item["status"] == "needs_review" and item["files"] == []

    moved = svc.move(conn, item["id"], "{archive}/admin/bills", hint="bills go to the flat")
    assert moved["status"] == "moved" and moved["files"] == [filed_file]
    assert moved["date_prefix"] is True and moved["sequence"] == "0003"

    # No revert leg at all: there was nothing on disk to undo, and inventing one
    # would have asked the archiver to un-file a mail it never filed. The run
    # itself filed nothing, so the move's own `apply` is the first there is.
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply"]
    # …and the correction it teaches carries the hint (#158).
    stored = archive_store.recent_corrections(conn)
    assert len(stored) == 1 and stored[0]["hint"] == "bills go to the flat"
    assert stored[0]["chosen_folder"] == "E:/archive/admin/bills"


def test_move_refuses_a_reverted_mail_and_names_why(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A reverted mail is back in the Inbox and belongs to the next run, not to
    a second filing from a stale report row."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("undone@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("undone@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])])],
        revert=[revert_doc([revert_result("undone@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo)
    item = _one_archived_item(conn, svc)
    assert svc.revert(conn, item["id"])["status"] == "reverted"

    with pytest.raises(ArchiveError) as caught:
        svc.move(conn, item["id"], "{archive}/admin/bills")
    assert caught.value.http_status == 409 and caught.value.code == "archive_bad_state"
    assert "nothing here to file" in str(caught.value)


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
    items = {i["message_id"]: i for i in archive_store.list_items(conn, svc.run_now()["id"])}

    accepted = svc.accept(conn, items["seen@example.invalid"]["id"])
    assert accepted["status"] == "needs_review" and accepted["decided_at"]

    with pytest.raises(ArchiveError) as caught:
        svc.accept(conn, items["done@example.invalid"]["id"])
    assert caught.value.http_status == 409 and "needs no review" in str(caught.value)


def test_retry_finishes_a_move_outlook_refused_and_keeps_what_is_on_disk(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The whole point of #174: the file was written, only the move was refused.

    The archiver's remedy is the *same* decision again — it writes nothing,
    reuses the file and finishes the move — so nothing is re-decided here and
    the row keeps the sequence number the first attempt allocated (a reuse
    allocates none).
    """
    repo = _stuck_then_finished(tmp_path, second=apply_result(
        "stuck@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE], sequence="",
        reused=True, move_via="saved_retry",
    ))
    svc = service_for(repo)
    item = archive_store.list_items(conn, svc.run_now()["id"])[0]
    assert item["status"] == "failed" and item["files"] == [ARCHIVED_FILE]
    assert item["sequence"] == "0042" and item["decided_at"] is None
    assert "move_failed" in item["error"]

    finished = svc.retry(conn, item["id"])
    assert finished["status"] == "archived" and finished["files"] == [ARCHIVED_FILE]
    assert finished["error"] is None and finished["decided_at"]
    assert finished["sequence"] == "0042"

    # The same message, the same folder, the same naming form — a retry is a
    # re-send, never a second decision.
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply", "apply"]
    assert calls(repo)[-1]["payload"] == [{
        "message_id": "stuck@example.invalid", "folder_path": FOLDER_HOUSE, "date_prefix": True,
    }]


def test_a_retry_refused_again_keeps_the_row_failed_with_the_newer_reason(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The second message is the useful one — it names the remedy that is left."""
    repo = _stuck_then_finished(tmp_path, second=apply_result(
        "stuck@example.invalid", FOLDER_HOUSE, ok=False, files=[ARCHIVED_FILE], sequence="0042",
        error={"code": "move_failed",
               "message": "Outlook itself is holding this item — restart Outlook, then apply "
                          "the same decision again"},
    ))
    svc = service_for(repo)
    item = archive_store.list_items(conn, svc.run_now()["id"])[0]

    with pytest.raises(ArchiveError) as caught:
        svc.retry(conn, item["id"])
    assert caught.value.http_status == 502 and caught.value.code == "archive_retry_failed"

    still = archive_store.get_item(conn, item["id"])
    assert still["status"] == "failed" and still["files"] == [ARCHIVED_FILE]
    assert "restart Outlook" in still["error"] and still["decided_at"] is None
    # Still on disk and still in the Inbox, so it is still offered a retry.
    assert still["chosen_folder"] == FOLDER_HOUSE


def test_retry_refuses_every_row_with_nothing_half_done(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Filed, never-filed and failed-before-anything-was-written: three 409s.

    A retry only ever *finishes* something. On any other row it would either
    file a mail twice or re-send a decision no file backs, so it is refused by
    the service before a child is spawned at all.
    """
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("done@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("shy@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.2)]),
            mail("nowhere@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
        ])],
        apply=[apply_doc([
            apply_result("done@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
            apply_result("nowhere@example.invalid", FOLDER_HOUSE, ok=False, error={
                "code": "not_in_inbox", "message": "no mail with this Message-ID is in the Inbox",
            }),
        ])],
    )
    svc = service_for(repo)
    items = {i["message_id"]: i for i in archive_store.list_items(conn, svc.run_now()["id"])}
    assert items["done@example.invalid"]["status"] == "archived"
    assert items["shy@example.invalid"]["status"] == "needs_review"
    assert items["nowhere@example.invalid"]["status"] == "failed"
    assert items["nowhere@example.invalid"]["files"] == []

    for message_id in ("done@example.invalid", "shy@example.invalid", "nowhere@example.invalid"):
        with pytest.raises(ArchiveError) as caught:
            svc.retry(conn, items[message_id]["id"])
        assert caught.value.http_status == 409 and caught.value.code == "archive_bad_state"
        assert "already on disk" in str(caught.value)
    assert [c["verb"] for c in calls(repo)] == ["plan", "apply"]


def test_an_apply_that_renumbers_heals_every_path_this_database_stores(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The archiver renames, task-os follows — in all three places at once.

    ``apply --renumber`` re-sequences the folder it just wrote into, and its own
    ``files`` name what the mail was written as *before* that. So the row, the
    link chip and the capture key must all end up on the new name, and the next
    capture poll must recognise the mail rather than land it a second time.
    """
    captured = _capture_the_email(conn, ARCHIVED_FILE)
    repo_dir = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("boiler@example.invalid", subject="Boiler service",
                             candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc(
            # the pre-renumber names, exactly as the archiver reports them
            [apply_result("boiler@example.invalid", FOLDER_HOUSE,
                          files=[ARCHIVED_FILE, ATTACHMENT_FILE])],
            renumbered_map=renumbered(
                FOLDER_HOUSE, old=ARCHIVED_FILE, new=RENUMBERED_FILE,
                message_id="boiler@example.invalid",
                attachments=[[ATTACHMENT_FILE, RENUMBERED_ATTACHMENT]],
            ),
        )],
    )
    svc = service_for(repo_dir)
    item = _one_archived_item(conn, svc)

    # The flag actually went out on the command line…
    assert "--renumber" in [c for c in calls(repo_dir) if c["verb"] == "apply"][0]["argv"]
    # …the row carries the names on disk now, not the ones apply reported…
    assert item["files"] == [RENUMBERED_FILE, RENUMBERED_ATTACHMENT]
    assert item["reason"].endswith(" · renumbered 2 file(s) in heating")

    # …the link chip opens the renamed file…
    link = repo.list_links(conn, captured["id"])[0]
    assert link["url"] == "{archive}/house/heating/0002 - boiler service.msg"
    # …and the capture key moved with it, so a second poll lands nothing.
    again, outcome = repo.capture_task(
        conn, external_id=link["url"] and email_capture.external_id_for(link["url"]),
        title="Boiler service", actor=email_capture.CAPTURE_ACTOR,
    )
    assert outcome == "unchanged" and again["id"] == captured["id"]
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_a_revert_renumbers_the_folder_and_the_next_undo_gets_the_right_files(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The mail that stays behind is renamed, and its own revert must find it.

    A ``revert`` leaves a hole and the archiver closes it, which renumbers the
    *other* mails in that folder. Without the heal the second undo would hand
    the archiver a path that no longer exists — the failure this whole issue is
    about.
    """
    repo_dir = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("first@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("second@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
        ])],
        apply=[apply_doc([
            apply_result("first@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
            apply_result("second@example.invalid", FOLDER_HOUSE, files=[OLDER_FILE]),
        ])],
        revert=[
            revert_doc(
                [revert_result("first@example.invalid", deleted=[ARCHIVED_FILE])],
                renumbered_map=renumbered(
                    FOLDER_HOUSE, old=OLDER_FILE, new=OLDER_RENUMBERED,
                    message_id="second@example.invalid",
                ),
            ),
            revert_doc([revert_result("second@example.invalid", deleted=[OLDER_RENUMBERED])]),
        ],
    )
    svc = service_for(repo_dir)
    items = {i["message_id"]: i for i in archive_store.list_items(conn, svc.run_now()["id"])}

    undone = svc.revert(conn, items["first@example.invalid"]["id"])
    assert undone["status"] == "reverted" and undone["files"] == []
    assert undone["reason"].endswith(" · renumbered 1 file(s) in heating")
    # The mail still filed there followed the rename.
    stayed = archive_store.get_item(conn, items["second@example.invalid"]["id"])
    assert stayed["files"] == [OLDER_RENUMBERED]

    svc.revert(conn, stayed["id"])
    sent = [c for c in calls(repo_dir) if c["verb"] == "revert"][-1]["payload"]
    assert sent == [{"message_id": "second@example.invalid", "files": [OLDER_RENUMBERED]}]


def test_a_map_is_healed_even_when_the_mail_itself_failed(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A per-mail failure rides *inside* a completed verb — the map still applies.

    The archiver renumbers after its own work whether or not one mail's undo
    went through, so the names on disk have moved either way. Dropping the map
    on the error path is exactly how a stale path survives the one code that
    was written to prevent it.
    """
    repo_dir = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("stuck@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("neighbour@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
        ])],
        apply=[apply_doc([
            apply_result("stuck@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
            apply_result("neighbour@example.invalid", FOLDER_HOUSE, files=[OLDER_FILE]),
        ])],
        revert=[revert_doc(
            [revert_result("stuck@example.invalid", ok=False, error={
                "code": "not_in_archive_folder", "message": "no mail with this Message-ID is there",
            })],
            renumbered_map=renumbered(
                FOLDER_HOUSE, old=OLDER_FILE, new=OLDER_RENUMBERED,
                message_id="neighbour@example.invalid",
            ),
        )],
    )
    svc = service_for(repo_dir)
    items = {i["message_id"]: i for i in archive_store.list_items(conn, svc.run_now()["id"])}
    with pytest.raises(ArchiveError) as caught:
        svc.revert(conn, items["stuck@example.invalid"]["id"])
    assert caught.value.code == "archive_revert_failed"

    stayed = archive_store.get_item(conn, items["neighbour@example.invalid"]["id"])
    assert stayed["files"] == [OLDER_RENUMBERED]


def test_a_move_that_gets_no_result_still_heals_both_legs_maps(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """#193: the undo leg renumbered the old folder whatever the apply leg said.

    An ``apply`` that completes with no entry for the mail is the one exit from
    ``move`` that used to drop the maps — leaving the neighbours' rows naming
    files the undo had renamed.
    """
    bills_file = "E:\\archive\\admin\\bills\\0009 - a bystander.msg"
    bills_renumbered = "E:\\archive\\admin\\bills\\0008 - a bystander.msg"
    repo_dir = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("moving@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("neighbour@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("bystander@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.9)]),
        ])],
        apply=[
            apply_doc([
                apply_result("moving@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE]),
                apply_result("neighbour@example.invalid", FOLDER_HOUSE, files=[OLDER_FILE]),
                apply_result("bystander@example.invalid", FOLDER_BILLS, files=[bills_file]),
            ]),
            apply_doc([], renumbered_map=renumbered(
                FOLDER_BILLS, old=bills_file, new=bills_renumbered,
                message_id="bystander@example.invalid",
            )),
        ],
        revert=[revert_doc(
            [revert_result("moving@example.invalid", deleted=[ARCHIVED_FILE])],
            renumbered_map=renumbered(
                FOLDER_HOUSE, old=OLDER_FILE, new=OLDER_RENUMBERED,
                message_id="neighbour@example.invalid",
            ),
        )],
    )
    svc = service_for(repo_dir)
    items = {i["message_id"]: i for i in archive_store.list_items(conn, svc.run_now()["id"])}
    with pytest.raises(ArchiveError) as caught:
        svc.move(conn, items["moving@example.invalid"]["id"], "{archive}/admin/bills")
    assert caught.value.code == "archive_move_failed"

    assert archive_store.get_item(conn, items["moving@example.invalid"]["id"])["status"] == "reverted"
    neighbour = archive_store.get_item(conn, items["neighbour@example.invalid"]["id"])
    assert neighbour["files"] == [OLDER_RENUMBERED]
    bystander = archive_store.get_item(conn, items["bystander@example.invalid"]["id"])
    assert bystander["files"] == [bills_renumbered]


def test_renumbering_off_asks_for_nothing_and_a_document_without_a_map_changes_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """``archive.renumber: false`` and an archiver too old to renumber: one shape.

    Neither is an error and neither may heal anything — a missing ``renumbered``
    key is what every build before email-archiver#61 prints, so absence has to
    read as "nothing moved", never as a reason to guess.
    """
    repo_dir = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("quiet@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc([apply_result("quiet@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
    )
    svc = service_for(repo_dir, renumber=False)
    item = _one_archived_item(conn, svc)
    assert "--renumber" not in [c for c in calls(repo_dir) if c["verb"] == "apply"][0]["argv"]
    assert item["files"] == [ARCHIVED_FILE]
    assert "renumbered" not in (item["reason"] or "")


def test_a_folder_the_archiver_refused_to_renumber_is_said_out_loud(
    conn: sqlite3.Connection, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty map means *already in order*; a refusal is a different fact.

    Only the second one can leave a stored path stale, so it is logged rather
    than folded into the quiet path — and neither of them writes a note onto a
    row that had nothing renamed.
    """
    repo_dir = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("tidy@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])])],
        apply=[apply_doc(
            [apply_result("tidy@example.invalid", FOLDER_HOUSE, files=[ARCHIVED_FILE])],
            renumbered_map={FOLDER_HOUSE: []},
            refused=[{"folder_path": FOLDER_BILLS, "reason": "outside the archive roots"}],
        )],
    )
    svc = service_for(repo_dir)
    with caplog.at_level("WARNING"):
        item = _one_archived_item(conn, svc)
    assert item["files"] == [ARCHIVED_FILE] and "renumbered" not in (item["reason"] or "")
    assert "refused to renumber bills" in caplog.text


def test_a_chained_renumber_moves_each_row_once(conn: sqlite3.Connection) -> None:
    """An older mail filed into a folder shifts its neighbours: 003→001, 001→002, 002→003.

    Healing pair by pair carried the link on the original 001 through 002 on to
    003 and hit the unique capture key; every row must land on its own new ref.
    """
    folder = "E:\\archive\\house\\heating\\"
    names = {n: f"{folder}{n:04d} - mail.msg" for n in (1, 2, 3)}
    tasks = {n: _capture_the_email(conn, names[n]) for n in (1, 2, 3)}
    entries = [
        {"from": names[3], "to": names[1]},
        {"from": names[1], "to": names[2]},
        {"from": names[2], "to": names[3]},
    ]

    dry = apply_renumber_map(conn, folder, entries, placeholders_map={"archive": "E:/archive"}, dry_run=True)
    assert dry["links"] == 3 and dry["tasks"] == 3

    done = apply_renumber_map(conn, folder, entries, placeholders_map={"archive": "E:/archive"})
    assert (done["links"], done["tasks"]) == (3, 3)
    expected = {1: 2, 2: 3, 3: 1}  # old number -> the number it now carries
    for old, new in expected.items():
        link = repo.list_links(conn, tasks[old]["id"])[0]["url"]
        assert link.endswith(f"{new:04d} - mail.msg")
        key = repo.get_task(conn, tasks[old]["id"])["external_id"]
        assert key.endswith(f"{new:04d} - mail.msg")


def test_a_saved_map_heals_the_same_way_and_a_dry_run_writes_nothing(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``scripts/apply_renumber_map.py`` — the out-of-band repair, previewable.

    Same three rewrites as an in-run heal, driven from a map file the archiver's
    own ``renumber`` verb printed; ``--dry-run`` reports the identical counts and
    leaves every row exactly as it was.
    """
    monkeypatch.setenv(
        "TASKOS_CONFIG_PATH",
        str(write_test_config(tmp_path / "config.json", placeholders={"archive": "E:/archive"})),
    )
    captured = _capture_the_email(conn, ARCHIVED_FILE)
    item_id = archive_store.insert_item(
        conn, archive_store.create_run(conn)["id"], message_id="saved@example.invalid",
        subject="Boiler service", status="archived",
        files_json=json.dumps([ARCHIVED_FILE, ATTACHMENT_FILE]),
    )
    map_file = tmp_path / "renumber-heal.json"
    map_file.write_text(json.dumps(renumbered(
        FOLDER_HOUSE, old=ARCHIVED_FILE, new=RENUMBERED_FILE,
        attachments=[[ATTACHMENT_FILE, RENUMBERED_ATTACHMENT]],
    )), encoding="utf-8")

    assert apply_map.main([str(map_file), "--dry-run"]) == 0
    preview = capsys.readouterr().out
    assert "would rewrite 1 archive item(s), 1 link(s) and 1 captured task(s)" in preview
    assert archive_store.get_item(conn, item_id)["files"] == [ARCHIVED_FILE, ATTACHMENT_FILE]

    assert apply_map.main([str(map_file)]) == 0
    assert "rewrote 1 archive item(s), 1 link(s) and 1 captured task(s)" in capsys.readouterr().out
    assert archive_store.get_item(conn, item_id)["files"] == [
        RENUMBERED_FILE, RENUMBERED_ATTACHMENT,
    ]
    assert repo.list_links(conn, captured["id"])[0]["url"].endswith("0002 - boiler service.msg")

    # And again: a pair whose old name is stored nowhere matches nothing.
    assert apply_map.main([str(map_file)]) == 0
    assert "rewrote 0 archive item(s), 0 link(s) and 0 captured task(s)" in capsys.readouterr().out
