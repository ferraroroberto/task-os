"""Story 24 — the mail surface: what needs me becomes a task, the rest gets filed.

    Flag an email in Outlook and archive it as usual → Settings' *Capture into
    Inbox* card lands it as an Inbox task carrying its ``.msg`` chip (#98) →
    then, for everything that only needs filing, the **Archive** tab: one
    button runs the batch (#157) with the local model picking the folder
    (#158), the report appears row by row, and each row offers the review level
    its own state allows — *accept* what needed a human, *file / move* into a
    ranked candidate or any other folder with a one-line hint, *revert* a mail
    back into the Inbox (#159).

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
    docs/screenshots/story-24-archive-7-phone.png     the report as cards
    docs/screenshots/story-24-archive-8-phone.png     one card's review menu (dark)
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e._geometry import assert_min_target, assert_no_horizontal_overflow
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

FILED_ID = "boiler@example.invalid"
UNSURE_ID = "ambiguous@example.invalid"
STUCK_ID = "roof@example.invalid"

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
        ])],
        apply=[
            apply_doc([
                apply_result(FILED_ID, HOUSE, files=[HOUSE_FILE]),
                apply_result(STUCK_ID, HOUSE, ok=False, files=[STUCK_FILE], sequence="0043",
                             error={"code": "move_failed",
                                    "message": "the mail could not be moved to Archive"}),
            ]),
            # every later apply is the story's own filing of the unsure mail
            apply_doc([apply_result(UNSURE_ID, BILLS, files=[BILLS_FILE], sequence="0007")]),
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

    # 5. It finishes on its own and the report fills in: one filed, one that
    #    needs a human, one the archiver broke on.
    expect(pane.locator("#archiveRun")).to_be_enabled(timeout=30000)
    expect(pane.locator(".archive-row")).to_have_count(3)
    run_id = _get(base, "/api/archive/runs")["runs"][0]["id"]
    items = _items(base, run_id)
    assert {i["message_id"]: i["status"] for i in items} == {
        FILED_ID: "archived", UNSURE_ID: "needs_review", STUCK_ID: "failed",
    }
    expect(pane.locator("#statusArchiveRun")).to_contain_text(
        "3 mail(s) · 1 filed · 1 need you · 1 failed"
    )
    filed_row, filed_item = _row(page, FILED_ID, items)
    expect(filed_row.locator(".archive-state")).to_have_text("filed")
    expect(filed_row.locator(".archive-dest")).to_have_text("archive › house › heating")
    expect(filed_row.locator(".archive-files a.chip")).to_have_attribute(
        "href", "taskos://open?ref=" + "E%3A%5Carchive%5Chouse%5Cheating%5C0042%20-%20boiler%20service.msg"
    )
    stuck_row, _ = _row(page, STUCK_ID, items)
    expect(stuck_row.locator(".archive-state")).to_have_text("failed")
    expect(stuck_row.locator(".archive-reason")).to_contain_text("move_failed")
    # An `archived` row is finished, not reviewed: the API answers 409 on
    # accept, so the screen does not offer it.
    expect(filed_row.locator(".archive-action", has_text="Accept")).to_have_count(0)
    expect(page.locator("#archiveAcceptAll")).to_have_text("Accept all 2 that need you")
    dismiss_toasts(page)
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
    expect(page.locator("#archiveAcceptAll")).to_be_hidden()
    assert next(i for i in _items(base, run_id) if i["message_id"] == STUCK_ID)["decided_at"]

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
    shot(page, shots / "story-24-archive-6-desktop.png")

    # 9. The Board's Inbox header points at what the run left for a human, and
    #    the palette reaches the tab the same way every other destination is
    #    reached.
    page.emulate_media(color_scheme="light")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.get_by_role("tab", name="Board").click()
    link = page.locator(".board-col[data-col='inbox'] .board-archive-link")
    expect(link).to_have_text("1 mail(s) need you")
    link.click()
    expect(page.locator("#paneArchive")).to_be_visible()
    page.get_by_role("tab", name="Board").click()
    page.click("#paletteBtn")
    page.fill("#paletteInput", ">go to archive")
    page.keyboard.press("Enter")
    expect(page.locator("#paneArchive")).to_be_visible()
    ctx.close()

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
    expect(p.locator(".archive-card")).to_have_count(3)
    expect(p.locator(".archive-table")).to_have_count(0)
    shot(p, shots / "story-24-archive-7-phone.png")

    assert_no_horizontal_overflow(p)
    assert_min_target(p.locator("#archiveRun"))
    assert_min_target(p.locator("#archiveLimit"))

    p.emulate_media(color_scheme="dark")
    p.evaluate("document.documentElement.dataset.theme = 'dark'")
    stuck_card = p.locator(f".archive-card[data-id='{_stuck_id(base, run_id)}']")
    stuck_card.locator(".archive-menu-summary").tap()
    expect(stuck_card.locator(".archive-move-toggle")).to_be_visible()
    # Everything in an open review menu is pressed with a thumb here.
    assert_min_target(stuck_card.locator(".archive-action"))
    shot(p, shots / "story-24-archive-8-phone.png")
    phone.close()

    # 11. The run is history now, and reading it back needs no archiver at all
    #     — the picker is the whole record. (`limit`, the bound that makes a
    #     first real run safe, is proven over the API in tests/test_archive.py;
    #     firing a second run here would only race this instance's shutdown.)
    listed = _get(base, "/api/archive/runs")
    assert listed["count"] == 1 and listed["runs"][0]["planned"] == 3


def _stuck_id(base: str, run_id: int) -> int:
    return next(i["id"] for i in _items(base, run_id) if i["message_id"] == STUCK_ID)
