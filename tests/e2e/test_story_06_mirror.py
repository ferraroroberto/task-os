"""Story 06 — edit in a text editor (Step 6/13, issue #7).

    The mirror folder fills with one .md per task → open a task's file in an
    editor, change ``due:`` and append a comment line → within seconds the
    app shows both, log actor ``md`` → make a conflicting edit → the conflict
    is recorded as a mirror event (issue #84) — visible on the Settings
    card, nothing added to the task's own comment thread — the backup folder
    holds a dated ``.db`` copy → a malformed file is skipped and reported,
    never fatal.

Walks the story against the **mirrored** disposable instance (conftest
``mirrored_webapp``: the synthetic seed, ``mirror.dir`` / ``backup_dir`` under
a temp folder — never a real synced folder) at 1440×900 Chromium, saving the
proof shots the validation record links to:

    docs/screenshots/story-06-mirror-1-desktop.png   Settings card: mirror + backup on
    docs/screenshots/story-06-mirror-2-desktop.png   drawer: the comment typed in the file, origin md
    docs/screenshots/story-06-mirror-3-desktop.png   drawer: activity due old → new by md
    docs/screenshots/story-06-mirror-4-desktop.png   Settings card: the import conflict, inspect + clear
    docs/screenshots/story-06-mirror-5-desktop.png   Settings card: backup file + a skipped file (dark)

The "editor" is the test writing the file — the headed walk in
``docs/validation/story-06-mirror.md`` does it in a real editor beside the app.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import _get

DESKTOP = {"width": 1440, "height": 900}


def _send(base: str, method: str, path: str, body: dict | None = None, actor: str = "ui") -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Actor", actor)
    with urllib.request.urlopen(req, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def _wait(predicate: Callable[[], bool], timeout: float = 15.0, what: str = "condition") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def _edit(path: Path, text: str) -> None:
    """What an editor's save does: write, and make sure the mtime moves past our last export."""
    path.write_text(text, encoding="utf-8", newline="\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def test_edit_in_a_text_editor(mirrored_webapp, browser: Browser, shots: Path) -> None:
    inst = mirrored_webapp
    base = inst.base
    n_tasks = _get(base, "/api/tasks?include_closed=true")["count"]

    # 0. The lifespan thread exports every task on startup; the status says so.
    _wait(lambda: _get(base, "/api/status")["mirror"]["files"] == n_tasks, what="initial export")
    files = sorted(inst.mirror_dir.glob("*.md"))
    assert len(files) == n_tasks
    quotes = _get(base, "/api/tasks?q=Get%20three%20quotes")["items"][0]
    task_id = quotes["id"]
    path = inst.mirror_dir / f"{task_id:04d}-get-three-quotes.md"
    assert path.exists(), sorted(p.name for p in files)[:5]

    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()

        # 1. Settings → the card reports both services on, pointing at the temp folders.
        page.goto(f"{base}/")
        page.click("nav.tabs .tab[data-tab='settings']")
        card = page.locator("#mirrorCard")
        expect(card.locator("#statusMirror .status-ok")).to_have_text("enabled")
        expect(card.locator("#statusMirror")).to_contain_text(str(inst.mirror_dir))
        expect(card.locator("#statusMirror")).to_contain_text(f"{n_tasks} file(s)")
        expect(card.locator("#statusBackup .status-ok")).to_have_text("enabled")
        expect(card.locator("#mirrorCardMeta")).to_have_text("both on")
        page.screenshot(path=str(shots / "story-06-mirror-1-desktop.png"))

        # 2. "Open the file in an editor": change due: and append a comment line.
        old_due = _get(base, f"/api/tasks/{task_id}")["due"]
        text = path.read_text(encoding="utf-8")
        assert f"\ndue: {old_due}\n" in text and "## Comments" in text
        text = text.replace(f"\ndue: {old_due}\n", "\ndue: 2026-12-24\n", 1)
        text = text.replace("\n## Log", "- checked the tiles supplier, they deliver on Fridays\n\n## Log", 1)
        _edit(path, text)

        # 3. Within seconds the app shows both, log actor md.
        def _imported() -> bool:
            t = _get(base, f"/api/tasks/{task_id}")
            return t["due"] == "2026-12-24" and any(c["origin"] == "md" for c in t["comments"])

        _wait(_imported, what="the watcher to import the file edit")
        detail = _get(base, f"/api/tasks/{task_id}")
        act = detail["activity"][0]
        assert (act["field"], act["actor"], act["old_value"], act["new_value"]) == ("due", "md", old_due, "2026-12-24")
        md_comment = [c for c in detail["comments"] if c["origin"] == "md"][-1]
        assert md_comment["body"] == "checked the tiles supplier, they deliver on Fridays"
        assert md_comment["author"] == "Roberto Ferraro"  # the configured owner (sample config)
        # …and the file converged to canonical form (re-exported with the new comment line)
        _wait(lambda: "· Roberto Ferraro · md: checked the tiles supplier" in path.read_text(encoding="utf-8"),
              what="the re-export")
        page.goto(f"{base}/#task/{task_id}")
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        newest = drawer.locator(".comment").first
        expect(newest.locator(".comment-origin")).to_have_text("md")
        expect(newest.locator(".comment-body")).to_contain_text("checked the tiles supplier")
        page.screenshot(path=str(shots / "story-06-mirror-2-desktop.png"))
        due_row = drawer.locator(".activity-row[data-field='due']").first
        expect(due_row.locator(".activity-old")).to_have_text(old_due)
        expect(due_row.locator(".activity-new")).to_have_text("2026-12-24")
        expect(due_row.locator(".activity-meta")).to_contain_text("md ·")
        due_row.scroll_into_view_if_needed()
        page.screenshot(path=str(shots / "story-06-mirror-3-desktop.png"))

        # 4. A conflicting edit: the app moves the due (a UI edit) and the file — still
        #    carrying the older export — is saved with another value right after. The DB
        #    wins and the rejected file value is recorded as a mirror event (issue #84),
        #    never as a comment on the task.
        n_comments_before_conflict = len(detail["comments"])
        time.sleep(1.2)  # a distinct second from the last export (the baseline is second-precise)
        _send(base, "PATCH", f"/api/tasks/{task_id}", {"due": "2026-11-11"}, actor="ui")
        text = path.read_text(encoding="utf-8").replace("\ndue: 2026-12-24\n", "\ndue: 2026-10-10\n", 1)
        _edit(path, text)

        def _conflict() -> bool:
            return _get(base, "/api/mirror/events")["events"] != []

        _wait(_conflict, what="the conflict event")
        detail = _get(base, f"/api/tasks/{task_id}")
        assert detail["due"] == "2026-11-11"  # the DB won
        assert len(detail["comments"]) == n_comments_before_conflict  # untouched — no diagnostic comment
        events = _get(base, "/api/mirror/events")["events"]
        assert len(events) == 1
        conflict = events[0]
        assert conflict["task_id"] == task_id and conflict["kind"] == "conflict" and conflict["field"] == "due"
        assert conflict["file_value"] == "2026-10-10" and conflict["kept_value"] == "2026-11-11"
        _wait(lambda: "\ndue: 2026-11-11\n" in path.read_text(encoding="utf-8"), what="the file to converge")
        page.reload()  # same #task/<id> URL: a reload re-fetches the drawer
        expect(drawer).to_be_visible()
        # the drawer's newest comment is still the one typed in step 3 — the conflict added no comment
        expect(drawer.locator(".comment").first.locator(".comment-body")).to_contain_text("checked the tiles supplier")

        # The diagnostic surfaces on the Settings card instead — inspect, then clear it.
        page.keyboard.press("Escape")  # close the drawer first — it overlays the tab panel
        expect(drawer).to_be_hidden()
        page.click("nav.tabs .tab[data-tab='settings']")
        card.locator("summary.collapse-summary").click()  # the disclosure starts collapsed
        expect(card.locator("#statusMirrorEvents .status-warn")).to_have_text("1 since the last review")
        expect(card.locator("#statusMirrorEvents")).to_contain_text("due: file said 2026-10-10, kept 2026-11-11")
        page.screenshot(path=str(shots / "story-06-mirror-4-desktop.png"))
        clear_btn = card.locator("#mirrorEventsClear")
        clear_btn.scroll_into_view_if_needed()
        clear_btn.click()

        def _cleared() -> bool:
            return _get(base, "/api/mirror/events")["events"] == []

        _wait(_cleared, what="the events to clear")
        expect(card.locator("#statusMirrorEvents .status-ok")).to_have_text("none since the last review")

        # 5. The backup folder holds a dated .db copy (the startup pass) — and a
        #    malformed file is skipped and reported, never fatal.
        _wait(lambda: any(inst.backup_dir.glob("tasks-????????.db")), what="the startup backup")
        backup = sorted(inst.backup_dir.glob("tasks-????????.db"))[-1]
        assert backup.stat().st_size > 0
        broken = sorted(inst.mirror_dir.glob("*.md"))[1]
        _edit(broken, "---\nid: 2\ntitle: [oops\n")
        _wait(lambda: _get(base, "/api/status")["mirror"]["errors"] == 1, what="the skipped-file counter")
        st = _get(base, "/api/status")
        assert st["mirror"]["error_files"] == [broken.name]
        assert st["backup"]["last_file"] == backup.name
        assert _get(base, "/healthz")["ok"] is True
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.click("nav.tabs .tab[data-tab='settings']")
        expect(card.locator("#statusMirror .status-warn")).to_have_text("enabled · 1 file(s) skipped")
        expect(card.locator("#statusMirror")).to_contain_text(broken.name)
        expect(card.locator("#statusBackup")).to_contain_text(backup.name)
        page.screenshot(path=str(shots / "story-06-mirror-5-desktop.png"))
    finally:
        context.close()
