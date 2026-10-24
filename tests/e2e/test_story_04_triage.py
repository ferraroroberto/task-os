"""Story 04 — Monday triage (Step 4/13, issue #5).

    Board filtered status:todo → a row's ⋯ → Move… → Pick a date… opens
    the date picker and the pick lands → the activity log shows old → new with
    time → open a drawer → add a comment containing a link → the link is a
    clickable chip → the + opens the quick-add dialog (#80) → "renew passport
    next friday" → the parsed date shows as a chip → create → file it under a
    project with the drawer head's Change parent → the breadcrumb appears;
    Remove parent takes it back out (the Table and its Tree, where this story
    used to run, were removed in #350; the More-fields Move to select went in
    #468).

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-04-triage-{1..8}-desktop.png
    docs/screenshots/story-04-triage-12-desktop.png   (the parent picker, #468)
    docs/screenshots/story-04-triage-11-desktop.png   (stale window, #101)

then — in the same test function since #96 — the drawer at 390×844 (WebKit,
touch) with the geometry checks:

    docs/screenshots/story-04-triage-9-phone.png   (the Board's rows)
    docs/screenshots/story-04-triage-10-phone.png  (drawer as a full-screen sheet)

UX round 3 (issue #46): the filter state is ONE state shared by every tab and
lives in the URL (``?status=todo`` is the same view on the Board and
Today), so a shared URL no longer moves the tab by itself — the story opens
the Board explicitly.

**Story 13 — start date + snooze (#87)** rides in this file too, as
``_walk_starts_and_snooze`` at the end of the desktop leg plus the phone
assertions in the phone leg. It is a story of its own in
``docs/validation.md``, not a new test: the e2e suite is capped at 15 tests
(CLAUDE.md) and already held 14, and this story walks the same surface —
the filter sheet, the quick-add dialog, a Today row, the drawer. Its shots:

    docs/screenshots/story-13-starts-snooze-{1,2,4,5}-desktop.png
    docs/screenshots/story-13-starts-snooze-{6,7}-phone.png

**Story 30 — Today's split view (#336)** rides here as ``_walk_today_split``
right after the stale-window walk, on the same Today surface: the list in the left
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
from tests.e2e._surface import surface
from tests.e2e._triage_steps import (
    _change_due_from_row,
    _change_parent_picker,
    _drawer_quick_moves_and_comment,
    _filtered_board,
    _open_drawer_with_activity,
    _parent_move_remove_and_cycle,
    _quick_add_create,
    _quick_add_fill,
    _trow,
)
from tests.e2e.conftest import (
    E2E_ANCHOR,
    SWIPE_JS,
    _get,
    board_mode,
    close_filter_sheet,
    dismiss_toasts,
    filter_button,
    open_filter_sheet,
    open_more_fields,
    open_settings_sheet,
    shot,
    text_contrast,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


# A native date picker is an OS widget no browser automation can see or drive,
# so `showPicker()` is recorded instead: the call is what "the picker opened"
# means from the page's side, and the `change` the test then dispatches on the
# same input is what the user picking a day produces (#107).
_RECORD_SHOW_PICKER = """
window.__pickerOpens = [];
HTMLInputElement.prototype.showPicker = function () { window.__pickerOpens.push(this.className); };
"""

# Where story 25's first shot frames the open drawer: its "More fields" row 784 px
# below the drawer's top edge, whatever the drawer was scrolled to getting there.
_FRAME_MORE_FIELDS_JS = """() => {
  const d = document.querySelector('#taskDrawer');
  const row = d.querySelector('details.drawer-more > summary');
  const top = row.getBoundingClientRect().top - d.getBoundingClientRect().top + d.scrollTop;
  d.scrollTop = Math.round(top) - 784;
}"""


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

        quotes = _filtered_board(page, base, shots)
        task_id, old_due, new_due = _change_due_from_row(page, base, shots, quotes)
        drawer = _open_drawer_with_activity(page, base, shots, task_id, old_due, new_due)
        surface(page, "board.drawer")
        _drawer_quick_moves_and_comment(page, context, base, shots, drawer, task_id, new_due)
        quick_add, qa, friday = _quick_add_fill(page, shots)
        surface(page, "app.quick-add")
        new_row, new_id = _quick_add_create(page, base, shots, quick_add, qa, friday)
        family_id, picker = _change_parent_picker(page, base, shots, new_row, new_id, drawer)
        surface(page, "app.parent-picker")
        _parent_move_remove_and_cycle(page, base, shots, new_id, family_id, picker, drawer)

        # ------------------------------- closed tasks on demand (#309) ----
        _walk_closed_on_demand(page, base)

        # ---------------------------------------------- story 13 (#87) ----
        _walk_starts_and_snooze(page, base, shots)

        # ------------------------------------------- stale window (#101) ----
        _walk_stale_window(page, base, shots)

        # ------------------------------ one task load per hash open (#236) ----
        _walk_hash_open_loads_once(page, base)

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
    finally:
        dark_ctx.close()

    _walk_phone_rows_and_drawer_sheet(base, playwright, shots)

# ------------------------------------------ closed tasks on demand (#309)
#
# Riding inside this test because the suite is capped (CLAUDE.md): no shots,
# the default views are unchanged, so the gallery does not move. It runs in its own context — a cold boot, an empty HTTP cache
# — so every recorded response is a 200 with a body to read.

def _flatten(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children") or []))
    return out


def _walk_closed_on_demand(page: Page, base: str) -> None:
    """The boot ships no closed tasks and no descriptions; a closed status in
    the filter is the list's to answer, never a second forest (#309, #350)."""
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
        # the header names Today's exceptions, never a bare open count (#393)
        expect(p.locator("#homeHeadStatus")).to_have_text(re.compile(r"^\d+ overdue · \d+ due today$"))
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

        # 2. A closed status in the filter: the Board shows the closed task off
        #    the filtered list, and nothing ever reads the closed forest.
        p.click("nav.tabs .tab[data-tab='board']")
        expect(_trow(p, "Buy a birthday gift", "#paneBoard")).to_have_count(0)
        open_filter_sheet(p, "paneBoard").locator(".filter-checks[data-name='status'] input[value='done']").check()
        close_filter_sheet(p)
        expect(_trow(p, "Buy a birthday gift", "#paneBoard")).to_be_visible()
        assert [r.url for r in calls("/api/tasks/tree") if "include_closed" in query(r)] == []
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
    open_more_fields(page.locator("#taskDrawer"))   # Repeat is a rare field (#394)
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
    open_more_fields(drawer)
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
    # The Every field already reads 7 before the drawer's re-render lands, so that
    # check settles nothing: the new activity rows are what the redraw adds (#459).
    expect(drawer.locator(".activity-row").nth(0)).to_contain_text("recurrence_anchor")
    expect(drawer.locator(".activity-row").nth(1)).to_contain_text("recurrence_interval")
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    # Frame the drawer rather than inherit its scroll offset (#459). Where it ends
    # up is whatever Playwright's scroll-into-view and the redraws between them
    # left, against a layout that was still moving (the drawer's content grows by
    # tens of pixels as each redraw lands), so one capture sat 46 px off the
    # baseline with every pixel of content identical. Park the "More fields" row at
    # the offset the baseline shows it, in the settled layout.
    page.evaluate(_FRAME_MORE_FIELDS_JS)
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
    page.click("nav.tabs .tab[data-tab='board']")
    open_filter_sheet(page, "paneBoard").locator("select[name='updated']").select_option("stale30")
    expect(page).to_have_url(f"{base}/?updated=stale30")
    close_filter_sheet(page)
    rows = page.locator("#paneBoard .trow[data-id]")
    expect(rows).to_have_count(1)
    expect(rows.locator(".trow-title")).to_have_text("Sort the garage shelves")
    expect(filter_button(page, "paneBoard")).to_have_attribute("aria-label", "Filter, 1 on: untouched > 30 days")
    expect(page.locator("#boardFilterText .filter-q")).to_have_attribute("placeholder", "Filter 1 task…")
    shot(page, shots / "story-04-triage-11-desktop.png")
    # the token round-trips: a fresh load of the shared URL is the same view
    page.goto(f"{base}/?updated=stale30")
    page.click("nav.tabs .tab[data-tab='board']")
    expect(rows).to_have_count(1)
    # 60 days back nothing is that old — an honest empty list, not an error
    open_filter_sheet(page, "paneBoard").locator("select[name='updated']").select_option("stale60")
    close_filter_sheet(page)
    expect(rows).to_have_count(0)


# ------------------------------------- one task load per hash open (#236)
#
# Riding here because the suite is capped (CLAUDE.md): no shots. This used to
# close the plan-my-day walk (story 15, removed in #369), which is where the
# race was found, so the check outlived the feature.


def _walk_hash_open_loads_once(page: Page, base: str) -> None:
    """One hash navigation, one load (#236): it fires `popstate` and
    `hashchange`, and while both opened the drawer the slower of the two
    loads — read before an edit — could paint over the edit's own refresh,
    leaving the label on "Starts · in 7d" for a task the server had already
    cleared (1 run in 8, and the rest of the gallery drifted after it)."""
    # Today is the landing tab and the last tab is remembered, so leave the app
    # where the next walk (Today's split view) expects to find it
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    lib_id = int(_get(base, "/api/tasks?q=Return%20library%20books")["items"][0]["id"])
    page.request.patch(f"{base}/api/tasks/{lib_id}", data={"starts": "next week"})
    loads: list[str] = []
    task_path = f"/api/tasks/{lib_id}"

    def on_request(r) -> None:  # noqa: ANN001 — a Playwright Request
        if r.method == "GET" and r.url.endswith(task_path):
            loads.append(r.url)

    page.on("request", on_request)
    page.goto(f"{base}/#task/{lib_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    # Today opens its first task in the drawer on its own (the split view), so a
    # visible drawer is not yet *this* task's: clearing Starts there writes
    # nothing, and the bare label it then shows is another task's.
    expect(drawer.locator("#drawerTitle")).to_have_value("Return library books")
    page.remove_listener("request", on_request)
    assert len(loads) == 1, f"one hash navigation loaded the task {len(loads)} times"
    open_more_fields(drawer)   # Starts is a rare field (#394)
    starts_input = drawer.locator(".field-starts input[data-field='starts']")
    expect(starts_input).not_to_have_value("")      # the seeded date is on screen to clear
    starts_input.fill("")
    starts_input.blur()
    # The field's own label is the *re-render* signal: `dateField` appends
    # " · <caption>" only while the field has a value, so a bare "Starts"
    # means the PATCH came back and the drawer redrew from the response.
    # Asserting on the input alone would pass on the local edit and let the
    # API read below race the write.
    expect(drawer.locator(".field-starts .field-label")).to_have_text("Starts")
    assert _get(base, f"/api/tasks/{lib_id}")["starts"] is None


# ------------------------------------------- story 30 — Today split (#336)

def _walk_today_split(page: Page, base: str, shots: Path) -> None:
    """Today at 1440: the list takes the left half, the detail pane the right.

    The right half is never empty while a task is due (#393, decision 8 of
    #390): a cold load opens the first due task there by itself, with no hash
    written, and the row keymap keeps working beside it. Closing it shows the
    empty state, and the list keeps its half width, so a row's ⋯ stays near its
    title. Opening a task fills that same right half (no overlay), the
    ``#task/<id>`` link works on a cold load. Other tabs keep the 440px panel,
    and the task Today opened by itself does not follow you there.

    Screenshots: docs/screenshots/story-30-today-split-{1,2,3}-desktop.png
    """
    page.goto(f"{base}/")
    pane = page.locator("#paneToday")
    drawer = page.locator("#taskDrawer")
    empty = page.locator("#todayDetailEmpty")
    first = pane.locator("section.today .trow[data-id]").first
    expect(first).to_be_visible()

    # 1. The first due task fills the right half on its own; the URL is still bare.
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(drawer.locator("#drawerTitle")).to_have_value(first.locator(".trow-title").inner_text())
    expect(page).to_have_url(f"{base}/")
    list_box, drawer_box = pane.bounding_box(), drawer.bounding_box()
    assert list_box and drawer_box
    assert list_box["x"] + list_box["width"] <= drawer_box["x"] + 1, (list_box, drawer_box)
    assert 0.35 * DESKTOP["width"] <= list_box["width"] <= 0.6 * DESKTOP["width"], list_box
    assert 0.35 * DESKTOP["width"] <= drawer_box["width"] <= 0.6 * DESKTOP["width"], drawer_box
    kebab = pane.locator(".today-group .trow-kebab").first.bounding_box()
    assert kebab and kebab["x"] + kebab["width"] <= drawer_box["x"], "the ⋯ must sit inside the list half"
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-30-today-split-1-desktop.png")
    surface(page, "today.split-drawer")
    # the keymap stays on beside it: a focused row still takes a key
    first.locator(".trow-main").focus()
    page.keyboard.press("?")
    expect(page.locator("#keysHelp")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#keysHelp")).to_be_hidden()
    expect(drawer).to_be_visible()

    # 2. Closed, the empty state holds the right half; ⋯ → Open details fills
    #    it again, and the menu opens whole, inside the window.
    drawer.locator(".drawer-close").click()
    expect(drawer).to_be_hidden()
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("Select a task to see its details")
    empty_box = empty.bounding_box()
    assert empty_box and abs(empty_box["x"] - drawer_box["x"]) <= 1, (empty_box, drawer_box)
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
    surface(page, "today.drawer-empty")

    # 3. The cold deep link opens its own task on Today (the landing tab),
    #    not the first due one, without an overlay.
    drawer.locator(".drawer-close").click()
    expect(drawer).to_be_hidden()
    last_id = int(pane.locator("section.today .trow[data-id]").last.get_attribute("data-id"))
    page.goto(f"{base}/#task/{last_id}")
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(drawer.locator("#drawerTitle")).to_have_value(
        pane.locator(f"section.today .trow[data-id='{last_id}'] .trow-title").inner_text())
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
    shot(page, shots / "story-30-today-split-3-desktop.png")

    # 4. The other tabs keep the 440px panel for a task you opened and show no
    #    empty pane; back on Today with nothing open, the first due task again.
    page.click("nav.tabs .tab[data-tab='board']")
    box = drawer.bounding_box()
    assert box and 400 <= box["width"] <= 480, box
    drawer.locator(".drawer-close").click()
    expect(empty).to_be_hidden()
    page.click("nav.tabs .tab[data-tab='today']")
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(page).to_have_url(f"{base}/")
    # 5. …and the task Today opened by itself stays on Today.
    page.click("nav.tabs .tab[data-tab='board']")
    expect(drawer).to_be_hidden()
    page.click("nav.tabs .tab[data-tab='today']")
    expect(drawer).to_be_visible()


# ---------------------------------------------- story 13 — starts + snooze
#
# Rides inside this file rather than becoming a 15th test: the e2e suite is
# capped at 15 (CLAUDE.md) and sat at 14, and this story is a continuation of
# the same triage surface — the filter card, a Today row, the quick-add dialog.


def _walk_starts_and_snooze(page: Page, base: str, shots: Path) -> None:
    """A task created asleep stays out of the working views until its day, is
    findable under *Deferred*, and a Today row can be pushed away and undone.

    Screenshots: docs/screenshots/story-13-starts-snooze-{1,2,4,5}-desktop.png
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

    # 2. It is nowhere in the working views — Today, the Board.
    expect(_trow(page, "renew insurance", "#paneToday")).to_have_count(0)
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator("#paneBoard")).to_be_visible()
    expect(page.locator("#paneBoard").get_by_text("renew insurance", exact=True)).to_have_count(0)

    # 3. Deferred is a visible state, not an absence: the status ticks'
    #    pseudo-value lists exactly the sleeping tasks, each wearing the marker
    #    that says why the working views are quiet about it, and the state is
    #    the URL.
    open_filter_sheet(page, "paneBoard").locator(".filter-checks[data-name='status'] input[value='deferred']").check()
    expect(page).to_have_url(f"{base}/?status=deferred")
    close_filter_sheet(page)
    expect(filter_button(page, "paneBoard")).to_have_attribute("aria-label", "Filter, 1 on: deferred")
    rows = page.locator("#paneBoard .trow[data-id]")
    # the seed's own deferred task plus the one just created — and nothing else
    expect(rows).to_have_count(2)
    titles = rows.locator(".trow-title").all_inner_texts()
    assert sorted(titles) == ["Book boiler service", "renew insurance"], titles
    expect(rows.locator(".trow-starts")).to_have_count(2)
    # #392: a neutral exception chip — the clock says "snoozed until", the day follows
    snoozed = _trow(page, "renew insurance", "#paneBoard").locator(".trow-starts")
    expect(snoozed).to_have_text(re.compile(r"^\d+ \w{3}$"))
    expect(snoozed).to_have_attribute("data-tone", "neutral")
    expect(snoozed).to_have_attribute("title", re.compile(r"^Snoozed until \w{3} \d+ \w{3}$"))
    dismiss_toasts(page)
    shot(page, shots / "story-13-starts-snooze-2-desktop.png")
    open_filter_sheet(page, "paneBoard").locator(".filter-clear").click()
    close_filter_sheet(page)
    expect(page).to_have_url(f"{base}/")

    # 4. Snooze from a Today row's menu: pick an option, the task leaves, the
    #    toast names the day it went to — and Undo puts it straight back.
    page.click("nav.tabs .tab[data-tab='today']")
    row = _trow(page, "School enrolment forms", "#paneToday")
    expect(row).to_be_visible()
    task_id = int(row.get_attribute("data-id"))
    # The completion circle is an .icon-button over the vendored action-row (project-scaffolding#339);
    # it keeps its own success tone, pressed and on hover, over their attention / ink.
    done = row.locator(".trow-done")
    want = page.evaluate("""() => { const p = document.createElement('i'); p.style.color = 'var(--success)';
      document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; }""")
    done.hover()
    assert done.evaluate("el => getComputedStyle(el).color") == want
    page.mouse.move(0, 0)
    pressed = done.evaluate("""el => { el.setAttribute('aria-pressed', 'true'); const c = getComputedStyle(el).color;
      el.setAttribute('aria-pressed', 'false'); return c; }""")
    assert pressed == want
    before = _get(base, f"/api/tasks/{task_id}")
    assert before["starts"] is None
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
    snoozed = _get(base, f"/api/tasks/{task_id}")
    assert snoozed["starts"] == next_week
    # #486: the due date travels with the start when it would fall before it,
    # so the task is never left asleep past its own due day
    assert before["due"] and before["due"] < next_week, before["due"]
    assert snoozed["due"] == next_week
    expect(toast).to_contain_text("due moved too")
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_have_count(0)
    # the change is in the log like any other field change
    assert "starts" in [a["field"] for a in _get(base, f"/api/tasks/{task_id}")["activity"]]

    toast.locator(".toast-action").click()
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_be_visible()
    undone = _get(base, f"/api/tasks/{task_id}")
    assert (undone["starts"], undone["due"]) == (None, before["due"])   # Undo restores both

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
    surface(page, "today.row-menu")
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
    card = open_settings_sheet(page, "rows")
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
    row.locator(".trow-main").evaluate(SWIPE_JS, [900, 300])          # synthetic touch: the wiring
    picker = page.locator(".snooze-pop .snooze-menu")
    expect(picker).to_have_attribute("data-field", "starts")
    page.keyboard.press("Escape")
    expect(picker).to_have_count(0)
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None    # a cancelled pick writes nothing
    open_settings_sheet(page, "rows")
    page.click("#rowActionsReset")
    expect(meta).to_have_text("Default")
    assert page.evaluate("localStorage.getItem('task-os.rowactions')") is None
    page.click("nav.tabs .tab[data-tab='today']")

    # 5. The drawer edits Starts with Due's control, one behaviour; Starts
    #    sits under More fields since #394.
    page.goto(f"{base}/#task/{task_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("School enrolment forms")   # not Today's own first task
    open_more_fields(drawer)
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
    # The input is empty the instant it is cleared, so on its own that proves
    # nothing about the write. A bare "Starts" label is the re-render signal
    # (`dateField` appends " · <caption>" only while a value is set): the PATCH
    # came back and the drawer redrew from it, so the API read below cannot race.
    expect(drawer.locator(".field-starts .field-label")).to_have_text("Starts")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None


# ------------------------------------------------------------- phone leg

def _walk_phone_rows_and_drawer_sheet(base: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): the Board's Todo column as the shared rows,
    drawer full-screen, 44px targets (the row's completion circle and ⋯ kebab are
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
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        # every todo task, the synced issue's included (#391's All scope)
        page.locator("#boardScope .segmented-item[data-scope='all']").tap()
        rows = page.locator("#paneBoard .trow[data-id]")
        expect(rows).to_have_count(_get(base, "/api/tasks?status=todo")["count"])
        # the ONE shared row (circle + title, the one passive meta line with the
        # project in it, the ⋯ menu — no status select on the row since #311)
        watering = _trow(page, "Fix watering schedule drift", "#paneBoard")
        expect(watering.locator(".trow-project")).to_have_text("Side project: garden-bot")
        expect(watering.locator(".trow-due")).to_be_visible()
        expect(watering).to_have_attribute("data-status", "todo")
        expect(rows.locator(".trow-status")).to_have_count(0)
        assert_no_horizontal_overflow(page)
        # the top strip (#80, #395): the text filter, the filter button, the
        # Select toggle and the + sit side by side on one line, all at the
        # touch floor, with effective rectangles that never overlap; pressed,
        # the toggle says its name in accent-text on the accent tint, 4.5:1
        # (WCAG 1.4.3): a word, not a glyph's 3:1 (#339)
        strip = page.locator("#paneBoard .filter-q, #paneBoard .filter-open, #paneBoard [data-select-toggle], #paneBoard .quick-add-btn")
        tops = strip.evaluate_all("els => els.map(e => Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2))")
        assert max(tops) - min(tops) <= 2, tops                         # one line
        assert_min_target(strip)
        assert_no_overlap(strip)
        page.locator("#paneBoard [data-select-toggle]").tap()
        pressed = page.locator("#paneBoard [data-select-toggle][aria-pressed='true'] .strip-label")
        expect(pressed).to_be_visible()
        assert text_contrast(pressed) >= 4.5, text_contrast(pressed)
        page.locator("#paneBoard [data-select-toggle]").tap()
        expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "false")
        page.locator("#paneBoard .quick-add-btn").tap()
        expect(page.locator("#quickAdd")).to_be_visible()
        assert_min_target(page.locator("#quickAdd .quick-add-input"))
        page.keyboard.press("Escape")
        expect(page.locator("#quickAdd")).to_be_hidden()
        # rows are >=44px tall; a touch screen draws no completion circle
        # (#350: a swipe right or the drawer's status closes a task), so the
        # row's one control is the ⋯ kebab, a real 44x44 box that never
        # overlaps the open target (#311)
        assert_min_target(rows)
        expect(rows.locator(".trow-done").first).to_be_hidden()
        assert_min_target(rows.locator(".trow-kebab"))
        assert_no_overlap(rows.locator(".trow-main, .trow-kebab"))
        sizes = rows.locator(".trow-kebab").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })")
        assert sizes and all(w == 44 and h == 44 for w, h in sizes), sizes
        # #74 round 2, #392: nothing on the meta line makes a card taller. An
        # exception chip sits on the one meta line like every other part, so a
        # row that wears one is exactly as tall as a plain one; the folder
        # glyph that used to be the case here left the row for its menu.
        by_flag = rows.evaluate_all(
            "els => els.map(e => [!!e.querySelector('.trow-flag'),"
            " Math.round(e.getBoundingClientRect().height)])")
        assert any(f for f, _ in by_flag) and any(not f for f, _ in by_flag), by_flag
        # (the list's first row has no hairline above it, so it is 1px shorter:
        # the claim is that a chip row is no taller than a plain one)
        plain_h = {h for f, h in by_flag if not f}
        assert {h for f, h in by_flag if f} <= plain_h, by_flag
        # #311: the row is title-over-meta · kebab, level with each other, no
        # taller than 60px (+ the hairline) with its meta line, the kebab at
        # the row's right edge
        main_box = watering.locator(".trow-main").bounding_box()
        kebab_box = watering.locator(".trow-kebab").bounding_box()
        row_box = watering.bounding_box()
        assert main_box and kebab_box and row_box
        assert row_box["height"] <= 61, row_box
        row_mid = row_box["y"] + row_box["height"] / 2
        assert abs((kebab_box["y"] + kebab_box["height"] / 2) - row_mid) <= 8, (kebab_box, row_box)
        assert main_box["x"] + main_box["width"] <= kebab_box["x"] + 1, (main_box, kebab_box)
        assert abs((kebab_box["x"] + kebab_box["width"]) - (row_box["x"] + row_box["width"])) <= 8, (kebab_box, row_box)
        shot(page, shots / "story-04-triage-9-phone.png")
        # (after the shot: the pill hides while a dialog is up, and a capture
        # right after one closes can catch the frosted bar mid-repaint)
        # the filter sheet (#395): every filter and the sort in one place, sort
        # first; status holds the five statuses + `deferred` (#87) + `blocked`
        # (#100), the pseudo-values that show the sleeping and the locked tasks
        # the working views leave out, the URL's one ticked; on the phone the
        # ticks sit two per line, every one a 44px target, none overlapping
        sheet = open_filter_sheet(page, "paneBoard")
        names = sheet.locator(".filter-sheet-row").evaluate_all("els => els.map(e => e.dataset.name)")
        assert names == ["sort", "status", "project", "person", "due", "updated"], names
        status = sheet.locator(".filter-checks[data-name='status']")
        expect(status.locator("input[name='status']")).to_have_count(7)
        expect(status.locator("input[name='status'][value='deferred']")).to_have_count(1)
        expect(status.locator("input[name='status'][value='blocked']")).to_have_count(1)
        expect(status.locator("input[name='status'][value='todo']")).to_be_checked()
        ticks = sheet.locator(".filter-check")
        assert_min_target(ticks)
        assert_no_overlap(ticks)
        lefts = sorted(set(status.locator(".filter-check").evaluate_all(
            "els => els.map(e => Math.round(e.getBoundingClientRect().x))")))
        assert len(lefts) == 2, lefts                                   # two columns
        assert_min_target(sheet.locator(".filter-select, .detail-close, .filter-done"))
        # a sheet that outgrows the phone scrolls: its footer ends the sheet
        # rather than riding pinned over the last rows, where it overlapped a
        # select's tap area (TOUCH-02, the live walk after #404 — the seed's
        # sheet fits, so the cause is asserted, not the overlap)
        assert sheet.locator(".filter-actions").evaluate("el => getComputedStyle(el).position") == "static"
        assert_no_overlap(sheet.locator(".filter-select, .filter-check, .filter-done"))
        close_filter_sheet(page)

        # the drawer is a full-screen sheet; the pill is hidden while it is up
        _trow(page, "Get three quotes", "#paneBoard").locator(".trow-main").tap()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        box = drawer.bounding_box()
        assert box and box["width"] >= PHONE["width"] - 1 and box["height"] >= PHONE["height"] - 1, box
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "hidden"
        assert_min_target(drawer.locator(".drawer-close"))
        assert_min_target(drawer.locator(".field-control:visible"))
        assert_min_target(drawer.locator(".comment-send"))
        # the quick moves are two by two on the phone, each a whole target (#394)
        assert_min_target(drawer.locator(".quick-move"))
        assert_no_overlap(drawer.locator(".quick-move"))
        # UX round 2 (#32): the composer keeps the Ctrl+Enter hint; Send stays
        # on the Description "Edit" tier (ghost, same rendered height).
        expect(drawer.locator(".comment-input")).to_have_attribute(
            "placeholder", "Add a comment… (Ctrl+Enter to send)")
        send_box = drawer.locator(".comment-send").bounding_box()
        edit_box = drawer.locator(".drawer-tools .button-ghost").first.bounding_box()
        assert send_box and edit_box and abs(send_box["height"] - edit_box["height"]) <= 1, (send_box, edit_box)
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-04-triage-10-phone.png")
        # …and every field under More fields is a whole target too, once opened
        open_more_fields(drawer)
        assert_min_target(drawer.locator(".field-control"))
        assert_no_horizontal_overflow(page)
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
        # whose kebab is a touch target clear of the open target
        # (the rows on screen: Later and No date start folded, #393)
        assert_min_target(page.locator("#paneToday .today-group .trow-kebab:visible"))
        assert_no_overlap(page.locator("#paneToday .today-group .trow-main:visible, "
                                       "#paneToday .today-group .trow-kebab:visible"))
        today_row.locator(".trow-kebab").tap()
        page.locator(".row-menu [data-action='snooze']").tap()
        menu = page.locator("dialog#dateDialog .snooze-menu.date-sheet")
        expect(menu).to_be_visible()
        assert_min_target(menu.locator(".snooze-opt"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-13-starts-snooze-6-phone.png")
        surface(page, "today.date-sheet")
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()

        # the sleeping seed task wears its marker wherever it still shows
        page.goto(f"{base}/?status=deferred")
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        board_mode(page, "status")
        page.locator("#paneBoard .board-strip-btn[data-col='todo']").tap()   # it is a todo task
        sleeping = _trow(page, "Book boiler service", "#paneBoard")
        expect(sleeping).to_be_visible()
        expect(sleeping.locator(".trow-starts")).to_have_text(re.compile(r"^\d+ \w{3}$"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-13-starts-snooze-7-phone.png")

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
        open_more_fields(drawer)
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
