"""Story 08 — an issue becomes a task (Step 8/13, issue #9).

    Settings → Sync now → my open issues appear as coding tasks in To do → open one: the
    drawer's issue panel (repo#N, state, labels, last synced) → file it under
    a project with the drawer's Move to → the issue is closed on the forge → Sync now → the task
    is done and the log says ``sync`` → "Create issue" on a plain task → it
    turns coding with the new number, chip on the Board.

Walks the story against the **issues** disposable instance (conftest
``issues_webapp``: the synthetic seed + the file-backed fake provider — the
"forge" is a JSON file this test edits; never ``gh``, never the network) at
1440×900 Chromium, saving the proof shots the validation record links to:

    docs/screenshots/story-08-issues-1-desktop.png   Board after Sync now: two new coding rows in To do, toast
    docs/screenshots/story-08-issues-2-desktop.png   drawer: issue panel — chip, open, label, last synced
    docs/screenshots/story-08-issues-3-desktop.png   drawer + Board row: the issue task under the project
    docs/screenshots/story-08-issues-4-desktop.png   drawer after the close: done · activity by sync · closed chip
    docs/screenshots/story-08-issues-5-desktop.png   drawer: a plain task's issue panel — Create issue / Link existing
    docs/screenshots/story-08-issues-6-desktop.png   drawer: after "Create issue" — linked, code, open chip
    docs/screenshots/story-08-issues-7-desktop.png   Settings sheet (dark): provider enabled, last sync counts

The real-provider walk (``gh`` against the owner's account) is in
``docs/validation/story-08-issues.md`` — counts only, no titles.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import (
    _get,
    board_mode,
    close_settings_sheet,
    dismiss_toasts,
    open_more_fields,
    open_settings_sheet,
    scroll_to_bottom,
    shot,
)

DESKTOP = {"width": 1440, "height": 900}



def _sync_now(page: Page) -> None:
    """Settings → Issues as tasks → *Sync now* (the app's one sync control since #301).

    The sheet is opened for the press and closed again with Done (#397), so the
    step that reads the row's word (6) finds the Settings list as a user would.
    """
    card = open_settings_sheet(page, "issues")
    sync = card.locator("#issuesSyncNow")
    expect(sync).to_be_enabled()
    sync.click()
    close_settings_sheet(page)

def test_an_issue_becomes_a_task(issues_webapp, browser: Browser, shots: Path) -> None:
    inst = issues_webapp
    base = inst.base
    st = _get(base, "/api/issues/status")
    assert st["enabled"] is True and st["provider"] == "github"
    todo_before = _get(base, "/api/tasks?status=todo")["count"]

    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. Settings → Sync now (the header carries no sync button since #301) →
        #    back on the Board, the two issues without a task are coding tasks in To do.
        page.goto(f"{base}/")
        expect(page.locator("#paneToday")).to_be_visible()   # the landing tab (#319)
        expect(page.locator(".home-head #issuesSync")).to_have_count(0)
        _sync_now(page)
        expect(page.locator(".toast-success").last).to_contain_text("Issues synced: 3 open · 2 new")
        page.click("nav.tabs .tab[data-tab='board']")
        expect(page.locator("#paneBoard")).to_be_visible()
        # the status columns, every task in them: a synced issue's task is
        # behind the scope switch's Issues / All (#391, the Board's since #396)
        board_mode(page, "status")
        page.locator("#boardScope .segmented-item[data-scope='all']").click()
        todo_col = page.locator("#paneBoard .board-status .board-col[data-col='todo']")
        # UX rounds 2+3 (#32/#46): a coding task's row names the issue as the
        # code on its meta line (the launcher's "repo#N" look) — no duplicate
        # issue chip on the row.
        expect(todo_col.locator(".trow .trow-code", has_text=re.compile(r"^garden-bot#14$"))).to_have_count(1)
        expect(todo_col.locator(".trow .trow-code", has_text=re.compile(r"^home-dashboard#3$"))).to_have_count(1)
        expect(todo_col.locator(".trow", has=page.locator(".trow-code", has_text="garden-bot#14")).locator(".chip-issue")).to_have_count(0)
        expect(todo_col.locator(".board-col-count")).to_have_text(str(todo_before + 2))
        api_todo = _get(base, "/api/tasks?status=todo")["items"]
        new = {t["code"]: t for t in api_todo if t.get("issue_ref") and t["code"] in {"garden-bot#14", "home-dashboard#3"}}
        assert set(new) == {"garden-bot#14", "home-dashboard#3"}
        sensor = new["garden-bot#14"]
        assert sensor["type"] == "coding" and sensor["title"] == "Add soil-moisture sensor to the loop"
        assert sensor["issue_ref"]["state"] == "open" and sensor["created_by"] == "sync"
        # the seeded coding task (garden-bot#12) was matched, not duplicated
        assert _get(base, "/api/tasks?type=coding&include_closed=true")["count"] == 3
        shot(page, shots / "story-08-issues-1-desktop.png")

        # 2. Open the new task → the drawer's issue panel.
        card = todo_col.locator(f".trow[data-id='{sensor['id']}'] .trow-main")
        card.click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(drawer.locator(".drawer-code")).to_have_text("garden-bot#14")
        # the issue is one of the drawer's link pills (#394); its panel, with
        # Unlink and the sync, is under More fields
        expect(drawer.locator(".drawer-pill-row .chip-issue")).to_have_text("garden-bot#14")
        open_more_fields(drawer)
        panel = drawer.locator(".drawer-issue")
        expect(panel.locator(".chip-issue")).to_have_text("garden-bot#14")
        expect(panel.locator(".chip-issue")).to_have_attribute("href", "https://github.com/example/garden-bot/issues/14")
        expect(panel.locator(".issue-state")).to_have_text("open")
        expect(panel.locator(".issue-labels .chip-label-tag")).to_have_text(["enhancement"])
        expect(panel.locator(".issue-meta")).to_contain_text("github · last synced")
        expect(panel.locator(".issue-unlink")).to_be_visible()
        expect(drawer.locator(".drawer-desc")).to_contain_text("Read the capacitive sensor")
        dismiss_toasts(page)
        scroll_to_bottom(page, drawer)
        shot(page, shots / "story-08-issues-2-desktop.png")
        page.keyboard.press("Escape")
        expect(drawer).to_be_hidden()

        # 3. File it under the garden-bot project with the drawer's Move to
        #    (#350: the one re-parent path since the Tree went); the code
        #    travels with it, and the Board row names its new project.
        bot_id = next(p["id"] for p in _get(base, "/api/projects")["items"] if p["title"] == "Side project: garden-bot")
        row = page.locator(f"#paneBoard .trow[data-id='{sensor['id']}']")
        row.locator(".trow-main").click()
        expect(drawer).to_be_visible()
        drawer.locator("select[data-field='parent']").select_option(str(bot_id))
        expect(page.locator(".toast-success").last).to_contain_text("under Side project: garden-bot")
        moved = _get(base, f"/api/tasks/{sensor['id']}")
        assert moved["parent_id"] == bot_id and moved["activity"][0]["field"] == "parent"
        expect(drawer.locator(".drawer-crumbs .crumb")).to_have_text(["Side project: garden-bot"])
        expect(drawer.locator(".drawer-code")).to_have_text("garden-bot#14")
        expect(row.locator(".trow-project")).to_have_text("Side project: garden-bot")
        # one context name per row (#392): the project now, the code is the drawer's
        expect(row.locator(".trow-code")).to_have_count(0)
        dismiss_toasts(page)
        shot(page, shots / "story-08-issues-3-desktop.png")
        page.keyboard.press("Escape")
        expect(drawer).to_be_hidden()

        # 4. The issue is closed on the forge → Sync now → the task is done, the log says sync.
        inst.set_issue("example/garden-bot", 14, state="closed")
        _sync_now(page)
        expect(page.locator(".toast-success").last).to_contain_text("1 closed")
        done = _get(base, f"/api/tasks/{sensor['id']}")
        assert done["status"] == "done" and done["done_at"] and done["issue_ref"]["state"] == "closed"
        acts = [(a["field"], a["old_value"], a["new_value"], a["actor"]) for a in done["activity"][:2]]
        assert ("status", "todo", "done", "sync") in acts and ("issue_state", "open", "closed", "sync") in acts
        page.goto(f"{base}/#task/{sensor['id']}")
        expect(drawer).to_be_visible()
        open_more_fields(drawer)
        expect(drawer.locator(".drawer-fields select[data-field='status']")).to_have_value("done")
        expect(panel.locator(".issue-state")).to_have_text("closed")
        expect(panel.locator(".chip-issue-closed")).to_be_visible()
        # the sync's rows fold behind one toggle (#394, decision 7): the
        # owner's own change (the Move to above) leads the log
        expect(drawer.locator(".activity-row").first).to_have_attribute("data-field", "parent")
        expect(drawer.locator(".activity-row[data-field='status']")).to_have_count(0)
        sync_toggle = drawer.locator(".activity-sync-toggle")
        expect(sync_toggle).to_have_text(re.compile(r"^Show \d+ sync updates$"))
        sync_toggle.click()
        expect(sync_toggle).to_have_text("Hide sync updates")
        row = drawer.locator(".activity-row[data-field='status']").first
        expect(row.locator(".activity-new")).to_have_text("done")
        expect(row.locator(".activity-meta")).to_contain_text("sync ·")
        expect(drawer.locator(".activity-row[data-field='issue_state']").first.locator(".activity-meta")).to_contain_text("sync ·")
        dismiss_toasts(page)
        scroll_to_bottom(page, drawer)
        shot(page, shots / "story-08-issues-4-desktop.png")
        # …and the seeded coding task, still open on the forge, was left alone
        assert _get(base, "/api/tasks?q=watering&include_closed=true")["items"][0]["status"] == "todo"

        # 5. "Create issue" on a plain task → it turns coding with the new number.
        plain = _get(base, "/api/tasks?q=standing%20desk")["items"][0]
        assert plain["type"] == "task" and plain["issue_ref"] is None
        page.goto(f"{base}/#task/{plain['id']}")
        expect(drawer).to_be_visible()
        open_more_fields(drawer)
        expect(panel.locator(".issue-create")).to_be_visible()
        expect(panel.locator(".issue-link")).to_be_visible()
        repo_input = panel.locator(".issue-create input")
        dismiss_toasts(page)
        scroll_to_bottom(page, drawer)
        shot(page, shots / "story-08-issues-5-desktop.png")
        repo_input.fill("example/garden-bot")
        panel.locator(".issue-create button").click()
        expect(page.locator(".toast-success").last).to_contain_text("Created example/garden-bot#15")
        expect(panel.locator(".chip-issue")).to_have_text("garden-bot#15")
        expect(panel.locator(".issue-state")).to_have_text("open")
        expect(drawer.locator(".drawer-code")).to_have_text("garden-bot#15")
        linked = _get(base, f"/api/tasks/{plain['id']}")
        assert linked["type"] == "coding" and linked["issue_ref"]["number"] == 15
        assert [link["kind"] for link in linked["links"]] == ["issue"]
        forge = inst.issues()
        assert forge[-1]["title"] == plain["title"] and forge[-1]["number"] == 15 and forge[-1]["state"] == "open"
        dismiss_toasts(page)
        scroll_to_bottom(page, drawer)
        shot(page, shots / "story-08-issues-6-desktop.png")
        # the code is on the Board row's meta line too (#32/#46) — linking an
        # existing task to an issue doesn't change its status, so it's still
        # wherever it was seeded (inbox), not the sync-default todo column.
        page.keyboard.press("Escape")
        page.click("nav.tabs .tab[data-tab='board']")
        page.locator("#boardScope .segmented-item[data-scope='all']").click()   # it is an issue's task now
        inbox_col = page.locator("#paneBoard .board-status .board-col[data-col='inbox']")
        expect(inbox_col.locator(f".trow[data-id='{plain['id']}'] .trow-code")).to_have_text("garden-bot#15")

        # 6. Settings (dark): provider enabled, the last sync's counts.
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.click("#settingsBtn")
        # every Settings row carries its state word (#397): the row says it, the
        # sheet behind its chevron has the detail
        expect(page.locator("#issuesCardMeta")).to_have_text("synced")
        expect(page.locator("#settingsSheet")).to_be_hidden()
        card = open_settings_sheet(page, "issues")
        expect(card.locator("#statusIssues .status-ok")).to_have_text("enabled")
        expect(card.locator("#statusIssues")).to_contain_text("github")
        expect(card.locator("#statusIssuesSync")).to_contain_text("2 open issue(s) · 0 new · 0 retitled · 0 reopened · 1 closed")
        expect(card.locator("#statusIssuesSync")).to_contain_text("example/garden-bot")
        expect(card.locator("#issuesSyncNow")).to_be_enabled()
        shot(page, shots / "story-08-issues-7-desktop.png")
        assert errors == []
    finally:
        context.close()
