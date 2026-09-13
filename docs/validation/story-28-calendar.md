# Story 28 — Plan the day against the real calendar

**Issue:** #96. Numbered 28 as the index's next free slot (see `docs/validation.md`).

**Tests:** `tests/e2e/test_story_28_calendar.py::test_today_calendar_lane` (two seeded disposable instances: the usual blank-config one, and one whose `calendar.ics_url` is `tests/fixtures/calendar_fake.FakeCalendar` — a loopback server in the pytest process serving the synthetic `tests/fixtures/calendar/day.ics`, never a real calendar) · `tests/test_calendar.py` (31): the reader over the fixture files — the story day, the day after (a meeting across midnight, a daily rule with that day's `EXDATE`), a Windows-named `TZID` resolved from the feed's own `VTIMEZONE` on both sides of the DST change, a UTC event landing on the local day it falls on, folding and text escapes, `COUNT` / `UNTIL` / `INTERVAL` / `BYDAY` rules, `RDATE`, only a still-applicable unexpandable rule counted, one unreadable event counted while the rest show, an HTML page and a truncated feed as parse errors · the service — blank config never fetches, **the failures are distinct states** (`off` · `bad_url` for a 404 and a non-http scheme · `timeout` · `parse_error` · `unreachable`), none of them an empty list with `stale: false`, a good fetch, **a slow server never holds a request past the timeout** (nothing cached: answers `timeout` within the bound; a copy cached: answers at once with `stale` + `refreshing`), a failure after a good fetch keeps the copy with `failing_since`, a failure retried after a minute and not on every request, **the address never reaching a status, an error or the log** (every mode, the secret path asserted absent), status as the group without its rows · the API — `/api/today` carries the group, `/api/status` and `POST /api/calendar/refresh` agree, `/api/today` answers within the bound while the calendar hangs, both routes behind the gate · `tests/test_views.py::test_routes_shape` · `tests/test_cli.py` status keys on both backends.

The e2e budget: adding this file would have taken the suite to 17 collected tests, so story 04's phone leg was folded into its desktop test (`test_desktop_triage` now runs both walks — same steps, same order, same shots), as story 05's was for story 27. The count stays at 16.

**Steps → expected (the acceptance story)**

1. With no `calendar.ics_url`, Today on the desktop shows the **Calendar** lane beside the task list saying *No calendar connected* with how to connect one; Settings → *Calendar* reads *off — not configured*, *Refresh now* disabled; `/api/status` → `calendar.configured: false` with the reason.
2. The owner puts a private ICS address in `config/config.json` → `calendar.ics_url` and restarts. If the address is refused (a 404 — mistyped or revoked), the lane is a red callout *Calendar address refused since 09:00* with the server's answer, and no event list — never an empty lane.
3. An answer that is not a calendar (a sign-in page): *Calendar feed unreadable*; Settings reads *not a calendar* after *Refresh now*.
4. A server that hangs: *Refresh now* answers within the 2 s bound with *Calendar did not answer in time*; Today itself answers at once meanwhile.
5. A dropped connection: *Calendar unreachable since 09:00*.
6. The real feed: *Refresh now* → Settings reads *reading · 6 event(s) today · 1 recurring not checked*, source `127.0.0.1` (the host, never the address). Today shows *School holiday* and *Team offsite* on the all-day strip; *09:30–09:45 Standup*, *14:00–14:30 1:1 with Sam Rivera (moved)* (the moved occurrence once, where it moved to), *16:30–17:15 Dentist, check-up*, *23:00–06:00 Night train · ends tomorrow*; no *Gym* (excluded that day) and no cancelled lunch; *1 recurring event could not be checked* for the monthly rule it does not expand.
7. *Plan more* opens plan mode: the candidates list and the lane stay side by side.
8. The address starts failing again after a good fetch: the lane keeps the events, with *Calendar address refused since 09:00* and *Showing the copy from 09:00.* above them; the head reads *stale*.
9. At phone width the lane is not drawn (out of scope this pass).

**Screenshots** (synthetic seed and synthetic feed only)

| # | Shot | What it shows |
| --- | --- | --- |
| 1 | [story-28-calendar-1-desktop](../screenshots/story-28-calendar-1-desktop.png) | Today with the lane off — *No calendar connected* and the config key that connects one |
| 2 | [story-28-calendar-2-desktop](../screenshots/story-28-calendar-2-desktop.png) | the address refused before any copy exists: the red callout with *HTTP 404* and *since 09:00*, no list |
| 3 | [story-28-calendar-3-desktop](../screenshots/story-28-calendar-3-desktop.png) | Settings → *Calendar* after *Refresh now*: *reading · 6 event(s) today · 1 recurring not checked*, source host, last fetched |
| 4 | [story-28-calendar-4-desktop](../screenshots/story-28-calendar-4-desktop.png) | today's events beside My plan and the due groups: the all-day strip, four timed events, the skipped-rule note |
| 5 | [story-28-calendar-5-desktop](../screenshots/story-28-calendar-5-desktop.png) | plan mode — the candidates with *Today* / *Later* and the lane alongside |
| 6 | [story-28-calendar-6-desktop](../screenshots/story-28-calendar-6-desktop.png) | dark: a failure after a good fetch — the kept copy under *Calendar address refused since 09:00 · Showing the copy from 09:00.* |

**Result**

| Leg | Result |
| --- | --- |
| Unit — `tests/test_calendar.py` (31) + the shape assertions in `test_views.py` / `test_cli.py` | verified 2026-09-13 — 31 passed; full unit suite 739 passed in the gate run |
| E2e — `test_story_28_calendar.py`, steps 1–9 against two loopback disposable instances and the fake feed | verified 2026-09-13 — passed in the full gate run (16 e2e) and again on its own; its six shots byte-identical across runs (`shot_determinism --check-tree` after a story-28-only run: 0 drifted). The full gate's gallery stage is **red**: 20 existing shots moved because desktop Today now carries the lane and Settings a Calendar card — a re-baseline those shots still owe (see the PR) |
| Headed walk on this PC — a disposable instance (synthetic seed) reading the fake feed, flipped through three of its modes in a visible browser | verified 2026-09-13 — headed Chrome against a disposable seeded instance on a loopback port: 404 → *Calendar address refused since 09:00* with the server's answer and no list · feed good, Settings opened after the one-minute retry → *on*, 6 events (a first *Refresh now* click landed on the collapsed card and did nothing) · card opened, feed switched to a sign-in page, *Refresh now* → Settings *not a calendar · stale*, Today re-rendered by the refresh to *Calendar feed unreadable since 09:00 · Showing the copy from 09:00.* over the kept all-day strip, four events and the skipped-rule note. Read from the page text; the extension's screenshot capture timed out on that window, so no image was inspected for this leg (the e2e shots above were) |
| **Today against the owner's own calendar** (a real Google or Outlook private ICS address, a real week with recurring meetings, moved and cancelled ones) | **not verified** — the owner's walk; nothing in this repo may read a real calendar |
