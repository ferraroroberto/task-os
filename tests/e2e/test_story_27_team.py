"""Story 27 — A teammate comments (Step 12/13, issue #13).

    A second person opens the URL → team password → picks their name →
    comments on a task with a link → the row shows their name → the folder
    chip hands the ref to their own opener.

Two browser contexts against one seeded disposable instance whose config has
team mode on (``team.enabled``, three synthetic people, a team password and a
token): **the teammate** signs in at ``/login`` with the team password, picks
"Sam Rivera", comments on *Get three quotes* with a web link and a folder
ref, and changes the priority; **the owner** (a second, fresh context — no
cookies) opens the same task and sees Sam's comment under Sam's name, then
answers under their own (``team.people[0]``); the thread then holds both, each
under its writer's name. Numbered after the story index's next
free slot (27), not the Step number — docs/validation.md.

What a browser on this PC cannot prove, and the unit tests in
``tests/test_auth.py`` do: the disposable instance binds loopback, so both
contexts are the owner as far as the *gate* goes. The teammate's sign-in is
still the real team-password → ``taskos_team`` cookie exchange, but the
non-loopback half — a page redirecting to the name step until one is picked,
the team cookie passing the gate without the token — is asserted there with a
spoofed tailnet address. A second person on a second PC is recorded **not
verified** in docs/validation/story-27-team.md.

Shots:
    docs/screenshots/story-27-team-1-desktop.png  pick your name (after the team password)
    docs/screenshots/story-27-team-2-desktop.png  the teammate's comment, named, with its chips
    docs/screenshots/story-27-team-3-desktop.png  the owner's view of the same thread (dark)
    docs/screenshots/story-27-team-4-phone.png    pick your name on the phone (dark)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import Browser, Page, expect

from src.auth import hash_password
from tests.conftest import write_test_config
from tests.e2e._geometry import assert_min_target, assert_no_horizontal_overflow
from tests.e2e.conftest import (
    E2E_ANCHOR,
    INTERCEPT,
    _boot,
    _get,
    _terminate,
    e2e_workdir,
    settle,
    shot,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
E2E_TOKEN = "e2e-story-27-token"
TEAM_PASSWORD = "e2e-story-27-team"
PEOPLE = ["Alex Chen", "Sam Rivera", "Jordan Lee"]
COMMENT = "Second quote is in: https://example.com/quotes/2 — plans updated in {onedrive}/house/kitchen/plans"
FOLDER_HREF = "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen%2Fplans"


@pytest.fixture(scope="module")
def team_webapp() -> Iterator[str]:
    """A seeded disposable instance with team mode on (synthetic people and secrets only)."""
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("team")
    seed_db(work / "tasks.db", E2E_ANCHOR)
    cfg = write_test_config(work / "config.json")           # sample, mirror / backup dirs blanked
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["auth"] = {"token": E2E_TOKEN, "password_hash": ""}
    raw["team"] = {"enabled": True, "people": PEOPLE, "password_hash": hash_password(TEAM_PASSWORD)}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    proc, base, log = _boot(work, work / "tasks.db", cfg)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


def _task_id(base: str, title: str) -> int:
    items = _get(base, "/api/tasks?q=" + quote(title))["items"]
    return next(t["id"] for t in items if t["title"] == title)


def _newest_comment(page: Page):
    return page.locator("#taskDrawer .comment-list .comment").first


def _park_on_comments(page: Page) -> None:
    """Scroll the drawer so its Comments section heads the panel — and prove it
    stayed there (the same settle → scroll → settle → check loop as
    ``scroll_to_bottom``, #166), so the shot is of the thread, deterministically."""
    read = """el => {
      const off = Math.round(el.querySelector('.drawer-comments').getBoundingClientRect().top - el.getBoundingClientRect().top);
      return [off, Math.abs(el.scrollHeight - el.clientHeight - el.scrollTop) <= 1];
    }"""
    park = "el => { el.scrollTop += Math.round(el.querySelector('.drawer-comments').getBoundingClientRect().top - el.getBoundingClientRect().top); }"
    drawer = page.locator("#taskDrawer")
    for _ in range(10):
        settle(page)
        drawer.evaluate(park)
        before = drawer.evaluate(read)
        settle(page)
        off, at_end = drawer.evaluate(read)
        # at the top, or as far as the panel scrolls (a short task's thread)
        if [off, at_end] == before and (abs(off) <= 1 or (at_end and off > 0)):
            return
    raise AssertionError("the drawer never settled with Comments at its top")


def test_teammate_signs_in_picks_a_name_and_comments(team_webapp: str, browser: Browser, shots: Path) -> None:
    base = team_webapp
    quotes = _task_id(base, "Get three quotes")

    # ---- the teammate: team password → pick a name → the deep link
    mate = browser.new_context(viewport=DESKTOP, color_scheme="light")
    mate.add_init_script(INTERCEPT)
    try:
        page = mate.new_page()
        page.goto(f"{base}/login?next=%2F%23task%2F{quotes}")
        expect(page.locator("#loginForm.card")).to_be_visible()
        page.fill("#loginSecret", "not-the-team-password")
        page.locator("#loginSubmit").click()
        expect(page.locator("#loginError")).to_have_text("wrong token or password")
        page.fill("#loginSecret", TEAM_PASSWORD)
        page.locator("#loginSubmit").click()
        pick = page.locator("#pickCard")
        expect(pick).to_be_visible()
        expect(page.locator("#loginForm")).to_be_hidden()
        people = pick.locator("#pickList .team-person")
        expect(people).to_have_count(3)
        expect(people.locator(".team-name")).to_have_text(PEOPLE)
        expect(people.first.locator(".team-initials")).to_have_text("AC")      # no avatar file → initials
        expect(people.first).to_be_focused()
        cookies = {c["name"]: c for c in mate.cookies()}
        assert cookies["taskos_team"]["httpOnly"] is True
        assert "taskos_token" not in cookies                                   # never the owner's token
        shot(page, shots / "story-27-team-1-desktop.png")

        pick.get_by_role("button", name="Sam Rivera").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        assert page.url == f"{base}/#task/{quotes}"
        cookies = {c["name"]: c for c in mate.cookies()}
        assert cookies["taskos_name"]["value"] == "Sam%20Rivera" and cookies["taskos_name"]["httpOnly"] is True

        # ---- the comment, with a link and a folder ref, signed "Sam Rivera"
        drawer.locator(".comment-input").fill(COMMENT)
        drawer.locator(".comment-send").click()
        newest = _newest_comment(page)
        expect(newest.locator(".comment-body")).to_contain_text("Second quote is in")
        expect(newest.locator(".comment-meta strong")).to_have_text("Sam Rivera")
        expect(newest.locator("a.chip-web")).to_have_attribute("href", "https://example.com/quotes/2")
        folder = newest.locator("a.chip-folder")
        expect(folder).to_have_attribute("href", FOLDER_HREF)
        _park_on_comments(page)
        shot(page, shots / "story-27-team-2-desktop.png")
        # the chip goes to this PC's own opener (taskos://, story 09), not a web page
        folder.click()
        assert page.evaluate("window.__taskosClicks") == [FOLDER_HREF]
        page.keyboard.press("Escape")

        # a change they make is theirs in the activity log too
        assert page.request.patch(f"{base}/api/tasks/{quotes}", data={"priority": "high"}).ok
        top = page.request.get(f"{base}/api/tasks/{quotes}").json()["activity"][0]
        assert (top["field"], top["actor"]) == ("priority", "Sam Rivera")

        # Settings says who this browser is, with the way back to the name step
        page.goto(f"{base}/")
        page.locator("nav.tabs .tab[data-tab='settings']").click()
        page.locator("#accessCard summary").click()
        expect(page.locator("#accessRows")).to_contain_text("you are Sam Rivera")
        expect(page.locator("#accessRows a")).to_have_attribute("href", "/login?step=name&next=%2F%23settings%2Faccess")
    finally:
        mate.close()

    # ---- the owner: a fresh context on this PC sees Sam's comment, answers as themselves
    owner = browser.new_context(viewport=DESKTOP, color_scheme="dark")
    try:
        page = owner.new_page()
        page.goto(f"{base}/#task/{quotes}")
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(_newest_comment(page).locator(".comment-meta strong")).to_have_text("Sam Rivera")
        drawer.locator(".comment-input").fill("Thanks — booking the first one.")
        drawer.locator(".comment-send").click()
        expect(_newest_comment(page).locator(".comment-body")).to_have_text("Thanks — booking the first one.")
        expect(_newest_comment(page).locator(".comment-meta strong")).to_have_text("Alex Chen")
        _park_on_comments(page)
        shot(page, shots / "story-27-team-3-desktop.png")
    finally:
        owner.close()

    thread = [(c["author"], c["body"]) for c in _get(base, f"/api/tasks/{quotes}")["comments"]][-2:]
    assert thread == [("Sam Rivera", COMMENT), ("Alex Chen", "Thanks — booking the first one.")]

    # ---- the name step on a phone
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="dark")
    try:
        page = phone.new_page()
        page.goto(f"{base}/login?step=name")
        expect(page.locator("#pickCard")).to_be_visible()
        expect(page.locator("#pickList .team-person")).to_have_count(3)
        for i in range(3):
            assert_min_target(page.locator("#pickList .team-person").nth(i))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-27-team-4-phone.png")
    finally:
        phone.close()
