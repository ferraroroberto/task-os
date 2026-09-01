"""Dates — the small natural-language parser + recurrence arithmetic.

Shared by the ``tasks`` CLI today and by quick-add later, so the phrases a
user types map to one deterministic rule set:

    today · tomorrow · yesterday
    fri · friday               → the coming Friday (today if today is Friday)
    next fri · next friday     → the Friday after that (+7 days)
    this weekend · weekend     → the coming Saturday (today if today is Saturday)
    next week / next month / next year
    in 3 days · in 2 weeks · in 1 month · in 1 year   (also "3d", "2w", "+2w")
    oct 15 · 15 oct · october 15  → that day this year, or next year once it
                                    has passed (the same "coming" rule the
                                    weekday phrases use); add a year to pin it
                                    ("oct 15 2028")
    2026-09-01                  → ISO date, passed through
    none · clear · -            → explicit "no date" (returns ``None``)

Recurrence rolls advance a *due date*, never "now": ``advance(date(2026, 1,
31), "monthly")`` is ``2026-02-28`` (month-end clamps, never overflows into
March), quarterly is three months, yearly clamps Feb 29 → Feb 28.

A recurrence may also carry an **anchor** — the fixed day it lands on, stored
beside the cadence in ``tasks.recurrence_anchor`` (issue #112, the iCalendar
split ``FREQ=WEEKLY;BYDAY=FR``):

    weekly  + ``fri``                  every Friday
    weekly  + ``mon,tue,wed,thu,fri``  every weekday
    monthly + ``day-15``               the 15th, clamped to a short month's end
    monthly + ``1-sun`` … ``4-sun``    the nth weekday of the month
    monthly + ``last-fri``             the last such weekday of the month
    daily / quarterly / yearly         no anchor
    (no anchor)                        the plain offset from the due date

:func:`next_due` is the one roll used on completion, anchored or not: the
first occurrence strictly after the completed due *and* strictly after today,
so a task three weeks overdue lands in the future instead of on another
overdue date. Candidates are always measured from the original due, never
accumulated step by step, so a plain monthly on the 31st reads Feb 28 → Mar 31
→ Apr 30 rather than drifting onto the 28th for good.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

RECURRENCES = ("daily", "weekly", "monthly", "quarterly", "yearly")
#: Cadences that can carry a fixed-day anchor (#112) — the rest are pure offsets.
ANCHORED_RECURRENCES = ("weekly", "monthly")
#: Canonical weekday abbreviations, Monday-first (``date.weekday()`` order).
WEEKDAY_ABBR = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
#: The weekday-list anchor behind "every weekday".
WEEKDAYS_ANCHOR = "mon,tue,wed,thu,fri"

# Spelled out here rather than read from ``calendar.day_name``, which follows
# the process locale — the label a task carries must not depend on it.
_WEEKDAY_FULL = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)
_ORDINAL_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth"}

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

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_ANCHOR_DAY_RE = re.compile(r"^day-(\d{1,2})$")
_ANCHOR_NTH_RE = re.compile(r"^(1|2|3|4|last)-([a-z]+)$")

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_REL_RE = re.compile(r"^(?:in\s+|\+)?(\d+)\s*([a-z]+)$")
# "oct 15", "oct 15 2028", "15 oct", "15 october 2028" — an ordinal suffix
# ("15th") and a trailing comma are tolerated because people type them.
_MONTH_DAY_RE = re.compile(r"^([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?,?(?: (\d{4}))?$")
_DAY_MONTH_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)? ([a-z]+)\.?,?(?: (\d{4}))?$")


class DateParseError(ValueError):
    """The text is not a date phrase this parser knows."""


class AnchorError(ValueError):
    """The anchor is not a fixed day this cadence can carry."""


def add_months(d: date, months: int) -> date:
    """``d`` plus ``months`` calendar months, day clamped to the target month's end."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def normalise_anchor(recurrence: str | None, anchor: str | None) -> str | None:
    """The canonical spelling of ``anchor`` for ``recurrence``, or ``None``.

    ``None`` / blank is "no anchor" — the plain offset roll. Input is
    forgiving (case, spaces, ``friday`` for ``fri``, any weekday order) and
    the result is canonical, so ``"Friday, MON"`` on a weekly stores as
    ``"mon,fri"`` and two spellings of the same anchor compare equal.

    Raises :class:`AnchorError` for an anchor on a cadence that cannot carry
    one, and for anything outside the grammar — a typo must be a rejection,
    never a silently unanchored task.
    """
    if anchor is None or not str(anchor).strip():
        return None
    text = re.sub(r"\s+", "", str(anchor).strip().lower())
    if recurrence not in ANCHORED_RECURRENCES:
        raise AnchorError(
            f"recurrence {recurrence!r} takes no anchor "
            f"(only {', '.join(ANCHORED_RECURRENCES)} do)"
        )

    if recurrence == "weekly":
        days: list[int] = []
        for part in text.split(","):
            if part not in _WEEKDAYS:
                raise AnchorError(
                    f"unknown weekday {part!r} in anchor {anchor!r} — "
                    f"try {', '.join(WEEKDAY_ABBR)}, or a comma-separated list"
                )
            if _WEEKDAYS[part] not in days:
                days.append(_WEEKDAYS[part])
        return ",".join(WEEKDAY_ABBR[d] for d in sorted(days))

    m = _ANCHOR_DAY_RE.match(text)
    if m:
        day = int(m.group(1))
        if not 1 <= day <= 31:
            raise AnchorError(f"day-of-month {day} out of range in anchor {anchor!r} (1–31)")
        return f"day-{day}"
    m = _ANCHOR_NTH_RE.match(text)
    if m and m.group(2) in _WEEKDAYS:
        return f"{m.group(1)}-{WEEKDAY_ABBR[_WEEKDAYS[m.group(2)]]}"
    raise AnchorError(
        f"cannot parse monthly anchor {anchor!r} — try day-15, 1-sun, or last-fri"
    )


def _anchor_weekdays(anchor: str) -> list[int]:
    return [_WEEKDAYS[part] for part in anchor.split(",")]


def _next_weekday_after(d: date, weekdays: list[int]) -> date:
    """The first day strictly after ``d`` whose weekday is in ``weekdays``."""
    for step in range(1, 8):
        candidate = d + timedelta(days=step)
        if candidate.weekday() in weekdays:
            return candidate
    raise AssertionError("unreachable: a week always contains an anchored weekday")


def _monthly_anchor_date(anchor: str, year: int, month: int) -> date:
    """The day ``anchor`` picks out of one month.

    ``day-N`` clamps to the month's end (the 31st is the 30th in April), and
    the ordinals stop at the 4th so every month has one — a "5th Tuesday"
    would be missing from most months, and skipping months is not a cadence.
    """
    last_day = calendar.monthrange(year, month)[1]
    m = _ANCHOR_DAY_RE.match(anchor)
    if m:
        return date(year, month, min(int(m.group(1)), last_day))
    ordinal, name = anchor.split("-")
    weekday = _WEEKDAYS[name]
    if ordinal == "last":
        end = date(year, month, last_day)
        return end - timedelta(days=(end.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (int(ordinal) - 1) * 7)


def _next_monthly_anchor_after(d: date, anchor: str) -> date:
    """The first date the monthly ``anchor`` picks out, strictly after ``d``."""
    year, month = d.year, d.month
    for _ in range(3):  # this month, then the next — the third is pure paranoia
        candidate = _monthly_anchor_date(anchor, year, month)
        if candidate > d:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise AssertionError(f"unreachable: no {anchor!r} occurrence within three months of {d}")


def _next_offset_after(base: date, recurrence: str, floor: date) -> date:
    """The first ``base + k × cadence`` (k ≥ 1) strictly after ``floor``.

    Measured from ``base`` every time rather than accumulated, so a monthly on
    the 31st reads Feb 28 → Mar 31 → Apr 30 instead of clamping once and
    living on the 28th ever after.
    """
    days = {"daily": 1, "weekly": 7}.get(recurrence)
    if days:
        return base + timedelta(days=((floor - base).days // days + 1) * days)
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}[recurrence]
    step = 1
    while True:
        candidate = add_months(base, months * step)
        if candidate > floor:
            return candidate
        step += 1


def next_due(
    due: date | None,
    recurrence: str,
    anchor: str | None = None,
    *,
    today: date | None = None,
) -> date:
    """The due date a recurring task rolls to when it is completed (#112).

    The first occurrence strictly after **both** the completed ``due`` and
    ``today``: completing a Friday-anchored task on a Monday lands on the
    coming Friday rather than the next Monday, and a task three weeks overdue
    catches up into the future instead of rolling onto another overdue date.
    Completing early still moves a whole cadence — the occurrence being
    completed is the one that is due, so the next one is the one after it.

    ``due`` of ``None`` rolls from today. An unanchored cadence keeps the
    plain offset it has always had, now with the same catch-up.
    """
    if recurrence not in RECURRENCES:
        raise ValueError(
            f"unknown recurrence {recurrence!r} (expected one of {', '.join(RECURRENCES)})"
        )
    today = today or date.today()
    base = due if due is not None else today
    floor = max(base, today)
    canonical = normalise_anchor(recurrence, anchor)
    if canonical is None:
        return _next_offset_after(base, recurrence, floor)
    if recurrence == "weekly":
        return _next_weekday_after(floor, _anchor_weekdays(canonical))
    return _next_monthly_anchor_after(floor, canonical)


def describe_recurrence(recurrence: str | None, anchor: str | None = None) -> str:
    """A human label for a cadence + anchor — ``"every Friday"``, ``"monthly on the 15th"``.

    The one place the wording is decided; ``format.js`` mirrors it for the web
    UI and the CLI prints it verbatim.
    """
    if not recurrence:
        return ""
    canonical = normalise_anchor(recurrence, anchor)
    if canonical is None:
        return recurrence
    if recurrence == "weekly":
        days = _anchor_weekdays(canonical)
        if days == [0, 1, 2, 3, 4]:
            return "every weekday"
        names = [_WEEKDAY_FULL[d] for d in days]
        if len(names) == 1:
            return f"every {names[0]}"
        return "every " + ", ".join(names[:-1]) + " and " + names[-1]
    m = _ANCHOR_DAY_RE.match(canonical)
    if m:
        return f"monthly on the {_ordinal(int(m.group(1)))}"
    ordinal, name = canonical.split("-")
    which = "last" if ordinal == "last" else _ORDINAL_WORDS[int(ordinal)]
    return f"monthly on the {which} {_WEEKDAY_FULL[_WEEKDAYS[name]]}"


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _coming_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _month_day(text: str, today: date) -> date | None:
    """``oct 15`` / ``15 oct`` / ``october 15 2028`` → a date, else ``None``.

    Without an explicit year the *coming* occurrence wins: this year while the
    day is still ahead, next year once it has passed — the same rule the bare
    weekday phrases follow, so "due oct 15" typed in November means next
    October rather than a date ten months overdue.
    """
    for pattern, month_group, day_group in (
        (_MONTH_DAY_RE, 1, 2), (_DAY_MONTH_RE, 2, 1),
    ):
        m = pattern.match(text)
        if not m:
            continue
        month = _MONTHS.get(m.group(month_group))
        if month is None:
            continue
        day = int(m.group(day_group))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            d = date(year, month, day)
        except ValueError as exc:
            raise DateParseError(f"invalid date {text!r}: {exc}") from exc
        if not m.group(3) and d < today:
            try:
                d = date(year + 1, month, day)
            except ValueError as exc:  # 29 Feb into a common year
                raise DateParseError(f"invalid date {text!r}: {exc}") from exc
        return d
    return None


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
    if s in ("this weekend", "weekend"):
        # The coming Saturday — the snooze menu's middle option (#87). Saturday
        # itself stays Saturday; Sunday means the Saturday six days out, which
        # is what "push this to the weekend" asks for on a Sunday.
        return _coming_weekday(today, 5)
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

    named = _month_day(s, today)
    if named is not None:
        return named

    raise DateParseError(
        f"cannot parse date {text!r} — try today, tomorrow, fri, next friday, "
        f"this weekend, in 2 weeks, oct 15, or YYYY-MM-DD"
    )
