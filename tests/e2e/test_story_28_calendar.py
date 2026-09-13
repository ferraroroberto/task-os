"""Story 28 — plan the day against the real calendar (issue #96).

    Today, on the desktop, shows today's events from a private ICS address in
    a slim lane beside the task list: all-day events as a strip, timed ones
    with their times, the moved meeting once, the recurring rule it could not
    expand counted — and every way the calendar can fail says so in words,
    never as an empty lane that reads as a free day.

Two disposable instances over the synthetic seed. The plain ``seeded_webapp``
(blank ``calendar.ics_url``, like every other story) shows the lane **off**.
``calendar_webapp`` points ``calendar.ics_url`` at
:class:`tests.fixtures.calendar_fake.FakeCalendar` — a loopback server in this
pytest process serving ``tests/fixtures/calendar/day.ics``, never a real
calendar — whose ``mode`` the story flips to walk the failures in the order a
first-time setup meets them: a refused address, an answer that is not a
calendar, a server that hangs past the 2 s bound, a dropped connection, then
the real feed, then a failure *after* a good fetch (the copy stays, marked).

The four states that need the feed to be broken before anything was fetched
are asserted in text; the shots are the ones a reader needs to see:

    docs/screenshots/story-28-calendar-1-desktop.png  lane off — no calendar connected
    docs/screenshots/story-28-calendar-2-desktop.png  address refused, before any copy
    docs/screenshots/story-28-calendar-3-desktop.png  Settings → Calendar after Refresh now
    docs/screenshots/story-28-calendar-4-desktop.png  today's events beside the tasks
    docs/screenshots/story-28-calendar-5-desktop.png  plan mode with the lane alongside
    docs/screenshots/story-28-calendar-6-desktop.png  a failure after a good fetch (dark)

The walk against the owner's own calendar is recorded **not verified** in
docs/validation/story-28-calendar.md until the owner does it.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _boot,
    _get,
    _terminate,
    dismiss_toasts,
    e2e_workdir,
    shot,
)
from tests.fixtures.calendar_fake import SECRET, FakeCalendar

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
TIMEOUT_S = 2.0


class CalendarInstance:
    def __init__(self, base: str, fake: FakeCalendar) -> None:
        self.base = base
        self.fake = fake


@pytest.fixture(scope="module")
def calendar_webapp() -> Iterator[CalendarInstance]:
    """A seeded disposable instance reading the fake calendar (synthetic feed only)."""
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("calendar")
    seed_db(work / "tasks.db", E2E_ANCHOR)
    with FakeCalendar(mode="404", delay_s=4.0) as fake:
        cfg = write_test_config(work / "config.json",
                                calendar={"ics_url": fake.url, "timeout_seconds": TIMEOUT_S})
        proc, base, log = _boot(work, work / "tasks.db", cfg)
        try:
            yield CalendarInstance(base, fake)
        finally:
            _terminate(proc)
            log.close()


def _refresh(base: str) -> tuple[dict, float]:
    """``POST /api/calendar/refresh`` — the group and how long the answer took."""
    req = urllib.request.Request(f"{base}/api/calendar/refresh", data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=15) as res:
        body = json.loads(res.read().decode("utf-8"))
    return body, time.perf_counter() - started


def _open_today(page: Page, base: str) -> None:
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    expect(page.locator("#paneToday .cal-lane")).to_be_visible()


def _open_calendar_card(page: Page):
    page.get_by_role("tab", name="Settings").click()
    card = page.locator("#calendarCard")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


def test_today_calendar_lane(
    seeded_webapp: str, calendar_webapp: CalendarInstance, browser: Browser, shots: Path
) -> None:
    # 1. No calendar connected: the lane is there and says so — with a reason
    #    in the API, the Settings card and the lane itself.
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        assert _get(seeded_webapp, "/api/today")["calendar"]["state"] == "off"
        assert _get(seeded_webapp, "/api/status")["calendar"]["configured"] is False
        _open_today(page, seeded_webapp)
        lane = page.locator("#paneToday .cal-lane")
        expect(lane).to_have_attribute("data-state", "off")
        expect(lane).to_contain_text("No calendar connected")
        expect(lane.locator(".cal-counts")).to_have_text("off")
        shot(page, shots / "story-28-calendar-1-desktop.png")
        card = _open_calendar_card(page)
        expect(card.locator("#calendarCardMeta")).to_have_text("off")
        expect(card.locator("#statusCalendar")).to_contain_text("not configured")
        expect(card.locator("#calendarRefresh")).to_be_disabled()
    finally:
        context.close()

    base, fake = calendar_webapp.base, calendar_webapp.fake
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 2. The address is refused (HTTP 404) before anything was ever fetched:
        #    a red callout with the reason and since when — not an empty lane.
        _open_today(page, base)
        lane = page.locator("#paneToday .cal-lane")
        expect(lane).to_have_attribute("data-state", "bad_url")
        expect(lane.locator(".cal-notice-title")).to_have_text("Calendar address refused since 09:00")
        expect(lane.locator(".cal-notice-detail")).to_contain_text("HTTP 404")
        expect(lane.locator(".cal-event")).to_have_count(0)
        expect(lane).not_to_contain_text("No events today")
        expect(lane.locator(".cal-counts")).to_have_text("unavailable")
        shot(page, shots / "story-28-calendar-2-desktop.png")

        # 3. An answer that is not a calendar (a sign-in page), through the
        #    Settings card's Refresh now.
        fake.mode = "html"
        card = _open_calendar_card(page)
        expect(card.locator("#calendarRefresh")).to_be_enabled()
        card.locator("#calendarRefresh").click()
        expect(card.locator("#statusCalendar .status-warn")).to_have_text("not a calendar")
        expect(card.locator("#calendarCardMeta")).to_have_text("error")
        page.click("nav.tabs .tab[data-tab='today']")
        expect(lane).to_have_attribute("data-state", "parse_error")
        expect(lane.locator(".cal-notice-title")).to_contain_text("Calendar feed unreadable")

        # 4. A server that hangs: the refresh answers within the bound, and
        #    Today itself never waits on it again inside the retry window.
        fake.mode = "slow"
        group, took = _refresh(base)
        assert group["state"] == "timeout", group
        assert took < TIMEOUT_S + 1.5, f"refresh held the request {took:.2f} s"
        started = time.perf_counter()
        today = _get(base, "/api/today")
        assert time.perf_counter() - started < TIMEOUT_S, "Today waited on a calendar it already knows is down"
        assert today["calendar"]["state"] == "timeout" and today["calendar"]["events"] == []
        _open_today(page, base)
        expect(lane.locator(".cal-notice-title")).to_contain_text("Calendar did not answer in time")

        # 5. A dropped connection is its own state again.
        fake.mode = "drop"
        group, _ = _refresh(base)
        assert group["state"] == "unreachable", group
        _open_today(page, base)
        expect(lane.locator(".cal-notice-title")).to_contain_text("Calendar unreachable since 09:00")

        # 6. The real feed: Refresh now → the card reads it, the lane shows the day.
        fake.mode = "ok"
        card = _open_calendar_card(page)
        card.locator("#calendarRefresh").click()
        expect(card.locator("#statusCalendar .status-ok")).to_have_text("reading")
        expect(card.locator("#statusCalendar")).to_contain_text("6 event(s) today · 1 recurring not checked")
        expect(card.locator("#statusCalendarSource")).to_contain_text("127.0.0.1")
        expect(card.locator("#calendarCardMeta")).to_have_text("on")
        dismiss_toasts(page)
        shot(page, shots / "story-28-calendar-3-desktop.png")

        page.click("nav.tabs .tab[data-tab='today']")
        expect(lane).to_have_attribute("data-state", "ok")
        expect(lane.locator(".cal-chip")).to_have_text(["School holiday", "Team offsite"])
        expect(lane.locator(".cal-time")).to_have_text(["09:30–09:45", "14:00–14:30", "16:30–17:15", "23:00–06:00"])
        expect(lane.locator(".cal-summary")).to_have_text(
            ["Standup", "1:1 with Sam Rivera (moved)", "Dentist, check-up", "Night train"])
        expect(lane.locator(".cal-span")).to_have_text(["ends tomorrow"])
        expect(lane.locator(".cal-note.is-attention")).to_have_text(
            "1 recurring event could not be checked — open the calendar itself to be sure.")
        expect(lane).not_to_contain_text("Gym")               # EXDATE'd today
        expect(lane).not_to_contain_text("Lunch with Jordan")  # cancelled
        expect(lane.locator(".cal-counts")).to_have_text("6 events")
        shot(page, shots / "story-28-calendar-4-desktop.png")

        # 7. Plan mode picks against that day: the lane stays alongside the candidates.
        page.locator("#paneToday .plan-more").click()
        expect(page.locator("#paneToday .plan-picker")).to_be_visible()
        expect(lane.locator(".cal-event")).to_have_count(4)
        pick_box, lane_box = page.locator("#paneToday .plan-picker").bounding_box(), lane.bounding_box()
        assert pick_box and lane_box and lane_box["x"] >= pick_box["x"] + pick_box["width"]
        shot(page, shots / "story-28-calendar-5-desktop.png")
        page.locator("#paneToday .plan-done-btn").click()
        expect(page.locator("#paneToday .plan-picker")).to_have_count(0)

        # The address is a secret: nothing the page or the API holds names it.
        assert SECRET not in page.content()
        assert SECRET not in json.dumps(_get(base, "/api/status")) + json.dumps(_get(base, "/api/today"))
        assert errors == []
    finally:
        context.close()

    # 8. A failure after a good fetch: the copy stays on screen, marked, with the
    #    failure and the time it was fetched beside it (dark).
    fake.mode = "404"
    group, _ = _refresh(base)
    assert group["state"] == "bad_url" and group["stale"] is True and len(group["events"]) == 4
    dark = browser.new_context(viewport=DESKTOP, color_scheme="dark")
    try:
        page = dark.new_page()
        _open_today(page, base)
        lane = page.locator("#paneToday .cal-lane")
        expect(lane.locator(".cal-notice-title")).to_have_text("Calendar address refused since 09:00")
        expect(lane.locator(".cal-notice-detail").last).to_have_text("Showing the copy from 09:00.")
        expect(lane.locator(".cal-event")).to_have_count(4)
        expect(lane.locator(".cal-counts")).to_have_text("stale")
        shot(page, shots / "story-28-calendar-6-desktop.png")
    finally:
        dark.close()

    # The phone skips the lane this pass (#96): not drawn below 1024 px.
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    try:
        page = phone.new_page()
        page.goto(f"{base}/")
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        expect(page.locator("#paneToday section.today").last).to_be_visible()
        expect(page.locator("#paneToday .cal-lane")).to_be_hidden()
    finally:
        phone.close()
