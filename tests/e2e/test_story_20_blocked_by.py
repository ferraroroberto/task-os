"""Story 20 — Blocked-by dependencies (issue #100).

    Board hides "Release v0.2" — it's blocked on "Write sensor driver" — while
    the Tree still shows it, wearing a lock and "blocked by 1" → open its
    drawer: the "Blocked by" section lists the blocker as a removable row →
    the filter card's `blocked` pseudo-filter narrows the Board to exactly the
    locked task → a fresh pair of tasks demonstrates the cycle guard: blocking
    B on A then trying to block A back on B is refused with a toast, nothing
    applied → adding and removing a real blocker updates the lock live.

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — the seed's own "Release
v0.2" ↔ "Write sensor driver" pair, added for this issue) at 1440×900
desktop, saving the proof shots the validation record links to:

    docs/screenshots/story-20-blocked-by-1-desktop.png   Board: no "Release v0.2" row
    docs/screenshots/story-20-blocked-by-2-desktop.png   Tree: locked row, lock + "blocked by 1"
    docs/screenshots/story-20-blocked-by-3-desktop.png   drawer: Blocked by section
    docs/screenshots/story-20-blocked-by-4-desktop.png   Board filtered to `blocked` — exactly one row
    docs/screenshots/story-20-blocked-by-5-desktop.png   drawer (dark): cycle rejected toast + the picker
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Browser, expect

from tests.e2e._geometry import assert_no_horizontal_overflow
from tests.e2e.conftest import _get

DESKTOP = {"width": 1440, "height": 900}


def _trow(page, title: str, scope: str = ""):
    """The ONE shared task row (rows.js) by exact title, optionally inside ``scope``."""
    return page.locator(f"{scope} .trow".strip(), has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _open_filters(page, host_id: str):
    """The shared filter card is collapsed by default — open it like a user would."""
    card = page.locator(f"#{host_id} .filter-card")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


def test_blocked_by_dependencies(seeded_webapp: str, browser: Browser, shots: Path) -> None:
    base = seeded_webapp
    release = _get(base, "/api/tasks?q=Release%20v0.2&include_closed=true")["items"][0]
    driver = _get(base, "/api/tasks?q=Write%20sensor%20driver&include_closed=true")["items"][0]
    assert release["blocked"] is True and release["blocker_count"] == 1
    assert [b["id"] for b in release["blocked_by"]] == [driver["id"]]

    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()

        # 1. Board: the blocked task is out of every column — hidden by default,
        #    exactly like a deferred (#87) one.
        page.goto(f"{base}/")
        expect(page.locator("#paneBoard")).to_be_visible()
        release_id = release["id"]
        expect(page.locator(f".trow[data-id='{release_id}']")).to_have_count(0)
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-20-blocked-by-1-desktop.png"))

        # 2. Tree: still findable — the map of everything — wearing a lock and
        #    "blocked by 1" instead of any starts marker (blocked wins, #100's
        #    explicit precedence over #87's deferred clock).
        page.click("nav.tabs .tab[data-tab='tree']")
        expect(page.locator("#paneTree")).to_be_visible()
        locked = _trow(page, "Release v0.2", "#paneTree")
        expect(locked).to_be_visible()
        expect(locked.locator(".trow-blocked")).to_have_text("blocked by 1")
        expect(locked.locator(".trow-starts")).to_have_count(0)
        page.screenshot(path=str(shots / "story-20-blocked-by-2-desktop.png"))

        # 3. Drawer: the Blocked by section lists the blocker, click-to-navigate,
        #    removable.
        locked.locator(".trow-main").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        blockers = drawer.locator(".drawer-blocked .drawer-blockers .blocker-row")
        expect(blockers).to_have_count(1)
        expect(blockers.locator(".blocker-title")).to_have_text("Write sensor driver")
        expect(blockers.locator(".pill")).to_have_text("todo")
        page.screenshot(path=str(shots / "story-20-blocked-by-3-desktop.png"))
        page.keyboard.press("Escape")
        expect(drawer).to_be_hidden()

        # 4. The filter card's `blocked` pseudo-filter (status multi-select, the
        #    same shape `deferred` uses) narrows the Board to exactly this task.
        page.click("nav.tabs .tab[data-tab='board']")
        card = _open_filters(page, "boardFilters")
        status_sel = card.locator(".msel[data-name='status']")
        status_sel.locator("summary.msel-summary").click()
        status_sel.locator("input[name='status'][value='blocked']").check()
        expect(page).to_have_url(f"{base}/?status=blocked")
        page.keyboard.press("Escape")
        rows = page.locator("#paneBoard .trow")
        expect(rows).to_have_count(1)
        expect(rows.first).to_be_visible()   # not just present — the column it's in must not be hidden
        expect(rows.locator(".trow-title")).to_have_text("Release v0.2")
        expect(rows.locator(".trow-blocked")).to_have_text("blocked by 1")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-20-blocked-by-4-desktop.png"))
        card = _open_filters(page, "boardFilters")
        card.locator(".filter-clear").click()
        expect(page).to_have_url(f"{base}/")

        # 5. Cycle guard through the real UI: two fresh tasks, B blocks A, then
        #    A blocking B back is refused with a toast — nothing applied — and
        #    a real add/remove updates the lock live. Dark, for the paired shot
        #    — through localStorage, not a DOM mutation: the steps below do full
        #    page navigations (fresh `boot()`, so the blocker picker's
        #    state.taskIndex sees the two new tasks), which wipe an in-memory
        #    `dataset.theme` flip but read the persisted key on every load.
        page.evaluate("localStorage.setItem('task-os.theme', 'dark')")
        made_a = page.request.post(f"{base}/api/tasks", data=json.dumps({"title": "Cycle A"}),
                                    headers={"content-type": "application/json"})
        made_b = page.request.post(f"{base}/api/tasks", data=json.dumps({"title": "Cycle B"}),
                                    headers={"content-type": "application/json"})
        assert made_a.ok and made_b.ok, (made_a.text(), made_b.text())
        a_id, b_id = made_a.json()["id"], made_b.json()["id"]
        # A forced full navigation (the query bust), not a hash-only goto: the
        # blocker picker reads state.taskIndex, built from the tree fetch
        # `boot()` awaits before it opens a #task/<id> deep link — a plain API
        # POST made outside the page never refreshes it on its own, and a
        # hash-only goto on an already-loaded page never re-runs boot() at all.
        page.goto(f"{base}/?_e2e=1#task/{a_id}")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(drawer).to_be_visible()
        blocked_sec = drawer.locator(".drawer-blocked")
        expect(blocked_sec.locator(".drawer-none")).to_have_text("Not blocked by anything.")
        sel_a = blocked_sec.locator(".blocker-form select")
        sel_a.select_option(label="Cycle B")
        expect(sel_a).to_have_value(str(b_id))
        blocked_sec.locator(".blocker-form button[type='submit']").click()
        expect(blocked_sec.locator(".blocker-row .blocker-title")).to_have_text("Cycle B")
        assert _get(base, f"/api/tasks/{a_id}")["blocked"] is True

        page.goto(f"{base}/?_e2e=2#task/{b_id}")
        expect(drawer).to_be_visible()
        blocked_sec = drawer.locator(".drawer-blocked")
        sel_b = blocked_sec.locator(".blocker-form select")
        sel_b.select_option(label="Cycle A")
        expect(sel_b).to_have_value(str(a_id))
        page.screenshot(path=str(shots / "story-20-blocked-by-5-desktop.png"))
        blocked_sec.locator(".blocker-form button[type='submit']").click()
        expect(page.locator(".toast-error").last).to_contain_text("cycle")
        assert _get(base, f"/api/tasks/{b_id}")["blocked"] is False
        assert _get(base, f"/api/tasks/{b_id}")["blocked_by"] == []

        # remove the real edge: Cycle A unblocks
        page.goto(f"{base}/#task/{a_id}")
        expect(drawer).to_be_visible()
        drawer.locator(".drawer-blocked .blocker-row .icon-btn").click()
        expect(drawer.locator(".drawer-blocked .drawer-none")).to_have_text("Not blocked by anything.")
        assert _get(base, f"/api/tasks/{a_id}")["blocked"] is False

        # clean up the throwaway pair — the seeded instance is session-scoped
        page.request.delete(f"{base}/api/tasks/{a_id}")
        page.request.delete(f"{base}/api/tasks/{b_id}")
    finally:
        context.close()
