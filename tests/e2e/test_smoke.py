"""Static-tier smoke: the shell boots and answers — the narrow target the
gate runs for inert-asset-only diffs (.fleet.toml [e2e] static_pytest_target).
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_shell_boots(webapp: str, page: Page) -> None:
    page.goto(webapp)
    expect(page.locator("nav.tabs .tab")).to_have_count(6)
    expect(page.locator("#paneBoard .empty-state-message")).to_have_text("Add your first task")
    expect(page.locator("#buildReadout")).to_contain_text("Build:")
