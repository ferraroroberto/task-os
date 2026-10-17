"""One-time import of the time-tracker prototype's database export (#457).

The prototype (a private claude.ai artifact) kept its data in a document store.
Its export is a folder with one JSON file per document, file name = document id:

    entries/<id>.json   {who, cat, min, date "YYYY-MM-DD", note, at <ms when saved>}
    guesses/<who>.json  {pct, at}
    timers/<who>.json   {cat, start <ms>}     — ephemeral, never imported

This script maps that onto the v19 tables through ``src/time_repo.import_rows``:

- **Idempotent on the document id** (``time_entries.source_id``): a second run
  inserts nothing. A guess already in task-os is never overwritten.
- **No invented clock range**: the prototype saved a duration and the save
  moment, never a start or a stop, so every imported entry is duration-only.
- ``who`` must be a configured ``time.people`` id, and ``cat`` a Home-area
  category slug (the seed carries the prototype's ten). Any unknown person or
  category is **refused before anything is written**: exit 2 with the list.
  ``--skip-unknown-people`` skips (and counts) unknown people's rows instead.
- Rows the prototype's own Totals ignore (``min <= 0``, a malformed date) are
  skipped and counted, so the imported totals match its Totals view.
- Possible duplicates (same person, category, minutes and day, saved within
  :data:`DUPLICATE_WINDOW_SECONDS` of each other — early save retries) are
  reported by id and imported as they are; deleting one is the owner's call.

The target is the usual database (``TASKOS_DB_PATH`` overrides it — run against
a scratch copy first) and the usual config (``TASKOS_CONFIG_PATH``).

Usage:
    .venv/Scripts/python.exe scripts/import_time_prototype.py <export dir> [--skip-unknown-people]

Exit codes: 0 imported (or nothing new), 2 refused (nothing written).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import clock  # noqa: E402
from src import time_repo as repo  # noqa: E402
from src.config import load_config  # noqa: E402
from src.db import connect, db_path, init_db  # noqa: E402
from src.logger import configure_logging  # noqa: E402

logger = logging.getLogger("import_time_prototype")

#: The area the prototype's categories live in (the v19 seed puts them there).
PROTOTYPE_AREA = "home"
#: Two identical rows saved this close together look like a save retry.
DUPLICATE_WINDOW_SECONDS = 120
REFUSED = 2
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Plan:
    """What an import would write, and everything it would leave out."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    guesses: list[dict[str, Any]] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    unknown_people: set[str] = field(default_factory=set)
    unknown_categories: set[str] = field(default_factory=set)
    duplicates: list[list[str]] = field(default_factory=list)
    timers: int = 0
    truncated_notes: int = 0


def _documents(folder: Path) -> list[tuple[str, Any]]:
    """``(document id, parsed JSON)`` per file, in id order; a missing folder is empty."""
    if not folder.is_dir():
        return []
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(folder.glob("*.json"))]


def _saved_at(ms: Any) -> str:
    """The prototype's ``at`` (epoch ms) as the local ISO stamp the tables use."""
    if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
        return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")
    return clock.now_iso()


def build_plan(export: Path, *, people: tuple[str, ...], categories: dict[str, int],
               skip_unknown_people: bool) -> Plan:
    """Read the export and decide every row, writing nothing."""
    plan = Plan()
    kept: list[tuple[str, dict[str, Any]]] = []
    for doc_id, doc in _documents(export / "entries"):
        if not isinstance(doc, dict):
            plan.skipped["not an object"] += 1
            continue
        who, minutes, day = doc.get("who"), doc.get("min"), doc.get("date")
        if who not in people:
            if skip_unknown_people:
                plan.skipped["unknown person"] += 1
            else:
                plan.unknown_people.add(str(who))
            continue
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
            plan.skipped["minutes not above zero"] += 1
            continue
        if not isinstance(day, str) or not _DAY_RE.match(day):
            plan.skipped["malformed date"] += 1
            continue
        if round(minutes) > repo.MAX_MINUTES:
            plan.skipped[f"over {repo.MAX_MINUTES} minutes"] += 1
            continue
        category_id = categories.get(str(doc.get("cat")))
        if category_id is None:
            plan.unknown_categories.add(str(doc.get("cat")))
            continue
        note = str(doc.get("note") or "").strip()
        if len(note) > repo.MAX_NOTE_CHARS:
            note = note[: repo.MAX_NOTE_CHARS]
            plan.truncated_notes += 1
        plan.entries.append({
            "source_id": doc_id, "person": who, "category_id": category_id, "day": day,
            "minutes": max(1, round(minutes)), "note": note, "created_at": _saved_at(doc.get("at")),
        })
        kept.append((doc_id, doc))

    groups: dict[tuple[Any, ...], list[tuple[float, str]]] = {}
    for doc_id, doc in kept:
        key = (doc["who"], doc.get("cat"), doc["min"], doc["date"])
        groups.setdefault(key, []).append((float(doc.get("at") or 0), doc_id))
    for rows in groups.values():
        rows.sort()
        run = [rows[0][1]] if rows else []
        for (prev_at, _), (at, doc_id) in zip(rows, rows[1:], strict=False):
            if at - prev_at <= DUPLICATE_WINDOW_SECONDS * 1000:
                run.append(doc_id)
            else:
                if len(run) > 1:
                    plan.duplicates.append(run)
                run = [doc_id]
        if len(run) > 1:
            plan.duplicates.append(run)

    for who, doc in _documents(export / "guesses"):
        if who not in people:
            if skip_unknown_people:
                plan.skipped["unknown person (guess)"] += 1
            else:
                plan.unknown_people.add(who)
            continue
        pct = doc.get("pct") if isinstance(doc, dict) else None
        if not isinstance(pct, (int, float)) or isinstance(pct, bool) or not 0 <= pct <= 100:
            plan.skipped["malformed guess"] += 1
            continue
        plan.guesses.append({"person": who, "pct": round(pct), "updated_at": _saved_at(doc.get("at"))})
    plan.timers = len(_documents(export / "timers"))
    return plan


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="import the time-tracker prototype's export (idempotent)")
    parser.add_argument("export", type=Path, help="the export folder (holds entries/, guesses/, timers/)")
    parser.add_argument("--skip-unknown-people", action="store_true",
                        help="skip and count rows of people not in time.people instead of refusing")
    args = parser.parse_args(argv)

    if not (args.export / "entries").is_dir():
        logger.error("❌ %s has no entries/ folder — not a prototype export", args.export)
        return REFUSED
    people = load_config().time.ids
    target = db_path()
    init_db(target)
    conn = connect(target)
    try:
        categories = {
            c["slug"]: c["id"]
            for a in repo.list_areas(conn) if a["slug"] == PROTOTYPE_AREA for c in a["categories"]
        }
        plan = build_plan(args.export, people=people, categories=categories,
                          skip_unknown_people=args.skip_unknown_people)
        if plan.unknown_people or plan.unknown_categories:
            if plan.unknown_people:
                logger.error("❌ refused: people not in time.people: %s (configured: %s) — add them to "
                             "config, or pass --skip-unknown-people", ", ".join(sorted(plan.unknown_people)),
                             ", ".join(people))
            if plan.unknown_categories:
                logger.error("❌ refused: categories not in the %s area: %s",
                             PROTOTYPE_AREA, ", ".join(sorted(plan.unknown_categories)))
            logger.error("❌ nothing was written to %s", target)
            return REFUSED
        logger.info("ℹ️ importing %s into %s", args.export, target)
        counts = repo.import_rows(conn, plan.entries, plan.guesses)
    finally:
        conn.close()

    logger.info("✅ entries: %d imported, %d already there · guesses: %d imported, %d already there",
                counts["entries_inserted"], counts["entries_existing"],
                counts["guesses_inserted"], counts["guesses_existing"])
    for reason, n in sorted(plan.skipped.items()):
        logger.info("ℹ️ skipped %d row(s): %s", n, reason)
    if plan.truncated_notes:
        logger.warning("⚠️ %d note(s) cut to %d characters", plan.truncated_notes, repo.MAX_NOTE_CHARS)
    for run in plan.duplicates:
        logger.warning("⚠️ possible duplicate entries (imported as they are; delete in History if so): %s",
                       ", ".join(run))
    if plan.timers:
        logger.warning("⚠️ %d running timer(s) in the export were not imported — stop them in the prototype "
                       "and re-export before the final import", plan.timers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
