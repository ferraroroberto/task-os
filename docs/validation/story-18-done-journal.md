# Story 18 — What got done (#102)

**Story.** Friday afternoon: "what actually happened this week?" The Board's Done column head carries a quiet **journal** link (the palette has *Journal* too); it opens the done journal over the current pane — no tab lights, `#journal` in the URL. Days newest first, each a flat heading with its count (`Yesterday · Tue 1 Sep · 2 done`), the same rows as everywhere (project, issue chip, breadcrumb on hover, the status select that reopens a task in place); cancelled tasks sit muted under their day, one switch drops them. The shared filter card narrows by project, person or text and rides the URL — the status, due, modified and sort controls are not there, because they say nothing about a closed task. The page is this week; **Show the week before** widens it, and the journal only says "that is everything" once the server confirmed nothing closed earlier. A row opens the drawer under `#journal/task/<id>`; pressing any tab leaves. `tasks journal` prints the same grouping in the terminal.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Board → click **journal** in the Done column head | The journal pane replaces the Board; no tab in the pill is lit; the URL ends in `#journal` |
| 2 | Read the days | Newest first — today (what the story closed), *Yesterday* (the seed's two: kettle · lease renewal, `2 done`), two days back (`1 done · 1 cancelled`, the cancelled row muted); the rows on screen are exactly the API's `status=done,cancelled&done_from=…&done_to=…` window |
| 3 | Complete the coding task through the API, reload on `#journal` | The deep link lands on the journal; the task sits under today with its issue chip and project |
| 4 | Flip the **cancelled** switch off, then on | The muted row leaves and the day's count reads `1 done`; back on it returns |
| 5 | Open the filter card, pick a project | Only project and person controls (plus the text strip) — no status / due / modified / sort; every row wears that project; `?project=N…#journal` in the URL; *Clear* puts it back |
| 6 | **Show the week before**, repeatedly | Nine days back appears (the borrowed drill), then the seed's first closing day; only then the foot says *That is everything — nothing closed before …* |
| 7 | Click a row, then Escape | The drawer opens with `#journal/task/<id>`; closing it leaves `#journal` and the journal on screen |
| 8 | Press **Board**; `Ctrl+K` → `>journal` → Enter | The tab press leaves (hash cleared, Board lit); the palette entry brings it back |
| 9 | Phone: open `/#journal` | The journal under the floating pill, no tab lit, the switch a 44 px target, no horizontal overflow; tapping *Today* leaves |
| 10 | Terminal: `tasks journal [--weeks N] [--json]` | The same day groups, newest first, `[x]` done / `[-]` cancelled, over either backend; `--json` = `{from, to, count, days:[{day, count, items}]}` |

## Proof

- Screenshots: [story-18-done-journal-1-desktop.png](../screenshots/story-18-done-journal-1-desktop.png) (this week, light) · [2](../screenshots/story-18-done-journal-2-desktop.png) (widened to the seed's first closing day, filter card open, dark) · [3](../screenshots/story-18-done-journal-3-phone.png) (phone, `#journal` deep link).
- E2e: `_walk_done_journal` inside `tests/e2e/test_story_05_board.py` (§ #102 — rides the Board story, so the suite stays at 14 tests) plus step 12 of its phone leg.
- Unit: `tests/test_repo.py::test_done_window_is_local_midnight_and_newest_first` (the window's local-midnight boundary — the `done_on` rule — the newest-first order, cancelling stamps `done_at`, reopening clears it) · `tests/test_api.py::test_done_window_over_http_orders_newest_first` (the page and the older-probe over HTTP, a bad date is a 422) · `tests/test_schema.py::test_v10_stamps_closed_at_on_cancelled_tasks` (the backfill: activity time when logged, `updated_at` otherwise, done and open rows untouched) · `tests/test_cli.py::test_journal_over_both_backends`.

## Result

verified — e2e walk + screenshots on the seeded instance (desktop light + dark, phone), unit suite green, headed walk on the real install (read-only: opened, widened, filtered, left). Date: 2026-09-02.

**Deliberate limits:** no seventh tab — the pill is the vendored nav contract and the journal is read, not lived in (palette, the Done column link and the hash are its three doors); no streaks, charts or per-day totals beyond the count; editing from the journal is what the row already allows (the status select, the due chip, the drawer); the cancelled switch is local state, not a URL parameter; cancelled tasks closed before schema v10 carry their `status → cancelled` activity time, or `updated_at` when an importer created them cancelled — the best the history can say, never a guess at a day.
