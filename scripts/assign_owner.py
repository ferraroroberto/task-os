"""Hand every task about one contact to a member, in one pass (#476).

Before v20 a task had no owner, so every task reads as the install owner's.
Some of them are really another member's — the ones about a contact that
stands for that member. This finds the tasks whose ``person_id`` (the contact
a task is *about*) is ``--person-id`` and whose effective owner is not already
``--to``, and with ``--apply`` gives each of them that owner through
``src/tasks_repo.update_task``, so every change is an activity row like an
edit in the app.

**A dry run by default:** it opens the database read-only and prints counts
only — never a title — and writes nothing. ``--apply`` is the one write.

The target is the usual database (``--db`` or ``TASKOS_DB_PATH``) and the
usual config (``TASKOS_CONFIG_PATH``), whose ``people`` say who ``--to`` may
be. The database must already be at schema v20 (start the app on this build
first; ``scripts/migrate_dry_run.py`` rehearses that).

Usage:
    .venv/Scripts/python.exe scripts/assign_owner.py --person-id N --to <member id> [--db PATH] [--apply]

Exit codes: 0 done (or nothing to do) · 2 refused (nothing written).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import tasks_repo as repo  # noqa: E402
from src.config import load_config  # noqa: E402
from src.db import connect, db_path  # noqa: E402
from src.logger import configure_logging  # noqa: E402

logger = logging.getLogger("assign_owner")

ACTOR = "assign_owner"


def candidates(conn: sqlite3.Connection, person_id: int, to: str) -> list[int]:
    """The ids of the tasks about ``person_id`` that ``to`` does not own yet."""
    rows = conn.execute(
        "SELECT id, owner FROM tasks WHERE person_id = ? ORDER BY id", (person_id,)
    ).fetchall()
    return [int(r[0]) for r in rows if (r[1] or repo.install_owner()) != to]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Give a member every task about one contact.")
    parser.add_argument("--person-id", required=True, type=int, help="the contact (people.id) the tasks are about")
    parser.add_argument("--to", required=True, help="the member id that takes them")
    parser.add_argument("--db", type=Path, help="default: TASKOS_DB_PATH, else the runtime database")
    parser.add_argument("--apply", action="store_true", help="write; without it nothing is written")
    args = parser.parse_args(argv)
    configure_logging()

    members = [p.id for p in load_config().people]
    repo.set_members(members)
    path = args.db or db_path()
    if not path.is_file():
        logger.error("❌ no such database: %s", path)
        return 2
    if args.to not in members:
        logger.error("❌ %r is not a member (people: %s)", args.to, ", ".join(members))
        return 2

    conn = connect(path) if args.apply else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "owner" not in cols:
            logger.error("❌ the database has no tasks.owner yet — start the app on a v20 build first")
            return 2
        if conn.execute("SELECT 1 FROM people WHERE id = ?", (args.person_id,)).fetchone() is None:
            logger.error("❌ no contact with id %d", args.person_id)
            return 2
        ids = candidates(conn, args.person_id, args.to)
        total = int(conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE person_id = ?", (args.person_id,)
        ).fetchone()[0])
        print(f"tasks about contact {args.person_id}: {total}; to give to {args.to}: {len(ids)}")
        if not args.apply:
            print("dry run — nothing written (add --apply to write)")
            return 0
        conn.row_factory = sqlite3.Row
        for task_id in ids:
            repo.update_task(conn, task_id, actor=ACTOR, owner=args.to)
        logger.info("✅ %d task(s) now owned by %s", len(ids), args.to)
        print(f"applied: {len(ids)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
