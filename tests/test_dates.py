"""``src/dates.py`` — the natural-date parser and recurrence arithmetic."""

from __future__ import annotations

from datetime import date

import pytest

from src.dates import DateParseError, add_months, advance, parse_date

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
def test_advance(start: date, cadence: str, expected: date) -> None:
    assert advance(start, cadence) == expected


def test_advance_unknown_cadence() -> None:
    with pytest.raises(ValueError):
        advance(MON, "fortnightly")
