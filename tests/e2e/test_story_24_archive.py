"""Story 24 — the mail surface: what needs me becomes a task, the rest gets filed.

    Flag an email in Outlook and archive it as usual → Settings' *Capture into
    Inbox* sheet lands it as an Inbox task carrying its ``.msg`` chip (#98) →
    then, for everything that only needs filing, Settings → **Email
    archiving** (the Archive tab until #397): one
    button runs the batch (#157) with the local model picking the folder
    (#158), the report appears row by row, and each row offers the review level
    its own state allows — *accept* what needed a human, *file / move* into a
    ranked candidate or any other folder with a one-line hint, *revert* a mail
    back into the Inbox, *retry* the one whose file was written before Outlook
    refused the move (#159, #174 — a mail the archiver's index already has and
    the Inbox still holds is finished by the run itself). The Settings row
    carries the run's word and the Settings header what it left for a human, so
    Settings stays the one complete picture of what this install can do (#167,
    #397).

One instance, because one index feeds both halves: the archiver's ``emails.db``
is what capture reads, and the archiver's ``main_batch.py`` is what the run
drives. Both are **synthetic** — the emails come from
``tests/fixtures/emails_fixture.py`` and the archiver is
``tests/fixtures/archiver_fake.build_fake_archiver``, a real checkout with
canned JSON answers and no Outlook anywhere near it. ``archive.enabled`` is
true **only** in this instance's temp config; the committed sample keeps it
off (``tests/test_archive.py::test_the_sample_config_never_arms_the_real_archiver``).

This test replaced ``test_story_21_capture.py`` when the Archive tab landed:
the suite is capped (CLAUDE.md), so the capture walk's on-screen half — the
card's *on* state, *Check now*, and the captured task's ``.msg`` chip — rides
here instead of in a file of its own. Everything story 21 proved that is not
on screen (the re-run creating nothing, an un-flagged mail keeping its task,
the WhatsApp replay, the pre-flag *not configured* reason) is unit-level in
``tests/test_capture.py`` and ``tests/test_api.py`` and stayed there.

1440×900 Chromium then a 390-wide touch context, saving the proof shots the
validation record links to:

    docs/screenshots/story-24-archive-1-desktop.png   Capture sheet after "Check now"
    docs/screenshots/story-24-archive-2-desktop.png   the captured task's .msg chip
    docs/screenshots/story-24-archive-3-desktop.png   Email archiving sheet, nothing run yet
    docs/screenshots/story-24-archive-4-desktop.png   the report: filed · needs you · failed
    docs/screenshots/story-24-archive-5-desktop.png   filing a needs-you mail, hint typed
    docs/screenshots/story-24-archive-6-desktop.png   after the review round (dark)
    docs/screenshots/story-24-archive-7-phone.png     the report as cards (the #168 head,
                                                      picker, bulk button and reviewed row)
    docs/screenshots/story-24-archive-8-phone.png     one card's review menu and its
                                                      *File it…* panel (dark)
    docs/screenshots/story-24-archive-9-desktop.png   Settings after the run: the row's word,
                                                      the header's "needs you"
    docs/screenshots/story-24-archive-9-phone.png     the same list at 390 (dark)
    docs/screenshots/story-24-archive-10-phone.png    *Retry* on the mail whose move was
                                                      refused, in its review menu (dark)
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page

from tests.conftest import write_test_config
from tests.e2e._archive_steps import (
    BILLS,
    BILLS_FILE,
    CHILD_SLEEP_S,
    DESKTOP,
    FILED_ID,
    HOUSE,
    HOUSE_FILE,
    LONG_ATT_1,
    LONG_ATT_2,
    LONG_ATT_3,
    LONG_ATT_4,
    LONG_FILE,
    LONG_ID,
    MEMBERSHIPS,
    OPEN_ID,
    REUSED_FILE,
    REUSED_ID,
    REVIEWED_ID,
    STUCK_FILE,
    STUCK_ID,
    UNREACHABLE,
    UNSURE_ID,
    ArchiveInstance,
    _accept_and_bulk_cancel,
    _archive_sheet_before_run,
    _capture_into_inbox,
    _file_unsure_by_hand,
    _long_row_chips,
    _open_phone_report,
    _palette_and_settings_header,
    _phone_back_to_settings,
    _phone_bulk_and_reviewed,
    _phone_head_readings,
    _phone_long_card,
    _phone_retry_stuck,
    _phone_review_menu,
    _report_rows,
    _reused_row_and_kebab,
    _revert_filed_row,
    _run_archive,
    _second_run,
    _stuck_row_and_menus,
)
from tests.e2e._surface import surface
from tests.e2e.conftest import (
    INTERCEPT,
    _boot,
    _get,
    _terminate,
    e2e_workdir,
)
from tests.fixtures.archiver_fake import (
    apply_doc,
    apply_result,
    build_fake_archiver,
    candidate,
    mail,
    plan_doc,
    revert_doc,
    revert_result,
)


@pytest.fixture(scope="module")
def archive_webapp() -> Iterator[ArchiveInstance]:
    """One disposable instance over the synthetic index **and** the fake archiver."""
    from tests.fixtures.emails_fixture import build_emails_db

    work = e2e_workdir("archive")
    od = work / "od"
    od.mkdir(parents=True)
    build_emails_db(work / "emails.db", root=od, flags=True)
    repo = build_fake_archiver(
        work / "archiver",
        plan=[plan_doc([
            # over the threshold → filed by the run
            mail(FILED_ID, subject="Boiler service due", sender="service@example.invalid",
                 candidates=[candidate(HOUSE, 0.91, date_prefix=True), candidate(BILLS, 0.44)]),
            # under it → left in the Inbox for a human, which is what the tab is for
            mail(UNSURE_ID, subject="Something ambiguous", sender="unknown@example.invalid",
                 candidates=[candidate(BILLS, 0.31), candidate(HOUSE, 0.28)]),
            # the archiver wrote the file and then could not move the mail
            mail(STUCK_ID, subject="Roof survey report", sender="survey@example.invalid",
                 attachments=1, candidates=[candidate(HOUSE, 0.88)]),
            # under the threshold as well — reviewed by hand on the desktop leg
            mail(REVIEWED_ID, subject="Membership renewal", sender="member@example.invalid",
                 candidates=[candidate(MEMBERSHIPS, 0.29), candidate(BILLS, 0.21)]),
            # …and one left open, so the phone has something to file
            mail(OPEN_ID, subject="Service invoice", sender="billing@example.invalid",
                 candidates=[candidate(BILLS, 0.34), candidate(HOUSE, 0.22)]),
            # over the threshold, filed with a long `.msg` name and three
            # attachments beside it (#173) — the phone card this reproduces
            # sideways scroll on.
            mail(LONG_ID, subject="School enrolment forms for the autumn term",
                 sender="school@example.invalid", attachments=4,
                 candidates=[candidate(HOUSE, 0.93, date_prefix=True)]),
            # its `.msg` is already in the archiver's index and the mail is
            # still in the Inbox — the run finishes it rather than calling it
            # done (#174)
            mail(REUSED_ID, subject="Insurance policy renewal",
                 sender="insurer@example.invalid", already_archived=REUSED_FILE, in_inbox=True),
        ])],
        apply=[
            apply_doc([
                apply_result(FILED_ID, HOUSE, files=[HOUSE_FILE]),
                apply_result(STUCK_ID, HOUSE, ok=False, files=[STUCK_FILE], sequence="0043",
                             error={"code": "move_failed",
                                    "message": "the mail could not be moved to Archive — "
                                               f"{UNREACHABLE} is not reachable"}),
                apply_result(LONG_ID, HOUSE,
                             files=[LONG_FILE, LONG_ATT_1, LONG_ATT_2, LONG_ATT_3, LONG_ATT_4],
                             sequence="0006"),
                # nothing written, the existing file handed back, no sequence
                # allocated — what finishing a mail already on disk looks like
                apply_result(REUSED_ID, MEMBERSHIPS, files=[REUSED_FILE], sequence="",
                             reused=True, move_via="refetched"),
            ]),
            # the story's own filing of the unsure mail…
            apply_doc([apply_result(UNSURE_ID, BILLS, files=[BILLS_FILE], sequence="0007")]),
            # …and then the phone's *Retry* on the mail the move was refused
            # for: the same decision, the same file, finished this time
            apply_doc([apply_result(STUCK_ID, HOUSE, files=[STUCK_FILE], sequence="",
                                    reused=True, move_via="saved_retry")]),
        ],
        revert=[revert_doc([revert_result(FILED_ID, deleted=[HOUSE_FILE])])],
        sleep=CHILD_SLEEP_S,
        sleep_verbs=("plan",),
    )
    cfg = write_test_config(
        work / "config.json",
        placeholders={"onedrive": od.as_posix(), "user": "sam", "archive": "E:/archive"},
        email_db=str(work / "emails.db"),
        archive={
            "enabled": True, "repo": str(repo), "python": sys.executable,
            "timeout_seconds": 60, "confidence_threshold": 0.7,
        },
    )
    proc, base, log = _boot(work, work / "tasks.db", cfg)
    try:
        yield ArchiveInstance(base, od, repo, work / "tasks.db")
    finally:
        _terminate(proc)
        log.close()


def test_story_24_archive(archive_webapp: ArchiveInstance, browser: Browser, shots: Path) -> None:
    inst = archive_webapp
    base = inst.base

    st = _get(base, "/api/status")
    assert st["capture"]["enabled"] is True and st["capture"]["reason"] is None
    assert st["archive"]["configured"] is True and st["archive"]["reason"] is None
    assert st["archive"]["running"] is False and st["archive"]["last_run"] is None

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(INTERCEPT)
    page: Page = ctx.new_page()
    page.goto(base + "/")

    # ---------------------------------------------------------------- capture

    _capture_into_inbox(page, base, shots)

    # ---------------------------------------------------------------- archive
    # 3. Settings → Email archiving (the Archive tab until #397) before anything
    #    has run: configured, the model named, where it lives and its threshold,
    #    the bound empty (= the whole Inbox), and no run to show.
    pane = _archive_sheet_before_run(page, inst, shots)
    surface(page, "settings.archive-empty")

    run_id, items = _run_archive(page, base, pane)
    filed_row, filed_item, long_row = _report_rows(page, pane, items)
    _long_row_chips(page, long_row)
    stuck_row, menus = _stuck_row_and_menus(page, items)
    _reused_row_and_kebab(page, inst, shots, items, menus, filed_item, stuck_row)
    _file_unsure_by_hand(page, inst, shots, items, run_id)
    reviewed_item = _accept_and_bulk_cancel(page, base, items, run_id, stuck_row)
    _revert_filed_row(page, inst, shots, run_id, filed_row, filed_item)
    _palette_and_settings_header(page, shots)

    # 10. Phone: four destinations in the pill (Settings is the gear, #281;
    #     Email archiving one of its rows, #397), and the report as cards whose
    #     actions live behind each row's own menu — the grid does not fit here.
    phone, p = _open_phone_report(browser, base)
    _phone_long_card(p, base, run_id)
    _phone_head_readings(p)
    _phone_bulk_and_reviewed(p, shots, reviewed_item)
    stuck_card, open_card = _phone_review_menu(p, base, run_id, shots)
    _phone_retry_stuck(p, inst, shots, run_id, stuck_card, open_card)
    _phone_back_to_settings(p, phone, shots)

    _second_run(page, ctx, base)
