"""``src/tasks_repo.py`` â€” comments, links, issue refs, people, list filters,
search, bulk edits, the done journal and the snooze rule."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from src import db as dbmod
from src import tasks_repo as repo
from tests.tasks._support import (
    ANCHOR,
    _at,
    _fields,
)

# ------------------------------------------------------------ comments

def test_comments_thread_order_and_origin(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Talk")
    ts = iter([
        datetime(2026, 8, 17, 9, 0), datetime(2026, 8, 17, 9, 5), datetime(2026, 8, 17, 9, 5),
    ])
    with repo.use_clock(lambda: next(ts).astimezone()):
        repo.add_comment(conn, t["id"], "first", author="a", origin="cli")
        repo.add_comment(conn, t["id"], "second", author="b")
        repo.add_comment(conn, t["id"], "third (same second)", author="b", origin="md")
    thread = repo.list_comments(conn, t["id"])
    assert [c["body"] for c in thread] == ["first", "second", "third (same second)"]
    assert [c["origin"] for c in thread] == ["cli", "ui", "md"]
    assert thread[0]["author"] == "a"
    with pytest.raises(repo.ValidationError):
        repo.add_comment(conn, t["id"], "  ")
    with pytest.raises(repo.ValidationError):
        repo.add_comment(conn, t["id"], "x", origin="fax")
    with pytest.raises(repo.NotFound):
        repo.add_comment(conn, 999, "x")


def test_comment_edit_keeps_attribution_and_delete_is_task_scoped(conn: sqlite3.Connection) -> None:
    """#155 — an edit corrects the text only; both writes are scoped to the task."""
    t = repo.create_task(conn, "Talk")
    other = repo.create_task(conn, "Elsewhere")
    with repo.use_clock(lambda: datetime(2026, 8, 17, 9, 0).astimezone()):
        c = repo.add_comment(conn, t["id"], "recieved reply", author="a", origin="cli")

    edited = repo.update_comment(conn, t["id"], c["id"], "  received reply + answered  ")
    assert edited["body"] == "received reply + answered"          # trimmed
    assert (edited["author"], edited["ts"], edited["origin"]) == (c["author"], c["ts"], c["origin"])
    assert [x["body"] for x in repo.list_comments(conn, t["id"])] == ["received reply + answered"]

    with pytest.raises(repo.ValidationError):
        repo.update_comment(conn, t["id"], c["id"], "   ")
    with pytest.raises(repo.NotFound):                            # right id, wrong task
        repo.update_comment(conn, other["id"], c["id"], "hijack")
    with pytest.raises(repo.NotFound):
        repo.delete_comment(conn, other["id"], c["id"])
    assert repo.list_comments(conn, t["id"])                      # neither write landed

    repo.delete_comment(conn, t["id"], c["id"])
    assert repo.list_comments(conn, t["id"]) == []
    with pytest.raises(repo.NotFound):
        repo.delete_comment(conn, t["id"], c["id"])


def test_last_comment_follows_thread_order_not_max_id(conn: sqlite3.Connection) -> None:
    """A historical import (``add_comment(..., ts=...)`` — the path the Notion
    importer and ``Mirror._apply_comments`` use) can land a newer id with an
    older ts. ``list_tasks``' ``last_comment`` (via ``_enrich_list``) must
    follow thread order (``ts, id``, the same ordering ``list_comments``
    uses) — not a bare ``MAX(id)``."""

    def _ts_at(dt: datetime) -> str:
        with repo.use_clock(lambda: dt.astimezone()):
            return repo.now_iso()

    t_early = _ts_at(datetime(2026, 8, 17, 9, 0, 0))
    t_mid = _ts_at(datetime(2026, 8, 17, 9, 30, 0))

    t = repo.create_task(conn, "Talk")
    repo.add_comment(conn, t["id"], "early", ts=t_early)  # id=1, ts=t_early
    with repo.use_clock(lambda: datetime(2026, 8, 17, 10, 0, 0).astimezone()):
        repo.add_comment(conn, t["id"], "latest by time", author="b")  # id=2, ts=t_late
    # Historical import lands after "latest by time" in id order, but its ts
    # sits between the other two — this is the newer-id/older-ts case.
    repo.add_comment(conn, t["id"], "historical mid", ts=t_mid)  # id=3, ts=t_mid

    thread = repo.list_comments(conn, t["id"])
    assert [c["body"] for c in thread] == ["early", "historical mid", "latest by time"]

    items = repo.list_tasks(conn)
    item = next(i for i in items if i["id"] == t["id"])
    assert item["last_comment"]["body"] == "latest by time"


# ---------------------------------------------------------------- links

def test_links_add_list_remove(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Docs")
    lk = repo.add_link(conn, t["id"], "https://example.com", label="site", kind="web")
    repo.add_link(conn, t["id"], "{onedrive}/x", kind="folder")
    assert [x["kind"] for x in repo.list_links(conn, t["id"])] == ["web", "folder"]
    repo.remove_link(conn, t["id"], lk["id"])
    assert len(repo.list_links(conn, t["id"])) == 1
    with pytest.raises(repo.NotFound):
        repo.remove_link(conn, t["id"], lk["id"])
    with pytest.raises(repo.ValidationError):
        repo.add_link(conn, t["id"], "x", kind="carrier-pigeon")


def test_links_rename(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Docs")
    lk = repo.add_link(conn, t["id"], "https://example.com", label="old label", kind="web")
    renamed = repo.rename_link(conn, t["id"], lk["id"], "new label")
    assert renamed["label"] == "new label"
    assert renamed["url"] == "https://example.com" and renamed["kind"] == "web"
    cleared = repo.rename_link(conn, t["id"], lk["id"], "  ")
    assert cleared["label"] is None
    with pytest.raises(repo.NotFound):
        repo.rename_link(conn, t["id"], lk["id"] + 999, "x")


# ------------------------------------------------------- coding / issue

def test_coding_iff_issue_ref(conn: sqlite3.Connection) -> None:
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "Bug", type="coding")
    t = repo.create_task(conn, "Bug")
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, t["id"], type="coding")
    c = repo.set_issue_ref(conn, t["id"], provider="github", repo="example/repo", number=7, actor="me")
    assert c["type"] == "coding" and c["issue_ref"]["number"] == 7
    assert ("type", "task", "coding") in _fields(c["activity"])
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, t["id"], type="note")   # still has an issue
    back = repo.remove_issue_ref(conn, t["id"])
    assert back["type"] == "task" and back["issue_ref"] is None
    with pytest.raises(repo.NotFound):
        repo.remove_issue_ref(conn, t["id"])


# --------------------------------------------------------------- people

def test_people_crud_and_task_pointer(conn: sqlite3.Connection) -> None:
    p = repo.create_person(conn, "Sam", email="s@example.com")
    t = repo.create_task(conn, "Call", person_id=p["id"], status="todo")
    assert t["person"] == {"id": p["id"], "name": "Sam"}
    assert repo.get_person(conn, p["id"])["open_tasks"] == 1
    assert repo.update_person(conn, p["id"], name="Sam R.")["name"] == "Sam R."
    assert [x["id"] for x in repo.list_tasks(conn, person_id=p["id"])] == [t["id"]]
    with pytest.raises(repo.NotFound):
        repo.create_task(conn, "x", person_id=999)
    repo.delete_person(conn, p["id"])
    assert repo.get_task(conn, t["id"])["person_id"] is None
    with pytest.raises(repo.NotFound):
        repo.get_person(conn, p["id"])


# ---------------------------------------------------------- list / due

def test_list_filters(conn: sqlite3.Connection, seeded: dict, frozen: None) -> None:
    today = {t["title"] for t in repo.list_tasks(conn, due="today")}
    assert {"School enrolment forms", "Call the plumber back", "Practice scales"} <= today
    overdue = {t["title"] for t in repo.list_tasks(conn, due="overdue")}
    assert {"Fix leaking tap", "Return library books", "Repair fence"} <= overdue
    assert "Buy a birthday gift" not in overdue          # done → hidden
    week = repo.list_tasks(conn, due="week")
    assert all(ANCHOR.isoformat() <= t["due"] <= "2026-08-24" for t in week)
    assert [t["title"] for t in repo.list_tasks(conn, status="standby", project=seeded["home"])] == [
        "Plant tomatoes", "Garden",
    ]
    assert {t["title"] for t in repo.list_tasks(conn, parent_id="root")} >= {"Home renovation", "Learning"}
    assert [t["type"] for t in repo.list_tasks(conn, type="coding")] == ["coding"]
    assert [t["title"] for t in repo.list_tasks(conn, type="note")] == ["Reading list"]
    with pytest.raises(repo.ValidationError):
        repo.list_tasks(conn, status="later")


def test_delete_cascades_subtree(conn: sqlite3.Connection, seeded: dict) -> None:
    before = repo.counts(conn)
    r = repo.delete_task(conn, seeded["kitchen"])
    assert r["deleted"] == 4                                    # kitchen + 3 children
    after = repo.counts(conn)
    assert before["tasks"] - after["tasks"] == 4
    assert after["links"] == before["links"] - 2               # kitchen's two links
    with pytest.raises(repo.NotFound):
        repo.get_task(conn, seeded["quotes"])


def test_bulk_delete_names_the_gone_and_folds_a_child_into_its_parent(
    conn: sqlite3.Connection, seeded: dict
) -> None:
    """#121: the detail carries the whole subtree's size (what a delete takes),
    and the bulk twin reports per id — a ticked child whose parent went first
    is not a failure, an id that was never there is a named one."""
    kitchen, quotes = seeded["kitchen"], seeded["quotes"]
    assert repo.get_task(conn, kitchen)["descendant_count"] == 3
    assert repo.get_task(conn, kitchen)["child_count"] == 3
    assert repo.get_task(conn, quotes)["descendant_count"] == 0
    before = repo.counts(conn)["tasks"]
    rows = repo.bulk_delete(conn, [kitchen, quotes, kitchen, 999_999])
    assert [(r["id"], r["ok"], r.get("deleted")) for r in rows] == [
        (kitchen, True, 4),
        (quotes, True, 0),          # went with its parent — not a failure
        (999_999, False, None),     # duplicates collapse; the unknown id is named
    ]
    assert rows[2]["error"]["code"] == "not_found"
    assert before - repo.counts(conn)["tasks"] == 4


# --------------------------------------------------------------- search

def test_search_title_description_and_comments(conn: sqlite3.Connection, seeded: dict) -> None:
    by_title = repo.search(conn, "worktop")
    assert [h["id"] for h in by_title] == [seeded["worktop"]]
    assert by_title[0]["matched_in"] == "title" and "[worktop]" in by_title[0]["snippet"]
    assert [c["title"] for c in by_title[0]["breadcrumb"]] == ["Home renovation", "Kitchen"]

    by_desc = repo.search(conn, "balcony")
    assert [h["id"] for h in by_desc] == [seeded["bot"]]
    assert by_desc[0]["matched_in"] == "description"

    by_comment = repo.search(conn, "washer")
    assert [h["id"] for h in by_comment] == [seeded["tap"]]
    assert by_comment[0]["matched_in"] == "comment" and "[washer]" in by_comment[0]["snippet"]

    # prefix + punctuation-safe
    assert seeded["watering"] in {h["id"] for h in repo.search(conn, "garden-bot#12")}
    assert seeded["quotes"] in {h["id"] for h in repo.search(conn, "quot")}
    assert repo.search(conn, "") == []
    assert repo.search(conn, "zzzznothing") == []
    # a hit reaches list_tasks via q=
    assert [t["id"] for t in repo.list_tasks(conn, q="washer")] == [seeded["tap"]]


def test_a_bracket_in_a_title_does_not_decide_where_a_search_matched(
    conn: sqlite3.Connection,
) -> None:
    """#440 — ``[`` is both the highlight mark and was the "the title matched" test.

    A title that merely contains ``[`` was always reported as a title hit with
    its unmarked title as the snippet, even when only the description matched.
    """
    t = repo.create_task(conn, "[WIP] fix tap", description="the washer is worn out")

    by_desc = repo.search(conn, "washer")
    assert [h["id"] for h in by_desc] == [t["id"]]
    assert by_desc[0]["matched_in"] == "description"
    assert "[washer]" in by_desc[0]["snippet"]

    by_title = repo.search(conn, "fix")
    assert by_title[0]["matched_in"] == "title"
    # The title's own brackets survive; the match is marked on top of them.
    assert by_title[0]["snippet"] == "[WIP] [fix] tap"


def test_fts_follows_updates_and_deletes(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Alpha", description="first text")
    assert repo.search(conn, "alpha")
    repo.update_task(conn, t["id"], title="Beta")
    assert not repo.search(conn, "alpha") and repo.search(conn, "beta")
    c = repo.add_comment(conn, t["id"], "unique gamma word")
    assert repo.search(conn, "gamma")[0]["matched_in"] == "comment"
    repo.update_comment(conn, t["id"], c["id"], "unique delta word")
    assert not repo.search(conn, "gamma") and repo.search(conn, "delta")[0]["matched_in"] == "comment"
    repo.delete_comment(conn, t["id"], c["id"])
    assert not repo.search(conn, "delta")
    repo.delete_task(conn, t["id"])
    assert not repo.search(conn, "beta")


def test_dates_stay_iso_and_clock_pinned(conn: sqlite3.Connection, frozen: None) -> None:
    t = repo.create_task(conn, "Clock", due=date(2026, 9, 1))
    assert t["due"] == "2026-09-01"
    assert t["created_at"].startswith("2026-08-17T09:00:00")


# ----------------------------------------------------------------- bulk

def test_bulk_update_applies_to_every_id(conn: sqlite3.Connection) -> None:
    ids = [repo.create_task(conn, f"T{n}")["id"] for n in range(3)]
    results = repo.bulk_update(conn, ids, actor="me", status="standby")
    assert [r["id"] for r in results] == ids
    assert all(r["ok"] for r in results)
    assert {r["task"]["status"] for r in results} == {"standby"}
    # the same activity trail a one-by-one edit would leave
    assert _fields(repo.get_task(conn, ids[0])["activity"])[0] == ("status", "todo", "standby")


def test_bulk_update_reports_the_failed_id_and_applies_the_rest(conn: sqlite3.Connection) -> None:
    good = [repo.create_task(conn, f"T{n}")["id"] for n in range(2)]
    results = repo.bulk_update(conn, [good[0], 4242, good[1]], status="todo")
    assert [(r["id"], r["ok"]) for r in results] == [(good[0], True), (4242, False), (good[1], True)]
    assert results[1]["error"]["code"] == "not_found"
    # the bad id in the middle does NOT stop the batch
    assert [repo.get_task(conn, i)["status"] for i in good] == ["todo", "todo"]


def test_bulk_update_surfaces_a_validation_error_per_id(conn: sqlite3.Connection) -> None:
    ids = [repo.create_task(conn, f"T{n}")["id"] for n in range(2)]
    results = repo.bulk_update(conn, ids, due="not-a-date")
    assert [r["ok"] for r in results] == [False, False]
    assert {r["error"]["code"] for r in results} == {"validation_error"}


def test_bulk_complete_rolls_recurring_and_closes_the_rest(
    conn: sqlite3.Connection, frozen: None
) -> None:
    # `frozen` is load-bearing, not decoration: a roll lands on the first
    # occurrence after *both* the old due date and today, so an unpinned clock
    # makes the expected date true only until the real today passes it.
    rolling = repo.create_task(conn, "Weekly", recurrence="weekly", due="2026-08-31", status="todo")["id"]
    oneoff = repo.create_task(conn, "One-off", due="2026-08-31", status="todo")["id"]
    results = repo.bulk_update(conn, [rolling, oneoff], actor="me", complete=True)
    assert all(r["ok"] for r in results)
    # the recurring task rolls and stays open; the plain one closes — exactly
    # what the row select's `complete` does per task (#54)
    assert results[0]["task"]["due"] == "2026-09-07"
    assert results[0]["task"]["status"] == "todo"
    assert results[1]["task"]["status"] == "done" and results[1]["task"]["done_at"]


def test_bulk_update_collapses_duplicate_ids(conn: sqlite3.Connection, frozen: None) -> None:
    rolling = repo.create_task(conn, "Weekly", recurrence="weekly", due="2026-08-31")["id"]
    results = repo.bulk_update(conn, [rolling, rolling, rolling], complete=True)
    assert [r["id"] for r in results] == [rolling]
    assert repo.get_task(conn, rolling)["due"] == "2026-09-07"    # rolled once, not three times


# ------------------------------------------------------------ done journal (#102)

def test_done_window_is_local_midnight_and_newest_first(conn: sqlite3.Connection, seeded: dict) -> None:
    """#102 — ``done_from`` / ``done_to`` bound the closing day at local
    midnight (the ``done_on`` rule), a window flips the order to newest
    closing first, and cancelling stamps the same closed-at column."""
    with _at(2026, 8, 16, 23, 59):
        repo.done(conn, seeded["library"])
    with _at(2026, 8, 17, 0, 0):
        repo.done(conn, seeded["callback"])
    with _at(2026, 8, 17, 12, 0):
        cancelled = repo.set_status(conn, seeded["inbox3"], "cancelled", actor="me")
    assert cancelled["done_at"].startswith("2026-08-17T12:00")
    closed = ["done", "cancelled"]
    day = repo.list_tasks(conn, status=closed, done_from="2026-08-17", done_to="2026-08-17")
    assert [t["id"] for t in day] == [seeded["inbox3"], seeded["callback"]]    # 23:59 the day before is out
    both = repo.list_tasks(conn, status=closed, done_from="2026-08-16", done_to="2026-08-17")
    # …then the 16th: the library book at 23:59, and the seed's two "yesterday" closings
    assert [t["id"] for t in both] == [seeded["inbox3"], seeded["callback"], seeded["library"], seeded["kettle"], seeded["lease"]]
    # the seed's own closed days (anchor−1, −2, −9): a week holds seven, the
    # week before starts with the drill — newest closing first throughout
    week = [t["title"] for t in repo.list_tasks(conn, status=closed, done_from="2026-08-11", done_to="2026-08-17")]
    assert week == [
        "Compare phone plans", "Call the plumber back", "Return library books",
        "Descale the kettle", "Send the lease renewal",
        "Fix the watering timezone bug", "Cancel the unused streaming plan",
    ]
    older = repo.list_tasks(conn, status=closed, done_to="2026-08-10")
    assert older[0]["title"] == "Return the borrowed drill"
    assert "Sell the old bikes" in [t["title"] for t in older]      # created cancelled → stamped too
    # reopening clears the stamp — a reopened task has no closing day
    assert repo.set_status(conn, seeded["inbox3"], "todo")["done_at"] is None
    with pytest.raises(repo.ValidationError):
        repo.list_tasks(conn, done_from="whenever")


def test_a_hand_made_task_starts_in_to_do(conn: sqlite3.Connection) -> None:
    """The default is To Do, not Inbox (#148).

    Inbox is the arrivals tray for what came in on its own; a task somebody
    typed has already been triaged by the act of writing it. Every hand-driven
    surface inherits this one default, which is what keeps the CLI and the UI
    from disagreeing about what "no status given" means.
    """
    assert repo.create_task(conn, "Renew passport")["status"] == "todo"
    assert repo.create_task(conn, "Renew passport", status="")["status"] == "todo"
    assert repo.create_task(conn, "Renew passport", status=None)["status"] == "todo"
    # …and saying otherwise still wins.
    assert repo.create_task(conn, "Triage me", status="inbox")["status"] == "inbox"


def test_a_captured_task_still_lands_in_the_inbox(conn: sqlite3.Connection) -> None:
    """Capture names Inbox itself rather than inheriting the create default.

    This is the guard that matters: flipping :data:`DEFAULT_STATUS` to ``todo``
    must not quietly move flagged emails and marked WhatsApp messages out of
    the tray they exist to fill. A caller with no opinion can say so as an
    absent key, a ``None`` or a blank, and all three mean Inbox here.
    """
    for i, fields in enumerate([{}, {"status": None}, {"status": ""}]):
        task, outcome = repo.capture_task(
            conn, external_id=f"email:{i}", title="A flagged email", actor="sync", **fields,
        )
        assert (outcome, task["status"]) == ("created", "inbox"), fields
    # A source that does have an opinion is still obeyed.
    task, _ = repo.capture_task(
        conn, external_id="email:opinion", title="Already triaged", actor="sync", status="todo",
    )
    assert task["status"] == "todo"


def test_an_import_reads_a_blank_status_as_the_create_default(conn: sqlite3.Connection) -> None:
    """``import_diff``'s "empty ≡ default" has to mean the *same* default.

    It decides whether an incoming field differs from the stored row, so if it
    kept saying "inbox" while creates said "todo", a re-import of a task with
    no status would look like a change on every pass.
    """
    stored = repo.create_task(conn, "From elsewhere")
    assert repo.import_diff(stored, status="") == {}
    assert repo.import_diff(stored, status="todo") == {}
    assert repo.import_diff(stored, status="inbox") == {"status": "inbox"}


def test_list_tasks_costs_the_same_queries_whatever_the_row_count(tmp_path: Path) -> None:
    """The list path prefetches, so its query count is a property of the page,
    not of its length (#186).

    ``_summary`` used to issue five lookups per row while ``_enrich_list``,
    right beside it, argued the opposite case in its own docstring — one module
    answering the same question two ways. This pins the answer: ten times the
    rows, the same number of queries.
    """

    class Counting(sqlite3.Connection):
        n = 0

        def execute(self, *args: object, **kwargs: object):  # type: ignore[override]
            type(self).n += 1
            return super().execute(*args, **kwargs)

    def queries_for(rows: int) -> int:
        path = tmp_path / f"count-{rows}.db"
        dbmod.init_db(path)
        setup = dbmod.connect(path)
        person = repo.create_person(setup, "Assignee")["id"]
        for i in range(rows):
            task = repo.create_task(setup, f"Task {i}", person_id=person)
            repo.add_link(setup, task["id"], "https://example.invalid/ai", kind="ai")
        setup.close()
        counting = sqlite3.connect(path, factory=Counting)
        counting.row_factory = sqlite3.Row
        Counting.n = 0
        items = repo.list_tasks(counting, include_closed=True)
        counting.close()
        assert len(items) == rows
        return Counting.n

    assert queries_for(3) == queries_for(30)


@pytest.mark.parametrize(("url", "kind"), [
    ("{onedrive}/areas/x", "folder"),
    ("mailto:someone@example.com", "email"),
    ("https://claude.ai/code/session_01abc", "ai"),
    ("https://chatgpt.com/c/1", "ai"),
    ("https://gemini.google.com/app/1", "ai"),
    ("https://github.com/copilot", "ai"),
    ("https://github.com/owner/repo/issues/12", "issue"),
    ("https://example.com/claude.ai/", "web"),
    ("https://example.com", "web"),
])
def test_infer_link_kind(url: str, kind: str) -> None:
    """#257: the one server-side rule every link without a kind goes through."""
    assert repo.infer_link_kind(url) == kind


def test_add_link_without_kind_infers_it(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Chat")
    assert repo.add_link(conn, t["id"], "https://chatgpt.com/c/9")["kind"] == "ai"
    assert repo.add_link(conn, t["id"], "https://example.com", kind="folder")["kind"] == "folder"


# ------------------------------------------- snooze never strands a task (#486)

def test_snoozing_a_task_due_today_moves_its_due_with_it(conn: sqlite3.Connection, frozen) -> None:
    """#486: the Board's snooze sets only `starts`; a task due today then hid
    until tomorrow and came back overdue. `due` now travels with it."""
    t = repo.create_task(conn, "Pay the invoice", status="todo", due="2026-08-17")
    snoozed = repo.set_starts(conn, t["id"], "2026-08-18", actor="me")
    assert (snoozed["starts"], snoozed["due"]) == ("2026-08-18", "2026-08-18")
    assert ("due", "2026-08-17", "2026-08-18") in _fields(snoozed["activity"])
    # the task is asleep today and awake, on its due day, tomorrow
    assert t["id"] not in [r["id"] for r in repo.list_tasks(conn, deferred="hide")]
    with repo.use_clock(lambda: datetime(2026, 8, 18, 9, 0, 0).astimezone()):
        awake = [r for r in repo.list_tasks(conn, deferred="hide") if r["id"] == t["id"]]
    assert awake and awake[0]["due"] == "2026-08-18"


def test_snooze_leaves_a_later_due_and_an_undated_task_alone(conn: sqlite3.Connection) -> None:
    later = repo.create_task(conn, "Later", due="2026-09-30")
    assert repo.set_starts(conn, later["id"], "2026-08-18")["due"] == "2026-09-30"
    same_day = repo.create_task(conn, "Same day", due="2026-08-18")
    assert repo.set_starts(conn, same_day["id"], "2026-08-18")["due"] == "2026-08-18"
    undated = repo.create_task(conn, "Undated")
    snoozed = repo.set_starts(conn, undated["id"], "2026-08-18")
    assert (snoozed["starts"], snoozed["due"]) == ("2026-08-18", None)
    assert "due" not in [f for f, _, _ in _fields(snoozed["activity"])]


def test_snooze_rule_covers_update_bulk_and_respects_an_explicit_due(conn: sqlite3.Connection) -> None:
    a = repo.create_task(conn, "A", due="2026-08-17")
    b = repo.create_task(conn, "B", due="2026-08-17")
    rows = repo.bulk_update(conn, [a["id"], b["id"]], starts="2026-08-20")
    assert [r["task"]["due"] for r in rows] == ["2026-08-20", "2026-08-20"]
    # a patch that names `due` itself is the caller's own pair — never rewritten
    c = repo.create_task(conn, "C", due="2026-08-17")
    kept = repo.update_task(conn, c["id"], starts="2026-08-20", due="2026-08-19")
    assert (kept["starts"], kept["due"]) == ("2026-08-20", "2026-08-19")
    # clearing the snooze does not touch due
    cleared = repo.update_task(conn, a["id"], starts=None)
    assert cleared["due"] == "2026-08-20"
