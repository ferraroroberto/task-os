"""Story 05 — Board day (Step 5/13, issue #6).

    Board tab: the week planner (#396) — Today · Tomorrow · This week · This
    weekend · Next week · Later (the undated tasks closing it) side by side with
    no sideways scroll at 1280 / 1920 / 1440px (#414), the header naming the
    Inbox arrivals and what is overdue — and a drag between two lanes changes
    the due date and nothing else (Undo puts it back) → the Status segment:
    four columns visible at once on the laptop → the top strip's
    text filter narrows the board without opening any disclosure and the +
    opens the quick-add dialog (#80) → project chip
    filters to one project (shared with Today, encoded in the URL) → drag
    a row todo → standby → the counts update and the activity log has the
    row → Today tab lists due / overdue grouped by project, sorted by due
    then priority within a group → mark a recurring task complete → its due
    rolls a cadence forward and it
    leaves Today's due list, then mark it done instead → it closes for good
    (issue #54) → mark a plain task done → it lands in the Board's Done
    today.

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-05-board-{1..7}-desktop.png
    docs/screenshots/story-05-board-{10..12}-desktop.png   (§ #81, below)
    docs/screenshots/story-05-board-14-desktop.png          (Week mode, #396)

then the phone at 390×844 (WebKit, touch) — Today as the landing tab, the
Board's Week mode as one list of lane sections and its Status mode as a
one-column scroll-snap carousel — with the geometry checks:

    docs/screenshots/story-05-board-8-phone.png   (Today, the landing tab)
    docs/screenshots/story-05-board-9-phone.png   (Board carousel, one column)
    docs/screenshots/story-05-board-14-phone.png  (Board Week mode, one list)
    docs/screenshots/story-05-board-10-phone.png  (§ #81 Select mode + bulk bar)
    docs/screenshots/story-05-board-15-{desktop,phone}.png  (§ #476 the drawer's Owner)
    docs/screenshots/story-05-board-16-desktop.png          (§ #477 Everyone on the Board)
    docs/screenshots/story-05-board-{17,18}-phone.png       (§ #477 a second member's phone: Mine, Everyone)
    docs/screenshots/story-05-board-19-phone-dark.png       (§ #477 their Board, dark)

§ #81 (multi-select, folded into this story rather than a 15th e2e test, the
way #77 rides inside story 09): Select mode across Board and Today over ONE
selection store, the bulk status / due actions, and the partial-failure
report. Story 12 in ``docs/validation.md`` points here.

§ #476 (an owner per task, same reason): the bulk bar's Set owner… hands a
selection to the second member in one pick, and the drawer's Owner — in the
head beside status and priority, on the desktop panel and the phone's
full-screen drawer — hands one task over, logs ``owner old → new`` by name,
and a reload keeps it.

§ #477 (Mine · Everyone, same reason): the pages open on the signed-in member's
own tasks, so the tasks the bulk bar just handed to the second member leave
the Board and Everyone — one tap, kept per device and mirrored in ``?whose=`` —
brings them back (``_walk_whose_switch``); a phone signed in as that second
member (the owner's loopback is member one) lands on their own tasks, taps
Everyone, reloads and is still on it while a second device is unaffected
(``_walk_second_member_phone``); an install with one member has no switch at all
(``_walk_one_member``). The existing scope reads Tasks · Issues · All.

§ #99 (``_walk_keyboard_actions``, same reason): a keyboard-only triage —
the row keys and their undo, the inert-while-typing and inert-while-the-
drawer-is-open guards, the same keys over a selection, the `?` sheet and the
palette entries that carry them. Story 16 points here.

    docs/screenshots/story-16-keyboard-triage-{1..5}-desktop.png

§ #102 (``_walk_done_journal``, same reason): the done journal — reached
from the Done column's link and the palette, days newest first with counts,
the seed's own closings (yesterday · two days back with a cancelled row ·
the week before), the cancelled switch, the shared filters riding the URL
with the status / due / modified / sort controls hidden, "the week before"
loading older weeks down to the seed's first closing day, the drawer under
``#journal/task/<id>``, and a tab press leaving. Story 18 points here.

    docs/screenshots/story-18-done-journal-{1,2}-desktop.png
    docs/screenshots/story-18-done-journal-3-phone.png   (phone leg, below)

§ #121 (``_walk_delete_task``, same reason): deleting a task — the drawer's
Delete and its confirmation naming the task and the subtree that goes with
it, cancel leaving everything untouched, confirm closing the drawer with a
toast and a 404 behind it, then the Select bar's delete over a batch of
mistakes. The walk makes its own tasks over the API so the seed stays whole.
Story 19 points here.

    docs/screenshots/story-19-delete-task-{1,2}-desktop.png

§ #350 (``_walk_today_horizons``, same reason): with the Table gone no open
task may be out of reach, so Today lists them all in four horizons — Today,
Soon, Later, No date — and a task due a year out and a task with no date are
both reached from Today, by scrolling and by the text filter. Story 31 points
here. § #391 rides the same walk: the horizons under `overline` headers with
their counts, the Mine · Issues · All switch (Mine by default, the pick kept
in the URL across a reload) and project sub-headers only where two or more
groups need telling apart. § #393: Later and No date start folded with their
counts (one tap opens each, and a re-render keeps it open), a text filter
opens them, and the due rows carry no header of their own: the page header
names them, and the open count is the text field's placeholder.

    docs/screenshots/story-31-today-horizons-{1,2,3,4}-desktop.png

§ #321 (``_walk_edit_refresh``, same reason): an edit the server confirmed shows
on every visible row without a reload even when an earlier refresh is still in
flight — the title edited with the list reads held back, the due date edited
before they arrive, then both rows (Board, Today) are checked once the late
answers land. No screenshots: the proof is the rows.

UX round 3 (issue #46, the row slimmed by #311): every view renders the ONE
task row (``.trow`` — completion circle, title with its one-line passive meta,
the Move verb on a fine pointer outside the Board's columns (#392), ⋯ kebab)
and shares ONE filter state; "ticking" is the row's circle, on every
pointer, and every other action (status, date, snooze, priority, folder,
AI, issue) is a ⋯ menu item. Today's done tasks ride in the shared list only
for the Board's Done today column: Today keeps showing open tasks (as the
filter sheet says), so a task finished today leaves the Today
list and appears in the Board's Done today column.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._board_steps import (
    DESKTOP,
    PHONE,
    _assert_scope_switch_spans_row,
    _bulk_move_and_partial_failure,
    _bulk_status_and_owner,
    _clear_toasts,
    _complete_recurring_then_done,
    _drag_row_and_open_drawer,
    _move_verb_apply,
    _move_verb_sheet,
    _project_filter,
    _select_three_cards,
    _status_columns,
    _today_due_list,
    _today_row,
    _top_strip,
    _walk_drawer_owner,
    _week_lane_drag_and_clear,
    _week_lanes,
)
from tests.e2e._board_walks import (
    _walk_done_journal,
    _walk_keyboard_actions,
    _walk_phone_today_landing_and_board_carousel,
)
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e._surface import surface
from tests.e2e.conftest import (
    E2E_ANCHOR,
    E2E_P2_TOKEN,
    _get,
    booted,
    e2e_workdir,
    scroll_to_bottom,
    settle,
    shot,
)

# ----------------------------------------------------------- desktop leg

def test_desktop_board_day(
    seeded_webapp: str, authed_webapp: str, browser: Browser, playwright: Playwright, shots: Path
) -> None:
    """The desktop walk, then the phone leg on the same instance.

    One collected test, not two: the phone leg was its own test function until
    Step 12's team story needed a slot under the e2e budget (CLAUDE.md), so it
    is folded in here — same steps, same order, same shots.
    """
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        _week_lanes(page, base)
        _week_lane_drag_and_clear(page, base, shots)
        api = _status_columns(page, base, shots)
        surface(page, "board.columns")
        _top_strip(page, base)
        _project_filter(page, base, shots, api)
        _drag_row_and_open_drawer(page, base, shots, api)
        today, head, soon, school = _today_due_list(page, base, shots)
        surface(page, "today.soon")
        sheet, sid = _move_verb_sheet(page, base, shots, school)
        surface(page, "today.date-popover")
        _move_verb_apply(page, base, sheet, sid)
        _complete_recurring_then_done(page, base, shots, today, head, soon)
        ids = _select_three_cards(page, base, shots)
        surface(page, "board.select-bar")
        _bulk_status_and_owner(page, base, shots, ids)
        _bulk_move_and_partial_failure(page, base, shots, ids)

        # 15. The drawer's Owner (#476): in the head beside status and
        #     priority, it hands one task back; the log names both members,
        #     and a reload keeps the pick.
        _walk_drawer_owner(page, base, ids[2], "p1")
        shot(page, shots / "story-05-board-15-desktop.png")
        page.keyboard.press("Escape")                    # the row keys are inert under the drawer
        expect(page.locator("#taskDrawer")).to_be_hidden()

        _walk_whose_switch(page, base, shots, ids[0])

        _walk_keyboard_actions(page, base, shots)
        _walk_done_journal(page, base, shots)
        _walk_delete_task(page, base, shots)
        _walk_edit_refresh(page, base)
        _walk_today_horizons(page, base, shots)
        assert errors == [], errors
    finally:
        context.close()
    _walk_phone_today_landing_and_board_carousel(base, playwright, shots)
    _walk_second_member_phone(authed_webapp, playwright, shots)
    _walk_one_member(playwright)


_JSON = {"content-type": "application/json"}


def _walk_whose_switch(page: Page, base: str, shots: Path, handed: int) -> None:
    """§ #477 — Mine · Everyone on the Board (Today shares the key), as the owner.

    Step 11c left this device on Everyone with the second member's task
    ``handed`` on the Board. The pick is the device's (``task-os.whose``) and
    the URL's (``?whose=everyone``, Mine writing no key); an explicit URL value
    beats the stored one, and reading a link never rewrites the device's pick.
    The journal follows the switch. Leaves the device on Mine, the task back
    with the owner, as the rest of the story expects.
    """
    switch = page.locator("#boardWhose .segmented.whose-switch")
    item = lambda who: switch.locator(f".segmented-item[data-whose='{who}']")  # noqa: E731
    pressed = switch.locator(".segmented-item[aria-pressed='true']")
    row = page.locator(f"#paneBoard .trow[data-id='{handed}']")
    stored = "() => localStorage.getItem('task-os.whose')"

    def board(url: str) -> None:
        page.goto(f"{base}{url}")
        page.click("nav.tabs .tab[data-tab='board']")

    def hand(task_id: int, owner: str) -> None:
        res = page.request.post(f"{base}/api/tasks/bulk", data=json.dumps({"ids": [task_id], "owner": owner}),
                                headers=_JSON)
        assert res.ok, res.status

    # 1. Everyone, from step 11c: on the URL, on the device, the row on the Board
    expect(pressed).to_have_text("Everyone")
    expect(page).to_have_url(re.compile(r"[?&]whose=everyone"))
    assert page.evaluate(stored) == "everyone"
    expect(row).to_be_visible()
    expect(switch.locator(".segmented-item")).to_have_text(["Mine", "Everyone"])
    _clear_toasts(page)
    shot(page, shots / "story-05-board-16-desktop.png")
    # 2. the scope beside it reads Tasks · Issues · All and is its own axis
    expect(page.locator("#boardScope .scope-switch .segmented-item")).to_have_text(["Tasks", "Issues", "All"])
    # 3. a reload keeps Everyone even with the key gone from the address
    board("/")
    expect(pressed).to_have_text("Everyone")
    expect(row).to_be_visible()
    # 4. an explicit ?whose=mine beats the stored Everyone, and only the tap
    #    rewrites the device's pick
    board("/?whose=mine")
    expect(pressed).to_have_text("Mine")
    expect(row).to_have_count(0)
    assert page.evaluate(stored) == "everyone"
    # 5. …the journal follows: a closed task of the second member's is off it on
    #    Mine and on it under Everyone (the seed's, handed over and back)
    kettle = _get(base, "/api/tasks?q=descale%20the%20kettle&include_closed=true")["items"][0]
    hand(kettle["id"], "p2")
    journal_row = page.locator("#journalHost .trow", has=page.locator(".trow-title", has_text="Descale the kettle"))
    page.goto(f"{base}/?whose=mine#journal")
    expect(page.locator("#paneJournal")).to_be_visible()
    expect(page.locator("#journalHost .trow").first).to_be_visible()
    expect(journal_row).to_have_count(0)
    page.goto(f"{base}/?whose=everyone#journal")
    expect(journal_row).to_have_count(1)
    hand(kettle["id"], "p1")
    # 6. Mine by the tap, then an explicit ?whose=everyone beats the stored Mine
    board("/?whose=mine")
    item("everyone").click()
    item("mine").click()
    assert page.evaluate(stored) == "mine"
    expect(page).not_to_have_url(re.compile(r"[?&]whose="))
    board("/?whose=everyone")
    expect(pressed).to_have_text("Everyone")
    expect(row).to_be_visible()
    assert page.evaluate(stored) == "mine"
    # 7. the way back: the task to the owner, the device on Mine, no key
    hand(handed, "p1")
    board("/")
    expect(pressed).to_have_text("Mine")
    expect(row).to_be_visible()


_LABELS_FIT_JS = """sel => [...document.querySelectorAll(sel)].filter(b => b.offsetParent).map(b => {
  const r = document.createRange(); r.selectNodeContents(b);
  const t = r.getBoundingClientRect(), box = b.getBoundingClientRect();
  return t.left >= box.left - 0.5 && t.right <= box.right + 0.5;
})"""


def _assert_labels_fit(page: Page, selector: str) -> None:
    """Every segment's label sits inside its own segment (a crowded row ran
    "Mine" into "Everyone" on a phone while every box still met the 44px rule)."""
    fits = page.evaluate(_LABELS_FIT_JS, selector)
    assert fits and all(fits), (selector, fits)


def _second_member_sees_their_own(context, base: str, shots: Path, owners, title):
    """Steps 1-3: the second member's phone lists and edits only their own tasks."""
    try:
        page = context.new_page()
        page.goto(f"{base}/")
        assert page.request.get(f"{base}/api/me").json()["id"] == "p2"
        # 1. no picker: Today opens on their own tasks, the switch says Mine
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        whose = page.locator("#todayWhose .segmented.whose-switch")
        pressed = whose.locator(".segmented-item[aria-pressed='true']")
        expect(pressed).to_have_text("Mine")
        expect(page.locator("#todayScope .scope-switch .segmented-item")).to_have_text(["Tasks", "Issues", "All"])
        for title in ("Water the ferns", "Order paint samples"):
            expect(_today_row(page, title)).to_be_visible()
        assert owners(page) == {"p2"}
        expect(page).not_to_have_url(re.compile(r"[?&]whose="))
        assert_min_target(page.locator("#todayWhose .segmented-item, #todayScope .segmented-item"))
        assert_no_overlap(page.locator("#todayWhose .segmented-item, #todayScope .segmented-item"))
        _assert_labels_fit(page, "#todayWhose .segmented-item, #todayScope .segmented-item")
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-17-phone.png")
        # 2. one tap on Everyone: both members' tasks, the choice in the URL and on the device
        whose.locator(".segmented-item[data-whose='everyone']").tap()
        expect(pressed).to_have_text("Everyone")
        expect(page).to_have_url(re.compile(r"[?&]whose=everyone"))
        page.wait_for_function("() => document.querySelectorAll('#paneToday .trow[data-id]').length > 2")
        assert owners(page) == {"p1", "p2"}
        shot(page, shots / "story-05-board-18-phone.png")
        # 3. the pick follows to the Board (one filter state) and survives a reload
        page.click("nav.tabs .tab[data-tab='board']")
        expect(page.locator("#boardWhose .whose-switch .segmented-item[aria-pressed='true']")).to_have_text("Everyone")
        assert_min_target(page.locator("#boardWhose .segmented-item, #boardScope .segmented-item"))
        _assert_labels_fit(page, "#boardBar .segmented-item")
        assert_no_horizontal_overflow(page)
        page.goto(f"{base}/")
        page.click("nav.tabs .tab[data-tab='today']")
        expect(pressed).to_have_text("Everyone")
        page.wait_for_function("() => document.querySelectorAll('#paneToday .trow[data-id]').length > 2")
        assert owners(page) == {"p1", "p2"}
    finally:
        context.close()
    return page


def _owner_phone_is_unaffected(page: Page, base: str, shots: Path, owners, phone) -> None:
    """Step 4: a second device, the owner's phone, is unaffected."""
    # 4. a second device is unaffected: the owner's phone (no member token, a
    #    fresh store) opens on Mine, the owner's tasks, none of theirs
    other = phone(member=False)
    try:
        page = other.new_page()
        page.goto(f"{base}/")
        assert page.request.get(f"{base}/api/me").json()["id"] == "p1"
        expect(page.locator("#todayWhose .whose-switch .segmented-item[aria-pressed='true']")).to_have_text("Mine")
        expect(page.locator("#paneToday .trow[data-id]").first).to_be_visible()
        assert owners(page) == {"p1"}
        expect(_today_row(page, "Water the ferns")).to_have_count(0)
    finally:
        other.close()
    # 5. dark: the switch beside the scope on the second member's Board
    dark = phone("dark")
    try:
        page = dark.new_page()
        page.goto(f"{base}/")
        page.click("nav.tabs .tab[data-tab='board']")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(page.locator("#boardWhose .whose-switch")).to_be_visible()
        assert_min_target(page.locator("#boardWhose .segmented-item, #boardScope .segmented-item"))
        _assert_labels_fit(page, "#boardBar .segmented-item")
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-19-phone-dark.png")
    finally:
        dark.close()


def _walk_second_member_phone(base: str, playwright: Playwright, shots: Path) -> None:
    """§ #477 — a phone signed in as the second member: no picker step, their own
    tasks first, Everyone one tap, kept across a reload and per device.

    ``base`` is the instance with a token for each member. The owner's loopback
    browser is member one; presenting the second member's token (the cookie the
    /login page sets) makes this one member two. Two tasks are theirs; the seed's
    are the owner's. Search covers everyone either way (story 10).
    """
    api = playwright.request.new_context(base_url=base)
    try:
        for title in ("Water the ferns", "Order paint samples"):
            res = api.post("/api/tasks", data={"title": title, "owner": "p2", "due": E2E_ANCHOR.isoformat()})
            assert res.ok, res.status
    finally:
        api.dispose()
    try:
        wk = playwright.webkit.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — a missing browser is a hard failure, named
        pytest.fail(f"WebKit is required for the phone leg: {exc}")
    try:
        def phone(scheme: str = "light", *, member: bool = True):
            ctx = wk.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True,
                                 color_scheme=scheme)
            if member:
                ctx.add_cookies([{"name": "taskos_token", "value": E2E_P2_TOKEN, "url": base}])
            return ctx

        def owners(page: Page) -> set[str]:
            ids = page.locator("#paneToday .trow[data-id]").evaluate_all("els => els.map(e => e.dataset.id)")
            assert ids, "Today shows rows"
            return {_get(base, f"/api/tasks/{i}")["owner"] for i in ids}

        context = phone()
        page = _second_member_sees_their_own(context, base, shots, owners, title)
        _owner_phone_is_unaffected(page, base, shots, owners, phone)
    finally:
        wk.close()


def _walk_one_member(playwright: Playwright) -> None:
    """§ #477 — an install with one member has no Mine · Everyone switch, and
    Today and the Board read as before apart from the scope's renamed label.
    A throwaway instance on the sample with its second member removed."""
    from tests.conftest import write_test_config
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("one-member")
    seed_db(work / "tasks.db", E2E_ANCHOR)
    cfg = write_test_config(work / "config.json")
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["time"]["people"] = raw["time"]["people"][:1]
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    with booted(work, work / "tasks.db", cfg) as base:
        assert len(_get(base, "/api/me")["people"]) == 1
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport=DESKTOP)
            page.goto(f"{base}/")
            expect(page.locator("#todayScope .scope-switch .segmented-item")).to_have_text(["Tasks", "Issues", "All"])
            expect(page.locator("#paneToday .trow[data-id]").first).to_be_visible()
            expect(page.locator(".whose-switch")).to_have_count(0)
            expect(page.locator("#todayWhose")).to_be_hidden()
            page.click("nav.tabs .tab[data-tab='board']")
            expect(page.locator("#boardScope .scope-switch")).to_be_visible()
            expect(page.locator(".whose-switch")).to_have_count(0)
            expect(page.locator("#paneBoard .trow[data-id]").first).to_be_visible()
        finally:
            browser.close()


def _status(page: Page, base: str, path: str) -> int:
    """The HTTP status of a GET — for the 404 a deleted task must answer with
    (`_get` raises on 4xx, which is the wrong shape for that assertion)."""
    return page.evaluate("p => fetch(p).then(r => r.status)", path)


def _walk_delete_task(page: Page, base: str, shots: Path) -> None:
    """§ #121 — delete a task from the drawer, then a batch from the Select bar.

    The walk makes its own tasks over the API (a small project with two
    children, two loose mistakes) so nothing the seed proves elsewhere is
    touched; a reload on the deep link brings the Board up to date.
    """
    mk = lambda body: page.evaluate(  # noqa: E731
        "b => fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
        "body: JSON.stringify(b)}).then(r => r.json())", body)
    fence = mk({"title": "Repaint the garden fence", "status": "todo"})["id"]
    kid = mk({"title": "Buy the primer", "parent_id": fence})["id"]
    mk({"title": "Sand the posts", "parent_id": fence})
    dupe = mk({"title": "Repaint the fence (duplicate)"})["id"]
    test = mk({"title": "test task, ignore"})["id"]

    # 1. The drawer's foot carries Delete; the dialog names the task and its subtree.
    _clear_toasts(page)
    page.goto(f"{base}/#task/{fence}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Repaint the garden fence")
    # The drawer is its own scroller and Delete sits at its foot, so the click
    # would scroll the panel by however much the layout happened to need at
    # that instant — and the Issue section below it arrives on a fetch. The
    # shot behind the dialog was then a coin toss between two offsets: 163,962
    # px apart between two runs of one commit (#225). Park it at the end first
    # and prove it stayed there (#166), so the click scrolls nothing.
    scroll_to_bottom(page, drawer)
    drawer.locator(".drawer-delete").click()
    dialog = page.locator("#confirmDialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#confirmTitle")).to_have_text('Delete "Repaint the garden fence"?')
    expect(dialog.locator(".confirm-body")).to_contain_text("Its 2 child tasks go with it.")
    expect(dialog.locator(".confirm-body")).to_contain_text("cannot be undone")
    expect(dialog.locator(".confirm-warn")).to_have_count(0)     # not a synced coding task
    shot(page, shots / "story-19-delete-task-1-desktop.png")
    surface(page, "app.confirm-delete")

    # 2. Escape is "no": the drawer stays, the task is still there.
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(drawer).to_be_visible()
    assert _status(page, base, f"/api/tasks/{fence}") == 200

    # 3. Confirm: the subtree is gone, the drawer closes, the hash clears, a toast says how much.
    drawer.locator(".drawer-delete").click()
    expect(dialog).to_be_visible()
    dialog.locator(".button-tint.danger").click()
    expect(dialog).to_be_hidden()
    expect(drawer).to_be_hidden()
    assert page.evaluate("location.hash") == ""
    expect(page.locator(".toasts")).to_contain_text('Deleted "Repaint the garden fence" · 3 tasks')
    assert _status(page, base, f"/api/tasks/{fence}") == 404
    assert _status(page, base, f"/api/tasks/{kid}") == 404
    expect(page.locator(f"#boardHost .trow[data-id='{fence}']")).to_have_count(0)

    # 4. A batch of mistakes from the Board's Select bar: one dialog with the count.
    _clear_toasts(page)
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator(f"#boardHost .trow[data-id='{dupe}']")).to_be_visible()
    page.click("#paneBoard [data-select-toggle]")
    page.locator(f"#boardHost .trow[data-id='{dupe}'] .trow-check").check()
    page.locator(f"#boardHost .trow[data-id='{test}'] .trow-check").check()
    page.locator("#boardBulk .bulk-delete").click()
    expect(dialog).to_be_visible()
    expect(dialog.locator("#confirmTitle")).to_have_text("Delete 2 tasks?")
    shot(page, shots / "story-19-delete-task-2-desktop.png")
    dialog.locator(".button-tint.danger").click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".toasts")).to_contain_text("2 tasks deleted")
    expect(page.locator(f"#boardHost .trow[data-id='{dupe}']")).to_have_count(0)
    expect(page.locator(f"#boardHost .trow[data-id='{test}']")).to_have_count(0)
    assert _status(page, base, f"/api/tasks/{dupe}") == 404
    # a clean batch clears the selection but stays in Select mode; leave it as found
    expect(page.locator("#boardBulk")).to_be_hidden()
    page.click("#paneBoard [data-select-toggle]")
    expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "false")


# Wraps the page's own fetch so a list read is answered by the server at once
# and handed to the app late — the order the network does not promise (#321).
# In the page, not a Playwright route: a route handler that sleeps is a callback
# in flight, and one still sleeping when the context closes fails the teardown.
_HOLD_LIST_READS = r"""() => {
  const real = window.fetch.bind(window);
  const hold = window.__hold = {on: false, held: 0, delivered: 0};
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init && init.method) || 'GET';
    const lists = /\/api\/(tasks\?|tasks\/tree|today)/.test(url);
    if (!hold.on || method !== 'GET' || !lists) return real(input, init);
    hold.held += 1;
    return real(input, init).then(function (res) {
      return new Promise(function (resolve) {
        setTimeout(function () { hold.delivered += 1; resolve(res); }, 1500);
      });
    });
  };
}"""


def _walk_today_horizons(page: Page, base: str, shots: Path) -> None:
    """§ #350 (story 31) — no open task is out of Today's reach.

    With the Table gone, Today lists every open task in four horizons — Today,
    Soon (the next seven days), Later and No date — and the strip's text filter
    works across all of them. A task due a year out and a task with no date are
    reached from Today by scrolling, then each by its text alone. The walk makes
    both over the API and deletes them after, so the seed stays whole.
    """
    def make(body: dict) -> int:
        return page.evaluate(
            "b => fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
            "body: JSON.stringify(b)}).then(r => r.json()).then(t => t.id)", body)

    far_due = (E2E_ANCHOR + timedelta(days=365)).isoformat()
    far = make({"title": "Renew the residence card", "due": far_due, "status": "todo"})
    loose = make({"title": "Sort the attic boxes", "status": "todo"})
    try:
        page.goto(f"{base}/")
        page.click("nav.tabs .tab[data-tab='today']")
        pane = page.locator("#paneToday")
        # 1. Later and No date start closed with their counts (#393, decision 6
        #    of #390); one tap opens each, and a re-render keeps it open.
        later = pane.locator(".today-far")
        nodate = pane.locator(".today-nodate")
        assert later.evaluate("el => el.open") is False and nodate.evaluate("el => el.open") is False
        expect(pane.locator(".today-soon")).to_have_js_property("open", True)
        _clear_toasts(page)
        nodate.scroll_into_view_if_needed()
        shot(page, shots / "story-31-today-horizons-4-desktop.png")      # folded, counts showing
        for horizon in (later, nodate):
            n = int(horizon.locator(".section-count").inner_text())
            assert n == horizon.locator(".trow[data-id]").count() and n >= 1
            horizon.locator(".collapse-summary").click()
            expect(horizon).to_have_js_property("open", True)
        page.locator("#paneToday .scope-switch .segmented-item").nth(2).click()   # All: a re-render
        page.locator("#paneToday .scope-switch .segmented-item").nth(0).click()   # back to Mine
        expect(later).to_have_js_property("open", True)
        expect(nodate).to_have_js_property("open", True)
        far_row = later.locator(f".trow[data-id='{far}']")
        loose_row = nodate.locator(f".trow[data-id='{loose}']")
        far_row.scroll_into_view_if_needed()
        expect(far_row).to_be_in_viewport()
        expect(far_row.locator(".trow-due")).to_have_attribute("title", far_due)
        loose_row.scroll_into_view_if_needed()
        expect(loose_row).to_be_in_viewport()
        expect(loose_row.locator(".trow-due")).to_have_count(0)
        # the horizons come in order, nearest first, and every open task the
        # filter shows is in exactly one of them; each header is the overline
        # role (caps from CSS, so the text itself stays sentence case) with its
        # count beside it (#391)
        heads = pane.locator(".today-horizon .collapse-title")
        order = heads.evaluate_all("els => els.map(e => e.textContent)")
        assert order == ["Soon", "Later", "No date"], order
        assert heads.evaluate_all("els => els.every(e => e.classList.contains('overline') "
                                  "&& getComputedStyle(e).textTransform === 'uppercase')")
        expect(later.locator(".section-count")).to_have_text(re.compile(r"^\d+$"))
        _clear_toasts(page)
        nodate.scroll_into_view_if_needed()
        shot(page, shots / "story-31-today-horizons-1-desktop.png")
        # 2. The text filter reaches both from the top strip
        q = page.locator("#todayFilterText .filter-q")
        listed = pane.locator(".today-group .trow[data-id]")
        q.fill("residence card")
        expect(listed).to_have_count(1)
        expect(later.locator(f".trow[data-id='{far}']")).to_be_visible()
        q.fill("attic")
        expect(listed).to_have_count(1)
        expect(nodate.locator(f".trow[data-id='{loose}']")).to_be_visible()
        expect(page).to_have_url(re.compile(r"[?&]q=attic"))
        # under a text filter an empty section says nothing matches it, never
        # "all clear": the day may be full, the filter just hides it (#339)
        for empty in (pane.locator("section.today .empty-state"), pane.locator(".today-soon .empty-state")):
            expect(empty).to_contain_text("matches “attic”")
            expect(empty).not_to_contain_text("all clear")
        nodate.locator(f".trow[data-id='{loose}']").scroll_into_view_if_needed()
        shot(page, shots / "story-31-today-horizons-2-desktop.png")
        q.fill("")
        _walk_scope_switch(page, base, shots)
    finally:
        for tid in (far, loose):
            page.evaluate("id => fetch('/api/tasks/' + id, {method: 'DELETE'})", tid)


def _walk_scope_switch(page: Page, base: str, shots: Path) -> None:
    """§ #391 — Today's Mine · Issues · All switch, one URL key, Mine by default.

    The seed's one synced coding task (it carries an issue_ref) is the Issues
    scope; everything else is Mine. The pick survives a reload through
    ``?scope=``, and Mine writes no key at all. Under Issues the Soon horizon
    holds a single project's group, so it draws no sub-header and the row
    names its project on the meta line instead.
    """
    pane = page.locator("#paneToday")
    switch = page.locator("#todayScope .segmented.scope-switch")
    pressed = switch.locator(".segmented-item[aria-pressed='true']")
    rows = pane.locator(".today-group .trow[data-id]")
    open_items = _get(base, "/api/tasks")["items"]
    issue_ids = sorted(t["id"] for t in open_items if t.get("issue_ref"))
    assert issue_ids, "the seed carries one synced coding task"
    # 1. Mine is the default: on screen, and absent from the URL
    expect(pressed).to_have_text("Tasks")
    expect(page).not_to_have_url(re.compile(r"[?&]scope="))
    _assert_scope_switch_spans_row(page)   # #399: the row's full width on desktop
    for tid in issue_ids:
        expect(pane.locator(f".trow[data-id='{tid}']")).to_have_count(0)
    # 2. Issues: only the synced tasks, the pick written to the URL
    switch.locator(".segmented-item[data-scope='issues']").click()
    expect(pressed).to_have_text("Issues")
    expect(page).to_have_url(re.compile(r"[?&]scope=issues"))
    expect(rows).to_have_count(len(issue_ids))
    assert sorted(int(i) for i in rows.evaluate_all("els => els.map(e => e.dataset.id)")) == issue_ids
    # 3. …and kept across a reload
    page.reload()
    expect(pressed).to_have_text("Issues")
    expect(rows).to_have_count(len(issue_ids))
    # one group in the horizon: no sub-header, the row names its project
    expect(pane.locator(".today-group-title")).to_have_count(0)
    expect(rows.first.locator(".trow-project")).to_be_visible()
    _clear_toasts(page)
    shot(page, shots / "story-31-today-horizons-3-desktop.png")
    # 4. All, then back to Mine, which drops the key again
    switch.locator(".segmented-item[data-scope='all']").click()
    expect(page).to_have_url(re.compile(r"[?&]scope=all"))
    for tid in issue_ids:
        expect(pane.locator(f".trow[data-id='{tid}']")).to_have_count(1)
    switch.locator(".segmented-item[data-scope='mine']").click()
    expect(pressed).to_have_text("Tasks")
    expect(page).not_to_have_url(re.compile(r"[?&]scope="))


def _edit_refresh_hold_the_reads(page: Page, base: str, made):
    """Step 1: a task, and the first edit's refresh reads held back."""
    tid = made["id"]
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")   # the last tab left is remembered, not Today
    expect(_today_row(page, "Renew the parking permit")).to_be_visible()   # due today → the due list
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator(f"#boardHost .trow[data-id='{tid}']")).to_be_visible()
    page.evaluate(_HOLD_LIST_READS)

    def counts() -> dict:
        return page.evaluate("window.__hold")

    page.locator(f"#boardHost .trow[data-id='{tid}'] .trow-title").click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()

    # 1. The title, with its refresh's list reads held back.
    page.evaluate("window.__hold.on = true")
    drawer.locator("#drawerTitle").fill("Renew the residents' permit")
    drawer.locator("#drawerTitle").press("Enter")
    for _ in range(100):
        if counts()["held"]:
            break
        page.wait_for_timeout(50)
    assert counts()["held"], "the first edit's refresh never read the list"
    # …every read of that refresh, not only the first to arrive: wait until the
    # batch stops growing before the hold is lifted.
    seen = -1
    while seen != counts()["held"]:
        seen = counts()["held"]
        page.wait_for_timeout(250)
    return counts, drawer, tid


def _edit_refresh_second_edit(page: Page, base: str, drawer, tid) -> None:
    """Step 2: the due date, edited while those reads are still held."""
    # 2. The due date, while those reads are still held: a phrase, the way the
    #    drawer takes one. Its refresh is answered at once.
    page.evaluate("window.__hold.on = false")
    due = drawer.locator("input[data-field='due']")
    due.fill("in 30 days")
    later = (E2E_ANCHOR + timedelta(days=30)).isoformat()
    # (#364) Enter fires a PATCH, and a read taken right after the key can beat
    # it on a busy box and see the old date. The walk waits on that PATCH's
    # response — and parks the request first, so the stale window is certain
    # rather than occasional: the read below must still see the old date, and
    # only the answered PATCH may make it the new one.
    parked: list = []

    def park_patch(route):
        if route.request.method == "PATCH":
            parked.append(route)
        else:
            route.continue_()

    page.route(f"**/api/tasks/{tid}", park_patch)
    try:
        with page.expect_response(
            lambda r: r.request.method == "PATCH" and r.url.endswith(f"/api/tasks/{tid}")
        ) as patched:
            due.press("Enter")
            for _ in range(100):
                if parked:
                    break
                page.wait_for_timeout(50)
            assert parked, "the due edit never sent its PATCH"
            assert _get(base, f"/api/tasks/{tid}")["due"] != later, "the PATCH was not held"
            parked.pop().continue_()
        assert patched.value.ok, patched.value.status
    finally:
        for route in parked:
            route.continue_()
        page.unroute(f"**/api/tasks/{tid}", park_patch)
    assert _get(base, f"/api/tasks/{tid}")["due"] == later


def _edit_refresh_rows_after_release(page: Page, counts, drawer, tid) -> None:
    """Step 3: every held answer lands; the rows keep the newer edit."""
    # 3. Let every held answer land, then settle — the stale overwrite, if there
    #    is one, has happened by now.
    for _ in range(200):
        state = counts()
        if state["delivered"] >= state["held"]:
            break
        page.wait_for_timeout(50)
    assert state["delivered"] >= state["held"], "held reads were never delivered"
    settle(page)

    # 4. Board: the new title and the new due on the one row, no reload.
    row = page.locator(f"#boardHost .trow[data-id='{tid}']")
    expect(row.locator(".trow-title")).to_have_text("Renew the residents' permit")
    expect(row).to_contain_text("in 4w")
    expect(drawer.locator("#drawerTitle")).to_have_value("Renew the residents' permit")

    # 5. Today: the task moved out of the due list with its date.
    page.click("nav.tabs .tab[data-tab='today']")
    expect(_today_row(page, "Renew the residents' permit")).to_have_count(0)
    expect(_today_row(page, "Renew the parking permit")).to_have_count(0)

    # 6. Leave the instance as found: the phone leg shares it, and one more
    #    task would move its counts and the shots that show them.
    page.evaluate(f"fetch('/api/tasks/{tid}', {{method: 'DELETE'}})")


def _walk_edit_refresh(page: Page, base: str) -> None:
    """§ #321 — a late read from an earlier refresh must not undo a newer edit.

    Every edit's ``refreshAll()`` follows the last one's, and the network does
    not answer in order: the read issued before the second edit landed used to
    resolve *after* the one issued once it had, and the older snapshot then sat
    on the rows until a reload. The walk holds the list reads of the first
    edit's refresh (the server answers them at once — it is the delivery that
    is late), makes the second edit while they are held, and only checks the
    rows after the held answers have been delivered, so a stale overwrite has
    already happened by the time it is looked for.
    """
    made = page.evaluate(
        "b => fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
        "body: JSON.stringify(b)}).then(r => r.json())",
        {"title": "Renew the parking permit", "status": "todo", "due": E2E_ANCHOR.isoformat()})
    counts, drawer, tid = _edit_refresh_hold_the_reads(page, base, made)
    _edit_refresh_second_edit(page, base, drawer, tid)
    _edit_refresh_rows_after_release(page, counts, drawer, tid)
