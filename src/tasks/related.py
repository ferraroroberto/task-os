"""Writes for the rows that hang off a task or sit beside it — comments, mirror
events, links, issue refs and people — under the same activity-log and
write-listener rules as :mod:`src.tasks.mutations`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from src.clock import now_iso
from src.schema import (
    COMMENT_ORIGINS,
    ISSUE_PROVIDERS,
    LINK_KINDS,
)
from src.tasks.queries import _person_task_ids, count_mirror_events, get_person, get_task
from src.tasks.schema import (
    DEFAULT_ACTOR,
    NotFound,
    ValidationError,
    _log,
    _require_person,
    _require_task,
    _row,
    _touched,
)

logger = logging.getLogger(__name__)


def add_comment(
    conn: sqlite3.Connection,
    task_id: int,
    body: str,
    *,
    author: str | None = None,
    origin: str = "ui",
    ts: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Append a comment (thread order = ``ts``).

    ``ts`` / ``external_id`` are the import path: a historical comment keeps
    its original timestamp and source id (dedupe key) and does **not** bump
    the task's ``updated_at`` — only a fresh comment (no ``ts``) does.
    """
    _require_task(conn, task_id)
    body = (body or "").strip()
    if not body:
        raise ValidationError("comment body is required")
    if origin not in COMMENT_ORIGINS:
        raise ValidationError(f"origin must be one of {', '.join(COMMENT_ORIGINS)} (got {origin!r})")
    historical = ts is not None
    ts = ts or now_iso()
    cur = conn.execute(
        "INSERT INTO comments(task_id, author, ts, body, origin, external_id) VALUES (?,?,?,?,?,?)",
        (task_id, author or DEFAULT_ACTOR, ts, body, origin, external_id),
    )
    if not historical:
        conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (ts, task_id))
    conn.commit()
    _touched(task_id)
    return _row(conn.execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def update_comment(
    conn: sqlite3.Connection, task_id: int, comment_id: int, body: str
) -> dict[str, Any]:
    """Rewrite one comment's body in place (#155).

    Author, ``ts`` and ``origin`` are deliberately kept: the row stays whose it
    was and keeps saying where it came from — an edit corrects the text, it does
    not re-attribute the comment. ``comments_au`` re-indexes ``comments_fts``,
    so search follows the new words; ``_touched`` re-exports the markdown file,
    so a stale mirror copy cannot resurrect the old line on the next import.
    """
    body = (body or "").strip()
    if not body:
        raise ValidationError("comment body is required")
    cur = conn.execute(
        "UPDATE comments SET body = ? WHERE id = ? AND task_id = ?", (body, comment_id, task_id)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise NotFound(f"comment {comment_id} on task {task_id} not found")
    _touched(task_id)
    return _row(conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone())  # type: ignore[return-value]


def delete_comment(conn: sqlite3.Connection, task_id: int, comment_id: int) -> None:
    cur = conn.execute(
        "DELETE FROM comments WHERE id = ? AND task_id = ?", (comment_id, task_id)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise NotFound(f"comment {comment_id} on task {task_id} not found")
    _touched(task_id)


#: A permanently-unresolvable field caps out here so one noisy install can't
#: grow the table unbounded; the oldest rows fall off first.
MIRROR_EVENT_KINDS = ("conflict", "rejected")


MIRROR_EVENTS_CAP = 500


def record_mirror_event(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    kind: str,
    field: str,
    file_value: str,
    kept_value: str,
) -> None:
    """Record a mirror import conflict/rejection, deduped on (task_id, field, file_value).

    A repeat of the same unresolvable value refreshes ``ts`` in place rather
    than adding a new row (a permanently-broken field produces one standing
    event, not one per import pass).
    """
    _require_task(conn, task_id)
    if kind not in MIRROR_EVENT_KINDS:
        raise ValidationError(f"kind must be one of {', '.join(MIRROR_EVENT_KINDS)} (got {kind!r})")
    ts = now_iso()
    conn.execute(
        "INSERT INTO mirror_events(task_id, kind, field, file_value, kept_value, ts) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(task_id, field, file_value) DO UPDATE SET "
        "kind = excluded.kind, kept_value = excluded.kept_value, ts = excluded.ts",
        (task_id, kind, field, file_value, kept_value, ts),
    )
    conn.execute(
        "DELETE FROM mirror_events WHERE id NOT IN "
        "(SELECT id FROM mirror_events ORDER BY ts DESC, id DESC LIMIT ?)",
        (MIRROR_EVENTS_CAP,),
    )
    conn.commit()


def resolve_mirror_field(conn: sqlite3.Connection, task_id: int, field: str) -> None:
    """Clear any standing event(s) for this task's field — it imported cleanly this pass."""
    conn.execute("DELETE FROM mirror_events WHERE task_id = ? AND field = ?", (task_id, field))
    conn.commit()


def clear_mirror_events(conn: sqlite3.Connection) -> int:
    """Delete every standing event; returns how many were cleared."""
    n = count_mirror_events(conn)
    if n:
        conn.execute("DELETE FROM mirror_events")
        conn.commit()
    return n


_AI_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:claude\.ai/|chatgpt\.com/|chat\.openai\.com/|gemini\.google\.com/"
    r"|copilot\.microsoft\.com/|github\.com/copilot(?:/|$))",
    re.IGNORECASE,
)


_ISSUE_URL_RE = re.compile(r"github\.com/[^/]+/[^/]+/issues/\d+")


def infer_link_kind(url: str) -> str:
    """The ``kind`` a link is stored under when the caller names none — the
    one rule for the drawer, quick-add, the CLI and any script (#257): a
    ``{placeholder}`` ref is a folder, ``mailto:`` an email, a known AI chat
    host an AI conversation (#77), a GitHub issue URL an issue, else web."""
    url = (url or "").strip()
    if url.startswith("{"):
        return "folder"
    if re.match(r"^mail(?:to:|://)", url, re.IGNORECASE):
        return "email"
    if _AI_URL_RE.match(url):
        return "ai"
    if _ISSUE_URL_RE.search(url):
        return "issue"
    return "web"


def add_link(
    conn: sqlite3.Connection,
    task_id: int,
    url: str,
    *,
    label: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Attach a link; ``kind=None`` → :func:`infer_link_kind`."""
    _require_task(conn, task_id)
    url = (url or "").strip()
    if not url:
        raise ValidationError("link url is required")
    kind = kind or infer_link_kind(url)
    if kind not in LINK_KINDS:
        raise ValidationError(f"kind must be one of {', '.join(LINK_KINDS)} (got {kind!r})")
    cur = conn.execute(
        "INSERT INTO links(task_id, url, label, kind) VALUES (?,?,?,?)", (task_id, url, label, kind)
    )
    conn.commit()
    _touched(task_id)
    return _row(conn.execute("SELECT * FROM links WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def remove_link(conn: sqlite3.Connection, task_id: int, link_id: int) -> None:
    cur = conn.execute("DELETE FROM links WHERE id = ? AND task_id = ?", (link_id, task_id))
    conn.commit()
    if cur.rowcount == 0:
        raise NotFound(f"link {link_id} on task {task_id} not found")
    _touched(task_id)


def rename_link_url(
    conn: sqlite3.Connection, old_url: str, new_url: str, *, kind: str, dry_run: bool = False
) -> int:
    """Every ``kind`` link pointing at ``old_url`` now points at ``new_url``; how many.

    The one write that exists because a link's *target* moved rather than
    because anyone edited the task — the archiver renumbering a folder renames
    the ``.msg`` an email link holds the ref of (#176), and a chip pointing at
    a file that is no longer there is a dead chip. Identity only: no activity
    row, because the log records what a human or a channel did to a task and a
    file being renamed on disk is neither. The write listeners *are* notified —
    the mirror renders the link, so its markdown is now stale.

    ``dry_run`` counts the rows it would rewrite and writes nothing.
    """
    old_url, new_url = (old_url or "").strip(), (new_url or "").strip()
    if not old_url or not new_url or old_url == new_url:
        return 0
    rows = conn.execute(
        "SELECT id, task_id FROM links WHERE kind = ? AND url = ?", (kind, old_url)
    ).fetchall()
    if not rows or dry_run:
        return len(rows)
    conn.execute("UPDATE links SET url = ? WHERE kind = ? AND url = ?", (new_url, kind, old_url))
    conn.commit()
    _touched(*[int(r["task_id"]) for r in rows])
    return len(rows)


def rename_external_id(
    conn: sqlite3.Connection, old_external_id: str, new_external_id: str, *, dry_run: bool = False
) -> int:
    """Re-key the task captured under ``old_external_id``; how many rows moved.

    The capture key is derived from the source's own identity — for a flagged
    email, the folded path of its ``.msg`` (:mod:`src.email_capture`) — so a
    source that renames the thing it offered leaves this database keyed on a
    name nothing will ever present again, and the next poll captures the same
    mail a second time. Re-keying is what keeps *capture lands once* true
    across such a rename; nothing about the task itself changes.

    A collision is possible and is **not** an error to raise: the new key may
    already belong to a task a poll captured before the heal ran. The v3
    partial unique index refuses it, and this says so in the log and returns 0
    rather than merging two tasks nobody asked it to merge.

    The ``capture_keys`` row moves too, **with or without a task** (#254): a
    capture already dismissed by a delete must stay dismissed under its new
    name, or the renamed ``.msg`` lands again. The count is still tasks moved.
    """
    old_external_id, new_external_id = (old_external_id or "").strip(), (new_external_id or "").strip()
    if not old_external_id or not new_external_id or old_external_id == new_external_id:
        return 0
    rows = conn.execute(
        "SELECT id FROM tasks WHERE external_id = ?", (old_external_id,)
    ).fetchall()
    keyed = conn.execute(
        "SELECT 1 FROM capture_keys WHERE external_id = ?", (old_external_id,)
    ).fetchone() is not None
    if dry_run or not (rows or keyed):
        return len(rows)
    try:
        conn.execute(
            "UPDATE tasks SET external_id = ? WHERE external_id = ?",
            (new_external_id, old_external_id),
        )
        # OR IGNORE: the new name may already be known (captured before the
        # heal ran) — then the old key simply goes.
        conn.execute(
            "INSERT OR IGNORE INTO capture_keys(external_id, captured_at)"
            " SELECT ?, captured_at FROM capture_keys WHERE external_id = ?",
            (new_external_id, old_external_id),
        )
        conn.execute("DELETE FROM capture_keys WHERE external_id = ?", (old_external_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        logger.warning(
            "⚠️ repo: task %s already carries the new capture key — left on the old one",
            ", ".join(f"#{int(r['id'])}" for r in rows),
        )
        return 0
    _touched(*[int(r["id"]) for r in rows])
    return len(rows)


def rename_link(conn: sqlite3.Connection, task_id: int, link_id: int, label: str | None) -> dict[str, Any]:
    label = (label or "").strip() or None
    cur = conn.execute(
        "UPDATE links SET label = ? WHERE id = ? AND task_id = ?", (label, link_id, task_id)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise NotFound(f"link {link_id} on task {task_id} not found")
    _touched(task_id)
    return _row(conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone())  # type: ignore[return-value]


def set_issue_ref(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    provider: str,
    repo: str,
    number: int,
    url: str | None = None,
    state: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Attach (or replace) the issue on a task → the task becomes ``coding``."""
    current = _require_task(conn, task_id)
    if provider not in ISSUE_PROVIDERS:
        raise ValidationError(f"provider must be one of {', '.join(ISSUE_PROVIDERS)} (got {provider!r})")
    if not repo or not number:
        raise ValidationError("repo and number are required")
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO issue_refs(task_id, provider, repo, number, state, url, last_synced)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(task_id) DO UPDATE SET provider = excluded.provider, repo = excluded.repo,
            number = excluded.number, state = excluded.state, url = excluded.url,
            last_synced = excluded.last_synced
        """,
        (task_id, provider, repo, int(number), state, url, ts),
    )
    if current["type"] != "coding":
        conn.execute("UPDATE tasks SET type = 'coding', updated_at = ? WHERE id = ?", (ts, task_id))
        _log(conn, task_id, actor, "type", current["type"], "coding", ts)
    _log(conn, task_id, actor, "issue", None, f"{repo}#{number}", ts)
    conn.commit()
    _touched(task_id)
    return get_task(conn, task_id)


def touch_issue_ref(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    state: str | None = None,
    url: str | None = None,
    actor: str | None = None,
    ts: str | None = None,
) -> dict[str, Any] | None:
    """The sync's bookkeeping on an existing ref: ``last_synced`` always, ``state`` /
    ``url`` when given. A state change (open ↔ closed) writes an ``issue_state``
    activity row; nothing else is logged. Returns the row, ``None`` when absent."""
    ref = conn.execute("SELECT * FROM issue_refs WHERE task_id = ?", (task_id,)).fetchone()
    if ref is None:
        return None
    ts = ts or now_iso()
    new_state = state if state is not None else ref["state"]
    new_url = url if url is not None else ref["url"]
    conn.execute(
        "UPDATE issue_refs SET state = ?, url = ?, last_synced = ? WHERE task_id = ?",
        (new_state, new_url, ts, task_id),
    )
    if new_state != ref["state"]:
        _log(conn, task_id, actor, "issue_state", ref["state"], new_state, ts)
    conn.commit()
    if new_state != ref["state"]:
        _touched(task_id)
    return _row(conn.execute("SELECT * FROM issue_refs WHERE task_id = ?", (task_id,)).fetchone())


def remove_issue_ref(conn: sqlite3.Connection, task_id: int, *, actor: str | None = None) -> dict[str, Any]:
    """Detach the issue → the task reverts to ``task``."""
    current = _require_task(conn, task_id)
    ref = conn.execute("SELECT * FROM issue_refs WHERE task_id = ?", (task_id,)).fetchone()
    if ref is None:
        raise NotFound(f"task {task_id} has no issue_ref")
    ts = now_iso()
    conn.execute("DELETE FROM issue_refs WHERE task_id = ?", (task_id,))
    conn.execute("UPDATE tasks SET type = 'task', updated_at = ? WHERE id = ?", (ts, task_id))
    _log(conn, task_id, actor, "type", current["type"], "task", ts)
    _log(conn, task_id, actor, "issue", f"{ref['repo']}#{ref['number']}", None, ts)
    conn.commit()
    _touched(task_id)
    return get_task(conn, task_id)


def create_person(
    conn: sqlite3.Connection,
    name: str,
    *,
    email: str | None = None,
    avatar_path: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValidationError("name is required")
    cur = conn.execute(
        "INSERT INTO people(name, email, avatar_path, external_id) VALUES (?,?,?,?)",
        (name, email, avatar_path, external_id),
    )
    conn.commit()
    assert cur.lastrowid is not None  # an INSERT always sets it
    return get_person(conn, int(cur.lastrowid))


def update_person(conn: sqlite3.Connection, person_id: int, **changes: Any) -> dict[str, Any]:
    allowed = {"name", "email", "avatar_path", "external_id"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError(f"unknown person field(s): {', '.join(sorted(unknown))}")
    _require_person(conn, person_id)
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise ValidationError("name cannot be empty")
    if changes:
        assignments = ", ".join(f"{k} = :{k}" for k in changes)
        conn.execute(f"UPDATE people SET {assignments} WHERE id = :id", {**changes, "id": person_id})
        conn.commit()
        if "name" in changes:
            _touched(*_person_task_ids(conn, person_id))
    return get_person(conn, person_id)


def delete_person(conn: sqlite3.Connection, person_id: int) -> None:
    """Remove a person; tasks pointing at them keep going with ``person_id = NULL``."""
    _require_person(conn, person_id)
    affected = _person_task_ids(conn, person_id)
    conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
    conn.commit()
    _touched(*affected)
