"""Synthetic fixture dataset — the only data allowed in tests, e2e and screenshots.

Deterministic: the repo clock is pinned (one minute per write, starting 30
days before ``anchor``) and every id / timestamp / due date is a function of
``anchor`` alone, so a test can assert exact values and a screenshot taken
today looks the same as one taken next month (relative dates stay relative).
The runtime default anchor is **today** — that is what keeps relative dates
relative for the today-bucketing assertions (issue #29: a pinned default
drifted every seeded due one bucket per passing day); pass ``--anchor`` /
``anchor=`` only to pin a reproduction to a known date.

Shape: four projects nested to depth 3, ~40 tasks, three people, comments
(some carrying web / folder / issue links), links, activity from real
status / priority / due changes, a handful of recurring tasks, a few done or
cancelled, one ``coding`` task with an issue_ref, and one ``note``.

Use it:

    from tests.fixtures.seed import seed, seed_db
    seed(conn)                              # into an open connection
    seed_db(Path("…/tasks.db"))             # create + migrate + seed a file

    python -m tests.fixtures.seed --db E:/tmp/tasks.db [--reset] [--anchor 2026-08-17]

The e2e conftest / a disposable webapp point ``TASKOS_DB_PATH`` at a file
seeded this way. Nothing here comes from a real import.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src import tasks_repo as repo
from src.db import connect, init_db

# The frozen-clock unit suites (tests/test_repo.py, tests/test_views.py) pin
# the repo clock to this date and must seed with the same anchor so the two
# clocks agree; everything else seeds with the default (the real today).
PINNED_ANCHOR = date(2026, 8, 17)

PEOPLE = [
    ("Sam Rivera", "sam@example.com"),
    ("Alex Chen", "alex@example.com"),
    ("Jordan Lee", None),
]


class _Clock:
    """Advances one minute per call so ordering is stable and visible."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(minutes=1)
        return self.t


def _iso(anchor: date, days: int) -> str:
    return (anchor + timedelta(days=days)).isoformat()


def seed(conn: sqlite3.Connection, anchor: date | None = None) -> dict[str, Any]:
    """Populate an already-migrated database; returns ``{"ids": {...}, "counts": {...}}``.

    Raises if tasks already exist (never mixes with real data).
    """
    anchor = anchor or date.today()
    if conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]:
        raise RuntimeError("seed refuses to run on a database that already has tasks")

    start = datetime.combine(anchor - timedelta(days=30), datetime.min.time()).astimezone()
    d = lambda n: _iso(anchor, n)  # noqa: E731
    ids: dict[str, int] = {}

    with repo.use_clock(_Clock(start)):
        people = {name: repo.create_person(conn, name, email=email)["id"] for name, email in PEOPLE}
        sam, alex, jordan = (people[p[0]] for p in PEOPLE)

        def task(key: str, title: str, **fields: Any) -> int:
            t = repo.create_task(conn, title, actor="seed", **fields)
            ids[key] = t["id"]
            return t["id"]

        # ---- project 1: Home renovation (depth 3) -----------------------
        home = task("home", "Home renovation", status="doing", priority="high",
                    description="Everything about the house works, room by room.",
                    folder_ref="{onedrive}/house")
        kitchen = task("kitchen", "Kitchen", parent_id=home, status="doing", priority="high",
                       folder_ref="{onedrive}/house/kitchen")
        task("quotes", "Get three quotes", parent_id=kitchen, status="doing", due=d(3), person_id=sam)
        task("worktop", "Choose worktop material", parent_id=kitchen, status="todo", due=d(10))
        task("installer", "Book installer", parent_id=kitchen, status="todo", due=d(21), person_id=alex)
        bathroom = task("bathroom", "Bathroom", parent_id=home, status="todo")
        task("tap", "Fix leaking tap", parent_id=bathroom, status="todo", due=d(-4), priority="medium")
        task("ceiling", "Repaint ceiling", parent_id=bathroom, status="todo", due=d(14))
        garden = task("garden", "Garden", parent_id=home, status="standby")
        task("tomatoes", "Plant tomatoes", parent_id=garden, status="standby", due=d(30))
        task("fence", "Repair fence", parent_id=garden, status="todo", due=d(-10), priority="low")

        # ---- project 2: Family admin (depth 3, recurring) --------------
        family = task("family", "Family admin", status="todo", priority="medium",
                      description="Renewals, bills, forms.")
        passports = task("passports", "Renew passports", parent_id=family, status="doing", due=d(4), priority="high")
        task("appointment", "Book appointment", parent_id=passports, status="todo", due=d(1))
        task("photos", "Collect photos", parent_id=passports, status="done", due=d(-2))
        task("school", "School enrolment forms", parent_id=family, status="todo", due=d(0), priority="high", person_id=jordan)
        task("car", "Car insurance renewal", parent_id=family, status="todo", due=d(45), recurrence="yearly")
        task("water", "Pay water bill", parent_id=family, status="todo", due=d(7), recurrence="monthly")
        task("dentist", "Dentist check-up", parent_id=family, status="todo", due=d(0), recurrence="quarterly")

        # ---- project 3: Side project garden-bot (coding) ---------------
        bot = task("bot", "Side project: garden-bot", status="doing", priority="medium",
                   description="A tiny watering controller for the balcony.",
                   folder_ref="{user}/code/garden-bot")
        watering = task("watering", "Fix watering schedule drift", parent_id=bot, status="doing", due=d(2), priority="high")
        sensor = task("sensor", "Add moisture sensor", parent_id=bot, status="todo", due=d(20))
        task("order", "Order sensor", parent_id=sensor, status="done", due=d(-5))
        task("driver", "Write sensor driver", parent_id=sensor, status="todo", due=d(18))
        task("readme", "Write README", parent_id=bot, status="todo", due=d(25), priority="low")
        task("release", "Release v0.2", parent_id=bot, status="standby", due=d(40))
        repo.set_issue_ref(conn, watering, provider="github", repo="example/garden-bot", number=12,
                           url="https://github.com/example/garden-bot/issues/12", state="open", actor="seed")

        # ---- project 4: Learning (recurring daily/weekly) --------------
        learning = task("learning", "Learning", status="todo", priority="low")
        spanish = task("spanish", "Spanish", parent_id=learning, status="doing")
        task("lesson", "Lesson 12: past tense", parent_id=spanish, status="todo", due=d(2))
        task("vocab", "Vocabulary review", parent_id=spanish, status="todo", due=d(0), recurrence="weekly")
        piano = task("piano", "Piano", parent_id=learning, status="todo")
        task("scales", "Practice scales", parent_id=piano, status="todo", due=d(0), recurrence="daily")
        task("piece", "Learn a new piece", parent_id=piano, status="todo", due=d(28))
        task("book", "Read a book on focus", parent_id=learning, status="todo", due=d(35))

        # ---- loose tasks --------------------------------------------------
        task("callback", "Call the plumber back", status="todo", due=d(0), priority="high", person_id=sam)
        task("library", "Return library books", status="todo", due=d(-3), priority="medium")
        task("review", "Weekly review", status="todo", due=d(5), recurrence="weekly")
        task("gift", "Buy a birthday gift", status="done", due=d(-7))
        task("bikes", "Sell the old bikes", status="cancelled")
        task("inbox1", "Look into a standing desk", status="inbox")
        task("inbox2", "Try the new bakery", status="inbox")
        task("inbox3", "Compare phone plans", status="inbox", due=d(12))
        task("reading", "Reading list", type="note",
             description="- a book on focus\n- a book on gardening\n- the garden-bot docs")

        # ---- comments (some with links) ---------------------------------
        repo.add_comment(conn, ids["quotes"], "First quote in: https://example.com/quotes/1 — a bit high.", author="Sam Rivera", origin="ui")
        repo.add_comment(conn, ids["quotes"], "Second quote asked, waiting until Friday.", author="Sam Rivera", origin="cli")
        repo.add_comment(conn, ids["quotes"], "Plans are in {onedrive}/house/kitchen/plans", author="Alex Chen", origin="ui")
        repo.add_comment(conn, ids["appointment"], "Called the office — earliest slot is next week.", author="Jordan Lee", origin="cli")
        repo.add_comment(conn, ids["watering"], "Drift traced to the RTC; see example/garden-bot#12", author="Alex Chen", origin="ui")
        repo.add_comment(conn, ids["tap"], "Needs a new washer, size 15mm.", author="Sam Rivera", origin="ui")
        repo.add_comment(conn, ids["car"], "Renewed until next year; keep the letter in {onedrive}/admin/car", author="Jordan Lee", origin="md")
        repo.add_comment(conn, ids["lesson"], "Homework: exercises 3-5", author="Sam Rivera", origin="ui")
        repo.add_comment(conn, ids["release"], "Blocked on the sensor driver.", author="Alex Chen", origin="ui")

        # ---- links --------------------------------------------------------
        repo.add_link(conn, ids["kitchen"], "https://example.com/kitchen-ideas", label="Ideas board", kind="web")
        repo.add_link(conn, ids["kitchen"], "{onedrive}/house/kitchen", label="Kitchen folder", kind="folder")
        repo.add_link(conn, ids["passports"], "mail://renewal-instructions", label="Renewal instructions", kind="email")
        repo.add_link(conn, ids["watering"], "https://github.com/example/garden-bot/issues/12", label="garden-bot#12", kind="issue")
        repo.add_link(conn, ids["book"], "https://example.com/reading", label="Where to buy", kind="web")

        # ---- activity beyond creation: real edits ------------------------
        repo.set_priority(conn, ids["tap"], "high", actor="Sam Rivera")
        repo.set_due(conn, ids["installer"], d(24), actor="Alex Chen")
        repo.set_status(conn, ids["fence"], "standby", actor="seed")
        repo.set_status(conn, ids["fence"], "todo", actor="seed")
        repo.move(conn, ids["review"], ids["family"], actor="seed")
        repo.move(conn, ids["review"], None, actor="seed")
        repo.done(conn, ids["scales"], actor="seed")   # daily → rolls to d(1)
        repo.set_due(conn, ids["scales"], d(0), actor="seed")  # …and back, so "today" stays populated

    return {"ids": ids, "counts": repo.counts(conn)}


def seed_db(path: Path, anchor: date | None = None, reset: bool = False) -> dict[str, Any]:
    """Create/migrate the file at ``path`` and seed it (``reset`` deletes it first)."""
    if reset:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(path) + suffix)
            if p.exists():
                p.unlink()
    init_db(path)
    conn = connect(path)
    try:
        return seed(conn, anchor)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="seed a task-os database with the synthetic fixture")
    p.add_argument("--db", required=True, help="database file to create/seed")
    p.add_argument("--reset", action="store_true", help="delete the file first")
    p.add_argument("--anchor", default=None, help="'today' for the fixture (YYYY-MM-DD; default: the real today)")
    args = p.parse_args(argv)
    anchor = date.fromisoformat(args.anchor) if args.anchor else None
    result = seed_db(Path(args.db), anchor, reset=args.reset)
    print(f"seeded {args.db}: {result['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
