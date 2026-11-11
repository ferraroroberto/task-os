"""The flagged-mail route of folder-explorer's v1 API, as the two fakes serve it.

``GET /api/v1/mail/flagged?limit=&offset=`` answers the search envelope plus
``mails`` (oldest first) and ``total`` (every flagged mail, before paging) —
``docs/service-api.md`` in folder-explorer is the contract. :func:`flagged_mails`
reads the synthetic ``emails_fixture`` index (never a real mailbox) and
:func:`flagged_page` slices it the way the route does, so
``folder_explorer_fake`` (unit tests) and ``archiver_fake`` (the archive story,
whose one fake address is the whole folder-explorer) agree.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


def flagged_mails(db_path: str | Path) -> list[dict[str, Any]]:
    """The flagged rows (``flag_status`` 2) of a fixture index as v1 ``mails``, oldest first."""
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, file_path, folder_path, filename, subject, sender, date_sent, body_preview"
            "  FROM emails WHERE flag_status = 2 ORDER BY date_sent, id"
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        name, _, addr = (r["sender"] or "").partition(" <")
        out.append({
            "id": r["id"], "path": r["file_path"], "filename": r["filename"], "folder": r["folder_path"],
            "subject": r["subject"], "sender": r["sender"],
            "from_name": name if addr else "", "from_addr": addr.rstrip(">") if addr else (r["sender"] or ""),
            "date": (r["date_sent"] or "") + "+02:00", "preview": r["body_preview"],
        })
    return out


def flagged_page(mails: list[dict[str, Any]], raw_path: str) -> dict[str, Any]:
    """The ``ok`` body for one request path: ``limit`` (1-200, default 200) and ``offset`` slice ``mails``."""
    q = {k: v[-1] for k, v in parse_qs(urlsplit(raw_path).query).items()}
    limit, offset = int(q.get("limit", "200")), int(q.get("offset", "0"))
    return {"mails": mails[offset:offset + limit], "total": len(mails)}
