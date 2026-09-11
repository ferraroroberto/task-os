"""Heal this database's stored ``.msg`` paths from a saved renumber map (#176).

The archiver re-sequences a folder so its ``NNN`` prefixes stay contiguous and
in sent-date order (email-archiver#61) and prints the old → new map; from a
batch ``apply`` / ``revert`` task-os reads that map straight off the child's
answer and heals itself. This script is the same heal for a map produced **out
of band** — ``main_batch.py renumber --folder …`` run by hand, or the repair of
a folder that was already ragged before task-os started asking for it.

It takes either shape: the bare map (``{"<folder>": [{from, to, attachments}]}``)
or a whole verb document carrying one under ``renumbered``. Three places are
rewritten, exactly as an in-run heal rewrites them —
``archive_items.files_json``, an email link's ref and a captured task's
``external_id`` — and the whole thing is idempotent, so running it twice is a
no-op rather than a mess.

``--dry-run`` reports the counts it *would* write and touches nothing: run it
first, read the numbers, then run it for real. ``TASKOS_DB_PATH`` picks the
database, as everywhere else.

Usage:
    .venv/Scripts/python.exe scripts/apply_renumber_map.py <map.json> --dry-run
    .venv/Scripts/python.exe scripts/apply_renumber_map.py <map.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.archive_renumber import apply_renumber_map, renumbered_folders  # noqa: E402
from src.config import load_config  # noqa: E402
from src.db import connect, db_path  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_map(path: Path) -> dict[str, list]:
    """The map in ``path``, whether it is the bare map or a verb document.

    A document is answered through the same reader the service uses, so
    ``renumber_refused`` is reported here too rather than passing unseen.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path} does not hold a renumber map")
    if "renumbered" in doc or "verb" in doc:
        return renumbered_folders(doc)
    folders = {str(k): v for k, v in doc.items() if isinstance(v, list)}
    if not folders:
        raise ValueError(f"{path} names no folder with a list of renamed bundles")
    return folders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="apply an email-archiver renumber map to task-os's stored paths",
    )
    parser.add_argument("map", type=Path, help="the JSON map (or a verb document carrying one)")
    parser.add_argument(
        "--dry-run", action="store_true", help="report the counts and write nothing",
    )
    args = parser.parse_args(argv)

    if not args.map.is_file():
        print(f"❌ no map at {args.map}")
        return 2
    try:
        folders = read_map(args.map)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 2

    placeholders = load_config().placeholders
    total = {"renames": 0, "items": 0, "links": 0, "tasks": 0}
    conn = connect()
    try:
        print(f"{'🔍 dry run over' if args.dry_run else '🛠️ healing'} {db_path()}")
        for folder, entries in folders.items():
            counts = apply_renumber_map(
                conn, folder, entries, placeholders_map=placeholders, dry_run=args.dry_run,
            )
            for key, value in counts.items():
                total[key] += value
            print(
                f"   {counts['renames']:>4} renamed file(s) → {counts['items']} archive item(s) · "
                f"{counts['links']} link(s) · {counts['tasks']} captured task(s)"
            )
    finally:
        conn.close()

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(
        f"{'🔍' if args.dry_run else '✅'} {len(folders)} folder(s), {total['renames']} renamed "
        f"file(s): {verb} {total['items']} archive item(s), {total['links']} link(s) and "
        f"{total['tasks']} captured task(s)"
    )
    if args.dry_run:
        print("   re-run without --dry-run to apply it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
