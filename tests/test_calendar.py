"""#96 — the read-only calendar lane: the ICS reader, the fetch states, the API.

Every feed is synthetic (``tests/fixtures/calendar/``) and every address is a
loopback :class:`~tests.fixtures.calendar_fake.FakeCalendar` — no test reads a
real calendar. The day under test is the e2e anchor, Monday 2026-09-07.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, date, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import calendar_lane, clock, ics
from src import db as dbmod
from src.calendar_lane import CalendarFetchError, CalendarService
from src.config import AppConfig, CalendarConfig
from tests.conftest import write_test_config
from tests.fixtures.calendar_fake import FIXTURES, SECRET, FakeCalendar, closed_port_url

DAY = date(2026, 9, 7)
PLUS_TWO = timezone(timedelta(hours=2))
LOOPBACK = ("127.0.0.1", 50000)


def agenda(name: str, day: date = DAY, tz: timezone = PLUS_TWO) -> ics.Agenda:
    return ics.day_agenda(ics.parse_calendar((FIXTURES / name).read_text(encoding="utf-8")), day, tz)


def times(a: ics.Agenda) -> list[tuple[str, str, str]]:
    return [(str(e["start"]), str(e["end"]), str(e["summary"])) for e in a.timed]


def feed(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def vevent(*lines: str) -> str:
    return "BEGIN:VEVENT\r\n" + "".join(line + "\r\n" for line in lines) + "END:VEVENT\r\n"


# ------------------------------------------------------------------ reader
def test_the_story_day_reads_as_a_person_would_read_it() -> None:
    """All-day events as a strip; timed ones in order with local times; a moved
    occurrence once, where it moved to; cancelled, excluded and other days'
    events absent; a meeting across midnight shown with its real end."""
    a = agenda("day.ics")
    assert [e["summary"] for e in a.all_day] == ["School holiday", "Team offsite"]
    assert times(a) == [
        ("09:30", "09:45", "Standup"),
        ("14:00", "14:30", "1:1 with Sam Rivera (moved)"),
        ("16:30", "17:15", "Dentist, check-up"),
        ("23:00", "06:00", "Night train"),
    ]
    assert a.timed[-1]["ends_after"] is True and a.timed[0]["starts_before"] is False
    # the monthly rule is not expanded — and not dropped either
    assert a.skipped_recurring == 1
    assert a.unreadable == 0


def test_the_next_day_carries_what_crossed_midnight_and_the_rule_that_skips_monday() -> None:
    a = agenda("day.ics", DAY + timedelta(days=1))
    assert times(a) == [("23:00", "06:00", "Night train"), ("07:00", "08:00", "Gym")]
    assert a.timed[0]["starts_before"] is True
    assert [e["summary"] for e in a.all_day] == ["School holiday"]


def test_a_feed_timezone_is_honoured_even_under_a_windows_name() -> None:
    """Outlook's ``TZID`` is a Windows name no tz database knows: the feed's own
    VTIMEZONE decides, including which side of the DST change a date is on."""
    utc = UTC
    assert times(agenda("zoned.ics", DAY, utc)) == [
        ("07:00", "07:30", "Weekly sync"),         # CEST: 09:00 − 2 h
        ("08:00", "09:00", "Planning (summer time)"),
        ("22:00", "22:30", "Late call"),
    ]
    winter = agenda("zoned.ics", date(2026, 1, 12), utc)
    assert ("08:00", "08:30", "Weekly sync") in times(winter)   # CET: 09:00 − 1 h
    assert ("09:00", "10:00", "Planning (winter time)") in times(winter)


def test_a_utc_event_lands_on_the_local_day_it_falls_on() -> None:
    assert "Late call" not in [e["summary"] for e in agenda("zoned.ics", DAY, PLUS_TWO).timed]
    assert ("00:00", "00:30", "Late call") in times(agenda("zoned.ics", DAY + timedelta(days=1), PLUS_TWO))


def test_folding_and_text_escapes() -> None:
    text = feed(vevent("UID:a", "SUMMARY:Review\\, plan\\; and", " notes", "DTSTART:20260907T080000", "DURATION:PT90M"))
    a = ics.day_agenda(ics.parse_calendar(text), DAY, PLUS_TWO)
    assert times(a) == [("08:00", "09:30", "Review, plan; andnotes")]


@pytest.mark.parametrize(
    ("rule", "on_day"),
    [
        ("FREQ=DAILY;COUNT=3", True),                         # 5th, 6th, 7th
        ("FREQ=DAILY;COUNT=2", False),
        ("FREQ=DAILY;UNTIL=20260906", False),
        ("FREQ=DAILY;UNTIL=20260907T235959Z", True),
        ("FREQ=DAILY;INTERVAL=2", True),                      # 5th, 7th
        ("FREQ=DAILY;BYDAY=SA,SU", False),
        ("FREQ=WEEKLY;BYDAY=MO;COUNT=1", False),              # DTSTART is a Saturday instance, then Monday 7th = 2nd
        ("FREQ=WEEKLY;BYDAY=MO;COUNT=2", True),
        ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO", False),           # week of 31 Aug active, 7 Sep not
        ("FREQ=WEEKLY;INTERVAL=3;BYDAY=MO", False),
    ],
)
def test_simple_rules_expand(rule: str, on_day: bool) -> None:
    # DTSTART Saturday 2026-09-05
    text = feed(vevent("UID:r", "SUMMARY:R", "DTSTART:20260905T080000", "DTEND:20260905T083000", f"RRULE:{rule}"))
    a = ics.day_agenda(ics.parse_calendar(text), DAY, PLUS_TWO)
    assert bool(a.timed) is on_day
    assert a.skipped_recurring == 0


def test_rdate_adds_an_occurrence() -> None:
    text = feed(vevent("UID:r", "SUMMARY:Extra", "DTSTART:20260801T080000", "DTEND:20260801T090000",
                       "RDATE:20260907T080000,20260910T080000"))
    assert times(ics.day_agenda(ics.parse_calendar(text), DAY, PLUS_TWO)) == [("08:00", "09:00", "Extra")]


def test_only_a_rule_that_could_still_apply_is_counted_as_skipped() -> None:
    text = feed(
        vevent("UID:old", "SUMMARY:Ended", "DTSTART:20200101T080000", "RRULE:FREQ=MONTHLY;UNTIL=20210101T000000Z"),
        vevent("UID:future", "SUMMARY:Later", "DTSTART:20270101T080000", "RRULE:FREQ=YEARLY"),
        vevent("UID:live", "SUMMARY:Live", "DTSTART:20260101T080000", "RRULE:FREQ=MONTHLY;BYDAY=1MO"),
    )
    assert ics.day_agenda(ics.parse_calendar(text), DAY, PLUS_TWO).skipped_recurring == 1


def test_one_unreadable_event_is_counted_and_the_rest_still_show() -> None:
    text = feed(vevent("UID:bad", "SUMMARY:Bad", "DTSTART:tomorrow-ish"),
                vevent("UID:ok", "SUMMARY:Fine", "DTSTART:20260907T100000"))
    a = ics.day_agenda(ics.parse_calendar(text), DAY, PLUS_TWO)
    assert a.unreadable == 1 and [e["summary"] for e in a.timed] == ["Fine"]


@pytest.mark.parametrize("name", ["not_a_calendar.html", "truncated.ics"])
def test_a_document_that_is_not_a_whole_calendar_is_a_parse_error(name: str) -> None:
    with pytest.raises(ics.ICSParseError):
        ics.parse_calendar((FIXTURES / name).read_text(encoding="utf-8"))


# ----------------------------------------------------------------- service
def service(url: str = "", *, timeout: float = 1.0, **kw) -> CalendarService:
    return CalendarService(AppConfig(calendar=CalendarConfig(ics_url=url, timeout_seconds=timeout)), **kw)


@pytest.fixture(autouse=True)
def _pinned_day() -> Iterator[None]:
    from datetime import datetime

    with clock.use_clock(lambda: datetime(2026, 9, 7, 9, 0).astimezone()):
        yield


@pytest.fixture
def fake() -> Iterator[FakeCalendar]:
    with FakeCalendar() as f:
        yield f


def test_blank_address_is_off_with_a_reason_and_never_fetches() -> None:
    calls: list[str] = []
    g = service(fetcher=lambda u, t: calls.append(u) or "").today()
    assert (g["configured"], g["state"], g["events"]) == (False, "off", [])
    assert g["reason"] and not calls


def test_the_four_failures_are_four_different_states(fake: FakeCalendar) -> None:
    """Blank config, bad URL, timeout and parse failure — none of them an empty
    lane that reads as a free day (plus a dead server, a fifth)."""
    got = {"blank": service().today()}
    fake.mode = "404"
    got["bad_url"] = service(fake.url).today()
    got["bad_scheme"] = service("ftp://calendar.example.com/x.ics").today()
    fake.mode = "slow"
    got["timeout"] = service(fake.url, timeout=0.3).today()
    fake.mode = "html"
    got["parse"] = service(fake.url).today()
    fake.mode = "drop"   # a closed port on Windows can take ~2 s to refuse; a dropped connection is instant
    got["dead"] = service(fake.url).today()
    assert {k: g["state"] for k, g in got.items()} == {
        "blank": "off", "bad_url": "bad_url", "bad_scheme": "bad_url",
        "timeout": "timeout", "parse": "parse_error", "dead": "unreachable",
    }
    for key, g in got.items():
        assert g["events"] == [] and g["all_day"] == []
        assert g["reason"] or g["error"], key
        assert g["stale"] is False
    assert "404" in got["bad_url"]["error"]


def test_a_good_feed_answers_the_day(fake: FakeCalendar) -> None:
    g = service(fake.url).today()
    assert g["state"] == "ok" and g["error"] is None
    assert g["source"] == "127.0.0.1" and g["date"] == "2026-09-07"
    assert [e["summary"] for e in g["events"]][:1] == ["Standup"]
    assert g["skipped_recurring"] == 1 and g["fetched_at"] and not g["stale"]


def test_a_slow_server_never_holds_a_request_past_the_timeout(fake: FakeCalendar) -> None:
    """(d) With nothing cached the request waits for the fetch, and no longer
    than the bound; with a copy in hand an expired one is served at once."""
    fake.mode, fake.delay_s = "slow", 5.0
    svc = service(fake.url, timeout=0.5)
    started = time.perf_counter()
    g = svc.today()
    assert time.perf_counter() - started < 0.5 + calendar_lane.WAIT_GRACE_S + 0.4
    assert g["state"] == "timeout"

    now = [1000.0]
    svc = service(fake.url, timeout=0.5, monotonic=lambda: now[0])
    fake.mode = "ok"
    assert svc.today()["state"] == "ok"
    now[0] += svc.refresh_minutes * 60      # the copy expires…
    fake.mode = "slow"                      # …and the server has started hanging
    started = time.perf_counter()
    g = svc.today()
    assert time.perf_counter() - started < 0.2
    assert g["state"] == "ok" and g["stale"] is True and g["refreshing"] is True
    assert [e["summary"] for e in g["events"]][:1] == ["Standup"]


def test_a_failure_after_a_good_fetch_keeps_the_copy_and_says_since_when(fake: FakeCalendar) -> None:
    svc = service(fake.url)
    assert svc.today()["state"] == "ok"
    fake.mode = "drop"
    g = svc.refresh()
    assert g["state"] == "unreachable" and g["stale"] is True
    assert g["failing_since"] and g["events"], "the good copy stays on screen"


def test_a_failure_is_retried_after_a_minute_not_on_every_request() -> None:
    calls: list[float] = []
    now = [0.0]

    def failing(url: str, timeout: float) -> str:
        calls.append(now[0])
        raise CalendarFetchError("unreachable", "no route")

    svc = service("https://calendar.example.com/x.ics", fetcher=failing, monotonic=lambda: now[0])
    assert svc.today()["state"] == "unreachable"
    now[0] += 30
    assert svc.today()["state"] == "unreachable"
    assert len(calls) == 1
    now[0] += calendar_lane.RETRY_AFTER_FAILURE_S
    svc.today()
    assert len(calls) == 2
    svc.refresh()                            # Settings' Refresh now does not wait
    assert len(calls) == 3


def test_the_address_never_reaches_a_status_an_error_or_the_log(
    fake: FakeCalendar, caplog: pytest.LogCaptureFixture
) -> None:
    # INFO is the level `src.logger` runs the app at. (urllib3's own DEBUG line
    # quotes the request path — any library at DEBUG would; the app never logs
    # there.)
    caplog.set_level(logging.INFO)
    seen = []
    for mode in ("404", "500", "html", "ok", "drop"):
        fake.mode = mode
        svc = service(fake.url)
        seen += [svc.today(), svc.refresh(), svc.status()]
    seen.append(service(closed_port_url()).status())
    blob = json.dumps(seen) + caplog.text
    assert SECRET not in blob and "/calendar/ical/" not in blob
    assert "127.0.0.1" in blob       # the host is what is shown instead


def test_status_is_the_group_without_its_rows(fake: FakeCalendar) -> None:
    st = service(fake.url).status()
    assert "events" not in st and "all_day" not in st
    assert st["events_today"] == 6 and st["state"] == "ok"
    assert st["refresh_minutes"] == 10 and st["timeout_seconds"] == 1.0
    assert service().status()["events_today"] is None


# --------------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeCalendar) -> Iterator[TestClient]:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(
        write_test_config(tmp_path / "config.json", calendar={"ics_url": fake.url, "timeout_seconds": 0.5})))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=LOOPBACK) as c:
        yield c


def test_today_carries_the_calendar_group_and_status_and_refresh_agree(
    client: TestClient, fake: FakeCalendar
) -> None:
    body = client.get("/api/today").json()
    assert body["calendar"]["state"] == "ok" and body["calendar"]["events"]
    assert "plan" in body and "due" in body
    assert client.get("/api/status").json()["calendar"]["events_today"] == 6
    fake.mode = "404"
    refreshed = client.post("/api/calendar/refresh").json()
    assert refreshed["state"] == "bad_url" and refreshed["stale"] is True


def test_today_answers_within_the_bound_while_the_calendar_hangs(
    client: TestClient, fake: FakeCalendar
) -> None:
    fake.mode, fake.delay_s = "slow", 5.0
    started = time.perf_counter()
    res = client.get("/api/today")
    assert res.status_code == 200
    assert time.perf_counter() - started < 0.5 + calendar_lane.WAIT_GRACE_S + 0.6
    assert res.json()["calendar"]["state"] == "timeout"


def test_the_calendar_routes_are_behind_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 1)) as outside:
        assert outside.get("/api/today").status_code == 401
        assert outside.post("/api/calendar/refresh").status_code == 401
