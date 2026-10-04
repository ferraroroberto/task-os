# Story 29 — Act on a row from its menu (#311)

**The row (#311 step 3).** A task row is the fleet's vendored action-row: a leading completion circle, the title over one quiet meta line (due · blocked or asleep · project · status where the view does not imply it · priority · glyphs for recurrence, children, comments, folder, AI conversation and issue · person), and one trailing ⋯ kebab, 60px tall where it used to be about 88. The status select, Today's snooze clock, the due picker and the folder, AI and issue chips left the row. Every one of them is in the menu, and the drawer still has them all. The circle completes an open task (a recurring one rolls) and reopens a closed one. It goes through the same runner as the menu, so both get a toast with Undo.

**Story.** Every action a task row offers sits behind its trailing ⋯ kebab. A tap (or right-click, or `.` on a focused row, or the menu key) opens a list of the actions that apply to that task: complete or reopen, change the date, snooze, the statuses it is not already in, priority. Then come the task's own links: plan it for today, open its folder, its AI conversation, its issue, its details. A menu action commits through the same runner as the keys, so it gets the same toast with **Undo (Z)**. The menu is the vendored data-driven row-menu (project-scaffolding#317): it escapes the Board's sideways carousel, follows the menu-button keyboard pattern and gives focus back to the kebab.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | On Today, tap the ⋯ of an open `todo` task | The menu opens under the kebab, first item focused, kebab `aria-expanded="true"`. Items: Complete task · Change date… · Snooze… · Status: inbox · Status: standby · Status: cancelled · Cycle priority · Plan for today · Open details. *Status: todo* and *Reopen* are absent, because they do not apply |
| 2 | Choose **Snooze…**, then **Tomorrow** | The menu closes, the date picker opens beside the row, the task leaves Today, and a toast reads `Snoozed to …` with **Undo (Z)** |
| 3 | Press Undo | `starts` is cleared again and the row is back |
| 4 | Focus the row, press `.`, then `Escape` | The menu opens from the keyboard, and Escape closes it with focus on the row's kebab |
| 5 | On Today, tap the circle of a recurring task, then of a plain overdue one (story 05) | The recurring task rolls one cadence forward (toast `Completed — next: …` with **Undo (Z)**). The plain one closes and lands in the Board's Done-today column |
| 6 | On the phone, tap ⋯ → **Change date…** on a row (story 07) | The vendored modal (top-anchored) offers Today · Tomorrow · This weekend · Next week · Pick a date… · No date, and a pick re-dates the row |
| 7 | Measure a phone row (stories 04, 05, 07) | The circle and the kebab are 44×44, the circle, the open target and the kebab share no pixel, the row is ≤ 61px with its hairline, and nothing on the meta line is a button or a link |
| 8 | On the phone, swipe a Table row left, then right (story 07, synthetic touch pointers) | Left: the row springs back and the date sheet opens, nothing written. A swipe that starts in the 20px edge zone does nothing. Right: the row slides out, the task is done, the toast offers **Undo (Z)**, and Undo brings the row back |
| 9 | Settings → **Row actions** (story 04): swipe left → *Snooze…*, untick *Cycle priority*, move *Snooze…* to the top | The card says **Custom**. *Snooze…* is ticked and locked ("used by swipe left") and so is *Complete task* ("used by swipe right"). The row's ⋯ menu now starts with Snooze… and has no priority item, and a swipe left opens the snooze picker. **Reset to the defaults** clears the stored choice and the card says **Default** again |

## Proof

- Screenshots: [story-29-row-actions-1-desktop.png](../screenshots/story-29-row-actions-1-desktop.png) (the open menu on a Today row) · [story-29-row-actions-2-desktop.png](../screenshots/story-29-row-actions-2-desktop.png) (Settings → Row actions, customised).
- E2e: step 4b of `_walk_starts_and_snooze` inside `tests/e2e/test_story_04_triage.py`, the circle in `tests/e2e/test_story_05_board.py`, and the phone row in `tests/e2e/test_story_07_phone.py` (`_walk_row_tap_targets`). They ride existing stories, so the suite gains no test function.
- Unit: `tests/test_row_actions.py`, the shared table's plans, inverses and messages under node. `tests/test_swipe.py`, the swipe classifier: edge zone, slop and direction lock, the 96px / 35 % threshold, flick. `tests/test_row_prefs.py`, the Row actions choice: defaults, normalising whatever storage returns, and a swipe's action always kept in the menu.

## Owner's iPhone checklist (not verified)

Walk these in the **installed standalone PWA** on the iPhone. Record each item as walked, or as **not verified**.

- **Gestures**
  - Swipe right from the middle of a Today row: it slides out, and the toast offers Undo for 10 s.
  - Swipe right starting near the left edge: does iOS edge-back fire instead, and is 20 px of edge zone enough?
  - Swipe left: the row springs back and the date sheet (top-anchored modal) opens. Cancel writes nothing.
  - Flick-scroll a long Today list vertically: no row should swipe by accident.
  - A slow diagonal drag should scroll, not swipe.
  - A long-press on a row: no callout and no text selection.
- **Feedback and access**
  - Undo works inside 10 s, and the toast sits clear of the nav pill.
  - With Reduce Motion on in iOS Settings, the row still follows the finger, but the spring-back and slide-out are instant.
  - VoiceOver reaches Complete through the circle and Change date through ⋯, without swiping.
- **Layout**
  - Rows run edge to edge on Today, the Table and the Tree.
  - On the Board, rows do not swipe and the columns still do.
  - The ⋯ menu inside the Board carousel is not clipped.
  - Check all of the above in light and dark.

## Result

verified in the browser (e2e, desktop light). **Real phone not verified**: the gesture and touch checks for the whole #311 redesign are on the owner's checklist once the swipe step lands. Date: 2026-10-04.
