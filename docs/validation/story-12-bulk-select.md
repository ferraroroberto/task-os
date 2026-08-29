# Story 12 — act on several tasks at once (issue #81)

> Monday morning, four things I queued last week are stale. I flip the Board into Select mode, tick them across whatever columns they sit in, and set them all to standby in one go. Then I tick two more and push their due dates out two weeks. If one of them has gone missing, the app tells me which — it does not quietly drop it.

Not a numbered build step — a feature issue validated story-style. The automated walk lives **inside `tests/e2e/test_story_05_board.py`** (same surface — the Board and Table over the shared list; the suite stays under 15 tests), sections "§ #81".

## Steps and expected

| # | Step | Expected | Shot |
| --- | --- | --- | --- |
| 1 | Seeded Board (1440×900) → the Select toggle in the pane's top strip | Every card grows a leading checkbox; the toggle reads pressed; drag is off (a card that both drags and ticks turns a slightly-moved tap into a status change) | [10-desktop](../screenshots/story-05-board-10-desktop.png) |
| 2 | Tick three cards sitting in three different columns | "3 selected" appears in the bulk bar, which **takes the top strip over** — the text filter and the `+` step aside, the pane gains no third row | [10-desktop](../screenshots/story-05-board-10-desktop.png) |
| 3 | Switch to the Table mid-selection | The same three rows are ticked, in the Table's own leading checkbox column, and its bulk bar reads "3 selected" — one selection store, not two | [11-desktop](../screenshots/story-05-board-11-desktop.png) |
| 4 | Bulk bar → *Set status…* → `standby` | All three move; each gets its own `activity` row (`status`, old → new), exactly as three single-task edits would; the selection clears and Select mode **stays on** for the next pick | — |
| 5 | Tick two, pick a date from the bar's calendar button | Both land on that date. The bar carries the **picker only** — one square button, so the row stays one line; the natural phrases stay on the Table's inline cell, the drawer and the CLI (the API still accepts them) | — |
| 6 | Tick two, delete one behind the app's back, then bulk-change the status | Toast: `1 updated · 1 failed (#N: task N not found)` in the error tone; the surviving task **is** updated. The batch neither aborts nor silently drops the bad id | [12-desktop](../screenshots/story-05-board-12-desktop.png) |
| 7 | Leave Select mode (the toggle, or Escape) | Checkboxes and the bulk bar go; the text filter, `+` and drag come back; a row click opens the drawer again | — |
| 8 | Phone (390×844, WebKit, touch) → Select toggle, tap a card body | The card ticks instead of opening the drawer — **no swipe gesture** (the horizontal swipe still belongs to the Board's column carousel). The bulk bar sits on **one line** inside the top strip, clear of the floating nav pill; the count, select, date and ✕ share one height and the two squares match the strip's own buttons at 44px | [10-phone](../screenshots/story-05-board-10-phone.png) |

`complete` vs `done` (#54) carries into bulk unchanged: the bar offers `complete` alongside the plain statuses, and the server decides per task — a recurring task rolls its due one cadence forward and stays open, a plain one closes.

Unit legs: `tests/test_repo.py::test_bulk_*` (every id attempted; a bad id in the middle does not stop the batch; `complete` rolls a recurring task and closes a plain one; duplicate ids collapse so a double-click cannot roll a due twice) and `tests/test_api.py::test_bulk_*` (status + due together, `""` clears the date, partial failure is a **200** naming the id, and the four malformed-request refusals — empty `ids`, nothing to change, `complete` with a `due`, an unparseable phrase).

## Real walk (this PC, 2026-08-29)

Chrome against a disposable seeded instance (never the live `:8448`), light and dark:

- Select mode on the Board, three cards ticked across inbox/todo/doing, carried intact to the Table (checkbox column, same three ticked, both bars agreeing).
- Bulk status applied to all three; bulk `in 2 weeks` applied to two — both confirmed against `/api/tasks/{id}`, not just on screen.
- **Partial failure walked, not assumed**: a ticked task was deleted through the API behind the app's back and the batch then run — `1 updated · 1 failed (#36: task 36 not found)`, with the survivor updated.
- Two defects found and fixed during the walk, both invisible to the unit tests: every tick was re-rendering all four views (which destroyed the checkbox the keyboard was on, so a keyboard user lost their place after the first tick) — a membership change now updates the affected rows in place, and only a mode change rebuilds; and Escape was swallowed while focus sat on a row checkbox, because the drawer's guard treated any `input` as a text field.
- Leaving Select mode restored the pane exactly: no checkboxes, filter text and `+` back, all 39 rows draggable again, a row click opening `#task/42`.
- **Phone geometry: not walked by hand** — this machine's Chrome window will not go below ~1072px. It is covered by the e2e phone leg above (390×844 WebKit, touch, asserting the 44px floor, no overlapping hit rects, nav-pill clearance, and the one-line/one-height bar). The owner caught two things there that the desktop walk could not: the Select toggle kept the 36px control height while the `+` went to 44px, and the bar wrapped to two lines with a due *phrase box* — both fixed, and both now pinned by assertions. A real-device check stays on the owner's checklist, as for every other story.

Result: **verified** (e2e desktop + phone legs · unit · headed desktop walk in both themes, including the partial-failure path) · real phone = owner's checklist. Date: 2026-08-29.
