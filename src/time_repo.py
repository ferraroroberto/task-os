"""The time tracker's rows (#457) — areas, categories, entries, timers, guesses.

Every rule about tracked time lives here and nowhere else: the router
(``app/webapp/routers/time.py``) and the prototype importer call these
functions, and nothing else writes the five ``time_*`` tables (v19). None of it
touches a task, so none of it belongs in ``src/tasks_repo.py`` — the
``src/archive_store.py`` precedent. No FastAPI import: errors subclass
``tasks_repo.RepoError`` and reach the one JSON envelope through ``server.py``.

The rules worth knowing before changing anything:

- **One running timer per person** (the ``time_timers`` PK); two people's
  timers are independent. Start, stop, switch and discard each run in one
  ``BEGIN IMMEDIATE`` transaction, so a stop deletes the timer and inserts the
  entry together or not at all, and a second stop (a double tap, another
  device) finds no timer and saves nothing.
- **A clocked entry's end is its start plus its minutes**, always: a stop
  rounds the elapsed time to whole minutes (at least one, at most
  :data:`MAX_MINUTES`) and derives the end from it, so History's range and its
  duration can never disagree, and an edit of the start or the duration moves
  the end. An entry without a range (the importer's) never gains one.
- **The server owns the day.** A timer's entry counts on the day it *started*
  (an entry crossing midnight stays on its start day), in the process clock's
  zone (``src/clock.py``); "today" and "not in the future" are the server's
  date, never the browser's.
- **Archived, not deleted**: an archived area or category cannot be started
  or picked, and every entry already in it keeps showing and counting. Only a
  category nothing points at — no entry, no running timer — can be deleted
  (:func:`delete_category`, #463): one made by mistake.
- **Totals count configured people only** — the prototype's ``validEntries``
  rule, so imported totals match it; History lists every entry.
- **An import only ever adds** (:func:`import_rows`): keyed on the prototype's
  document id, a re-run inserts nothing, and a guess changed here after the
  import is never overwritten by it.
- **A pushing app owns its entries** (:func:`upsert_by_source`, #469): an entry
  whose ``source_id`` is namespaced (``usage:app-launcher:2026-10-14``) is
  created or replaced by the app that pushed it, so a hand edit is overwritten
  by the next push and a hand delete is recreated. The pattern needs a colon,
  which no prototype document id carries, so the two key spaces cannot meet.

``people`` arguments are the configured ``time.people`` ids
(``TimeConfig.ids``): the repo validates against them but never reads the
config itself.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import Any

from src import clock
from src.tasks_repo import NotFound, RepoError, ValidationError

logger = logging.getLogger(__name__)

#: The longest entry: one day. A timer left running longer saves this much.
MAX_MINUTES = 1440
MAX_NOTE_CHARS = 140
#: Totals periods: today, the last 7 / 30 days (today included), everything.
PERIODS = ("today", "7", "30", "all")
#: A pushed entry's key: a lowercase namespace, a colon, then the caller's own id.
SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*:[A-Za-z0-9:._-]{1,120}")
CSV_COLUMNS = ("day", "start", "end", "minutes", "person_id", "person_name", "area", "category", "note")


class TimerRunning(RepoError):
    """Starting a second timer for a person who already has one."""

    code = "timer_running"
    http_status = 409


class NoTimer(RepoError):
    """Stopping or discarding a timer that is not running (already stopped elsewhere)."""

    code = "no_timer"
    http_status = 409


class SlugTaken(RepoError):
    """An area or category name whose slug is already used where it would land."""

    code = "slug_taken"
    http_status = 409


class CategoryInUse(RepoError):
    """Deleting a category an entry or a running timer still points at — archive it instead."""

    code = "category_in_use"
    http_status = 409


# ------------------------------------------------------------- plumbing


@contextmanager
def _immediate(conn: sqlite3.Connection) -> Iterator[None]:
    """One write transaction, taken up front: two phones stopping the same
    timer serialise here instead of both reading it as running."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def slugify(name: str) -> str:
    """``"Kids: care and play"`` → ``"kids-care-and-play"``; never empty."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


def _clean_name(name: str, what: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValidationError(f"{what} needs a name")
    if len(cleaned) > 80:
        raise ValidationError(f"{what} name is longer than 80 characters")
    return cleaned


def _clean_hint(hint: str | None) -> str:
    """A category's subtitle (the ``hint`` under its name): optional, so empty clears it."""
    cleaned = (hint or "").strip()
    if len(cleaned) > 80:
        raise ValidationError("a subtitle is longer than 80 characters")
    return cleaned


def _check_person(person: str, people: Collection[str]) -> None:
    if person not in people:
        raise ValidationError(f"unknown person {person!r}")


def _check_minutes(minutes: int) -> int:
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        raise ValidationError(f"minutes must be a whole number from 1 to {MAX_MINUTES}")
    return minutes


def _check_note(note: str | None) -> str:
    cleaned = (note or "").strip()
    if len(cleaned) > MAX_NOTE_CHARS:
        raise ValidationError(f"a note is at most {MAX_NOTE_CHARS} characters")
    return cleaned


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f"day {value!r} is not a YYYY-MM-DD date") from None


def _check_day(value: str) -> date:
    day = _parse_day(value)
    if day > clock.today():
        raise ValidationError("an entry cannot be on a future day")
    return day


def _parse_hhmm(value: str) -> time:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValidationError(f"start {value!r} is not an HH:MM time")
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"start {value!r} is not an HH:MM time") from None


def _at(day: date, at: time, tz: Any) -> datetime:
    """``day`` at the wall-clock time ``at`` in the server's zone."""
    return datetime.combine(day, at, tzinfo=tz)


# ------------------------------------------------- areas and categories


def list_areas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every area in position order, each with its categories — archived ones
    included and flagged, because History and Totals still name them."""
    areas = [
        {"id": r["id"], "slug": r["slug"], "name": r["name"], "position": r["position"],
         "archived": r["archived_at"] is not None, "categories": []}
        for r in conn.execute("SELECT * FROM time_areas ORDER BY position, id")
    ]
    by_id = {a["id"]: a for a in areas}
    used = _used_category_ids(conn)
    for r in conn.execute("SELECT * FROM time_categories ORDER BY position, id"):
        by_id[r["area_id"]]["categories"].append(_category_dict(r, r["id"] in used))
    return areas


def _used_category_ids(conn: sqlite3.Connection, category_id: int | None = None) -> set[int]:
    """The categories an entry or a running timer points at (only ``category_id``'s
    row, when given) — the ones :func:`delete_category` refuses."""
    where, args = ("WHERE category_id = ?", (category_id, category_id)) if category_id is not None else ("", ())
    return {int(r[0]) for r in conn.execute(
        f"SELECT category_id FROM time_entries {where} UNION SELECT category_id FROM time_timers {where}", args)}


def _category_dict(r: sqlite3.Row, in_use: bool) -> dict[str, Any]:
    return {"id": r["id"], "area_id": r["area_id"], "slug": r["slug"], "name": r["name"],
            "hint": r["hint"], "position": r["position"], "archived": r["archived_at"] is not None,
            "in_use": in_use}


def _category_out(conn: sqlite3.Connection, category_id: int) -> dict[str, Any]:
    return _category_dict(_category_row(conn, category_id), bool(_used_category_ids(conn, category_id)))


def _area_row(conn: sqlite3.Connection, area_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM time_areas WHERE id = ?", (area_id,)).fetchone()
    if row is None:
        raise NotFound(f"area {area_id} not found")
    return row


def _category_row(conn: sqlite3.Connection, category_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT c.*, a.archived_at AS area_archived_at FROM time_categories c "
        "JOIN time_areas a ON a.id = c.area_id WHERE c.id = ?", (category_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"category {category_id} not found")
    return row


def _check_pickable(conn: sqlite3.Connection, category_id: int) -> None:
    """A category a new timer or a changed entry may point at: not archived, nor its area."""
    row = _category_row(conn, category_id)
    if row["archived_at"] is not None or row["area_archived_at"] is not None:
        raise ValidationError(f"category {row['name']!r} is archived")


def _reorder(conn: sqlite3.Connection, table: str, scope: str | None, scope_id: int | None,
             item_id: int | None = None, position: int | None = None) -> None:
    """Put ``item_id`` at ``position`` (clamped; ``None`` = last) among its
    siblings and renumber them 0..n-1, so positions never collide or gap.
    No ``item_id`` = just renumber (the gap a category moved away leaves)."""
    where, args = (f"WHERE {scope} = ?", [scope_id]) if scope else ("WHERE 1", [])
    if item_id is not None:
        where += " AND id <> ?"
        args.append(item_id)
    siblings = [r[0] for r in conn.execute(f"SELECT id FROM {table} {where} ORDER BY position, id", args)]
    if item_id is not None:
        index = len(siblings) if position is None else max(0, min(position, len(siblings)))
        siblings.insert(index, item_id)
    conn.executemany(f"UPDATE {table} SET position = ? WHERE id = ?", [(i, sid) for i, sid in enumerate(siblings)])


def _area_dict(conn: sqlite3.Connection, area_id: int) -> dict[str, Any]:
    return next(a for a in list_areas(conn) if a["id"] == area_id)


def create_area(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    name = _clean_name(name, "an area")
    slug = slugify(name)
    with _immediate(conn):
        if conn.execute("SELECT 1 FROM time_areas WHERE slug = ?", (slug,)).fetchone():
            raise SlugTaken(f"an area called {name!r} already exists")
        area_id = int(conn.execute(
            "INSERT INTO time_areas(slug, name, position) VALUES (?, ?, 0)", (slug, name)).lastrowid)
        _reorder(conn, "time_areas", None, None, area_id, None)
    logger.info("ℹ️ time: area %d %r added", area_id, slug)
    return _area_dict(conn, area_id)


def update_area(conn: sqlite3.Connection, area_id: int, *, name: str | None = None,
                position: int | None = None, archived: bool | None = None) -> dict[str, Any]:
    """Rename, move or (un)archive an area. A rename keeps the slug: it is the
    stable key ``time.compare_area`` names."""
    with _immediate(conn):
        row = _area_row(conn, area_id)
        if name is not None:
            conn.execute("UPDATE time_areas SET name = ? WHERE id = ?", (_clean_name(name, "an area"), area_id))
        if archived is not None and archived != (row["archived_at"] is not None):
            conn.execute("UPDATE time_areas SET archived_at = ? WHERE id = ?",
                         (clock.now_iso() if archived else None, area_id))
        if position is not None:
            _reorder(conn, "time_areas", None, None, area_id, position)
    return _area_dict(conn, area_id)


def create_category(conn: sqlite3.Connection, area_id: int, name: str, hint: str = "") -> dict[str, Any]:
    name = _clean_name(name, "a category")
    hint = _clean_hint(hint)
    slug = slugify(name)
    with _immediate(conn):
        _area_row(conn, area_id)
        if conn.execute("SELECT 1 FROM time_categories WHERE area_id = ? AND slug = ?", (area_id, slug)).fetchone():
            raise SlugTaken(f"this area already has a category called {name!r}")
        cid = int(conn.execute(
            "INSERT INTO time_categories(area_id, slug, name, hint, position) VALUES (?, ?, ?, ?, 0)",
            (area_id, slug, name, hint),
        ).lastrowid)
        _reorder(conn, "time_categories", "area_id", area_id, cid, None)
    logger.info("ℹ️ time: category %d %r added to area %d", cid, slug, area_id)
    return _category_out(conn, cid)


def update_category(conn: sqlite3.Connection, category_id: int, *, name: str | None = None,
                    hint: str | None = None, position: int | None = None, area_id: int | None = None,
                    archived: bool | None = None) -> dict[str, Any]:
    """Rename, re-hint, move (within or to another area) or (un)archive a
    category. Moving keeps every entry on it — the entries point at the
    category, not the area."""
    with _immediate(conn):
        row = _category_row(conn, category_id)
        if name is not None:
            conn.execute("UPDATE time_categories SET name = ? WHERE id = ?",
                         (_clean_name(name, "a category"), category_id))
        if hint is not None:
            conn.execute("UPDATE time_categories SET hint = ? WHERE id = ?", (_clean_hint(hint), category_id))
        if archived is not None and archived != (row["archived_at"] is not None):
            conn.execute("UPDATE time_categories SET archived_at = ? WHERE id = ?",
                         (clock.now_iso() if archived else None, category_id))
        target = row["area_id"]
        if area_id is not None and area_id != row["area_id"]:
            _area_row(conn, area_id)
            if conn.execute("SELECT 1 FROM time_categories WHERE area_id = ? AND slug = ?",
                            (area_id, row["slug"])).fetchone():
                raise SlugTaken(f"the target area already has a category called {row['name']!r}")
            conn.execute("UPDATE time_categories SET area_id = ? WHERE id = ?", (area_id, category_id))
            _reorder(conn, "time_categories", "area_id", row["area_id"])   # close the gap left behind
            target = area_id
        if position is not None or target != row["area_id"]:
            _reorder(conn, "time_categories", "area_id", target, category_id, position)
    return _category_out(conn, category_id)


def delete_category(conn: sqlite3.Connection, category_id: int) -> None:
    """Delete a category made by mistake: only one no entry and no running
    timer points at (409 ``category_in_use`` otherwise — archive that one), in
    the same transaction as the check, so a timer started meanwhile on another
    device either lands first and blocks the delete or finds the category gone.
    The area's remaining categories close the gap."""
    with _immediate(conn):
        row = _category_row(conn, category_id)
        if _used_category_ids(conn, category_id):
            raise CategoryInUse(f"category {row['name']!r} has entries or a running timer; archive it instead")
        conn.execute("DELETE FROM time_categories WHERE id = ?", (category_id,))
        _reorder(conn, "time_categories", "area_id", row["area_id"])
    logger.info("ℹ️ time: category %d %r deleted from area %d", category_id, row["slug"], row["area_id"])


def category_by_slug(conn: sqlite3.Connection, area_slug: str, slug: str) -> int | None:
    """The id of ``area_slug``/``slug``, or ``None`` — the importer's mapping."""
    row = conn.execute(
        "SELECT c.id FROM time_categories c JOIN time_areas a ON a.id = c.area_id "
        "WHERE a.slug = ? AND c.slug = ?", (area_slug, slug),
    ).fetchone()
    return int(row[0]) if row else None


# ----------------------------------------------------------------- entries

_ENTRY_SELECT = (
    "SELECT e.*, c.slug AS category_slug, c.name AS category_name, c.area_id AS area_id, "
    "a.slug AS area_slug, a.name AS area_name FROM time_entries e "
    "JOIN time_categories c ON c.id = e.category_id JOIN time_areas a ON a.id = c.area_id"
)
_ENTRY_ORDER = " ORDER BY e.day DESC, COALESCE(e.started_at, e.created_at) DESC, e.id DESC"
_ENTRY_KEYS = (
    "id", "person", "category_id", "category_slug", "category_name", "area_id", "area_slug", "area_name",
    "day", "minutes", "started_at", "ended_at", "note", "created_at", "updated_at", "source_id",
)


def _entry_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {k: r[k] for k in _ENTRY_KEYS}


def get_entry(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any]:
    row = conn.execute(_ENTRY_SELECT + " WHERE e.id = ?", (entry_id,)).fetchone()
    if row is None:
        raise NotFound(f"entry {entry_id} not found (deleted meanwhile?)")
    return _entry_dict(row)


def _insert_entry(conn: sqlite3.Connection, *, person: str, category_id: int, day: date, minutes: int,
                  started: datetime | None, note: str = "") -> int:
    now = clock.now_iso()
    ended = started + timedelta(minutes=minutes) if started is not None else None
    cur = conn.execute(
        "INSERT INTO time_entries(person, category_id, day, minutes, started_at, ended_at, note, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (person, category_id, day.isoformat(), minutes, _iso(started) if started else None,
         _iso(ended) if ended else None, note, now, now),
    )
    return int(cur.lastrowid)


def create_entry(conn: sqlite3.Connection, *, person: str, category_id: int, day: str, minutes: int,
                 people: Collection[str], start: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Time already spent ("Add time already spent"): ``start`` is the HH:MM it
    began on ``day``, and the end is derived from it; no ``start`` = a
    duration-only entry."""
    _check_person(person, people)
    minutes = _check_minutes(minutes)
    note = _check_note(note)
    the_day = _check_day(day)
    started = None
    if start is not None:
        now = clock.now()
        started = _at(the_day, _parse_hhmm(start), now.tzinfo)
        if started > now:
            raise ValidationError("an entry cannot start in the future")
    with _immediate(conn):
        _check_pickable(conn, category_id)
        entry_id = _insert_entry(conn, person=person, category_id=category_id, day=the_day,
                                 minutes=minutes, started=started, note=note)
    logger.info("ℹ️ time: entry %d added by hand (%s, %d min on %s)", entry_id, person, minutes, day)
    return get_entry(conn, entry_id)


def update_entry(conn: sqlite3.Connection, entry_id: int, *, people: Collection[str], person: str | None = None,
                 category_id: int | None = None, day: str | None = None, minutes: int | None = None,
                 start: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Correct any entry, whoever logged it: person, category, day, duration,
    note and — for an entry with a clock range — the start. A changed start,
    day or duration moves the end; an entry without a range never gains one."""
    with _immediate(conn):
        row = conn.execute("SELECT * FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise NotFound(f"entry {entry_id} not found (deleted meanwhile?)")
        fields: dict[str, Any] = {}
        if person is not None and person != row["person"]:
            _check_person(person, people)
            fields["person"] = person
        if category_id is not None and category_id != row["category_id"]:
            _check_pickable(conn, category_id)
            fields["category_id"] = category_id
        if note is not None:
            fields["note"] = _check_note(note)
        new_day = _check_day(day) if day is not None else date.fromisoformat(row["day"])
        new_minutes = _check_minutes(minutes) if minutes is not None else int(row["minutes"])
        fields["day"] = new_day.isoformat()
        fields["minutes"] = new_minutes
        if row["started_at"] is None:
            if start is not None:
                raise ValidationError("this entry was imported with a duration only; it has no start time")
        else:
            old = datetime.fromisoformat(row["started_at"])
            at = _parse_hhmm(start) if start is not None else old.time()
            started = _at(new_day, at, old.tzinfo)
            if started > clock.now():
                raise ValidationError("an entry cannot start in the future")
            fields["started_at"] = _iso(started)
            fields["ended_at"] = _iso(started + timedelta(minutes=new_minutes))
        fields["updated_at"] = clock.now_iso()
        conn.execute(
            f"UPDATE time_entries SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), entry_id),
        )
    logger.info("ℹ️ time: entry %d edited (%s)", entry_id, ", ".join(k for k in fields if k != "updated_at"))
    return get_entry(conn, entry_id)


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    with _immediate(conn):
        if conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,)).rowcount == 0:
            raise NotFound(f"entry {entry_id} not found (deleted meanwhile?)")
    logger.info("ℹ️ time: entry %d deleted", entry_id)


def _check_source_id(source_id: str) -> str:
    if not SOURCE_ID_RE.fullmatch(source_id or ""):
        raise ValidationError(
            f"source_id {source_id!r} must be <namespace>:<id>, e.g. usage:app-launcher:2026-10-14")
    return source_id


def upsert_by_source(conn: sqlite3.Connection, source_id: str, *, person: str, category_id: int, day: str,
                     minutes: int, people: Collection[str], note: str | None = None) -> tuple[dict[str, Any], bool]:
    """Create or replace the duration-only entry a pushing app keys on
    ``source_id`` (#469); returns ``(entry, created)``. The same checks as
    :func:`create_entry`. Re-sending what is already stored changes nothing,
    ``updated_at`` included, so a nightly re-push does not churn."""
    _check_source_id(source_id)
    _check_person(person, people)
    minutes = _check_minutes(minutes)
    note = _check_note(note)
    the_day = _check_day(day).isoformat()
    with _immediate(conn):
        _check_pickable(conn, category_id)
        row = conn.execute("SELECT * FROM time_entries WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            now = clock.now_iso()
            entry_id = int(conn.execute(
                "INSERT INTO time_entries(person, category_id, day, minutes, note, created_at, updated_at, source_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (person, category_id, the_day, minutes, note, now, now, source_id),
            ).lastrowid)
            created = True
            logger.info("ℹ️ time: entry %d added by its source %s (%s, %d min on %s)",
                        entry_id, source_id, person, minutes, the_day)
        else:
            entry_id, created = int(row["id"]), False
            wanted = {"person": person, "category_id": category_id, "day": the_day, "minutes": minutes,
                      "note": note, "started_at": None, "ended_at": None}
            if any(row[k] != v for k, v in wanted.items()):
                conn.execute(
                    f"UPDATE time_entries SET {', '.join(f'{k} = ?' for k in wanted)}, updated_at = ? WHERE id = ?",
                    (*wanted.values(), clock.now_iso(), entry_id),
                )
                logger.info("ℹ️ time: entry %d replaced by its source %s", entry_id, source_id)
            else:
                logger.info("ℹ️ time: entry %d already matches its source %s", entry_id, source_id)
    return get_entry(conn, entry_id), created


def delete_by_source(conn: sqlite3.Connection, source_id: str) -> None:
    """Remove the entry a pushing app keyed on ``source_id`` (404 when none is)."""
    _check_source_id(source_id)
    with _immediate(conn):
        if conn.execute("DELETE FROM time_entries WHERE source_id = ?", (source_id,)).rowcount == 0:
            raise NotFound(f"no entry has source_id {source_id!r}")
    logger.info("ℹ️ time: entry with source %s deleted", source_id)


def list_entries(conn: sqlite3.Connection, *, names: Mapping[str, str], q: str | None = None,
                 limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """History: newest day first, one page at a time. ``q`` matches the
    category, area, person name, note or day."""
    where, args = "", []
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        matching = [pid for pid, name in names.items() if needle in name.lower() or needle in pid.lower()]
        where = (" WHERE (lower(c.name) LIKE ? OR lower(a.name) LIKE ? OR lower(e.note) LIKE ? OR e.day LIKE ?"
                 + "".join(" OR e.person = ?" for _ in matching) + ")")
        args = [like, like, like, like, *matching]
    total = conn.execute(
        "SELECT COUNT(*) FROM time_entries e JOIN time_categories c ON c.id = e.category_id "
        "JOIN time_areas a ON a.id = c.area_id" + where, args,
    ).fetchone()[0]
    rows = conn.execute(_ENTRY_SELECT + where + _ENTRY_ORDER + " LIMIT ? OFFSET ?", (*args, limit, offset))
    return {"items": [_entry_dict(r) for r in rows], "total": int(total), "limit": limit, "offset": offset}


def recent_categories(conn: sqlite3.Connection, person: str, limit: int = 5) -> list[int]:
    """``person``'s last ``limit`` distinct categories, newest first — the
    Recent quick-start row. Archived ones are left out: they cannot be started."""
    rows = conn.execute(
        "SELECT e.category_id FROM time_entries e JOIN time_categories c ON c.id = e.category_id "
        "JOIN time_areas a ON a.id = c.area_id "
        "WHERE e.person = ? AND c.archived_at IS NULL AND a.archived_at IS NULL "
        "GROUP BY e.category_id ORDER BY MAX(e.created_at) DESC, MAX(e.id) DESC LIMIT ?",
        (person, limit),
    )
    return [int(r[0]) for r in rows]


# ------------------------------------------------------------------ timers

_TIMER_SELECT = (
    "SELECT t.person, t.category_id, t.started_at, c.name AS category_name, c.slug AS category_slug, "
    "a.id AS area_id, a.slug AS area_slug, a.name AS area_name FROM time_timers t "
    "JOIN time_categories c ON c.id = t.category_id JOIN time_areas a ON a.id = c.area_id"
)


def list_timers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every running timer — at most one per person."""
    return [dict(r) for r in conn.execute(_TIMER_SELECT + " ORDER BY t.started_at")]


def _timer(conn: sqlite3.Connection, person: str) -> dict[str, Any] | None:
    row = conn.execute(_TIMER_SELECT + " WHERE t.person = ?", (person,)).fetchone()
    return dict(row) if row else None


def elapsed_minutes(started_at: str, now: datetime | None = None) -> int:
    """What a stop saves by itself: the elapsed time rounded to whole minutes,
    at least one and at most :data:`MAX_MINUTES` (the prototype's rule)."""
    seconds = ((now or clock.now()) - datetime.fromisoformat(started_at)).total_seconds()
    return max(1, min(MAX_MINUTES, round(seconds / 60)))


def _stop_locked(conn: sqlite3.Connection, timer: Mapping[str, Any], minutes: int | None) -> int:
    """Inside an open transaction: remove ``timer`` and save its entry on the day it started."""
    minutes = _check_minutes(minutes) if minutes is not None else elapsed_minutes(timer["started_at"])
    started = datetime.fromisoformat(timer["started_at"])
    conn.execute("DELETE FROM time_timers WHERE person = ?", (timer["person"],))
    return _insert_entry(conn, person=timer["person"], category_id=timer["category_id"],
                         day=started.date(), minutes=minutes, started=started)


def start_timer(conn: sqlite3.Connection, person: str, category_id: int, *, people: Collection[str],
                switch: bool = False) -> dict[str, Any]:
    """Start ``person``'s timer on ``category_id``. A timer already running is
    refused (:class:`TimerRunning`) unless ``switch``, which stops and saves it
    and starts the new one in the same transaction. Answers ``{timer, entry}``
    (``entry`` = what a switch saved, else ``None``)."""
    _check_person(person, people)
    entry_id = None
    with _immediate(conn):
        _check_pickable(conn, category_id)
        running = _timer(conn, person)
        if running is not None:
            if not switch:
                raise TimerRunning(f"{person} already has a timer running ({running['category_name']})")
            entry_id = _stop_locked(conn, running, None)
        conn.execute("INSERT INTO time_timers(person, category_id, started_at) VALUES (?, ?, ?)",
                     (person, category_id, clock.now_iso()))
    logger.info("ℹ️ time: %s started a timer on category %d%s", person, category_id,
                f" (switched; entry {entry_id} saved)" if entry_id else "")
    return {"timer": _timer(conn, person), "entry": get_entry(conn, entry_id) if entry_id else None}


def stop_timer(conn: sqlite3.Connection, person: str, *, minutes: int | None = None) -> dict[str, Any]:
    """Stop and save ``person``'s timer; ``minutes`` overrides the elapsed time
    (the forgotten-timer correction). Nothing running → :class:`NoTimer`."""
    with _immediate(conn):
        running = _timer(conn, person)
        if running is None:
            raise NoTimer(f"{person} has no timer running (stopped on another device?)")
        entry_id = _stop_locked(conn, running, minutes)
    entry = get_entry(conn, entry_id)
    logger.info("ℹ️ time: %s stopped a timer → entry %d (%d min)", person, entry_id, entry["minutes"])
    return entry


def discard_timer(conn: sqlite3.Connection, person: str) -> None:
    """Throw ``person``'s running timer away without saving anything."""
    with _immediate(conn):
        if conn.execute("DELETE FROM time_timers WHERE person = ?", (person,)).rowcount == 0:
            raise NoTimer(f"{person} has no timer running (stopped on another device?)")
    logger.info("ℹ️ time: %s discarded a timer", person)


# ------------------------------------------------------------------ totals


def period_start(period: str, today: date) -> date | None:
    """The first day ``period`` covers (``None`` = no lower bound)."""
    if period not in PERIODS:
        raise ValidationError(f"period must be one of {', '.join(PERIODS)}")
    if period == "all":
        return None
    return today - timedelta(days=(1 if period == "today" else int(period)) - 1)


def _counted_entries(conn: sqlite3.Connection, *, people: Collection[str], from_day: date | None,
                     to_day: date | None, area: str | None, person: str | None) -> list[sqlite3.Row]:
    """The entries Totals and the CSV both count — one query, so the two can
    never disagree. Only configured people count (see the module docstring)."""
    ids = [p for p in people if person is None or p == person]
    if not ids:
        return []
    clauses = [f"e.person IN ({', '.join('?' for _ in ids)})"]
    args: list[Any] = list(ids)
    if from_day is not None:
        clauses.append("e.day >= ?")
        args.append(from_day.isoformat())
    if to_day is not None:
        clauses.append("e.day <= ?")
        args.append(to_day.isoformat())
    if area:
        clauses.append("a.slug = ?")
        args.append(area)
    return conn.execute(_ENTRY_SELECT + " WHERE " + " AND ".join(clauses) + _ENTRY_ORDER, args).fetchall()


def summary(conn: sqlite3.Connection, *, people: Collection[str], period: str = "7", area: str | None = None,
            person: str | None = None) -> dict[str, Any]:
    """Totals for ``period`` (today · 7 · 30 · all), optionally one area (slug)
    and one person: the total, per person (with the days each logged
    something on), per area and per category within it — the prototype's
    ``sums`` and coverage arithmetic, for any number of people."""
    today = clock.today()
    start = period_start(period, today)
    rows = _counted_entries(conn, people=people, from_day=start, to_day=None, area=area, person=person)
    shown = [p for p in people if person is None or p == person]
    by_person = {p: 0 for p in shown}
    days: dict[str, set[str]] = {p: set() for p in shown}
    by_area: dict[int, dict[str, Any]] = {}
    by_category: dict[int, dict[str, Any]] = {}
    for r in rows:
        by_person[r["person"]] += r["minutes"]
        days[r["person"]].add(r["day"])
        a = by_area.setdefault(r["area_id"], {"id": r["area_id"], "slug": r["area_slug"],
                                              "name": r["area_name"], "minutes": 0})
        a["minutes"] += r["minutes"]
        c = by_category.setdefault(r["category_id"], {
            "id": r["category_id"], "slug": r["category_slug"], "name": r["category_name"],
            "area_slug": r["area_slug"], "minutes": 0, "by_person": {p: 0 for p in shown},
        })
        c["minutes"] += r["minutes"]
        c["by_person"][r["person"]] += r["minutes"]
    if start is not None:
        span = (today - start).days + 1
    else:
        first = min((r["day"] for r in rows), default=None)
        span = (today - date.fromisoformat(first)).days + 1 if first else 0
    return {
        "period": period, "from": start.isoformat() if start else None, "today": today.isoformat(),
        "area": area, "person": person, "span_days": span,
        "total_minutes": sum(by_person.values()),
        "by_person": by_person,
        "days_logged": {p: len(d) for p, d in days.items()},
        "by_area": sorted(by_area.values(), key=lambda x: (-x["minutes"], x["name"])),
        "by_category": sorted(by_category.values(), key=lambda x: (-x["minutes"], x["name"])),
    }


def entries_csv(conn: sqlite3.Connection, *, people: Collection[str], names: Mapping[str, str],
                from_day: date | None = None, to_day: date | None = None, area: str | None = None,
                person: str | None = None) -> str:
    """The counted entries as CSV, oldest first, for analysis outside the app."""
    rows = _counted_entries(conn, people=people, from_day=from_day, to_day=to_day, area=area, person=person)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in reversed(rows):
        writer.writerow((
            r["day"], (r["started_at"] or "")[11:16], (r["ended_at"] or "")[11:16], r["minutes"],
            r["person"], names.get(r["person"], r["person"]), r["area_name"], r["category_name"], r["note"],
        ))
    return out.getvalue()


# ----------------------------------------------------------------- guesses


def _guess(conn: sqlite3.Connection, person: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT pct, updated_at FROM time_guesses WHERE person = ?", (person,)).fetchone()
    return {"pct": row["pct"], "updated_at": row["updated_at"]} if row else None


def get_guesses(conn: sqlite3.Connection, person: str, *, people: Collection[str]) -> dict[str, Any]:
    """``person``'s own guess, and the others' only once ``person`` has locked
    one in (``others`` is ``None`` until then) — a courtesy so nobody anchors
    on the other answer, not security: every token holder could read the rows."""
    _check_person(person, people)
    mine = _guess(conn, person)
    others = None
    if mine is not None:
        others = {p: g for p in people if p != person and (g := _guess(conn, p)) is not None}
    return {"person": person, "mine": mine, "others": others}


def set_guess(conn: sqlite3.Connection, person: str, pct: int, *, people: Collection[str]) -> dict[str, Any]:
    _check_person(person, people)
    if not isinstance(pct, int) or isinstance(pct, bool) or not 0 <= pct <= 100:
        raise ValidationError("a guess is a whole percentage from 0 to 100")
    with _immediate(conn):
        conn.execute(
            "INSERT INTO time_guesses(person, pct, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(person) DO UPDATE SET pct = excluded.pct, updated_at = excluded.updated_at",
            (person, pct, clock.now_iso()),
        )
    logger.info("ℹ️ time: %s locked in a guess", person)
    return get_guesses(conn, person, people=people)


# ------------------------------------------------------------------ import


def import_rows(conn: sqlite3.Connection, entries: Iterable[Mapping[str, Any]],
                guesses: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """The prototype importer's one write (``scripts/import_time_prototype.py``),
    all of it in one transaction — any bad row and nothing lands.

    ``entries`` carry ``source_id`` (the prototype document id), ``person``,
    ``category_id``, ``day``, ``minutes``, ``note`` and ``created_at``; they are
    stored **without** a clock range (the prototype never recorded one) and an
    id already imported is left alone. ``guesses`` carry ``person``, ``pct``
    and ``updated_at``; a person who already has a guess keeps it."""
    counts = {"entries_inserted": 0, "entries_existing": 0, "guesses_inserted": 0, "guesses_existing": 0}
    with _immediate(conn):
        for e in entries:
            cur = conn.execute(
                "INSERT INTO time_entries(person, category_id, day, minutes, note, created_at, updated_at, source_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_id) DO NOTHING",
                (e["person"], e["category_id"], _parse_day(e["day"]).isoformat(), _check_minutes(e["minutes"]),
                 _check_note(e["note"]), e["created_at"], e["created_at"], e["source_id"]),
            )
            counts["entries_inserted" if cur.rowcount else "entries_existing"] += 1
        for g in guesses:
            if not isinstance(g["pct"], int) or not 0 <= g["pct"] <= 100:
                raise ValidationError(f"guess for {g['person']!r} is not a percentage")
            cur = conn.execute(
                "INSERT INTO time_guesses(person, pct, updated_at) VALUES (?, ?, ?) ON CONFLICT(person) DO NOTHING",
                (g["person"], g["pct"], g["updated_at"]),
            )
            counts["guesses_inserted" if cur.rowcount else "guesses_existing"] += 1
    return counts
