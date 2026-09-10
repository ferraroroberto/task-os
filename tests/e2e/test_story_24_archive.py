"""Story 24 — the mail surface: what needs me becomes a task, the rest gets filed.

    Flag an email in Outlook and archive it as usual → Settings' *Capture into
    Inbox* card lands it as an Inbox task carrying its ``.msg`` chip (#98) →
    then, for everything that only needs filing, the **Archive** tab: one
    button runs the batch (#157) with the local model picking the folder
    (#158), the report appears row by row, and each row offers the review level
    its own state allows — *accept* what needed a human, *file / move* into a
    ranked candidate or any other folder with a one-line hint, *revert* a mail
    back into the Inbox, *retry* the one whose file was written before Outlook
    refused the move (#159, #174 — a mail the archiver's index already has and
    the Inbox still holds is finished by the run itself). Settings carries the
    same block as a card of
    its own, so the Settings tab stays the one complete picture of what this
    install can do — and can start a run without leaving it (#167).

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

    docs/screenshots/story-24-archive-1-desktop.png   Capture card after "Check now"
    docs/screenshots/story-24-archive-2-desktop.png   the captured task's .msg chip
    docs/screenshots/story-24-archive-3-desktop.png   Archive tab, nothing run yet
    docs/screenshots/story-24-archive-4-desktop.png   the report: filed · needs you · failed
    docs/screenshots/story-24-archive-5-desktop.png   filing a needs-you mail, hint typed
    docs/screenshots/story-24-archive-6-desktop.png   after the review round (dark)
    docs/screenshots/story-24-archive-7-phone.png     the report as cards (the #168 head,
                                                      picker, bulk button and reviewed row)
    docs/screenshots/story-24-archive-8-phone.png     one card's review menu and its
                                                      *File it…* panel (dark)
    docs/screenshots/story-24-archive-9-desktop.png   Settings' archiving card after the run
    docs/screenshots/story-24-archive-9-phone.png     the same card at 390 (dark)
    docs/screenshots/story-24-archive-10-phone.png    *Retry* on the mail whose move was
                                                      refused, in its review menu (dark)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e.conftest import (
    INTERCEPT,
    _boot,
    _get,
    _terminate,
    dismiss_toasts,
    e2e_workdir,
    shot,
)
from tests.fixtures.archiver_fake import (
    apply_doc,
    apply_result,
    build_fake_archiver,
    calls,
    candidate,
    mail,
    plan_doc,
    revert_doc,
    revert_result,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

KITCHEN = "Kitchen quotes from the installer"
SCHOOL = "School enrolment forms — deadline Friday"

# The synthetic archive tree. `{archive}` is a placeholder of this instance, so
# the *Other folder…* field can name a folder the way the drawer would.
HOUSE = "E:\\archive\\house\\heating"
BILLS = "E:\\archive\\admin\\bills"
HOUSE_FILE = "E:\\archive\\house\\heating\\0042 - boiler service.msg"
BILLS_FILE = "E:\\archive\\admin\\bills\\0007 - something ambiguous.msg"
STUCK_FILE = "E:\\archive\\house\\heating\\0043 - roof survey.msg"
# Deep enough that the reason it appears in is wider than a 390px card, which
# is what the phone's last-three-components fold is for (#168).
UNREACHABLE = "E:\\archive\\house\\heating\\2026\\surveys\\pending"
MEMBERSHIPS = "E:\\archive\\admin\\renewals"

FILED_ID = "boiler@example.invalid"
UNSURE_ID = "ambiguous@example.invalid"
STUCK_ID = "roof@example.invalid"
#: A mail the archiver's index already has **and** which is still sitting in the
#: Inbox — what a refused move leaves behind on every later plan (#174). The run
#: finishes it instead of recording it as done: nothing is written, the file it
#: already has is reused, and the mail finally leaves the Inbox.
REUSED_ID = "insurance@example.invalid"
REUSED_FILE = "E:\\archive\\admin\\renewals\\0031 - insurance policy.msg"
#: Two more mails the ranking would not decide (#168): one gets accepted on the
#: desktop leg, so the phone shows a **reviewed** row that offers nothing; the
#: other is left open, so the phone also shows a live *File it…* and a bulk
#: button whose count is the rows that really do still offer *Accept*.
REVIEWED_ID = "renewal@example.invalid"
OPEN_ID = "invoice@example.invalid"
#: A filed mail whose `.msg` name alone is ~90 characters, with three
#: attachment files beside it — the phone card #173 fixes: on the school
#: mail's real card the `.msg` chip ran past the card's right edge and the
#: pane scrolled sideways, exactly what the run below reproduces before the
#: fix (and stays clean after it).
LONG_ID = "school-enrolment@example.invalid"
LONG_FILE = ("E:\\archive\\house\\heating\\2026-09-08 - 0006 - "
             "School enrolment forms for the autumn term and the after-school club.msg")
LONG_ATT_1 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - enrolment-form.pdf"
LONG_ATT_2 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - payment-schedule.docx"
LONG_ATT_3 = "E:\\archive\\house\\heating\\2026-09-08 - 0006 - club-timetable.pdf"

#: Long enough that the running state is observable from the page and from a
#: second POST, short enough that the story stays a few seconds.
CHILD_SLEEP_S = 1.1


class ArchiveInstance:
    def __init__(self, base: str, od: Path, repo: Path, db: Path) -> None:
        self.base = base
        self.od = od
        self.repo = repo
        self.db = db


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
                 sender="school@example.invalid", attachments=3,
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
                apply_result(LONG_ID, HOUSE, files=[LONG_FILE, LONG_ATT_1, LONG_ATT_2, LONG_ATT_3],
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


def _post_status(base: str, path: str, body: dict) -> int:
    """POST and hand back the status code — including a 4xx, which is the point."""
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return int(res.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _open_card(page: Page, card_id: str):
    """A Settings card is a collapsed disclosure (#46) — open it like a user would."""
    card = page.locator(f"#{card_id}")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


def _row(page: Page, message_id: str, items: list[dict]):
    """The report row for one mail, by the item id the API gave it."""
    item = next(i for i in items if i["message_id"] == message_id)
    return page.locator(f".archive-row[data-id='{item['id']}']"), item


def _items(base: str, run_id: int) -> list[dict]:
    return _get(base, f"/api/archive/runs/{run_id}")["items"]


#: One caption line at this width, with room for the row's own leading. A
#: status row taller than this has wrapped, which is the thing #168 removed.
_ONE_LINE_PX = 24.0


def _box(locator) -> dict[str, float]:
    """The rendered box of the one element *locator* matches; missing fails loud."""
    box = locator.bounding_box()
    if box is None:
        raise AssertionError(f"{locator} has no box — it is not rendered")
    return box


def _mid_y(box: dict[str, float]) -> float:
    return box["y"] + box["height"] / 2


def _pin_scroller(page: Page) -> None:
    """Park the report's own scroller at its left edge, and prove it stayed.

    The nine columns fit 1440 with only a few pixels of slack, so focusing a
    control inside the panel can nudge the scroller — enough to reframe a shot
    between two runs of one commit (rule 3 in `docs/validation.md`).
    """
    scroller = page.locator("#paneArchive .table-scroll")
    scroller.evaluate("el => { el.scrollLeft = 0; }")
    assert scroller.evaluate("el => el.scrollLeft") == 0


def _confirm(page: Page, action: str) -> None:
    """The one vendored destructive-action dialog (#121) — press its primary."""
    dialog = page.locator("#confirmDialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".confirm-danger")).to_have_text(action)
    dialog.locator(".confirm-danger").click()
    expect(dialog).to_be_hidden()


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
    # 1. Settings → the Capture card is on, and "Check now" lands the two
    #    flagged mails as Inbox tasks (the on-screen half of story 21).
    page.get_by_role("tab", name="Settings").click()
    card = _open_card(page, "captureCard")
    expect(card.locator("#captureCardMeta")).to_have_text("on")
    expect(card.locator("#statusCaptureRun")).to_have_text("not yet")
    card.locator("#captureRunNow").click()
    expect(card.locator("#captureCardMeta")).to_have_text("checked")
    expect(card.locator("#statusCaptureRun")).to_contain_text("2 flagged · 2 new")
    shot(page, shots / "story-24-archive-1-desktop.png")

    # 2. …as Inbox tasks the capture made, each carrying the .msg its chip opens
    page.get_by_role("tab", name="Board").click()
    inbox = page.locator(".board-col[data-col='inbox']")
    expect(inbox.locator(".trow-title", has_text=KITCHEN)).to_be_visible()
    captured = _get(base, "/api/tasks?status=inbox")["items"]
    assert {t["title"] for t in captured} == {KITCHEN, SCHOOL}
    assert all(t["created_by"] == "email-archiver" for t in captured)
    inbox.locator(".trow-main", has_text=KITCHEN).first.click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    chip = drawer.locator(".link-row a.chip").first
    expect(chip).to_contain_text("2026-08-10 Kitchen quotes.msg")
    expect(chip).to_have_attribute(
        "href",
        "taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse%2F2026-08-10%20Kitchen%20quotes.msg",
    )
    shot(page, shots / "story-24-archive-2-desktop.png")
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()

    # ---------------------------------------------------------------- archive
    # 3. The Archive tab before anything has run: configured, the model named,
    #    the bound empty (= the whole Inbox), and no run to show.
    page.get_by_role("tab", name="Archive").click()
    pane = page.locator("#paneArchive")
    expect(pane).to_be_visible()
    expect(pane.locator("#statusArchive .status-ok")).to_have_text("ready")
    expect(pane.locator("#statusArchiveRun")).to_have_text("never")
    expect(pane.locator("#statusArchiveRecent")).to_have_text("no finished run yet")
    expect(pane.locator("#archiveLimit")).to_have_value("")
    expect(pane.locator("#archiveRun")).to_be_enabled()
    expect(pane.locator("#archiveHost .empty-state-message")).to_contain_text("No run yet")
    shot(page, shots / "story-24-archive-3-desktop.png")

    # 4. Press it. While the child is working the button is disabled and a
    #    second run is refused by the API with its own reason — one Outlook,
    #    one run at a time.
    pane.locator("#archiveRun").click()
    expect(pane.locator("#archiveRun")).to_be_disabled()
    expect(pane.locator("#archiveRunLabel")).to_have_text("Archiving…")
    assert _post_status(base, "/api/archive/run", {}) == 409

    # 5. It finishes on its own and the report fills in: two filed, one that
    #    needs a human, one the archiver broke on.
    expect(pane.locator("#archiveRun")).to_be_enabled(timeout=30000)
    expect(pane.locator(".archive-row")).to_have_count(7)
    run_id = _get(base, "/api/archive/runs")["runs"][0]["id"]
    items = _items(base, run_id)
    assert {i["message_id"]: i["status"] for i in items} == {
        FILED_ID: "archived", UNSURE_ID: "needs_review", STUCK_ID: "failed",
        REVIEWED_ID: "needs_review", OPEN_ID: "needs_review", LONG_ID: "archived",
        REUSED_ID: "archived",
    }
    expect(pane.locator("#statusArchiveRun")).to_contain_text(
        "7 mail(s) · 3 filed · 3 need you · 1 failed"
    )
    filed_row, filed_item = _row(page, FILED_ID, items)
    expect(filed_row.locator(".archive-state")).to_have_text("filed")
    expect(filed_row.locator(".archive-dest")).to_have_text("archive › house › heating")
    expect(filed_row.locator(".archive-files a.chip")).to_have_attribute(
        "href", "taskos://open?ref=" + "E%3A%5Carchive%5Chouse%5Cheating%5C0042%20-%20boiler%20service.msg"
    )
    long_row, long_item = _row(page, LONG_ID, items)
    expect(long_row.locator(".archive-state")).to_have_text("filed")
    expect(long_row.locator(".archive-files a.chip")).to_have_count(4)
    # Desktop keeps the full name, date prefix and all (#173) — the phone-only
    # trim is a card-width concession, not a change to what the desktop shows.
    expect(long_row.locator(".archive-files a.chip").first).to_have_text(
        "2026-09-08 - 0006 - School enrolment forms for the autumn term and the after-school club.msg"
    )
    stuck_row, _ = _row(page, STUCK_ID, items)
    expect(stuck_row.locator(".archive-state")).to_have_text("failed")
    expect(stuck_row.locator(".archive-reason")).to_contain_text("move_failed")
    # …and, because the file was written before the move was refused, it is the
    # one row that can be *finished* rather than only undone (#174). No other
    # row offers it: a retry re-sends a decision, which anywhere else would file
    # a mail twice.
    expect(stuck_row.locator(".archive-action", has_text="Retry")).to_have_count(1)
    expect(stuck_row.locator(".archive-action", has_text="Revert")).to_have_count(1)
    expect(page.locator(".archive-row-actions .archive-action", has_text="Retry")).to_have_count(1)

    # 5b. The mail whose `.msg` the archiver's index already had, still sitting
    #     in the Inbox: the run finished it — the folder is the one its file
    #     lives in, nothing was ranked and nothing was written.
    reused_row, reused_item = _row(page, REUSED_ID, items)
    expect(reused_row.locator(".archive-state")).to_have_text("filed")
    expect(reused_row.locator(".archive-dest")).to_have_text("archive › admin › renewals")
    expect(reused_row.locator(".archive-reason")).to_contain_text("finished a mail already on disk")
    expect(reused_row.locator(".archive-files a.chip")).to_have_count(1)
    assert reused_item["files"] == [REUSED_FILE] and reused_item["chosen_rank"] is None
    # A reuse allocates no sequence number, and the row says so.
    assert reused_item["sequence"] is None
    assert {
        "message_id": REUSED_ID, "folder_path": "E:/archive/admin/renewals", "date_prefix": False,
    } in [c for c in calls(inst.repo) if c["verb"] == "apply"][0]["payload"]

    # An `archived` row is finished, not reviewed: the API answers 409 on
    # accept, so the screen does not offer it.
    expect(filed_row.locator(".archive-action", has_text="Accept")).to_have_count(0)
    expect(reused_row.locator(".archive-action", has_text="Accept")).to_have_count(0)
    # The bulk button's N is the rows that really do offer *Accept*, not a
    # second count that drifts from them (#168).
    offering = page.locator(".archive-row-actions .archive-action", has_text="Accept")
    expect(offering).to_have_count(4)
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 4 that need you")
    dismiss_toasts(page)
    _pin_scroller(page)
    shot(page, shots / "story-24-archive-4-desktop.png")

    # 6. The mail the ranking would not decide: open its menu, the candidates it
    #    ranked are there, type why, and file it into one of them.
    unsure_row, unsure_item = _row(page, UNSURE_ID, items)
    expect(unsure_row.locator(".archive-state")).to_have_text("needs you")
    expect(unsure_row.locator(".archive-dest")).to_have_text("archive › admin › bills")
    unsure_row.locator(".archive-move-toggle").click()
    # the panel is a full-width row of its own, under the mail's
    panel = page.locator(f".archive-move-row[data-id='{unsure_item['id']}']")
    expect(panel).to_be_visible()
    cands = panel.locator(".archive-cand")
    expect(cands).to_have_count(2)
    expect(cands.first.locator(".archive-cand-path")).to_have_text("archive › admin › bills")
    panel.locator(".archive-hint").fill("anything from this sender belongs with the bills")
    dismiss_toasts(page)
    _pin_scroller(page)
    shot(page, shots / "story-24-archive-5-desktop.png")
    cands.first.click()
    _confirm(page, "File it")
    expect(page.locator(f".archive-row[data-id='{unsure_item['id']}'] .archive-state")).to_have_text(
        "moved by you"
    )
    moved = next(i for i in _items(base, run_id) if i["message_id"] == UNSURE_ID)
    assert moved["status"] == "moved" and moved["files"] == [BILLS_FILE]
    assert moved["reason"] == "filed here by hand from the Inbox"
    # It was never on disk, so nothing was undone first — the archiver was
    # asked to file it, once.
    assert [c["verb"] for c in calls(inst.repo)] == ["plan", "apply", "apply"]

    # 7. Accept the row the archiver broke on — "I have seen this", no file moved
    stuck_row.locator(".archive-action", has_text="Accept").click()
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 2 that need you")
    assert next(i for i in _items(base, run_id) if i["message_id"] == STUCK_ID)["decided_at"]
    # Seeing it is not finishing it: the mail is still in the Inbox, so the
    # offer to finish it stands and the error text stays on screen until a
    # retry actually succeeds (#174).
    expect(stuck_row.locator(".archive-action", has_text="Retry")).to_have_count(1)
    expect(stuck_row.locator(".archive-reason")).to_contain_text("move_failed")

    # 7b. A `needs_review` row that has had its human stops asking for one
    #     (#168): it reads *reviewed*, offers neither *Accept* nor *File it…*,
    #     and the bulk count follows the rows down instead of drifting from
    #     them — the run with three *needs you* rows used to say *Accept all 2*.
    reviewed_row, reviewed_item = _row(page, REVIEWED_ID, items)
    expect(reviewed_row.locator(".archive-state")).to_have_text("needs you")
    reviewed_row.locator(".archive-action", has_text="Accept").click()
    reviewed_row = page.locator(f".archive-row[data-id='{reviewed_item['id']}']")
    expect(reviewed_row.locator(".archive-state")).to_have_text("reviewed")
    expect(reviewed_row.locator(".c-act")).to_have_text("nothing left to do")
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 1 that need you")
    expect(page.locator(".archive-row-actions .archive-action", has_text="Accept")).to_have_count(1)

    # 8. Undo the one the run filed: the files go, the mail is back in the Inbox
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    filed_row.locator(".archive-action", has_text="Revert").click()
    _confirm(page, "Undo it")
    expect(page.locator(f".archive-row[data-id='{filed_item['id']}'] .archive-state")).to_have_text(
        "reverted"
    )
    undone = next(i for i in _items(base, run_id) if i["message_id"] == FILED_ID)
    assert undone["status"] == "reverted" and undone["files"] == []
    sent = [c for c in calls(inst.repo) if c["verb"] == "revert"][0]["payload"]
    assert sent == [{"message_id": FILED_ID, "files": [HOUSE_FILE]}]
    # …and there is nothing left to press on it, which the row says out loud.
    expect(page.locator(f".archive-row[data-id='{filed_item['id']}'] .c-act")).to_have_text(
        "back in the Inbox"
    )
    dismiss_toasts(page)
    _pin_scroller(page)
    shot(page, shots / "story-24-archive-6-desktop.png")

    # 9. The Board's Inbox header points at what the run left for a human, and
    #    the palette reaches the tab the same way every other destination is
    #    reached.
    page.emulate_media(color_scheme="light")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.get_by_role("tab", name="Board").click()
    link = page.locator(".board-col[data-col='inbox'] .board-archive-link")
    expect(link).to_have_text("3 mail(s) need you")
    link.click()
    expect(page.locator("#paneArchive")).to_be_visible()
    page.get_by_role("tab", name="Board").click()
    page.click("#paletteBtn")
    page.fill("#paletteInput", ">go to archive")
    page.keyboard.press("Enter")
    expect(page.locator("#paneArchive")).to_be_visible()

    # 9b. Settings gets the same one-card picture every other service has
    #     (#167): what the archiver is, what the model works with, where the
    #     threshold sits and what the last run did — read from the very block
    #     the tab renders, plus the way back to it.
    page.get_by_role("tab", name="Settings").click()
    acard = _open_card(page, "archiveCard")
    expect(acard.locator("#archiveCardMeta")).to_have_text("on")
    expect(acard.locator("#statusArchiveRepo .status-ok")).to_have_text("ready")
    expect(acard.locator("#statusArchiveRepo code")).to_have_text(str(inst.repo))
    expect(acard.locator("#statusArchiveModel")).to_contain_text("per batch")
    expect(acard.locator("#statusArchiveThreshold")).to_contain_text("70%")
    expect(acard.locator("#statusArchiveLast")).to_contain_text(
        "7 mail(s) · 3 filed · 3 need you · 1 failed"
    )
    dismiss_toasts(page)
    shot(page, shots / "story-24-archive-9-desktop.png")
    acard.locator("#archiveOpenTab").click()
    expect(page.locator("#paneArchive")).to_be_visible()

    # 10. Phone: six destinations in the pill, and the report as cards whose
    #     actions live behind each row's own menu — the grid does not fit here.
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True,
                                has_touch=True, color_scheme="light")
    phone.add_init_script(INTERCEPT)
    p = phone.new_page()
    p.goto(base + "/")
    expect(p.locator("nav.tabs .tab")).to_have_count(6)
    p.get_by_role("tab", name="Archive").tap()
    expect(p.locator("#paneArchive")).to_be_visible()
    expect(p.locator(".archive-card")).to_have_count(7)
    expect(p.locator(".archive-table")).to_have_count(0)

    # 10a-1. The long `.msg` name with three attachments beside it (#173):
    #        every chip stays inside the card, cut with an ellipsis, rather
    #        than widening the card and scrolling the pane sideways — the
    #        defect #168 fixed for the subject/path/reason columns, now for
    #        the file chips too.
    long_card = p.locator(f".archive-card[data-id='{_item_id(base, run_id, LONG_ID)}']")
    long_chips = long_card.locator(".archive-files .chip")
    expect(long_chips).to_have_count(4)
    card_box = _box(long_card)
    for chip_index in range(4):
        chip_box = _box(long_chips.nth(chip_index))
        assert chip_box["x"] + chip_box["width"] <= card_box["x"] + card_box["width"] + 1, (
            f"chip {chip_index} runs past the card's right edge ({chip_box} vs {card_box})"
        )
    assert_no_horizontal_overflow(p)

    # 10a. The head is one line, and the three readings are one line each — no
    #      label column, short wording, and the bound compact beside the button
    #      that grew into what it left (#168).
    head_run, head_limit = _box(p.locator("#archiveRun")), _box(p.locator(".archive-limit"))
    assert abs(_mid_y(head_run) - _mid_y(head_limit)) < 6, "the head wrapped onto two lines"
    assert head_run["width"] > head_limit["width"], "the button did not take the free width"
    expect(p.locator("#statusArchive")).to_contain_text("/batch")
    expect(p.locator("#archiveRecentLabel")).to_have_text("Recent")
    # `09/09 09:00`, not `9/9/26, 9:00 AM` — no year, a 24-hour clock, and the
    # day still in the locale's own order (the date moves, so the shape is what
    # is asserted).
    expect(p.locator("#statusArchiveRun")).to_have_text(
        re.compile(r"^\d{2}\D\d{2} \d{2}:\d{2} · done · 3 filed")
    )
    for index in range(3):
        row = _box(p.locator("#paneArchive .archive-head .status-row").nth(index))
        assert row["height"] < _ONE_LINE_PX, f"status row {index} wraps ({row['height']}px)"

    # 10b. The picker reaches the right edge and the bulk button is a full-width
    #      one under it, counting exactly the rows that still offer *Accept*.
    bar = _box(p.locator(".archive-runbar"))
    pick = _box(p.locator("#archiveRunPick"))
    assert pick["x"] + pick["width"] >= bar["x"] + bar["width"] - 1, "the picker stops short"
    bulk = p.locator("#archiveAcceptAll")
    expect(bulk).to_have_text("Accept all (1)")
    assert abs(_box(bulk)["width"] - bar["width"]) < 1, "the bulk button is not full width"
    assert_min_target(bulk)

    # 10c. …and the row that already had its human says so and asks nothing.
    reviewed_card = p.locator(f".archive-card[data-id='{reviewed_item['id']}']")
    expect(reviewed_card.locator(".archive-state")).to_have_text("reviewed")
    expect(reviewed_card.locator(".archive-menu-toggle")).to_have_count(0)
    expect(reviewed_card).to_contain_text("nothing left to do")
    assert_no_horizontal_overflow(p)
    assert_min_target(p.locator("#archiveRun"))
    assert_min_target(p.locator("#archiveLimit"))
    shot(p, shots / "story-24-archive-7-phone.png")

    # 10d. The long path the archiver failed on is folded to its last three
    #      components on screen, with the whole sentence still in the title —
    #      an absolute path is what used to push the pane sideways.
    stuck_card = p.locator(f".archive-card[data-id='{_item_id(base, run_id, STUCK_ID)}']")
    reason = stuck_card.locator(".archive-reason")
    expect(reason).to_contain_text("… 2026 › surveys › pending")
    assert UNREACHABLE in (reason.get_attribute("title") or "")

    # 10e. Open one review menu: *Review* is the same button as the three it
    #      hides, and the *File it…* panel is a phone panel — two-line
    #      candidates, one full-width field with the glyph inside it, a
    #      full-width *Archive here*, every control on its own line at the same
    #      height, nothing overlapping, nothing pushing the pane sideways.
    p.emulate_media(color_scheme="dark")
    p.evaluate("document.documentElement.dataset.theme = 'dark'")
    open_card = p.locator(f".archive-card[data-id='{_item_id(base, run_id, OPEN_ID)}']")
    open_card.locator(".archive-menu-toggle").tap()
    expect(open_card.locator(".archive-move-toggle")).to_be_visible()
    assert_min_target(open_card.locator(".archive-action"))
    shapes = open_card.locator(".archive-action").evaluate_all(
        "els => els.map(el => ({tag: el.tagName, height: Math.round(el.offsetHeight),"
        " font: getComputedStyle(el).fontSize, pad: getComputedStyle(el).padding}))"
    )
    assert len(shapes) == 3, shapes                          # Review · Accept · File it…
    assert {s["tag"] for s in shapes} == {"BUTTON"}, shapes   # no link-styled <summary>
    for key in ("height", "font", "pad"):
        assert len({s[key] for s in shapes}) == 1, f"row actions differ in {key}: {shapes}"
    open_card.locator(".archive-move-toggle").tap()
    panel = open_card.locator(".archive-move-body")
    expect(panel).to_be_visible()
    cand = panel.locator(".archive-cand").first
    name, path = _box(cand.locator(".archive-cand-name")), _box(cand.locator(".archive-cand-path"))
    assert path["y"] >= name["y"] + name["height"] - 1, "the candidate is still one line"
    assert abs(_mid_y(name) - _mid_y(_box(cand.locator(".archive-cand-score")))) < 4
    field = _box(panel.locator(".archive-other-field"))
    go = _box(panel.locator(".archive-other-go"))
    body = _box(panel)
    assert field["width"] > body["width"] - 20 and go["width"] > body["width"] - 20
    assert go["y"] >= field["y"] + field["height"] - 1, "*Archive here* is not on its own line"
    assert abs(_box(panel.locator(".archive-hint"))["height"] - field["height"]) < 1
    assert_min_target(panel.locator(".archive-other-field"))
    assert_min_target(panel.locator(".archive-other-field .folder-pick"))
    assert_min_target(panel.locator(".archive-other-go"))
    assert_min_target(panel.locator(".archive-hint"))
    assert_min_target(panel.locator(".archive-cand"))
    assert_no_overlap([
        panel.locator(".archive-other-field"),
        panel.locator(".archive-other-go"),
        panel.locator(".archive-hint"),
    ])
    assert_no_horizontal_overflow(p)
    # The panel is what this shot is for, so put it on screen and check it got
    # there — clear of the floating pill, which owns the last ~90px (rule 3 in
    # docs/validation.md: a position is asserted, never assumed).
    panel.evaluate("el => el.scrollIntoView({block: 'center'})")
    seat = _box(panel)
    assert seat["y"] >= 0 and seat["y"] + seat["height"] <= PHONE["height"] - 90, seat
    shot(p, shots / "story-24-archive-8-phone.png")

    # 10f. The mail the archiver wrote and could not move, on the phone (#174).
    #      Its menu offers *Retry* in the same `.archive-action` shape as the
    #      rest — *Accept* is gone because it was accepted on the desktop leg,
    #      and being seen is not being finished. One tap and it is filed: the
    #      file it already had is reused, the error text goes, and the mail has
    #      left the Inbox.
    open_card.locator(".archive-menu-toggle").tap()      # close the one before it
    expect(open_card.locator(".archive-move-toggle")).to_be_hidden()
    stuck_card.locator(".archive-menu-toggle").tap()
    retry = stuck_card.locator(".archive-action", has_text="Retry")
    expect(retry).to_be_visible()
    stuck_shapes = stuck_card.locator(".archive-action").evaluate_all(
        "els => els.map(el => ({tag: el.tagName, text: el.textContent.trim(),"
        " height: Math.round(el.offsetHeight), font: getComputedStyle(el).fontSize,"
        " pad: getComputedStyle(el).padding}))"
    )
    # Review · Move to… · Retry · Revert — no *Accept* on a row already seen.
    assert [s["text"] for s in stuck_shapes] == [
        "Review", "Move to…", "Retry", "Revert",
    ], stuck_shapes
    assert {s["tag"] for s in stuck_shapes} == {"BUTTON"}, stuck_shapes
    for key in ("height", "font", "pad"):
        assert len({s[key] for s in stuck_shapes}) == 1, f"row actions differ in {key}: {stuck_shapes}"
    assert_min_target(retry)
    assert_no_horizontal_overflow(p)
    retry.scroll_into_view_if_needed()
    seat = _box(stuck_card)
    assert seat["y"] >= 0, seat
    dismiss_toasts(p)
    shot(p, shots / "story-24-archive-10-phone.png")

    retry.tap()
    expect(stuck_card.locator(".archive-state")).to_have_text("filed")
    expect(stuck_card.locator(".archive-reason")).not_to_contain_text("move_failed")
    done = next(i for i in _items(base, run_id) if i["message_id"] == STUCK_ID)
    assert done["status"] == "archived" and done["error"] is None
    # Nothing was written and nothing re-decided: the same message, the same
    # folder, the same naming form — and the sequence the first attempt
    # allocated survives a reuse that allocates none.
    assert done["files"] == [STUCK_FILE] and done["sequence"] == "0043"
    assert calls(inst.repo)[-1] == {
        "verb": "apply", "argv": calls(inst.repo)[-1]["argv"],
        "payload": [{"message_id": STUCK_ID, "folder_path": HOUSE, "date_prefix": False}],
    }

    # 10b. The Settings card is the same five rows in a 390-wide column, and the
    #      two things it can do are still thumb-sized there (#167).
    p.locator("nav.tabs .tab[data-tab='settings']").tap()
    pcard = p.locator("#archiveCard")
    pcard.locator("summary.collapse-summary").tap()
    expect(pcard).to_have_attribute("open", "")
    expect(pcard.locator(".status-row")).to_have_count(5)
    expect(pcard.locator("#archiveCardMeta")).to_have_text("on")
    expect(pcard.locator("#statusArchiveLast")).to_contain_text("3 filed")
    assert_no_horizontal_overflow(p)
    dismiss_toasts(p)
    # Full page, as story 09's Settings shot is: the pane is taller than 844 px
    # here and the floating pill sits over its last rows, so a viewport shot
    # would have to be scrolled to a position that shows either the card's
    # header word or its button, never both.
    shot(p, shots / "story-24-archive-9-phone.png", full_page=True)
    phone.close()

    # 11. "Run now" starts the same run the tab's button starts, and goes out
    #     while the archiver works. The card's reading is at most one poll old,
    #     so a second press is reachable from a screen that has not caught up
    #     (a run started on another device) — and that press gets the API's own
    #     sentence as a toast, never a console error. Left until last: a second
    #     run re-plans the same three mails and would move the report the steps
    #     above read. It is waited out, so nothing races the shutdown.
    page.get_by_role("tab", name="Settings").click()
    run_now = acard.locator("#archiveRunNow")
    expect(run_now).to_be_enabled()
    run_now.click()
    expect(acard.locator("#archiveCardMeta")).to_have_text("running")
    expect(run_now).to_be_disabled()
    run_now.evaluate("el => { el.disabled = false; el.click(); }")
    expect(page.locator(".toast-error")).to_contain_text("one Outlook, one run at a time")
    # The card polls itself out of "running" — no tab change, no reload.
    expect(run_now).to_be_enabled(timeout=30000)
    expect(acard.locator("#archiveCardMeta")).not_to_have_text("running")
    ctx.close()

    # 12. Both runs are history now, and reading them back needs no archiver at
    #     all — the picker is the whole record. (`limit`, the bound that makes a
    #     first real run safe, is proven over the API in tests/test_archive.py.)
    listed = _get(base, "/api/archive/runs")
    assert listed["count"] == 2 and listed["runs"][1]["planned"] == 7


def _item_id(base: str, run_id: int, message_id: str) -> int:
    return next(i["id"] for i in _items(base, run_id) if i["message_id"] == message_id)
