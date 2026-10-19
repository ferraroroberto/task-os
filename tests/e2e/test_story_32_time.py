"""Story 32 — Track time and compare shares (#457).

    Open Time (no "who is this?" step: the tab logs as whoever is signed in,
    #475) → start a timer → switch it → stop and
    save → add time already spent → edit that entry to the other person →
    read Totals, which opens on Home at 30 days → lock in a guess and see the
    other one → in Settings,
    add a category with a subtitle, see it in Log, clear the subtitle, and
    delete the category made by mistake (#463).

One seeded disposable instance (the sample config's placeholder people ``p1``
"Person 1" and ``p2`` "Person 2", the synthetic seed's fortnight of time; the
config carries a token for each, so the phone leg signs in at ``/login`` as the
second person with their own). Its
clock and the browser's are both pinned to ``E2E_NOW``, so a timer started
here reads 0:00 and a stop saves the one-minute floor: the shots never frame a
ticking value. The second device is the API (``page.request``), the way a
phone's request reaches the same server: its timer is independent, a second
start for the same person is a 409, a second stop is a 409 that saves
nothing. Every rule behind those answers is unit-tested in tests/test_time.py;
this walk proves the screen says the same. The Settings leg runs after the
last desktop shot, so it frames nothing: Delete is offered only on a category
nothing points at, and the server refuses a used one with its own code.

Shots:
    docs/screenshots/story-32-time-1-desktop.png  Log: today per person, the running timer
    docs/screenshots/story-32-time-2-desktop.png  History: clock ranges, the moved entry
    docs/screenshots/story-32-time-3-desktop.png  Totals (Home, 30 days by default): head-to-head, guesses revealed
    docs/screenshots/story-32-time-4-phone.png    Log on the phone (dark), signed in as the other person
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect

from tests.conftest import write_test_config
from tests.e2e._geometry import assert_min_target, assert_no_horizontal_overflow
from tests.e2e._surface import surface
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _boot,
    _terminate,
    close_settings_sheet,
    dismiss_toasts,
    e2e_workdir,
    open_settings_sheet,
    shot,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
TODAY = E2E_ANCHOR.isoformat()
OWNER_TOKEN = "e2e-story-32-owner-token"
P2_TOKEN = "e2e-story-32-second-member-token"   # the sample's second member, p2 (#474)
STALE_PERSON_KEY = "task-os.time.person"        # what #457 stored per device; ignored since #475


@pytest.fixture(scope="module")
def member_webapp() -> Iterator[str]:
    """A seeded disposable instance whose config carries a token per member (the owner's and p2's)."""
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("seeded-test_story_32_time")
    seed_db(work / "tasks.db", E2E_ANCHOR)
    cfg = write_test_config(work / "config.json")           # sample, mirror / backup dirs blanked
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["auth"] = {"token": OWNER_TOKEN, "password_hash": "", "people": {"p2": {"token": P2_TOKEN}}}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    proc, base, log = _boot(work, work / "tasks.db", cfg)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


def _start_row(page, name: str):
    """The start-list row for `name` in its area group (the Recent copy is skipped)."""
    return page.locator(f"#timeLog .time-start .action-row-main:not([data-group='recent']):has(.action-row-title:text-is('{name}'))")


def _today(page, base: str) -> dict:
    return page.request.get(f"{base}/api/time/summary?period=today").json()["by_person"]


def test_track_time_and_compare_shares(member_webapp: str, browser: Browser, shots: Path) -> None:
    base = member_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        time_calls: list[str] = []
        page.on("request", lambda r: time_calls.append(r.url) if "/api/time/" in r.url else None)
        page.goto(f"{base}/")
        expect(page.locator("nav.tabs .tab")).to_have_count(4)
        expect(page.locator("nav.tabs .tab .tab-label")).to_have_text(["Today", "Board", "Time", "Search"])
        page.wait_for_load_state("networkidle")
        assert time_calls == [], "Today's load must not touch the time tracker"

        # ---- first visit: no "who is this?" — this PC is the install owner (#475), and the
        # device label an older build stored (here: the other person) changes nothing
        page.evaluate(f"localStorage.setItem('{STALE_PERSON_KEY}', 'p2')")
        page.locator("nav.tabs .tab[data-tab='time']").click()
        expect(page.locator(".home-head h1.home-title")).to_have_text("Time")
        expect(page.locator("#timeViews")).to_be_visible()
        expect(page.locator("#timePicker")).to_be_hidden()
        page.wait_for_function(f"localStorage.getItem('{STALE_PERSON_KEY}') === null")
        assert page.request.get(f"{base}/api/time/meta").json()["you"] == "p1"

        # ---- Log: today per person, then a timer
        glance = page.locator("#timeLog .time-glance")
        expect(glance.locator(".time-glance-value")).to_have_text(["45m", "1h"])
        expect(page.locator("#homeHeadStatus")).to_have_text("45m today")
        _start_row(page, "Cooking and dishes").click()
        timer = page.locator("#timeLog .time-timer")
        expect(timer.locator(".time-timer-cat")).to_have_text("Cooking and dishes")
        expect(timer.locator(".time-clock")).to_have_text("0:00")
        expect(page.locator("#homeHeadStatus")).to_have_text("1 running")

        # the other device: its own timer runs beside ours; a second one for us is refused
        r = page.request.post(f"{base}/api/time/timers", data={"person": "p2", "category_id": 1})
        assert r.status == 201
        twice = page.request.post(f"{base}/api/time/timers", data={"person": "p1", "category_id": 1})
        assert twice.status == 409 and twice.json()["error"]["code"] == "timer_running"
        # a reload keeps both: the timers live on the server
        page.reload()
        expect(timer.locator(".time-timer-cat")).to_have_text("Cooking and dishes")
        expect(glance.locator(".action-row-meta")).to_have_text([
            "Timer running · Cooking and dishes", "Timer running · Kids: care and play"])
        expect(page.locator("#homeHeadStatus")).to_have_text("2 running")
        dismiss_toasts(page)
        shot(page, shots / "story-32-time-1-desktop.png")
        surface(page, "time.log-running")

        # ---- Switch: another category while one runs is one call
        _start_row(page, "Laundry and ironing").click()
        dialog = page.locator("#timeDialog")
        expect(dialog.locator("h2")).to_have_text("A timer is running")
        surface(page, "time.dialog-running")
        dialog.get_by_role("button", name="Stop and start Laundry and ironing").click()
        expect(timer.locator(".time-timer-cat")).to_have_text("Laundry and ironing")
        expect(glance.locator(".time-glance-value").first).to_have_text("46m")   # the 1-minute floor saved

        # ---- Stop and save, once: a second stop from the other device saves nothing
        timer.get_by_role("button", name="Stop and save").click()
        expect(timer).to_have_count(0)
        expect(glance.locator(".time-glance-value").first).to_have_text("47m")
        again = page.request.post(f"{base}/api/time/timers/p1/stop")
        assert again.status == 409 and again.json()["error"]["code"] == "no_timer"
        assert _today(page, base)["p1"] == 47
        assert page.request.delete(f"{base}/api/time/timers/p2").status == 204

        # ---- Add time already spent: 30 minutes of cleaning that just ended
        page.locator("#timeLog .time-add").click()
        expect(dialog.locator("h2")).to_have_text("Add time already spent")
        surface(page, "time.dialog-add")
        dialog.locator("select").select_option(label="Cleaning and tidying")
        dialog.locator(".time-pick", has_text="30").click()
        expect(dialog.locator("input[type='time']")).to_have_value("08:30")      # it ended now (09:00)
        dialog.get_by_role("button", name="Add").click()
        expect(dialog).to_be_hidden()
        assert _today(page, base)["p1"] == 77

        # ---- History: the range on every clocked row; edit the new entry to the other person
        page.locator("#timeViews [data-view='history']").click()
        rows = page.locator("#timeHistory .time-entry")
        added = rows.filter(has_text="Cleaning and tidying").first
        expect(added.locator(".action-row-meta")).to_have_text("08:30 to 09:00 · 30m · Person 1")
        before = _today(page, base)
        added.locator(".action-row-main").click()
        expect(dialog.locator("h2")).to_have_text("Edit entry")
        dialog.locator(".time-person-seg .segmented-item", has_text="Person 2").click()
        dialog.get_by_role("button", name="Save").click()
        expect(dialog).to_be_hidden()
        after = _today(page, base)
        assert after == {"p1": before["p1"] - 30, "p2": before["p2"] + 30}
        moved = rows.filter(has_text="Cleaning and tidying").first
        expect(moved.locator(".action-row-meta")).to_have_text("08:30 to 09:00 · 30m · Person 2")
        # the kebab holds Edit first and Delete last
        moved.locator(".action-row-kebab").click()
        expect(page.locator(".time-menu [role=menuitem]")).to_have_text(["Edit", "Start again", "Delete"])
        page.keyboard.press("Escape")
        dismiss_toasts(page)
        shot(page, shots / "story-32-time-2-desktop.png")

        # ---- Totals opens on Home at 30 days (#463): the comparison, then a guess that reveals the other
        page.locator("#timeViews [data-view='totals']").click()
        expect(page.locator(".time-area")).to_have_value("home")
        expect(page.locator(".time-period .segmented-item[aria-pressed='true']")).to_have_text("30 days")
        compare = page.locator("#timeTotals .time-compare")
        expect(compare).to_be_visible()
        expect(compare.locator(".time-coverage")).to_contain_text("Days with something logged: Person 1")
        guess = page.locator("#timeTotals .time-guess")
        expect(guess.locator("table")).to_have_count(0)               # Person 2's guess stays hidden
        guess.locator("#timeGuessPct").fill("40")
        guess.get_by_role("button", name="Lock in").click()
        expect(guess.locator("table tbody tr")).to_have_count(2)
        expect(guess.locator("table tbody tr").nth(1).locator("td").nth(1)).to_have_text("60%")
        expect(guess.locator(".time-card-note")).to_have_text("The guesses add up to 100%. Accurate views would add up to 100%.")
        csv = page.locator("#timeTotals .time-csv")
        expect(csv).to_have_attribute("href", "/api/time/entries.csv?period=30&area=home")
        dismiss_toasts(page)
        shot(page, shots / "story-32-time-3-desktop.png", full_page=True)
        surface(page, "time.totals")

        # ---- Settings → Time categories: a category with a subtitle, shown in Log; then cleared
        cats = open_settings_sheet(page, "timecats")
        expect(page.locator("[data-settings-sheet='timeperson']")).to_have_count(0)   # no "Time tracking as" row
        menu_items = page.locator(".time-admin-menu [role=menuitem]")
        cats.get_by_role("button", name="Area actions: Home").click()
        menu_items.filter(has_text="Add category").click()
        dialog.get_by_label("Name").fill("Made by mistake")
        dialog.get_by_label("Subtitle").fill("one to delete")
        dialog.get_by_role("button", name="Add").click()
        made = cats.locator(".action-row", has=page.locator(".action-row-title", has_text="Made by mistake"))
        expect(made.locator(".action-row-meta")).to_have_text("one to delete")
        close_settings_sheet(page)
        page.locator("nav.tabs .tab[data-tab='time']").click()
        page.locator("#timeViews [data-view='log']").click()
        expect(_start_row(page, "Made by mistake").locator(".action-row-meta")).to_have_text("one to delete")
        cats = open_settings_sheet(page, "timecats")
        cats.get_by_role("button", name="Category actions: Made by mistake").click()
        menu_items.filter(has_text="Edit").click()
        expect(dialog.get_by_label("Subtitle")).to_have_value("one to delete")
        dialog.get_by_label("Subtitle").fill("")
        dialog.get_by_role("button", name="Save").click()
        expect(made.locator(".action-row-meta")).to_have_count(0)

        # ---- a category made by mistake can be deleted, a used one cannot
        cats.get_by_role("button", name="Category actions: Cooking and dishes").click()
        expect(menu_items.filter(has_text="Delete")).to_have_count(0)        # it has entries: archive only
        page.keyboard.press("Escape")
        cats.get_by_role("button", name="Category actions: Made by mistake").click()
        menu_items.filter(has_text="Delete").click()
        confirm = page.locator("#confirmDialog")
        expect(confirm.locator("h2")).to_have_text("Delete Made by mistake?")
        confirm.get_by_role("button", name="Delete category").click()
        expect(cats.locator(".action-row-title", has_text="Made by mistake")).to_have_count(0)
        used = page.request.delete(f"{base}/api/time/categories/1")
        assert used.status == 409 and used.json()["error"]["code"] == "category_in_use"
        close_settings_sheet(page)
    finally:
        context.close()

    # ---- the phone, signed in as the other person with their own token (dark)
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True,
                                color_scheme="dark")
    try:
        page = phone.new_page()
        page.goto(f"{base}/login")
        page.fill("#loginSecret", P2_TOKEN)
        page.locator("#loginSubmit").tap()
        expect(page.locator("nav.tabs .tab.active")).to_be_visible()      # the shell, signed in
        page.wait_for_load_state("networkidle")
        page.locator("nav.tabs .tab[data-tab='time']").tap()
        expect(page.locator("#timePicker")).to_be_hidden()            # signed in, so no question
        expect(page.locator("#timeLog .time-glance .time-glance-value")).to_have_text(["47m", "1h 30m"])
        # a timer started here is theirs: the server fills the person from the sign-in
        _start_row(page, "Cooking and dishes").tap()
        expect(page.locator("#timeLog .time-timer-cat")).to_have_text("Cooking and dishes")
        assert [t["person"] for t in page.request.get(f"{base}/api/time/timers").json()["items"]] == ["p2"]
        page.locator("#timeLog .time-timer").get_by_role("button", name="Stop and save").tap()
        expect(page.locator("#timeLog .time-timer")).to_have_count(0)
        assert _today(page, base) == {"p1": 47, "p2": 91}             # the one-minute floor, saved as p2
        expect(page.locator("#timeLog .time-glance .time-glance-value")).to_have_text(["47m", "1h 31m"])
        for item in page.locator("#timeViews .segmented-item").all():
            assert_min_target(item)
        assert_no_horizontal_overflow(page)
        dismiss_toasts(page)
        page.evaluate("window.scrollTo(0, 0)")   # the tap on a start row scrolled the page; frame the top
        shot(page, shots / "story-32-time-4-phone.png")
    finally:
        phone.close()
