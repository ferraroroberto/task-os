# Story 17 — Repeat on a fixed day (#112)

**Story.** A weekly review belongs on Friday, not "seven days after whenever I last ticked it". **Repeat** in the drawer is now two controls: the cadence, and — for weekly and monthly — the day it lands on. Weekly takes a weekday or the Mon–Fri set; monthly takes a day of the month or an ordinal weekday (*the first Sunday*, *the last Friday*). Completing the task rolls its due to the first occurrence after **both** the due being completed and today, so a Friday review ticked on a Tuesday goes to Friday, and a task weeks overdue catches up into the future instead of landing on another past date — which the plain cadences now do too. An anchor never retroactively moves the due already on the task; the next roll settles onto it.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open the seed's **Weekly review** (`weekly`, anchored `fri`) | The fields row shows **Repeat** `weekly` beside **On** `Friday` — one composer, same control shape as its neighbours, on desktop and on the phone |
| 2 | Complete it from the status select on a **Tuesday**, with the due on Sunday 6 Sep | The task stays open and its due becomes **Friday 11 Sep** — the next anchored day after both the old due and today, not `due + 7` |
| 3 | Complete a **plain** weekly a month overdue | The new due is ahead of today and keeps the original due's weekday — no second overdue date (`test_next_due_plain_cadence_catches_up`) |
| 4 | Switch **Repeat** to `monthly` | The **On** picker re-populates with the monthly vocabulary (Day of month · Weekday groups); picking *the first Sunday* stores `1-sun` |
| 5 | Switch **Repeat** to `quarterly` | The **On** picker disappears and the stored anchor is cleared, with its own `recurrence_anchor` activity row — a cadence change is an edit, not an error |
| 6 | `tasks add … --recurrence weekly --recurrence-anchor fri`, then `tasks done N` | `#N done — recurring every Friday, next due 2026-09-11`; `tasks show` and `tasks ls` print the same label |
| 7 | Send a bad pair over the API (`daily` + `fri`, or `monthly` + `5-sun`) | 422 with the JSON error envelope — a typo is a rejection, never a silently unanchored task |

## Proof

- Screenshots: [story-17-recurrence-anchor-1-desktop.png](../screenshots/story-17-recurrence-anchor-1-desktop.png) (the composer: Repeat `weekly` · On `Friday`) · [2](../screenshots/story-17-recurrence-anchor-2-desktop.png) (the picker following a switch to `monthly` → *the first Sunday*) · [3](../screenshots/story-17-recurrence-anchor-3-phone.png) (the same two controls on the phone).
- E2e: `_walk_recurrence_anchor` inside `tests/e2e/test_story_04_triage.py` (§ #112 — rides the existing triage story, so the suite stays at 14 tests): asserts both selects, completes the task and checks the rolled due is a **Friday** strictly after both the old due and today, then switches to `quarterly` and asserts the picker is gone.
- Unit: `tests/test_dates.py` — the anchor grammar (canonical spelling, the twelve rejections), each anchor kind, month-end clamping, the leap year (`day-31` → 29 Feb 2028), and the three roll cases (overdue · on time · early); `tests/test_repo.py::test_done_rolls_to_the_anchored_weekday` (the story), `test_done_rolls_an_overdue_plain_recurrence_into_the_future`, `test_changing_the_cadence_drops_an_anchor_it_cannot_carry`; `tests/test_api.py::test_recurrence_anchor_round_trips_and_rejects_a_bad_pair`; `tests/test_schema.py::test_v9_adds_the_recurrence_anchor_to_an_existing_database` (a v8 file's recurring tasks survive, unanchored).
- Headed walk (real Chrome, disposable instance over the synthetic seed, light and dark, 1440×900 and 390×844): the composer present on all four; on desktop, switching to `monthly` + *the first Sunday* held, and completing the Friday-anchored review on Tue 1 Sep moved its due **2026-09-06 → 2026-09-11** with Repeat still `weekly` / `fri`.
- CLI walk (`--local`, same seeded DB, Tue 1 Sep): `#37 done — recurring every Friday, next due 2026-09-11` · `#18 done — recurring monthly on the 15th, next due 2026-09-15` · `#30 done — recurring weekly, next due 2026-09-08` (the plain cadence, unchanged where it was already ahead of today).

## Result

verified — e2e + unit suite green (`scripts/verify-before-ship.ps1`), headed desktop and phone walk in both themes, CLI walk on both anchored kinds; the live install restarted and serving the branch build (`/api/version` → schema 9). **Real phone not verified** — the owner's own check on the restarted install. Date: 2026-09-01.

**Deliberate limits:** no anchors on `quarterly` / `yearly`, no "every N weeks", no end date or occurrence count, no time of day. Quick-add and the CLI do not *parse* "every friday" from free text — the anchor is picked, or passed as `--recurrence-anchor`. Monthly ordinals stop at the fourth (a "fifth Tuesday" is missing from most months, and skipping months is not a cadence); `last-<weekday>` covers the end of the month instead.
