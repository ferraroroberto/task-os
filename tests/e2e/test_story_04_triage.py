"""Story 04 — Monday triage (Step 4/13, issue #5).

    Table filtered status:doing → click the due cell → the date picker opens
    and the pick lands → the activity log
    shows old → new with time → open a drawer → add a comment containing a
    link → the link is a clickable chip → the + opens the quick-add dialog
    (#80) → "renew passport next friday" → the parsed date shows as a chip →
    create → drag it under a project in the Tree → the breadcrumb appears in
    the Table.

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-04-triage-{1..8}-desktop.png
    docs/screenshots/story-04-triage-11-desktop.png   (stale window, #101)

then the drawer at 390×844 (WebKit, touch) with the geometry checks:

    docs/screenshots/story-04-triage-9-phone.png   (table as the shared rows)
    docs/screenshots/story-04-triage-10-phone.png  (drawer as a full-screen sheet)

UX round 3 (issue #46): the filter state is ONE card shared by every tab and
lives in the URL (``?status=doing`` is the same view on the Board, Table,
Tree, Today), so a shared URL no longer moves the tab by itself — the story
opens the Table explicitly. On the phone the Table renders the ONE shared
task row (``.trow``) instead of a card-ified grid.

**Story 13 — start date + snooze (#87)** rides in this file too, as
``_walk_starts_and_snooze`` at the end of the desktop leg plus the phone
assertions in the phone leg. It is a story of its own in
``docs/validation.md``, not a new test: the e2e suite is capped at 15 tests
(CLAUDE.md) and already held 14, and this story walks the same surface —
the filter card, the quick-add dialog, a Today row, the drawer. Its shots:

    docs/screenshots/story-13-starts-snooze-{1..5}-desktop.png
    docs/screenshots/story-13-starts-snooze-{6,7}-phone.png

**Story 15 — plan my day (#89)** rides here the same way, as
``_walk_plan_my_day`` after the stale-window walk plus a phone assertion.
Its shots:

    docs/screenshots/story-15-plan-my-day-{1..5}-desktop.png
    docs/screenshots/story-15-plan-my-day-6-desktop.png   (dark)
    docs/screenshots/story-15-plan-my-day-7-phone.png
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e.conftest import _get

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
LINK = "https://example.com/passport-office"


def _next_friday(today: date) -> date:
    coming = today + timedelta(days=(4 - today.weekday()) % 7)
    return coming + timedelta(days=7)


def _row(page: Page, title: str):
    """A desktop Table grid row by exact title (the seed has both "Renew
    passports" and the story's "renew passport")."""
    return page.locator(".task-row", has=page.locator(".t-title-text", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _trow(page: Page, title: str, scope: str = ""):
    """The ONE shared task row (rows.js) by exact title, optionally inside ``scope``."""
    return page.locator(f"{scope} .trow".strip(), has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


# A native date picker is an OS widget no browser automation can see or drive,
# so `showPicker()` is recorded instead: the call is what "the picker opened"
# means from the page's side, and the `change` the test then dispatches on the
# same input is what the user picking a day produces (#107).
_RECORD_SHOW_PICKER = """
window.__pickerOpens = [];
HTMLInputElement.prototype.showPicker = function () { window.__pickerOpens.push(this.className); };
"""


def _open_filters(page: Page, host_id: str):
    """The shared filter card is collapsed by default — open it like a user would."""
    card = page.locator(f"#{host_id} .filter-card")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


# ----------------------------------------------------------- desktop leg

def test_desktop_triage(seeded_webapp: str, browser: Browser, shots: Path) -> None:
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        page.add_init_script(_RECORD_SHOW_PICKER)

        # 1. Table filtered status:doing — via the URL, the shareable view. The
        #    filter is shared by every tab (UX round 3), so the URL never moves
        #    the tab by itself: open the Table, the query survives the switch.
        page.goto(f"{base}/?status=doing")
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        expect(page).to_have_url(f"{base}/?status=doing")
        card = _open_filters(page, "tableFilters")
        # status is a multi-select (#48): the summary reads the one status picked
        status_sel = card.locator(".msel[data-name='status']")
        expect(status_sel.locator(".msel-text")).to_have_text("doing")
        expect(status_sel.locator("input[name='status']:checked")).to_have_count(1)
        expect(status_sel.locator("input[name='status'][value='doing']")).to_be_checked()
        expect(card.locator(".filter-desc")).to_contain_text("doing")
        rows = page.locator(".task-row")
        expect(rows).to_have_count(7)  # the seed's seven `doing` tasks
        expect(card.locator(".filter-desc")).to_contain_text("7 tasks")
        statuses = page.locator(".task-row .trow-status").evaluate_all("els => els.map(e => e.value)")
        assert set(statuses) == {"doing"}
        # breadcrumb under a nested title, project = top ancestor
        quotes = _row(page, "Get three quotes")
        expect(quotes.locator(".t-crumb")).to_have_text("Home renovation › Kitchen")
        expect(quotes.locator(".c-project")).to_have_text("Home renovation")
        # last comment renders its folder placeholder as a chip
        expect(quotes.locator(".c-comment .chip-folder")).to_contain_text("{onedrive}/house/kitchen/plans")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-04-triage-1-desktop.png"))

        # 2. Change a due date inline — one click on the cell opens the date
        # picker (#107), where it used to swap the cell for a text box you had
        # to type a phrase into. `showPicker()` opens a native calendar no
        # browser automation can drive, so the walk proves the two halves that
        # are observable: the click really does call it (stubbed at page load
        # in `_count_show_picker`), and the pick it commits really does PATCH.
        task_id = int(quotes.get_attribute("data-id"))
        old_due = _get(base, f"/api/tasks/{task_id}")["due"]
        page.evaluate("window.__pickerOpens = []")
        quotes.locator(".due-btn").click()
        assert page.evaluate("window.__pickerOpens") == ["due-date"], "the cell did not open the picker"
        assert quotes.locator(".due-text").count() == 0, "the cell still swaps in a text box"
        new_due = (date.today() + timedelta(days=14)).isoformat()
        quotes.locator(".due-date").evaluate(
            "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }", new_due
        )
        expect(page.locator(f".task-row[data-id='{task_id}'] .due-btn")).to_have_attribute(
            "title", f"{new_due} — click to change"
        )
        assert _get(base, f"/api/tasks/{task_id}")["due"] == new_due
        page.screenshot(path=str(shots / "story-04-triage-2-desktop.png"))

        # 3. Open the drawer → activity shows due: old → new with actor + time.
        page.locator(f".task-row[data-id='{task_id}']").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(page).to_have_url(f"{base}/?status=doing#task/{task_id}")
        expect(drawer.locator("#drawerTitle")).to_have_value("Get three quotes")
        first_act = drawer.locator(".activity-row").first
        expect(first_act).to_have_attribute("data-field", "due")
        expect(first_act.locator(".activity-old")).to_have_text(old_due)
        expect(first_act.locator(".activity-new")).to_have_text(new_due)
        expect(first_act.locator(".activity-meta")).to_contain_text("Roberto")  # X-Actor default from the sample config
        # The list stays visible beside the drawer (side panel, not an overlay).
        table_box = page.locator(".table-wrap").bounding_box()
        drawer_box = drawer.bounding_box()
        assert table_box and drawer_box and table_box["x"] + table_box["width"] <= drawer_box["x"] + 1
        assert drawer_box["width"] >= 400
        page.screenshot(path=str(shots / "story-04-triage-3-desktop.png"))

        # 4. Add a comment containing a link → chip with href, newest first.
        # UX rounds 1+2 (issues #27/#32): placeholder keeps the Ctrl+Enter
        # hint, quiet ghost Send (the Description Edit tier).
        expect(drawer.locator(".comment-input")).to_have_attribute("placeholder", "Add a comment… (Ctrl+Enter to send)")
        expect(drawer.locator(".comment-send")).to_have_class(re.compile(r"\bbutton-ghost\b"))
        drawer.locator(".comment-input").fill(f"Office booked, details at {LINK} — bring photos")
        drawer.locator(".comment-input").press("Control+Enter")
        newest = drawer.locator(".comment").first
        expect(newest.locator(".comment-body")).to_contain_text("Office booked")
        chip = newest.locator("a.chip")
        expect(chip).to_have_attribute("href", LINK)
        expect(chip).to_have_attribute("target", "_blank")
        expect(chip).to_have_attribute("rel", "noopener")
        expect(newest.locator(".comment-origin")).to_have_text("ui")
        comments = _get(base, f"/api/tasks/{task_id}/comments")["items"]
        assert comments[-1]["origin"] == "ui" and LINK in comments[-1]["body"]
        # …and the Table's last-comment column picked it up
        expect(page.locator(f".task-row[data-id='{task_id}'] .c-comment a.chip")).to_have_attribute("href", LINK)
        page.screenshot(path=str(shots / "story-04-triage-4-desktop.png"))
        # click the chip: opens the link in a new tab (the target is stubbed —
        # the suite never depends on the network)
        context.route(LINK, lambda route: route.fulfill(status=200, content_type="text/html", body="<title>stub</title>ok"))
        with context.expect_page() as popup_info:
            chip.click()
        popup = popup_info.value
        popup.wait_for_load_state()
        assert popup.url == LINK, popup.url
        popup.close()
        drawer.locator(".drawer-close").click()
        expect(drawer).to_be_hidden()

        # 5. Quick-add (#80): the + in the top strip opens the one dialog;
        #    "renew passport next friday" parses into the editable Due field,
        #    and the rest of the first-moment fields are right there — no second
        #    trip through the drawer to set a description, a status, a folder
        #    or a link.
        page.locator("#paneTable .quick-add-btn").click()
        quick_add = page.locator("#quickAdd")
        expect(quick_add).to_be_visible()
        qa = quick_add.locator(".quick-add-input")
        qa.fill("renew passport next friday")
        friday = _next_friday(date.today()).isoformat()
        expect(quick_add.locator(".quick-add-due")).to_have_value(friday)
        expect(quick_add.locator(".quick-add-status")).to_have_value("inbox")   # the default
        quick_add.locator(".quick-add-desc").fill("both passports, town hall appointment")
        quick_add.locator(".quick-add-status").select_option("todo")
        quick_add.locator(".quick-add-folder").fill("{onedrive}/house")
        quick_add.locator(".quick-add-link-url").fill("https://example.com/passport-form")
        quick_add.locator(".quick-add-link-label").fill("application form")
        page.screenshot(path=str(shots / "story-04-triage-5-desktop.png"))

        # 6. Enter creates it with everything set and closes the dialog; the new
        #    row is focused (default filter = open).
        qa.press("Enter")
        expect(quick_add).to_be_hidden()
        expect(page.locator(".toast-success").last).to_contain_text("renew passport")
        # the doing filter hides an inbox task — clear to see it, as a user would
        _open_filters(page, "tableFilters").locator(".filter-clear").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.locator("#tableFilters .msel[data-name='status'] .msel-text")).to_have_text("Open tasks")
        new_row = _row(page, "renew passport")
        expect(new_row).to_be_visible()
        new_id = int(new_row.get_attribute("data-id"))
        created = _get(base, f"/api/tasks/{new_id}")
        assert created["due"] == friday and created["parent_id"] is None
        # every field the dialog offered landed on the task in one go (#80)
        assert created["status"] == "todo"
        assert created["description"] == "both passports, town hall appointment"
        assert created["folder_ref"] == "{onedrive}/house"
        assert [(link_["url"], link_["label"]) for link_ in created["links"]] == [
            ("https://example.com/passport-form", "application form")
        ]
        expect(new_row.locator(".due-btn")).to_have_attribute("title", f"{friday} — click to change")
        page.screenshot(path=str(shots / "story-04-triage-6-desktop.png"))

        # 7. Tree: drag it under a project (Family admin) → moved, toast, rollup.
        page.click("nav.tabs .tab[data-tab='tree']")
        expect(page.locator("#paneTree")).to_be_visible()
        family = page.locator(".tree-node", has=page.locator(":scope > .tree-row .trow-title", has_text="Family admin")).first
        family_id = int(family.get_attribute("data-id"))
        kids_before = int(family.locator(":scope > .tree-row .trow-kids").inner_text())
        # Collapse the four top-level projects so source and target share the
        # viewport (a real user does the same on a long tree); the state persists.
        project_ids = page.locator(".tree-node[aria-level='1'][aria-expanded='true']").evaluate_all(
            "els => els.map(e => e.dataset.id)"
        )
        for pid in project_ids:
            page.locator(f".tree-node[data-id='{pid}'] > .tree-row > .tree-toggle").click()
        expect(page.locator(".tree-node[aria-level='1'][aria-expanded='false']")).to_have_count(4)
        assert page.evaluate("JSON.parse(localStorage.getItem('task-os.tree.collapsed')).length") == 4
        source = page.locator(f".tree-node[data-id='{new_id}']")
        expect(source).to_be_visible()
        expect(source).to_have_attribute("aria-level", "1")
        # UX round 1 (issue #27): the top-level drop zone only shows during a drag
        expect(page.locator(".tree-root-drop")).to_be_hidden()
        source.locator(":scope > .tree-row").drag_to(family.locator(":scope > .tree-row"))
        expect(page.locator(".toast-success").last).to_contain_text("under Family admin")
        moved = _get(base, f"/api/tasks/{new_id}")
        assert moved["parent_id"] == family_id
        assert [c["title"] for c in moved["breadcrumb"]] == ["Family admin"]
        assert moved["activity"][0]["field"] == "parent"
        # the re-render kept the collapse state; expand Family admin to see it nested
        family = page.locator(f".tree-node[data-id='{family_id}']")
        expect(family).to_have_attribute("aria-expanded", "false")
        family.locator(":scope > .tree-row > .tree-toggle").click()
        nested = family.locator(f".tree-children .tree-node[data-id='{new_id}']")
        expect(nested).to_be_visible()
        expect(nested).to_have_attribute("aria-level", "2")
        # the row's children count (the shared row's rollup) grew by one
        expect(family.locator(":scope > .tree-row .trow-kids")).to_have_text(str(kids_before + 1))
        page.screenshot(path=str(shots / "story-04-triage-7-desktop.png"))
        # a cycle is refused and surfaced as a toast, nothing changes (the
        # two-line rows push the nested one below the fold — bring both into
        # the viewport first, as a user scrolling would; a drag that starts
        # while the page scrolls under the pointer would pick up another row)
        nested.locator(":scope > .tree-row").evaluate("el => el.scrollIntoView({block: 'end'})")
        family.locator(":scope > .tree-row").drag_to(nested.locator(":scope > .tree-row"))
        expect(page.locator(".toast-error").last).to_contain_text("cycle")
        assert _get(base, f"/api/tasks/{family_id}")["parent_id"] is None

        # 8. Back in the Table the breadcrumb is there.
        page.click("nav.tabs .tab[data-tab='table']")
        moved_row = page.locator(f".task-row[data-id='{new_id}']")
        expect(moved_row.locator(".t-crumb")).to_have_text("Family admin")
        expect(moved_row.locator(".c-project")).to_have_text("Family admin")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-04-triage-8-desktop.png"))

        # Deep link: a fresh load of #task/<id> opens the drawer with the breadcrumb.
        page.goto(f"{base}/#task/{new_id}")
        expect(page.locator("#taskDrawer")).to_be_visible()
        expect(page.locator("#taskDrawer .drawer-crumbs .crumb")).to_have_text(["Family admin"])

        # ---------------------------------------------- story 13 (#87) ----
        _walk_starts_and_snooze(page, base, shots)

        # ------------------------------------------- stale window (#101) ----
        _walk_stale_window(page, base, shots)

        # ------------------------------------------- plan my day (#89) ----
        _walk_plan_my_day(page, base, shots)

        # --------------------------------------- recurrence anchor (#112) ----
        _walk_recurrence_anchor(page, base, shots)
    finally:
        context.close()

    # the same walk in dark, for the paired proof shots
    dark_ctx = browser.new_context(viewport=DESKTOP, color_scheme="dark")
    try:
        dark_page = dark_ctx.new_page()
        dark_page.goto(f"{base}/?status=deferred")
        expect(dark_page.locator("#paneBoard, #paneTable, #paneToday").first).to_be_visible()
        dark_page.screenshot(path=str(shots / "story-13-starts-snooze-5-desktop.png"))
        # Today in dark: My plan on top with the restored seeded plan (#89)
        dark_page.goto(f"{base}/")
        dark_page.click("nav.tabs .tab[data-tab='today']")
        expect(dark_page.locator("#paneToday .today-plan")).to_be_visible()
        dark_page.screenshot(path=str(shots / "story-15-plan-my-day-6-desktop.png"))
    finally:
        dark_ctx.close()


# ------------------------------------------- recurrence anchor (#112)
#
# Riding inside this test for the same reason stories 13–15 do: the suite is
# capped at 15 tests and this walks the drawer the triage story already has
# open. The seeded instance is session-scoped, so the walk puts the task back
# the way it found it before returning.


def _walk_recurrence_anchor(page: Page, base: str, shots: Path) -> None:
    """#112 — Repeat is a cadence *and* the fixed day it lands on.

    The seed's "Weekly review" repeats every Friday. The drawer shows both
    selects; completing it from the status select rolls the due to a Friday
    rather than one flat week on, and switching the cadence to one that
    cannot carry a weekday clears the anchor rather than keeping a stale day.

    Screenshot: docs/screenshots/story-17-recurrence-anchor-1-desktop.png
    """
    review = page.request.get(f"{base}/api/tasks?q=Weekly review").json()["items"][0]
    page.goto(f"{base}/#task/{review['id']}")
    cadence = page.locator("#taskDrawer select[data-field='recurrence']")
    anchor = page.locator("#taskDrawer select[data-field='recurrence_anchor']")
    expect(cadence).to_have_value("weekly")
    expect(anchor).to_have_value("fri")
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    page.screenshot(path=str(shots / "story-17-recurrence-anchor-1-desktop.png"))

    # Complete it: the same task stays open and its new due is a Friday,
    # strictly after both the due it had and today.
    old_due = date.fromisoformat(review["due"])
    page.locator("#taskDrawer select[data-field='status']").select_option("complete")
    expect(page.locator("#taskDrawer input[data-field='due']")).not_to_have_value(review["due"])
    rolled = date.fromisoformat(
        page.locator("#taskDrawer input[data-field='due']").input_value()
    )
    assert rolled.weekday() == 4, f"rolled to {rolled} ({rolled:%A}), expected a Friday"
    assert rolled > old_due and rolled > date.today()

    # A cadence that takes no fixed day drops the anchor — and the picker with
    # it. The picker vanishing is the re-render signal: the drawer only redraws
    # once the PATCH has come back, so the stored value is safe to read here.
    cadence.select_option("quarterly")
    expect(anchor).to_have_count(0)
    assert page.request.get(
        f"{base}/api/tasks/{review['id']}"
    ).json()["recurrence_anchor"] is None

    # Restore over the API, not the UI — the seeded instance is session-scoped
    # and later stories read the same DB; one synchronous call cannot race.
    page.request.patch(f"{base}/api/tasks/{review['id']}", data={
        "recurrence": "weekly", "recurrence_anchor": "fri", "due": review["due"],
    })


# ------------------------------------------------- stale window (#101)


def _walk_stale_window(page: Page, base: str, shots: Path) -> None:
    """#101 — the modified select's inverse windows: *untouched > N days*.
    The seed's dormant task (last touched 45 days back) is the one hit at 30
    days and gone at 60; the URL keeps the window token while the API only
    ever sees the plain date the client computed.

    Screenshot: docs/screenshots/story-04-triage-11-desktop.png
    """
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='table']")
    card = _open_filters(page, "tableFilters")
    card.locator("select[name='updated']").select_option("stale30")
    expect(page).to_have_url(f"{base}/?updated=stale30")
    rows = page.locator(".task-row")
    expect(rows).to_have_count(1)
    expect(rows.locator(".t-title-text")).to_have_text("Sort the garage shelves")
    expect(card.locator(".filter-desc")).to_contain_text("untouched > 30 days")
    expect(card.locator(".filter-desc")).to_contain_text("1 task")
    page.screenshot(path=str(shots / "story-04-triage-11-desktop.png"))
    # the token round-trips: a fresh load of the shared URL is the same view
    page.goto(f"{base}/?updated=stale30")
    page.click("nav.tabs .tab[data-tab='table']")
    expect(page.locator(".task-row")).to_have_count(1)
    # 60 days back nothing is that old — an honest empty list, not an error
    _open_filters(page, "tableFilters").locator("select[name='updated']").select_option("stale60")
    expect(page.locator(".task-row")).to_have_count(0)


# ------------------------------------------------- story 15 — plan my day
#
# #89, riding here like stories 13 and 14: the suite is capped at 15 tests
# and this story walks the same Today surface. The seeded instance is
# session-scoped, so the walk restores what it changed (statuses, starts,
# the seeded plan) before returning — later stories assert over the same DB.


def _walk_plan_my_day(page: Page, base: str, shots: Path) -> None:
    """The morning ritual: My plan sits on top of Today with a progress line;
    emptied, the banner offers plan mode, where every candidate takes two
    large targets — Today (commits it) and Later (the #87 snooze popover) —
    and a task planned the day before wears its "planned yesterday" note.
    Committed tasks reorder by drag; completing one moves the progress line.

    Screenshots: docs/screenshots/story-15-plan-my-day-{1..5}-desktop.png
    (6 = dark, in the dark context; 7 = phone, in the phone leg).
    """
    today = date.today().isoformat()

    # 1. The seed's plan renders ordered on top of Today, with the progress line.
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    plan = page.locator("#paneToday .today-plan")
    expect(plan).to_be_visible()
    expect(plan.locator(".today-counts")).to_have_text("0 of 2 done")
    expect(plan.locator(".plan-list .trow .trow-title")).to_have_text(
        ["Look into a standing desk", "Try the new bakery"])
    page.screenshot(path=str(shots / "story-15-plan-my-day-1-desktop.png"))

    # 2. Unplan both (a conscious act, activity-logged, undoable) — the plan
    #    empties and the banner appears with the candidate counts.
    for title in ("Look into a standing desk", "Try the new bakery"):
        row = _trow(page, title, "#paneToday .plan-list")
        rid = int(row.get_attribute("data-id"))
        row.locator(".plan-unplan").click()
        expect(page.locator(".toast-success").last).to_contain_text("Removed from today")
        assert _get(base, f"/api/tasks/{rid}")["planned_on"] is None
        assert "planned_on" in [a["field"] for a in _get(base, f"/api/tasks/{rid}")["activity"]]
    banner = page.locator("#paneToday .plan-banner")
    expect(banner).to_be_visible()
    # 4 in Inbox: the seed's three plus the "renew passport" this story's own
    # quick-add walk created a few steps back
    expect(banner.locator(".plan-banner-text")).to_have_text(
        "Plan your day — 3 overdue · 5 due today · 4 new in Inbox")
    page.screenshot(path=str(shots / "story-15-plan-my-day-2-desktop.png"))

    # 3. Plan mode: every candidate carries the two targets; the task planned
    #    yesterday and not finished says so — never silently re-planned.
    banner.locator(".plan-banner-btn").click()
    picker = page.locator("#paneToday .plan-picker")
    expect(picker).to_be_visible()
    expect(picker.locator(".today-counts")).to_have_text("12 candidates")
    tap_row = _trow(page, "Fix leaking tap", "#paneToday .plan-cands")
    expect(tap_row.locator(".plan-note")).to_have_text("planned yesterday — not finished")
    tap_id = int(tap_row.get_attribute("data-id"))
    assert _get(base, f"/api/tasks/{tap_id}")["planned_on"] < today
    page.screenshot(path=str(shots / "story-15-plan-my-day-3-desktop.png"))

    # 4. Commit two (the standing desk, then the tap — re-committing the
    #    carry-over is the conscious act) and push one away with Later, the
    #    same #87 snooze popover, then leave plan mode.
    _trow(page, "Look into a standing desk", "#paneToday .plan-cands").locator("button.plan-target").click()
    expect(_trow(page, "Look into a standing desk", "#paneToday .plan-cands")).to_have_count(0)
    expect(_trow(page, "Look into a standing desk", "#paneToday .plan-list")).to_be_visible()
    _trow(page, "Fix leaking tap", "#paneToday .plan-cands").locator("button.plan-target").click()
    expect(_trow(page, "Fix leaking tap", "#paneToday .plan-list")).to_be_visible()
    assert _get(base, f"/api/tasks/{tap_id}")["planned_on"] == today
    lib_row = _trow(page, "Return library books", "#paneToday .plan-cands")
    lib_id = int(lib_row.get_attribute("data-id"))
    lib_row.locator(".snooze-summary").click()
    lib_row.locator(".snooze-menu").get_by_text("Next week", exact=True).click()
    expect(page.locator(".toast-success").last).to_contain_text("Snoozed to")
    expect(_trow(page, "Return library books", "#paneToday .plan-cands")).to_have_count(0)
    page.locator("#paneToday .plan-done-btn").click()
    expect(page.locator("#paneToday .plan-picker")).to_have_count(0)

    # 5. Drag to reorder — the tap first — and complete it: the progress line
    #    moves, the done item stays on the list, struck through.
    expect(plan.locator(".today-counts")).to_have_text("0 of 2 done")
    tap_planned = _trow(page, "Fix leaking tap", "#paneToday .plan-list")
    desk_planned = _trow(page, "Look into a standing desk", "#paneToday .plan-list")
    tap_planned.drag_to(desk_planned)
    expect(page.locator("#paneToday .plan-list .trow .trow-title").first).to_have_text("Fix leaking tap")
    api_plan = _get(base, "/api/today")["plan"]
    assert [t["title"] for t in api_plan["items"]] == ["Fix leaking tap", "Look into a standing desk"]
    page.screenshot(path=str(shots / "story-15-plan-my-day-4-desktop.png"))
    _trow(page, "Fix leaking tap", "#paneToday .plan-list").locator(".trow-status").select_option("done")
    expect(plan.locator(".today-counts")).to_have_text("1 of 2 done")
    done_row = _trow(page, "Fix leaking tap", "#paneToday .plan-list")
    expect(done_row).to_have_class(re.compile(r"\bis-closed\b"))
    api_plan = _get(base, "/api/today")["plan"]
    assert (api_plan["done"], api_plan["total"]) == (1, 2)
    page.screenshot(path=str(shots / "story-15-plan-my-day-5-desktop.png"))

    # ---- restore: the session-scoped seed serves the later stories --------
    # tap back to todo and out of the plan; the bakery back in (the seeded
    # plan's shape); the library awake again via the drawer (story-13 idiom).
    done_row.locator(".trow-status").select_option("todo")
    expect(plan.locator(".today-counts")).to_have_text("0 of 2 done")
    _trow(page, "Fix leaking tap", "#paneToday .plan-list").locator(".plan-unplan").click()
    expect(_trow(page, "Fix leaking tap", "#paneToday .plan-list")).to_have_count(0)
    page.locator("#paneToday .plan-more").click()
    _trow(page, "Try the new bakery", "#paneToday .plan-cands").locator("button.plan-target").click()
    expect(_trow(page, "Try the new bakery", "#paneToday .plan-list")).to_be_visible()
    page.locator("#paneToday .plan-done-btn").click()
    expect(page.locator("#paneToday .plan-list .trow .trow-title")).to_have_text(
        ["Look into a standing desk", "Try the new bakery"])
    page.goto(f"{base}/#task/{lib_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    starts_input = drawer.locator(".field-starts input[data-field='starts']")
    starts_input.fill("")
    starts_input.blur()
    # The field's own label is the *re-render* signal: `dateField` appends
    # " · <caption>" only while the field has a value, so a bare "Starts"
    # means the PATCH came back and the drawer redrew from the response.
    # Asserting on the input alone would pass on the local edit and let the
    # API read below race the write (seen failing once against a stale value).
    expect(drawer.locator(".field-starts .field-label")).to_have_text("Starts")
    assert _get(base, f"/api/tasks/{lib_id}")["starts"] is None
    assert _get(base, f"/api/tasks/{tap_id}")["status"] == "todo"


# ---------------------------------------------- story 13 — starts + snooze
#
# Rides inside this file rather than becoming a 15th test: the e2e suite is
# capped at 15 (CLAUDE.md) and sat at 14, and this story is a continuation of
# the same triage surface — the filter card, a Today row, the quick-add dialog.


def _walk_starts_and_snooze(page: Page, base: str, shots: Path) -> None:
    """A task created asleep stays out of the working views until its day, is
    findable under *Deferred*, and a Today row can be pushed away and undone.

    Screenshots: docs/screenshots/story-13-starts-snooze-{1..5}-desktop.png
    """
    today = date.today()
    starts = (today + timedelta(days=30)).isoformat()
    due = (today + timedelta(days=60)).isoformat()

    # 1. Quick-add both dates off one line — the parser fills two correctable
    #    fields, so nothing about the task is a mystery before it exists.
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    page.locator("#paneToday .quick-add-btn").click()
    quick_add = page.locator("#quickAdd")
    expect(quick_add).to_be_visible()
    quick_add.locator(".quick-add-input").fill("renew insurance due in 60 days starts in 30 days")
    expect(quick_add.locator(".quick-add-due")).to_have_value(due)
    expect(quick_add.locator(".quick-add-starts")).to_have_value(starts)
    quick_add.locator(".quick-add-status").select_option("todo")
    page.screenshot(path=str(shots / "story-13-starts-snooze-1-desktop.png"))
    quick_add.locator(".quick-add-input").press("Enter")
    expect(quick_add).to_be_hidden()
    expect(page.locator(".toast-success").last).to_contain_text("renew insurance")

    created = next(t for t in _get(base, "/api/tasks?status=deferred")["items"]
                   if t["title"] == "renew insurance")
    assert (created["due"], created["starts"]) == (due, starts)

    # 2. It is nowhere in the working views — Today, the Board, the Table.
    expect(_trow(page, "renew insurance", "#paneToday")).to_have_count(0)
    for tab, pane in (("board", "#paneBoard"), ("table", "#paneTable")):
        page.click(f"nav.tabs .tab[data-tab='{tab}']")
        expect(page.locator(pane)).to_be_visible()
        expect(page.locator(pane).get_by_text("renew insurance", exact=True)).to_have_count(0)
    # …but the Tree still has it, wearing the marker that says why it is quiet
    page.click("nav.tabs .tab[data-tab='tree']")
    sleeping = _trow(page, "renew insurance", "#paneTree")
    expect(sleeping).to_be_visible()
    expect(sleeping.locator(".trow-starts")).to_have_text(re.compile(r"^starts \d"))
    page.screenshot(path=str(shots / "story-13-starts-snooze-2-desktop.png"))

    # 3. Deferred is a visible state, not an absence: the status multi-select's
    #    pseudo-value lists exactly the sleeping tasks, and the state is the URL.
    page.click("nav.tabs .tab[data-tab='table']")
    card = _open_filters(page, "tableFilters")
    status_sel = card.locator(".msel[data-name='status']")
    status_sel.locator("summary.msel-summary").click()
    status_sel.locator("input[name='status'][value='deferred']").check()
    expect(page).to_have_url(f"{base}/?status=deferred")
    expect(status_sel.locator(".msel-text")).to_have_text("deferred")
    rows = page.locator("#paneTable .task-row")
    titles = rows.locator(".t-title-text").all_inner_texts()
    # the seed's own deferred task plus the one just created — and nothing else
    assert sorted(titles) == ["Book boiler service", "renew insurance"], titles
    # the desktop grid has its own cells, so it carries the marker explicitly —
    # the list of sleeping tasks is exactly where the start day matters
    expect(rows.locator(".t-starts")).to_have_count(2)
    expect(rows.locator(".t-starts").first).to_have_text(re.compile(r"^starts \d"))
    page.screenshot(path=str(shots / "story-13-starts-snooze-3-desktop.png"))
    card.locator(".filter-clear").click()
    expect(page).to_have_url(f"{base}/")

    # 4. Snooze from a Today row: pick an option, the task leaves, the toast
    #    names the day it went to — and Undo puts it straight back.
    page.click("nav.tabs .tab[data-tab='today']")
    row = _trow(page, "School enrolment forms", "#paneToday")
    expect(row).to_be_visible()
    task_id = int(row.get_attribute("data-id"))
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None
    row.locator(".snooze-summary").click()
    menu = row.locator(".snooze-menu")
    expect(menu).to_be_visible()
    expect(menu.locator(".snooze-opt")).to_have_count(4)   # 3 phrases + pick a date
    page.screenshot(path=str(shots / "story-13-starts-snooze-4-desktop.png"))
    menu.get_by_text("Next week", exact=True).click()

    next_week = (today + timedelta(days=7)).isoformat()
    toast = page.locator(".toast-success").last
    expect(toast).to_contain_text("Snoozed to")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] == next_week
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_have_count(0)
    # the change is in the log like any other field change
    assert "starts" in [a["field"] for a in _get(base, f"/api/tasks/{task_id}")["activity"]]

    toast.locator(".toast-action").click()
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_be_visible()
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None

    # 5. The drawer edits Starts beside Due — the same control, one behaviour.
    page.goto(f"{base}/#task/{task_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    starts_input = drawer.locator(".field-starts input[data-field='starts']")
    expect(starts_input).to_be_visible()
    expect(drawer.locator(".field-due input[data-field='due']")).to_be_visible()
    starts_input.fill("in 3 days")
    starts_input.blur()
    expect(starts_input).to_have_value((today + timedelta(days=3)).isoformat())
    assert _get(base, f"/api/tasks/{task_id}")["starts"] == (today + timedelta(days=3)).isoformat()
    assert_no_horizontal_overflow(page)

    # Put the seeded task back the way this walk found it: `seeded_webapp` is
    # session-scoped, so a task left asleep here would vanish from Today for
    # every later story (it did — story 05 caught it).
    starts_input.fill("")
    starts_input.blur()
    expect(starts_input).to_have_value("")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None


# ------------------------------------------------------------- phone leg

def test_phone_table_cards_and_drawer_sheet(seeded_webapp: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): the Table as the shared rows, drawer
    full-screen, 44px targets (the row's status select is the deliberate
    compact exception — ≤32px, centred on the title line, UX rounds 1–3)."""
    base = seeded_webapp
    try:
        wk = playwright.webkit.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — a missing browser is a hard failure, named
        pytest.fail(f"WebKit is required for the phone leg: {exc}")
    try:
        context = wk.new_context(
            viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True,
            color_scheme="light",
        )
        page = context.new_page()
        page.goto(f"{base}/?status=doing")
        page.locator("nav.tabs .tab[data-tab='table']").tap()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        rows = page.locator("#paneTable .table-rows .trow")
        expect(rows).to_have_count(7)
        # phone: the grid is not rendered at all — the Table is the ONE shared
        # row (title + status select, the meta line with the project under it)
        expect(page.locator(".task-table")).to_have_count(0)
        watering = _trow(page, "Fix watering schedule drift", "#paneTable")
        expect(watering.locator(".trow-project")).to_have_text("Side project: garden-bot")
        expect(watering.locator(".trow-due")).to_be_visible()
        expect(watering.locator(".trow-status")).to_have_value("doing")
        assert_no_horizontal_overflow(page)
        # the top strip (#80): the text filter and the + sit side by side, both
        # at the touch floor, with effective rectangles that never overlap
        strip = page.locator("#paneTable .filter-q, #paneTable .quick-add-btn")
        assert_min_target(strip)
        assert_no_overlap(strip)
        page.locator("#paneTable .quick-add-btn").tap()
        expect(page.locator("#quickAdd")).to_be_visible()
        assert_min_target(page.locator("#quickAdd .quick-add-input"))
        page.keyboard.press("Escape")
        expect(page.locator("#quickAdd")).to_be_hidden()
        # the shared filter card: the status multi-select holds the six statuses,
        # the URL's one checked; on the phone the controls sit two per line,
        # equal widths (#48)
        card = _open_filters(page, "tableFilters")
        status_sel = card.locator(".msel[data-name='status']")
        status_sel.locator("summary.msel-summary").click()
        # six statuses + `deferred`, the pseudo-value that shows the sleeping
        # tasks the working views leave out (#87)
        expect(status_sel.locator("input[name='status']")).to_have_count(7)
        expect(status_sel.locator("input[name='status'][value='deferred']")).to_have_count(1)
        expect(status_sel.locator("input[name='status'][value='doing']")).to_be_checked()
        page.keyboard.press("Escape")
        boxes = card.locator(".filter-row > .filter-select, .filter-row > .msel").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.width)]; })")
        assert len(boxes) == 6, boxes
        lefts = sorted(set(b[0] for b in boxes))
        assert len(lefts) == 2, boxes                                  # two columns
        assert max(b[1] for b in boxes) - min(b[1] for b in boxes) <= 2, boxes   # equal widths
        # rows are >=44px tall; the status select is compact and, since #74,
        # centred against the WHOLE card (title + meta) rather than the title line
        assert_min_target(rows)
        assert_no_overlap(rows.locator(".trow-status"))
        heights = rows.locator(".trow-status").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and all(h <= 32 for h in heights), heights
        # #74 round 2: a folder never makes a card taller. It is an inline glyph
        # like every other meta item now, so a row that has one is exactly as tall
        # as a plain one. (Rows above that height are metas that wrapped to a
        # second line - a different thing, and not what the folder caused.)
        by_folder = rows.evaluate_all(
            "els => els.map(e => [!!e.querySelector('.chip-folder'),"
            " Math.round(e.getBoundingClientRect().height)])")
        assert any(f for f, _ in by_folder) and any(not f for f, _ in by_folder), by_folder
        # `base_h`, not `base` — that name is the instance URL in this function
        base_h = min(h for _, h in by_folder)
        assert {h for f, h in by_folder if f} == {base_h}, by_folder
        assert base_h in {h for f, h in by_folder if not f}, by_folder
        sel_box = watering.locator(".trow-status").bounding_box()
        main_box = watering.locator(".trow-main").bounding_box()
        meta_box = watering.locator(".trow-meta").bounding_box()
        assert sel_box and main_box and meta_box
        sel_center = sel_box["y"] + sel_box["height"] / 2
        rows_center = (main_box["y"] + meta_box["y"] + meta_box["height"]) / 2
        assert abs(sel_center - rows_center) <= 2, (sel_box, main_box, meta_box)
        assert page.locator("#paneTable .table-rows").evaluate("el => getComputedStyle(el).borderRadius") == "0px"
        page.screenshot(path=str(shots / "story-04-triage-9-phone.png"))

        # the drawer is a full-screen sheet; the pill is hidden while it is up
        _trow(page, "Get three quotes", "#paneTable").locator(".trow-main").tap()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        box = drawer.bounding_box()
        assert box and box["width"] >= PHONE["width"] - 1 and box["height"] >= PHONE["height"] - 1, box
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "hidden"
        assert_min_target(drawer.locator(".drawer-close"))
        assert_min_target(drawer.locator(".field-control"))
        assert_min_target(drawer.locator(".comment-send"))
        # UX round 2 (#32): the composer keeps the Ctrl+Enter hint; Send stays
        # on the Description "Edit" tier (ghost, same rendered height).
        expect(drawer.locator(".comment-input")).to_have_attribute(
            "placeholder", "Add a comment… (Ctrl+Enter to send)")
        send_box = drawer.locator(".comment-send").bounding_box()
        edit_box = drawer.locator(".drawer-tools .button-ghost").first.bounding_box()
        assert send_box and edit_box and abs(send_box["height"] - edit_box["height"]) <= 1, (send_box, edit_box)
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-04-triage-10-phone.png"))
        drawer.locator(".drawer-close").tap()
        expect(drawer).to_be_hidden()
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "visible"

        # --------------------------------------------- story 13 (#87) ----
        # The snooze control is a real touch target on the phone — this is the
        # device where "not today" is most often decided — and its popover
        # never pushes the page sideways.
        page.goto(f"{base}/")          # drop the story's ?status=doing first
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        expect(page.locator("#paneToday")).to_be_visible()
        today_row = page.locator("#paneToday .today-group .trow.has-snooze").first
        expect(today_row).to_be_visible()
        snooze = today_row.locator(".snooze-summary")
        assert_min_target(snooze)
        assert_no_overlap(page.locator("#paneToday .trow.has-snooze .snooze-summary, "
                                       "#paneToday .trow.has-snooze .trow-status"))
        snooze.tap()
        menu = today_row.locator(".snooze-menu")
        expect(menu).to_be_visible()
        assert_min_target(menu.locator(".snooze-opt"))
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-13-starts-snooze-6-phone.png"))
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()

        # the sleeping seed task wears its marker wherever it still shows
        page.goto(f"{base}/?status=deferred")
        page.locator("nav.tabs .tab[data-tab='table']").tap()
        sleeping = _trow(page, "Book boiler service", "#paneTable")
        expect(sleeping).to_be_visible()
        expect(sleeping.locator(".trow-starts")).to_have_text(re.compile(r"^starts \d"))
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-13-starts-snooze-7-phone.png"))

        # --------------------------------------------- story 15 (#89) ----
        # Today is the phone's landing tab — My plan sits on top with real
        # touch targets on its controls, and nothing pushes the page sideways.
        page.goto(f"{base}/")
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        plan = page.locator("#paneToday .today-plan")
        expect(plan).to_be_visible()
        expect(plan.locator(".plan-list .trow")).to_have_count(2)
        assert_min_target(plan.locator(".plan-unplan"))
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-15-plan-my-day-7-phone.png"))
        context.close()
    finally:
        wk.close()
