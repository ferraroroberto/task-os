# Story 30 — Today as a split view (#336)

**Story.** On a desktop window, Today is two columns. The task list takes the left half and the right half is the detail pane, so a row's ⋯ menu sits beside the title instead of at the far edge of the window. With nothing open, the right half says *Select a task to see its details*, and the list keeps its half width. Opening a task (a tap on the row, Enter, or ⋯ → **Open details**) fills that same right half with the task drawer's content: the same drawer, no second detail view, no overlay. `#task/<id>` opens it from a cold load, and closing returns to the empty state.

The split applies on the Today tab from 1024px up, the drawer's own desktop breakpoint. The phone and narrow windows are unchanged (the drawer stays a full-screen sheet). Board, Table and Archive keep the 440px panel that opens beside their list. With a calendar configured, its lane no longer fits beside the rows in half a window, so on Today it moves above them.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open Today at 1440px with nothing open | The list is the left half and an empty-state pane the right half, which says *Select a task to see its details*. Every row's ⋯ sits inside the list half and nothing overflows sideways |
| 2 | ⋯ on a row | The menu opens whole, inside the window |
| 3 | Choose **Open details** | The empty state is replaced by the task's drawer in the same box (same x and width), beside the list, and the URL is `#task/<id>` |
| 4 | Close the drawer | The empty state is back |
| 5 | Load `#task/<id>` cold | Today is the active tab with the drawer filling the right half |
| 6 | Switch to the Table with a task open, close it, return to Today | The Table's panel is the 440px side panel, no empty pane shows there, and Today shows the empty state again |

## Proof

- Screenshots: [story-30-today-split-1-desktop.png](../screenshots/story-30-today-split-1-desktop.png) (nothing open) · [story-30-today-split-2-desktop.png](../screenshots/story-30-today-split-2-desktop.png) (a task open) · [story-30-today-split-3-desktop.png](../screenshots/story-30-today-split-3-desktop.png) (the cold deep link).
- E2e: `_walk_today_split` inside `tests/e2e/test_story_04_triage.py` (geometry assertions, seen red against the pre-change assets first). The view-width pin in `tests/e2e/test_story_01_open.py` now measures Today as list plus pane, and the plan-mode step of `tests/e2e/test_story_28_calendar.py` asserts the lane above the candidates. They ride existing tests, so the suite gains no test function.
- Every other desktop Today shot in the gallery was re-baselined because the empty pane or the wider drawer is now on screen. Each was compared old against new.

## Not covered

- The arrow keys do not move a selection through Today's rows. The established walk there is Tab, as before. The detail still follows only on open.
- The open task's row is not highlighted in the list.

## Result

verified in the browser (e2e, desktop Chromium, light and dark shots seen). Date: 2026-10-04.
