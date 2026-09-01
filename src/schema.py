"""Versioned schema migrations — the one place DDL lives.

``MIGRATIONS`` maps a target version to the SQL that upgrades a database from
``version - 1``. ``migrate(conn)`` reads ``settings.schema_version`` (0 when
the table is missing), applies every step above it inside one transaction
each, and stamps the new version in the same transaction — a crash leaves the
DB at the last fully-applied version, and re-running is a no-op.

Version history:

    1  settings(key, value) + schema_version marker                (Step 1)
    2  tasks / links / comments / activity / people / issue_refs   (Step 2)
       + FTS5 external-content indexes over tasks(title, description) and
       comments(body) kept in sync by triggers, + indices on parent_id /
       status / due.
    3  tasks.external_id + comments.external_id (partial unique indexes)  (Step 3)
       — the source-system key an importer (Notion) is idempotent on:
       a re-run finds the row by external_id and updates instead of duplicating.
    4  mirror_state(task_id, path, exported_at, file_mtime_ns, content_hash)  (Step 6)
       — one row per task file the markdown mirror last wrote: the watcher
       compares a file's mtime against ``file_mtime_ns`` to spot an edit,
       ``exported_at`` is the conflict baseline ("did the DB change after the
       file was written?"), ``content_hash`` skips no-op rewrites. No FK
       cascade on purpose: the exporter needs the old ``path`` after a task is
       deleted so it can remove the file, then drops the row itself.
    5  links.kind gains 'ai' — an AI-conversation link (Claude, ChatGPT,
       Gemini, Copilot — one kind, no per-provider split; issue #77). SQLite
       cannot widen a CHECK in place, so the step rebuilds ``links`` and
       recreates its index; v2's DDL stays frozen on the shipped kind list.
    6  mirror_events(id, task_id, kind, field, file_value, kept_value, ts)  (issue #84)
       — a conflicting or rejected mirror import value, recorded here instead
       of as a comment on the task. Deduped on (task_id, field, file_value)
       so a permanently unresolvable value produces one standing row, not one
       per import pass; ``src/mirror.py`` clears a task's row for a field once
       that field imports cleanly. No existing comment is touched or removed.
    7  tasks.starts (TEXT date, nullable) + its index                (issue #87)
       — the day a task starts mattering. Until it arrives the task is
       *deferred*: ``src/tasks_repo.py``'s ``list_tasks`` hides it from the
       working views (Board · Today · Table · ``tasks ls``) while the Tree and
       search still show it. Snooze is this column worn as a row control, not
       a second mechanism. The recurrence roll never touches it — see the
       contract note below.
    8  tasks.planned_on (TEXT date, nullable) + tasks.plan_order (INTEGER,
       nullable) + an index on planned_on                            (issue #89)
       — the day a task was committed to ("My plan" on Today) and its position
       inside that day's plan. ``planned_on`` is a first-class task field
       (activity-logged, mirrored); ``plan_order`` is presentation-level
       ordering managed by ``src/tasks_repo.py`` only (appended on plan,
       cleared on unplan, rewritten by ``plan_reorder``) — never PATCHed
       directly, never mirrored.
    9  tasks.recurrence_anchor (TEXT, nullable)                     (issue #112)
       — the fixed day a recurrence lands on, beside the cadence rather than
       inside it (the iCalendar split: ``FREQ=WEEKLY;BYDAY=FR``). ``weekly``
       takes a weekday list (``fri``, ``mon,tue,wed,thu,fri``), ``monthly``
       takes ``day-N`` or ``<1..4|last>-<weekday>``; the other cadences take
       none. NULL keeps the plain offset roll. Grammar and arithmetic live in
       ``src/dates.py``, validation in ``src/tasks_repo.py``.

Contract (plan §04): a task with children is a project; ``coding`` ⇔ an
``issue_refs`` row exists (enforced in ``src/tasks_repo.py``); every due /
status / parent / priority change writes ``activity``; recurrence rolls the
same task's due forward on done — to the first occurrence that is after both
the completed due *and* today, so an overdue task never rolls into another
overdue date (issue #112) — and leaves ``starts`` alone (issue #87): a
start date is an absolute one-time gate that always eventually arrives, so a
snoozed recurring task wakes on its start day and rolls normally from then on
rather than being hidden forever by a gate that moves with it.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

TASK_TYPES = ("task", "coding", "note")
TASK_STATUSES = ("inbox", "todo", "doing", "standby", "done", "cancelled")
TASK_PRIORITIES = ("high", "medium", "low", "none")
RECURRENCES = ("daily", "weekly", "monthly", "quarterly", "yearly")
LINK_KINDS = ("web", "folder", "email", "issue", "ai")
COMMENT_ORIGINS = ("ui", "cli", "md", "notion", "import", "sync")
ISSUE_PROVIDERS = ("github", "gitlab")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


_V1 = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_V2 = f"""
CREATE TABLE people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    avatar_path TEXT,
    external_id TEXT
);

CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    code        TEXT,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'task'  CHECK (type IN ({_in(TASK_TYPES)})),
    status      TEXT NOT NULL DEFAULT 'inbox' CHECK (status IN ({_in(TASK_STATUSES)})),
    priority    TEXT NOT NULL DEFAULT 'none'  CHECK (priority IN ({_in(TASK_PRIORITIES)})),
    due         TEXT,
    recurrence  TEXT CHECK (recurrence IS NULL OR recurrence IN ({_in(RECURRENCES)})),
    description TEXT NOT NULL DEFAULT '',
    folder_ref  TEXT,
    next_action TEXT,
    person_id   INTEGER REFERENCES people(id) ON DELETE SET NULL,
    created_by  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    done_at     TEXT
);
CREATE INDEX idx_tasks_parent   ON tasks(parent_id);
CREATE INDEX idx_tasks_status   ON tasks(status);
CREATE INDEX idx_tasks_due      ON tasks(due);
CREATE INDEX idx_tasks_person   ON tasks(person_id);

CREATE TABLE links (
    id      INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url     TEXT NOT NULL,
    label   TEXT,
    kind    TEXT NOT NULL DEFAULT 'web' CHECK (kind IN ('web', 'folder', 'email', 'issue'))
);
CREATE INDEX idx_links_task ON links(task_id);

CREATE TABLE comments (
    id      INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    author  TEXT,
    ts      TEXT NOT NULL,
    body    TEXT NOT NULL,
    origin  TEXT NOT NULL DEFAULT 'ui' CHECK (origin IN ({_in(COMMENT_ORIGINS)}))
);
CREATE INDEX idx_comments_task ON comments(task_id, ts);

CREATE TABLE activity (
    id        INTEGER PRIMARY KEY,
    task_id   INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    ts        TEXT NOT NULL,
    actor     TEXT,
    field     TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);
CREATE INDEX idx_activity_task ON activity(task_id, ts);

CREATE TABLE issue_refs (
    task_id     INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL CHECK (provider IN ({_in(ISSUE_PROVIDERS)})),
    repo        TEXT NOT NULL,
    number      INTEGER NOT NULL,
    state       TEXT,
    url         TEXT,
    last_synced TEXT
);

-- Full-text search: external-content FTS5 over tasks(title, description) and
-- comments(body); triggers keep both in sync (the FTS5-documented pattern).
CREATE VIRTUAL TABLE tasks_fts USING fts5(
    title, description,
    content='tasks', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER tasks_ai AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER tasks_ad AFTER DELETE ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, title, description)
        VALUES ('delete', old.id, old.title, old.description);
END;
CREATE TRIGGER tasks_au AFTER UPDATE OF title, description ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, title, description)
        VALUES ('delete', old.id, old.title, old.description);
    INSERT INTO tasks_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;

CREATE VIRTUAL TABLE comments_fts USING fts5(
    body,
    content='comments', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER comments_ai AFTER INSERT ON comments BEGIN
    INSERT INTO comments_fts(rowid, body) VALUES (new.id, new.body);
END;
CREATE TRIGGER comments_ad AFTER DELETE ON comments BEGIN
    INSERT INTO comments_fts(comments_fts, rowid, body) VALUES ('delete', old.id, old.body);
END;
CREATE TRIGGER comments_au AFTER UPDATE OF body ON comments BEGIN
    INSERT INTO comments_fts(comments_fts, rowid, body) VALUES ('delete', old.id, old.body);
    INSERT INTO comments_fts(rowid, body) VALUES (new.id, new.body);
END;
"""

_V3 = """
ALTER TABLE tasks ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX idx_tasks_external_id ON tasks(external_id) WHERE external_id IS NOT NULL;
ALTER TABLE comments ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX idx_comments_external_id ON comments(external_id) WHERE external_id IS NOT NULL;
"""

_V4 = """
CREATE TABLE mirror_state (
    task_id       INTEGER PRIMARY KEY,
    path          TEXT NOT NULL,
    exported_at   TEXT NOT NULL,
    file_mtime_ns INTEGER NOT NULL,
    content_hash  TEXT NOT NULL
);
"""

# links.kind gains 'ai' (#77). A CHECK cannot be altered in place: rebuild the
# table (dropping a child table trips nothing — only tasks is referenced) and
# recreate its one index. v2 above keeps the shipped kind list verbatim.
_V5 = f"""
CREATE TABLE links_new (
    id      INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url     TEXT NOT NULL,
    label   TEXT,
    kind    TEXT NOT NULL DEFAULT 'web' CHECK (kind IN ({_in(LINK_KINDS)}))
);
INSERT INTO links_new(id, task_id, url, label, kind)
    SELECT id, task_id, url, label, kind FROM links;
DROP TABLE links;
ALTER TABLE links_new RENAME TO links;
CREATE INDEX idx_links_task ON links(task_id);
"""

_V6 = """
CREATE TABLE mirror_events (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('conflict', 'rejected')),
    field      TEXT NOT NULL,
    file_value TEXT NOT NULL,
    kept_value TEXT NOT NULL,
    ts         TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_mirror_events_dedupe ON mirror_events(task_id, field, file_value);
CREATE INDEX idx_mirror_events_ts ON mirror_events(ts);
"""

# tasks.starts (#87) — a plain nullable column, so an existing database gains
# it with every task awake (NULL = no gate). The index carries the deferral
# clause every list query now adds.
_V7 = """
ALTER TABLE tasks ADD COLUMN starts TEXT;
CREATE INDEX idx_tasks_starts ON tasks(starts);
"""

# tasks.planned_on + tasks.plan_order (#89) — plain nullable columns, so an
# existing database gains them with nothing planned. The index serves the
# plan-group and candidate queries (planned_on = today / < today).
_V8 = """
ALTER TABLE tasks ADD COLUMN planned_on TEXT;
ALTER TABLE tasks ADD COLUMN plan_order INTEGER;
CREATE INDEX idx_tasks_planned_on ON tasks(planned_on);
"""

# tasks.recurrence_anchor (#112) — a plain nullable column, so an existing
# database gains it with every recurring task unanchored (NULL = the offset
# roll it has always had). The fixed day lives beside the cadence rather than
# inside it because widening ``tasks.recurrence``'s CHECK would mean rebuilding
# ``tasks`` — and ``DROP TABLE tasks`` with foreign keys on fires the
# ON DELETE CASCADE of links / comments / activity / issue_refs, while
# ``PRAGMA foreign_keys`` is a no-op inside the transaction this step runs in.
# (v5's ``links`` rebuild was safe only because nothing references ``links``.)
# No index: the column is never a query predicate, only carried on the row.
_V9 = """
ALTER TABLE tasks ADD COLUMN recurrence_anchor TEXT;
"""

#: version → SQL script that upgrades from version - 1.
MIGRATIONS: dict[int, str] = {
    1: _V1, 2: _V2, 3: _V3, 4: _V4, 5: _V5, 6: _V6, 7: _V7, 8: _V8, 9: _V9,
}

#: The version a freshly migrated database carries.
SCHEMA_VERSION = max(MIGRATIONS)


def current_version(conn: sqlite3.Connection) -> int:
    """The stored ``schema_version``; 0 when the settings table does not exist yet."""
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every pending migration in order; return the resulting version.

    Each step runs as one transaction with its version stamp, so a failure
    mid-script rolls that step back and leaves the stamp at the previous
    version. Idempotent: a current DB is left untouched.
    """
    start = current_version(conn)
    version = start
    for target in sorted(MIGRATIONS):
        if target <= version:
            continue
        # executescript() issues an implicit COMMIT first, so open the
        # transaction inside the script and stamp before it ends.
        script = (
            "BEGIN;\n"
            + MIGRATIONS[target]
            + "\nINSERT INTO settings(key, value) VALUES('schema_version', "
            f"'{target}') ON CONFLICT(key) DO UPDATE SET value = excluded.value;\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            logger.error("❌ db: migration to schema_version %d failed (stays at %d)", target, version)
            raise
        version = target
    if version != start:
        logger.info("ℹ️ db: schema_version %d → %d", start, version)
    return version


def table_names(conn: sqlite3.Connection) -> set[str]:
    """Every table + virtual table name (handy for tests and health checks)."""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}
