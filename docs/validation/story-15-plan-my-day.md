# Story 15 — Plan my day (#89)

**Story.** Each morning Today offers the ritual: the plan is empty, a banner counts the candidates — *Plan your day — 3 overdue · 5 due today · 4 new in Inbox* — and plan mode gives every candidate two large targets: **Today** commits it, **Later** is the #87 snooze popover. **My plan** then sits on top of Today in your order with an *n of m done* progress line; rows drag to reorder and carry a quiet remove control. A task planned yesterday and left unfinished reappears as a candidate wearing *planned yesterday — not finished* — re-committing is a conscious act, never a silent carry-over. The CLI runs the same ritual as `tasks plan` (y/n/s per candidate) and `tasks plan ls`.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open Today (seeded) | **My plan** on top: the two seeded planned tasks in order, counts line `0 of 2 done`, drag grips and × per row |
| 2 | Remove both via × | Toast `Removed from today's plan` with Undo per removal; `planned_on` cleared and activity-logged; the plan empties and the **banner** appears with the exact candidate counts |
| 3 | *Plan my day* → plan mode | The candidate list with **Today** / **Later** targets per row; the task planned yesterday wears `planned yesterday — not finished`; the counts line names the candidates |
| 4 | Tap **Today** on two (the carry-over included), **Later → Next week** on one, then *Done planning* | Committed tasks move up into My plan as they are tapped; the snoozed one leaves the candidates (deferred, #87 — same popover, same toast); the picker closes |
| 5 | Drag a plan row to the top | Order flips in place; `POST /api/plan/reorder` rewrote `plan_order` — `/api/today` returns the new order |
| 6 | Complete a planned row via its status select | Progress line moves to `1 of 2 done`; the done item stays on the list, struck through; the due groups below never showed the planned tasks (they live in the plan) |
| 7 | `tasks plan` (piped y/s/n) · `tasks plan ls --json` | The interactive pass plans/snoozes/skips over either backend (dialogue on stderr, stdout clean); `plan ls` prints the ordered plan with the progress line; `--json` is the API shape on both backends |

## Proof

- Screenshots: [story-15-plan-my-day-1-desktop.png](../screenshots/story-15-plan-my-day-1-desktop.png) (My plan, ordered, progress line) · [2](../screenshots/story-15-plan-my-day-2-desktop.png) (the banner with candidate counts) · [3](../screenshots/story-15-plan-my-day-3-desktop.png) (plan mode: targets + the *planned yesterday* note) · [4](../screenshots/story-15-plan-my-day-4-desktop.png) (reordered by drag) · [5](../screenshots/story-15-plan-my-day-5-desktop.png) (`1 of 2 done`, done row struck) · [6](../screenshots/story-15-plan-my-day-6-desktop.png) (dark) · [7-phone](../screenshots/story-15-plan-my-day-7-phone.png) (Today as the phone landing tab, touch-sized controls).
- E2e: `_walk_plan_my_day` inside `tests/e2e/test_story_04_triage.py` plus the phone assertions in its phone leg (rides the existing Today/triage story — the suite stays at 14, no new test).
- Unit: `tests/test_repo.py::test_plan_my_day_rules` (order append, activity, snooze-un-plans, planning-wakes, reorder permutation-or-refuse, plan group + due exclusion), `tests/test_repo.py::test_plan_candidates_and_the_seeded_plan`, `tests/test_api.py::test_plan_my_day_over_http` (phrases, candidates, reorder 422), `tests/test_mirror.py::test_planned_on_round_trips_plan_order_stays_home`, `tests/test_cli.py::test_plan_over_both_backends`.

## Result

verified — e2e walk + screenshots on the seeded instance (light, dark, phone), unit suite green, live walk on the real install (Today opened, plan mode entered and left; `tasks plan ls` read the same plan). Date: 2026-08-31.

**Deliberate limits:** reorder is desktop drag only (HTML5 DnD does not fire on touch — the phone plans in tap order); the plan is not filter-scoped (it is your commitment list — the filter card shapes the due groups, never My plan); the Board is untouched.
