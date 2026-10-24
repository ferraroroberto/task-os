"""Read side of the task domain layer — single-task and list reads, the tree,
the search entry, the Board / Today views and counts, and the small lookups
(comments, links, activity, issue refs, people, mirror events, external-id keys).

Nothing here writes; the write side is :mod:`src.tasks.mutations` and
:mod:`src.tasks.related`, which read through this module.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from src.clock import today
from src.schema import (
    CLOSED_SQL,
    CLOSED_STATUSES,
)
from src.tasks.schema import (
    ValidationError,
    _ancestors,
    _blocked_fields,
    _blocker_rows,
    _currently_blocked_ids,
    _descendant_ids,
    _owner_of,
    _require_person,
    _require_task,
    _row,
    _rows,
    _summaries,
    _summary,
    _validate_date,
    _validate_enum,
    install_owner,
)


def list_blockers(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    """``task_id``'s blockers — id/title/status, ordered by id."""
    _require_task(conn, task_id)
    return _blocker_rows(conn, task_id)


def would_cycle(
    conn: sqlite3.Connection, task_id: int, new_parent_id: int | None
) -> bool:
    """Would parenting ``task_id`` under ``new_parent_id`` close a loop?

    The parent-cycle rule itself, with no side effects and nothing to log, so
    a caller that only wants to *reject* a proposal — :func:`move` before it
    writes, ``src.ai.triage`` before it stores a suggestion it would later
    hand to :func:`move` — asks the same question of the same tree instead of
    walking ``parent_id`` for itself. ``None`` (root) can never cycle.

    "Is the proposed parent one of my descendants?" and "am I one of the
    proposed parent's ancestors?" are the same question on an acyclic tree,
    and this tree is acyclic because this function is the only gate onto it.
    """
    if new_parent_id is None:
        return False
    new_parent_id = int(new_parent_id)
    if new_parent_id == task_id:
        return True
    return new_parent_id in _descendant_ids(conn, task_id)


def find_by_external_id(
    conn: sqlite3.Connection, table: str, external_id: str
) -> dict[str, Any] | None:
    """The row of ``tasks`` / ``comments`` / ``people`` carrying ``external_id``, or ``None``."""
    if table not in _EXTERNAL_ID_TABLES:
        raise ValueError(f"no external_id on {table!r}")
    return _row(
        conn.execute(f"SELECT * FROM {table} WHERE external_id = ?", (external_id,)).fetchone()
    )


_EXTERNAL_ID_TABLES = ("tasks", "comments", "people")


def captured_keys(conn: sqlite3.Connection, prefix: str) -> dict[str, bool]:
    """Every capture key starting with ``prefix`` → whether a task still carries it.

    ``False`` is a dismissal (#254): captured once, task since deleted. What
    :func:`capture_task` would answer ``unchanged`` / ``dismissed`` for, read in
    one pass, so a source can step over keys it has already settled instead of
    spending its batch limit on them (#440).
    """
    cut = len(prefix)
    keys = {
        str(r[0]): False
        for r in conn.execute(
            "SELECT external_id FROM capture_keys WHERE substr(external_id, 1, ?) = ?",
            (cut, prefix),
        )
    }
    for r in conn.execute(
        "SELECT external_id FROM tasks WHERE substr(external_id, 1, ?) = ?", (cut, prefix)
    ):
        keys[str(r[0])] = True
    return keys


def get_task(conn: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    """The full detail view: task + links, comments, activity, children, breadcrumb."""
    row = _require_task(conn, task_id)
    out = _summary(conn, row)
    # the whole subtree, not just the direct children — what a delete takes
    # with it, so a confirmation can name the count (#121)
    out["descendant_count"] = len(_descendant_ids(conn, task_id))
    out["breadcrumb"] = _ancestors(conn, task_id)
    out["children"] = _summaries(
        conn,
        [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tasks WHERE parent_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        ],
    )
    out["links"] = list_links(conn, task_id)
    out["comments"] = list_comments(conn, task_id)
    out["activity"] = list_activity(conn, task_id)
    return out


def _due_window(due: str | None) -> tuple[str | None, str | None, bool]:
    """``today|week|overdue|YYYY-MM-DD`` → (from, to, overdue_only)."""
    if not due:
        return None, None, False
    t = today()
    if due == "today":
        return t.isoformat(), t.isoformat(), False
    if due == "week":
        return t.isoformat(), (t + timedelta(days=7)).isoformat(), False
    if due == "overdue":
        return None, (t - timedelta(days=1)).isoformat(), True
    d = _validate_date(due)
    return d, d, False


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | list[str] | None = None,
    parent_id: int | str | None = None,
    project: int | None = None,
    due: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    type: str | None = None,
    person_id: int | list[int] | None = None,
    owner: str | list[str] | None = None,
    q: str | None = None,
    include_closed: bool = False,
    limit: int | None = None,
    done_on: str | None = None,
    done_from: str | None = None,
    done_to: str | None = None,
    updated_since: str | None = None,
    updated_before: str | None = None,
    deferred: str | None = None,
    blocked: str | None = None,
    descriptions: bool = True,
) -> list[dict[str, Any]]:
    """Filtered flat list (summaries), ordered due → priority → id.

    - ``status``: one value or a list; ``"open"`` = not done/cancelled;
    - ``parent_id``: an id, or ``"root"`` for top-level tasks only;
    - ``project``: descendant-of ``project`` (any depth);
    - ``due``: ``today`` · ``week`` · ``overdue`` · a date; or ``due_from``/``due_to``;
    - ``person_id``: one id or a list (the filter card's multi-select);
    - ``owner``: one member id or a list (#476) — a NULL owner counts as the
      install owner's, so naming them also returns every task nobody gave one;
    - ``q``: FTS over title/description/comments (see :func:`search`);
    - ``done_on``: a local calendar date — only tasks whose ``done_at`` falls
      on that day (the Board's *Done today* column; ``done_at`` is a local
      timestamp, so the boundary is local midnight).
    - ``done_from`` / ``done_to``: an inclusive window of local calendar days
      over ``done_at`` — the done journal's page (#102), same midnight rule.
      ``done_at`` is the closed-at stamp, so ``status=done,cancelled`` plus a
      window is "everything that closed that week". A done window flips the
      order to **newest closing first** (``done_at`` desc): it is only ever
      read as a journal, and a due-first order would scatter one day's
      completions across the page.
    - ``updated_since``: a local calendar date — only tasks whose ``updated_at``
      falls on or after that day (the shared filter card's *modified* window).
    - ``updated_before``: the inverse twin — only tasks whose ``updated_at``
      falls strictly before that day (the filter card's *untouched > N days*
      stale windows, #101). Any write moves ``updated_at`` — sync and mirror
      included — so a GitHub-synced task never looks stale.
    - closed (done/cancelled) tasks are hidden unless ``include_closed`` or a
      status filter names them.
    - ``deferred``: what to do with a task whose ``starts`` has not arrived
      (#87) — ``"hide"`` (only awake tasks), ``"only"`` (only sleeping ones —
      the filter card's *Deferred*, ``tasks ls --deferred``) or ``"all"``.
      Unset follows the working-view/closed-view split below: a closed view
      means "hide nothing", so it lifts this gate too — otherwise a count
      taken with it (the app's "any tasks at all?", the mirror's file total)
      would quietly omit the sleeping ones and report a number nobody could
      reconcile.
      This is the ONE place the working views' deferral rule lives: Board,
      Today and the CLI are all projections of this function, so they
      inherit it. :func:`tree` and :func:`search` do not go through here on
      purpose — a deferred task stays findable.
    - ``blocked``: what to do with a task that has an open blocker (#100) —
      ``"hide"`` (only unblocked tasks — the default working-view rule),
      ``"only"`` (only blocked ones — the status multi-select's ``blocked``
      pseudo-filter, ``tasks ls --blocked``) or ``"all"``. Unset follows the
      same closed-view rule as ``deferred``. This is the ONE place the
      rule lives; :func:`tree` and :func:`search` keep showing a blocked task
      (with its lock) on purpose.
    - Unset ``deferred``/``blocked`` default to ``"hide"`` in a *working*
      view and ``"all"`` in a *closed* view — ``include_closed=True``, a
      ``status`` filter naming only closed statuses (``done``/``cancelled``,
      not the ``"open"`` shorthand), or a ``done_on``/``done_from``/``done_to``
      window. Those are all read as the done journal / closed history, where
      a still-blocked or not-yet-started task that already finished must not
      vanish (#263). Pass ``deferred``/``blocked`` explicitly to override
      either default in either kind of view.

    Each item is a summary plus ``breadcrumb`` (root → parent), ``root`` (the
    top ancestor — the project the Board, Today and Search rows and the filter card name) and ``last_comment``.
    ``descriptions=False`` leaves the ``description`` key off every item: the
    web app's boot never reads one from the list (the drawer fetches its own
    task) and it is most of the payload (#309); the default keeps today's
    shape for the CLI and every other caller.
    """
    where: list[str] = []
    args: list[Any] = []

    status_values = [status] if isinstance(status, str) else (list(status) if status else None)
    # A closed-only view (an explicit closed-status filter, or a done-window
    # journal query) is a working-view escape hatch just like include_closed:
    # deferred/blocked default to "all" so a done task with a future `starts`
    # or an unresolved blocker still surfaces in the done journal / Done column.
    closed_view = (
        include_closed
        or bool(done_on or done_from or done_to)
        or (
            status_values is not None
            and status_values != ["open"]
            and all(v in CLOSED_STATUSES for v in status_values)
        )
    )

    if deferred is None:
        deferred = "all" if closed_view else "hide"
    if deferred not in ("hide", "only", "all"):
        raise ValidationError(f"deferred must be hide, only or all (got {deferred!r})")
    if deferred != "all":
        where.append(
            "(t.starts IS NULL OR t.starts <= ?)" if deferred == "hide" else "t.starts > ?"
        )
        args.append(today().isoformat())

    if blocked is None:
        blocked = "all" if closed_view else "hide"
    if blocked not in ("hide", "only", "all"):
        raise ValidationError(f"blocked must be hide, only or all (got {blocked!r})")
    if blocked != "all":
        blocked_ids = _currently_blocked_ids(conn)
        if blocked == "hide":
            if blocked_ids:
                where.append(f"t.id NOT IN ({', '.join('?' * len(blocked_ids))})")
                args.extend(blocked_ids)
        else:  # only
            if not blocked_ids:
                return []
            where.append(f"t.id IN ({', '.join('?' * len(blocked_ids))})")
            args.extend(blocked_ids)

    if status_values is not None:
        if status_values == ["open"]:
            where.append(f"t.status NOT IN ({CLOSED_SQL})")
        else:
            for v in status_values:
                _validate_enum("status", v)
            where.append(f"t.status IN ({', '.join('?' * len(status_values))})")
            args.extend(status_values)
    elif not include_closed:
        where.append(f"t.status NOT IN ({CLOSED_SQL})")

    if parent_id is not None:
        if parent_id == "root":
            where.append("t.parent_id IS NULL")
        else:
            where.append("t.parent_id = ?")
            args.append(int(parent_id))

    if project is not None:
        ids = _descendant_ids(conn, int(project))
        if not ids:
            return []
        where.append(f"t.id IN ({', '.join('?' * len(ids))})")
        args.extend(ids)

    d_from, d_to, overdue = _due_window(due)
    d_from = _validate_date(due_from) or d_from
    d_to = _validate_date(due_to) or d_to
    if d_from:
        where.append("t.due >= ?")
        args.append(d_from)
    if d_to:
        where.append("t.due <= ?")
        args.append(d_to)
    if overdue:
        where.append("t.due IS NOT NULL")

    if type:
        _validate_enum("type", type)
        where.append("t.type = ?")
        args.append(type)

    if person_id is not None:
        people = [int(p) for p in (person_id if isinstance(person_id, (list, tuple)) else [person_id])]
        if people:
            where.append(f"t.person_id IN ({', '.join('?' * len(people))})")
            args.extend(people)

    if owner is not None:
        owners = [str(o) for o in (owner if isinstance(owner, (list, tuple)) else [owner])]
        if owners:
            clause = f"t.owner IN ({', '.join('?' * len(owners))})"
            if install_owner() in owners:
                clause = f"({clause} OR t.owner IS NULL)"
            where.append(clause)
            args.extend(owners)

    if done_on:
        where.append("substr(t.done_at, 1, 10) = ?")
        args.append(_validate_date(done_on, "done_on"))

    if done_from:
        where.append("substr(t.done_at, 1, 10) >= ?")
        args.append(_validate_date(done_from, "done_from"))

    if done_to:
        where.append("substr(t.done_at, 1, 10) <= ?")
        args.append(_validate_date(done_to, "done_to"))

    if updated_since:
        where.append("substr(t.updated_at, 1, 10) >= ?")
        args.append(_validate_date(updated_since, "updated_since"))

    if updated_before:
        where.append("substr(t.updated_at, 1, 10) < ?")
        args.append(_validate_date(updated_before, "updated_before"))

    if q:
        hit_ids = [h["id"] for h in search(conn, q, limit=500)]
        if not hit_ids:
            return []
        where.append(f"t.id IN ({', '.join('?' * len(hit_ids))})")
        args.extend(hit_ids)

    sql = "SELECT t.* FROM tasks t"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if done_from or done_to:
        sql += " ORDER BY t.done_at DESC, t.id DESC"
    else:
        sql += (
            " ORDER BY t.due IS NULL, t.due, "
            "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, t.id"
        )
    if limit:
        sql += f" LIMIT {int(limit)}"
    items = _summaries(conn, [dict(r) for r in conn.execute(sql, args).fetchall()])
    _enrich_list(conn, items)
    if not descriptions:
        for it in items:
            it.pop("description", None)
    return items


def _enrich_list(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    """Add what the task rows need — ``breadcrumb`` (root → parent),
    ``root`` (the top ancestor, i.e. the project column), ``last_comment``
    and ``comment_count`` (the Board shows the count, never the body)
    — in four queries total instead of four per row."""
    if not items:
        return
    titles: dict[int, tuple[int | None, str]] = {
        r["id"]: (r["parent_id"], r["title"])
        for r in conn.execute("SELECT id, parent_id, title FROM tasks").fetchall()
    }
    ids = [it["id"] for it in items]
    counts: dict[int, int] = {
        r["task_id"]: int(r["n"])
        for r in conn.execute(
            f"SELECT task_id, COUNT(*) AS n FROM comments"
            f" WHERE task_id IN ({', '.join('?' * len(ids))}) GROUP BY task_id",
            ids,
        ).fetchall()
    }
    last: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        f"""
        SELECT task_id, ts, author, body, origin
          FROM (
              SELECT task_id, ts, author, body, origin,
                     ROW_NUMBER() OVER (
                         PARTITION BY task_id ORDER BY ts DESC, id DESC
                     ) AS rn
                FROM comments
               WHERE task_id IN ({', '.join('?' * len(ids))})
          )
         WHERE rn = 1
        """,
        ids,
    ).fetchall():
        last[r["task_id"]] = {"ts": r["ts"], "author": r["author"], "body": r["body"], "origin": r["origin"]}
    for it in items:
        chain: list[dict[str, Any]] = []
        pid = it["parent_id"]
        seen: set[int] = set()
        while pid is not None and pid in titles and pid not in seen:
            seen.add(pid)
            chain.append({"id": pid, "title": titles[pid][1]})
            pid = titles[pid][0]
        chain.reverse()
        it["breadcrumb"] = chain
        it["root"] = chain[0] if chain else None
        it["last_comment"] = last.get(it["id"])
        it["comment_count"] = counts.get(it["id"], 0)


def tree(
    conn: sqlite3.Connection,
    root_id: int | None = None,
    *,
    include_closed: bool = False,
    descriptions: bool = True,
) -> list[dict[str, Any]]:
    """Nested ``{...task, children: [...]}`` forest — the whole tree, or ``root_id``'s subtree.

    Closed (done/cancelled) tasks are pruned unless ``include_closed``; a
    closed project keeps showing while it has open descendants.
    ``descriptions=False`` leaves the ``description`` key off every node: the
    web app boots from the whole forest and never reads one there (the drawer
    fetches its own task), yet the closed ones are most of the payload (#280).
    """
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    by_parent: dict[int | None, list[dict[str, Any]]] = {}
    all_by_id: dict[int, dict[str, Any]] = {}
    for r in rows:
        row = dict(r)
        if not descriptions:
            row.pop("description", None)
        by_parent.setdefault(r["parent_id"], []).append(row)
        all_by_id[r["id"]] = row
    refs = {r["task_id"]: dict(r) for r in conn.execute("SELECT * FROM issue_refs").fetchall()}
    # blocked-by (#100), prefetched like issue_refs above: one query for the
    # whole tree rather than a per-node lookup. Ordered by blocker id, the
    # order :func:`_blocker_rows` gives every other task shape.
    blockers_by: dict[int, list[int]] = {}
    for r in conn.execute(
        "SELECT blocker_id, blocked_id FROM task_blocks ORDER BY blocked_id, blocker_id"
    ).fetchall():
        blockers_by.setdefault(r["blocked_id"], []).append(r["blocker_id"])

    def blocked_fields(task_id: int) -> dict[str, Any]:
        return _blocked_fields([
            {"id": bid, "title": all_by_id[bid]["title"], "status": all_by_id[bid]["status"]}
            for bid in blockers_by.get(task_id, []) if bid in all_by_id
        ])

    def build(pid: int | None, depth: int) -> list[dict[str, Any]]:
        out = []
        for row in by_parent.get(pid, []):
            node = dict(row)
            node["depth"] = depth
            node["issue_ref"] = refs.get(row["id"])
            node["owner"] = _owner_of(row)
            node.update(blocked_fields(row["id"]))
            node["children"] = build(row["id"], depth + 1)
            node["child_count"] = len(by_parent.get(row["id"], []))
            node["is_project"] = node["child_count"] > 0
            closed = row["status"] in CLOSED_STATUSES
            if closed and not include_closed and not node["children"]:
                continue
            out.append(node)
        return out

    if root_id is None:
        return build(None, 0)
    root = _require_task(conn, root_id)
    node = dict(root)
    if not descriptions:
        node.pop("description", None)
    node["depth"] = 0
    node["issue_ref"] = refs.get(root_id)
    node["owner"] = _owner_of(root)
    node.update(blocked_fields(root_id))
    node["children"] = build(root_id, 1)
    node["child_count"] = len(by_parent.get(root_id, []))
    node["is_project"] = node["child_count"] > 0
    return [node]


def projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every task that has children — ``{id, title, depth, status}`` in tree order.

    The web app's project filter and *Move to…* list, closed projects
    included: the boot's forest no longer carries closed tasks (#309), and a
    project whose children are all closed is a leaf there, so this is the one
    place that says what a project is (``tree()``'s ``is_project`` rule).
    """
    by_parent: dict[int | None, list[sqlite3.Row]] = {}
    for r in conn.execute("SELECT id, parent_id, title, status FROM tasks ORDER BY id").fetchall():
        by_parent.setdefault(r["parent_id"], []).append(r)
    out: list[dict[str, Any]] = []

    def walk(pid: int | None, depth: int) -> None:
        for r in by_parent.get(pid, []):
            if r["id"] in by_parent:
                out.append({"id": r["id"], "title": r["title"], "depth": depth, "status": r["status"]})
                walk(r["id"], depth + 1)

    walk(None, 0)
    return out


def list_comments(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    """Oldest first (thread order), ties broken by insertion."""
    return _rows(
        conn.execute(
            "SELECT * FROM comments WHERE task_id = ? ORDER BY ts, id", (task_id,)
        ).fetchall()
    )


def list_mirror_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Most recent first — for the Settings mirror card's "inspect" view."""
    return _rows(conn.execute("SELECT * FROM mirror_events ORDER BY ts DESC, id DESC").fetchall())


def count_mirror_events(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM mirror_events").fetchone()
    return int(row["n"])


def list_links(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    return _rows(conn.execute("SELECT * FROM links WHERE task_id = ? ORDER BY id", (task_id,)).fetchall())


def list_activity(
    conn: sqlite3.Connection, task_id: int | None = None, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Newest first; all tasks when ``task_id`` is ``None``."""
    sql = "SELECT * FROM activity"
    args: list[Any] = []
    if task_id is not None:
        sql += " WHERE task_id = ?"
        args.append(task_id)
    sql += " ORDER BY ts DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _rows(conn.execute(sql, args).fetchall())


def list_issue_refs(conn: sqlite3.Connection, provider: str | None = None) -> list[dict[str, Any]]:
    """Every ``issue_refs`` row (optionally one provider) with its task's title / status."""
    sql = """
        SELECT r.task_id, r.provider, r.repo, r.number, r.state, r.url, r.last_synced,
               t.title AS task_title, t.status AS task_status
        FROM issue_refs r JOIN tasks t ON t.id = r.task_id
    """
    params: tuple[Any, ...] = ()
    if provider:
        sql += " WHERE r.provider = ?"
        params = (provider,)
    return _rows(conn.execute(sql + " ORDER BY r.repo, r.number", params).fetchall())


def get_person(conn: sqlite3.Connection, person_id: int) -> dict[str, Any]:
    p = _require_person(conn, person_id)
    n = conn.execute(
        f"SELECT COUNT(*) FROM tasks WHERE person_id = ? AND status NOT IN ({CLOSED_SQL})",
        (person_id,),
    ).fetchone()[0]
    p["open_tasks"] = int(n)
    return p


def list_people(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id FROM people ORDER BY name COLLATE NOCASE, id").fetchall()
    return [get_person(conn, r["id"]) for r in rows]


def _person_task_ids(conn: sqlite3.Connection, person_id: int) -> list[int]:
    rows = conn.execute("SELECT id FROM tasks WHERE person_id = ?", (person_id,)).fetchall()
    return [r["id"] for r in rows]


def _fts_query(q: str) -> str:
    """Turn free text into a safe FTS5 query: each word a prefix term, ANDed.

    Quotes every token so punctuation (``#``, ``-``, ``:``) can't break the
    MATCH grammar; a trailing ``*`` makes ``pass`` hit ``passport``. The twin
    of ``src.search.base.fts_query``, kept here because importing that package
    would pull its adapters — which import this module — into every import of
    this one; a test pins the two together.
    """
    tokens = [t.replace('"', '""') for t in q.split() if t.strip()]
    return " ".join(f'"{t}"*' for t in tokens)


def search(conn: sqlite3.Connection, q: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Full-text hits over title / description / comment bodies.

    Returns task summaries with ``snippet`` (the matched text, ``[`` ``]``
    marks) and ``matched_in`` (``title|description|comment``); a task that
    hits in several places appears once with the best-ranked location.
    """
    q = (q or "").strip()
    if not q:
        return []
    match = _fts_query(q)
    hits: dict[int, dict[str, Any]] = {}
    # The task text is free-form and may itself hold ``[`` (``[WIP] fix tap``),
    # so "did the title match" is asked of a mark that cannot occur in text; the
    # display ``[`` ``]`` are swapped in afterwards (#440).
    for r in conn.execute(
        """
        SELECT rowid AS id, bm25(tasks_fts) AS rank,
               snippet(tasks_fts, 0, char(1), char(2), '…', 12) AS s_title,
               snippet(tasks_fts, 1, char(1), char(2), '…', 12) AS s_desc,
               highlight(tasks_fts, 0, char(1), char(2)) AS h_title
          FROM tasks_fts WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?
        """,
        (match, limit),
    ).fetchall():
        matched_in = "title" if "\x01" in (r["h_title"] or "") else "description"
        snippet = r["s_title"] if matched_in == "title" else r["s_desc"]
        snippet = (snippet or "").replace("\x01", "[").replace("\x02", "]")
        hits[r["id"]] = {"rank": r["rank"], "matched_in": matched_in, "snippet": snippet}
    for r in conn.execute(
        """
        SELECT c.task_id AS id, bm25(comments_fts) AS rank,
               snippet(comments_fts, 0, '[', ']', '…', 12) AS s_body
          FROM comments_fts JOIN comments c ON c.id = comments_fts.rowid
         WHERE comments_fts MATCH ? ORDER BY rank LIMIT ?
        """,
        (match, limit),
    ).fetchall():
        prev = hits.get(r["id"])
        if prev is None or r["rank"] < prev["rank"]:
            hits[r["id"]] = {"rank": r["rank"], "matched_in": "comment", "snippet": r["s_body"]}
    if not hits:
        return []
    ordered = sorted(hits.items(), key=lambda kv: (kv[1]["rank"], kv[0]))[:limit]
    ids = [tid for tid, _ in ordered]
    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            f"SELECT * FROM tasks WHERE id IN ({', '.join('?' * len(ids))})", ids
        ).fetchall()
    }
    hit_meta = [(rows[tid], meta) for tid, meta in ordered if tid in rows]
    out = _summaries(conn, [row for row, _ in hit_meta])
    for item, (_, meta) in zip(out, hit_meta, strict=True):
        item.update(meta)
    # breadcrumb · root · last_comment · comment_count — the same enriched
    # summary every list view gets, so a search hit renders as the same row
    _enrich_list(conn, out)
    return out


BOARD_COLUMNS = ("inbox", "todo", "standby", "done")


def board(
    conn: sqlite3.Connection,
    *,
    project: int | None = None,
    person_id: int | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """The Board's four buckets: ``inbox · todo · standby · done``.

    The first three are the open statuses; ``done`` holds only tasks completed
    **today** (``done_at`` on the current local calendar day — an older done
    task never shows, and the boundary is local midnight, not UTC). Items are
    the same enriched summaries :func:`list_tasks` returns, in its order
    (due → priority → id). Two queries: one over the open statuses, one over
    today's done.
    """
    day = today().isoformat()
    columns: dict[str, list[dict[str, Any]]] = {key: [] for key in BOARD_COLUMNS}
    for item in list_tasks(
        conn, status=list(BOARD_COLUMNS[:-1]), project=project, person_id=person_id, q=q
    ):
        columns[item["status"]].append(item)
    columns["done"] = list_tasks(
        conn, status=["done"], project=project, person_id=person_id, q=q, done_on=day
    )
    return {"today": day, "columns": columns}


def _group_by_root(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``[{root, items}]`` — grouped by top ancestor (``None`` = no project);
    groups ordered by their earliest due, then root title; inside a group,
    items keep the incoming due → priority → id order (the list order),
    recurring or not — same as every other view (#118, following #116)."""
    groups: dict[int | None, dict[str, Any]] = {}
    for it in items:
        root = it.get("root")
        key = root["id"] if root else None
        g = groups.setdefault(key, {"root": root, "items": []})
        g["items"].append(it)
    return sorted(
        groups.values(),
        key=lambda g: (
            min(t["due"] for t in g["items"]),
            (g["root"] or {}).get("title", "").lower(),
        ),
    )


def today_view(conn: sqlite3.Connection, *, person_id: int | None = None) -> dict[str, Any]:
    """The Today tab: open tasks due ≤ today (overdue first, then today),
    grouped by root project, plus a *later this week* bucket (tomorrow …
    +7 days) in the same shape."""
    t = today()
    iso = t.isoformat()
    due = list_tasks(conn, status="open", due_to=iso, person_id=person_id)
    week = list_tasks(
        conn,
        status="open",
        due_from=(t + timedelta(days=1)).isoformat(),
        due_to=(t + timedelta(days=7)).isoformat(),
        person_id=person_id,
    )
    return {
        "today": iso,
        "due": _group_by_root(due),
        "week": _group_by_root(week),
        "counts": {
            "overdue": sum(1 for it in due if it["due"] < iso),
            "today": sum(1 for it in due if it["due"] == iso),
            "week": len(week),
        },
    }


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts per table — the health/summary readout."""
    out: dict[str, int] = {}
    for table in ("tasks", "people", "comments", "links", "activity", "issue_refs"):
        out[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return out
