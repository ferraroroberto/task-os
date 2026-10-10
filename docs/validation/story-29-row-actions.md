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
| 8 | On the phone, swipe a Today row left, then right (story 07, synthetic touch pointers) | Left: the row springs back and the date sheet opens, nothing written. A swipe that starts in the 20px edge zone does nothing. Right: the row slides out, the task is done, the toast offers **Undo (Z)**, and Undo brings the row back |
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
  - Rows run edge to edge on Today and the Board.
  - On the Board, rows do not swipe and the columns still do.
  - The ⋯ menu inside the Board carousel is not clipped.
  - Check all of the above in light and dark.

## Result

verified in the browser (e2e, desktop light). **Real phone not verified**: the gesture and touch checks for the whole #311 redesign are on the owner's checklist once the swipe step lands. Date: 2026-10-04.

**2026-10-05 (#350):** the Table tab (grid and Tree) was removed. The phone swipe walk (story 07) runs on a Today row.

**2026-10-05 (#350):** a touch screen draws no completion circle any more: a task closes by swiping it right, or by opening it and setting its status in the drawer (the non-gesture way, so WCAG 2.5.1 holds), and a closed one reopens from the drawer. A mouse, a trackpad and the keyboard keep the circle and `e`. The phone legs of stories 04, 05 and 07 assert the circle is hidden and that the open target and the ⋮ are the row's 44px targets; red first against the build that still drew it.

## 2026-10-10 — the row on a budget, with Move as its verb (#392, redesign step 2/7)

**Story.** Re-dating is most of what the owner does to a task, so it is the row's one visible verb. On a mouse or trackpad every open row outside the Board's columns carries **Move** (a calendar glyph on a 44px icon button between the title and the ⋯, unpainted at rest like the ⋯: the vendored `.action-row-verb` tint fails the rubric's COMP-05 on every row): one click opens the date sheet beside the row, one pick moves the task, with Undo. On the phone a swipe left opens the same sheet and a swipe right completes (the defaults since #311). Select mode keeps its shape, with **Move** as the bar's first action. The meta line is on a budget: due (repeat glyph folded in) · exception chips only, neutral (*Blocked* or the day a snooze ends, *Inbox* / *Standby* where the view does not say the status, *High*; no medium/low mark, no danger tone; overdue and due today in the attention tone) · one context name (the project when ungrouped, else the issue code), the only part the ellipsis may take on a phone · at most two counts. The folder, AI and issue glyphs and the person left the row: the ⋯ menu opens each link and the drawer shows them all.

| # | Step | Expected |
| --- | --- | --- |
| 10 | Desktop Today (story 05, step 6b): look at a row, click its **Move**, pick *Tomorrow*, press Undo | The verb sits between the title and the kebab, 44px, within the action-row budget. The sheet opens beside the row with the push-outs first, each with its date; the pick moves the task off today's list with a `Due …` toast; Undo puts the date back |
| 11 | Board Select mode (story 05, step 12): tick two rows, press the bar's first square (**Move**), pick *Next week* | The sheet is titled for the selection and offers *No date*; both tasks land on the date `GET /api/dates` gives for *next week* |
| 12 | Phone (story 07): a row with every part the budget allows — overdue, blocked, standby, High, a long project name, a child and a comment, plus a folder and an AI link | At 390 px the chips read *Blocked · Standby · High* whole, both counts show, and only the project name is ellipsized (each part measured against its own max-content width once the web font is in). No folder, AI, issue or person glyph on the line; the ⋯ menu offers *Open folder*, *Open AI conversation* and *Move…*; no Move square on a touch screen |
| 13 | Phone (story 07): swipe the row left, then right | Left opens the sheet titled *Move to a date*, nothing written; right completes with Undo, and Undo restores the status |

**Everything still reachable from the row.**

| Was on the row | Where it lives now |
| --- | --- |
| Folder glyph | ⋯ → *Open folder* · drawer *Folder* section |
| AI conversation glyph | ⋯ → *Open AI conversation* (and *Resume in CLI* on a PC) · drawer *Links* |
| Issue glyph | ⋯ → *Open issue repo#N* · drawer issue panel |
| Person | drawer *Person* field · filter card *person* |
| Code beside a project | drawer *Code* field (still on the row when there is no project) |
| Medium / low priority mark | drawer *Priority* field · ⋯ → *Cycle priority* |
| Bulk bar's native date picker | the bar's **Move** → date sheet → *Pick a date…* |

**Proof.** [story-05-board-13-desktop.png](../screenshots/story-05-board-13-desktop.png) (Move's sheet beside a desktop row) · [story-07-phone-9-phone.png](../screenshots/story-07-phone-9-phone.png) (the full-budget row at 390 px) · [story-07-phone-10-phone.png](../screenshots/story-07-phone-10-phone.png) (the sheet on the phone). Tests: `tests/e2e/test_story_05_board.py` steps 6b and 12 plus the phone bar leg, `tests/e2e/test_story_07_phone.py` (`_walk_row_tap_targets`), and the reworked meta assertions in stories 04, 08, 09, 10 and 20; no new test file, the suite stays at 16. The 390 px budget check was proven red first: on the build that let the chips shrink by weight it reported all three chips cut (each a fraction of a pixel short, which is what paints "Block…"), and two weaker checks (integer `scrollWidth`, text range extents) had passed over that same build, so the check measures each part against its own max-content width after the web font loads.

**Design measure (seeded pre-check, rubric 1.18.0, 66/66 screens):** A 97.83, failing TYPE-01 and COMP-02 only, both already failing in the post-#391 baseline (A 96.83). A first build that used the vendored `.action-row-verb` tint failed COMP-05 (an icon-only button painted at rest) on 38 desktop rows, so the verb is an unpainted icon button; the contradiction between that recipe and the rubric is filed upstream (project-scaffolding#347).

**Result.** verified in the browser: e2e desktop and phone (light), headed walk of stories 05 and 07 on a disposable seeded instance (invented data only; no real task was written). **Not verified:** the swipe and the Move sheet on a real iPhone, and dark mode on a real phone; the owner's checklist above still applies. On a Board column narrowed by the open drawer the chips and counts ellipsize once the project name is gone (the Board is rebuilt in step 6/7). Date: 2026-10-10.
