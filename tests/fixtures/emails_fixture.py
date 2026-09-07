"""A tiny synthetic **email-archiver** index — the fixture behind the emails adapter tests.

Mirrors the archiver's schema verbatim (``emails`` + the FTS5 ``emails_fts``
content table + the three sync triggers, ``folders``) so the adapter is
exercised against the real DDL, never a simplification of it. Six made-up
emails whose ``.msg`` paths live under ``root`` (a temp dir the test picks,
usually the same tree ``{onedrive}`` points at, so ``to_ref`` folds them onto
the placeholder). ``fts=False`` builds the pre-FTS layout (no ``emails_fts``)
to prove the ``LIKE`` fallback; ``flags=False`` builds the pre-flag layout (no
``flag_status`` / ``flag_request``) to prove capture's not-configured reason.
Two of the six carry a follow-up flag (:data:`FLAGGED`) — the rows task-os#98's
capture pass turns into Inbox tasks.

    from tests.fixtures.emails_fixture import build_emails_db
    build_emails_db(tmp / "emails.db", root=tmp / "od")

    python -m tests.fixtures.emails_fixture --db E:/tmp/emails.db --root E:/tmp/od

Nothing here comes from a real mailbox.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

# The archiver's DDL (email_archiver/database/models.py), WAL/pragmas aside.
_DDL = """
CREATE TABLE IF NOT EXISTS emails (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT    UNIQUE NOT NULL,
    folder_path  TEXT    NOT NULL,
    filename     TEXT    NOT NULL,
    subject      TEXT,
    sender       TEXT,
    recipients   TEXT,
    date_sent    TEXT,
    body_preview TEXT,
    file_mtime   REAL    NOT NULL,
    indexed_at   TEXT    NOT NULL DEFAULT (datetime('now')){flag_columns}
);
CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails(folder_path);
CREATE TABLE IF NOT EXISTS folders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path  TEXT    UNIQUE NOT NULL,
    email_count  INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# The follow-up flag the archiver reads off each .msg while scanning
# (MAPI PidTagFlagStatus + PidLidFlagRequest) — task-os#98's capture contract.
# `flags=False` builds the pre-flag layout so the "no flag_status column"
# not-configured reason is tested against a real older-archiver shape.
_FLAG_COLUMNS = """,
    flag_status  INTEGER NOT NULL DEFAULT 0,
    flag_request TEXT"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject, sender, recipients, body_preview,
    content = emails, content_rowid = id,
    tokenize = 'unicode61 remove_diacritics 1'
);
CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, sender, recipients, body_preview)
    VALUES (new.id, new.subject, new.sender, new.recipients, new.body_preview);
END;
CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, sender, recipients, body_preview)
    VALUES ('delete', old.id, old.subject, old.sender, old.recipients, old.body_preview);
END;
CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, sender, recipients, body_preview)
    VALUES ('delete', old.id, old.subject, old.sender, old.recipients, old.body_preview);
    INSERT INTO emails_fts(rowid, subject, sender, recipients, body_preview)
    VALUES (new.id, new.subject, new.sender, new.recipients, new.body_preview);
END;
"""

# (relative folder, filename, subject, sender, recipients, date_sent, body_preview)
EMAILS: list[tuple[str, str, str, str, str, str, str]] = [
    ("mail/house", "2026-08-10 Kitchen quotes.msg", "Kitchen quotes from the installer",
     "Sam Rivera <sam@example.com>", "me@example.com", "2026-08-10T09:12:00",
     "Hi — attached the three kitchen quotes we discussed. The worktop is the big line item."),
    ("mail/house", "2026-08-12 Fence repair.msg", "Fence repair — availability next week",
     "Alex Chen <alex@example.com>", "me@example.com", "2026-08-12T16:40:00",
     "I can come by for the garden fence on Tuesday or Thursday afternoon."),
    ("mail/admin", "2026-08-01 Passport appointment.msg", "Passport renewal appointment confirmed",
     "appointments@example.org", "me@example.com", "2026-08-01T11:05:00",
     "Your passport renewal appointment is confirmed. Bring two photos and the old passport."),
    ("mail/admin", "2026-08-05 Water bill.msg", "Water bill for July",
     "billing@example.net", "me@example.com", "2026-08-05T08:00:00",
     "Your water bill for July is ready. Amount due by the 20th."),
    ("mail/admin", "2026-08-14 School forms.msg", "School enrolment forms — deadline Friday",
     "Jordan Lee <jordan@example.com>", "me@example.com; sam@example.com", "2026-08-14T18:22:00",
     "Reminder: the enrolment forms are due Friday. The kitchen-table copy is signed."),
    ("mail/garden-bot", "2026-08-15 Sensor shipped.msg", "Your soil-moisture sensor has shipped",
     "shop@example.shop", "me@example.com", "2026-08-15T13:30:00",
     "Order 4471: capacitive soil-moisture sensor, arriving in 3-5 days."),
]

#: Which of the six carry an Outlook follow-up flag, and its text — the two
#: task-os#98's capture pass is expected to land. Kept beside ``EMAILS``
#: rather than as extra tuple columns so the rows above stay readable and
#: anything already unpacking them keeps working.
FLAGGED: dict[str, str] = {
    "2026-08-10 Kitchen quotes.msg": "Follow up",
    "2026-08-14 School forms.msg": "Reply",
}


def build_emails_db(path: Path, *, root: Path, fts: bool = True, touch_files: bool = True,
                    flags: bool = True) -> dict[str, Any]:
    """Create the fixture index at ``path``; the ``.msg`` paths sit under ``root``.

    ``touch_files`` also creates the (empty) ``.msg`` files so a hit's path
    exists on disk. ``flags=False`` omits the two flag columns — the layout an
    archiver build older than the flag release has, which is what task-os#98's
    capture reports as *not configured* rather than as "no flagged emails".
    Returns ``{"path", "count", "fts", "flags", "flagged", "paths"}``.
    """
    root = Path(root)
    path = Path(path)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_DDL.format(flag_columns=_FLAG_COLUMNS if flags else ""))
        if fts:
            conn.executescript(_FTS_DDL)
        paths: list[str] = []
        flagged: list[str] = []
        for rel_folder, filename, subject, sender, recipients, date_sent, body in EMAILS:
            folder = (root / rel_folder)
            if touch_files:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / filename).touch()
            fp = str(folder / filename).replace("\\", "/")
            paths.append(fp)
            columns = "file_path, folder_path, filename, subject, sender, recipients, date_sent, body_preview, file_mtime"
            values: tuple[Any, ...] = (
                fp, str(folder).replace("\\", "/"), filename, subject, sender,
                recipients, date_sent, body, 1_700_000_000.0,
            )
            if flags:
                request = FLAGGED.get(filename)
                if request is not None:
                    flagged.append(fp)
                columns += ", flag_status, flag_request"
                values += (2 if request else 0, request)
            conn.execute(
                f"INSERT INTO emails({columns}) VALUES ({', '.join('?' * len(values))})", values
            )
        for rel_folder in sorted({e[0] for e in EMAILS}):
            n = sum(1 for e in EMAILS if e[0] == rel_folder)
            conn.execute("INSERT INTO folders(folder_path, email_count) VALUES (?, ?)", (str(root / rel_folder).replace("\\", "/"), n))
        conn.commit()
    finally:
        conn.close()
    return {"path": str(path), "count": len(EMAILS), "fts": fts, "flags": flags,
            "flagged": flagged, "paths": paths}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="build the synthetic email-archiver index")
    p.add_argument("--db", required=True)
    p.add_argument("--root", required=True, help="where the fake .msg files live")
    p.add_argument("--no-fts", action="store_true", help="omit emails_fts (LIKE fallback layout)")
    p.add_argument("--no-flags", action="store_true",
                   help="omit flag_status/flag_request (pre-flag archiver layout)")
    args = p.parse_args(argv)
    r = build_emails_db(Path(args.db), root=Path(args.root), fts=not args.no_fts,
                        flags=not args.no_flags)
    print(f"built {r['path']}: {r['count']} email(s), fts={r['fts']}, "
          f"flags={r['flags']} ({len(r['flagged'])} flagged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
