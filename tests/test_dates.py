"""``src/dates.py`` — the natural-date parser and recurrence arithmetic."""

from __future__ import annotations

from datetime import date

import pytest

from src.dates import (
    AnchorError,
    DateParseError,
    add_months,
    describe_recurrence,
    next_due,
    normalise_anchor,
    parse_date,
)

MON = date(2026, 8, 17)  # a Monday
FRI = date(2026, 8, 21)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", MON),
        ("Today ", MON),
        ("tomorrow", date(2026, 8, 18)),
        ("yesterday", date(2026, 8, 16)),
        ("fri", FRI),
        ("Friday", FRI),
        ("mon", MON),                      # same weekday → today
        ("next mon", date(2026, 8, 24)),   # → +7
        ("next fri", date(2026, 8, 28)),
        ("next friday", date(2026, 8, 28)),
        ("next week", date(2026, 8, 24)),
        ("next month", date(2026, 9, 17)),
        ("next year", date(2027, 8, 17)),
        ("in 3 days", date(2026, 8, 20)),
        ("in 2 weeks", date(2026, 8, 31)),
        ("2w", date(2026, 8, 31)),
        ("+10d", date(2026, 8, 27)),
        ("in 1 month", date(2026, 9, 17)),
        ("in 1 year", date(2027, 8, 17)),
        ("2026-09-01", date(2026, 9, 1)),
        # the snooze menu's middle option (#87) — the coming Saturday
        ("this weekend", date(2026, 8, 22)),
        ("weekend", date(2026, 8, 22)),
        # month-name dates (#87): the coming occurrence, this year or next
        ("oct 15", date(2026, 10, 15)),
        ("Oct 15", date(2026, 10, 15)),
        ("october 15", date(2026, 10, 15)),
        ("15 oct", date(2026, 10, 15)),
        ("15th october", date(2026, 10, 15)),
        ("oct 15, 2028", date(2028, 10, 15)),
        ("aug 17", MON),                    # today itself is not "next year"
        ("aug 16", date(2027, 8, 16)),      # yesterday already passed → next year
        ("jan 5", date(2027, 1, 5)),
    ],
)
def test_parse_natural(text: str, expected: date) -> None:
    assert parse_date(text, today=MON) == expected


def test_this_weekend_on_a_saturday_stays_that_day() -> None:
    """`_coming_weekday`'s rule, stated for the phrase the snooze menu sends:
    Saturday means today, Sunday means the Saturday six days out."""
    assert parse_date("this weekend", today=date(2026, 8, 22)) == date(2026, 8, 22)
    assert parse_date("this weekend", today=date(2026, 8, 23)) == date(2026, 8, 29)


@pytest.mark.parametrize("text", ["none", "clear", "-", "", "  "])
def test_parse_no_date(text: str) -> None:
    assert parse_date(text, today=MON) is None
    assert parse_date(None) is None


@pytest.mark.parametrize(
    "text",
    ["nonsense", "2026-13-01", "in two weeks", "32/01/2026", "next",
     # a month name alone is not a date, and an impossible day is an error,
     # never a silently clamped one (#87)
     "october", "oct", "feb 30", "oct 32"],
)
def test_parse_rejects_unknown(text: str) -> None:
    with pytest.raises(DateParseError):
        parse_date(text, today=MON)


def test_add_months_clamps_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)   # leap year
    assert add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)  # year rollover


@pytest.mark.parametrize(
    ("start", "cadence", "expected"),
    [
        (date(2026, 8, 31), "daily", date(2026, 9, 1)),
        (date(2026, 8, 31), "weekly", date(2026, 9, 7)),
        (date(2026, 8, 31), "monthly", date(2026, 9, 30)),
        (date(2026, 1, 31), "monthly", date(2026, 2, 28)),
        (date(2026, 11, 30), "quarterly", date(2027, 2, 28)),
        (date(2028, 2, 29), "yearly", date(2029, 2, 28)),
        (date(2026, 12, 31), "yearly", date(2027, 12, 31)),
    ],
)
def test_next_due_plain_cadence(start: date, cadence: str, expected: date) -> None:
    """Completed on its due day: one cadence on, exactly as before #112."""
    assert next_due(start, cadence, today=start) == expected


def test_next_due_unknown_cadence() -> None:
    with pytest.raises(ValueError):
        next_due(MON, "fortnightly")


# ---------------------------------------------------------------- anchors


@pytest.mark.parametrize(
    ("cadence", "raw", "canonical"),
    [
        ("weekly", "fri", "fri"),
        ("weekly", "Friday", "fri"),
        ("weekly", " FRI , mon ", "mon,fri"),          # sorted Monday-first, spaces dropped
        ("weekly", "mon,mon,tue", "mon,tue"),          # duplicates collapse
        ("weekly", "mon,tue,wed,thu,fri", "mon,tue,wed,thu,fri"),
        ("monthly", "day-15", "day-15"),
        ("monthly", "DAY-1", "day-1"),
        ("monthly", "1-sunday", "1-sun"),
        ("monthly", "last-fri", "last-fri"),
        ("weekly", "", None),
        ("weekly", None, None),
        ("daily", None, None),
    ],
)
def test_normalise_anchor(cadence: str, raw: str | None, canonical: str | None) -> None:
    assert normalise_anchor(cadence, raw) == canonical


@pytest.mark.parametrize(
    ("cadence", "raw"),
    [
        ("daily", "fri"),          # cadence carries no anchor
        ("quarterly", "day-1"),
        ("yearly", "fri"),
        (None, "fri"),
        ("weekly", "funday"),      # not a weekday
        ("weekly", "fri,funday"),
        ("weekly", "day-15"),      # monthly grammar on a weekly cadence
        ("monthly", "day-0"),      # out of range
        ("monthly", "day-32"),
        ("monthly", "5-sun"),      # no 5th weekday — every month must have one
        ("monthly", "fri"),        # weekly grammar on a monthly cadence
        ("monthly", "first-sun"),
    ],
)
def test_normalise_anchor_rejects(cadence: str | None, raw: str) -> None:
    with pytest.raises(AnchorError):
        normalise_anchor(cadence, raw)


# The user story (#112): a Friday task ticked on a Monday lands on Friday.
def test_next_due_anchored_weekday_from_a_different_day() -> None:
    assert next_due(date(2026, 8, 14), "weekly", "fri", today=MON) == FRI  # Fri 14th → Fri 21st


def test_next_due_anchored_catches_up_from_far_overdue() -> None:
    """Three weeks late still lands on the *coming* Friday, never another past one."""
    assert next_due(date(2026, 7, 24), "weekly", "fri", today=MON) == FRI


def test_next_due_anchored_completed_early_moves_a_whole_cadence() -> None:
    """Ticked on Wednesday while due Friday: the due one is done, so the next is a week on."""
    assert next_due(FRI, "weekly", "fri", today=date(2026, 8, 19)) == date(2026, 8, 28)


def test_next_due_anchored_on_its_own_day() -> None:
    assert next_due(FRI, "weekly", "fri", today=FRI) == date(2026, 8, 28)


def test_next_due_weekday_list_picks_the_nearest_day() -> None:
    # Mon–Fri, completed on the Monday → Tuesday; completed on the Friday → Monday.
    assert next_due(MON, "weekly", "mon,tue,wed,thu,fri", today=MON) == date(2026, 8, 18)
    assert next_due(FRI, "weekly", "mon,tue,wed,thu,fri", today=FRI) == date(2026, 8, 24)


def test_next_due_plain_cadence_catches_up() -> None:
    """An overdue weekly keeps its weekday and lands ahead of today (#112)."""
    rolled = next_due(date(2026, 7, 20), "weekly", today=MON)  # a Monday, four weeks back
    assert rolled == date(2026, 8, 24)
    assert rolled.weekday() == 0


def test_next_due_plain_monthly_catch_up_measures_from_the_original_due() -> None:
    """Jan 31 → Feb 28 → Mar 31: the clamp applies per month, it does not stick."""
    assert next_due(date(2026, 1, 31), "monthly", today=date(2026, 3, 1)) == date(2026, 3, 31)


@pytest.mark.parametrize(
    ("due", "anchor", "today", "expected"),
    [
        ("2026-08-15", "day-15", "2026-08-15", date(2026, 9, 15)),
        ("2026-01-31", "day-31", "2026-01-31", date(2026, 2, 28)),   # clamped to a short month
        ("2028-01-31", "day-31", "2028-01-31", date(2028, 2, 29)),   # leap year
        ("2026-08-02", "1-sun", "2026-08-02", date(2026, 9, 6)),     # first Sunday
        ("2026-08-01", "1-sat", "2026-08-01", date(2026, 9, 5)),     # the 1st itself is one
        ("2026-08-28", "last-fri", "2026-08-28", date(2026, 9, 25)),
        ("2026-08-11", "2-tue", "2026-08-11", date(2026, 9, 8)),
        ("2026-05-04", "1-sun", "2026-06-02", date(2026, 6, 7)),     # overdue → catches up
    ],
)
def test_next_due_monthly_anchor(due: str, anchor: str, today: str, expected: date) -> None:
    assert next_due(date.fromisoformat(due), "monthly", anchor, today=date.fromisoformat(today)) == expected


def test_next_due_without_a_due_rolls_from_today() -> None:
    assert next_due(None, "weekly", "fri", today=MON) == FRI
    assert next_due(None, "weekly", today=MON) == date(2026, 8, 24)


@pytest.mark.parametrize(
    ("cadence", "anchor", "label"),
    [
        ("weekly", None, "weekly"),
        ("quarterly", None, "quarterly"),
        ("weekly", "fri", "every Friday"),
        ("weekly", "mon,tue,wed,thu,fri", "every weekday"),
        ("weekly", "mon,thu", "every Monday and Thursday"),
        ("monthly", "day-15", "monthly on the 15th"),
        ("monthly", "day-1", "monthly on the 1st"),
        ("monthly", "day-22", "monthly on the 22nd"),
        ("monthly", "1-sun", "monthly on the first Sunday"),
        ("monthly", "last-fri", "monthly on the last Friday"),
        (None, None, ""),
    ],
)
def test_describe_recurrence(cadence: str | None, anchor: str | None, label: str) -> None:
    assert describe_recurrence(cadence, anchor) == label
