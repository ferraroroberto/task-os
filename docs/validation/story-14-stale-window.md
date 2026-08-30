# Story 14 — The stale pass (#101)

**Story.** Once a week you ask the list to be honest: open the filter card, flip *Modified* to **Untouched > 30 days**, and every sediment task that nothing has touched in a month is in front of you — ready to be planned, deferred with a start date (#87), or cancelled. 60 and 90 days deepen the dig. The URL is shareable (`?updated=stale30`), the CLI answers the same question (`tasks ls --updated-before 30d`), and a task touched today never appears.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Table → open the filter card → *Modified* select | The select now carries the three inverse windows: *Untouched > 30/60/90 days* under the existing *Modified …* options |
| 2 | Pick *Untouched > 30 days* | Only tasks last touched strictly before today−30 remain (the seed's dormant task, last touched 45 days back); the collapsed summary reads `untouched > 30 days · … · 1 task`; the URL becomes `?updated=stale30` |
| 3 | Reload the URL | Same view — the token round-trips; the API only ever received the plain date the client computed (`updated_before=YYYY-MM-DD`, no relative magic server-side) |
| 4 | Pick *Untouched > 60 days* | Honest empty list — nothing is that old |
| 5 | `tasks ls --updated-before 30d --json` (and with the app down) | The same tasks, identical JSON on both backends; `Nd` resolves CLI-side, a natural/ISO date also accepted, garbage is a named `bad_date` error |

## Proof

- Screenshot: [story-04-triage-11-desktop.png](../screenshots/story-04-triage-11-desktop.png) — the stale-30 view listing exactly the dormant seeded task, summary line spelling the state.
- E2e: `_walk_stale_window` inside `tests/e2e/test_story_04_triage.py` (rides the existing filter-card story — the suite stays at 14, no new test).
- Unit: `tests/test_repo.py::test_updated_before_is_a_strict_stale_boundary` (strict boundary — touched on the boundary day or today never appears; any write is a touch; composes with other filters; bad date refused), `tests/test_api.py::test_updated_before_lists_the_dormant_task` (HTTP param + 422), `tests/test_cli.py::test_ls_updated_before_over_both_backends` (parity, `Nd`, natural date, error path).

## Result

verified — e2e walk + screenshots on the seeded instance, unit suite green, live walk on the real install (filter applied read-only, result seen on screen). Date: 2026-08-30.

**Honesty caveat (by design):** `updated_at` moves on *any* write — GitHub issue sync and mirror imports included — so a synced task never looks stale even if you personally ignore it. Stated in the README where the filter is described.
