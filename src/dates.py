"""Dates — the small natural-language parser + recurrence arithmetic.

Shared by the ``tasks`` CLI today and by quick-add later, so the phrases a
user types map to one deterministic rule set:

    today · tomorrow · yesterday
    fri · friday               → the coming Friday (today if today is Friday)
    next fri · next friday     → the Friday after that (+7 days)
    next week / next month / next year
    in 3 days · in 2 weeks · in 1 month · in 1 year   (also "3d", "2w", "+2w")
    2026-09-01                  → ISO date, passed through
    none · clear · -            → explicit "no date" (returns ``None``)

Recurrence rolls advance a *due date*, never "now": ``advance(date(2026, 1,
31), "monthly")`` is ``2026-02-28`` (month-end clamps, never overflows into
March), quarterly is three months, yearly clamps Feb 29 → Feb 28.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

RECURRENCES = ("daily", "weekly", "monthly", "quarterly", "yearly")

_WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
_UNIT_DAYS = {"d": 1, "day": 1, "days": 1, "w": 7, "week": 7, "weeks": 7}
_UNIT_MONTHS = {"m": 1, "month": 1, "months": 1, "y": 12, "year": 12, "years": 12}
_NO_DATE = {"none", "clear", "-", "null", ""}

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_REL_RE = re.compile(r"^(?:in\s+|\+)?(\d+)\s*([a-z]+)$")


class DateParseError(ValueError):
    """The text is not a date phrase this parser knows."""


def add_months(d: date, months: int) -> date:
    """``d`` plus ``months`` calendar months, day clamped to the target month's end."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def advance(d: date, recurrence: str) -> date:
    """The next occurrence after ``d`` for a recurrence cadence."""
    if recurrence == "daily":
        return d + timedelta(days=1)
    if recurrence == "weekly":
        return d + timedelta(days=7)
    if recurrence == "monthly":
        return add_months(d, 1)
    if recurrence == "quarterly":
        return add_months(d, 3)
    if recurrence == "yearly":
        return add_months(d, 12)
    raise ValueError(f"unknown recurrence {recurrence!r} (expected one of {', '.join(RECURRENCES)})")


def _coming_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def parse_date(text: str | None, today: date | None = None) -> date | None:
    """Turn a natural or ISO phrase into a :class:`date`; ``None`` for "no date".

    Raises :class:`DateParseError` for anything unrecognised so a typo in
    ``--due`` is an error, never a silently unset date.
    """
    if text is None:
        return None
    today = today or date.today()
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)
    if s in _NO_DATE:
        return None

    m = _ISO_RE.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError as exc:
            raise DateParseError(f"invalid ISO date {text!r}: {exc}") from exc

    if s in ("today", "now", "tod"):
        return today
    if s in ("tomorrow", "tmr", "tom"):
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)
    if s == "next week":
        return today + timedelta(days=7)
    if s == "next month":
        return add_months(today, 1)
    if s == "next year":
        return add_months(today, 12)

    if s in _WEEKDAYS:
        return _coming_weekday(today, _WEEKDAYS[s])
    if s.startswith("next ") and s[5:] in _WEEKDAYS:
        return _coming_weekday(today, _WEEKDAYS[s[5:]]) + timedelta(days=7)

    m = _REL_RE.match(s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit in _UNIT_DAYS:
            return today + timedelta(days=n * _UNIT_DAYS[unit])
        if unit in _UNIT_MONTHS:
            return add_months(today, n * _UNIT_MONTHS[unit])

    raise DateParseError(
        f"cannot parse date {text!r} — try today, tomorrow, fri, next friday, in 2 weeks, or YYYY-MM-DD"
    )
