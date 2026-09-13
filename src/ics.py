"""Just enough iCalendar (RFC 5545) to answer "what is on my calendar today" (#96).

Stdlib only, read-only, one question: given a feed's text and a local day,
which events touch that day, and at what local times. Everything else in the
format is ignored on purpose — attendees, alarms, free/busy, VTODO.

What is understood:

- line unfolding, quoted parameters, the text escapes in ``SUMMARY``;
- ``DTSTART`` / ``DTEND`` / ``DURATION`` as a date (all-day) or a date-time —
  UTC (``Z``), floating (this PC's local time) or ``TZID=``. A ``TZID`` is
  resolved from the feed's own ``VTIMEZONE`` first (Google and Outlook both
  ship one, and Outlook's ids are Windows names no tz database knows), then
  from the tz database when this Python has one, else read as floating — the
  calendar's owner and this PC are almost always in the same zone;
- ``STATUS:CANCELLED``, ``EXDATE``, ``RDATE`` and ``RECURRENCE-ID`` overrides
  (a moved meeting shows once, where it moved to);
- ``RRULE`` with ``FREQ=DAILY`` or ``FREQ=WEEKLY`` and only ``INTERVAL``,
  ``UNTIL``, ``COUNT``, plain ``BYDAY`` and ``WKST``.

Every other recurrence rule is **not expanded and not dropped**: an event whose
rule could still apply on the day is counted in ``skipped_recurring``, so the
lane can say "2 recurring events could not be checked" instead of implying a
free afternoon. An event whose start cannot be read is counted in
``unreadable`` for the same reason.

:func:`parse_calendar` raises :class:`ICSParseError` only for a document that
is not a calendar at all (an HTML login page, a truncated download) — one odd
event never blanks the whole lane.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["Agenda", "Calendar", "ICSParseError", "day_agenda", "parse_calendar"]

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
#: The rule parts :func:`_rule_matcher` expands; any other part makes a rule
#: unexpandable (counted, never guessed at).
_SUPPORTED_RULE_PARTS = frozenset({"FREQ", "INTERVAL", "UNTIL", "COUNT", "BYDAY", "WKST"})
_DATE_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")
_DATETIME_RE = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)")
_DURATION_RE = re.compile(
    r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?"
)
_OFFSET_RE = re.compile(r"([+-])(\d{2})(\d{2})(\d{2})?")
_BYDAY_RE = re.compile(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)")


class ICSParseError(ValueError):
    """The document is not a readable iCalendar feed."""


# ------------------------------------------------------------------ lexing
@dataclass
class _Prop:
    name: str
    params: dict[str, str]
    value: str


@dataclass
class _Component:
    name: str
    props: list[_Prop] = field(default_factory=list)
    children: list[_Component] = field(default_factory=list)

    def get(self, name: str) -> _Prop | None:
        return next((p for p in self.props if p.name == name), None)

    def all(self, name: str) -> list[_Prop]:
        return [p for p in self.props if p.name == name]


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def _split_outside_quotes(text: str, sep: str) -> list[str]:
    parts, buf, quoted = [], [], False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == sep and not quoted:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _parse_line(line: str) -> _Prop | None:
    """``NAME;PARAM=x:value`` → a property; ``None`` for a line with no value."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return None
    parts = _split_outside_quotes(head, ";")
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, _, val = part.partition("=")
        params[key.strip().upper()] = val.strip().strip('"')
    return _Prop(parts[0].strip().upper(), params, value)


def _parse_components(text: str) -> _Component:
    lines = _unfold(text)
    if not lines or lines[0].strip().upper() != "BEGIN:VCALENDAR":
        raise ICSParseError("it does not start with BEGIN:VCALENDAR")
    root: _Component | None = None
    stack: list[_Component] = []
    for line in lines:
        prop = _parse_line(line)
        if prop is None:
            continue
        if prop.name == "BEGIN":
            comp = _Component(prop.value.strip().upper())
            if stack:
                stack[-1].children.append(comp)
            elif root is not None:
                raise ICSParseError("content after END:VCALENDAR")
            else:
                root = comp
            stack.append(comp)
        elif prop.name == "END":
            name = prop.value.strip().upper()
            if not stack or stack[-1].name != name:
                open_name = stack[-1].name if stack else "nothing"
                raise ICSParseError(f"END:{name} does not close BEGIN:{open_name}")
            stack.pop()
        elif stack:
            stack[-1].props.append(prop)
    if stack or root is None:
        raise ICSParseError("the feed stops before END:VCALENDAR (a truncated download?)")
    return root


def _unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


# --------------------------------------------------------------- time zones
def _parse_offset(value: str) -> timedelta | None:
    m = _OFFSET_RE.fullmatch(value.strip())
    if not m:
        return None
    delta = timedelta(hours=int(m[2]), minutes=int(m[3]), seconds=int(m[4] or 0))
    return -delta if m[1] == "-" else delta


def _nth_weekday(year: int, month: int, nth: int, weekday: int) -> date | None:
    """The ``nth`` (1…5, or -1…-5 from the end) ``weekday`` of a month."""
    if nth > 0:
        first = date(year, month, 1)
        d = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    else:
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        last = nxt - timedelta(days=1)
        d = last - timedelta(days=(last.weekday() - weekday) % 7 + 7 * (-nth - 1))
    return d if d.month == month else None


@dataclass
class _Observance:
    """One STANDARD / DAYLIGHT block: from ``start`` (and each yearly repeat)
    the wall clock runs at ``offset``."""

    start: datetime
    offset: timedelta
    month: int | None = None
    nth: int | None = None
    weekday: int | None = None
    until: datetime | None = None
    rdates: list[datetime] = field(default_factory=list)

    def last_onset(self, wall: datetime) -> datetime | None:
        onsets = [self.start] if self.start <= wall else []
        onsets += [r for r in self.rdates if r <= wall]
        if self.month is not None and self.nth is not None and self.weekday is not None:
            for year in (wall.year, wall.year - 1):
                d = _nth_weekday(year, self.month, self.nth, self.weekday)
                if d is None:
                    continue
                onset = datetime.combine(d, self.start.time())
                if self.start <= onset <= wall and (self.until is None or onset <= self.until):
                    onsets.append(onset)
        return max(onsets) if onsets else None


class _FeedZone(tzinfo):
    """A ``VTIMEZONE`` from the feed itself, as a ``tzinfo`` (yearly
    nth-weekday rules — every real zone Google and Outlook emit)."""

    def __init__(self, tzid: str, observances: list[_Observance]) -> None:
        self.tzid = tzid
        self.observances = observances

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return self.observances[0].offset
        wall = dt.replace(tzinfo=None)
        best: tuple[datetime, timedelta] | None = None
        for obs in self.observances:
            onset = obs.last_onset(wall)
            if onset is not None and (best is None or onset > best[0]):
                best = (onset, obs.offset)
        return best[1] if best else min(self.observances, key=lambda o: o.start).offset

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return self.tzid

    def fromutc(self, dt: datetime) -> datetime:
        naive = dt.replace(tzinfo=None)
        wall = naive + self.utcoffset(naive)
        wall = naive + self.utcoffset(wall)
        return wall.replace(tzinfo=self)


def _observance(comp: _Component) -> _Observance | None:
    start_prop, to_prop = comp.get("DTSTART"), comp.get("TZOFFSETTO")
    if start_prop is None or to_prop is None:
        return None
    m = _DATETIME_RE.fullmatch(start_prop.value.strip())
    offset = _parse_offset(to_prop.value)
    if not m or offset is None:
        return None
    obs = _Observance(datetime(*(int(m[i]) for i in range(1, 7))), offset)
    for rd in comp.all("RDATE"):
        for v in rd.value.split(","):
            rm = _DATETIME_RE.fullmatch(v.strip())
            if rm:
                obs.rdates.append(datetime(*(int(rm[i]) for i in range(1, 7))))
    rule_prop = comp.get("RRULE")
    if rule_prop is None:
        return obs
    rule = _parse_rule(rule_prop.value)
    byday = _BYDAY_RE.fullmatch(rule.get("BYDAY", ""))
    if rule.get("FREQ") != "YEARLY" or not rule.get("BYMONTH", "").isdigit() or not byday:
        return obs if obs.rdates else None
    obs.month, obs.weekday = int(rule["BYMONTH"]), WEEKDAYS[byday[2]]
    obs.nth = int(byday[1]) if byday[1] else 1
    if "UNTIL" in rule:
        um = _DATETIME_RE.fullmatch(rule["UNTIL"])
        if um:
            obs.until = datetime(*(int(um[i]) for i in range(1, 7)))
    return obs


def _feed_zones(root: _Component) -> dict[str, tzinfo]:
    zones: dict[str, tzinfo] = {}
    for comp in root.children:
        tzid = comp.get("TZID")
        if comp.name != "VTIMEZONE" or tzid is None:
            continue
        observances = [o for c in comp.children if c.name in ("STANDARD", "DAYLIGHT") if (o := _observance(c))]
        if observances:
            zones[tzid.value.strip()] = _FeedZone(tzid.value.strip(), observances)
    return zones


# ------------------------------------------------------------------- values
Moment = date | datetime


def _parse_rule(value: str) -> dict[str, str]:
    rule: dict[str, str] = {}
    for part in value.strip().split(";"):
        key, _, val = part.partition("=")
        if key.strip():
            rule[key.strip().upper()] = val.strip().upper()
    return rule


class _Values:
    """Reads date / date-time values against the feed's zones."""

    def __init__(self, zones: dict[str, tzinfo]) -> None:
        self.zones = zones
        self._resolved: dict[str, tzinfo | None] = {}

    def zone(self, tzid: str) -> tzinfo | None:
        if tzid not in self._resolved:
            found = self.zones.get(tzid)
            if found is None:
                try:
                    found = ZoneInfo(tzid)
                except (ZoneInfoNotFoundError, ValueError, OSError):
                    found = None   # no tz database / an unknown id → floating
            self._resolved[tzid] = found
        return self._resolved[tzid]

    def moment(self, raw: str, params: dict[str, str]) -> Moment:
        v = raw.strip()
        if params.get("VALUE", "").upper() == "DATE" or _DATE_RE.fullmatch(v):
            m = _DATE_RE.fullmatch(v)
            if not m:
                raise ICSParseError(f"unreadable date {v!r}")
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = _DATETIME_RE.fullmatch(v)
        if not m:
            raise ICSParseError(f"unreadable date-time {v!r}")
        naive = datetime(*(int(m[i]) for i in range(1, 7)))
        if m[7]:
            return naive.replace(tzinfo=UTC)
        tz = self.zone(params["TZID"]) if params.get("TZID") else None
        return naive.replace(tzinfo=tz) if tz else naive

    def moments(self, props: list[_Prop]) -> list[Moment]:
        out: list[Moment] = []
        for p in props:
            if p.params.get("VALUE", "").upper() == "PERIOD":
                continue
            out += [self.moment(v, p.params) for v in p.value.split(",") if v.strip()]
        return out


def _parse_duration(value: str) -> timedelta | None:
    m = _DURATION_RE.fullmatch(value.strip())
    if not m or not any(m.groups()[1:]):
        return None
    w, d, h, mi, s = (int(g or 0) for g in m.groups()[1:])
    delta = timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -delta if m[1] == "-" else delta


# ------------------------------------------------------------------- model
@dataclass
class Event:
    uid: str
    summary: str
    start: Moment
    end: Moment | None = None
    duration: timedelta | None = None
    rule: dict[str, str] | None = None
    exdates: list[Moment] = field(default_factory=list)
    rdates: list[Moment] = field(default_factory=list)
    recurrence_id: Moment | None = None
    cancelled: bool = False

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)


@dataclass
class Calendar:
    events: list[Event]
    #: VEVENTs whose start could not be read — reported, never silently lost.
    unreadable: int = 0


def parse_calendar(text: str) -> Calendar:
    """The feed's events; :class:`ICSParseError` if it is not a calendar."""
    root = _parse_components(text)
    if root.name != "VCALENDAR":
        raise ICSParseError(f"the outer component is {root.name}, not VCALENDAR")
    values = _Values(_feed_zones(root))
    events: list[Event] = []
    unreadable = 0
    for comp in root.children:
        if comp.name != "VEVENT":
            continue
        try:
            events.append(_event(comp, values))
        except ICSParseError:
            unreadable += 1
    return Calendar(events, unreadable)


def _event(comp: _Component, values: _Values) -> Event:
    start_prop = comp.get("DTSTART")
    if start_prop is None:
        raise ICSParseError("VEVENT without DTSTART")
    uid, summary = comp.get("UID"), comp.get("SUMMARY")
    ev = Event(
        uid=uid.value.strip() if uid else "",
        summary=_unescape(summary.value).strip() if summary else "",
        start=values.moment(start_prop.value, start_prop.params),
    )
    end_prop, dur_prop = comp.get("DTEND"), comp.get("DURATION")
    if end_prop is not None:
        ev.end = values.moment(end_prop.value, end_prop.params)
    elif dur_prop is not None:
        ev.duration = _parse_duration(dur_prop.value)
    rule_prop = comp.get("RRULE")
    if rule_prop is not None:
        ev.rule = _parse_rule(rule_prop.value)
    ev.exdates = values.moments(comp.all("EXDATE"))
    ev.rdates = values.moments(comp.all("RDATE"))
    rid = comp.get("RECURRENCE-ID")
    if rid is not None:
        ev.recurrence_id = values.moment(rid.value, rid.params)
    status = comp.get("STATUS")
    ev.cancelled = bool(status and status.value.strip().upper() == "CANCELLED")
    return ev


# ------------------------------------------------------------------ the day
@dataclass
class Agenda:
    day: date
    all_day: list[dict[str, object]]
    timed: list[dict[str, object]]
    skipped_recurring: int = 0
    unreadable: int = 0


class _Local:
    """Conversion to the reader's wall clock: ``tz`` (tests) or this PC's zone."""

    def __init__(self, tz: tzinfo | None) -> None:
        self.tz = tz

    def __call__(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:   # floating: already the local wall clock
            return moment.replace(tzinfo=self.tz) if self.tz else moment.astimezone()
        return moment.astimezone(self.tz) if self.tz else moment.astimezone()

    def midnight(self, day: date) -> datetime:
        return self(datetime.combine(day, time.min))


def day_agenda(cal: Calendar, day: date, tz: tzinfo | None = None) -> Agenda:
    """What touches ``day`` on the local wall clock (``tz``; default this PC's).

    ``timed`` rows are ``{summary, start, end, starts_before, ends_after}``
    with ``HH:MM`` local times, ordered by start; ``all_day`` rows are
    ``{summary}``. A multi-day event appears on each day it covers.
    """
    local = _Local(tz)
    day_start, day_end = local.midnight(day), local.midnight(day + timedelta(days=1))
    overrides = _overrides(cal.events)
    all_day: list[tuple[str, dict[str, object]]] = []
    timed: list[tuple[datetime, str, dict[str, object]]] = []
    skipped = 0
    for ev in cal.events:
        # A cancelled override still hides its master's occurrence (it is in
        # `overrides`); it just never shows itself. A live override is an
        # ordinary single event at its own DTSTART.
        if ev.cancelled:
            continue
        if ev.rule is not None or ev.rdates:
            occurs = _occurrence_test(ev, local, overrides.get(ev.uid, []))
            if occurs is None:
                if _rule_may_apply(ev, day, local):
                    skipped += 1
                continue
        else:
            occurs = None
        summary = ev.summary or "(no title)"
        if ev.all_day:
            span = _all_day_span(ev)
            starts = [day - timedelta(days=k) for k in range(span)]
            hit = any((occurs(d) if occurs else d == ev.start) for d in starts)
            if hit:
                all_day.append((summary, {"summary": summary}))
            continue
        start = ev.start
        assert isinstance(start, datetime)
        length = _timed_length(ev, local)
        if occurs is None:
            candidates = [local(start)]
        else:
            first = day - timedelta(days=length.days + 1)
            candidates = [
                local(datetime.combine(first + timedelta(days=k), start.time(), tzinfo=start.tzinfo))
                for k in range(length.days + 3)
                if occurs(first + timedelta(days=k))
            ]
        for s in candidates:
            e = s + length
            if s < day_end and (e > day_start or (e == s and s >= day_start)):
                timed.append((s, summary, {
                    "summary": summary,
                    "start": s.strftime("%H:%M"),
                    "end": e.strftime("%H:%M"),
                    "starts_before": s < day_start,
                    "ends_after": e > day_end,
                }))
    return Agenda(
        day=day,
        all_day=[row for _, row in sorted(all_day, key=lambda r: r[0].casefold())],
        timed=[row for _, _, row in sorted(timed, key=lambda r: (r[0], r[1].casefold()))],
        skipped_recurring=skipped,
        unreadable=cal.unreadable,
    )


def _all_day_span(ev: Event) -> int:
    if isinstance(ev.end, date) and not isinstance(ev.end, datetime):
        return max(1, (ev.end - ev.start).days)   # type: ignore[operator]
    if ev.duration is not None:
        return max(1, ev.duration.days)
    return 1


def _timed_length(ev: Event, local: _Local) -> timedelta:
    start = ev.start
    assert isinstance(start, datetime)
    if isinstance(ev.end, datetime):
        return max(timedelta(0), local(ev.end) - local(start))
    if ev.duration is not None:
        return max(timedelta(0), ev.duration)
    return timedelta(0)


def _wall_date(moment: Moment, master: Event, local: _Local) -> date:
    """``moment`` as a date on the master's own wall clock (EXDATE / RECURRENCE-ID)."""
    if not isinstance(moment, datetime):
        return moment
    start = master.start
    if moment.tzinfo is not None and isinstance(start, datetime) and start.tzinfo is not None:
        return moment.astimezone(start.tzinfo).date()
    if moment.tzinfo is not None:   # master floating or all-day: read it locally
        return local(moment).date()
    return moment.date()


def _overrides(events: list[Event]) -> dict[str, list[Moment]]:
    """``uid → [RECURRENCE-ID, …]`` — occurrences a separate VEVENT replaces."""
    out: dict[str, list[Moment]] = {}
    for ev in events:
        if ev.recurrence_id is not None and ev.uid:
            out.setdefault(ev.uid, []).append(ev.recurrence_id)
    return out


def _start_date(ev: Event) -> date:
    return ev.start.date() if isinstance(ev.start, datetime) else ev.start


def _rule_may_apply(ev: Event, day: date, local: _Local) -> bool:
    """Could an unexpandable rule put something on ``day``? Only those count."""
    if _start_date(ev) > day:
        return False
    until = (ev.rule or {}).get("UNTIL")
    if not until:
        return True
    try:
        moment = _Values({}).moment(until, {})
    except ICSParseError:
        return True
    return _wall_date(moment, ev, local) >= day - timedelta(days=1)


def _occurrence_test(ev: Event, local: _Local, replaced: list[Moment]) -> Callable[[date], bool] | None:
    """``date → does an occurrence start on that wall date``; ``None`` = the rule
    is outside what this module expands."""
    excluded = {_wall_date(m, ev, local) for m in [*ev.exdates, *replaced]}
    extra = {_wall_date(m, ev, local) for m in ev.rdates}
    start = _start_date(ev)
    pattern = _rule_matcher(ev, local) if ev.rule is not None else (lambda d: d == start)
    if pattern is None:
        return None
    return lambda d: d not in excluded and (d in extra or pattern(d))


def _rule_matcher(ev: Event, local: _Local) -> Callable[[date], bool] | None:
    rule = ev.rule or {}
    if set(rule) - _SUPPORTED_RULE_PARTS or rule.get("FREQ") not in ("DAILY", "WEEKLY"):
        return None
    try:
        interval = int(rule.get("INTERVAL", "1"))
        count = int(rule["COUNT"]) if "COUNT" in rule else None
        until = _Values({}).moment(rule["UNTIL"], {}) if "UNTIL" in rule else None
    except (ValueError, ICSParseError):
        return None
    if interval < 1:
        return None
    byday: set[int] | None = None
    if "BYDAY" in rule:
        tokens = [t for t in rule["BYDAY"].split(",") if t]
        if not tokens or any(t not in WEEKDAYS for t in tokens):
            return None   # an ordinal ("1MO") belongs to monthly rules
        byday = {WEEKDAYS[t] for t in tokens}
    wkst = WEEKDAYS.get(rule.get("WKST", "MO"), 0)
    start = _start_date(ev)
    freq = rule["FREQ"]
    if freq == "WEEKLY" and byday is None:
        byday = {start.weekday()}

    def week_of(d: date) -> date:
        return d - timedelta(days=(d.weekday() - wkst) % 7)

    def in_pattern(d: date) -> bool:
        if d < start:
            return False
        if d == start:
            return True   # DTSTART is always the first instance
        if freq == "DAILY":
            return (d - start).days % interval == 0 and (byday is None or d.weekday() in byday)
        weeks = (week_of(d) - week_of(start)).days // 7
        return weeks % interval == 0 and d.weekday() in (byday or set())

    def before_until(d: date) -> bool:
        if until is None:
            return True
        if not isinstance(until, datetime):
            return d <= until
        begin = ev.start.time() if isinstance(ev.start, datetime) else time.min
        tz = ev.start.tzinfo if isinstance(ev.start, datetime) else None
        return local(datetime.combine(d, begin, tzinfo=tz)) <= local(until)

    def within_count(d: date) -> bool:
        if count is None:
            return True
        if freq == "DAILY" and byday is None:
            return (d - start).days // interval < count
        seen, cursor = 0, start
        while cursor <= d:
            if in_pattern(cursor):
                seen += 1
                if seen > count:
                    return False
            cursor += timedelta(days=1)
        return True

    return lambda d: in_pattern(d) and before_until(d) and within_count(d)
