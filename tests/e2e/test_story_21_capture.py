"""Story 21 — capture into the Inbox (issue #98).

    Flag an email in Outlook and archive it as usual → Settings' *Capture into
    Inbox* card says the poller is on → "Check now" → the flagged mail is an
    Inbox task carrying its ``.msg`` chip, and a second check creates nothing.
    A WhatsApp message the radar marks arrives the same way over
    ``POST /api/tasks`` and replays deduped. An archiver too old to record
    flags is a *visible* not-configured state naming the missing column, never
    a silent "no flagged emails".

Walks the story against **two disposable instances**, both reading a synthetic
archiver index built by ``tests/fixtures/emails_fixture.py`` — never a real
mailbox, and never the real ``emails.db``:

  * the flagged instance (``flags=True``) for the whole capture walk;
  * a pre-flag instance (``flags=False``) for the one shot proving what this
    install shows until the archiver ships the flag columns — the state
    Roberto actually sees first.

1440×900 Chromium then a 390-wide touch context, saving the proof shots the
validation record links to:

    docs/screenshots/story-21-capture-1-desktop.png   Capture card: on, "not yet"
    docs/screenshots/story-21-capture-2-desktop.png   after "Check now": 2 flagged · 2 new
    docs/screenshots/story-21-capture-3-desktop.png   Board Inbox with both captured tasks
    docs/screenshots/story-21-capture-4-desktop.png   drawer: the .msg chip (dark)
    docs/screenshots/story-21-capture-5-phone.png     phone: Inbox
    docs/screenshots/story-21-capture-6-desktop.png   pre-flag archiver: the reason on screen
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e.conftest import (
    INTERCEPT,
    _boot,
    _get,
    _post,
    _terminate,
    e2e_workdir,
    shot,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

KITCHEN = "Kitchen quotes from the installer"
SCHOOL = "School enrolment forms — deadline Friday"


class CaptureInstance:
    def __init__(self, base: str, od: Path, db: Path) -> None:
        self.base = base
        self.od = od
        self.db = db


def _instance(name: str, *, flags: bool) -> Iterator[CaptureInstance]:
    """A disposable instance over a synthetic archiver index, flagged or not."""
    from tests.fixtures.emails_fixture import build_emails_db

    work = e2e_workdir(name)
    od = work / "od"
    od.mkdir(parents=True)
    build_emails_db(work / "emails.db", root=od, flags=flags)
    cfg = write_test_config(
        work / "config.json",
        placeholders={"onedrive": od.as_posix(), "user": "sam"},
        email_db=str(work / "emails.db"),
    )
    proc, base, log = _boot(work, work / "tasks.db", cfg)
    try:
        yield CaptureInstance(base, od, work / "tasks.db")
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="module")
def capture_webapp() -> Iterator[CaptureInstance]:
    """Two of the six fixture emails carry a follow-up flag."""
    yield from _instance("capture", flags=True)


@pytest.fixture(scope="module")
def preflag_webapp() -> Iterator[CaptureInstance]:
    """The same index from an archiver build that never recorded a flag."""
    yield from _instance("capture-preflag", flags=False)


def _post_json(base: str, path: str, body: dict) -> tuple[int, dict]:
    """POST a real JSON body — the radar's own call shape, status included."""
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.status, json.loads(res.read().decode("utf-8"))


def _open_card(page: Page, card_id: str):
    """A Settings card is a collapsed disclosure (#46) — open it like a user would."""
    card = page.locator(f"#{card_id}")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


def test_capture_into_inbox(
    capture_webapp: CaptureInstance, preflag_webapp: CaptureInstance,
    browser: Browser, shots: Path,
) -> None:
    inst = capture_webapp
    base = inst.base

    # The poller is on because the index carries the flag column; nothing has
    # run yet (the first pass is 15 s out — this story fires it by hand so it
    # is deterministic rather than racing the startup thread).
    st = _get(base, "/api/status")["capture"]
    assert st["enabled"] is True and st["reason"] is None
    assert st["last_run"] is None

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(INTERCEPT)
    page: Page = ctx.new_page()
    page.goto(base + "/")

    # 1. Settings → the Capture card is on, and says so before anything has run
    page.get_by_role("tab", name="Settings").click()
    card = _open_card(page, "captureCard")
    expect(card.locator("#captureCardMeta")).to_have_text("on")
    expect(card.locator("#statusCapture .status-ok")).to_have_text("enabled")
    expect(card.locator("#statusCaptureRun")).to_have_text("not yet")
    run_now = card.locator("#captureRunNow")
    expect(run_now).to_be_enabled()
    shot(page, shots / "story-21-capture-1-desktop.png")

    # 2. "Check now" → the two flagged emails land, and the card says what happened
    run_now.click()
    expect(card.locator("#captureCardMeta")).to_have_text("checked")
    expect(card.locator("#statusCaptureRun")).to_contain_text("2 flagged · 2 new")
    shot(page, shots / "story-21-capture-2-desktop.png")

    # 3. …as Inbox tasks on the Board, created by the capture, not by a person
    page.get_by_role("tab", name="Board").click()
    inbox = page.locator(".board-col[data-col='inbox']")
    expect(inbox.locator(".trow-title", has_text=KITCHEN)).to_be_visible()
    expect(inbox.locator(".trow-title", has_text=SCHOOL)).to_be_visible()
    items = _get(base, "/api/tasks?status=inbox")["items"]
    assert {t["title"] for t in items} == {KITCHEN, SCHOOL}
    assert all(t["created_by"] == "email-archiver" for t in items)
    shot(page, shots / "story-21-capture-3-desktop.png")

    # 4. the task carries the .msg the opener chip opens (dark, for the record)
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    inbox.locator(".trow-main", has_text=KITCHEN).first.click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value(KITCHEN)
    chip = drawer.locator(".link-row a.chip").first
    expect(chip).to_contain_text("2026-08-10 Kitchen quotes.msg")
    expect(chip).to_have_attribute(
        "href",
        "taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse%2F2026-08-10%20Kitchen%20quotes.msg",
    )
    shot(page, shots / "story-21-capture-4-desktop.png")
    chip.click()
    assert page.evaluate("window.__taskosClicks")[-1].startswith("taskos://open?ref=%7Bonedrive%7D")
    page.keyboard.press("Escape")

    # 5. a second check creates nothing — flagging twice is not two tasks
    again = _post(base, "/api/capture/email/run")
    assert again == {"listed": 2, "created": 0, "unchanged": 2, "errors": [], "created_ids": []}
    assert _get(base, "/api/tasks?status=inbox")["count"] == 2

    # …and clearing the flag in Outlook never takes the task away again
    import sqlite3
    c = sqlite3.connect(str(inst.od.parent / "emails.db"))
    c.execute("UPDATE emails SET flag_status = 0")
    c.commit()
    c.close()
    assert _post(base, "/api/capture/email/run")["listed"] == 0
    assert _get(base, "/api/tasks?status=inbox")["count"] == 2

    # 6. the WhatsApp half: the radar's own POST shape, and its replay
    wa = {
        "title": "Bring the enrolment forms on Friday",
        "description": "From WhatsApp: a parent · the school group · 2026-08-14T18:22:00",
        "external_id": "wa:msg-4471",
        "actor": "whatsapp-radar",
    }
    status, made = _post_json(base, "/api/tasks", wa)
    assert status == 201 and made["status"] == "inbox"
    replay_status, replayed = _post_json(base, "/api/tasks", wa)
    assert replay_status == 200 and replayed["id"] == made["id"]
    assert _get(base, "/api/tasks?status=inbox")["count"] == 3

    ctx.close()

    # 7. phone: the captured items are just Inbox tasks — one column, the pill
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    phone.add_init_script(INTERCEPT)
    p = phone.new_page()
    p.goto(base + "/")
    p.get_by_role("tab", name="Board").click()
    expect(p.locator("#paneBoard")).to_be_visible()
    expect(p.locator(".board-col[data-col='inbox'] .trow-title", has_text=KITCHEN)).to_be_visible()
    shot(p, shots / "story-21-capture-5-phone.png")
    phone.close()

    # 8. the state this install shows until the archiver records flags: the
    #    reason names the missing column, and "Check now" stays disabled.
    off = _get(preflag_webapp.base, "/api/status")["capture"]
    assert off["enabled"] is False and "flag_status" in off["reason"]

    ctx2 = browser.new_context(viewport=DESKTOP, color_scheme="light")
    p2: Page = ctx2.new_page()
    p2.goto(preflag_webapp.base + "/")
    p2.get_by_role("tab", name="Settings").click()
    card2 = _open_card(p2, "captureCard")
    expect(card2.locator("#captureCardMeta")).to_have_text("off")
    expect(card2.locator("#statusCapture .status-off")).to_have_text("not configured")
    expect(card2.locator("#statusCapture")).to_contain_text("flag_status")
    expect(card2.locator("#captureRunNow")).to_be_disabled()
    shot(p2, shots / "story-21-capture-6-desktop.png")
    ctx2.close()
