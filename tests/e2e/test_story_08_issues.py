"""Story 08 — an issue becomes a task (Step 8/13, issue #9).

    ↻ sync → my open issues appear as coding tasks in To do → open one: the
    drawer's issue panel (repo#N, state, labels, last synced) → nest it under
    a project in the Tree → the issue is closed on the forge → ↻ → the task
    is done and the log says ``sync`` → "Create issue" on a plain task → it
    turns coding with the new number, chip on the Board.

Walks the story against the **issues** disposable instance (conftest
``issues_webapp``: the synthetic seed + the file-backed fake provider — the
"forge" is a JSON file this test edits; never ``gh``, never the network) at
1440×900 Chromium, saving the proof shots the validation record links to:

    docs/screenshots/story-08-issues-1-desktop.png   Board after ↻: two new coding rows in To do, toast
    docs/screenshots/story-08-issues-2-desktop.png   drawer: issue panel — chip, open, label, last synced
    docs/screenshots/story-08-issues-3-desktop.png   Tree: the issue task nested under the project
    docs/screenshots/story-08-issues-4-desktop.png   drawer after the close: done · activity by sync · closed chip
    docs/screenshots/story-08-issues-5-desktop.png   drawer: a plain task's issue panel — Create issue / Link existing
    docs/screenshots/story-08-issues-6-desktop.png   drawer: after "Create issue" — linked, code, open chip
    docs/screenshots/story-08-issues-7-desktop.png   Settings card (dark): provider enabled, last sync counts

The real-provider walk (``gh`` against the owner's account) is in
``docs/validation/story-08-issues.md`` — counts only, no titles.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import _get

DESKTOP = {"width": 1440, "height": 900}


def _dismiss_toasts(page) -> None:
    """Close the stacked toasts so a proof shot shows the panel behind them."""
    for btn in page.locator(".toast-close").all():
        try:
            btn.click(timeout=1000)
        except Exception:  # noqa: BLE001 — a toast that expired mid-loop is fine
            pass
    expect(page.locator(".toast")).to_have_count(0)


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

        # 1. Board → ↻ (header) → the two issues without a task become coding tasks in To do.
        page.goto(f"{base}/")
        expect(page.locator("#paneBoard")).to_be_visible()
        sync = page.locator("#issuesSync")
        expect(sync).to_be_visible()
        sync.click()
        expect(page.locator(".toast-success").last).to_contain_text("Issues synced: 3 open · 2 new")
        todo_col = page.locator(".board-col[data-col='todo']")
        # UX rounds 2+3 (#32/#46): a coding task's row names the issue as the
        # code on its meta line (the launcher's "repo#N" look) — no duplicate
        # issue chip on the row.
        expect(todo_col.locator(".trow .trow-code", has_text=re.compile(r"^garden-bot#14$"))).to_have_count(1)
        expect(todo_col.locator(".trow .trow-code", has_text=re.compile(r"^home-dashboard#3$"))).to_have_count(1)
        expect(todo_col.locator(".trow", has=page.locator(".trow-code", has_text="garden-bot#14")).locator(".chip-issue")).to_have_count(0)
        expect(page.locator(".board-col-count[data-col='todo']")).to_have_text(str(todo_before + 2))
        api_todo = _get(base, "/api/tasks?status=todo")["items"]
        new = {t["code"]: t for t in api_todo if t.get("issue_ref")}
        assert set(new) == {"garden-bot#14", "home-dashboard#3"}
        sensor = new["garden-bot#14"]
        assert sensor["type"] == "coding" and sensor["title"] == "Add soil-moisture sensor to the loop"
        assert sensor["issue_ref"]["state"] == "open" and sensor["created_by"] == "sync"
        # the seeded coding task (garden-bot#12) was matched, not duplicated
        assert _get(base, "/api/tasks?type=coding&include_closed=true")["count"] == 3
        page.screenshot(path=str(shots / "story-08-issues-1-desktop.png"))

        # 2. Open the new task → the drawer's issue panel.
        card = todo_col.locator(f".trow[data-id='{sensor['id']}'] .trow-main")
        card.click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(drawer.locator(".drawer-code")).to_have_text("garden-bot#14")
        panel = drawer.locator(".drawer-issue")
        expect(panel.locator(".chip-issue")).to_have_text("garden-bot#14")
        expect(panel.locator(".chip-issue")).to_have_attribute("href", "https://github.com/example/garden-bot/issues/14")
        expect(panel.locator(".issue-state")).to_have_text("open")
        expect(panel.locator(".issue-labels .chip-label-tag")).to_have_text(["enhancement"])
        expect(panel.locator(".issue-meta")).to_contain_text("github · last synced")
        expect(panel.locator(".issue-unlink")).to_be_visible()
        expect(drawer.locator(".drawer-desc")).to_contain_text("Read the capacitive sensor")
        _dismiss_toasts(page)
        drawer.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.screenshot(path=str(shots / "story-08-issues-2-desktop.png"))
        page.keyboard.press("Escape")
        expect(drawer).to_be_hidden()

        # 3. Tree: nest it under the garden-bot project (drag), the chip travels with it.
        page.click("nav.tabs .tab[data-tab='tree']")
        expect(page.locator("#paneTree")).to_be_visible()
        bot = page.locator(".tree-node", has=page.locator(":scope > .tree-row .trow-title", has_text="Side project: garden-bot")).first
        bot_id = int(bot.get_attribute("data-id"))
        for pid in page.locator(".tree-node[aria-level='1'][aria-expanded='true']").evaluate_all("els => els.map(e => e.dataset.id)"):
            page.locator(f".tree-node[data-id='{pid}'] > .tree-row > .tree-toggle").click()
        source = page.locator(f".tree-node[data-id='{sensor['id']}']")
        expect(source).to_be_visible()
        expect(source.locator(":scope > .tree-row .trow-code")).to_have_text("garden-bot#14")
        source.locator(":scope > .tree-row").drag_to(bot.locator(":scope > .tree-row"))
        expect(page.locator(".toast-success").last).to_contain_text("under Side project: garden-bot")
        moved = _get(base, f"/api/tasks/{sensor['id']}")
        assert moved["parent_id"] == bot_id and moved["activity"][0]["field"] == "parent"
        bot = page.locator(f".tree-node[data-id='{bot_id}']")
        bot.locator(":scope > .tree-row > .tree-toggle").click()
        nested = bot.locator(f".tree-children .tree-node[data-id='{sensor['id']}']")
        expect(nested).to_be_visible()
        expect(nested.locator(":scope > .tree-row .trow-code")).to_have_text("garden-bot#14")
        page.screenshot(path=str(shots / "story-08-issues-3-desktop.png"))

        # 4. The issue is closed on the forge → ↻ → the task is done, the log says sync.
        inst.set_issue("example/garden-bot", 14, state="closed")
        sync.click()
        expect(page.locator(".toast-success").last).to_contain_text("1 closed")
        done = _get(base, f"/api/tasks/{sensor['id']}")
        assert done["status"] == "done" and done["done_at"] and done["issue_ref"]["state"] == "closed"
        acts = [(a["field"], a["old_value"], a["new_value"], a["actor"]) for a in done["activity"][:2]]
        assert ("status", "todo", "done", "sync") in acts and ("issue_state", "open", "closed", "sync") in acts
        page.goto(f"{base}/#task/{sensor['id']}")
        expect(drawer).to_be_visible()
        expect(drawer.locator(".drawer-fields select[data-field='status']")).to_have_value("done")
        expect(panel.locator(".issue-state")).to_have_text("closed")
        expect(panel.locator(".chip-issue-closed")).to_be_visible()
        row = drawer.locator(".activity-row[data-field='status']").first
        expect(row.locator(".activity-new")).to_have_text("done")
        expect(row.locator(".activity-meta")).to_contain_text("sync ·")
        expect(drawer.locator(".activity-row[data-field='issue_state']").first.locator(".activity-meta")).to_contain_text("sync ·")
        _dismiss_toasts(page)
        drawer.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.screenshot(path=str(shots / "story-08-issues-4-desktop.png"))
        # …and the seeded coding task, still open on the forge, was left alone
        assert _get(base, "/api/tasks?q=watering&include_closed=true")["items"][0]["status"] == "doing"

        # 5. "Create issue" on a plain task → it turns coding with the new number.
        plain = _get(base, "/api/tasks?q=standing%20desk")["items"][0]
        assert plain["type"] == "task" and plain["issue_ref"] is None
        page.goto(f"{base}/#task/{plain['id']}")
        expect(drawer).to_be_visible()
        expect(panel.locator(".issue-create")).to_be_visible()
        expect(panel.locator(".issue-link")).to_be_visible()
        repo_input = panel.locator(".issue-create input")
        _dismiss_toasts(page)
        drawer.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.screenshot(path=str(shots / "story-08-issues-5-desktop.png"))
        repo_input.fill("example/garden-bot")
        panel.locator(".issue-create button[type='submit']").click()
        expect(page.locator(".toast-success").last).to_contain_text("Created example/garden-bot#15")
        expect(panel.locator(".chip-issue")).to_have_text("garden-bot#15")
        expect(panel.locator(".issue-state")).to_have_text("open")
        expect(drawer.locator(".drawer-code")).to_have_text("garden-bot#15")
        linked = _get(base, f"/api/tasks/{plain['id']}")
        assert linked["type"] == "coding" and linked["issue_ref"]["number"] == 15
        assert [link["kind"] for link in linked["links"]] == ["issue"]
        forge = inst.issues()
        assert forge[-1]["title"] == plain["title"] and forge[-1]["number"] == 15 and forge[-1]["state"] == "open"
        _dismiss_toasts(page)
        drawer.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.screenshot(path=str(shots / "story-08-issues-6-desktop.png"))
        # the code is on the Board row's meta line too (#32/#46) — linking an
        # existing task to an issue doesn't change its status, so it's still
        # wherever it was seeded (inbox), not the sync-default todo column.
        page.keyboard.press("Escape")
        page.click("nav.tabs .tab[data-tab='board']")
        inbox_col = page.locator(".board-col[data-col='inbox']")
        expect(inbox_col.locator(f".trow[data-id='{plain['id']}'] .trow-code")).to_have_text("garden-bot#15")

        # 6. Settings (dark): provider enabled, the last sync's counts.
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.click("nav.tabs .tab[data-tab='settings']")
        card = page.locator("#issuesCard")
        # every Settings card is a collapsed disclosure (#46): the summary
        # carries the state word, the body opens on demand
        expect(card.locator("#issuesCardMeta")).to_have_text("synced")
        assert card.evaluate("el => el.open") is False
        card.locator("summary.collapse-summary").click()
        expect(card).to_have_attribute("open", "")
        expect(card.locator("#statusIssues .status-ok")).to_have_text("enabled")
        expect(card.locator("#statusIssues")).to_contain_text("github")
        expect(card.locator("#statusIssuesSync")).to_contain_text("2 open issue(s) · 0 new · 0 retitled · 0 reopened · 1 closed")
        expect(card.locator("#statusIssuesSync")).to_contain_text("example/garden-bot")
        expect(card.locator("#issuesSyncNow")).to_be_enabled()
        page.screenshot(path=str(shots / "story-08-issues-7-desktop.png"))
        assert errors == []
    finally:
        context.close()
