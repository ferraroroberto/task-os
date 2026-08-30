"""Quick-add — one line of natural language → title + dates + parent reference.

The syntax the quick-add bar (and any future CLI shorthand) understands, so
the PWA and the terminal agree on what a phrase means:

    renew passport next friday          → title "renew passport", due = next Friday
    pay water bill by tomorrow          → "pay water bill", due tomorrow  (on / by / due prefix ok)
    write sensor driver in 2 weeks      → "write sensor driver", due +14 days
    renew insurance due oct 15 starts oct 1
                                        → due Oct 15 **and** starts Oct 1 (issue #87)
    order sensor #12                    → parent = task 12
    order sensor › garden-bot           → parent = the task whose title matches "garden-bot"
    fix tap > Bathroom tomorrow         → parent "Bathroom" (ASCII ">" works too), due tomorrow

Date phrases are :func:`src.dates.parse_date`'s — this module never spells a
date rule of its own; it only decides *which trailing words* form the phrase
(the longest trailing window that parses, up to four words, an optional
``on`` / ``by`` / ``due`` lead-in dropped). A phrase that would swallow the
whole title is not a date ("tomorrow" alone stays a title).

``starts`` is split off **first** and, unlike ``due``, needs its explicit
``starts`` / ``start`` keyword: a bare trailing date is the due date, which is
what almost every line means, so a start date has to say so. Once it is taken,
the remainder goes through the ordinary implicit due rules — hence the two
dates in the example above.

:func:`parse` is pure (no database): the parent comes back as a *reference*
(``{"id": 12}`` or ``{"title": "garden-bot"}``) that the caller resolves —
:func:`resolve_parent` does that against a connection, preferring an exact
title match, then a task that already has children, then the newest.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from typing import Any

from src.dates import DateParseError, parse_date

_PARENT_ID_RE = re.compile(r"\s#(\d+)\s*$")
_PARENT_TITLE_RE = re.compile(r"\s[›>]\s*(.+?)\s*$")
_LEAD_INS = {"on", "by", "due"}
_STARTS_LEAD_INS = {"starts", "start", "starting"}
_MAX_DATE_WORDS = 4


def _split_parent(text: str) -> tuple[str, dict[str, Any] | None]:
    m = _PARENT_ID_RE.search(text)
    if m:
        return text[: m.start()].rstrip(), {"id": int(m.group(1))}
    m = _PARENT_TITLE_RE.search(text)
    if m and m.group(1):
        return text[: m.start()].rstrip(), {"title": m.group(1)}
    return text, None


def _split_due(text: str, today: date) -> tuple[str, str | None, str | None]:
    """→ (title, due ISO | None, the phrase that produced it | None)."""
    words = text.split()
    for n in range(min(_MAX_DATE_WORDS, len(words) - 1), 0, -1):
        window = words[-n:]
        phrase_words = window[1:] if n > 1 and window[0].lower() in _LEAD_INS else window
        phrase = " ".join(phrase_words)
        try:
            d = parse_date(phrase, today)
        except DateParseError:
            continue
        if d is None:  # "none" / "clear" — not a date phrase in a title
            continue
        return " ".join(words[:-n]).rstrip(" ,;-"), d.isoformat(), " ".join(window)
    return text, None, None


def _split_starts(text: str, today: date) -> tuple[str, str | None, str | None]:
    """→ (head, starts ISO | None, the phrase that produced it | None).

    Requires the explicit ``starts`` / ``start`` / ``starting`` keyword — see
    the module docstring for why this one is not implicit. Unlike the due
    split, the keyword may swallow the whole remaining line ("starts monday"
    with no title is still a start date; the title check is the caller's).
    """
    words = text.split()
    for n in range(min(_MAX_DATE_WORDS + 1, len(words)), 1, -1):
        window = words[-n:]
        if window[0].lower() not in _STARTS_LEAD_INS:
            continue
        try:
            d = parse_date(" ".join(window[1:]), today)
        except DateParseError:
            continue
        if d is None:
            continue
        return " ".join(words[:-n]).rstrip(" ,;-"), d.isoformat(), " ".join(window)
    return text, None, None


def parse(text: str, today: date | None = None) -> dict[str, Any]:
    """Split one quick-add line into
    ``{title, due, due_phrase, starts, starts_phrase, parent_ref}``.

    ``parent_ref`` is ``None``, ``{"id": N}`` or ``{"title": "…"}``; ``due``
    and ``starts`` are ISO dates or ``None``. Never raises — an unparseable
    tail is simply part of the title.
    """
    today = today or date.today()
    raw = re.sub(r"\s+", " ", (text or "").strip())
    body, parent_ref = _split_parent(raw)
    body, starts, starts_phrase = _split_starts(body, today)
    title, due, phrase = _split_due(body, today)
    if parent_ref and "title" in parent_ref and due is None:
        # "fix tap › Bathroom tomorrow": the date rides after the parent name.
        p_title, p_due, p_phrase = _split_due(parent_ref["title"], today)
        if p_due:
            parent_ref = {"title": p_title}
            due, phrase = p_due, p_phrase
    return {
        "title": title.strip(), "due": due, "due_phrase": phrase,
        "starts": starts, "starts_phrase": starts_phrase, "parent_ref": parent_ref,
    }


def resolve_parent(conn: sqlite3.Connection, ref: dict[str, Any] | None) -> dict[str, Any] | None:
    """Turn a parent reference into ``{"id", "title"}`` — or ``None`` when it
    names nothing (the caller shows "no such parent" rather than guessing)."""
    if not ref:
        return None
    if "id" in ref:
        row = conn.execute("SELECT id, title FROM tasks WHERE id = ?", (int(ref["id"]),)).fetchone()
        return dict(row) if row else None
    needle = str(ref.get("title") or "").strip()
    if not needle:
        return None
    rows = conn.execute(
        """
        SELECT t.id, t.title,
               (SELECT COUNT(*) FROM tasks c WHERE c.parent_id = t.id) AS kids
          FROM tasks t
         WHERE t.title LIKE ? COLLATE NOCASE
           AND t.status NOT IN ('done', 'cancelled')
         ORDER BY (t.title = ? COLLATE NOCASE) DESC, kids > 0 DESC, t.id DESC
         LIMIT 1
        """,
        (f"%{needle}%", needle),
    ).fetchall()
    return {"id": rows[0]["id"], "title": rows[0]["title"]} if rows else None
