# Story 31 — every open task within Today's reach (#350)

**Story.** The Table went (#350), and with it the one view that listed every open task at once. Today takes that over: it lists every open task in four horizons, nearest first — **Today** (due ≤ today, overdue first; My plan stays above it), **Soon** (tomorrow … +7 days, the old *Later this week*), **Later** (further out) and **No date**. The filter card and the top strip's text filter work across all four, so a task due a year from now, or one with no date at all, is found from Today by scrolling or by typing a word of it.

Soon always shows, with its way forward when it is empty; Later and No date only show when they hold something. All three sit open below Today as flat disclosures, each collapsible by its chevron. Deferred and blocked tasks stay out, as on every working view: their filter pills show them.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Add *Renew the residence card* due a year out and *Sort the attic boxes* with no date, open Today | Below Today: *Soon*, *Later*, *No date*, in that order, open. The year-out task is in Later, its date on the meta line; the dateless one is in No date. Each is reached by scrolling |
| 2 | Type `residence card` in the top strip's filter | One row left in the horizons, the year-out task under Later (My plan stays whole whatever the filters, #89) |
| 3 | Type `attic` | One row left, under No date; the URL carries `?q=attic` |

## Proof

- Screenshots: [story-31-today-horizons-1-desktop.png](../screenshots/story-31-today-horizons-1-desktop.png) (scrolled to Later and No date) · [story-31-today-horizons-2-desktop.png](../screenshots/story-31-today-horizons-2-desktop.png) (filtered to the dateless task)
- Test: inside `tests/e2e/test_story_05_board.py` (`_walk_today_horizons`), the suite being over its 15-test target (CLAUDE.md). Red first: against the pre-change `today.js` the story fails at its first horizon assertion; that build had no bucket for a task without a date or due past a week, so neither task could appear.

Result: **verified** (e2e desktop, 2026-10-05) · phone walk not separately verified.

**2026-10-05 (#339):** under a text filter an empty Today or Soon section says no task matches it and names the box: *No task due today matches “attic” — change the filter text above*, never *Nothing due today — all clear* (the day may be full; the filter hides it). Without a filter the sentences and their *Add a task* actions are unchanged. Step 2 checks both sections under `attic`, seen red first on the old wording; [shot 2](../screenshots/story-31-today-horizons-2-desktop.png) re-baselined.
