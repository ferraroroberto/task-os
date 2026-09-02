"""``src/mirror.py`` — export/import engine on a hermetic seeded database + a temp mirror dir."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src import mirror as mirror_mod
from src import tasks_repo as repo
from src.config import load_config
from src.mirror import Mirror, MirrorParseError, file_name, parse_file, render, slugify
from tests.conftest import write_test_config
from tests.fixtures.seed import PINNED_ANCHOR, seed_db

T0 = datetime(2026, 8, 17, 9, 0, 0).astimezone()


def _clock(dt: datetime):
    return lambda: dt


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Seeded DB + config whose mirror.dir / backup_dir live under tmp_path."""
    db = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(db))
    mirror_dir = tmp_path / "mirror"
    mirror_dir.mkdir()
    cfg = write_test_config(tmp_path / "config.json", dir=str(mirror_dir), backup_dir=str(tmp_path / "backup"))
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    seed_db(db, PINNED_ANCHOR)
    conn = dbmod.connect()
    yield {"conn": conn, "dir": mirror_dir, "db": db, "config": cfg}
    conn.close()


@pytest.fixture
def mirror(env) -> Mirror:
    m = Mirror(load_config())
    assert m.enabled, m.reason
    return m


def _touch(path: Path, text: str) -> None:
    """Write and bump the mtime past the recorded one (2 s so coarse filesystems notice)."""
    path.write_text(text, encoding="utf-8", newline="\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def _bathroom(env) -> tuple[int, Path]:
    conn = env["conn"]
    tid = conn.execute("SELECT id FROM tasks WHERE title = 'Bathroom'").fetchone()["id"]
    return tid, env["dir"] / file_name(tid, "Bathroom")


# ------------------------------------------------------------- rendering


def test_slug_and_file_name() -> None:
    assert slugify("Renew passports (2026)!") == "renew-passports-2026"
    assert slugify("Café — überprüfen") == "cafe-uberprufen"
    assert slugify("   ") == "task"
    assert slugify("x" * 100) == "x" * 60
    assert file_name(42, "Copilot licences") == "0042-copilot-licences.md"


def test_frontmatter_round_trip(env) -> None:
    conn = env["conn"]
    t = repo.create_task(conn, 'Quote: "tricky" # title', description="Line one\n\n## Not a section\n- bullet")
    repo.add_link(conn, t["id"], "https://example.com/a?b=1", label="a: b", kind="web")
    repo.add_comment(conn, t["id"], "first line\nsecond line\n- looks like a bullet", author="Sam", origin="cli")
    task = repo.get_task(conn, t["id"])
    text = render(task, exported_at="2026-08-17T09:00:00+02:00")
    parsed = parse_file(text)
    fm = parsed.frontmatter
    assert fm["id"] == t["id"] and fm["title"] == 'Quote: "tricky" # title'
    assert fm["links"] == [{"url": "https://example.com/a?b=1", "label": "a: b", "kind": "web"}]
    assert fm["parent"] is None and fm["due"] is None and fm["exported_at"] == "2026-08-17T09:00:00+02:00"
    assert parsed.description == "Line one\n\n## Not a section\n- bullet"
    assert parsed.comments == [{
        "ts": task["comments"][0]["ts"], "author": "Sam", "origin": "cli",
        "body": "first line\nsecond line\n- looks like a bullet",
    }]
    # re-rendering the parsed structure is stable: render → parse → render is byte-identical
    assert render(task, exported_at="2026-08-17T09:00:00+02:00") == text


def test_parse_rejects_malformed() -> None:
    with pytest.raises(MirrorParseError):
        parse_file("no fence here")
    with pytest.raises(MirrorParseError):
        parse_file("---\ntitle: x\n")  # unterminated
    with pytest.raises(MirrorParseError):
        parse_file("---\ntitle: x\n---\n")  # no id
    with pytest.raises(MirrorParseError):
        parse_file('---\nid: 1\ntitle: "unterminated\n---\n')


# --------------------------------------------------------------- export


def test_export_all_is_deterministic_and_idempotent(env, mirror: Mirror) -> None:
    conn = env["conn"]
    with repo.use_clock(_clock(T0)):
        report = mirror.export_all(conn)
    n_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert report == {"tasks": n_tasks, "written": n_tasks, "removed": 0}
    files = sorted(env["dir"].glob("*.md"))
    assert len(files) == n_tasks
    snapshot = {p.name: p.read_bytes() for p in files}
    # second pass: nothing changed → nothing rewritten, bytes identical
    with repo.use_clock(_clock(T0.replace(hour=10))):
        assert mirror.export_all(conn)["written"] == 0
    assert {p.name: p.read_bytes() for p in sorted(env["dir"].glob("*.md"))} == snapshot
    # a second mirror over the same DB state under the same clock renders the same bytes
    other = env["dir"].parent / "mirror2"
    other.mkdir()
    cfg2 = write_test_config(env["dir"].parent / "config2.json", dir=str(other))
    with repo.use_clock(_clock(T0)):
        m2 = Mirror(load_config(cfg2))
        conn.execute("DELETE FROM mirror_state")
        conn.commit()
        m2.export_all(conn)
    assert {p.name: p.read_bytes() for p in sorted(other.glob("*.md"))} == snapshot
    assert conn.execute("SELECT COUNT(*) FROM mirror_state").fetchone()[0] == n_tasks


def test_rename_on_title_change_and_remove_on_delete(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    assert path.exists()
    repo.update_task(conn, tid, title="Bathroom refit")
    new_path = mirror.export_task(conn, tid)
    assert new_path == env["dir"] / f"{tid:04d}-bathroom-refit.md"
    assert new_path.exists() and not path.exists()
    assert conn.execute("SELECT path FROM mirror_state WHERE task_id = ?", (tid,)).fetchone()[0] == new_path.name
    repo.delete_task(conn, tid)
    assert mirror.export_task(conn, tid) is None
    assert not new_path.exists()
    assert conn.execute("SELECT 1 FROM mirror_state WHERE task_id = ?", (tid,)).fetchone() is None


def test_export_all_removes_files_of_deleted_tasks(env, mirror: Mirror) -> None:
    conn = env["conn"]
    mirror.export_all(conn)
    tid, path = _bathroom(env)
    subtree = repo._descendant_ids(conn, tid)
    conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))  # bypass the repo → no listener; FK cascades
    conn.commit()
    assert mirror.export_all(conn)["removed"] == 1 + len(subtree)
    assert not path.exists()


def test_touch_queue_flush_exports_only_touched(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.touch([tid])
    assert mirror.status(conn)["pending"] == 1
    assert mirror.flush(conn) == 1
    assert path.exists() and len(list(env["dir"].glob("*.md"))) == 1


def test_write_listener_reaches_the_queue(env, mirror: Mirror) -> None:
    conn = env["conn"]
    repo.add_write_listener(mirror.touch)
    try:
        t = repo.create_task(conn, "Listened")
        assert t["id"] in mirror._pending
    finally:
        repo.remove_write_listener(mirror.touch)


# --------------------------------------------------------------- import


def test_import_changed_due_logs_actor_md(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    text = path.read_text(encoding="utf-8").replace("\ndue: null\n", "\ndue: 2026-12-24\n")
    _touch(path, text)
    with repo.use_clock(_clock(T0.replace(hour=11))):
        report = mirror.import_tick(conn)
    assert [i["path"] for i in report["imported"]] == [path.name]
    assert report["imported"][0]["applied"] == {"due": "2026-12-24"}
    task = repo.get_task(conn, tid)
    assert task["due"] == "2026-12-24"
    top = task["activity"][0]
    assert (top["field"], top["actor"], top["old_value"], top["new_value"]) == ("due", "md", None, "2026-12-24")
    # re-exported to canonical form, and the watcher does not re-read its own write
    assert "due: 2026-12-24" in path.read_text(encoding="utf-8")
    assert mirror.import_tick(conn)["imported"] == []


def test_import_natural_due_phrase_and_person_by_name(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    text = path.read_text(encoding="utf-8")
    text = text.replace("\ndue: null\n", "\ndue: 2026-09-01\n").replace("\nperson: null\n", "\nperson: Alex Chen\n")
    text = text.replace("\nstatus: todo\n", "\nstatus: doing\n").replace("\npriority: none\n", "\npriority: high\n")
    _touch(path, text)
    res = mirror.import_tick(conn)["imported"][0]
    task = repo.get_task(conn, tid)
    assert task["due"] == "2026-09-01" and task["person"]["name"] == "Alex Chen"
    assert task["status"] == "doing" and task["priority"] == "high"
    assert set(res["applied"]) == {"due", "person", "status", "priority"}
    assert {a["actor"] for a in task["activity"][:4]} == {"md"}


def test_starts_round_trips_and_conflicts_like_any_field(env, mirror: Mirror) -> None:
    """#87: `starts:` exports, imports through the repo layer (natural phrases
    welcome) and loses to a newer DB value exactly as `due:` does — the policy
    is generic because the field goes through the same one layer."""
    conn = env["conn"]
    tid, path = _bathroom(env)
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    text = path.read_text(encoding="utf-8")
    assert "\nstarts: null\n" in text                      # exported, empty

    _touch(path, text.replace("\nstarts: null\n", "\nstarts: 2026-12-01\n"))
    with repo.use_clock(_clock(T0.replace(hour=11))):
        res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {"starts": "2026-12-01"}
    task = repo.get_task(conn, tid)
    assert task["starts"] == "2026-12-01"
    assert (task["activity"][0]["field"], task["activity"][0]["actor"]) == ("starts", "md")
    assert "starts: 2026-12-01" in path.read_text(encoding="utf-8")

    # a natural phrase in the file resolves through src/dates.py, like due
    text = path.read_text(encoding="utf-8").replace("\nstarts: 2026-12-01\n", "\nstarts: 2027-01-15\n")
    _touch(path, text)
    with repo.use_clock(_clock(T0.replace(hour=12))):
        mirror.import_tick(conn)
    assert repo.get_task(conn, tid)["starts"] == "2027-01-15"

    # conflict: the DB moved after the file was written, so the DB wins and
    # the rejection is an event, not a comment on the task
    with repo.use_clock(_clock(T0.replace(hour=13))):
        mirror.export_task(conn, tid)
    with repo.use_clock(_clock(T0.replace(hour=14))):
        repo.update_task(conn, tid, starts="2027-02-02", actor="ui")
    text = path.read_text(encoding="utf-8").replace("\nstarts: 2027-01-15\n", "\nstarts: 2027-03-03\n")
    _touch(path, text)
    with repo.use_clock(_clock(T0.replace(hour=15))):
        res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {}
    assert repo.get_task(conn, tid)["starts"] == "2027-02-02"
    event = [e for e in repo.list_mirror_events(conn) if e["field"] == "starts"]
    assert len(event) == 1 and event[0]["kind"] == "conflict"
    assert (event[0]["file_value"], event[0]["kept_value"]) == ("2027-03-03", "2027-02-02")
    assert "starts: 2027-02-02" in path.read_text(encoding="utf-8")


def test_planned_on_round_trips_plan_order_stays_home(env, mirror: Mirror) -> None:
    """#89: `planned_on:` exports and imports like `starts` — same one layer,
    same conflict policy — while `plan_order` never appears in the file:
    presentation-level ordering, and mirroring it would churn every synced
    file on every drag."""
    conn = env["conn"]
    tid, path = _bathroom(env)
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    text = path.read_text(encoding="utf-8")
    assert "\nplanned_on: null\n" in text                  # exported, empty
    assert "plan_order" not in text

    _touch(path, text.replace("\nplanned_on: null\n", "\nplanned_on: 2026-12-01\n"))
    with repo.use_clock(_clock(T0.replace(hour=11))):
        res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {"planned_on": "2026-12-01"}
    task = repo.get_task(conn, tid)
    assert task["planned_on"] == "2026-12-01"
    assert task["plan_order"] == 1                         # appended by the repo's plan rules
    assert (task["activity"][0]["field"], task["activity"][0]["actor"]) == ("planned_on", "md")
    assert "planned_on: 2026-12-01" in path.read_text(encoding="utf-8")


def test_import_description_section(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    text = path.read_text(encoding="utf-8").replace("## Description\n\n## Comments", "## Description\n\nRetile the floor first.\n\n## Comments")
    _touch(path, text)
    mirror.import_tick(conn)
    task = repo.get_task(conn, tid)
    assert task["description"] == "Retile the floor first."
    assert task["activity"][0]["field"] == "description" and task["activity"][0]["actor"] == "md"


def test_appended_comment_lines_become_md_comments(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    repo.add_comment(conn, tid, "existing thread", author="Sam", origin="ui")
    mirror.export_task(conn, tid)
    text = path.read_text(encoding="utf-8")
    # a dated line one hour ahead of now, so it sorts after the two "now" comments
    # whatever the wall clock (a fixed date here became a date-bomb once passed)
    later = (datetime.now().astimezone() + timedelta(hours=1)).isoformat(timespec="seconds")
    text = text.replace(
        "\n## Log",
        f"- hello from the editor\n- {later} · Alex Chen · md: dated line\n  with a second line\n\n## Log",
    )
    _touch(path, text)
    res = mirror.import_tick(conn)["imported"][0]
    assert res["comments_added"] == 2
    comments = repo.list_comments(conn, tid)
    assert [c["body"] for c in comments] == ["existing thread", "hello from the editor", "dated line\nwith a second line"]
    assert comments[1]["origin"] == "md" and comments[1]["author"] == "Roberto Ferraro"  # configured owner
    assert comments[2]["origin"] == "md" and comments[2]["author"] == "Alex Chen"
    assert comments[2]["ts"] == later
    # the known lines were not duplicated; a second import of the canonical file adds nothing
    _touch(path, path.read_text(encoding="utf-8"))
    assert mirror.import_tick(conn)["imported"][0]["comments_added"] == 0
    assert len(repo.list_comments(conn, tid)) == 3


def test_non_md_origin_line_imports_once(env, mirror: Mirror) -> None:
    """A file the app did not write imports its comment once, however often it is read (#123).

    Every imported comment is stored with ``origin=md``, so keying the dedup on the
    file's own origin token meant a ``· ui:`` line never matched the row it had just
    created — and was re-inserted on every pass, without bound.
    """
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    doctored = path.read_text(encoding="utf-8").replace(
        "\n## Log", "- 2026-07-31T00:46:00+02:00 · Sam Rivera · ui: an outside comment\n\n## Log"
    )
    for _ in range(3):
        _touch(path, doctored)  # the same file keeps arriving (a restore, a re-drop, a copied line)
        mirror.import_file(conn, path)
    bodies = [c["body"] for c in repo.list_comments(conn, tid)]
    assert bodies.count("an outside comment") == 1, bodies
    stored = next(c for c in repo.list_comments(conn, tid) if c["body"] == "an outside comment")
    assert stored["origin"] == "md"  # provenance is where it arrived, not what the file claimed
    assert stored["author"] == "Sam Rivera"


def test_unsigned_line_imports_once(env, mirror: Mirror) -> None:
    """A line written with the ``-`` author sentinel imports once, not once per pass (#123).

    ``-`` is what ``render`` emits for a missing author, so it is the natural thing
    to type; it comes back in as the configured owner, and keying the dedup on the
    raw token meant the stored row could never match the line that created it.
    """
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    doctored = path.read_text(encoding="utf-8").replace(
        "\n## Log", "- 2026-07-31T00:46:00+02:00 · - · md: nobody signed this\n\n## Log"
    )
    for _ in range(3):
        _touch(path, doctored)
        mirror.import_file(conn, path)
    bodies = [c["body"] for c in repo.list_comments(conn, tid)]
    assert bodies.count("nobody signed this") == 1, bodies
    stored = next(c for c in repo.list_comments(conn, tid) if c["body"] == "nobody signed this")
    assert stored["author"] == "Roberto Ferraro"  # the configured owner, per the sample config


def test_deleted_comment_lines_are_not_deletions(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    repo.add_comment(conn, tid, "keep me", author="Sam", origin="ui")
    mirror.export_task(conn, tid)
    text = "\n".join(ln for ln in path.read_text(encoding="utf-8").split("\n") if "keep me" not in ln)
    _touch(path, text)
    mirror.import_tick(conn)
    assert [c["body"] for c in repo.list_comments(conn, tid)] == ["keep me"]
    assert "keep me" in path.read_text(encoding="utf-8")  # restored by the re-export


def test_conflict_db_wins_and_is_recorded_as_event(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    n_comments_before = len(repo.get_task(conn, tid)["comments"])
    # the DB moves the due AFTER the file was written…
    with repo.use_clock(_clock(T0.replace(hour=10))):
        repo.update_task(conn, tid, due="2026-11-11", actor="ui")
    # …and the (older) file is edited to something else
    text = path.read_text(encoding="utf-8").replace("\ndue: null\n", "\ndue: 2026-10-10\n")
    _touch(path, text)
    with repo.use_clock(_clock(T0.replace(hour=11))):
        res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {} and res["conflicts"] == ["import conflict on due: file said 2026-10-10, kept 2026-11-11"]
    task = repo.get_task(conn, tid)
    assert task["due"] == "2026-11-11"
    # the task's own comment thread is untouched — the diagnostic is not a comment
    assert len(task["comments"]) == n_comments_before
    events = repo.list_mirror_events(conn)
    assert len(events) == 1
    assert events[0]["task_id"] == tid and events[0]["kind"] == "conflict" and events[0]["field"] == "due"
    assert events[0]["file_value"] == "2026-10-10" and events[0]["kept_value"] == "2026-11-11"
    # nothing lost, and the file converged to the DB's value
    assert "due: 2026-11-11" in path.read_text(encoding="utf-8")


def test_rejected_value_recorded_as_event_no_comment(env, mirror: Mirror) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    n_comments_before = len(repo.get_task(conn, tid)["comments"])
    text = path.read_text(encoding="utf-8").replace("\nstatus: todo\n", "\nstatus: later\n")
    text = text.replace("\nperson: null\n", "\nperson: Nobody Known\n")
    _touch(path, text)
    res = mirror.import_tick(conn)["imported"][0]
    assert len(res["rejected"]) == 2
    task = repo.get_task(conn, tid)
    assert task["status"] == "todo" and task["person_id"] is None
    assert len(task["comments"]) == n_comments_before
    events = {e["field"]: e for e in repo.list_mirror_events(conn)}
    assert set(events) == {"status", "person"}
    assert events["status"]["kind"] == "rejected" and events["status"]["file_value"] == "later"
    assert events["person"]["kind"] == "rejected" and events["person"]["file_value"] == "'Nobody Known'"
    # the mirror re-exported the file to canonical form after the rejection; an external
    # sync reintroducing the same unresolvable values (the real-world case, fleet-config#713)
    # is a second pass over an *unchanged* bad value — it must refresh, not duplicate, the event
    _touch(path, text)
    res2 = mirror.import_tick(conn)["imported"][0]
    assert len(res2["rejected"]) == 2
    assert len(repo.list_mirror_events(conn)) == 2


def test_malformed_file_is_skipped_not_fatal(env, mirror: Mirror, caplog: pytest.LogCaptureFixture) -> None:
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    _touch(path, f"---\nid: {tid}\ntitle: [oops\n")
    with caplog.at_level("WARNING", logger="src.mirror"):
        r1 = mirror.import_tick(conn)
        r2 = mirror.import_tick(conn)  # same broken version → not re-read, warned once
    assert r1["errors"][0]["path"] == path.name and "unterminated" in r1["errors"][0]["error"]
    assert r2 == {"checked": 1, "imported": [], "errors": []}
    assert sum("skipped" in rec.message for rec in caplog.records) == 1
    st = mirror.status(conn)
    assert st["errors"] == 1 and st["error_files"] == [path.name] and st["errors_total"] == 1
    assert repo.get_task(conn, tid)["title"] == "Bathroom"  # untouched
    # fixing the file clears the error on the next tick
    task = repo.get_task(conn, tid)
    _touch(path, render(task, exported_at="").replace("\ndue: null\n", "\ndue: 2026-12-01\n"))
    r3 = mirror.import_tick(conn)
    assert r3["imported"][0]["applied"] == {"due": "2026-12-01"}
    assert mirror.status(conn)["errors"] == 0


def test_watcher_tick_picks_only_changed_files_and_ignores_strangers(env, mirror: Mirror) -> None:
    conn = env["conn"]
    mirror.export_all(conn)
    n = mirror.status(conn)["files"]
    assert mirror.import_tick(conn) == {"checked": n, "imported": [], "errors": []}
    tid, path = _bathroom(env)
    _touch(path, path.read_text(encoding="utf-8").replace("\ncode: null\n", "\ncode: BATH\n"))
    (env["dir"] / "9999-not-ours.md").write_text("---\nid: 9999\n---\n", encoding="utf-8")
    (env["dir"] / "notes.md").write_text("free text", encoding="utf-8")
    report = mirror.import_tick(conn)
    assert [i["path"] for i in report["imported"]] == [path.name] and report["errors"] == []
    assert repo.get_task(conn, tid)["code"] == "BATH"


def test_export_imports_a_pending_edit_first(env, mirror: Mirror) -> None:
    """A DB write racing a not-yet-imported file edit: the edit is read before the file is rewritten."""
    conn = env["conn"]
    tid, path = _bathroom(env)
    mirror.export_task(conn, tid)
    _touch(path, path.read_text(encoding="utf-8").replace("\n## Log", "- typed while the app wrote\n\n## Log"))
    repo.update_task(conn, tid, priority="high")
    mirror.export_task(conn, tid)
    bodies = [c["body"] for c in repo.list_comments(conn, tid)]
    assert bodies == ["typed while the app wrote"]
    assert "typed while the app wrote" in path.read_text(encoding="utf-8")


def test_disabled_when_dir_not_configured_or_parent_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env) -> None:
    conn = env["conn"]
    m = Mirror(load_config(write_test_config(tmp_path / "c1.json")))
    assert not m.enabled and m.reason == "mirror.dir not configured"
    assert m.export_all(conn) == {"tasks": 0, "written": 0, "removed": 0}
    assert m.import_tick(conn) == {"checked": 0, "imported": [], "errors": []}
    m2 = Mirror(load_config(write_test_config(tmp_path / "c2.json", dir=str(tmp_path / "no" / "such" / "leaf"))))
    assert not m2.enabled and "parent folder missing" in m2.reason
    m3 = Mirror(load_config(write_test_config(tmp_path / "c3.json", dir="{nowhere}/mirror")))
    assert not m3.enabled and "unresolved placeholder" in m3.reason and "{nowhere}" in m3.reason
    # a missing leaf under an existing parent is created
    m4 = Mirror(load_config(write_test_config(tmp_path / "c4.json", dir=str(tmp_path / "fresh-leaf"))))
    assert m4.enabled and (tmp_path / "fresh-leaf").is_dir()
    assert m4.status(conn)["enabled"] and m4.status(conn)["files"] == 0


# ------------------------------------------------- provenance (#126)


def _exported_at(conn: sqlite3.Connection, tid: int) -> str:
    return conn.execute("SELECT exported_at FROM mirror_state WHERE task_id = ?", (tid,)).fetchone()[0]


def test_foreign_export_is_not_an_edit(env, mirror: Mirror) -> None:
    """#126: a file whose ``exported_at`` is newer than ours was rendered by another
    task-os instance — nothing in it is applied, every differing value is a standing
    event, and the file converges back to ours so a later real edit reads as one."""
    conn = env["conn"]
    tid, path = _bathroom(env)
    alex = conn.execute("SELECT id FROM people WHERE name = 'Alex Chen'").fetchone()["id"]
    with repo.use_clock(_clock(T0.replace(hour=8))):
        repo.update_task(conn, tid, person_id=alex, actor="ui")
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    ours = _exported_at(conn, tid)
    # what a second instance renders: its people table lacks Alex Chen, so its copy
    # of the task says null — under its own, later, exported_at
    later = T0.replace(hour=12).isoformat()
    foreign = (
        path.read_text(encoding="utf-8")
        .replace("\nperson: Alex Chen\n", "\nperson: null\n")
        .replace("\ntitle: Bathroom\n", "\ntitle: Someone else's task\n")
        .replace(f"\nexported_at: {ours}\n", f"\nexported_at: {later}\n")
    )
    assert "person: null" in foreign and f"exported_at: {later}" in foreign
    _touch(path, foreign)
    with repo.use_clock(_clock(T0.replace(hour=13))):
        res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {} and res["rejected"] == [] and res["comments_added"] == 0
    assert [c.split(":")[0] for c in res["conflicts"]] == ["import conflict on title", "import conflict on person"]
    assert all("written by another task-os instance" in c for c in res["conflicts"])
    task = repo.get_task(conn, tid)
    assert task["title"] == "Bathroom" and task["person"]["name"] == "Alex Chen"
    assert task["activity"][0]["actor"] == "ui"  # no md row was written
    events = {e["field"]: e for e in repo.list_mirror_events(conn)}
    assert set(events) == {"title", "person"}
    assert (events["person"]["kind"], events["person"]["file_value"], events["person"]["kept_value"]) == ("conflict", "∅", "Alex Chen")
    # the file converged back to ours, under our new stamp, and is not re-read
    text = path.read_text(encoding="utf-8")
    assert "person: Alex Chen" in text and "title: Bathroom" in text and later not in text
    assert mirror.import_tick(conn)["imported"] == []
    # a human blanking the person in *that* file is still a deliberate unassign
    _touch(path, text.replace("\nperson: Alex Chen\n", "\nperson: null\n"))
    res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {"person": None} and res["conflicts"] == []
    assert repo.get_task(conn, tid)["person_id"] is None
    assert "person" not in {e["field"] for e in repo.list_mirror_events(conn)}


def test_foreign_file_under_a_name_we_never_wrote_is_skipped(env, mirror: Mirror) -> None:
    """#126: another instance's rendering of the same id under its own slug is
    skipped (events recorded, our file untouched) and not re-read every tick."""
    conn = env["conn"]
    tid, path = _bathroom(env)
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    stranger = env["dir"] / f"{tid:04d}-someone-elses-task.md"
    stranger.write_text(
        path.read_text(encoding="utf-8")
        .replace("\ntitle: Bathroom\n", "\ntitle: Someone else's task\n")
        .replace(f"\nexported_at: {_exported_at(conn, tid)}\n", f"\nexported_at: {T0.replace(hour=12).isoformat()}\n"),
        encoding="utf-8", newline="\n",
    )
    before = path.stat().st_mtime_ns
    r1 = mirror.import_tick(conn)
    assert r1["imported"] == [] and [e["path"] for e in r1["errors"]] == [stranger.name]
    assert "written by another task-os instance" in r1["errors"][0]["error"]
    assert repo.get_task(conn, tid)["title"] == "Bathroom"
    assert path.stat().st_mtime_ns == before and stranger.exists()
    assert [(e["field"], e["file_value"]) for e in repo.list_mirror_events(conn)] == [("title", "Someone else's task")]
    assert mirror.status(conn)["error_files"] == [stranger.name]
    assert mirror.import_tick(conn) == {"checked": 2, "imported": [], "errors": []}
    # removing the stranger clears it from the skipped list on the next tick
    stranger.unlink()
    mirror.import_tick(conn)
    assert mirror.status(conn)["error_files"] == []


def test_stale_copy_of_our_file_is_judged_against_its_own_snapshot(env, mirror: Mirror) -> None:
    """A restored older version of our own file (``exported_at`` older than ours) is
    an edit made against *that* snapshot: what the DB changed since it wins."""
    conn = env["conn"]
    tid, path = _bathroom(env)
    with repo.use_clock(_clock(T0)):
        mirror.export_task(conn, tid)
    old = path.read_text(encoding="utf-8")  # the 09:00 rendering — due null, code null
    with repo.use_clock(_clock(T0.replace(hour=10))):
        repo.update_task(conn, tid, due="2026-11-11", actor="ui")
    with repo.use_clock(_clock(T0.replace(hour=11))):
        mirror.export_task(conn, tid)
    # a sync client brings the 09:00 version back, with a code the user had typed into it
    _touch(path, old.replace("\ncode: null\n", "\ncode: BATH\n"))
    with repo.use_clock(_clock(T0.replace(hour=12))):
        res = mirror.import_tick(conn)["imported"][0]
    assert res["applied"] == {"code": "BATH"}
    assert res["conflicts"] == ["import conflict on due: file said ∅, kept 2026-11-11"]
    assert repo.get_task(conn, tid)["due"] == "2026-11-11"


def test_overridden_db_only_mirrors_beside_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#126: an instance on ``TASKOS_DB_PATH`` (a harness, a scratch walk) never gets
    the mirror or the backup into a folder that is not next to that database."""
    from src.backup import BackupScheduler

    db = tmp_path / "instance" / "tasks.db"
    db.parent.mkdir()
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(db))
    shared = tmp_path / "shared"  # stands in for the real synced folder
    shared.mkdir()
    cfg = load_config(write_test_config(tmp_path / "c.json", dir=str(shared / "mirror"), backup_dir=str(shared / "backup")))
    m = Mirror(cfg)
    assert not m.enabled and "outside the TASKOS_DB_PATH folder" in m.reason and m.reason.startswith("mirror.dir:")
    b = BackupScheduler(cfg)
    assert not b.enabled and "outside the TASKOS_DB_PATH folder" in b.reason and b.reason.startswith("mirror.backup_dir:")
    assert not (shared / "mirror").exists() and not (shared / "backup").exists()
    beside = load_config(write_test_config(tmp_path / "c2.json", dir=str(db.parent / "mirror"), backup_dir=str(db.parent / "backup")))
    assert Mirror(beside).enabled and BackupScheduler(beside).enabled


def test_committed_sample_never_enables_mirror_or_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    """#126: a checkout without its own config (a fresh clone, a worktree) reads the
    sample, whose placeholders resolve to a real synced folder — both services stay off."""
    from src.config import CONFIG_SAMPLE_PATH

    cfg = load_config(CONFIG_SAMPLE_PATH)
    assert cfg.mirror.dir == "" and cfg.mirror.backup_dir == ""
    assert cfg.placeholders.get("onedrive") and cfg.issues.owner  # the rest of the sample still loads
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(CONFIG_SAMPLE_PATH))
    assert Mirror(load_config()).reason == "mirror.dir not configured"


# ------------------------------------------------------------- schema v4


def test_migration_v4_adds_mirror_state_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src import schema

    db = tmp_path / "v3.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "BEGIN;" + schema.MIGRATIONS[1] + schema.MIGRATIONS[2] + schema.MIGRATIONS[3]
        + "INSERT INTO settings VALUES ('schema_version', '3'); COMMIT;"
    )
    conn.close()
    assert dbmod.init_db(db) == schema.SCHEMA_VERSION
    conn = dbmod.connect(db)
    try:
        assert "mirror_state" in schema.table_names(conn)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(mirror_state)")]
        assert cols == ["task_id", "path", "exported_at", "file_mtime_ns", "content_hash"]
        n = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        assert schema.migrate(conn) == schema.SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == n
    finally:
        conn.close()


# ------------------------------------------------------------ API + CLI


def test_api_status_and_on_demand_runs(env) -> None:
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        st = c.get("/api/status").json()
        assert st["mirror"]["enabled"] is True and st["mirror"]["dir"] == str(env["dir"])
        assert st["backup"]["enabled"] is True and st["backup"]["next_run"]
        # the lifespan thread already did the initial export; an explicit run rewrites nothing
        r = c.post("/api/mirror/export").json()
        assert r["tasks"] > 0
        assert st["mirror"]["watching"] is True
        r = c.post("/api/mirror/import").json()
        assert r["errors"] == []
        b = c.post("/api/backup").json()
        assert b["file"].startswith("tasks-") and (Path(b["dir"]) / b["file"]).exists()
    assert len(list(env["dir"].glob("*.md"))) == env["conn"].execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


def test_api_status_reports_not_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.webapp.server import create_app

    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "t.db"))
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(write_test_config(tmp_path / "c.json")))
    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        st = c.get("/api/status").json()
        assert st["mirror"] == {**st["mirror"], "enabled": False, "reason": "mirror.dir not configured", "files": None}
        assert st["backup"]["enabled"] is False and st["backup"]["reason"] == "mirror.backup_dir not configured"
        r = c.post("/api/mirror/export")
        assert r.status_code == 409 and r.json()["error"]["code"] == "mirror_disabled"
        assert c.post("/api/backup").status_code == 409


def test_cli_mirror_and_backup_local(env, capsys: pytest.CaptureFixture[str]) -> None:
    from src.cli import main

    assert main(["--local", "mirror", "export"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("mirror: ") and "written" in out
    assert main(["--local", "mirror", "status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["mirror"]["enabled"] and st["mirror"]["files"] > 0
    assert main(["--local", "mirror"]) == 0  # status is the default action
    assert "mirror   enabled" in capsys.readouterr().out
    assert main(["--local", "backup", "--json"]) == 0
    b = json.loads(capsys.readouterr().out)
    assert Path(b["path"]).exists()
    # a local write mirrors the touched task synchronously (no app running)
    assert main(["--local", "add", "From the CLI", "--due", "2026-09-09"]) == 0
    capsys.readouterr()
    conn = env["conn"]
    tid = conn.execute("SELECT id FROM tasks WHERE title = 'From the CLI'").fetchone()["id"]
    assert (env["dir"] / file_name(tid, "From the CLI")).exists()
    assert main(["--local", "mirror", "import"]) == 0
    assert capsys.readouterr().out.startswith("mirror: checked")


def test_cli_reports_not_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from src.cli import main

    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "t.db"))
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(write_test_config(tmp_path / "c.json")))
    assert main(["--local", "mirror", "status"]) == 0
    out = capsys.readouterr().out
    assert "mirror   not configured — mirror.dir not configured" in out
    assert "backup   not configured" in out
    assert main(["--local", "mirror", "export"]) == 1
    assert "mirror.dir not configured" in capsys.readouterr().err
    assert main(["--local", "backup", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "backup_disabled"


def test_mirror_module_constants() -> None:
    assert mirror_mod.MD_ACTOR == "md" and mirror_mod.POLL_S == 2.0 and mirror_mod.DEBOUNCE_S == 1.0
