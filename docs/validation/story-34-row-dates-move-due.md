# Story 34 — Every list date change moves the due date (#703)

**Story.** From any list, a date change moves the task's *due* date and the task stays on the Board and Today in its new place. There is no snooze: the ⋯ menu's date entry is *Move…* (the `D` key, a swipe, Select mode's Move and the desktop row's Move button open the same sheet), and the one-tap *Due tomorrow* / *Due next week* entries push the due out. The start date is edited from the drawer's *Starts* field alone, from quick-add's explicit `starts` and from the CLI.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | On Today, open a task's ⋯ menu | Items start *Complete task* · *Move…*; there is no *Snooze…* |
| 2 | Choose **Move…**, then **Next week** | The sheet is titled *Move to a date*, its phrases each beside their date, *No date* offered. The due date becomes next week's, `starts` stays empty, the toast reads `Due …`, the task is not in the *deferred* list, the activity log's newest field is `due` |
| 3 | Press **Undo (Z)** | The previous due date is back, `starts` still empty |
| 4 | Settings → Row actions: set a swipe to *Move…*, move it to the top of the menu | The row's menu follows; a swipe left opens the sheet over `due`; a cancelled pick writes nothing |
| 5 | Phone: a swipe set to the one-tap due push (or saved under the old snooze name) | The due moves to tomorrow with a `Due tomorrow` toast and Undo, `starts` untouched; Undo restores the due date |
| 6 | Phone: a row's ⋯ → **Move…** | The sheet opens in the vendored modal at 390 px, every option a 44px target, no horizontal overflow |
| 7 | Drawer → More fields → *Starts* | Still set and cleared there; a start date past the due moves the due with it |

**Proof.** [story-13-starts-snooze-4-desktop.png](../screenshots/story-13-starts-snooze-4-desktop.png) (the date sheet from a Today row) · [story-13-starts-snooze-6-phone.png](../screenshots/story-13-starts-snooze-6-phone.png) (the sheet on a phone) · [story-29-row-actions-2-desktop.png](../screenshots/story-29-row-actions-2-desktop.png) (Settings → Row actions). Tests: `tests/test_row_actions.py::test_no_row_action_writes_the_start_date` (inspects the plan and undo of every action, proven red against the build that still had *Snooze…*), `tests/test_row_prefs.py` (a stored snooze id follows to its due twin), `tests/e2e/test_story_04_triage.py` (`_move_from_a_today_row`, `_move_from_the_menu`, `_settings_row_actions`, the phone sheet) and `tests/e2e/test_story_07_phone.py` (the one-tap swipe); no new e2e test, the suite stays at 16.

**Result.** verified in the browser: e2e desktop and phone, light, on a disposable seeded instance (invented data only). **Not verified:** the phone sheet in dark mode and on a real phone. Date: 2026-11-15.
