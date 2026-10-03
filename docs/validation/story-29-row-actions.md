# Story 29 — Act on a row from its menu (#311)

**Story.** Every action a task row offers sits behind its trailing ⋯ kebab. A tap (or right-click, or `.` on a focused row, or the menu key) opens a list of the actions that apply to that task: complete or reopen, change the date, snooze, the statuses it is not already in, priority. Then come the task's own links: plan it for today, open its folder, its AI conversation, its issue, its details. A menu action commits through the same runner as the keys, so it gets the same toast with **Undo (Z)**. The menu is the vendored data-driven row-menu (project-scaffolding#317): it escapes the Board's sideways carousel, follows the menu-button keyboard pattern and gives focus back to the kebab.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | On Today, tap the ⋯ of an open `todo` task | The menu opens under the kebab, first item focused, kebab `aria-expanded="true"`. Items: Complete task · Change date… · Snooze… · Status: inbox · Status: standby · Status: cancelled · Cycle priority · Plan for today · Open details. *Status: todo* and *Reopen* are absent, because they do not apply |
| 2 | Choose **Snooze…**, then **Tomorrow** | The menu closes, the date picker opens beside the row, the task leaves Today, and a toast reads `Snoozed to …` with **Undo (Z)** |
| 3 | Press Undo | `starts` is cleared again and the row is back |
| 4 | Focus the row, press `.`, then `Escape` | The menu opens from the keyboard, and Escape closes it with focus on the row's kebab |

## Proof

- Screenshots: [story-29-row-actions-1-desktop.png](../screenshots/story-29-row-actions-1-desktop.png) (the open menu on a Today row).
- E2e: step 4b of `_walk_starts_and_snooze` inside `tests/e2e/test_story_04_triage.py`. It rides an existing story, so the suite gains no test function.
- Unit: `tests/test_row_actions.py`, the shared table's plans, inverses and messages under node.

## Result

verified in the browser (e2e, desktop light). **Real phone not verified**: the gesture and touch checks for the whole #311 redesign are on the owner's checklist once the swipe step lands. Date: 2026-10-04.
