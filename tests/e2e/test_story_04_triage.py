"""Story 04 — Monday triage (Step 4/13, issue #5).

    Table filtered status:todo → click the due cell → the date picker opens
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

then — in the same test function since #96 — the drawer at 390×844 (WebKit,
touch) with the geometry checks:

    docs/screenshots/story-04-triage-9-phone.png   (table as the shared rows)
    docs/screenshots/story-04-triage-10-phone.png  (drawer as a full-screen sheet)

UX round 3 (issue #46): the filter state is ONE card shared by every tab and
lives in the URL (``?status=todo`` is the same view on the Board, Table,
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

**Story 30 — Today's split view (#336)** rides here as ``_walk_today_split``
right after the plan walk, on the same Today surface: the list in the left
half, the detail pane in the right (empty state until a task opens). Its shots:

    docs/screenshots/story-30-today-split-{1,2,3}-desktop.png

**Story 25 — repeat every N (#229)** rides here too, as
``_walk_recurrence_interval`` right after the story-17 anchor walk it extends
(the same drawer, the same seeded task) plus a phone assertion. Its shots:

    docs/screenshots/story-25-recurrence-interval-1-desktop.png
    docs/screenshots/story-25-recurrence-interval-2-phone.png

**Story 29 — act on a row from its menu (#311)** rides inside
``_walk_starts_and_snooze`` (step 4b): the same Today row, snoozed from its ⋯
kebab (the row has no clock any more) and read in full, through the shared
action runner. Its shots:

    docs/screenshots/story-29-row-actions-{1,2}-desktop.png
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _get,
    assert_grid_walk,
    dismiss_toasts,
    shot,
    table_view,
    tree_view,
)

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


# A sideways touch on a row, as synthetic Pointer Events (swipe.js, #311): it
# proves the wiring — which action a side runs — not the feel of the gesture,
# which is the owner's iPhone walk (story 29).
_SWIPE = """(el, [x0, x1]) => {
  const r = el.getBoundingClientRect();
  const y = r.top + r.height / 2;
  const fire = (type, x) => el.dispatchEvent(new PointerEvent(type, {
    pointerId: 7, pointerType: 'touch', isPrimary: true, bubbles: true, clientX: x, clientY: y }));
  fire('pointerdown', x0);
  for (let i = 1; i <= 8; i++) fire('pointermove', x0 + (x1 - x0) * i / 8);
  fire('pointerup', x1);
}"""

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

def test_desktop_triage(seeded_webapp: str, browser: Browser, playwright: Playwright, shots: Path) -> None:
    """The desktop walk, then the phone leg on the same instance.

    One collected test, not two: the phone leg was its own test function until
    #96's calendar story needed a slot under the e2e budget (CLAUDE.md), so it
    is folded in here, the way story 05's was for Step 12 — same steps, same
    order, same shots.
    """
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        page.add_init_script(_RECORD_SHOW_PICKER)

        # 1. Table filtered status:todo — via the URL, the shareable view. The
        #    filter is shared by every tab (UX round 3), so the URL never moves
        #    the tab by itself: open the Table, the query survives the switch.
        todo_count = _get(base, "/api/tasks?status=todo")["count"]
        page.goto(f"{base}/?status=todo")
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        expect(page).to_have_url(f"{base}/?status=todo")
        card = _open_filters(page, "tableFilters")
        # status is a multi-select (#48): the summary reads the one status picked
        status_sel = card.locator(".msel[data-name='status']")
        expect(status_sel.locator(".msel-text")).to_have_text("todo")
        expect(status_sel.locator("input[name='status']:checked")).to_have_count(1)
        expect(status_sel.locator("input[name='status'][value='todo']")).to_be_checked()
        expect(card.locator(".filter-desc")).to_contain_text("todo")
        rows = page.locator(".task-row")
        expect(rows).to_have_count(todo_count)
        expect(card.locator(".filter-desc")).to_contain_text(f"{todo_count} tasks")
        statuses = page.locator(".task-row .trow-status").evaluate_all("els => els.map(e => e.value)")
        assert set(statuses) == {"todo"}
        # breadcrumb under a nested title, project = top ancestor
        quotes = _row(page, "Get three quotes")
        expect(quotes.locator(".t-crumb")).to_have_text("Home renovation › Kitchen")
        expect(quotes.locator(".c-project")).to_have_text("Home renovation")
        # last comment renders its folder placeholder as a chip, labeled with
        # just the last path segment (the full ref lives in the title)
        comment_folder_chip = quotes.locator(".c-comment .chip-folder")
        expect(comment_folder_chip).to_contain_text("plans")
        expect(comment_folder_chip).to_have_attribute("title", "{onedrive}/house/kitchen/plans")
        # #305: a chip in the comment text is a 44px target whose band stays
        # inside the (clipping) comment line, and none shares a pixel
        comment_chips = page.locator(".task-table .c-comment .chip")
        assert_min_target(comment_chips)
        assert_no_overlap(comment_chips)
        # #305: the issue chip beside a coding task's title is one too
        title_chips = page.locator(".task-table .t-title a.chip")
        assert title_chips.count() >= 1, "the seed shows no issue chip in the grid's title cell"
        assert_min_target(title_chips)
        assert_no_overlap(title_chips)
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-04-triage-1-desktop.png")
        # #339: the grid is an ARIA data grid, its live cells (the issue chip,
        # due, status, the folder and AI chips) reached from the row by the
        # arrow keys rather than counted as a list row's actions
        # …and a row leads with its name, the code after it (#339)
        heads = page.locator(".task-table thead th").all_inner_texts()
        assert heads[:2] == ["Title", "Code"], heads
        coding = page.locator(".task-table .task-row", has=page.locator(".t-title a.chip")).first
        assert assert_grid_walk(coding) >= 4

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
        new_due = (E2E_ANCHOR + timedelta(days=14)).isoformat()
        quotes.locator(".due-date").evaluate(
            "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }", new_due
        )
        expect(page.locator(f".task-row[data-id='{task_id}'] .due-btn")).to_have_attribute(
            "title", f"{new_due} — click to change"
        )
        assert _get(base, f"/api/tasks/{task_id}")["due"] == new_due
        shot(page, shots / "story-04-triage-2-desktop.png")

        # 3. Open the drawer → activity shows due: old → new with actor + time.
        page.locator(f".task-row[data-id='{task_id}']").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(page).to_have_url(f"{base}/?status=todo#task/{task_id}")
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
        shot(page, shots / "story-04-triage-3-desktop.png")

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
        shot(page, shots / "story-04-triage-4-desktop.png")
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
        friday = _next_friday(E2E_ANCHOR).isoformat()
        expect(quick_add.locator(".quick-add-due")).to_have_value(friday)
        # To Do is the default for a task added by hand (#148) — Inbox is for
        # what arrives on its own, and this one is being typed.
        expect(quick_add.locator(".quick-add-status")).to_have_value("todo")
        quick_add.locator(".quick-add-desc").fill("both passports, town hall appointment")
        # Pick something the default is NOT, so this still proves the select is
        # honoured rather than agreeing with the default by accident.
        quick_add.locator(".quick-add-status").select_option("standby")
        quick_add.locator(".quick-add-folder").fill("{onedrive}/house")
        quick_add.locator(".quick-add-link-url").fill("https://example.com/passport-form")
        quick_add.locator(".quick-add-link-label").fill("application form")
        shot(page, shots / "story-04-triage-5-desktop.png")

        # 6. Enter creates it with everything set and closes the dialog; the new
        #    row is focused (default filter = open).
        qa.press("Enter")
        expect(quick_add).to_be_hidden()
        expect(page.locator(".toast-success").last).to_contain_text("renew passport")
        # the todo filter hides a standby task — clear to see it, as a user would
        _open_filters(page, "tableFilters").locator(".filter-clear").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.locator("#tableFilters .msel[data-name='status'] .msel-text")).to_have_text("Open tasks")
        new_row = _row(page, "renew passport")
        expect(new_row).to_be_visible()
        new_id = int(new_row.get_attribute("data-id"))
        created = _get(base, f"/api/tasks/{new_id}")
        assert created["due"] == friday and created["parent_id"] is None
        # every field the dialog offered landed on the task in one go (#80)
        assert created["status"] == "standby"
        assert created["description"] == "both passports, town hall appointment"
        assert created["folder_ref"] == "{onedrive}/house"
        assert [(link_["url"], link_["label"]) for link_ in created["links"]] == [
            ("https://example.com/passport-form", "application form")
        ]
        expect(new_row.locator(".due-btn")).to_have_attribute("title", f"{friday} — click to change")
        shot(page, shots / "story-04-triage-6-desktop.png")

        # 7. Tree (the Table pane's second view, #161): drag it under a project
        #    (Family admin) → moved, toast, rollup.
        tree_view(page)
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
        shot(page, shots / "story-04-triage-7-desktop.png")
        # a cycle is refused and surfaced as a toast, nothing changes (the
        # two-line rows push the nested one below the fold — bring both into
        # the viewport first, as a user scrolling would; a drag that starts
        # while the page scrolls under the pointer would pick up another row)
        nested.locator(":scope > .tree-row").evaluate("el => el.scrollIntoView({block: 'end'})")
        family.locator(":scope > .tree-row").drag_to(nested.locator(":scope > .tree-row"))
        expect(page.locator(".toast-error").last).to_contain_text("cycle")
        assert _get(base, f"/api/tasks/{family_id}")["parent_id"] is None

        # 8. Back on the Table's grid view the breadcrumb is there.
        table_view(page)
        moved_row = page.locator(f".task-row[data-id='{new_id}']")
        expect(moved_row.locator(".t-crumb")).to_have_text("Family admin")
        expect(moved_row.locator(".c-project")).to_have_text("Family admin")
        assert_no_horizontal_overflow(page)
        # #305: the folder cell's folder and AI chips are 44px targets that
        # share no pixel — measured over every chip the grid shows
        grid_chips = page.locator(".task-table .c-folder .chip")
        assert grid_chips.count() >= 2, "the seed shows no folder/AI chips in the grid"
        assert_min_target(grid_chips)
        assert_no_overlap(grid_chips)
        shot(page, shots / "story-04-triage-8-desktop.png")

        # Deep link: a fresh load of #task/<id> opens the drawer with the breadcrumb.
        page.goto(f"{base}/#task/{new_id}")
        expect(page.locator("#taskDrawer")).to_be_visible()
        expect(page.locator("#taskDrawer .drawer-crumbs .crumb")).to_have_text(["Family admin"])

        # ------------------------------- closed tasks on demand (#309) ----
        _walk_closed_on_demand(page, base)

        # ---------------------------------------------- story 13 (#87) ----
        _walk_starts_and_snooze(page, base, shots)

        # ------------------------------------------- stale window (#101) ----
        _walk_stale_window(page, base, shots)

        # ------------------------------------------- plan my day (#89) ----
        _walk_plan_my_day(page, base, shots)

        # -------------------------------------- today split view (#336) ----
        _walk_today_split(page, base, shots)

        # --------------------------------------- recurrence anchor (#112) ----
        _walk_recurrence_anchor(page, base, shots)

        # ------------------------------------- recurrence interval (#229) ----
        _walk_recurrence_interval(page, base, shots)
    finally:
        context.close()

    # the same walk in dark, for the paired proof shots
    dark_ctx = browser.new_context(viewport=DESKTOP, color_scheme="dark")
    try:
        dark_page = dark_ctx.new_page()
        dark_page.goto(f"{base}/?status=deferred")
        dark_page.click("nav.tabs .tab[data-tab='board']")   # Today is the landing tab (#319)
        expect(dark_page.locator("#paneBoard")).to_be_visible()
        shot(dark_page, shots / "story-13-starts-snooze-5-desktop.png")
        # Today in dark: My plan on top with the restored seeded plan (#89)
        dark_page.goto(f"{base}/")
        dark_page.click("nav.tabs .tab[data-tab='today']")
        expect(dark_page.locator("#paneToday .today-plan")).to_be_visible()
        shot(dark_page, shots / "story-15-plan-my-day-6-desktop.png")
    finally:
        dark_ctx.close()

    _walk_phone_table_cards_and_drawer_sheet(base, playwright, shots)


# ------------------------------------------ closed tasks on demand (#309)
#
# Riding inside this test because it is the Tree's story and the suite is
# capped (CLAUDE.md): no shots, the default views are unchanged, so the gallery
# does not move. It runs in its own context — a cold boot, an empty HTTP cache
# — so every recorded response is a 200 with a body to read.

def _flatten(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children") or []))
    return out


def _walk_closed_on_demand(page: Page, base: str) -> None:
    """The boot no longer ships closed tasks or descriptions; the Tree loads the
    closed forest only when a closed status is filtered, and only once."""
    ctx = page.context.browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        p = ctx.new_page()
        seen = []
        p.on("response", lambda r: seen.append(r) if "/api/" in r.url else None)

        def calls(path: str) -> list:
            return [r for r in seen if urlsplit(r.url).path == path]

        def query(r) -> dict:
            return parse_qs(urlsplit(r.url).query)

        # 1. The cold boot: open forest, slim list, the project list.
        p.goto(f"{base}/")
        expect(p.locator("#homeHeadStatus")).to_have_text(re.compile(r"^\d+ open$"))
        trees = calls("/api/tasks/tree")
        assert trees, "the boot read no forest"
        for r in trees:
            assert query(r).get("descriptions") == ["false"] and "include_closed" not in query(r), r.url
            nodes = _flatten(r.json()["items"])
            assert nodes and all("description" not in n for n in nodes)
            assert not [n for n in nodes if n["status"] in ("done", "cancelled") and not n["children"]],                 "the boot forest carries a closed leaf"
        lists = calls("/api/tasks")
        assert lists, "the boot read no list"
        for r in lists:
            assert query(r).get("descriptions") == ["false"], r.url
            assert all("description" not in t for t in r.json()["items"])
        assert calls("/api/projects"), "the boot did not read the project list"
        # the closed tasks are still there for whoever asks: the default shape
        assert any(t["status"] == "done" for t in _get(base, "/api/tasks?include_closed=true")["items"])

        # 2. The default Tree view pays nothing for them.
        tree_view(p)
        expect(p.locator("#paneTable #treeHost .tree")).to_be_visible()
        closed_calls = lambda: [r for r in calls("/api/tasks/tree") if "include_closed" in query(r)]  # noqa: E731
        assert closed_calls() == []
        expect(_trow(p, "Buy a birthday gift", "#paneTable #treeHost")).to_have_count(0)

        # 3. A closed status in the filter loads the closed forest — once — and
        #    the closed task is on the Tree; the next closed status reuses it.
        card = _open_filters(p, "tableFilters")
        status_sel = card.locator(".msel[data-name='status']")
        status_sel.locator("summary.msel-summary").click()
        status_sel.locator("input[name='status'][value='done']").check()
        expect(_trow(p, "Buy a birthday gift", "#paneTable #treeHost")).to_be_visible()
        # its ancestor is context, not a hole: a done task under an open project
        expect(_trow(p, "Collect photos", "#paneTable #treeHost")).to_be_visible()
        assert len(closed_calls()) == 1, [r.url for r in closed_calls()]
        status_sel.locator("input[name='status'][value='cancelled']").check()
        expect(_trow(p, "Sell the old bikes", "#paneTable #treeHost")).to_be_visible()
        assert len(closed_calls()) == 1, [r.url for r in closed_calls()]
    finally:
        ctx.close()


# ------------------------------------------- recurrence anchor (#112)
#
# Riding inside this test for the same reason stories 13–15 do: the suite is
# capped at 15 tests and this walks the drawer the triage story already has
# open. The file's seeded instance also serves the phone leg below, so the walk
# puts the task back the way it found it before returning.


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
    shot(page, shots / "story-17-recurrence-anchor-1-desktop.png")

    # Complete it: the same task stays open and its new due is a Friday,
    # strictly after both the due it had and today.
    old_due = date.fromisoformat(review["due"])
    page.locator("#taskDrawer select[data-field='status']").select_option("complete")
    expect(page.locator("#taskDrawer input[data-field='due']")).not_to_have_value(review["due"])
    rolled = date.fromisoformat(
        page.locator("#taskDrawer input[data-field='due']").input_value()
    )
    assert rolled.weekday() == 4, f"rolled to {rolled} ({rolled:%A}), expected a Friday"
    assert rolled > old_due and rolled > E2E_ANCHOR

    # A cadence that takes no fixed day drops the anchor — and the picker with
    # it. The picker vanishing is the re-render signal: the drawer only redraws
    # once the PATCH has come back, so the stored value is safe to read here.
    cadence.select_option("quarterly")
    expect(anchor).to_have_count(0)
    assert page.request.get(
        f"{base}/api/tasks/{review['id']}"
    ).json()["recurrence_anchor"] is None

    # Restore over the API, not the UI — the rest of this file reads the same
    # seeded DB; one synchronous call cannot race.
    page.request.patch(f"{base}/api/tasks/{review['id']}", data={
        "recurrence": "weekly", "recurrence_anchor": "fri", "due": review["due"],
    })


def _walk_recurrence_interval(page: Page, base: str, shots: Path) -> None:
    """#229 — Repeat every N: "every 7 weeks on Saturday".

    The seed's "Weekly review" is due on a Saturday. The drawer's Every field
    takes 7 and the On picker Saturday; the row behind the drawer reads the
    composed label, and completing the task lands exactly 7 weeks on — a
    Saturday, never the coming one. Restored over the API afterwards, like
    the anchor walk before it.

    Screenshot: docs/screenshots/story-25-recurrence-interval-1-desktop.png
    """
    review = page.request.get(f"{base}/api/tasks?q=Weekly review").json()["items"][0]
    task_url = f"{base}/api/tasks/{review['id']}"
    page.goto(f"{base}/")
    page.goto(f"{base}/#task/{review['id']}")
    drawer = page.locator("#taskDrawer")
    every = drawer.locator("input[data-field='recurrence_interval']")
    expect(every).to_have_value("")
    expect(drawer.locator(".field-unit")).to_have_text("weeks")

    def patched(r) -> bool:  # noqa: ANN001 — a Playwright Response
        return r.request.method == "PATCH" and r.url.endswith(f"/api/tasks/{review['id']}")

    every.fill("7")
    with page.expect_response(patched) as resp:
        every.press("Enter")
    assert resp.value.json()["recurrence_interval"] == 7
    with page.expect_response(patched) as resp:
        drawer.locator("select[data-field='recurrence_anchor']").select_option("sat")
    assert resp.value.json()["recurrence_anchor"] == "sat"
    # the re-rendered list behind the drawer speaks the same words the CLI prints
    label = "'every 7 weeks on Saturday'"
    expect(page.locator(f".trow-recur[title={label}], .due-recur[title={label}]").first).to_be_attached()
    expect(every).to_have_value("7")
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    shot(page, shots / "story-25-recurrence-interval-1-desktop.png")

    old_due = date.fromisoformat(review["due"])
    assert old_due.weekday() == 5, f"the seed's review is due {old_due:%A}, the walk expects a Saturday"
    page.locator("#taskDrawer select[data-field='status']").select_option("complete")
    expect(page.locator("#taskDrawer input[data-field='due']")).not_to_have_value(review["due"])
    rolled = date.fromisoformat(page.locator("#taskDrawer input[data-field='due']").input_value())
    assert rolled == old_due + timedelta(weeks=7), f"rolled to {rolled}, expected 7 weeks after {old_due}"
    assert page.request.get(task_url).json()["recurrence_interval"] == 7

    page.request.patch(task_url, data={
        "recurrence": "weekly", "recurrence_anchor": "fri", "recurrence_interval": None,
        "due": review["due"],
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
    shot(page, shots / "story-04-triage-11-desktop.png")
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
# shared with the phone leg below, so the walk restores what it changed
# (statuses, starts, the seeded plan) before returning.


def _walk_plan_my_day(page: Page, base: str, shots: Path) -> None:
    """The morning ritual: My plan sits on top of Today with a progress line;
    emptied, the banner offers plan mode, where every candidate takes two
    large targets — Today (commits it) and Later (the #87 snooze popover) —
    and a task planned the day before wears its "planned yesterday" note.
    Committed tasks reorder by drag; completing one moves the progress line.

    Screenshots: docs/screenshots/story-15-plan-my-day-{1..5}-desktop.png
    (6 = dark, in the dark context; 7 = phone, in the phone leg).
    """
    today = E2E_ANCHOR.isoformat()

    # 1. The seed's plan renders ordered on top of Today, with the progress line.
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    plan = page.locator("#paneToday .today-plan")
    expect(plan).to_be_visible()
    expect(plan.locator(".today-counts")).to_have_text("0 of 2 done")
    expect(plan.locator(".plan-list .trow .trow-title")).to_have_text(
        ["Look into a standing desk", "Try the new bakery"])
    shot(page, shots / "story-15-plan-my-day-1-desktop.png")

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
    shot(page, shots / "story-15-plan-my-day-2-desktop.png")

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
    shot(page, shots / "story-15-plan-my-day-3-desktop.png")

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
    # The rows swap in the DOM while the drag is still over them (`dragover`),
    # but the new order is POSTed only on `dragend`, so the DOM matching says
    # nothing yet about the server. Wait for the write itself before reading
    # it back (#236: the read below once returned the old order).
    def reordered(r) -> bool:  # noqa: ANN001 — a Playwright Response
        return r.request.method == "POST" and r.url.endswith("/api/plan/reorder")

    with page.expect_response(reordered):
        tap_planned.drag_to(desk_planned)
    expect(page.locator("#paneToday .plan-list .trow .trow-title").first).to_have_text("Fix leaking tap")
    api_plan = _get(base, "/api/today")["plan"]
    assert [t["title"] for t in api_plan["items"]] == ["Fix leaking tap", "Look into a standing desk"]
    shot(page, shots / "story-15-plan-my-day-4-desktop.png")
    _trow(page, "Fix leaking tap", "#paneToday .plan-list").locator(".trow-done").click()
    expect(plan.locator(".today-counts")).to_have_text("1 of 2 done")
    done_row = _trow(page, "Fix leaking tap", "#paneToday .plan-list")
    expect(done_row).to_have_class(re.compile(r"\bis-closed\b"))
    api_plan = _get(base, "/api/today")["plan"]
    assert (api_plan["done"], api_plan["total"]) == (1, 2)
    shot(page, shots / "story-15-plan-my-day-5-desktop.png")

    # ---- restore: the file's seeded instance serves the phone leg ---------
    # tap back to todo and out of the plan; the bakery back in (the seeded
    # plan's shape); the library awake again via the drawer (story-13 idiom).
    done_row.locator(".trow-done").click()   # a closed row: the circle reopens it
    expect(plan.locator(".today-counts")).to_have_text("0 of 2 done")
    _trow(page, "Fix leaking tap", "#paneToday .plan-list").locator(".plan-unplan").click()
    expect(_trow(page, "Fix leaking tap", "#paneToday .plan-list")).to_have_count(0)
    page.locator("#paneToday .plan-more").click()
    _trow(page, "Try the new bakery", "#paneToday .plan-cands").locator("button.plan-target").click()
    expect(_trow(page, "Try the new bakery", "#paneToday .plan-list")).to_be_visible()
    page.locator("#paneToday .plan-done-btn").click()
    expect(page.locator("#paneToday .plan-list .trow .trow-title")).to_have_text(
        ["Look into a standing desk", "Try the new bakery"])
    # One hash navigation, one load (#236): it fires `popstate` and
    # `hashchange`, and while both opened the drawer the slower of the two
    # loads — read before the edit below — could paint over the edit's own
    # refresh, leaving the label on "Starts · in 7d" for a task the server had
    # already cleared (1 run in 8, and the rest of the gallery drifted after it).
    loads: list[str] = []
    task_path = f"/api/tasks/{lib_id}"

    def on_request(r) -> None:  # noqa: ANN001 — a Playwright Request
        if r.method == "GET" and r.url.endswith(task_path):
            loads.append(r.url)

    page.on("request", on_request)
    page.goto(f"{base}/#task/{lib_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    page.remove_listener("request", on_request)
    assert len(loads) == 1, f"one hash navigation loaded the task {len(loads)} times"
    starts_input = drawer.locator(".field-starts input[data-field='starts']")
    starts_input.fill("")
    starts_input.blur()
    # The field's own label is the *re-render* signal: `dateField` appends
    # " · <caption>" only while the field has a value, so a bare "Starts"
    # means the PATCH came back and the drawer redrew from the response.
    # Asserting on the input alone would pass on the local edit and let the
    # API read below race the write.
    expect(drawer.locator(".field-starts .field-label")).to_have_text("Starts")
    assert _get(base, f"/api/tasks/{lib_id}")["starts"] is None
    assert _get(base, f"/api/tasks/{tap_id}")["status"] == "todo"


# ------------------------------------------- story 30 — Today split (#336)

def _walk_today_split(page: Page, base: str, shots: Path) -> None:
    """Today at 1440: the list takes the left half, the detail pane the right.

    With nothing open the right half says so (an empty state, not a blank), and
    the list keeps its half width, so a row's ⋯ stays near its title. Opening a
    task fills that same right half (no overlay), the ``#task/<id>`` link works
    on a cold load, and closing returns to the empty state. Other tabs keep the
    440px panel.

    Screenshots: docs/screenshots/story-30-today-split-{1,2,3}-desktop.png
    """
    page.goto(f"{base}/")
    pane = page.locator("#paneToday")
    drawer = page.locator("#taskDrawer")
    empty = page.locator("#todayDetailEmpty")
    expect(pane.locator(".today-group .trow").first).to_be_visible()

    # 1. Nothing open: the empty state fills the right half, the list the left.
    expect(drawer).to_be_hidden()
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("Select a task to see its details")
    list_box, empty_box = pane.bounding_box(), empty.bounding_box()
    assert list_box and empty_box
    assert list_box["x"] + list_box["width"] <= empty_box["x"] + 1, (list_box, empty_box)
    assert 0.35 * DESKTOP["width"] <= list_box["width"] <= 0.6 * DESKTOP["width"], list_box
    assert 0.35 * DESKTOP["width"] <= empty_box["width"] <= 0.6 * DESKTOP["width"], empty_box
    kebab = pane.locator(".today-group .trow-kebab").first.bounding_box()
    assert kebab and kebab["x"] + kebab["width"] <= empty_box["x"], "the ⋯ must sit inside the list half"
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-30-today-split-1-desktop.png")

    # 2. ⋯ → Open details fills the right half in place of the empty state, and
    #    the menu opens whole, inside the window.
    row = pane.locator(".today-group .trow").first
    task_id = int(row.get_attribute("data-id"))
    row.locator(".trow-kebab").click()
    menu = page.locator(".row-menu")
    expect(menu).to_be_visible()
    menu_box = menu.bounding_box()
    assert menu_box and menu_box["x"] >= 0 and menu_box["x"] + menu_box["width"] <= DESKTOP["width"], menu_box
    assert menu_box["y"] >= 0 and menu_box["y"] + menu_box["height"] <= DESKTOP["height"], menu_box
    menu.locator("[data-action='open']").click()
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(page).to_have_url(f"{base}/#task/{task_id}")
    drawer_box, list_box = drawer.bounding_box(), pane.bounding_box()
    assert drawer_box and list_box
    assert abs(drawer_box["x"] - empty_box["x"]) <= 1 and abs(drawer_box["width"] - empty_box["width"]) <= 1, (
        drawer_box, empty_box)
    assert list_box["x"] + list_box["width"] <= drawer_box["x"] + 1, (list_box, drawer_box)
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-30-today-split-2-desktop.png")

    # 3. Closing returns to the empty state, and the cold deep link opens the
    #    pane on Today (the landing tab) without an overlay.
    drawer.locator(".drawer-close").click()
    expect(drawer).to_be_hidden()
    expect(empty).to_be_visible()
    page.goto(f"{base}/#task/{task_id}")
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
    shot(page, shots / "story-30-today-split-3-desktop.png")

    # 4. The other tabs keep the 440px panel and show no empty pane.
    page.click("nav.tabs .tab[data-tab='table']")
    box = drawer.bounding_box()
    assert box and 400 <= box["width"] <= 480, box
    drawer.locator(".drawer-close").click()
    expect(empty).to_be_hidden()
    page.click("nav.tabs .tab[data-tab='today']")
    expect(empty).to_be_visible()


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
    today = E2E_ANCHOR
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
    shot(page, shots / "story-13-starts-snooze-1-desktop.png")
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
    # (the Table pane's second view since #161 — one pane, two drawings)
    tree_view(page)
    sleeping = _trow(page, "renew insurance", "#paneTable #treeHost")
    expect(sleeping).to_be_visible()
    expect(sleeping.locator(".trow-starts")).to_have_text(re.compile(r"^starts \d"))
    shot(page, shots / "story-13-starts-snooze-2-desktop.png")
    # the view is remembered: a reload comes back on the tree, not the grid (#161)
    page.reload()
    expect(page.locator("#paneTable #treeHost .tree")).to_be_visible()
    expect(page.locator("#paneTable #tableHost")).to_be_hidden()
    # …and a tab a pre-#161 build stored as `tree` lands in the same place
    # rather than dropping the user back on the default tab
    page.evaluate("() => { localStorage.setItem('task-os.tab', 'tree');"
                  " localStorage.removeItem('task-os.tableView'); }")
    page.reload()
    expect(page.locator("nav.tabs")).to_have_attribute("data-active-tab", "table")
    expect(page.locator("#paneTable #treeHost .tree")).to_be_visible()

    # 3. Deferred is a visible state, not an absence: the status multi-select's
    #    pseudo-value lists exactly the sleeping tasks, and the state is the URL.
    table_view(page)
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
    shot(page, shots / "story-13-starts-snooze-3-desktop.png")
    card.locator(".filter-clear").click()
    expect(page).to_have_url(f"{base}/")

    # 4. Snooze from a Today row's menu: pick an option, the task leaves, the
    #    toast names the day it went to — and Undo puts it straight back.
    page.click("nav.tabs .tab[data-tab='today']")
    row = _trow(page, "School enrolment forms", "#paneToday")
    expect(row).to_be_visible()
    task_id = int(row.get_attribute("data-id"))
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None
    row.locator(".trow-kebab").click()
    page.locator(".row-menu [data-action='snooze']").click()
    menu = page.locator(".snooze-pop .snooze-menu")
    expect(menu).to_be_visible()
    expect(menu.locator(".snooze-opt")).to_have_count(4)   # 3 phrases + pick a date
    shot(page, shots / "story-13-starts-snooze-4-desktop.png")
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

    # 4b. Story 29 (#311): the row's ⋯ menu, read in full. The kebab lists the
    #     row's actions — the shared table's, offered only where they apply,
    #     then the task's own links — and its Snooze… opens the date picker,
    #     commits through the same runner (toast + Undo), and the keyboard
    #     reaches the menu with `.`.
    row = _trow(page, "School enrolment forms", "#paneToday")
    kebab = row.locator(".trow-kebab")
    expect(kebab).to_have_attribute("aria-haspopup", "menu")
    dismiss_toasts(page)
    kebab.click()
    menu = page.locator(".row-menu")
    expect(menu).to_be_visible()
    expect(kebab).to_have_attribute("aria-expanded", "true")
    actions = menu.locator(".row-menu-item").evaluate_all("els => els.map(e => e.dataset.action)")
    assert actions[:3] == ["complete", "change-date", "snooze"], actions
    assert "reopen" not in actions and "status-todo" not in actions   # open task, already todo
    assert actions[-1] == "open"
    expect(menu.locator(".row-menu-item").first).to_be_focused()
    shot(page, shots / "story-29-row-actions-1-desktop.png")
    menu.locator("[data-action='snooze']").click()
    expect(menu).to_be_hidden()
    picker = page.locator(".snooze-pop .snooze-menu")
    expect(picker).to_be_visible()
    picker.get_by_text("Tomorrow", exact=True).click()
    tomorrow = (today + timedelta(days=1)).isoformat()
    toast = page.locator(".toast-success").last
    expect(toast).to_contain_text("Snoozed to")
    expect(toast.locator(".toast-action")).to_have_text("Undo (Z)")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] == tomorrow
    toast.locator(".toast-action").click()
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_be_visible()
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None
    # `.` on a focused row opens its menu; Escape closes it, focus back on the kebab
    _trow(page, "School enrolment forms", "#paneToday").locator(".trow-main").focus()
    page.keyboard.press(".")
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(_trow(page, "School enrolment forms", "#paneToday").locator(".trow-kebab")).to_be_focused()
    dismiss_toasts(page)

    # 4c. Story 29 (#311): Settings → Row actions sets, on this device, what a
    #     swipe runs and what the menu lists. Swipe left → Snooze…, Cycle
    #     priority out of the menu, Snooze… moved to the top: the row's menu
    #     follows, a swipe left opens the snooze picker, and the action a
    #     swipe runs cannot be taken out of the menu (WCAG 2.5.1). Reset puts
    #     the plan's defaults back.
    page.click("#settingsBtn")
    card = page.locator("#rowActionsCard")
    card.locator("summary").click()
    meta = page.locator("#rowActionsMeta")
    expect(meta).to_have_text("Default")
    page.select_option("#swipeLeftSelect", "snooze")
    lst = page.locator("#rowMenuList")
    expect(lst.locator("[data-action='snooze'] .row-actions-tick")).to_have_attribute("aria-pressed", "true")
    expect(lst.locator("[data-action='snooze'] .row-actions-tick")).to_be_disabled()
    expect(lst.locator("[data-action='snooze'] .row-actions-hint")).to_have_text("used by swipe left")
    lst.locator("[data-action='priority'] .row-actions-tick").click()
    expect(lst.locator("[data-action='priority'] .row-actions-tick")).to_have_attribute("aria-pressed", "false")
    # every control on the card is a real 44px target (the design review's TOUCH-01)
    assert_min_target(lst.locator(".row-actions-tick, .row-actions-move"))
    # …and their glyphs sit on the icons.size inline step (the design review's COMP-02)
    sizes = lst.locator(".row-actions-tick svg, .row-actions-move svg").evaluate_all(
        "els => els.map(e => Math.round(e.getBoundingClientRect().width))")
    assert set(sizes) == {16}, sizes
    for _ in range(3):                                   # 4th in the default list → 1st
        lst.locator("[data-action='snooze'] [data-move='up']").click()
    expect(lst.locator(".row-actions-item").first).to_have_attribute("data-action", "snooze")
    expect(lst.locator("[data-action='snooze'] [data-move='up']")).to_be_disabled()
    expect(meta).to_have_text("Custom")
    stored = page.evaluate("JSON.parse(localStorage.getItem('task-os.rowactions'))")
    assert stored["left"] == "snooze" and stored["menu"][0] == "snooze" and "priority" not in stored["menu"], stored
    card.scroll_into_view_if_needed()
    shot(page, shots / "story-29-row-actions-2-desktop.png")
    page.click("nav.tabs .tab[data-tab='today']")
    row = _trow(page, "School enrolment forms", "#paneToday")
    row.locator(".trow-kebab").click()
    actions = page.locator(".row-menu .row-menu-item").evaluate_all("els => els.map(e => e.dataset.action)")
    assert actions[0] == "snooze" and "priority" not in actions, actions
    page.keyboard.press("Escape")
    expect(page.locator(".row-menu")).to_have_count(0)
    row.locator(".trow-main").evaluate(_SWIPE, [900, 300])          # synthetic touch: the wiring
    picker = page.locator(".snooze-pop .snooze-menu")
    expect(picker).to_have_attribute("data-field", "starts")
    page.keyboard.press("Escape")
    expect(picker).to_have_count(0)
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None    # a cancelled pick writes nothing
    page.click("#settingsBtn")
    page.click("#rowActionsReset")
    expect(meta).to_have_text("Default")
    assert page.evaluate("localStorage.getItem('task-os.rowactions')") is None
    page.click("nav.tabs .tab[data-tab='today']")

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
    # shared with the phone leg below, so a task left asleep here would vanish
    # from its Today.
    starts_input.fill("")
    starts_input.blur()
    expect(starts_input).to_have_value("")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None


# ------------------------------------------------------------- phone leg

def _walk_phone_table_cards_and_drawer_sheet(base: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): the Table as the shared rows, drawer
    full-screen, 44px targets (the row's completion circle and ⋯ kebab are
    each a full 44x44 box either side of the open target, #311)."""
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
        page.goto(f"{base}/?status=todo")
        page.locator("nav.tabs .tab[data-tab='table']").tap()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        rows = page.locator("#paneTable .table-rows .trow")
        expect(rows).to_have_count(_get(base, "/api/tasks?status=todo")["count"])
        # phone: the grid is not rendered at all — the Table is the ONE shared
        # row (circle + title, the one passive meta line with the project in it,
        # the ⋯ menu — no status select on the row since #311)
        expect(page.locator(".task-table")).to_have_count(0)
        watering = _trow(page, "Fix watering schedule drift", "#paneTable")
        expect(watering.locator(".trow-project")).to_have_text("Side project: garden-bot")
        expect(watering.locator(".trow-due")).to_be_visible()
        expect(watering).to_have_attribute("data-status", "todo")
        expect(rows.locator(".trow-status")).to_have_count(0)
        assert_no_horizontal_overflow(page)
        # the top strip (#80): the text filter, the view toggle's two halves
        # (#161) and the + sit side by side, all at the touch floor, with
        # effective rectangles that never overlap — the segmented pair joins on
        # a shared hairline, so its halves touch without their hit rects doing
        strip = page.locator("#paneTable .filter-q, #paneTable .view-seg, #paneTable .quick-add-btn")
        assert_min_target(strip)
        assert_no_overlap(strip)
        page.locator("#paneTable .quick-add-btn").tap()
        expect(page.locator("#quickAdd")).to_be_visible()
        assert_min_target(page.locator("#quickAdd .quick-add-input"))
        page.keyboard.press("Escape")
        expect(page.locator("#quickAdd")).to_be_hidden()
        # the shared filter card: the status multi-select holds the five statuses,
        # the URL's one checked; on the phone the controls sit two per line,
        # equal widths (#48)
        card = _open_filters(page, "tableFilters")
        status_sel = card.locator(".msel[data-name='status']")
        status_sel.locator("summary.msel-summary").click()
        # five statuses + `deferred` (#87) + `blocked` (#100), the pseudo-values
        # that show the sleeping and the locked tasks the working views leave out
        expect(status_sel.locator("input[name='status']")).to_have_count(7)
        expect(status_sel.locator("input[name='status'][value='deferred']")).to_have_count(1)
        expect(status_sel.locator("input[name='status'][value='blocked']")).to_have_count(1)
        expect(status_sel.locator("input[name='status'][value='todo']")).to_be_checked()
        page.keyboard.press("Escape")
        boxes = card.locator(".filter-row > .filter-select, .filter-row > .msel").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.width)]; })")
        assert len(boxes) == 6, boxes
        lefts = sorted(set(b[0] for b in boxes))
        assert len(lefts) == 2, boxes                                  # two columns
        assert max(b[1] for b in boxes) - min(b[1] for b in boxes) <= 2, boxes   # equal widths
        # rows are >=44px tall, and the row's two controls — the completion
        # circle and the ⋯ kebab — are real 44x44 boxes that never overlap the
        # open target between them (#311)
        assert_min_target(rows)
        assert_min_target(rows.locator(".trow-done"))
        assert_min_target(rows.locator(".trow-kebab"))
        assert_no_overlap(rows.locator(".trow-done, .trow-main, .trow-kebab"))
        sizes = rows.locator(".trow-done, .trow-kebab").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })")
        assert sizes and all(w == 44 and h == 44 for w, h in sizes), sizes
        # #74 round 2: a folder never makes a card taller. It is a passive glyph
        # on the one meta line like every other item, so a row that has one is
        # exactly as tall as a plain one. (Rows above that height are metas
        # that wrapped - a different thing, and not what the folder caused.)
        by_folder = rows.evaluate_all(
            "els => els.map(e => [!!e.querySelector('.trow-folder'),"
            " Math.round(e.getBoundingClientRect().height)])")
        assert any(f for f, _ in by_folder) and any(not f for f, _ in by_folder), by_folder
        # (the list's first row has no hairline above it, so it is 1px shorter:
        # the claim is that a folder row is no taller than a plain one)
        plain_h = {h for f, h in by_folder if not f}
        assert {h for f, h in by_folder if f} <= plain_h, by_folder
        # #311: the row is circle · title-over-meta · kebab, level with each
        # other, no taller than 60px (+ the hairline) with its meta line, and
        # the kebab sits at the row's right edge
        done_box = watering.locator(".trow-done").bounding_box()
        main_box = watering.locator(".trow-main").bounding_box()
        kebab_box = watering.locator(".trow-kebab").bounding_box()
        row_box = watering.bounding_box()
        assert done_box and main_box and kebab_box and row_box
        assert row_box["height"] <= 61, row_box
        row_mid = row_box["y"] + row_box["height"] / 2
        for box in (done_box, kebab_box):
            assert abs((box["y"] + box["height"] / 2) - row_mid) <= 8, (box, row_box)
        assert done_box["x"] + done_box["width"] <= main_box["x"] + 1, (done_box, main_box)
        assert main_box["x"] + main_box["width"] <= kebab_box["x"] + 1, (main_box, kebab_box)
        assert abs((kebab_box["x"] + kebab_box["width"]) - (row_box["x"] + row_box["width"])) <= 8, (kebab_box, row_box)
        assert page.locator("#paneTable .table-rows").evaluate("el => getComputedStyle(el).borderRadius") == "0px"
        shot(page, shots / "story-04-triage-9-phone.png")

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
        shot(page, shots / "story-04-triage-10-phone.png")
        drawer.locator(".drawer-close").tap()
        expect(drawer).to_be_hidden()
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "visible"

        # --------------------------------------------- story 13 (#87) ----
        # The snooze control is a real touch target on the phone — this is the
        # device where "not today" is most often decided — and its popover
        # never pushes the page sideways.
        page.goto(f"{base}/")          # drop the story's ?status=todo first
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        expect(page.locator("#paneToday")).to_be_visible()
        today_row = page.locator("#paneToday .today-group .trow").first
        expect(today_row).to_be_visible()
        # the row has no clock any more (#311): snooze lives in the ⋯ menu,
        # whose kebab is a touch target clear of the circle and the open target
        assert_min_target(page.locator("#paneToday .today-group .trow-kebab"))
        assert_no_overlap(page.locator("#paneToday .today-group .trow-done, "
                                       "#paneToday .today-group .trow-main, "
                                       "#paneToday .today-group .trow-kebab"))
        today_row.locator(".trow-kebab").tap()
        page.locator(".row-menu [data-action='snooze']").tap()
        menu = page.locator("dialog#dateDialog .snooze-menu.date-sheet")
        expect(menu).to_be_visible()
        assert_min_target(menu.locator(".snooze-opt"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-13-starts-snooze-6-phone.png")
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()

        # the sleeping seed task wears its marker wherever it still shows
        page.goto(f"{base}/?status=deferred")
        page.locator("nav.tabs .tab[data-tab='table']").tap()
        sleeping = _trow(page, "Book boiler service", "#paneTable")
        expect(sleeping).to_be_visible()
        expect(sleeping.locator(".trow-starts")).to_have_text(re.compile(r"^starts \d"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-13-starts-snooze-7-phone.png")

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
        shot(page, shots / "story-15-plan-my-day-7-phone.png")

        # --------------------------------------------- story 25 (#229) ----
        # "Every [7] weeks" on the phone the PWA lives on: the interval input
        # is a real touch target with a digit keypad, beside its unit, and the
        # Repeat composer never pushes the sheet sideways.
        review = _get(base, "/api/tasks?q=Weekly%20review")["items"][0]
        task_url = f"{base}/api/tasks/{review['id']}"
        page.request.patch(task_url, data={"recurrence_anchor": "sat", "recurrence_interval": 7})
        page.goto(f"{base}/#task/{review['id']}")
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        every = drawer.locator("input[data-field='recurrence_interval']")
        expect(every).to_have_value("7")
        expect(every).to_have_attribute("inputmode", "numeric")
        expect(drawer.locator(".field-unit")).to_have_text("weeks")
        assert_min_target(every)
        assert_no_overlap(drawer.locator("select[data-field='recurrence'], "
                                         "input[data-field='recurrence_interval'], "
                                         "select[data-field='recurrence_anchor']"))
        every.scroll_into_view_if_needed()
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-25-recurrence-interval-2-phone.png")
        page.request.patch(task_url, data={"recurrence_anchor": "fri", "recurrence_interval": None})
        context.close()
    finally:
        wk.close()
