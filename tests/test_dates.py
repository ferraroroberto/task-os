"""``src/dates.py`` — the natural-date parser and recurrence arithmetic."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

import pytest

from src import clock
from src.dates import (
    MAX_INTERVAL,
    RECURRENCES,
    AnchorError,
    DateParseError,
    IntervalError,
    add_months,
    describe_recurrence,
    next_due,
    normalise_anchor,
    normalise_interval,
    parse_date,
    parse_interval,
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


# ------------------------------------------------ every-N intervals (#229)

@pytest.mark.parametrize(
    ("raw", "stored"),
    [(None, None), ("", None), ("  ", None), (1, None), ("1", None),
     (2, 2), (7, 7), (" 7 ", 7), (MAX_INTERVAL, MAX_INTERVAL)],
)
def test_normalise_interval(raw: object, stored: int | None) -> None:
    for cadence in RECURRENCES:
        assert normalise_interval(cadence, raw) == stored


@pytest.mark.parametrize("raw", [0, -3, MAX_INTERVAL + 1, "seven", "7.5", 7.5, True, "2w"])
def test_parse_interval_rejects(raw: object) -> None:
    with pytest.raises(IntervalError):
        parse_interval(raw)


def test_an_interval_needs_a_recurrence() -> None:
    with pytest.raises(IntervalError):
        normalise_interval(None, 7)
    assert normalise_interval(None, 1) is None   # "every one" of nothing is still nothing


@pytest.mark.parametrize(
    ("cadence", "interval", "expected"),
    [
        ("daily", 3, date(2026, 8, 20)),
        ("weekly", 2, date(2026, 8, 31)),
        ("monthly", 2, date(2026, 10, 17)),
        ("quarterly", 2, date(2027, 2, 17)),
        ("yearly", 3, date(2029, 8, 17)),
    ],
)
def test_next_due_unanchored_interval(cadence: str, interval: int, expected: date) -> None:
    assert next_due(MON, cadence, None, interval, today=MON) == expected


@pytest.mark.parametrize("cadence", RECURRENCES)
@pytest.mark.parametrize("interval", [None, 1])
def test_an_interval_of_one_rolls_exactly_as_no_interval(cadence: str, interval: int | None) -> None:
    """NULL and 1 are today's roll — every existing recurring task is unaffected."""
    anchors = {"weekly": [None, "fri", "mon,wed"], "monthly": [None, "day-31", "last-fri"]}
    for anchor in anchors.get(cadence, [None]):
        for due in (date(2026, 1, 31), MON, date(2026, 7, 4)):
            for today in (due, MON, date(2026, 12, 30)):
                assert next_due(due, cadence, anchor, interval, today=today) == next_due(
                    due, cadence, anchor, today=today
                )


def _roll(due: date, cadence: str, anchor: str | None, interval: int, today: date) -> date:
    return next_due(due, cadence, anchor, interval, today=today)


# The story (#229): treat the clothes against moths every 7 weeks, on a Saturday.
def test_every_seven_weeks_on_saturday_never_drifts() -> None:
    """Forty completions — early, on the day, late — stay on the original 7-week grid."""
    first = date(2026, 9, 5)  # a Saturday
    assert _roll(first, "weekly", "sat", 7, today=first) == date(2026, 10, 24)
    due = first
    for n in range(40):
        ticked = due + timedelta(days=(-3, 0, 4, 20)[n % 4])   # early · on time · late · very late
        rolled = _roll(due, "weekly", "sat", 7, today=ticked)
        assert rolled.weekday() == 5
        assert (rolled - first).days % 49 == 0
        assert rolled > ticked
        assert (rolled - due).days >= 49   # never a plain next-Saturday roll
        due = rolled


def test_an_overdue_interval_catches_up_onto_its_own_phase() -> None:
    """Three months late, the roll lands on the next qualifying Saturday, not the next Saturday."""
    assert _roll(date(2026, 9, 5), "weekly", "sat", 7, today=date(2026, 12, 1)) == date(2026, 12, 12)


def test_the_due_week_sets_the_phase_for_an_anchored_interval() -> None:
    """A due off the anchor day lands on the anchor in its own week — the N = 1 rule —
    and from there every step is a whole interval."""
    wednesday = date(2026, 9, 2)
    first = _roll(wednesday, "weekly", "sat", 7, today=wednesday)
    assert first == date(2026, 9, 5)
    assert _roll(first, "weekly", "sat", 7, today=first) == date(2026, 10, 24)


def test_a_weekday_list_interval_uses_every_day_of_a_qualifying_week() -> None:
    """Mon/Wed/Fri every 2 weeks: Monday → Wednesday, then Friday → the Monday two weeks on."""
    assert _roll(MON, "weekly", "mon,wed,fri", 2, today=MON) == date(2026, 8, 19)
    assert _roll(FRI, "weekly", "mon,wed,fri", 2, today=FRI) == date(2026, 8, 31)


@pytest.mark.parametrize(
    ("due", "anchor", "interval", "expected"),
    [
        ("2026-08-15", "day-15", 3, date(2026, 11, 15)),
        ("2026-08-28", "last-fri", 2, date(2026, 10, 30)),
        ("2026-12-06", "1-sun", 2, date(2027, 2, 7)),       # across the year end
        ("2026-01-31", "day-31", 3, date(2026, 4, 30)),     # clamped, then …
        ("2026-04-30", "day-31", 3, date(2026, 7, 31)),     # … back on the 31st
    ],
)
def test_next_due_monthly_anchor_interval(due: str, anchor: str, interval: int, expected: date) -> None:
    d = date.fromisoformat(due)
    assert _roll(d, "monthly", anchor, interval, today=d) == expected


def test_a_monthly_anchor_interval_never_drifts() -> None:
    first = date(2026, 1, 31)
    due = first
    for n in range(24):
        ticked = due + timedelta(days=(0, 10, -2)[n % 3])
        rolled = _roll(due, "monthly", "day-31", 2, today=ticked)
        months = (rolled.year - first.year) * 12 + rolled.month - first.month
        assert months % 2 == 0 and rolled > ticked
        assert rolled.day == calendar.monthrange(rolled.year, rolled.month)[1]
        due = rolled


def test_a_plain_monthly_interval_catch_up_measures_from_the_original_due() -> None:
    """Every 2 months from Dec 31, ticked on Mar 1: Feb 28 is passed over and the
    candidate after it is Apr 30 — measured from the 31st, not stepped from the 28th."""
    assert _roll(date(2025, 12, 31), "monthly", None, 2, today=date(2026, 3, 1)) == date(2026, 4, 30)


@pytest.mark.parametrize(
    ("cadence", "anchor", "interval", "label"),
    [
        ("weekly", "sat", 7, "every 7 weeks on Saturday"),
        ("weekly", "mon,thu", 2, "every 2 weeks on Monday and Thursday"),
        ("weekly", "mon,tue,wed,thu,fri", 2, "every 2 weeks on weekdays"),
        ("weekly", None, 3, "every 3 weeks"),
        ("daily", None, 3, "every 3 days"),
        ("monthly", "day-15", 2, "every 2 months on the 15th"),
        ("monthly", "last-fri", 6, "every 6 months on the last Friday"),
        ("monthly", None, 2, "every 2 months"),
        ("quarterly", None, 2, "every 2 quarters"),
        ("yearly", None, 5, "every 5 years"),
        ("weekly", "fri", 1, "every Friday"),
        ("yearly", None, None, "yearly"),
    ],
)
def test_describe_recurrence_with_an_interval(
    cadence: str, anchor: str | None, interval: int | None, label: str
) -> None:
    assert describe_recurrence(cadence, anchor, interval) == label


def test_the_default_today_is_the_process_clock_not_the_machine() -> None:
    """A pinned process resolves "tomorrow" against the day it believes in (#225).

    The e2e instances run on `TASKOS_CLOCK`, and the date this parser writes
    into the quick-add Due field is on the screenshot. Reading `date.today()`
    here made that one value the only thing on the page still following the
    machine's calendar, so the gallery could never match its committed self.
    """
    pinned = datetime.combine(MON, datetime.min.time()).astimezone()
    with clock.use_clock(lambda: pinned):
        assert parse_date("today") == MON
        assert parse_date("tomorrow") == date(2026, 8, 18)
        assert parse_date("next friday") == date(2026, 8, 28)
        assert next_due(None, "weekly", "fri") == FRI
