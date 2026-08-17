"""Emails adapter — the email archiver's SQLite index, **read-only**.

``config.search.email_db`` points at the archiver's ``emails.db`` (schema:
``emails(file_path UNIQUE, folder_path, filename, subject, sender,
recipients, date_sent, body_preview, …)`` + the FTS5 mirror ``emails_fts``
over subject / sender / recipients / body_preview). This adapter never
writes: the connection is opened with the ``file:…?mode=ro`` URI, per call,
so the archiver keeps sole ownership of the file.

Ranking is the archiver's own recipe — ``bm25(emails_fts, 10, 3, 3, 1)``
(subject × 10, sender / recipients × 3, body × 1); the query is every word a
quoted prefix term, ANDed. When the FTS table is missing (an older archiver
build) the search falls back to ``LIKE`` over the same four columns, newest
first — slower, still correct.

Not configured — with the reason — when the path is blank, the file does not
exist, or the file has no ``emails`` table.

Hit: title = subject (else the file name) · subtitle = ``sender · date ·
folder`` · snippet = the body / subject snippet with ``[match]`` marks · ref =
the ``.msg`` path folded onto the placeholders (``{onedrive}/…/mail.msg``
when it lies under a configured root, else the absolute path) — what
"attach" stores as ``links(kind=email)`` and the per-PC opener opens as a file ·
url = the ``taskos://open?ref=…`` link · extra = ``path, sender, recipients,
date, folder, filename, email_id``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.placeholders import normalize_path, opener_url, to_ref
from src.search.base import Hit, mark_terms, terms

logger = logging.getLogger(__name__)

__all__ = ["EmailsAdapter", "email_db_uri"]

FTS_TABLE = "emails_fts"
BM25_WEIGHTS = "10.0, 3.0, 3.0, 1.0"        # subject, sender, recipients, body_preview
_LIKE_COLUMNS = ("subject", "sender", "recipients", "body_preview")


def email_db_uri(path: str | Path) -> str:
    """``file:///E:/…/emails.db?mode=ro`` — the read-only URI :func:`sqlite3.connect` takes with ``uri=True``."""
    return Path(path).resolve().as_uri() + "?mode=ro"


def _fts_query(q: str) -> str:
    """Words as quoted terms, ANDed; a prefix ``*`` from two characters on
    (a one-letter prefix scans a fifth of a large index — measured 0.5 s on
    18 k rows — an exact one-letter token is cheap and just as useful)."""
    out = []
    for t in terms(q):
        quoted = '"' + t.replace('"', '""') + '"'
        out.append(quoted + "*" if len(t) >= 2 else quoted)
    return " ".join(out)


class EmailsAdapter:
    name = "emails"
    kind = "emails"

    def __init__(self, db_path: str, placeholders: Mapping[str, str] | None = None) -> None:
        self.db_path = (db_path or "").strip()
        self.placeholders = dict(placeholders or {})

    # ------------------------------------------------------------- state
    def is_configured(self) -> tuple[bool, str | None]:
        if not self.db_path:
            return False, "search.email_db not configured"
        p = Path(self.db_path)
        if not p.is_file():
            return False, f"email index not found at {self.db_path}"
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            return False, f"cannot open {self.db_path}: {exc}"
        try:
            has_emails = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'emails'"
            ).fetchone() is not None
        except sqlite3.Error as exc:
            return False, f"cannot read {self.db_path}: {exc}"
        finally:
            conn.close()
        if not has_emails:
            return False, f"no emails table in {self.db_path} — not an email-archiver index"
        return True, None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(email_db_uri(self.db_path), uri=True, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _has_fts(self, conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (FTS_TABLE,)
        ).fetchone() is not None

    # ------------------------------------------------------------ search
    def search(self, q: str, limit: int) -> list[Hit]:
        if not terms(q):
            return []
        conn = self._connect()
        try:
            if self._has_fts(conn):
                return self._search_fts(conn, q, limit)
            logger.info("ℹ️ email search: %s has no %s table — LIKE fallback", self.db_path, FTS_TABLE)
            return self._search_like(conn, q, limit)
        finally:
            conn.close()

    def _search_fts(self, conn: sqlite3.Connection, q: str, limit: int) -> list[Hit]:
        # FTS5 first, on its own (bm25/snippet only resolve when the virtual
        # table is the outermost table — the archiver hit that too), then one
        # batched lookup of the matched rows.
        rows = conn.execute(
            f"""
            SELECT rowid, bm25({FTS_TABLE}, {BM25_WEIGHTS}) AS rank,
                   highlight({FTS_TABLE}, 0, '[', ']') AS h_subject,
                   snippet({FTS_TABLE}, 3, '[', ']', '…', 14) AS s_body
              FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ? ORDER BY rank LIMIT ?
            """,
            (_fts_query(q), int(limit)),
        ).fetchall()
        if not rows:
            return []
        meta = {int(r["rowid"]): r for r in rows}
        ids = list(meta)
        emails = conn.execute(
            f"SELECT * FROM emails WHERE id IN ({', '.join('?' * len(ids))})", ids
        ).fetchall()
        by_id = {int(e["id"]): e for e in emails}
        out: list[Hit] = []
        for eid in ids:                                     # keep FTS rank order
            e = by_id.get(eid)
            if e is None:
                continue
            m = meta[eid]
            subject_hl = m["h_subject"] or ""
            snippet = subject_hl if "[" in subject_hl and "]" in subject_hl else (m["s_body"] or "")
            out.append(self._hit(e, snippet, -float(m["rank"] or 0.0)))
        return out

    def _search_like(self, conn: sqlite3.Connection, q: str, limit: int) -> list[Hit]:
        clauses = []
        params: list[Any] = []
        for t in terms(q):
            like = f"%{t}%"
            clauses.append("(" + " OR ".join(f"COALESCE({c}, '') LIKE ?" for c in _LIKE_COLUMNS) + ")")
            params.extend([like] * len(_LIKE_COLUMNS))
        rows = conn.execute(
            "SELECT * FROM emails WHERE " + " AND ".join(clauses) + " ORDER BY date_sent DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        out: list[Hit] = []
        words = [t.lower() for t in terms(q)]
        for i, e in enumerate(rows):
            subject = e["subject"] or ""
            # snippet from the field that carries a match: subject first, else the body
            text = subject if any(w in subject.lower() for w in words) else (e["body_preview"] or subject)
            out.append(self._hit(e, mark_terms(text[:200], q), float(limit - i)))
        return out

    def _hit(self, e: sqlite3.Row, snippet: str, score: float) -> Hit:
        path = normalize_path(e["file_path"] or "")
        ref = to_ref(path, self.placeholders)
        date = (e["date_sent"] or "")[:10]
        folder = normalize_path(e["folder_path"] or "").rstrip("/").rsplit("/", 1)[-1]
        subject = (e["subject"] or "").strip() or (e["filename"] or path.rsplit("/", 1)[-1])
        sub_bits = [b for b in ((e["sender"] or "").strip(), date, folder) if b]
        return Hit(
            kind="emails",
            title=subject,
            subtitle=" · ".join(sub_bits),
            snippet=snippet,
            ref=ref,
            url=opener_url(ref),
            score=score,
            extra={
                "email_id": int(e["id"]),
                "path": path,
                "sender": e["sender"],
                "recipients": e["recipients"],
                "date": e["date_sent"],
                "folder": normalize_path(e["folder_path"] or ""),
                "filename": e["filename"],
            },
        )
