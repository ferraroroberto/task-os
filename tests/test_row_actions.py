"""``actions.js`` — the one table of row actions the keys, the status select and the row menu read (#311).

Each action's ``plan`` (what to write) and ``invert`` (the undo) is hand-kept
JS, and the undo is only ever exercised by a user who changed their mind — so
this loads the module under node and holds every action to its contract: the
plan writes through the bulk endpoint's fields, and the inverse puts back each
task's *own* prior value, grouped so one bulk call carries one value.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "actions.js"
NODE = shutil.which("node")

# Reads [[action id, method, tasks, arg, after], …] on stdin and prints each
# result as one JSON array; "keys" lists the table's ids, keys and labels.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([id, method, tasks, arg, after]) => {
  if (method === 'keys') return mod.ACTIONS.map((a) => [a.id, a.key, a.label]);
  const a = mod.actionById(id);
  if (!a) return null;
  return method === "applies" ? a.applies(tasks) : a[method](tasks, arg, after);
});
process.stdout.write(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")


def _call_js(calls: list[list]) -> list:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps(calls), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


PLAIN = {"id": 1, "status": "todo", "due": "2026-10-01", "starts": None, "priority": "low", "recurrence": None}
WEEKLY = {"id": 2, "status": "inbox", "due": "2026-10-02", "starts": None, "priority": "none", "recurrence": "weekly"}
OTHER = {"id": 3, "status": "standby", "due": None, "starts": "2026-10-09", "priority": "high", "recurrence": None}


def test_the_table_keeps_its_ids_and_keys() -> None:
    """Keys, palette ids and the coming Settings choices all name actions by id."""
    (table,) = _call_js([[None, "keys", None, None, None]])
    assert [(a[0], a[1]) for a in table] == [
        ("complete", "e"), ("reopen", None), ("change-date", "d"), ("due-tomorrow", "t"),
        ("due-next-week", "w"), ("snooze", "s"), ("priority", "p"), ("status-inbox", "1"),
        ("status-todo", "2"), ("status-standby", "3"), ("status-cancelled", None),
    ]


def test_plans_write_one_group_through_the_bulk_fields() -> None:
    tasks = [PLAIN, WEEKLY]
    got = _call_js([
        ["complete", "plan", tasks, None, None],
        ["due-tomorrow", "plan", tasks, None, None],
        ["due-next-week", "plan", tasks, None, None],
        ["snooze", "plan", tasks, "this weekend", None],
        ["status-standby", "plan", tasks, None, None],
    ])
    assert got == [
        [{"ids": [1, 2], "changes": {"status": "complete"}}],
        [{"ids": [1, 2], "changes": {"due": "tomorrow"}}],
        [{"ids": [1, 2], "changes": {"due": "next week"}}],
        [{"ids": [1, 2], "changes": {"starts": "this weekend"}}],
        [{"ids": [1, 2], "changes": {"status": "standby"}}],
    ]


def test_the_menu_offers_only_what_applies() -> None:
    """The row menu hides an action that would do nothing or does not fit (#311)."""
    done = dict(PLAIN, status="done")
    ids = ["complete", "reopen", "change-date", "snooze", "priority", "status-todo", "status-cancelled"]
    got = _call_js([[i, "applies", t, None, None] for t in (PLAIN, done) for i in ids])
    assert dict(zip(ids, got[:7], strict=True)) == {
        "complete": True, "reopen": False, "change-date": True, "snooze": True,
        "priority": True, "status-todo": False, "status-cancelled": True,     # already todo
    }
    assert dict(zip(ids, got[7:], strict=True)) == {
        "complete": False, "reopen": True, "change-date": False, "snooze": False,
        "priority": True, "status-todo": False, "status-cancelled": False,   # closed: Reopen instead
    }


def test_change_date_writes_the_phrase_or_clears_it() -> None:
    got = _call_js([
        ["change-date", "plan", [PLAIN], "this weekend", None],
        ["change-date", "plan", [PLAIN], None, None],
        ["change-date", "message", [PLAIN], "this weekend", [dict(PLAIN, due="2026-10-10")]],
        ["change-date", "message", [PLAIN], None, [dict(PLAIN, due=None)]],
    ])
    assert got[0] == [{"ids": [1], "changes": {"due": "this weekend"}}]
    assert got[1] == [{"ids": [1], "changes": {"due": None}}]
    assert got[2] == "Due Sat 10 Oct"
    assert got[3] == "Due date cleared"


def test_priority_cycles_each_task_from_its_own_value() -> None:
    (plan,) = _call_js([["priority", "plan", [PLAIN, WEEKLY, OTHER], None, None]])
    assert plan == [
        {"ids": [1], "changes": {"priority": "medium"}},
        {"ids": [2], "changes": {"priority": "low"}},
        {"ids": [3], "changes": {"priority": "none"}},       # wraps at the top
    ]


def test_complete_undoes_a_roll_by_its_due_and_a_close_by_its_status() -> None:
    """Issue #54: the roll moved ``due`` and kept the status; a plain task closed."""
    (inverse,) = _call_js([["complete", "invert", [PLAIN, WEEKLY, OTHER], None, None]])
    assert inverse == [
        {"ids": [2], "changes": {"due": "2026-10-02"}},
        {"ids": [1], "changes": {"status": "todo"}},
        {"ids": [3], "changes": {"status": "standby"}},
    ]


def test_every_undo_puts_back_each_tasks_own_prior_value() -> None:
    tasks = [PLAIN, WEEKLY, OTHER]
    got = _call_js([
        ["due-tomorrow", "invert", tasks, None, None],
        ["snooze", "invert", tasks, "tomorrow", None],
        ["priority", "invert", tasks, None, None],
        ["status-inbox", "invert", tasks, None, None],
    ])
    assert got == [
        [{"ids": [1], "changes": {"due": "2026-10-01"}}, {"ids": [2], "changes": {"due": "2026-10-02"}},
         {"ids": [3], "changes": {"due": None}}],
        [{"ids": [1, 2], "changes": {"starts": None}}, {"ids": [3], "changes": {"starts": "2026-10-09"}}],
        [{"ids": [1], "changes": {"priority": "low"}}, {"ids": [2], "changes": {"priority": "none"}},
         {"ids": [3], "changes": {"priority": "high"}}],
        [{"ids": [1], "changes": {"status": "todo"}}, {"ids": [2], "changes": {"status": "inbox"}},
         {"ids": [3], "changes": {"status": "standby"}}],
    ]


def test_messages_name_the_result_the_server_answered() -> None:
    rolled = dict(WEEKLY, due="2026-10-09")
    snoozed = dict(PLAIN, starts="2026-10-10")
    got = _call_js([
        ["complete", "message", [PLAIN], None, [dict(PLAIN, status="done")]],
        ["complete", "message", [WEEKLY], None, [rolled]],
        ["complete", "message", [PLAIN, WEEKLY], None, [dict(PLAIN, status="done"), rolled]],
        ["snooze", "message", [PLAIN], "this weekend", [snoozed]],
        ["priority", "message", [PLAIN], None, None],
    ])
    assert got[0] == "Completed"
    assert got[1].startswith("Completed — next: Fri 9 Oct")
    assert got[2] == "Completed"
    assert got[3] == "Snoozed to Sat 10 Oct"
    assert got[4] == "Priority medium"
