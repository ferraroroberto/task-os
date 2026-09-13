# Story 25 — Repeat every N (#229)

**Story.** Clothes get treated against moths every 7 weeks, on a Saturday. Until now every cadence was exactly one unit — no way to say "every 7 weeks", "every 3 days" or "every 2 months on the 15th". **Repeat** in the drawer is now three controls read as one sentence: the cadence, **Every** *N* *weeks* (empty or 1 = every one), and — for weekly and monthly — **On** the fixed day. Any cadence takes an interval, anchored or not.

**The phase rule** (the issue's open design question). An anchored interval needs to know *which* Saturdays count. The due date being completed decides it: its week (Monday-first) or month qualifies, and so does every Nth one after it; the roll lands on the anchored day in the first qualifying week or month after both that due and today. A rolled due therefore always sits in a qualifying period itself, so the rhythm survives any number of completions — early, on the day, weeks late — and editing the due by hand deliberately re-sets it. With N = 1 every period qualifies, which is exactly the #112 roll: existing tasks are unaffected by construction. Unanchored intervals keep `next_due`'s other invariant — every candidate is `base + k × N × cadence`, measured from the due, never accumulated.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open the seed's **Weekly review** (due Saturday), type `7` into **Every**, press Enter, pick **On** `Saturday` | Each change is one PATCH (`recurrence_interval: 7`, then `recurrence_anchor: sat`); the fields row reads *Repeat weekly · Every 7 weeks · On Saturday*; the row behind the drawer carries the label *every 7 weeks on Saturday* |
| 2 | Complete it from the status select | The task stays open and its due moves **exactly 7 weeks**, onto a Saturday — never the coming Saturday |
| 3 | The same drawer at 390×844 (WebKit, touch) | *Every* is a ≥ 44 px target with a digit keypad (`inputmode=numeric`), beside its unit; Repeat · Every · On do not overlap and nothing scrolls sideways |
| 4 | `tasks add "Treat clothes against moths" --due 2026-09-19 --recurrence weekly --recurrence-anchor sat --recurrence-interval 7`, then `tasks done 1` twice | `(due 2026-09-19, every 7 weeks on Saturday)` → `next due 2026-11-07` → `next due 2026-12-26` |
| 5 | A bad interval — `0`, `1000`, `seven`, or any interval with no cadence — over the API, CLI or mirror | 422 / exit 1 / a `rejected` mirror event; never a silently every-cadence task |
| 6 | An existing database (v15) with recurring tasks, anchored and not, restarted on this build | v16 adds `tasks.recurrence_interval` with a plain `ADD COLUMN` (the `recurrence` CHECK and the table untouched, children intact), every row reads NULL, and each task rolls to the same due `origin/main` rolled it to |

## Proof

- Screenshots — both saved by the test: [story-25-recurrence-interval-1-desktop.png](../screenshots/story-25-recurrence-interval-1-desktop.png) (the three-control composer, *Every 7 weeks · On Saturday*) · [story-25-recurrence-interval-2-phone.png](../screenshots/story-25-recurrence-interval-2-phone.png) (the same composer on the phone sheet).
- E2e: `_walk_recurrence_interval` inside `tests/e2e/test_story_04_triage.py` (after the story-17 anchor walk, restored over the API afterwards) plus the story-25 block of that file's phone leg — no new test function, so the suite's collected count is unchanged.
- Unit: `tests/test_dates.py` — the interval grammar and its rejections, every cadence unanchored, weekday and weekday-list intervals, monthly day-N / ordinal / last intervals across a year end and a clamp, overdue catch-up onto the phase, the due-week phase rule, **forty consecutive 7-week-Saturday completions (early · on time · late · very late) that never leave the original grid**, a 24-roll monthly `day-31` drift check, and N = 1/NULL equal to no interval across every cadence ± anchor; `tests/test_recurrence_label_parity.py` — `recurrence.js::recurrenceLabel` against `describe_recurrence` for every cadence × anchor × interval (400+ cases, under node), and every `anchorOptions` value canonical; `tests/test_repo.py` (the story roll twice, canonical storage, rejections, carry across a cadence change); `tests/test_api.py::test_recurrence_interval_round_trips_and_rejects_a_bad_value`; `tests/test_cli.py::test_add_every_seven_weeks_on_saturday_and_roll_it` (both backends); `tests/test_mirror.py::test_import_recurrence_interval_round_trips`; `tests/test_schema.py::test_v16_adds_the_interval_without_touching_existing_recurring_tasks` (expected rolls read off `origin/main`'s `dates.py`).
- CLI walk (`--local`, a throwaway temp database): step 4's transcript verbatim, plus `interval 0 out of range (1–999)` and `an interval needs a recurrence (got None)`, both exit 1.

## Result

verified — unit + e2e (desktop and WebKit phone) + CLI walk, gate green (`scripts/verify-before-ship.ps1`). **Not verified:** a headed walk on the live install (the worker does not restart the tray) and the **real iPhone** — the owner's check after `tray.bat --restart`: open a recurring task, type a number into *Every*, confirm the digit keypad and that the sheet does not zoom or scroll sideways. Date: 2026-09-13.

**Deliberate limits:** no end date or occurrence count; quick-add does not parse "every 7 weeks" from free text; `recurrence.js` is still a hand-kept mirror of `src/dates.py`, held in step by the parity test rather than generated.
