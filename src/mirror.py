"""Markdown mirror — one ``.md`` per task, export on write, watcher import.

The database is canonical; the mirror is a human/LLM-editable projection of
it in a folder a sync client (OneDrive, a shared drive) can carry around:

    <mirror.dir>/<id:04d>-<slug>.md

    ---                       YAML frontmatter (flat scalars + a links list)
    id: 42 · external_id · parent · title · code · type · status · priority
    due · starts · planned_on · recurrence · recurrence_anchor · person (name)
    folder_ref · next_action
    blocked_by: [id, id]     the tasks that must close first (#100)
    links: [{url, label, kind}] · created_at · updated_at · done_at · exported_at
    ---
    ## Description            markdown, free
    ## Comments               one line per comment — append-only
    - <ISO ts> · <author> · <origin>: <body>
    ## Log                    activity, read-only

**Export** — :meth:`Mirror.export_task` renders a task deterministically
(same DB state → byte-identical file, ``exported_at`` aside, and the file is
left untouched when nothing changed) and records what it wrote in the
``mirror_state`` table (schema v4): path, ``exported_at``, the file's mtime
after the write, a content hash. A title change renames the file (the id
prefix keeps it findable), a deleted task removes it. The debounced
:meth:`Mirror.touch` queue behind :func:`src.tasks_repo.add_write_listener`
re-exports only the touched ids ~1 s after the last write.

**Import** — the watcher (:meth:`Mirror.import_tick`, stdlib polling of the
dir's mtimes every ~2 s; no watchdog dependency) picks files whose mtime
differs from the recorded one, parses them and applies:

- changed **scalar frontmatter fields** through the repo with ``actor="md"``
  (so activity rows are written like any other change) — ``title``, ``code``,
  ``status``, ``priority``, ``due``, ``starts`` and ``planned_on`` (natural
  phrases welcome), ``recurrence`` + ``recurrence_anchor``, ``person`` (by
  name), ``folder_ref``, ``next_action``, ``parent``; and the
  ``## Description`` body. ``plan_order``
  is deliberately not mirrored (#89): it is presentation-level ordering, and
  mirroring it would churn every synced file on every drag;
- ``blocked_by: [ids]`` (#100) — a relation, not a scalar field, diffed
  against the stored edges and applied add/remove through
  :func:`src.tasks_repo.add_blocker` / :func:`~src.tasks_repo.remove_blocker`
  — the same cycle-guard rejection path ``parent`` gets from :func:`~src.tasks_repo.move`;
  a rejected edit is a ``mirror_events`` row like any other, never a comment;
- **new lines under ``## Comments``** — anything not matching a known comment
  by (ts, author, body) — as comments ``origin=md`` (author from the line, else
  the configured owner). The origin token is read but never part of that
  identity: an imported comment is always stored as ``md``, so keying on what
  the line claimed made a ``· ui:`` line re-import on every pass (#123). A
  bare line (no timestamp) is always a new comment — that is how you add one
  by typing into the file, and the re-export dates it;
- ``## Log``, read-only keys (``id``, ``type``, ``links``, timestamps) and
  unknown sections are ignored; deleted lines are not deletions (append-only:
  the re-export restores them).

**Conflict rule** — per field: if the DB changed that field *after* the file
was written (latest ``activity.ts`` for the field > the recorded
``exported_at``), the DB wins and the rejected file value is kept as a
``mirror_events`` row (schema v6; issue #84) — ``import conflict on <field>:
file said <x>, kept <y>`` — nothing is silently lost, but it never becomes a
comment on the task. A value the repo refuses (bad status, unknown person, a
cycle) is recorded the same way (``import rejected on …``). Deduped on
(task_id, field, file_value) and cleared once that field imports cleanly;
:meth:`Mirror.status` ``events`` is the count the Settings mirror card reads.
After every import the file is re-exported so it converges to canonical
form. Malformed YAML → the file is skipped (warning once per change, counted
in :meth:`Mirror.status` ``errors``), never a crash.

**Provenance rule** (#126) — the file's ``exported_at`` is the one line no
human edit touches, so it says whose rendering a file is. Equal to what we
last wrote: our file, edited. Older: a stale copy of our file (a sync client
restoring a previous version) — still an edit, judged against *that*
snapshot. **Newer: we never wrote it** — another task-os instance rendered
its own database into this folder (a fresh checkout on the sample config, a
harness pointed at the real folder). That is not an edit: nothing is
applied, every differing value is a ``conflict`` event, the file is
re-exported to canonical (or, under a name we never wrote, skipped and left
alone). Without this, a second instance whose ``people`` table lacked a name
re-exported ``person: null`` over the live files and the live watcher cleared
23 assignments in one pass — and once rewrote 79 titles.

Enabled only when ``mirror.dir`` resolves (``config.placeholders``) to a path
whose parent exists — the leaf is created; otherwise :attr:`Mirror.enabled`
is ``False`` with a one-line reason surfaced by the log, ``/api/status`` and
``tasks mirror status``, never a silent no-op. Two boundaries keep a
*disposable* instance out of the real folder by construction: an instance on
an overridden database (``TASKOS_DB_PATH``) only mirrors / backs up to a
folder beside that database, and the committed sample config never enables
either service (``src.config.load_config``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src import tasks_repo as repo
from src.config import AppConfig, resolve_placeholders, unresolved_placeholders
from src.dates import DateParseError, parse_date
from src.db import DB_PATH_ENV, connect

logger = logging.getLogger(__name__)

MD_ACTOR = "md"
DEBOUNCE_S = 1.0
POLL_S = 2.0
SLUG_MAX = 60

FILE_RE = re.compile(r"^(\d{4,})(?:-[^\\/]*)?\.md$", re.IGNORECASE)
_HEADINGS = {"## description": "description", "## comments": "comments", "## log": "log"}
_COMMENT_RE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
    r" · (?P<author>.*?) · (?P<origin>[a-z]+): (?P<body>.*)$"
)
_INT_RE = re.compile(r"^-?\d+$")
_PLAIN_SAFE_RE = re.compile(r"^[A-Za-z0-9_./ ,+():@%\u00c0-\uffff-]*$")

#: Frontmatter keys, in the order they are written.
FRONTMATTER_KEYS = (
    "id", "external_id", "parent", "title", "code", "type", "status", "priority", "due",
    "starts", "planned_on", "recurrence", "recurrence_anchor", "person", "folder_ref",
    "next_action", "blocked_by", "links",
    "created_at", "updated_at", "done_at", "exported_at",
)
#: Keys the import applies (everything else in the frontmatter is read-only).
#: ``blocked_by`` is importable but not a scalar task field — it goes through
#: :meth:`Mirror._apply_blocked_by`, not the generic per-field loop below.
IMPORTABLE_KEYS = (
    "title", "code", "status", "priority", "due", "starts", "planned_on", "recurrence",
    "recurrence_anchor", "person", "folder_ref", "next_action", "parent",
)
#: file key → activity field name (the conflict baseline lookup).
_ACTIVITY_FIELD = {"parent": "parent", "person": "person_id"}
#: file key → task column
_TASK_FIELD = {"parent": "parent_id", "person": "person_id"}
#: a foreign file's value this database cannot even resolve (never equal to a stored one)
_UNRESOLVED = object()


class MirrorParseError(ValueError):
    """The file is not a mirror file we can read (bad frontmatter, no id, …)."""


# ================================================================ rendering


def slugify(title: str) -> str:
    """``"Renew passports (2026)"`` → ``renew-passports-2026``; ASCII, ≤ 60 chars, never empty."""
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    text = text[:SLUG_MAX].rstrip("-")
    return text or "task"


def file_name(task_id: int, title: str) -> str:
    return f"{int(task_id):04d}-{slugify(title)}.md"


def _needs_quotes(s: str) -> bool:
    if s == "" or s != s.strip():
        return True
    low = s.lower()
    if low in ("null", "~", "true", "false", "yes", "no", "on", "off") or _INT_RE.match(s):
        return True
    if s[0] in "-?:,[]{}#&*!|>'\"%@`" or ": " in s or " #" in s or "\n" in s:
        return True
    return not _PLAIN_SAFE_RE.match(s)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    return json.dumps(s, ensure_ascii=False) if _needs_quotes(s) else s


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s in ("", "null", "~", "Null", "NULL"):
        return None
    if s.startswith('"'):
        try:
            return json.loads(s)
        except ValueError as exc:
            raise MirrorParseError(f"bad quoted string {s[:40]!r}") from exc
    if s.startswith("'"):
        if not s.endswith("'") or len(s) < 2:
            raise MirrorParseError(f"unterminated string {s[:40]!r}")
        return s[1:-1].replace("''", "'")
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if _INT_RE.match(s):
        return int(s)
    return s


def render(task: dict[str, Any], *, exported_at: str) -> str:
    """The canonical file text for a ``tasks_repo.get_task`` detail dict."""
    fm: dict[str, Any] = {
        "id": task["id"],
        "external_id": task.get("external_id"),
        "parent": task.get("parent_id"),
        "title": task["title"],
        "code": task.get("code"),
        "type": task.get("type"),
        "status": task.get("status"),
        "priority": task.get("priority"),
        "due": task.get("due"),
        "starts": task.get("starts"),
        "planned_on": task.get("planned_on"),
        "recurrence": task.get("recurrence"),
        "recurrence_anchor": task.get("recurrence_anchor"),
        "person": (task.get("person") or {}).get("name"),
        "folder_ref": task.get("folder_ref"),
        "next_action": task.get("next_action"),
        "blocked_by": [b["id"] for b in task.get("blocked_by") or []],
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "done_at": task.get("done_at"),
        "exported_at": exported_at,
    }
    lines = ["---"]
    for key in FRONTMATTER_KEYS:
        if key == "blocked_by":
            ids = fm["blocked_by"]
            lines.append("blocked_by: [" + ", ".join(str(i) for i in ids) + "]")
            continue
        if key == "links":
            links = task.get("links") or []
            if not links:
                lines.append("links: []")
            else:
                lines.append("links:")
                for lk in links:
                    lines.append(f"  - url: {_scalar(lk.get('url'))}")
                    lines.append(f"    label: {_scalar(lk.get('label'))}")
                    lines.append(f"    kind: {_scalar(lk.get('kind') or 'web')}")
            continue
        lines.append(f"{key}: {_scalar(fm[key])}")
    lines.append("---")
    lines.append("")
    lines.append("## Description")
    lines.append("")
    desc = (task.get("description") or "").strip()
    if desc:
        lines.append(desc)
        lines.append("")
    lines.append("## Comments")
    lines.append("")
    for c in task.get("comments") or []:
        lines.append(_comment_line(c))
    if task.get("comments"):
        lines.append("")
    lines.append("## Log")
    lines.append("")
    activity = list(task.get("activity") or [])
    activity.reverse()  # get_task gives newest first; a log reads oldest first
    for a in activity:
        old = "∅" if a.get("old_value") is None else str(a["old_value"]).replace("\n", " ")
        new = "∅" if a.get("new_value") is None else str(a["new_value"]).replace("\n", " ")
        lines.append(f"- {a['ts']} · {a.get('actor') or '-'} · {a['field']}: {old} → {new}")
    if activity:
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _comment_line(c: dict[str, Any]) -> str:
    body = (c.get("body") or "").strip()
    first, *rest = body.split("\n")
    out = f"- {c['ts']} · {c.get('author') or '-'} · {c.get('origin') or 'ui'}: {first}"
    for extra in rest:
        out += "\n  " + extra
    return out


# ================================================================== parsing


@dataclass
class ParsedFile:
    frontmatter: dict[str, Any]
    description: str
    comments: list[dict[str, Any]]  # {ts, author, origin, body} (ts/author/origin None on a bare line)
    sections: dict[str, str] = field(default_factory=dict)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """``(mapping, body)`` for a ``---`` fenced YAML head; the tiny YAML subset we write."""
    if not text.startswith("---"):
        raise MirrorParseError("missing frontmatter fence")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise MirrorParseError("missing frontmatter fence")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        raise MirrorParseError("unterminated frontmatter")
    data: dict[str, Any] = {}
    i = 1
    while i < end:
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise MirrorParseError(f"unexpected indentation at frontmatter line {i}: {line[:40]!r}")
        if ":" not in line:
            raise MirrorParseError(f"expected 'key: value' at frontmatter line {i}: {line[:40]!r}")
        key, _, rest = line.partition(":")
        key = key.strip()
        if not key or " " in key:
            raise MirrorParseError(f"bad key at frontmatter line {i}: {line[:40]!r}")
        rest_s = rest.strip()
        if rest_s == "":
            # block: a list of mappings ("  - k: v" / "    k: v") or nothing
            items: list[dict[str, Any]] = []
            while i < end and (lines[i].startswith(" ") or not lines[i].strip()):
                sub = lines[i]
                i += 1
                st = sub.strip()
                if not st:
                    continue
                if st.startswith("- "):
                    items.append({})
                    st = st[2:].strip()
                    if not st:
                        continue
                elif not items:
                    raise MirrorParseError(f"unexpected nested line at frontmatter line {i}: {sub[:40]!r}")
                if ":" not in st:
                    raise MirrorParseError(f"expected 'key: value' in list at frontmatter line {i}: {sub[:40]!r}")
                k, _, v = st.partition(":")
                items[-1][k.strip()] = _parse_scalar(v)
            data[key] = items
        elif rest_s in ("[]", "[ ]"):
            data[key] = []
        elif rest_s.startswith("[") and rest_s.endswith("]"):
            # An inline scalar list — only ``blocked_by: [3, 7]`` writes this
            # shape today, so an int-only reader is enough; anything else is
            # malformed rather than silently coerced.
            inner = rest_s[1:-1].strip()
            items_flat: list[Any] = []
            for part in inner.split(","):
                part = part.strip()
                if not part:
                    continue
                if not _INT_RE.match(part):
                    raise MirrorParseError(f"expected an integer list at frontmatter line {i}: {line[:40]!r}")
                items_flat.append(int(part))
            data[key] = items_flat
        else:
            data[key] = _parse_scalar(rest_s)
    body = "\n".join(lines[end + 1:])
    return data, body


def split_sections(body: str) -> dict[str, str]:
    """``{"description": …, "comments": …, "log": …}`` by the three known ``##`` headings."""
    out: dict[str, list[str]] = {}
    current = "_preamble"
    for line in body.split("\n"):
        key = _HEADINGS.get(line.strip().lower())
        if key is not None:
            current = key
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def parse_comment_lines(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in text.split("\n"):
        if line.startswith("- "):
            m = _COMMENT_RE.match(line)
            if m:
                entries.append({
                    "ts": m.group("ts"), "author": m.group("author"),
                    "origin": m.group("origin"), "body": m.group("body"),
                })
            else:
                entries.append({"ts": None, "author": None, "origin": None, "body": line[2:]})
        elif entries and line.strip():
            entries[-1]["body"] += "\n" + (line[2:] if line.startswith("  ") else line.strip())
        elif entries and not line.strip():
            entries[-1]["body"] += "\n"
    for e in entries:
        e["body"] = e["body"].strip()
    return [e for e in entries if e["body"]]


def parse_file(text: str) -> ParsedFile:
    fm, body = parse_frontmatter(text.lstrip("\ufeff"))
    if not isinstance(fm.get("id"), int):
        raise MirrorParseError("frontmatter has no integer id")
    sections = split_sections(body)
    return ParsedFile(
        frontmatter=fm,
        description=sections.get("description", "").strip(),
        comments=parse_comment_lines(sections.get("comments", "")),
        sections=sections,
    )


# =================================================================== paths


def resolve_dir(raw: str, placeholders: dict[str, str], *, label: str) -> tuple[Path | None, str]:
    """``(path, "")`` when usable, else ``(None, reason)``.

    Usable = configured, every placeholder resolved, and the parent folder
    exists (the leaf is created — a missing sync root stays disabled).
    """
    if not (raw or "").strip():
        return None, f"{label} not configured"
    resolved = resolve_placeholders(raw, placeholders)
    missing = unresolved_placeholders(resolved)
    if missing:
        return None, f"{label}: unresolved placeholder(s) {', '.join('{' + m + '}' for m in missing)} — add them to config.placeholders"
    path = Path(resolved).expanduser()
    override = os.environ.get(DB_PATH_ENV, "").strip()
    if override:
        # A harness / disposable instance (the one thing TASKOS_DB_PATH is for)
        # only mirrors beside its own database. One pointed at the real synced
        # folder rendered a temp DB over the live files, and the live watcher
        # imported that as human edits (#126) — so this is refused, loudly,
        # rather than left to whoever copies the sample config next.
        root = Path(override).expanduser().resolve().parent
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return None, (
                f"{label}: {path} is outside the {DB_PATH_ENV} folder {root} — an instance on an "
                f"overridden database only mirrors beside it; put {label} under {root} or unset {DB_PATH_ENV}"
            )
    if path.is_dir():
        return path, ""
    if path.parent.is_dir():
        try:
            path.mkdir()
        except OSError as exc:
            return None, f"{label}: cannot create {path} ({exc})"
        return path, ""
    return None, f"{label}: parent folder missing — {path.parent} (create it, or fix {label} in config.json)"


# ================================================================== service


@dataclass
class ImportResult:
    path: Path
    task_id: int | None = None
    applied: dict[str, Any] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    comments_added: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path.name, "task_id": self.task_id, "applied": self.applied,
            "conflicts": self.conflicts, "rejected": self.rejected,
            "comments_added": self.comments_added, "error": self.error,
        }


class Mirror:
    """The export/import engine + the optional background thread.

    Synchronous entry points take an open connection (tests, the CLI); the
    thread started by :meth:`start` owns its own connection and runs the
    debounced export queue and the import watcher.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        db_path: Path | None = None,
        debounce_s: float = DEBOUNCE_S,
        poll_s: float = POLL_S,
    ) -> None:
        self.dir, self.reason = resolve_dir(config.mirror.dir, config.placeholders, label="mirror.dir")
        self.owner = config.team.people[0] if config.team.people else repo.DEFAULT_ACTOR
        self.db_path = db_path
        self.debounce_s = debounce_s
        self.poll_s = poll_s
        self._lock = threading.RLock()
        self._pending: set[int] = set()
        self._pending_since = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._bad_files: dict[str, int] = {}  # name → mtime_ns of the version that failed
        self.errors_total = 0
        self.last_export: str | None = None
        self.last_import: str | None = None
        self.exports = 0
        self.imports = 0
        if not self.enabled:
            logger.warning("⚠️ mirror disabled — %s", self.reason)

    @property
    def enabled(self) -> bool:
        return self.dir is not None

    # ------------------------------------------------------------ status

    def status(self, conn: sqlite3.Connection) -> dict[str, Any]:
        files: int | None = None
        if self.dir is not None:
            try:
                files = sum(1 for e in os.scandir(self.dir) if e.is_file() and FILE_RE.match(e.name))
            except OSError:
                files = None
        return {
            "enabled": self.enabled,
            "dir": str(self.dir) if self.dir else None,
            "reason": None if self.enabled else self.reason,
            "files": files,
            "last_export": self.last_export,
            "last_import": self.last_import,
            "exports": self.exports,
            "imports": self.imports,
            "errors": len(self._bad_files),
            "errors_total": self.errors_total,
            "error_files": sorted(self._bad_files),
            "pending": len(self._pending),
            "watching": self._thread is not None and self._thread.is_alive(),
            "events": repo.count_mirror_events(conn),
        }

    # ------------------------------------------------------------ export

    def _state(self, conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM mirror_state WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def _record(self, conn: sqlite3.Connection, task_id: int, path: Path, exported_at: str, content_hash: str) -> None:
        mtime_ns = path.stat().st_mtime_ns
        conn.execute(
            "INSERT INTO mirror_state(task_id, path, exported_at, file_mtime_ns, content_hash) "
            "VALUES (?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET path = excluded.path, "
            "exported_at = excluded.exported_at, file_mtime_ns = excluded.file_mtime_ns, "
            "content_hash = excluded.content_hash",
            (task_id, path.name, exported_at, mtime_ns, content_hash),
        )
        conn.commit()

    def _remove(self, conn: sqlite3.Connection, task_id: int, state: dict[str, Any] | None) -> bool:
        removed = False
        if state and self.dir is not None:
            old = self.dir / state["path"]
            try:
                old.unlink()
                removed = True
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("⚠️ mirror: could not remove %s (%s)", old, exc)
        conn.execute("DELETE FROM mirror_state WHERE task_id = ?", (task_id,))
        conn.commit()
        return removed

    def export_task(self, conn: sqlite3.Connection, task_id: int, *, force: bool = False) -> Path | None:
        """Write (or refresh, rename, remove) the file for ``task_id``; ``None`` when removed/disabled.

        A file whose mtime moved since we wrote it carries a user edit: it is
        imported first so the export never overwrites an unread change.
        """
        if self.dir is None:
            return None
        with self._lock:
            state = self._state(conn, task_id)
            try:
                task = repo.get_task(conn, task_id)
            except repo.NotFound:
                self._remove(conn, task_id, state)
                return None
            imported = False
            if state is not None and not force:
                old = self.dir / state["path"]
                try:
                    if old.stat().st_mtime_ns != state["file_mtime_ns"]:
                        self.import_file(conn, old, _reexport=False)
                        imported = True
                        state = self._state(conn, task_id)
                        task = repo.get_task(conn, task_id)
                except FileNotFoundError:
                    pass
            stable = render(task, exported_at="")
            content_hash = hashlib.sha256(stable.encode("utf-8")).hexdigest()
            target = self.dir / file_name(task_id, task["title"])
            if (
                state is not None and not force and not imported
                and state["path"] == target.name
                and state["content_hash"] == content_hash
                and target.exists()
                and target.stat().st_mtime_ns == state["file_mtime_ns"]
            ):
                return target
            exported_at = repo.now_iso()
            text = render(task, exported_at=exported_at)
            tmp = target.with_suffix(".md.tmp")
            tmp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(tmp, target)
            if state is not None and state["path"] != target.name:
                old = self.dir / state["path"]
                try:
                    old.unlink()
                except OSError:
                    pass
            self._record(conn, task_id, target, exported_at, content_hash)
            self.exports += 1
            self.last_export = exported_at
            return target

    def export_ids(self, conn: sqlite3.Connection, ids: list[int]) -> int:
        n = 0
        for tid in sorted(set(ids)):
            try:
                self.export_task(conn, tid)
                n += 1
            except Exception:  # noqa: BLE001 — one bad task never stops the batch
                logger.exception("❌ mirror: export of task %s failed", tid)
        return n

    def export_all(self, conn: sqlite3.Connection) -> dict[str, int]:
        """Every task → its file; files of deleted tasks removed. ``{"tasks", "written", "removed"}``."""
        if self.dir is None:
            return {"tasks": 0, "written": 0, "removed": 0}
        before = self.exports
        ids = [r["id"] for r in conn.execute("SELECT id FROM tasks ORDER BY id").fetchall()]
        for tid in ids:
            try:
                self.export_task(conn, tid)
            except Exception:  # noqa: BLE001
                logger.exception("❌ mirror: export of task %s failed", tid)
        removed = 0
        stale = conn.execute(
            "SELECT task_id FROM mirror_state WHERE task_id NOT IN (SELECT id FROM tasks)"
        ).fetchall()
        for r in stale:
            if self._remove(conn, r["task_id"], self._state(conn, r["task_id"])):
                removed += 1
        written = self.exports - before
        logger.info("ℹ️ mirror: exported %d task(s) → %s (%d written, %d removed)", len(ids), self.dir, written, removed)
        return {"tasks": len(ids), "written": written, "removed": removed}

    # ------------------------------------------------------------ import

    def _last_change(self, conn: sqlite3.Connection, task_id: int, key: str) -> str | None:
        field_name = _ACTIVITY_FIELD.get(key, key)
        row = conn.execute(
            "SELECT MAX(ts) FROM activity WHERE task_id = ? AND field = ?", (task_id, field_name)
        ).fetchone()
        return row[0] if row and row[0] else None

    def _person_id(self, conn: sqlite3.Connection, name: Any) -> int | None:
        if name is None or str(name).strip() == "":
            return None
        wanted = str(name).strip().lower()
        rows = conn.execute("SELECT id, name FROM people").fetchall()
        hits = [r["id"] for r in rows if (r["name"] or "").strip().lower() == wanted]
        if len(hits) != 1:
            raise repo.ValidationError(f"person {name!r} not found (tasks people lists them)")
        return int(hits[0])

    def _file_value(self, conn: sqlite3.Connection, key: str, raw: Any) -> Any:
        """Normalise a frontmatter value into what the repo stores for ``key``."""
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            return None
        if key in ("due", "starts", "planned_on"):
            try:
                d = parse_date(str(raw))
            except DateParseError as exc:
                raise repo.ValidationError(str(exc)) from exc
            return d.isoformat() if d else None
        if key == "person":
            return self._person_id(conn, raw)
        if key == "parent":
            try:
                return int(raw)
            except (TypeError, ValueError) as exc:
                raise repo.ValidationError(f"parent must be a task id (got {raw!r})") from exc
        if key in ("status", "priority", "recurrence", "recurrence_anchor"):
            return str(raw).strip().lower()
        return str(raw).strip()

    def import_file(self, conn: sqlite3.Connection, path: Path, *, _reexport: bool = True) -> ImportResult:
        """Apply one file's edits (fields, comments) to the DB; re-export it after."""
        result = ImportResult(path=path)
        with self._lock:
            try:
                mtime_ns = path.stat().st_mtime_ns
                text = path.read_text(encoding="utf-8-sig")
                parsed = parse_file(text)
            except FileNotFoundError:
                result.error = "file vanished"
                return result
            except (OSError, MirrorParseError, UnicodeDecodeError) as exc:
                return self._mark_bad(result, path, f"{type(exc).__name__}: {exc}")
            task_id = int(parsed.frontmatter["id"])
            m = FILE_RE.match(path.name)
            if m and int(m.group(1)) != task_id:
                return self._mark_bad(result, path, f"file id {m.group(1)} ≠ frontmatter id {task_id}")
            result.task_id = task_id
            try:
                task = repo.get_task(conn, task_id)
            except repo.NotFound:
                return self._mark_bad(result, path, f"task {task_id} does not exist")
            self._bad_files.pop(path.name, None)
            state = self._state(conn, task_id)
            baseline, foreign = self._provenance(state, parsed)
            self._apply_fields(conn, task, parsed, baseline, result, foreign=foreign)
            self._apply_blocked_by(conn, task, parsed, result, foreign=foreign)
            if foreign is not None:
                # Not an edit of our file: another task-os instance rendered its
                # own database into this folder (#126). Nothing was applied —
                # every differing value is a standing event — and the file is
                # rewritten to canonical below so a later human edit of it is
                # read as an edit again. A file under a name we never wrote is
                # left alone (and not re-read) so it cannot churn every tick.
                logger.warning(
                    "⚠️ mirror: %s — %s; nothing applied, %d value(s) kept as events",
                    path.name, foreign, len(result.conflicts),
                )
                if state is not None and state["path"] != path.name:
                    return self._mark_bad(result, path, f"{foreign}; nothing applied, {len(result.conflicts)} value(s) kept as events")
            else:
                self._apply_comments(conn, task, parsed, result)
            self.imports += 1
            self.last_import = repo.now_iso()
            if result.applied or result.comments_added or result.conflicts or result.rejected:
                logger.info(
                    "ℹ️ mirror: imported %s → task %d (applied %s · %d comment(s) · %d conflict(s) · %d rejected)",
                    path.name, task_id, list(result.applied) or "-", result.comments_added,
                    len(result.conflicts), len(result.rejected),
                )
            if _reexport:
                self.export_task(conn, task_id, force=True)
            else:
                # the caller re-exports; just stop the watcher re-reading this version
                if state is not None:
                    conn.execute("UPDATE mirror_state SET file_mtime_ns = ? WHERE task_id = ?", (mtime_ns, task_id))
                    conn.commit()
        return result

    @staticmethod
    def _provenance(state: dict[str, Any] | None, parsed: ParsedFile) -> tuple[str | None, str | None]:
        """``(baseline, foreign)`` from the file's ``exported_at`` against what we last wrote.

        ``exported_at`` is the one line no human edit touches, so it says which
        database snapshot a file is a rendering of:

        - **equal** (or absent, or no record yet) — our own file, edited: the
          per-field conflict rule applies against our ``exported_at``;
        - **older** — a stale copy of our own file (a sync client restoring a
          previous version, an editor saving a stale buffer): still an edit,
          but made against *that* snapshot, so the baseline is the file's own
          stamp and anything the DB changed since it wins;
        - **newer** — we never wrote this: another task-os instance rendered
          *its* database into this folder (a fresh checkout on the sample
          config, a harness pointed at the real folder — #126). Not an edit.
          ``foreign`` carries the reason and :meth:`_apply_fields` applies nothing.
        """
        stamp = parsed.frontmatter.get("exported_at")
        stamp = str(stamp) if stamp else None
        ours = (state or {}).get("exported_at") or None
        if not ours or not stamp:
            return ours or stamp, None
        if _after(stamp, ours):
            return ours, f"written by another task-os instance (file exported_at {stamp}, ours {ours})"
        return (stamp if _after(ours, stamp) else ours), None

    def _mark_bad(self, result: ImportResult, path: Path, message: str) -> ImportResult:
        result.error = message
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = -1
        if self._bad_files.get(path.name) != mtime_ns:
            self._bad_files[path.name] = mtime_ns
            self.errors_total += 1
            logger.warning("⚠️ mirror: skipped %s — %s (fix the file; it is re-read on the next change)", path.name, message)
        return result

    def _apply_fields(
        self,
        conn: sqlite3.Connection,
        task: dict[str, Any],
        parsed: ParsedFile,
        baseline: str | None,
        result: ImportResult,
        *,
        foreign: str | None = None,
    ) -> None:
        fm = parsed.frontmatter
        candidates: list[tuple[str, Any]] = [(k, fm[k]) for k in IMPORTABLE_KEYS if k in fm]
        if "description" in parsed.sections:
            candidates.append(("description", parsed.description))
        task_id = task["id"]
        for key, raw in candidates:
            column = _TASK_FIELD.get(key, key)
            current = task.get(column)
            if key == "description":
                current = (current or "").strip()
            try:
                value = self._file_value(conn, key, raw)
            except repo.RepoError as exc:
                if foreign is None:
                    self._note(
                        conn, task_id, result.rejected, kind="rejected", field=key,
                        file_value=repr(raw), kept_value=self._show(task, key), detail=str(exc),
                    )
                    continue
                value = _UNRESOLVED  # unresolvable here — differs from what we hold either way
            if key == "description":
                value = value or ""
            if value == current:
                repo.resolve_mirror_field(conn, task_id, key)
                continue
            if foreign is not None:
                # another instance's rendering of its own task: kept as a standing
                # event, never applied — the DB it describes is not this one (#126)
                self._note(
                    conn, task_id, result.conflicts, kind="conflict", field=key,
                    file_value=self._fmt(raw), kept_value=self._show(task, key), detail=foreign,
                )
                continue
            last = self._last_change(conn, task_id, key)
            if baseline and last and _after(last, baseline):
                self._note(
                    conn, task_id, result.conflicts, kind="conflict", field=key,
                    file_value=self._fmt(raw), kept_value=self._show(task, key),
                )
                continue
            try:
                repo.update_task(conn, task_id, actor=MD_ACTOR, **{column: value})
                result.applied[key] = value
                task = repo.get_task(conn, task_id)
                repo.resolve_mirror_field(conn, task_id, key)
            except repo.RepoError as exc:
                self._note(
                    conn, task_id, result.rejected, kind="rejected", field=key,
                    file_value=self._fmt(raw), kept_value=self._show(task, key), detail=str(exc),
                )

    def _apply_blocked_by(
        self,
        conn: sqlite3.Connection,
        task: dict[str, Any],
        parsed: ParsedFile,
        result: ImportResult,
        *,
        foreign: str | None,
    ) -> None:
        """``blocked_by: [ids]`` import (#100) — a relation, not a scalar, so it
        cannot go through :meth:`_apply_fields`'s per-field diff: the wanted set
        is diffed against the stored one and applied edge by edge, each add
        through :func:`src.tasks_repo.add_blocker` (the same cycle-guard
        rejection path :meth:`_apply_fields` gives ``parent``)."""
        fm = parsed.frontmatter
        if "blocked_by" not in fm:
            return
        task_id = task["id"]
        current_ids = sorted(b["id"] for b in task.get("blocked_by") or [])
        raw = fm["blocked_by"]
        if not isinstance(raw, list) or any(not isinstance(v, int) for v in raw):
            self._note(
                conn, task_id, result.rejected, kind="rejected", field="blocked_by",
                file_value=repr(raw), kept_value=self._fmt(current_ids),
                detail="blocked_by must be a list of task ids",
            )
            return
        wanted_ids = sorted(set(raw))
        if wanted_ids == current_ids:
            repo.resolve_mirror_field(conn, task_id, "blocked_by")
            return
        if foreign is not None:
            self._note(
                conn, task_id, result.conflicts, kind="conflict", field="blocked_by",
                file_value=self._fmt(wanted_ids), kept_value=self._fmt(current_ids), detail=foreign,
            )
            return
        any_rejected = False
        for bid in set(wanted_ids) - set(current_ids):
            try:
                repo.add_blocker(conn, task_id, bid, actor=MD_ACTOR)
                result.applied.setdefault("blocked_by", []).append(f"+{bid}")
            except repo.RepoError as exc:
                any_rejected = True
                self._note(
                    conn, task_id, result.rejected, kind="rejected", field="blocked_by",
                    file_value=f"+{bid}", kept_value=self._fmt(current_ids), detail=str(exc),
                )
        for bid in set(current_ids) - set(wanted_ids):
            try:
                repo.remove_blocker(conn, task_id, bid, actor=MD_ACTOR)
                result.applied.setdefault("blocked_by", []).append(f"-{bid}")
            except repo.RepoError as exc:
                any_rejected = True
                self._note(
                    conn, task_id, result.rejected, kind="rejected", field="blocked_by",
                    file_value=f"-{bid}", kept_value=self._fmt(current_ids), detail=str(exc),
                )
        # A field that imported cleanly clears any standing event for it, the
        # same rule every scalar field follows — but only once every edge in
        # this pass applied: a rejected edge's event must survive this call,
        # or the very note just recorded above would erase itself (#100).
        if not any_rejected:
            repo.resolve_mirror_field(conn, task_id, "blocked_by")

    @staticmethod
    def _fmt(value: Any) -> str:
        return "∅" if value is None or value == "" else str(value)

    @staticmethod
    def _show(task: dict[str, Any], key: str) -> str:
        if key == "person":
            return Mirror._fmt((task.get("person") or {}).get("name"))
        if key == "description":
            d = (task.get("description") or "").strip()
            return "∅" if not d else (d[:60] + "…" if len(d) > 60 else d)
        return Mirror._fmt(task.get(_TASK_FIELD.get(key, key)))

    def _note(
        self,
        conn: sqlite3.Connection,
        task_id: int,
        bucket: list[str],
        *,
        kind: str,
        field: str,
        file_value: str,
        kept_value: str,
        detail: str | None = None,
    ) -> None:
        message = f"import {kind} on {field}: file said {file_value}"
        if detail:
            message += f" ({detail})"
        message += f", kept {kept_value}"
        bucket.append(message)
        repo.record_mirror_event(conn, task_id, kind=kind, field=field, file_value=file_value, kept_value=kept_value)
        logger.info("ℹ️ mirror: task %d — %s", task_id, message)

    def _apply_comments(
        self, conn: sqlite3.Connection, task: dict[str, Any], parsed: ParsedFile, result: ImportResult
    ) -> None:
        # A comment's identity across the round-trip is (ts, author, body) — the
        # two axes the import cannot preserve are deliberately NOT in the key:
        #   · origin — every comment imported here is stored as MD_ACTOR whatever
        #     the line claimed, so keying on it meant a "· ui:" line never matched
        #     the row it had itself created, and was re-inserted on every pass;
        #   · a "-" author — the file's sentinel for NULL, which comes back in as
        #     the configured owner, so keying on the raw token had the same effect.
        # Both sides normalise through _comment_key so they cannot drift (#123).
        # The app's own re-export hides this (it rewrites the file to "· md:" with
        # a resolved author), so it only bites a file the app did not write:
        # hand-edited, restored by a sync client, or dropped in from elsewhere.
        known = {self._comment_key(c["ts"], c.get("author"), c.get("body")) for c in task.get("comments") or []}
        for entry in parsed.comments:
            key = self._comment_key(entry["ts"], entry["author"], entry["body"])
            if entry["ts"] is not None and key in known:
                continue
            ts = entry["ts"] if entry["ts"] and _valid_ts(entry["ts"]) else None
            repo.add_comment(conn, task["id"], entry["body"], author=key[1], origin=MD_ACTOR, ts=ts)
            known.add(key)
            result.comments_added += 1

    def _comment_key(self, ts: str | None, author: str | None, body: str | None) -> tuple[str | None, str, str]:
        """Round-trip identity of one comment — a stored row and its file line agree here."""
        name = (author or "").strip()
        return (ts, name if name and name != "-" else self.owner, (body or "").strip())

    def import_tick(self, conn: sqlite3.Connection) -> dict[str, Any]:
        """One watcher pass: import every file whose mtime moved since we wrote it."""
        report: dict[str, Any] = {"checked": 0, "imported": [], "errors": []}
        if self.dir is None:
            return report
        try:
            entries = [e for e in os.scandir(self.dir) if e.is_file() and FILE_RE.match(e.name)]
        except OSError as exc:
            logger.warning("⚠️ mirror: cannot list %s (%s)", self.dir, exc)
            return report
        states = {
            r["path"]: dict(r) for r in conn.execute("SELECT * FROM mirror_state").fetchall()
        }
        present = {e.name for e in entries}
        for name in [n for n in self._bad_files if n not in present]:
            del self._bad_files[name]  # removed from the folder → no longer a standing error
        for entry in sorted(entries, key=lambda e: e.name):
            report["checked"] += 1
            try:
                mtime_ns = entry.stat().st_mtime_ns
            except OSError:
                continue
            state = states.get(entry.name)
            if state is not None and state["file_mtime_ns"] == mtime_ns:
                continue
            if self._bad_files.get(entry.name) == mtime_ns:
                continue
            if state is None:
                m = FILE_RE.match(entry.name)
                tid = int(m.group(1)) if m else None
                exists = tid is not None and conn.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone()
                if not exists:
                    continue  # not ours (no state, no such task) — left alone
            res = self.import_file(conn, Path(entry.path))
            (report["imported"] if res.ok else report["errors"]).append(res.as_dict())
        return report

    # ------------------------------------------------------- background

    def touch(self, ids: list[int]) -> None:
        """Write-listener entry: queue ids for the debounced export."""
        if not self.enabled:
            return
        with self._lock:
            self._pending.update(int(i) for i in ids)
            self._pending_since = time.monotonic()

    def start(self) -> None:
        """Start the background thread (import first — offline edits — then a full export, then the loop)."""
        if not self.enabled or self._thread is not None:
            return
        repo.add_write_listener(self.touch)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="task-os-mirror", daemon=True)
        self._thread.start()
        logger.info("ℹ️ mirror: watching %s (export debounce %.1fs · poll %.1fs)", self.dir, self.debounce_s, self.poll_s)

    def stop(self) -> None:
        repo.remove_write_listener(self.touch)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def flush(self, conn: sqlite3.Connection) -> int:
        """Export whatever is queued now (tests / shutdown)."""
        with self._lock:
            ids = sorted(self._pending)
            self._pending.clear()
        return self.export_ids(conn, ids) if ids else 0

    def _run(self) -> None:
        conn = connect(self.db_path)
        try:
            try:
                self.import_tick(conn)
                self.export_all(conn)
            except Exception:  # noqa: BLE001
                logger.exception("❌ mirror: initial sync failed")
            last_poll = time.monotonic()
            while not self._stop.wait(0.25):
                now = time.monotonic()
                ids: list[int] = []
                with self._lock:
                    if self._pending and now - self._pending_since >= self.debounce_s:
                        ids = sorted(self._pending)
                        self._pending.clear()
                if ids:
                    try:
                        self.export_ids(conn, ids)
                    except Exception:  # noqa: BLE001
                        logger.exception("❌ mirror: debounced export failed")
                if now - last_poll >= self.poll_s:
                    last_poll = now
                    try:
                        self.import_tick(conn)
                    except Exception:  # noqa: BLE001
                        logger.exception("❌ mirror: import tick failed")
            self.flush(conn)
        finally:
            conn.close()


def _valid_ts(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _after(a: str, b: str) -> bool:
    """``a`` is strictly later than ``b`` — aware datetimes when both parse, else text order."""
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
        if (da.tzinfo is None) == (db.tzinfo is None):
            return da > db
    except ValueError:
        pass
    return a > b
