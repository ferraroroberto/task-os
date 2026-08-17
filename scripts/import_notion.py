"""One-shot, idempotent Notion → task-os importer (Step 3/13, issue #4).

    python -m scripts.import_notion --dry-run --database-id <id> --env-file E:/path/.env
    python -m scripts.import_notion --database-id <id> --env-file … [--db data/tasks.db]
    python -m scripts.import_notion --from-json dump.json --db …          # replay, no API
    python -m scripts.import_notion … --json-dump dump.json --limit 20    # smoke + keep raw

Reads a Notion *tasks* database (pages + each page's comments + body blocks +
the people relation), maps it onto the task-os schema and writes it through
``src.tasks_repo`` — the same domain layer the API and CLI use. Idempotent on
the Notion ids: tasks and comments carry ``external_id`` (schema v3), people
carry theirs in ``people.external_id``; a re-run updates what changed and
never duplicates. ``--dry-run`` fetches, maps, prints the report and writes
nothing (not even the migration).

Mapping (Notion → task-os):

    status   not started → todo · In progress → doing · Done → done (+done_at =
             last_edited_time) · null → todo, or inbox when priority = inbox
    priority high/medium/low → same · backlog → none · inbox → none · null → none
    recurrent daily/weekly/monthly → same · three months → quarterly · yearly → yearly
    Date.start → due (date part) · link → links(kind=web) · body → description (markdown)
    comments → comments(author = display_name.resolved_name, ts = created_time,
             origin = notion) in created order · connection[0] → people (+person_id),
             connection[1:] → a "also linked: <name>" comment
    every first import → ONE activity(actor = notion-import, field = imported)

Unmapped select/status values are counted in the report and fall back to the
default (status todo, priority none, recurrence none) — never silently dropped.

Token: ``NOTION_API_TOKEN`` from the OS env or the ``--env-file`` (default:
this repo's ``.env``); the database id from ``--database-id`` or
``NOTION_TASKS_DB_ID`` (env / env-file). No private identifier lives here.
REST plumbing (``api()``, token loading) follows the life-os journal script.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src import tasks_repo as repo
from src.db import connect, db_path, init_db
from src.logger import configure_logging
from src.schema import SCHEMA_VERSION, current_version

logger = logging.getLogger("import_notion")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
TOKEN_ENV = "NOTION_API_TOKEN"
DB_ID_ENV = "NOTION_TASKS_DB_ID"
NOTION_VERSION = "2022-06-28"
API_ROOT = "https://api.notion.com/v1"
ACTOR = "notion-import"
ORIGIN = "notion"
PAGE_SIZE = 100
RETRIES = 4
MAX_DEPTH = 3

STATUS_MAP = {"not started": "todo", "in progress": "doing", "done": "done"}
PRIORITY_MAP = {"high": "high", "medium": "medium", "low": "low", "backlog": "none", "inbox": "none"}
RECURRENCE_MAP = {
    "daily": "daily", "weekly": "weekly", "monthly": "monthly",
    "three months": "quarterly", "yearly": "yearly",
}


class NotionError(RuntimeError):
    """A failed Notion REST call (status + body) — the caller decides how loud."""


# ---------------------------------------------------------------- transport


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a dotenv file (quotes stripped, comments ignored)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_setting(name: str, env_file: Path) -> str | None:
    """``name`` from the OS env, else from ``env_file``; ``None`` when neither has it."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return read_env_file(env_file).get(name) or None


class NotionClient:
    """Minimal Notion REST client: one ``api()`` + the three list endpoints, paginated."""

    def __init__(self, token: str, *, version: str = NOTION_VERSION) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": version,
            "Content-Type": "application/json",
        }
        self.calls = 0

    def api(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """One call; 429 / 5xx retried with backoff (Retry-After honoured); else :class:`NotionError`."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(1, RETRIES + 1):
            req = urllib.request.Request(f"{API_ROOT}{path}", data=data, headers=self._headers, method=method)
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                    wait = float(exc.headers.get("Retry-After") or 2 ** attempt)
                    logger.warning("⚠️ notion %s %s → %d, retry %d in %.0fs", method, path, exc.code, attempt, wait)
                    time.sleep(wait)
                    continue
                raise NotionError(f"{method} {path} → {exc.code}: {detail[:300]}") from None
            except urllib.error.URLError as exc:
                if attempt < RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise NotionError(f"{method} {path} → {exc.reason}") from None
        raise NotionError(f"{method} {path} → gave up after {RETRIES} attempts")  # pragma: no cover

    def query_database(self, database_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": min(PAGE_SIZE, limit - len(pages)) if limit else PAGE_SIZE}
            if cursor:
                body["start_cursor"] = cursor
            res = self.api("POST", f"/databases/{database_id}/query", body)
            pages.extend(res.get("results", []))
            logger.info("ℹ️ notion: fetched %d pages", len(pages))
            if not res.get("has_more") or (limit and len(pages) >= limit):
                return pages[:limit] if limit else pages
            cursor = res.get("next_cursor")

    def _list(self, path: str, extra: dict[str, str] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"page_size": str(PAGE_SIZE), **(extra or {})}
            if cursor:
                params["start_cursor"] = cursor
            res = self.api("GET", f"{path}?{urllib.parse.urlencode(params)}")
            out.extend(res.get("results", []))
            if not res.get("has_more"):
                return out
            cursor = res.get("next_cursor")

    def comments(self, page_id: str) -> list[dict[str, Any]]:
        return self._list("/comments", {"block_id": page_id})

    def blocks(self, block_id: str, *, depth: int = 0) -> list[dict[str, Any]]:
        """Children of ``block_id``; nested children (quote / table rows / toggles…)
        are fetched too and attached as ``block["children"]``, up to ``MAX_DEPTH``."""
        out = self._list(f"/blocks/{block_id}/children")
        if depth < MAX_DEPTH:
            for b in out:
                if b.get("has_children") and b.get("type") not in ("child_page", "child_database"):
                    b["children"] = self.blocks(b["id"], depth=depth + 1)
        return out

    def page(self, page_id: str) -> dict[str, Any]:
        return self.api("GET", f"/pages/{page_id}")


# ------------------------------------------------------------------- fetch


def _title_of(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title") or []).strip()
    return ""


def fetch_export(client: NotionClient, database_id: str, limit: int | None = None) -> dict[str, Any]:
    """Pull pages + comments + blocks + related people into one JSON-able export.

    Shape (also what ``--json-dump`` writes and ``--from-json`` reads back)::

        {"database_id", "fetched_at", "notion_version",
         "pages": [{"page": <notion page>, "comments": [...], "blocks": [...]}],
         "people": {<notion page id>: {"name": str} | {"error": str}}}
    """
    pages = client.query_database(database_id, limit)
    entries: list[dict[str, Any]] = []
    people: dict[str, dict[str, Any]] = {}
    for n, page in enumerate(pages, 1):
        pid = page["id"]
        entry = {"page": page, "comments": client.comments(pid), "blocks": client.blocks(pid)}
        entries.append(entry)
        rel = page.get("properties", {}).get("connection", {}).get("relation") or []
        for r in rel:
            rid = r.get("id")
            if rid and rid not in people:
                try:
                    people[rid] = {"name": _title_of(client.page(rid))}
                except NotionError as exc:
                    people[rid] = {"error": str(exc)}
        if n % 25 == 0 or n == len(pages):
            logger.info("ℹ️ notion: %d/%d pages detailed (%d API calls)", n, len(pages), client.calls)
    return {
        "database_id": database_id,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notion_version": NOTION_VERSION,
        "pages": entries,
        "people": people,
    }


# ----------------------------------------------------------------- mapping


def _plain(rich: list[dict[str, Any]]) -> str:
    """Rich text → plain text, keeping explicit links as ``[text](href)``."""
    parts: list[str] = []
    for r in rich:
        text = r.get("plain_text") or ""
        href = r.get("href")
        parts.append(f"[{text}]({href})" if href and text and text != href else text)
    return "".join(parts)


def local_iso(ts: str | None) -> str | None:
    """A Notion UTC timestamp → local ISO 8601, second precision (the repo's convention)."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")


def blocks_to_markdown(blocks: list[dict[str, Any]], *, indent: str = "") -> tuple[str, Counter[str]]:
    """Notion blocks → simple markdown; returns (text, per-type counter incl. ``unknown:<type>``).

    Nested ``children`` render after their parent, indented two spaces; a
    ``table`` becomes pipe rows from its ``table_row`` children.
    """
    lines: list[str] = []
    seen: Counter[str] = Counter()
    number = 0
    for b in blocks:
        t = b.get("type", "")
        body = b.get(t) or {}
        text = _plain(body.get("rich_text") or [])
        seen[t] += 1
        if t != "numbered_list_item":
            number = 0
        if t == "table":
            for r_i, row in enumerate(b.get("children") or []):
                cells = [_plain(c) for c in (row.get("table_row") or {}).get("cells") or []]
                lines.append("| " + " | ".join(cells) + " |")
                if r_i == 0:
                    lines.append("|" + " --- |" * len(cells))
            continue
        if t == "paragraph":
            lines.append(text)
        elif t in ("heading_1", "heading_2", "heading_3"):
            lines.append(f"{'#' * int(t[-1])} {text}")
        elif t == "bulleted_list_item":
            lines.append(f"- {text}")
        elif t == "numbered_list_item":
            number += 1
            lines.append(f"{number}. {text}")
        elif t == "to_do":
            lines.append(f"- [{'x' if body.get('checked') else ' '}] {text}")
        elif t in ("quote", "callout"):
            lines.append(f"> {text}")
        elif t == "code":
            lang = body.get("language") or ""
            lines.append(f"```{lang}\n{text}\n```")
        elif t == "divider":
            lines.append("---")
        elif t == "image":
            src = body.get("external", {}).get("url") if body.get("type") == "external" else None
            caption = _plain(body.get("caption") or []) or "image"
            # Notion-hosted files are signed URLs that expire within the hour —
            # a placeholder is more honest than a dead link.
            lines.append(f"![{caption}]({src})" if src else f"[{caption}]")
        else:
            seen[f"unknown:{t}"] += 1
            if text:
                lines.append(text)
        if b.get("children"):
            nested, nested_seen = blocks_to_markdown(b["children"], indent=indent + "  ")
            if nested:
                lines.append(nested)
            seen.update(nested_seen)
    joined = "\n".join(lines).strip("\n")
    text = "\n".join(indent + line if line else line for line in joined.splitlines())
    return text, seen


@dataclass
class MappedComment:
    external_id: str
    author: str
    ts: str
    body: str


@dataclass
class MappedTask:
    external_id: str
    title: str
    status: str
    priority: str
    recurrence: str | None
    due: str | None
    description: str
    created_at: str
    updated_at: str
    done_at: str | None
    link: str | None
    person: tuple[str, str] | None                    # (notion id, name)
    also_linked: list[tuple[str, str]] = field(default_factory=list)
    comments: list[MappedComment] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)  # (kind, detail) skipped / unmapped
    raw: dict[str, str | None] = field(default_factory=dict)  # source values, for the report

    def fields(self) -> dict[str, Any]:
        return {
            "status": self.status, "priority": self.priority, "recurrence": self.recurrence,
            "due": self.due, "description": self.description,
        }


def _prop(page: dict[str, Any], name: str) -> Any:
    prop = page.get("properties", {}).get(name)
    if not prop:
        return None
    return prop.get(prop.get("type"))


def map_status(name: str | None, priority_name: str | None) -> tuple[str, str | None]:
    """→ (status, unmapped-value-or-None). null → todo, or inbox when priority = inbox."""
    if not name:
        return ("inbox" if (priority_name or "").lower() == "inbox" else "todo"), None
    mapped = STATUS_MAP.get(name.strip().lower())
    return (mapped or "todo"), (None if mapped else name)


def map_priority(name: str | None) -> tuple[str, str | None]:
    if not name:
        return "none", None
    mapped = PRIORITY_MAP.get(name.strip().lower())
    return (mapped or "none"), (None if mapped else name)


def map_recurrence(name: str | None) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    mapped = RECURRENCE_MAP.get(name.strip().lower())
    return mapped, (None if mapped else name)


def map_page(entry: dict[str, Any], people: dict[str, dict[str, Any]]) -> MappedTask:
    page = entry["page"]
    pid = page["id"]
    title = _title_of(page)
    notes: list[tuple[str, str]] = []
    if not title:
        title = "(untitled)"
        notes.append(("empty title", "→ '(untitled)'"))

    status_v = _prop(page, "status")
    status_name = status_v.get("name") if isinstance(status_v, dict) else None
    priority_v = _prop(page, "priority")
    priority_name = priority_v.get("name") if isinstance(priority_v, dict) else None
    recur_v = _prop(page, "recurrent")
    recur_name = recur_v.get("name") if isinstance(recur_v, dict) else None

    status, bad = map_status(status_name, priority_name)
    if bad:
        notes.append(("unmapped status", bad))
    priority, bad = map_priority(priority_name)
    if bad:
        notes.append(("unmapped priority", bad))
    recurrence, bad = map_recurrence(recur_name)
    if bad:
        notes.append(("unmapped recurrent", bad))

    date_v = _prop(page, "Date")
    due = None
    if isinstance(date_v, dict) and date_v.get("start"):
        due = str(date_v["start"])[:10]
        if date_v.get("end"):
            notes.append(("date range", "start kept"))

    link_v = _prop(page, "link")
    link = str(link_v).strip() if link_v else None

    description, block_types = blocks_to_markdown(entry.get("blocks") or [])
    for t, n in block_types.items():
        if t.startswith("unknown:"):
            notes.extend([("unknown block", t[8:])] * n)

    created_at = local_iso(page.get("created_time")) or repo.now_iso()
    updated_at = local_iso(page.get("last_edited_time")) or created_at
    done_at = updated_at if status == "done" else None

    rel = _prop(page, "connection") or []
    linked: list[tuple[str, str]] = []
    for r in rel:
        rid = r.get("id")
        info = people.get(rid) or {}
        name = (info.get("name") or "").strip()
        if not name:
            notes.append(("person unresolved", info.get("error", "no name")))
            continue
        linked.append((rid, name))
    person = linked[0] if linked else None
    also = linked[1:]

    comments: list[MappedComment] = []
    for c in entry.get("comments") or []:
        body = _plain(c.get("rich_text") or []).strip()
        if not body:
            notes.append(("empty comment", "skipped"))
            continue
        author = (c.get("display_name") or {}).get("resolved_name") or (c.get("created_by") or {}).get("name") or "notion"
        comments.append(MappedComment(c["id"], author, local_iso(c.get("created_time")) or created_at, body))
    comments.sort(key=lambda c: c.ts)

    return MappedTask(
        external_id=pid, title=title, status=status, priority=priority, recurrence=recurrence,
        due=due, description=description, created_at=created_at, updated_at=updated_at,
        done_at=done_at, link=link, person=person, also_linked=also, comments=comments,
        notes=notes,
        raw={"status": status_name, "priority": priority_name, "recurrent": recur_name},
    )


def map_export(export: dict[str, Any]) -> list[MappedTask]:
    people = export.get("people") or {}
    return [map_page(e, people) for e in export.get("pages") or []]


# ------------------------------------------------------------------- write


def _also_linked_id(task_external_id: str, person_external_id: str) -> str:
    return f"{task_external_id}/also-linked/{person_external_id}"


def _ensure_person(conn: sqlite3.Connection, external_id: str, name: str, counts: Counter[str]) -> int:
    row = repo.find_by_external_id(conn, "people", external_id)
    if row:
        return int(row["id"])
    same = conn.execute(
        "SELECT id FROM people WHERE external_id IS NULL AND name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if same:
        repo.update_person(conn, int(same["id"]), external_id=external_id)
        counts["people_linked"] += 1
        return int(same["id"])
    counts["people_created"] += 1
    return int(repo.create_person(conn, name, external_id=external_id)["id"])


def apply_import(conn: sqlite3.Connection, mapped: list[MappedTask]) -> Counter[str]:
    """Write every mapped page through the repo; returns the per-outcome counters."""
    counts: Counter[str] = Counter()
    for m in mapped:
        person_id = _ensure_person(conn, *m.person, counts) if m.person else None
        task, outcome = repo.import_task(
            conn, external_id=m.external_id, title=m.title, actor=ACTOR,
            created_at=m.created_at, updated_at=m.updated_at, done_at=m.done_at,
            person_id=person_id, **m.fields(),
        )
        counts[f"tasks_{outcome}"] += 1
        tid = task["id"]

        if m.link and not any(link["url"] == m.link for link in task["links"]):
            repo.add_link(conn, tid, m.link, kind="web")
            counts["links_added"] += 1

        for c in m.comments:
            if repo.find_by_external_id(conn, "comments", c.external_id):
                counts["comments_existing"] += 1
                continue
            repo.add_comment(conn, tid, c.body, author=c.author, origin=ORIGIN, ts=c.ts, external_id=c.external_id)
            counts["comments_added"] += 1

        for rid, name in m.also_linked:
            ext = _also_linked_id(m.external_id, rid)
            if repo.find_by_external_id(conn, "comments", ext):
                continue
            repo.add_comment(conn, tid, f"also linked: {name}", author=ACTOR, origin=ORIGIN, ts=m.created_at, external_id=ext)
            counts["also_linked_added"] += 1
    return counts


def plan_import(conn: sqlite3.Connection | None, mapped: list[MappedTask]) -> Counter[str]:
    """What a write *would* do against ``conn`` (read-only); all "create" when there is no DB yet."""
    counts: Counter[str] = Counter()
    for m in mapped:
        existing = repo.find_by_external_id(conn, "tasks", m.external_id) if conn else None
        if existing is None:
            counts["tasks_create"] += 1
            counts["comments_add"] += len(m.comments)
            counts["also_linked_add"] += len(m.also_linked)
            continue
        diff = repo.import_diff(existing, title=m.title, done_at=m.done_at, **m.fields())
        counts["tasks_update" if diff else "tasks_unchanged"] += 1
        for c in m.comments:
            counts["comments_add" if repo.find_by_external_id(conn, "comments", c.external_id) is None else "comments_existing"] += 1
        for rid, _ in m.also_linked:
            if repo.find_by_external_id(conn, "comments", _also_linked_id(m.external_id, rid)) is None:
                counts["also_linked_add"] += 1
    return counts


# ------------------------------------------------------------------ report


def summarize(mapped: list[MappedTask]) -> dict[str, Any]:
    """Counts only — no titles, names or links (safe to paste into a public record)."""
    status = Counter(m.status for m in mapped)
    priority = Counter(m.priority for m in mapped)
    recurrence = Counter(m.recurrence or "none" for m in mapped)
    raw_status = Counter(m.raw["status"] or "null" for m in mapped)
    raw_priority = Counter(m.raw["priority"] or "null" for m in mapped)
    raw_recur = Counter(m.raw["recurrent"] or "null" for m in mapped)
    people = {m.person[0] for m in mapped if m.person} | {rid for m in mapped for rid, _ in m.also_linked}
    threads = [len(m.comments) for m in mapped]
    notes = Counter(kind for m in mapped for kind, _ in m.notes)
    unmapped = {
        kind: sorted({detail for m in mapped for k, detail in m.notes if k == kind})
        for kind in ("unmapped status", "unmapped priority", "unmapped recurrent", "unknown block")
    }
    return {
        "pages": len(mapped),
        "status": dict(status), "priority": dict(priority), "recurrence": dict(recurrence),
        "source_status": dict(raw_status), "source_priority": dict(raw_priority), "source_recurrent": dict(raw_recur),
        "due_set": sum(1 for m in mapped if m.due),
        "with_link": sum(1 for m in mapped if m.link),
        "with_body": sum(1 for m in mapped if m.description),
        "comments_total": sum(threads),
        "pages_with_comments": sum(1 for n in threads if n),
        "longest_thread": max(threads, default=0),
        "people_distinct": len(people),
        "pages_with_person": sum(1 for m in mapped if m.person),
        "also_linked_comments": sum(len(m.also_linked) for m in mapped),
        "notes": dict(notes),
        "unmapped_values": {k: v for k, v in unmapped.items() if v},
    }


def _fmt(d: dict[str, Any]) -> str:
    return " · ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], str(kv[0])))) or "—"


def render_report(summary: dict[str, Any], plan: Counter[str], *, dry_run: bool, db: Path, applied: Counter[str] | None = None) -> str:
    head = "Notion import — DRY RUN (nothing written)" if dry_run else "Notion import — applied"
    lines = [
        head,
        f"  target db  : {db}",
        f"  pages      : {summary['pages']}",
        f"  status     : {_fmt(summary['status'])}   (source: {_fmt(summary['source_status'])})",
        f"  priority   : {_fmt(summary['priority'])}   (source: {_fmt(summary['source_priority'])})",
        f"  recurrence : {_fmt(summary['recurrence'])}   (source: {_fmt(summary['source_recurrent'])})",
        f"  due dates  : {summary['due_set']} set",
        f"  links      : {summary['with_link']} pages with a link",
        f"  body       : {summary['with_body']} pages with content",
        f"  comments   : {summary['comments_total']} on {summary['pages_with_comments']} pages (longest thread {summary['longest_thread']})",
        f"  people     : {summary['people_distinct']} distinct in relations · {summary['pages_with_person']} pages get a person · {summary['also_linked_comments']} extra relations → 'also linked' comments",
        f"  notes      : {_fmt(summary['notes'])}",
    ]
    for kind, values in summary["unmapped_values"].items():
        lines.append(f"               {kind}: {', '.join(values)}")
    if applied is not None:
        lines.append(
            f"  result     : tasks created {applied['tasks_created']} · updated {applied['tasks_updated']} · unchanged {applied['tasks_unchanged']}"
            f" · comments added {applied['comments_added']} (existing {applied['comments_existing']}) · also-linked {applied['also_linked_added']}"
            f" · links {applied['links_added']} · people created {applied['people_created']} (linked {applied['people_linked']})"
        )
    else:
        lines.append(
            f"  plan       : tasks create {plan['tasks_create']} · update {plan['tasks_update']} · unchanged {plan['tasks_unchanged']}"
            f" · comments add {plan['comments_add']} (existing {plan['comments_existing']}) · also-linked add {plan['also_linked_add']}"
        )
    return "\n".join(lines)


# -------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="import_notion", description=__doc__.split("\n\n")[0])
    p.add_argument("--dry-run", action="store_true", help="fetch + map + report; write nothing")
    p.add_argument("--db", type=Path, default=None, help="SQLite file (default: the app's data/tasks.db / TASKOS_DB_PATH)")
    p.add_argument("--database-id", default=None, help=f"Notion tasks database id (or {DB_ID_ENV} in env / env-file)")
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help=f"dotenv holding {TOKEN_ENV} (default: ./.env)")
    p.add_argument("--limit", type=int, default=None, help="fetch at most N pages (smoke runs)")
    p.add_argument("--json-dump", type=Path, default=None, help="save the raw fetched export here")
    p.add_argument("--from-json", type=Path, default=None, help="replay a saved export instead of calling the API")
    return p


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    target_db = args.db or db_path()

    if args.from_json:
        export = json.loads(args.from_json.read_text(encoding="utf-8"))
        logger.info("ℹ️ replaying %s (%d pages)", args.from_json, len(export.get("pages") or []))
    else:
        token = load_setting(TOKEN_ENV, args.env_file)
        if not token:
            logger.error("❌ %s not set (OS env or %s)", TOKEN_ENV, args.env_file)
            return 1
        database_id = args.database_id or load_setting(DB_ID_ENV, args.env_file)
        if not database_id:
            logger.error("❌ no database id: pass --database-id or set %s", DB_ID_ENV)
            return 1
        client = NotionClient(token)
        try:
            export = fetch_export(client, database_id, args.limit)
        except NotionError as exc:
            logger.error("❌ notion: %s", exc)
            return 1
        logger.info("ℹ️ notion: %d pages, %d API calls", len(export["pages"]), client.calls)

    if args.json_dump:
        args.json_dump.parent.mkdir(parents=True, exist_ok=True)
        args.json_dump.write_text(json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info("ℹ️ raw export saved → %s", args.json_dump)

    mapped = map_export(export)
    if args.limit and args.from_json:
        mapped = mapped[: args.limit]
    summary = summarize(mapped)

    if args.dry_run:
        # Read-only look at an existing DB (plain connect, SELECTs only — no
        # migration, no pragma, no file created) so the plan can say what a
        # write would create / update / leave alone.
        conn: sqlite3.Connection | None = None
        if target_db.exists():
            conn = sqlite3.connect(target_db)
            conn.row_factory = sqlite3.Row
            if current_version(conn) < SCHEMA_VERSION:
                logger.info("ℹ️ dry run: %s is at schema v%d (< %d) — plan assumes nothing imported yet", target_db, current_version(conn), SCHEMA_VERSION)
                conn.close()
                conn = None
        try:
            plan = plan_import(conn, mapped)
        finally:
            if conn:
                conn.close()
        print(render_report(summary, plan, dry_run=True, db=target_db))
        return 0

    init_db(target_db)
    conn = connect(target_db)
    try:
        applied = apply_import(conn, mapped)
    finally:
        conn.close()
    print(render_report(summary, Counter(), dry_run=False, db=target_db, applied=applied))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main())
