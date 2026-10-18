"""Rehearse a schema migration on a copy of a database — never on the database itself (#476).

The app migrates its database at every startup (``src/db.py::init_db``), so a
schema step reaches the live file the moment the tray restarts on a new build.
This script is the step before that restart:

1. opens the source **read-only** (``file:…?mode=ro``) and copies it into a
   temp folder with the SQLite backup API — a consistent snapshot even while
   the app is running, and no write to the source or its WAL;
2. counts every table's rows and fingerprints the content of every
   pre-existing column on the copy (all but the version stamp the migration
   itself bumps);
3. runs ``src.schema.migrate`` on the copy only;
4. counts and fingerprints again, and reports per table: rows before → after,
   whether the old columns' content is identical, plus the number of tasks
   whose ``owner`` is NULL (the install owner's, v20+).

The source's mtime is read before and after and reported, so a run proves it
left the file alone. Output is counts only — never a title or a name — so it
can be pasted anywhere. Reusable for any later schema step.

Usage:
    .venv/Scripts/python.exe scripts/migrate_dry_run.py --db <path to tasks.db> [--json] [--keep]

Exit codes: 0 every pre-existing table kept its rows and content and the
source is untouched · 1 something differs (read the report) · 2 usage (no
such file, not a task-os database).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logger import configure_logging  # noqa: E402
from src.schema import current_version, migrate  # noqa: E402

logger = logging.getLogger("migrate_dry_run")

#: Rows a migration writes by design, left out of the content fingerprint: the
#: version stamp every step bumps (``src.schema.migrate``).
OWN_WRITES = {"settings": "key <> 'schema_version'"}


def open_read_only(path: Path) -> sqlite3.Connection:
    """The source, opened so nothing this process does can write it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def snapshot(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """``{table: {rows, columns, digest}}`` for every table — the digest covers
    the listed columns of every row in rowid order (a virtual table: its count only)."""
    out: dict[str, dict[str, Any]] = {}
    tables = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for name, sql in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        rows = int(conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
        virtual = (sql or "").upper().startswith("CREATE VIRTUAL TABLE")
        columns = [] if virtual else [r[1] for r in conn.execute(f"PRAGMA table_info({quoted})").fetchall()]
        out[name] = {"rows": rows, "columns": columns, "virtual": virtual}
    return out


def digest(conn: sqlite3.Connection, table: str, columns: list[str]) -> str:
    """A content fingerprint of ``columns`` across every row of ``table``."""
    h = hashlib.sha256()
    quoted = '"' + table.replace('"', '""') + '"'
    cols = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
    where = f" WHERE {OWN_WRITES[table]}" if table in OWN_WRITES else ""
    try:
        cursor = conn.execute(f"SELECT {cols} FROM {quoted}{where} ORDER BY rowid")
    except sqlite3.OperationalError:  # WITHOUT ROWID
        cursor = conn.execute(f"SELECT {cols} FROM {quoted}{where} ORDER BY 1")
    for row in cursor:
        h.update(repr(tuple(row)).encode("utf-8"))
    return h.hexdigest()


def null_owners(conn: sqlite3.Connection) -> int | None:
    """Tasks with no owner of their own (read as the install owner's); ``None`` before v20."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "owner" not in cols:
        return None
    return int(conn.execute("SELECT COUNT(*) FROM tasks WHERE owner IS NULL").fetchone()[0])


def dry_run(source: Path, keep: bool = False) -> dict[str, Any]:
    """Copy ``source`` read-only, migrate the copy, compare. Never writes ``source``."""
    mtime_before = source.stat().st_mtime_ns
    work = Path(tempfile.mkdtemp(prefix="taskos-dry-run-"))
    copy = work / "tasks.db"
    try:
        src = open_read_only(source)
        try:
            dst = sqlite3.connect(copy)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        conn = sqlite3.connect(copy)
        try:
            version_before = current_version(conn)
            before = snapshot(conn)
            if "tasks" not in before:
                raise ValueError(f"{source.name} has no tasks table — not a task-os database")
            digests = {
                t: digest(conn, t, info["columns"]) for t, info in before.items() if not info["virtual"]
            }
            version_after = migrate(conn)
            after = snapshot(conn)
            tables: list[dict[str, Any]] = []
            for name in sorted(set(before) | set(after)):
                b, a = before.get(name), after.get(name)
                row: dict[str, Any] = {
                    "table": name,
                    "rows_before": b["rows"] if b else None,
                    "rows_after": a["rows"] if a else None,
                }
                if b and a and not b["virtual"]:
                    kept = [c for c in b["columns"] if c in a["columns"]]
                    row["content_unchanged"] = (
                        kept == b["columns"] and digest(conn, name, b["columns"]) == digests[name]
                    )
                tables.append(row)
            owners_null = null_owners(conn)
        finally:
            conn.close()
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)

    mtime_after = source.stat().st_mtime_ns
    rows_unchanged = all(
        t["rows_before"] == t["rows_after"] for t in tables if t["rows_before"] is not None
    )
    content_unchanged = all(t.get("content_unchanged", True) for t in tables)
    return {
        "schema_version_before": version_before,
        "schema_version_after": version_after,
        "tables": tables,
        "row_counts_unchanged": rows_unchanged,
        "content_unchanged": content_unchanged,
        "null_owner_tasks": owners_null,
        "source_mtime_unchanged": mtime_before == mtime_after,
        "copy": str(copy) if keep else None,
    }


def ok(report: dict[str, Any]) -> bool:
    return bool(
        report["row_counts_unchanged"] and report["content_unchanged"] and report["source_mtime_unchanged"]
    )


def format_report(report: dict[str, Any]) -> str:
    lines = [f"schema_version {report['schema_version_before']} → {report['schema_version_after']} (on the copy)"]
    for t in report["tables"]:
        b = "—" if t["rows_before"] is None else t["rows_before"]
        a = "—" if t["rows_after"] is None else t["rows_after"]
        content = {True: "content unchanged", False: "CONTENT CHANGED", None: ""}[t.get("content_unchanged")]
        lines.append(f"  {t['table']:<28} {b!s:>8} → {a!s:<8} {content}".rstrip())
    lines.append(f"row counts unchanged: {'yes' if report['row_counts_unchanged'] else 'NO'}")
    lines.append(f"existing content unchanged: {'yes' if report['content_unchanged'] else 'NO'}")
    lines.append(f"source mtime unchanged: {'yes' if report['source_mtime_unchanged'] else 'NO'}")
    if report["null_owner_tasks"] is not None:
        lines.append(f"tasks with a NULL owner (the install owner's): {report['null_owner_tasks']}")
    if report["copy"]:
        lines.append(f"migrated copy kept at {report['copy']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate a read-only copy of a task-os database and compare.")
    parser.add_argument("--db", required=True, type=Path, help="the database to rehearse (only ever read)")
    parser.add_argument("--json", action="store_true", help="the report as JSON")
    parser.add_argument("--keep", action="store_true", help="keep the migrated copy and print where")
    args = parser.parse_args(argv)
    configure_logging()
    if not args.db.is_file():
        logger.error("❌ no such database: %s", args.db)
        return 2
    try:
        report = dry_run(args.db, keep=args.keep)
    except (ValueError, sqlite3.DatabaseError) as exc:
        logger.error("❌ dry run refused: %s", exc)
        return 2
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    if ok(report):
        logger.info("✅ dry run: every table kept its rows and content; the source was not written")
        return 0
    logger.warning("⚠️ dry run: something differs — do not restart onto this build before reading the report")
    return 1


if __name__ == "__main__":
    sys.exit(main())
