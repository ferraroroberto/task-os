"""Story 10 — find anything (Step 10/13, issue #11).

    Type a word in the Search tab → results grouped in four collapsible
    groups, Tasks · Folders · Emails · Issues (task hits are the ONE shared
    row; the other hits' title is the link, then attach · new-task actions)
    → with a task open in the drawer, attach an email hit → the link appears in
    the drawer → create a task from a folder hit → it appears with the folder
    chip → Ctrl+K → type a word → Enter opens the task → `>` lists the
    commands → "Go to Board" switches the tab. On the phone the same box and
    the palette as a full-width sheet.

Walks the story against a **disposable seeded instance** whose four indexes
are all fixtures: ``{onedrive}`` → a temp tree (the folder index scans it),
``search.email_db`` → the synthetic archiver index built by
``tests/fixtures/emails_fixture.py`` under that same tree (never the real
mailbox), the issue provider → the file-backed fake (never ``gh``). 1440×900
Chromium then a 390-wide touch context, saving the proof shots the
validation record links to:

    docs/screenshots/story-10-search-1-desktop.png   "kitchen": four groups, full width
    docs/screenshots/story-10-search-2-desktop.png   drawer open + email attached (link in the drawer)
    docs/screenshots/story-10-search-3-desktop.png   task created from a folder hit (folder chip in the drawer)
    docs/screenshots/story-10-search-4-desktop.png   Ctrl+K: jump to a task
    docs/screenshots/story-10-search-5-desktop.png   Ctrl+K: > commands (dark)
    docs/screenshots/story-10-search-6-phone.png     phone: results
    docs/screenshots/story-10-search-7-phone.png     phone: the palette sheet
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
from tests.e2e.conftest import FAKE_ISSUES, _boot, _terminate

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
INTERCEPT = (
    "document.addEventListener('click', function (e) {"
    "  const a = e.target.closest && e.target.closest('a[href^=\"taskos:\"]');"
    "  if (a) { window.__taskosClicks = (window.__taskosClicks || []).concat(a.getAttribute('href')); e.preventDefault(); }"
    "}, true);"
)
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


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def _post(base: str, path: str) -> dict:
    req = urllib.request.Request(f"{base}{path}", data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


@pytest.fixture(scope="module")
def search_webapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SearchInstance]:
    """Seeded instance; every index a fixture under one temp tree."""
    from tests.fixtures.emails_fixture import build_emails_db
    from tests.fixtures.seed import seed_db

    work = tmp_path_factory.mktemp("taskos-e2e-search")
    od = work / "od"
    for rel in ("house/kitchen/plans", "house/garden", "house/bathroom", "admin/car", "admin/school", "task-os"):
        (od / rel).mkdir(parents=True)
    build_emails_db(work / "emails.db", root=od)
    seed_db(work / "tasks.db")
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
    """A result group is a collapsed disclosure (#46) — open it like a user would."""
    g = page.locator(f".search-group[data-kind='{kind}']")
    expect(g).to_be_visible()
    if not g.evaluate("el => el.open"):
        g.locator("summary").click()
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

    # 1. type a word → four groups (collapsed disclosures, the count on the
    #    summary), all populated; opened, every group shows its hits
    box.fill("kitchen")
    groups = page.locator(".search-group")
    expect(groups).to_have_count(4)
    for kind in ("tasks", "folders", "emails", "issues"):
        g = page.locator(f".search-group[data-kind='{kind}']")
        assert g.evaluate("el => el.open") is False                 # collapsed by default
        expect(g.locator(".search-group-count")).to_have_text(re.compile(r"^\d+ hits?$"))
        _open_group(page, kind)
        expect(g.locator(".search-hit").first).to_be_visible()
    expect(page.locator("#searchMeta")).to_have_text(re.compile(r"^\d+ hits$"))   # no milliseconds anywhere
    # task hits are the ONE shared row — title + status select + the meta line
    kitchen_hit = _task_hit(page, "Kitchen")
    expect(kitchen_hit.locator(".trow-title")).to_contain_text("Kitchen")
    expect(kitchen_hit.locator(".trow-status")).to_have_value("doing")
    expect(kitchen_hit.locator(".trow-meta .chip-folder")).to_contain_text("{onedrive}/house/kitchen")
    # folder / email / issue hits: the title IS the link, then Attach · New task
    folder_hit = page.locator(".search-group[data-kind='folders'] .search-hit").first
    expect(folder_hit.locator(".search-hit-sub")).to_have_text("{onedrive}/house/kitchen")
    expect(folder_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^taskos://open\?ref="))
    expect(folder_hit.locator("[data-act='new']")).to_be_visible()
    expect(page.locator(".search-group[data-kind='emails'] .search-hit-title").first).to_contain_text("Kitchen quotes from the installer")
    issue_hit = page.locator(".search-group[data-kind='issues'] .search-hit").first
    expect(issue_hit.locator(".search-hit-title")).to_contain_text("Kitchen lights automation")
    expect(issue_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", "https://github.com/example/home-dashboard/issues/7")
    expect(page.locator(".search-hit mark").first).to_be_visible()
    assert "q=kitchen" in page.url                                # ?q= keeps the query
    # every hit that can attach is disabled until a task is open in the drawer
    email_attach = page.locator(".search-group[data-kind='emails'] .search-hit").first.locator("[data-act='attach']")
    expect(email_attach).to_be_disabled()
    page.screenshot(path=str(shots / "story-10-search-1-desktop.png"), full_page=True)

    # 2. open a task (the Kitchen task) from its row → drawer; attach the email hit → link in the drawer
    kitchen_hit.locator(".trow-main").click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")
    expect(email_attach).to_be_enabled()
    email_attach.click()
    expect(page.locator(".toast")).to_contain_text("Email attached to #")
    link = drawer.locator(".drawer-links .chip", has_text="Kitchen quotes from the installer")
    expect(link).to_be_visible()
    assert link.get_attribute("href").startswith("taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse")
    kitchen = _task_by_title(base, "Kitchen")
    links = _get(base, f"/api/tasks/{kitchen['id']}")["links"]
    email_link = next(x for x in links if x["kind"] == "email" and x["label"] == "Kitchen quotes from the installer")
    assert email_link["url"] == "{onedrive}/mail/house/2026-08-10 Kitchen quotes.msg"
    page.screenshot(path=str(shots / "story-10-search-2-desktop.png"))

    # 3. create a task from a folder hit → the drawer opens on it with the folder chip
    plans = page.locator(".search-group[data-kind='folders'] .search-hit", has_text="{onedrive}/house/kitchen/plans")
    plans.locator("[data-act='new']").click()
    expect(page.locator(".toast").last).to_contain_text("created: plans")
    expect(drawer.locator("#drawerTitle")).to_have_value("plans")
    chip = drawer.locator(".drawer-folder a.chip-folder")
    expect(chip).to_have_attribute("href", "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen%2Fplans")
    created = _task_by_title(base, "plans")
    assert created["folder_ref"] == "{onedrive}/house/kitchen/plans"
    assert created["folder_resolved"] == inst.od_fwd + "/house/kitchen/plans"
    page.screenshot(path=str(shots / "story-10-search-3-desktop.png"))
    # the folder hit's title link hands the ref to the opener (intercepted here)
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
    page.screenshot(path=str(shots / "story-10-search-4-desktop.png"))
    pin.press("Enter")
    expect(palette).to_be_hidden()
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Renew passports")

    # 5. > commands → "Go to Board" (dark, for the record)
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    page.locator("#paletteBtn").click()
    expect(palette).to_be_visible()
    pin.fill(">go to")
    cmds = page.locator("#paletteList .palette-item[data-kind='command']")
    expect(cmds.first).to_contain_text("Go to Board")
    assert cmds.count() >= 6
    page.screenshot(path=str(shots / "story-10-search-5-desktop.png"))
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
    expect(p.locator(".search-group[data-kind='emails'] .search-group-count")).to_have_text(re.compile(r"^\d+ hits?$"))
    _open_group(p, "emails")
    expect(p.locator(".search-group[data-kind='emails'] .search-hit").first).to_be_visible()
    p.screenshot(path=str(shots / "story-10-search-6-phone.png"))
    p.locator("#paletteBtn").click()
    expect(p.locator("#palette")).to_be_visible()
    p.locator("#paletteInput").fill("water")
    expect(p.locator("#paletteList .palette-item[data-kind='task']").first).to_contain_text("Pay water bill")
    p.screenshot(path=str(shots / "story-10-search-7-phone.png"))
    phone.close()
