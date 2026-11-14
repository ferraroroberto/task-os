"""One-shot, idempotent SharePoint list → task-os importer.

    python -m src.imports.sharepoint --from-json dump.json --mapping config/sharepoint-mapping.json --dry-run
    python -m src.imports.sharepoint --from-json dump.json --mapping config/sharepoint-mapping.json [--db data/tasks.db]

Reads the JSON dump the owner takes from a signed-in browser (SharePoint's REST
API, no token needed here — ``docs/sharepoint-import.md`` has the console
script), maps it onto the task-os schema and writes it through
``src.tasks_repo``, the same domain layer the API and CLI use. Nothing is
fetched over the network: the dump is the only input.

Idempotent on the SharePoint item id: the task carries
``sharepoint:<list-id>:<item-id>`` as ``external_id``; comments, replies and
version entries add ``:c<id>``, ``:c<id>:r<id>`` and ``:v<column>:<version-id>``.
A re-run updates what changed in the source and never duplicates.
``--dry-run`` maps, prints the report and writes nothing (not even the migration).

Mapping (the mapping file names the columns, ``config/sharepoint-mapping.sample.json``):

    title / description / due   one column each; description is the column's text
    status / priority           a choice column + a value → task value table; an
                                unknown value is counted and falls back to the default
    person                      a person column → the task's contact (``people``)
    owner                       a person column + a display name → member id table
    append_columns              "append changes" text columns: one comment per version
                                holding only the text that version added
    text_columns                columns whose URLs also become web links
    comments + replies          comments(origin = sharepoint), oldest first, each reply
                                right after its parent
    attachments                 web links back to the list (no file is copied)
    every first import          ONE activity(actor = sharepoint-import, field = imported)
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src import tasks_repo as repo
from src.config import load_config
from src.db import connect, db_path, init_db
from src.imports.common import ensure_person, fmt_counts, plan_against
from src.logger import configure_logging
from src.schema import TASK_PRIORITIES, TASK_STATUSES, TaskStatus

logger = logging.getLogger("import_sharepoint")

ACTOR = "sharepoint-import"
ORIGIN = "sharepoint"
DEFAULT_PRIORITY = "none"
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
URL_TRAILING = ".,;:!?"
BREAKS_RE = re.compile(r"</(?:p|div|li)>|<br\s*/?>", re.IGNORECASE)
TAGS_RE = re.compile(r"<[^>]+>")


class DumpError(ValueError):
    """The dump or the mapping is not usable; the message says what is missing."""


# ----------------------------------------------------------------- helpers


def local_iso(ts: str | None) -> str | None:
    """A SharePoint UTC timestamp → local ISO 8601, second precision (the repo's convention)."""
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")


def plain_text(value: Any) -> str:
    """A column value → plain text: HTML line breaks kept as newlines, tags and entities removed."""
    if value is None:
        return ""
    text = BREAKS_RE.sub("\n", str(value))
    text = html.unescape(TAGS_RE.sub("", text)).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def find_urls(text: str) -> list[str]:
    """Every http(s) URL in ``text``, trailing punctuation dropped, first-seen order, no repeats."""
    seen: dict[str, None] = {}
    for match in URL_RE.findall(text):
        seen.setdefault(match.rstrip(URL_TRAILING), None)
    return list(seen)


def _first_name(value: str) -> str:
    """The first of a ``;``-separated list of display names."""
    return value.split(";")[0].strip()


# ----------------------------------------------------------------- mapping


@dataclass
class Mapping:
    title: str = "Title"
    description: str | None = None
    due: str | None = None
    status_column: str | None = None
    status_values: dict[str, str] = field(default_factory=dict)
    priority_column: str | None = None
    priority_values: dict[str, str] = field(default_factory=dict)
    person_column: str | None = None
    owner_column: str | None = None
    owner_members: dict[str, str] = field(default_factory=dict)
    append_columns: list[str] = field(default_factory=list)
    text_columns: list[str] = field(default_factory=list)


def load_mapping(path: Path | None) -> Mapping:
    """The mapping file as a :class:`Mapping`; no file = title only, every default."""
    if path is None:
        return Mapping()
    raw = json.loads(path.read_text(encoding="utf-8"))
    status, priority = raw.get("status") or {}, raw.get("priority") or {}
    person, owner = raw.get("person") or {}, raw.get("owner") or {}
    return Mapping(
        title=raw.get("title") or "Title",
        description=raw.get("description"),
        due=raw.get("due"),
        status_column=status.get("column"),
        status_values=dict(status.get("values") or {}),
        priority_column=priority.get("column"),
        priority_values=dict(priority.get("values") or {}),
        person_column=person.get("column"),
        owner_column=owner.get("column"),
        owner_members=dict(owner.get("members") or {}),
        append_columns=list(raw.get("append_columns") or []),
        text_columns=list(raw.get("text_columns") or []),
    )


@dataclass
class MappedComment:
    external_id: str
    author: str
    ts: str
    body: str


@dataclass
class MappedTask:
    item_id: int
    external_id: str
    title: str
    status: str
    priority: str
    due: str | None
    description: str
    created_at: str
    updated_at: str
    done_at: str | None
    owner: str | None
    person: tuple[str, str] | None                    # (external id, display name)
    links: list[tuple[str, str | None]] = field(default_factory=list)   # (url, label), item link first
    comments: list[MappedComment] = field(default_factory=list)
    versions: int = 0
    notes: list[tuple[str, str]] = field(default_factory=list)   # (kind, detail) unmapped / skipped
    raw: dict[str, str | None] = field(default_factory=dict)     # source values, for the report

    def fields(self) -> dict[str, Any]:
        return {
            "status": self.status, "priority": self.priority, "due": self.due,
            "description": self.description, "owner": self.owner,
        }


def _column_value(item: dict[str, Any], column: str | None) -> Any:
    """A column's raw value, else its text rendering (people and lookups only have the latter)."""
    if not column:
        return None
    value = item.get(column)
    if value in (None, "") or isinstance(value, (dict, list)):
        value = (item.get("FieldValuesAsText") or {}).get(column)
    return None if value in (None, "") else value


def _column_text(item: dict[str, Any], column: str | None) -> str:
    return plain_text(_column_value(item, column))


def _choice(table: dict[str, str], valid: tuple[str, ...], raw: str | None) -> tuple[str | None, str | None]:
    """→ (mapped value or None, unmapped source value or None); a table entry outside ``valid`` is unmapped."""
    if not raw:
        return None, None
    mapped = table.get(raw.strip())
    return (mapped, None) if mapped in valid else (None, raw.strip())


def _append_entries(item: dict[str, Any], column: str, notes: list[tuple[str, str]]) -> list[tuple[str, str, str, int]]:
    """One ``(author, ts, text, version-id)`` per version that added text to an append column.

    SharePoint keeps the whole history in the column; a version's added text is
    what it holds beyond the previous version (a prefix or a suffix, depending
    on which end the list stacks new entries). A version that extends neither
    way is kept whole and counted as a note.
    """
    out: list[tuple[str, str, str, int]] = []
    previous = ""
    for version in sorted(item.get("_versions") or [], key=lambda v: int(v.get("VersionId") or 0)):
        text = plain_text(version.get(column))
        if not text or text == previous:
            continue
        if previous and text.startswith(previous):
            added = text[len(previous):].strip()
        elif previous and text.endswith(previous):
            added = text[: -len(previous)].strip()
        else:
            added = text
            if previous:
                notes.append(("append column rewritten", column))
        previous = text
        if added:
            editor = (version.get("Editor") or {}).get("LookupValue") or "sharepoint"
            out.append((editor, local_iso(version.get("Created")) or "", added, int(version.get("VersionId") or 0)))
    return out


def _thread(item: dict[str, Any], prefix: str, fallback_ts: str, notes: list[tuple[str, str]]) -> list[MappedComment]:
    """SharePoint comments oldest first, every reply directly after its parent."""
    out: list[MappedComment] = []

    def make(raw: dict[str, Any], ext: str) -> MappedComment | None:
        body = plain_text(raw.get("text"))
        if not body:
            notes.append(("empty comment", "skipped"))
            return None
        author = (raw.get("author") or {}).get("name") or ORIGIN
        return MappedComment(ext, author, local_iso(raw.get("createdDate")) or fallback_ts, body)

    for parent in sorted(item.get("_comments") or [], key=lambda c: str(c.get("createdDate") or "")):
        top = make(parent, f"{prefix}:c{parent.get('id')}")
        if top:
            out.append(top)
        for reply in sorted(parent.get("_replies") or [], key=lambda r: str(r.get("createdDate") or "")):
            mapped = make(reply, f"{prefix}:c{parent.get('id')}:r{reply.get('id')}")
            if mapped:
                out.append(mapped)
    return out


def map_item(item: dict[str, Any], mapping: Mapping, ctx: dict[str, Any]) -> MappedTask:
    """One dump item → a :class:`MappedTask`.

    ``ctx`` carries the dump's ``list_id`` / ``site`` / ``origin`` and the
    install's ``members`` (owner first).
    """
    item_id = int(item["Id"])
    prefix = f"sharepoint:{ctx['list_id']}:{item_id}"
    notes: list[tuple[str, str]] = []
    title = _column_text(item, mapping.title)
    if not title:
        title = "(untitled)"
        notes.append(("empty title", "→ '(untitled)'"))

    status_raw = _column_text(item, mapping.status_column) or None
    priority_raw = _column_text(item, mapping.priority_column) or None
    status, bad = _choice(mapping.status_values, TASK_STATUSES, status_raw)
    if bad:
        notes.append(("unmapped status", bad))
    priority, bad = _choice(mapping.priority_values, TASK_PRIORITIES, priority_raw)
    if bad:
        notes.append(("unmapped priority", bad))

    due_raw = _column_value(item, mapping.due)
    due = str(due_raw)[:10] if due_raw else None

    created_at = local_iso(item.get("Created")) or repo.now_iso()
    updated_at = local_iso(item.get("Modified")) or created_at
    status = status or TaskStatus.TODO.value
    done_at = updated_at if status == TaskStatus.DONE.value else None

    person: tuple[str, str] | None = None
    person_text = _column_text(item, mapping.person_column)
    if person_text:
        name = _first_name(person_text)
        person = (f"sharepoint:{ctx['list_id']}:person:{name.casefold()}", name)
        if ";" in person_text:
            notes.append(("extra people", "first kept"))

    owner: str | None = None
    owner_text = _first_name(_column_text(item, mapping.owner_column))
    if owner_text:
        member = mapping.owner_members.get(owner_text)
        if member is None:
            notes.append(("unmapped owner", owner_text))
        elif member not in ctx["members"]:
            notes.append(("unknown member", member))
        elif member != ctx["members"][0]:
            owner = member   # the install owner stays NULL: that is what NULL already means

    description = _column_text(item, mapping.description)
    comments = _thread(item, prefix, created_at, notes)
    appended: list[str] = []
    for column in mapping.append_columns:
        for editor, ts, text, version_id in _append_entries(item, column, notes):
            label = f"{column}: " if len(mapping.append_columns) > 1 else ""
            comments.append(MappedComment(f"{prefix}:v{column}:{version_id}", editor, ts or created_at, label + text))
            appended.append(text)
    comments.sort(key=lambda c: c.ts)   # stable: a reply keeps its place after its parent

    urls: dict[str, str | None] = {}
    texts = [_column_text(item, column) for column in mapping.text_columns] + [c.body for c in comments]
    for url in (u for text in texts for u in find_urls(text)):
        urls.setdefault(url, None)
    links: list[tuple[str, str | None]] = [
        (f"{ctx['site']}/_layouts/15/listform.aspx?PageType=4&ListId={ctx['list_id']}&ID={item_id}", "SharePoint item"),
        *urls.items(),
    ]
    for att in item.get("AttachmentFiles") or []:
        if att.get("ServerRelativeUrl"):
            links.append((ctx["origin"] + str(att["ServerRelativeUrl"]), att.get("FileName")))

    return MappedTask(
        item_id=item_id, external_id=prefix, title=title, status=status,
        priority=priority or DEFAULT_PRIORITY, due=due, description=description,
        created_at=created_at, updated_at=updated_at, done_at=done_at, owner=owner,
        person=person, links=links, comments=comments, versions=len(item.get("_versions") or []),
        notes=notes, raw={"status": status_raw, "priority": priority_raw},
    )


def map_dump(dump: dict[str, Any], mapping: Mapping, members: Sequence[str]) -> list[MappedTask]:
    """Validate the dump's envelope, then map every item; ``members`` are the install's ids, owner first."""
    list_id = (dump.get("list") or {}).get("id")
    site = str(dump.get("site") or "").rstrip("/")
    if not list_id or not site or not isinstance(dump.get("items"), list):
        raise DumpError("the dump needs `site`, `list.id` and an `items` list")
    parts = urlsplit(site)
    ctx = {"list_id": list_id, "site": site, "origin": f"{parts.scheme}://{parts.netloc}", "members": tuple(members)}
    return [map_item(item, mapping, ctx) for item in dump["items"]]


# ------------------------------------------------------------------- write


def _write_item(conn: sqlite3.Connection, m: MappedTask, counts: Counter[str]) -> None:
    """One item: the task, then its links and comments, each skipped when already there."""
    contact = ensure_person(conn, *m.person, counts) if m.person else None
    task, outcome = repo.import_task(
        conn, external_id=m.external_id, title=m.title, actor=ACTOR,
        created_at=m.created_at, updated_at=m.updated_at, done_at=m.done_at,
        person_id=contact, **m.fields(),
    )
    counts[f"tasks_{outcome}"] += 1

    known = {link["url"] for link in task["links"]}
    for url, label in m.links:
        if url not in known:
            repo.add_link(conn, task["id"], url, label=label, kind="web")
            known.add(url)
            counts["links_added"] += 1

    for c in m.comments:
        if repo.find_by_external_id(conn, "comments", c.external_id):
            counts["comments_existing"] += 1
            continue
        repo.add_comment(conn, task["id"], c.body, author=c.author, origin=ORIGIN, ts=c.ts, external_id=c.external_id)
        counts["comments_added"] += 1


def apply_import(conn: sqlite3.Connection, mapped: list[MappedTask]) -> Counter[str]:
    """Write every mapped item; the counters say what each kind of write did."""
    counts: Counter[str] = Counter()
    for m in mapped:
        _write_item(conn, m, counts)
    return counts


def plan_import(conn: sqlite3.Connection | None, mapped: list[MappedTask]) -> Counter[str]:
    """What a write *would* do against ``conn`` (read-only); all "create" when there is no DB yet."""
    counts: Counter[str] = Counter()
    for m in mapped:
        existing = repo.find_by_external_id(conn, "tasks", m.external_id) if conn else None
        if existing is None:
            counts["tasks_create"] += 1
            counts["comments_add"] += len(m.comments)
            continue
        diff = repo.import_diff(existing, title=m.title, done_at=m.done_at, **m.fields())
        counts["tasks_update" if diff else "tasks_unchanged"] += 1
        for c in m.comments:
            counts["comments_add" if repo.find_by_external_id(conn, "comments", c.external_id) is None else "comments_existing"] += 1
    return counts


# ------------------------------------------------------------------ report


def summarize(dump: dict[str, Any], mapped: list[MappedTask], mapping: Mapping) -> dict[str, Any]:
    """Counts, plus the unmapped values the owner needs to fill the mapping. Never a title or a comment."""
    items = dump["items"]
    columns = {
        f.get("InternalName"): f.get("TypeAsString") or "?"
        for f in dump.get("fields") or [] if f.get("InternalName")
    }
    filled = {
        name: sum(1 for item in items if _column_value(item, name) is not None)
        for name in sorted(columns)
        if any(_column_value(item, name) is not None for item in items)
    }
    threads = [len(m.comments) for m in mapped]
    notes = Counter(kind for m in mapped for kind, _ in m.notes)
    needs_mapping = ("unmapped status", "unmapped priority", "unmapped owner", "unknown member")
    unmapped = {kind: sorted({d for m in mapped for k, d in m.notes if k == kind}) for kind in needs_mapping}
    return {
        "items": len(mapped),
        "columns": {name: (columns[name], count) for name, count in filled.items()},
        "status": dict(Counter(m.status for m in mapped)),
        "priority": dict(Counter(m.priority for m in mapped)),
        "source_status": dict(Counter(m.raw["status"] or "null" for m in mapped)),
        "source_priority": dict(Counter(m.raw["priority"] or "null" for m in mapped)),
        "due_set": sum(1 for m in mapped if m.due),
        "with_body": sum(1 for m in mapped if m.description),
        "with_person": sum(1 for m in mapped if m.person),
        "with_owner": sum(1 for m in mapped if m.owner),
        "links": sum(len(m.links) for m in mapped),
        "comments_total": sum(threads),
        "items_with_comments": sum(1 for n in threads if n),
        "versions_total": sum(m.versions for m in mapped),
        "per_item": [(m.item_id, len(m.comments), m.versions) for m in mapped],
        "append_columns": list(mapping.append_columns),
        "notes": dict(notes),
        "unmapped_values": {kind: values for kind, values in unmapped.items() if values},
    }


def render_report(summary: dict[str, Any], plan: Counter[str], *, dry_run: bool, db: Path, applied: Counter[str] | None = None) -> str:
    lines = [
        "SharePoint import — DRY RUN (nothing written)" if dry_run else "SharePoint import — applied",
        f"  target db  : {db}",
        f"  items      : {summary['items']}",
        f"  status     : {fmt_counts(summary['status'])}   (source: {fmt_counts(summary['source_status'])})",
        f"  priority   : {fmt_counts(summary['priority'])}   (source: {fmt_counts(summary['source_priority'])})",
        f"  due dates  : {summary['due_set']} set · body {summary['with_body']} · contact {summary['with_person']} · owner {summary['with_owner']}",
        f"  links      : {summary['links']} (item link, URLs in text, attachments)",
        f"  comments   : {summary['comments_total']} on {summary['items_with_comments']} items (versions read: {summary['versions_total']})",
        f"  notes      : {fmt_counts(summary['notes'])}",
        "  columns    : " + (" · ".join(f"{n} ({t}) {c}" for n, (t, c) in summary["columns"].items()) or "—"),
    ]
    for kind, values in summary["unmapped_values"].items():
        lines.append(f"               {kind}: {', '.join(values)}")
    lines.append("  per item   : id comments versions")
    lines.extend(f"               {i} {c} {v}" for i, c, v in summary["per_item"])
    if applied is not None:
        lines.append(
            f"  result     : tasks created {applied['tasks_created']} · updated {applied['tasks_updated']} · unchanged {applied['tasks_unchanged']}"
            f" · comments added {applied['comments_added']} (existing {applied['comments_existing']})"
            f" · links {applied['links_added']} · people created {applied['people_created']} (linked {applied['people_linked']})"
        )
    else:
        lines.append(
            f"  plan       : tasks create {plan['tasks_create']} · update {plan['tasks_update']} · unchanged {plan['tasks_unchanged']}"
            f" · comments add {plan['comments_add']} (existing {plan['comments_existing']})"
        )
    return "\n".join(lines)


# -------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="import_sharepoint", description=__doc__.split("\n\n")[0])
    p.add_argument("--from-json", type=Path, required=True, help="the browser export (see docs/sharepoint-import.md)")
    p.add_argument("--mapping", type=Path, default=None, help="column / value mapping file (config/sharepoint-mapping.json)")
    p.add_argument("--dry-run", action="store_true", help="map + report; write nothing")
    p.add_argument("--db", type=Path, default=None, help="SQLite file (default: the app's data/tasks.db / TASKOS_DB_PATH)")
    return p


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    target_db = args.db or db_path()
    try:
        dump = json.loads(args.from_json.read_text(encoding="utf-8"))
        mapping = load_mapping(args.mapping)
        members = [p.id for p in load_config().people]
        repo.set_members(members)
        mapped = map_dump(dump, mapping, members)
    except (OSError, ValueError) as exc:
        logger.error("❌ sharepoint import: %s", exc)
        return 1
    logger.info("ℹ️ replaying %s (%d items)", args.from_json, len(mapped))
    print(run(mapped, summarize(dump, mapped, mapping), target_db, dry_run=args.dry_run))
    return 0


def run(mapped: list[MappedTask], summary: dict[str, Any], target_db: Path, *, dry_run: bool) -> str:
    """The report of one pass: a dry run reads ``target_db`` and writes nothing; a real one migrates and writes it."""
    if dry_run:
        return render_report(summary, plan_against(target_db, plan_import, mapped), dry_run=True, db=target_db)
    init_db(target_db)
    conn = connect(target_db)
    try:
        applied = apply_import(conn, mapped)
    finally:
        conn.close()
    return render_report(summary, Counter(), dry_run=False, db=target_db, applied=applied)


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main())
