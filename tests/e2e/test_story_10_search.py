"""Story 10 — find anything (Step 10/13, issue #11).

    The Search tab opens on one box and a hint, no group waiting empty
    (#395) → a word that matches nothing folds every kind into one line →
    type a word → one open group per kind with hits, Tasks · Folders · Emails
    · Issues (task hits are the ONE shared row, narrowed by the scope switch
    and the filter sheet; folder / email / issue hits are the same row shape,
    the title IS the link, no buttons — #48) → open a task from its row → the drawer
    beside the results → a folder hit's title hands its ref to the opener →
    ↓ ↓ Enter walks the rows → Ctrl+K → type a word → Enter opens the task →
    `>` lists the commands, Today first as in the nav → "Go to Board" switches the tab. On the phone the
    same box and the palette as a full-width sheet.

Walks the story against a **disposable seeded instance** whose four indexes
are all fixtures: ``{onedrive}`` → a temp tree (the folder index scans it),
``search.email_db`` → the synthetic archiver index built by
``tests/fixtures/emails_fixture.py`` under that same tree (never the real
mailbox), the issue provider → the file-backed fake (never ``gh``). 1440×900
Chromium then a 390-wide touch context, saving the proof shots the
validation record links to:

    docs/screenshots/story-10-search-1-desktop.png   "kitchen": four open groups, in the centred 772px measure
    docs/screenshots/story-10-search-2-desktop.png   drawer open beside the results
    docs/screenshots/story-10-search-4-desktop.png   Ctrl+K: jump to a task
    docs/screenshots/story-10-search-5-desktop.png   Ctrl+K: > commands (dark)
    docs/screenshots/story-10-search-6-phone.png     phone: results
    docs/screenshots/story-10-search-7-phone.png     phone: the palette sheet

A shot number is the step it belongs to, so the set skips 3: that step used
to be "New task on a folder hit", which #48 removed along with the per-hit
buttons. Step 3 is still walked (the opener hand-off and the ↓ ↓ Enter
keyboard leg) — it just has nothing left worth a picture.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e.conftest import (
    E2E_ANCHOR,
    FAKE_ISSUES,
    INTERCEPT,
    _boot,
    _get,
    _post,
    _terminate,
    assert_control_boundaries,
    close_filter_sheet,
    e2e_workdir,
    open_filter_sheet,
    shot,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
KITCHEN_ISSUE = {
    "repo": "example/home-dashboard", "number": 7, "title": "Kitchen lights automation", "state": "open",
    "url": "https://github.com/example/home-dashboard/issues/7", "labels": ["enhancement", "kitchen"],
    "updated_at": "2026-08-16T12:00:00Z", "body": "Turn the kitchen lights on with the motion sensor.",
}


class SearchInstance:
    def __init__(self, base: str, od: Path, db: Path) -> None:
        self.base = base
        self.od = od
        self.od_fwd = od.as_posix()
        self.db = db


@pytest.fixture(scope="module")
def search_webapp() -> Iterator[SearchInstance]:
    """Seeded instance; every index a fixture under one temp tree."""
    from tests.fixtures.emails_fixture import build_emails_db
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("search")
    od = work / "od"
    for rel in ("house/kitchen/plans", "house/garden", "house/bathroom", "admin/car", "admin/school", "task-os"):
        (od / rel).mkdir(parents=True)
    build_emails_db(work / "emails.db", root=od)
    seed_db(work / "tasks.db", E2E_ANCHOR)
    cfg = write_test_config(
        work / "config.json",
        folder_roots=["{onedrive}"],
        placeholders={"onedrive": od.as_posix(), "user": "sam"},
        email_db=str(work / "emails.db"),
    )
    forge = work / "forge.json"
    forge.write_text(json.dumps({"issues": [*FAKE_ISSUES, KITCHEN_ISSUE], "error": None}, indent=1), encoding="utf-8")
    proc, base, log = _boot(work, work / "tasks.db", cfg,
                            extra_env={"TASKOS_ISSUE_PROVIDER": "fake", "TASKOS_ISSUE_FAKE_PATH": str(forge)})
    try:
        _post(base, "/api/folders/reindex")            # deterministic: don't race the startup thread
        _post(base, "/api/issues/sync")                # warm the issue cache (and make the fake's tasks)
        yield SearchInstance(base, od, work / "tasks.db")
    finally:
        _terminate(proc)
        log.close()


def _task_by_title(base: str, title: str) -> dict:
    items = _get(base, "/api/tasks?q=" + urllib.request.quote(title) + "&include_closed=true")["items"]
    return next(t for t in items if t["title"] == title)


def _open_group(page: Page, kind: str):
    """A result group: there only when its kind has hits, and open (#395)."""
    g = page.locator(f".search-group[data-kind='{kind}']")
    expect(g).to_be_visible()
    expect(g).to_have_attribute("open", "")
    return g


def _task_hit(page: Page, title: str):
    """A task hit = the ONE shared row (rows.js) by exact title."""
    return page.locator(".search-group[data-kind='tasks'] .search-hit.trow",
                        has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def test_find_anything(search_webapp: SearchInstance, browser: Browser, shots: Path) -> None:
    inst = search_webapp
    base = inst.base
    st = _get(base, "/api/search/status")["adapters"]
    assert all(a["configured"] for a in st), st                    # the four indexes are all wired

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(INTERCEPT)
    page: Page = ctx.new_page()
    page.goto(base + "/")
    page.get_by_role("tab", name="Search").click()
    box = page.locator("#searchInput")
    expect(box).to_be_focused()
    assert_control_boundaries(page.locator("#searchBox"))      # the card is the field's edge (#339)
    # before a query: one box and a hint — no group shells waiting empty, and
    # with every index set up, nothing to fold (J-09, #395)
    expect(page.locator(".search-hint")).to_have_text(re.compile(r"^Searches your tasks, folders, emails and issues"))
    expect(page.locator(".search-group")).to_have_count(0)
    expect(page.locator(".search-fold")).to_have_count(0)
    # a word that matches nothing: no group at all, every kind named on the one
    # folded line instead of four cards each saying "nothing"
    box.fill("zzqxnothing")
    expect(page.locator("#searchMeta")).to_have_text("0 hits")
    expect(page.locator(".search-group")).to_have_count(0)
    expect(page.locator(".search-fold")).to_have_text("No matches in tasks, folders, emails and issues")
    # the box carries the filter button (the sheet narrows the task hits), the
    # scope switch is the line under it; the sheet leads with the sort and
    # holds every filter (#395)
    sheet = open_filter_sheet(page, "paneSearch")
    names = sheet.locator(".filter-sheet-row").evaluate_all("els => els.map(e => e.dataset.name)")
    assert names == ["sort", "status", "project", "person", "due", "updated"], names
    close_filter_sheet(page)
    expect(page.locator("#searchScope .segmented-item[aria-pressed='true']")).to_have_text("Mine")

    # 1. type a word → four groups, open, each headed by its kind and count,
    #    all populated. Mine is the default scope: the synced issue's task is
    #    cut from the task hits (the Issues group still lists it), which the
    #    count says as "N of M"
    box.fill("kitchen")
    groups = page.locator(".search-group")
    expect(groups).to_have_count(4)
    for kind in ("tasks", "folders", "emails", "issues"):
        g = _open_group(page, kind)
        expect(g.locator(".search-group-count")).to_have_text(re.compile(r"^\d+( of \d+)?$"))
        expect(g.locator(".search-group-count")).to_have_attribute("aria-label", re.compile(r"^\d+ hits?$"))
        expect(g.locator(".search-hit").first).to_be_visible()
    expect(page.locator("#searchMeta")).to_have_text(re.compile(r"^\d+ hits$"))   # no milliseconds anywhere
    expect(page.locator(".search-fold")).to_have_count(0)            # every kind has hits
    issue_task = _task_hit(page, "Kitchen lights automation")
    expect(issue_task).to_have_count(0)
    expect(page.locator(".search-group[data-kind='tasks'] .search-group-count")).to_have_text(re.compile(r"^\d+ of \d+$"))
    # All brings it back into the task hits; the switch is the shared URL key
    page.locator("#searchScope .segmented-item[data-scope='all']").click()
    expect(issue_task).to_be_visible()
    expect(page.locator(".search-group[data-kind='tasks'] .search-group-count")).to_have_text(re.compile(r"^\d+$"))
    page.locator("#searchScope .segmented-item[data-scope='mine']").click()
    expect(issue_task).to_have_count(0)
    # task hits are the ONE shared row — done circle + title + the passive meta
    # line (no status word for "todo"; the folder is the row menu's, not a glyph —
    # #392) + the Move verb + the kebab
    kitchen_hit = _task_hit(page, "Kitchen")
    expect(kitchen_hit.locator(".trow-title")).to_contain_text("Kitchen")
    expect(kitchen_hit).to_have_attribute("data-status", "todo")
    expect(kitchen_hit.locator(".trow-done")).to_have_attribute("aria-pressed", "false")
    expect(kitchen_hit.locator(".trow-meta .trow-folder")).to_have_count(0)   # #392: the menu opens it
    expect(kitchen_hit.locator(".trow-kebab")).to_be_visible()
    # folder / email / issue hits are the same row shape (#48): a title line and
    # one muted meta line (inside .trow-main), no glyphs, no buttons — the title
    # IS the link, and no done circle or kebab (only task rows carry them)
    folder_hit = page.locator(".search-group[data-kind='folders'] .search-hit").first
    expect(folder_hit).to_have_class(re.compile(r"\btrow\b"))
    expect(folder_hit.locator(".trow-meta .search-hit-meta").first).to_contain_text("/house/kitchen")
    expect(folder_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^taskos://open\?ref="))
    expect(folder_hit.locator("[data-act='new'], [data-act='attach'], .search-hit-icon, .search-hit-actions, .trow-done, .trow-kebab")).to_have_count(0)
    email_hit = page.locator(".search-group[data-kind='emails'] .search-hit").first
    expect(email_hit.locator(".trow-title")).to_contain_text("Kitchen quotes from the installer")
    expect(email_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^taskos://open\?ref="))
    expect(email_hit.locator("[data-act='attach'], .search-hit-actions")).to_have_count(0)
    issue_hit = page.locator(".search-group[data-kind='issues'] .search-hit").first
    expect(issue_hit.locator(".trow-title")).to_contain_text("Kitchen lights automation")
    # this issue is already on the list: its title opens the linked task (the
    # issue chip inside the task is the forge link); the meta names repo#N + task
    expect(issue_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^#task/\d+$"))
    expect(issue_hit.locator(".trow-meta")).to_contain_text("example/home-dashboard#7")
    expect(issue_hit.locator(".trow-meta")).to_contain_text("task #")
    expect(page.locator(".search-hit mark").first).to_be_visible()
    assert "q=kitchen" in page.url                                # ?q= keeps the query
    shot(page, shots / "story-10-search-1-desktop.png", full_page=True)

    # 2. open a task (the Kitchen task) from its row → the drawer beside the results
    kitchen_hit.locator(".trow-main").click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")
    shot(page, shots / "story-10-search-2-desktop.png")

    # 3. the folder hit's title link hands the ref to the opener (intercepted here)
    page.locator(".search-group[data-kind='folders'] .search-hit").first.locator("a.search-hit-link[data-act='open']").click()
    assert page.evaluate("window.__taskosClicks")[-1] == "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"
    pop = page.locator("#folderPop")                                # the one-time "install the opener" hint (Step 9)
    expect(pop).to_be_visible()
    page.keyboard.press("Escape")
    expect(pop).to_be_hidden()
    # keyboard: ↓ from the box focuses the first row (its title button), ↓
    # again the second task row, Enter opens that row's task
    box.click()
    box.press("ArrowDown")
    expect(page.locator(".search-hit").first.locator(".trow-main")).to_be_focused()
    page.keyboard.press("ArrowDown")
    second = page.locator(".search-group[data-kind='tasks'] .search-hit").nth(1)
    expect(second.locator(".trow-main")).to_be_focused()
    second_title = _get(base, f"/api/tasks/{second.get_attribute('data-id')}")["title"]
    page.keyboard.press("Enter")
    expect(drawer.locator("#drawerTitle")).to_have_value(second_title)

    # 4. Ctrl+K → type → Enter opens the task
    page.keyboard.press("Escape")                                   # close the drawer
    expect(drawer).to_be_hidden()
    page.get_by_role("tab", name="Today").click()
    page.keyboard.press("Control+k")
    palette = page.locator("#palette")
    expect(palette).to_be_visible()
    pin = page.locator("#paletteInput")
    expect(pin).to_be_focused()
    pin.fill("passports")
    item = page.locator("#paletteList .palette-item[data-kind='task']").first
    expect(item).to_contain_text("Renew passports")
    shot(page, shots / "story-10-search-4-desktop.png")
    pin.press("Enter")
    expect(palette).to_be_hidden()
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Renew passports")

    # 5. > commands → "Go to Board" (dark, for the record)
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    page.keyboard.press("Control+K")
    expect(palette).to_be_visible()
    pin.fill(">go to")
    cmds = page.locator("#paletteList .palette-item[data-kind='command']")
    expect(cmds.first).to_contain_text("Go to Today")   # nav order: Today leads (#319)
    # one per nav destination plus Settings — the four tabs since #350
    expect(cmds).to_have_text([re.compile(rf"^Go to {name}") for name in ("Today", "Board", "Archive", "Search", "Settings")])
    shot(page, shots / "story-10-search-5-desktop.png")
    pin.fill(">go to board")
    expect(cmds.first).to_contain_text("Go to Board")
    pin.press("Enter")
    expect(palette).to_be_hidden()
    expect(page.locator("#paneBoard")).to_be_visible()
    expect(page.locator("nav.tabs")).to_have_attribute("data-active-tab", "board")
    # a "not configured" state renders as a visible row, never a blank: ask for a kind that is off
    # (the disposable instance has all four on — prove it through the API contract instead)
    off = _get(base, "/api/search?q=kitchen&kinds=tasks")
    assert next(g for g in off["groups"] if g["kind"] == "emails")["skipped"] is True
    ctx.close()

    # 6-7. phone: results as a one-column list, the palette as a full-width sheet
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    phone.add_init_script(INTERCEPT)
    p = phone.new_page()
    p.goto(base + "/?q=kitchen#search")
    expect(p.locator("#paneSearch")).to_be_visible()
    expect(p.locator("#searchInput")).to_have_value("kitchen")
    expect(p.locator(".search-group")).to_have_count(4)
    expect(p.locator(".search-group[data-kind='emails'] .search-group-count")).to_have_attribute("aria-label", re.compile(r"^\d+ hits?$"))
    _open_group(p, "emails")
    expect(p.locator(".search-group[data-kind='emails'] .search-hit").first).to_be_visible()
    shot(p, shots / "story-10-search-6-phone.png")
    p.keyboard.press("Control+K")
    expect(p.locator("#palette")).to_be_visible()
    p.locator("#paletteInput").fill("water")
    expect(p.locator("#paletteList .palette-item[data-kind='task']").first).to_contain_text("Pay water bill")
    shot(p, shots / "story-10-search-7-phone.png")
    phone.close()
