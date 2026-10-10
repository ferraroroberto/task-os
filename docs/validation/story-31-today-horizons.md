# Story 31 — every open task within Today's reach (#350)

**Story.** The Table went (#350), and with it the one view that listed every open task at once. Today takes that over: it lists every open task in four horizons, nearest first — **Today** (due ≤ today, overdue first), **Soon** (tomorrow … +7 days, the old *Later this week*), **Later** (further out) and **No date**. The filter card and the top strip's text filter work across all four, so a task due a year from now, or one with no date at all, is found from Today by scrolling or by typing a word of it.

Soon always shows, with its way forward when it is empty; Later and No date only show when they hold something. All three sit open below Today as flat disclosures, each collapsible by its chevron. Deferred and blocked tasks stay out, as on every working view: their filter pills show them.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Add *Renew the residence card* due a year out and *Sort the attic boxes* with no date, open Today | Below Today: *Soon*, *Later*, *No date*, in that order, open. The year-out task is in Later, its date on the meta line; the dateless one is in No date. Each is reached by scrolling |
| 2 | Type `residence card` in the top strip's filter | One row left in the horizons, the year-out task under Later |
| 3 | Type `attic` | One row left, under No date; the URL carries `?q=attic` |

## Proof

- Screenshots: [story-31-today-horizons-1-desktop.png](../screenshots/story-31-today-horizons-1-desktop.png) (scrolled to Later and No date) · [story-31-today-horizons-2-desktop.png](../screenshots/story-31-today-horizons-2-desktop.png) (filtered to the dateless task)
- Test: inside `tests/e2e/test_story_05_board.py` (`_walk_today_horizons`), the suite being over its 15-test target (CLAUDE.md). Red first: against the pre-change `today.js` the story fails at its first horizon assertion; that build had no bucket for a task without a date or due past a week, so neither task could appear.

Result: **verified** (e2e desktop, 2026-10-05) · phone walk not separately verified.

**2026-10-10 (#391):** the redesign's shared parts land on Today. Each horizon header is the `overline` role with its count beside it (*SOON 6*), a project sub-header is drawn only where a horizon holds two or more groups, and Today opens on **Mine** under a *Mine · Issues · All* switch (the vendored segmented control). New step 4 (`_walk_scope_switch`): Mine is pressed and writes no URL key, the seed's one synced coding task is absent; *Issues* shows exactly the tasks carrying an issue ref and writes `?scope=issues`; a reload keeps it; under Issues, Soon holds one group, so no sub-header and the row names its project; *All* shows them again and *Mine* drops the key. [Shot 3](../screenshots/story-31-today-horizons-3-desktop.png) (Issues, after the reload); shots 1–2 re-baselined. Unit: `tests/test_scope.py` (the URL key and the issue rule under node). Result: **verified** (e2e desktop); phone rendering seen in [story 07 shots 1 and 5](../screenshots/story-07-phone-1-phone.png) (light, dark), **owner's real-phone check not yet done**.

**2026-10-10 (#393, decision 6 of #390):** Today opens on what is due. The due rows carry no heading of their own: the page header names them (*3 overdue · 5 due today* in the attention tone, *Nothing due today* muted when there are none), read off the counts the horizons were drawn from, so the two never disagree; the header's old repeated open count is gone on every tab, and the open count is the top strip's placeholder (*Filter 39 tasks…*), no longer on the filter card's summary line. Later and No date start **folded** with their counts; new step 1: both folded, each count equals its rows, a click opens each, and a re-render (the scope switch to All and back) keeps them open; the text filter steps then find each task under its opened horizon, and a filter opens a folded horizon by itself. [Shot 4](../screenshots/story-31-today-horizons-4-desktop.png) (folded, counts showing); shots 1–3 re-baselined. Story 05 step 6 asserts the header line and its tone, no heading over the due rows and the placeholder count; story 04 asserts the Board's count on the placeholder. Unit: `tests/test_today.py` (the header line from the drawn counts, under node; fails against the pre-change `today.js`). Result: **verified** (e2e desktop and phone shots, light and dark seen in the design measure); **owner's real-phone check not yet done**.

**2026-10-05 (#339):** under a text filter an empty Today or Soon section says no task matches it and names the box: *No task due today matches “attic” — change the filter text above*, never *Nothing due today — all clear* (the day may be full; the filter hides it). Without a filter the sentences and their *Add a task* actions are unchanged. Step 2 checks both sections under `attic`, seen red first on the old wording; [shot 2](../screenshots/story-31-today-horizons-2-desktop.png) re-baselined.
