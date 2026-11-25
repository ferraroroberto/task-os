"""Story 07's History leg: my own changes on the phone, light and dark.

On the seeded instance the walk makes its own changes through the API, as the
loopback owner, so what History lists is exactly what this leg wrote: two
tasks created, one re-dated, re-prioritised and commented on, the other closed.
Newest first that reads as four rows (only *consecutive* changes to one task
fold together), the second of them the run of two that expands. The instance's
clock is pinned, so every change shares one second: inside it the activity rows
keep their write order and a comment, from the other table, follows them. The seed's
own activity is written by other names, so it never shows. The tasks are deleted
at the end, and their activity goes with them.

    docs/screenshots/story-07-phone-19-phone.png   History, a run of two expanded (light)
    docs/screenshots/story-07-phone-20-phone.png   History filtered to Date moved (dark)
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import APIRequestContext, Browser, BrowserContext, Page, expect

from tests.e2e._geometry import assert_min_target, assert_no_horizontal_overflow
from tests.e2e._surface import surface
from tests.e2e.conftest import E2E_ANCHOR, dismiss_toasts, shot

KIND_KEY = "task-os.history.kind"


def _make_changes(api: APIRequestContext, base: str) -> tuple[dict, dict]:
    """Two tasks of this leg's own, and four changes to them, newest last."""
    boiler = api.post(f"{base}/api/tasks", data={"title": "Book the boiler service"}).json()
    lamp = api.post(f"{base}/api/tasks", data={"title": "Return the desk lamp"}).json()
    assert api.patch(f"{base}/api/tasks/{boiler['id']}", data={"due": E2E_ANCHOR.isoformat()}).ok
    assert api.patch(f"{base}/api/tasks/{boiler['id']}", data={"priority": "high"}).ok
    assert api.post(f"{base}/api/tasks/{boiler['id']}/comments", data={"body": "Asked for a morning slot."}).ok
    assert api.patch(f"{base}/api/tasks/{lamp['id']}", data={"status": "done"}).ok
    return boiler, lamp


def _open_history(page: Page) -> None:
    page.locator("nav.tabs .tab[data-tab='history']").tap()
    expect(page.locator(".home-head h1.home-title")).to_have_text("History")
    expect(page.locator("#historyHost")).to_have_attribute("data-state", "ok")


def walk_history(browser: Browser, new_context, base: str, shots: Path) -> None:
    """``new_context(browser, scheme)`` opens a phone context in that colour scheme."""
    # The writes go through a context of their own, open until the clean-up has run.
    api_context = browser.new_context()
    api = api_context.request
    boiler, lamp = _make_changes(api, base)
    try:
        context: BrowserContext = new_context(browser, "light")
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/")
        _open_history(page)
        kinds = page.locator("#historyKinds .history-kind")
        expect(kinds).to_have_text([
            "All6", "Date moved1", "Closed/reopened1", "Status0", "Priority1", "Moved0", "Comments1",
        ])
        assert_min_target(kinds)
        rows = page.locator("#historyHost .history-row")
        # newest first, grouped per run of one task's changes
        expect(rows.locator(".action-row-title")).to_have_text([
            lamp["title"], boiler["title"], lamp["title"], boiler["title"],
        ])
        run = rows.nth(1)
        expect(run.locator(".action-row-meta")).to_have_text("Priority none → high · 09:00 · 2 changes")
        expect(rows.nth(3).locator(".action-row-meta")).to_have_text("Created · 09:00 · 2 changes")
        run.locator(".history-expand").tap()
        entries = page.locator("#historyHost .history-entry .history-entry-text")
        expect(entries).to_have_text(["Priority none → high", "Due none → Mon 7 Sep"])
        assert_no_horizontal_overflow(page)
        dismiss_toasts(page)
        shot(page, shots / "story-07-phone-19-phone.png")
        surface(page, "history.pane")

        # The row opens its task; leaving the drawer comes back to History.
        run.locator(".action-row-main").tap()
        expect(page.locator("#taskDrawer")).to_be_visible()
        expect(page.locator("#taskDrawer")).to_contain_text(boiler["title"])
        page.go_back()

        # A filter narrows and is remembered on this device.
        page.locator("#historyKinds [data-kind='dates']").tap()
        expect(rows).to_have_count(1)
        expect(rows.locator(".action-row-title")).to_have_text([boiler["title"]])
        assert page.evaluate(f"() => localStorage.getItem('{KIND_KEY}')") == "dates"
        surface(page, "history.kinds")
        # …one with nothing in it says so, and offers the way back to All.
        page.locator("#historyKinds [data-kind='moved']").tap()
        expect(page.locator("#historyHost")).to_have_attribute("data-state", "empty")
        expect(page.locator("#historyHost .empty-state-message")).to_have_text("No moved changes today")
        page.locator("#historyHost .empty-state-action").tap()
        expect(rows).to_have_count(4)
        page.locator("#historyKinds [data-kind='dates']").tap()
        expect(rows).to_have_count(1)
        context.close()

        # Dark, a fresh page on the same device profile: the kind is not, so set it again.
        context = new_context(browser, "dark")
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(f"localStorage.setItem('{KIND_KEY}', 'dates')")
        page.goto(f"{base}/")
        _open_history(page)
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(page.locator("#historyKinds [data-kind='dates']")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#historyHost .history-row")).to_have_count(1)
        dismiss_toasts(page)
        shot(page, shots / "story-07-phone-20-phone.png")

        # A feed that cannot be read is its own state, never an empty day.
        page.route("**/api/history*", lambda route: route.fulfill(status=500, body="{}"))
        page.locator("#historyKinds [data-kind='all']").tap()
        expect(page.locator("#historyHost")).to_have_attribute("data-state", "error")
        expect(page.locator("#historyHost .empty-state-message")).to_contain_text("Could not read your history")
        page.unroute("**/api/history*")
        page.locator("#historyHost .empty-state-action").tap()
        expect(page.locator("#historyHost")).to_have_attribute("data-state", "ok")
        context.close()
        assert not errors, errors
    finally:
        api.delete(f"{base}/api/tasks/{boiler['id']}")
        api.delete(f"{base}/api/tasks/{lamp['id']}")
        api_context.close()
