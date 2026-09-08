"""Story 23 — AI suggestions are staged, then explicitly accepted (#95)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e.conftest import E2E_ANCHOR, _boot, _get, _terminate, e2e_workdir, shot
from tests.fixtures.anthropic_fake import FakeAnthropic
from tests.fixtures.seed import seed_db

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


class AIInstance:
    def __init__(self, base: str) -> None:
        self.base = base


def _suggestions(body: dict) -> str:
    context = json.loads(body["messages"][0]["content"])
    project = context["projects"][0]
    return json.dumps({
        "suggestions": [{
            "task_id": task["id"],
            "parent_id": project["id"],
            "priority": "medium",
            "due": None,
            "person_id": None,
            "reason": "This belongs with the active home project.",
        } for task in context["inbox_tasks"]]
    })


@pytest.fixture(scope="module")
def ai_webapp() -> Iterator[AIInstance]:
    work = e2e_workdir("ai-triage")
    db = work / "tasks.db"
    seed_db(db, anchor=E2E_ANCHOR)
    with FakeAnthropic(_suggestions) as hub:
        config = write_test_config(
            work / "config.json", ai_enabled=True, ai_base_url=hub.url, ai_model="fake",
        )
        proc, base, log = _boot(work, db, config)
        try:
            yield AIInstance(base)
        finally:
            _terminate(proc)
            log.close()


def test_ai_inbox_triage(ai_webapp: AIInstance, browser: Browser, shots: Path) -> None:
    base = ai_webapp.base
    desktop = browser.new_context(viewport=DESKTOP, color_scheme="light")
    page: Page = desktop.new_page()
    page.goto(base + "/")
    expect(page.locator("#paneBoard")).to_be_visible()

    triage = page.locator(".board-col[data-col='inbox'] .board-triage")
    expect(triage).to_be_enabled()
    triage.click()
    suggestions = page.locator(".board-col[data-col='inbox'] .ai-suggestion")
    expect(suggestions.first).to_be_visible()
    assert suggestions.count() >= 1
    shot(page, shots / "story-23-ai-triage-1-desktop.png")

    first_task_id = int(suggestions.first.locator("xpath=..").get_attribute("data-id"))
    suggestions.first.get_by_role("button", name="Accept suggestion").click()
    expect(page.locator(f".board-col[data-col='todo'] .trow[data-id='{first_task_id}']")).to_be_visible()
    task = _get(base, f"/api/tasks/{first_task_id}")
    assert task["status"] == "todo" and task["priority"] == "medium"
    assert {row["actor"] for row in task["activity"] if row["field"] in {"parent", "priority", "status"}} == {"ai"}
    shot(page, shots / "story-23-ai-triage-2-desktop.png")

    page.get_by_role("tab", name="Settings").click()
    card = page.locator("#aiCard")
    card.locator("summary").click()
    expect(card.locator("#aiCardMeta")).to_have_text("on")
    expect(card.locator("#statusAI")).to_contain_text("reachable")
    desktop.close()

    phone = browser.new_context(
        viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="dark",
    )
    mobile = phone.new_page()
    mobile.goto(base + "/")
    mobile.get_by_role("tab", name="Board").click()
    mobile.locator(".board-strip-btn[data-col='inbox']").click()
    expect(mobile.locator(".board-triage-phone")).to_be_visible()
    expect(mobile.locator(".board-col[data-col='inbox'] .ai-suggestion").first).to_be_visible()
    shot(mobile, shots / "story-23-ai-triage-3-phone.png")
    phone.close()
