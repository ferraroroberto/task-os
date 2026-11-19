"""Story 07's Settings → Available features leg: the group-label steps.

A Settings group whose every row belongs to a switched-off block leaves with its
label; these steps are slices of ``test_story_07_phone``'s features walk and expect
the page where it leaves it (Settings open, every block off, or every block back on).
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

_FEATURES_GROUP = "#paneSettings .settings-group[aria-labelledby='settingsGroupFeatures']"


def _group(page: Page, key: str):
    """The group's label and its card."""
    return (
        page.locator(f"#settingsGroup{key}"),
        page.locator(f"#paneSettings .settings-group[aria-labelledby='settingsGroup{key}']"),
    )


def assert_empty_groups_follow_switches(page: Page) -> None:
    """Every block off: Sync (issues + calendar) and Email lose label and card on the
    first render after a reload; Tools keeps Search and Folder opener. Turning Email
    back on live restores its group and leaves Sync hidden."""
    expect(page.locator("#paneSettings")).to_be_visible()
    sync, email = _group(page, "Sync"), _group(page, "Email")
    for el in (*sync, *email):
        expect(el).to_be_hidden()
    expect(page.locator("#settingsGroupTools")).to_be_visible()
    page.locator(f"{_FEATURES_GROUP} [data-feature-key='email'] .toggle").tap()
    expect(page.locator("html")).to_have_attribute("data-features-off", "time calendar issues ai mirror")
    for el in email:
        expect(el).to_be_visible()
    for el in sync:
        expect(el).to_be_hidden()


def assert_group_labels_back(page: Page) -> None:
    """Every block on again: Sync and Email are back with their labels."""
    for el in (*_group(page, "Sync"), *_group(page, "Email")):
        expect(el).to_be_visible()


def assert_default_feature_rows(group: Locator) -> None:
    """Seven rows; every block is on by default but the opt-in one, which writes outside this install."""
    expect(group.locator(".settings-feature")).to_have_count(7)
    expect(group.locator(".toggle[aria-checked='true']")).to_have_count(6)
    publish = group.locator("[data-feature-key='publish_address']")
    expect(publish.locator(".toggle")).to_have_attribute("aria-checked", "false")
    expect(publish.locator(".settings-feature-state")).to_have_text("Off on this machine")


def walk_opt_in_row(page: Page, group: Locator) -> None:
    """Opting in with no file configured says so on the row, never a bare "on", and owns no
    screen: the page's off list is untouched either way. Switched off again at the end."""
    publish = group.locator("[data-feature-key='publish_address']")
    publish.locator(".toggle").tap()
    expect(publish.locator(".settings-feature-state")).to_have_text(
        "On, unavailable here: network_sharing.host_ip_file is blank — no file to publish to")
    expect(page.locator("html")).not_to_have_attribute("data-features-off", re.compile("."))
    publish.locator(".toggle").tap()
    expect(publish.locator(".settings-feature-state")).to_have_text("Off on this machine")
