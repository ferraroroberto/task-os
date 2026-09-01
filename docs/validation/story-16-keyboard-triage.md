# Story 16 — Triage with the keyboard (#99)

**Story.** A triage pass is keys, not mouse trips. `Tab` lands on a row — it tints, so the target is never in doubt — and then `e` completes it, `1`–`4` set the status, `t` / `w` set the due date, `s` opens the snooze menu, `p` cycles priority. Every change raises a toast with **Undo (Z)**, so speed is safe: `z` puts the exact prior value back through the API, activity row and all. With tasks ticked ([#81](story-12-bulk-select.md)) the same key does it to the whole selection — and the undo restores each task's *own* prior value, not one shared one. Focus stays on the row after the write (or on whatever takes its place when the task leaves the view), so `e e e` walks a column. `?` is the reference card; the command palette lists the same actions with their keys, which is where a shortcut is discovered.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Focus a Board card, press `p` | Priority steps one up (`low` → `medium`); toast `Priority medium` with **Undo (Z)** |
| 2 | Press `z` | The value is back, and `/api/tasks/{id}` carries **two** priority activity rows — `low → medium` then `medium → low`: the reversal is a write, not a client-side rollback |
| 3 | Press `t` on the same row | Still focused after the re-render; due = tomorrow |
| 4 | Focus a **recurring** task, press `e`, then `z` | `e` rolls the due one cadence forward and leaves the status alone (#54 semantics); the undo restores the **pre-roll** due |
| 5 | Type `etw` in the filter box; open the drawer and press `1` | Nothing happens to any task — the keys are inert wherever text is typed and while the drawer owns the keyboard |
| 6 | Tick two rows with **different** statuses, press `1`, then `z` | Both → `inbox`, toast `2 tasks · status inbox`; the undo puts `todo` and `doing` back — one call per group of tasks that shared a value. The ticks survive, so keys come in runs over one set |
| 7 | Focus a **Table** grid row (a `<tr>`, not the shared row) and a **Search** hit, press a key on each, undo both | Both act — the Table's own row element is a target, and the search hit's prior values come from a fetch (a hit can be a task outside the filtered list, so what is on screen is not enough) |
| 8 | Press `?` (light, then dark) | The shortcuts sheet: every action key with what it does, then *Getting around* (Tab · Enter · Space · Ctrl K · Esc). Built from the one keymap table in `keys.js`, so it cannot drift from the handler |
| 9 | `Ctrl+K` → `>priority` | The palette lists **Cycle priority** with its `P` badge and names what it will act on (the focused row's title, or *N selected*) |

## Proof

- Screenshots: [story-16-keyboard-triage-1-desktop.png](../screenshots/story-16-keyboard-triage-1-desktop.png) (the row acted on, toast with Undo (Z)) · [2](../screenshots/story-16-keyboard-triage-2-desktop.png) (one key over a two-task selection) · [3](../screenshots/story-16-keyboard-triage-3-desktop.png) (the `?` sheet) · [4](../screenshots/story-16-keyboard-triage-4-desktop.png) (the sheet, dark) · [5](../screenshots/story-16-keyboard-triage-5-desktop.png) (the palette entry carrying its key).
- E2e: `_walk_keyboard_actions` inside `tests/e2e/test_story_05_board.py` (§ #99 — rides the existing Board/select story, so the suite stays at 14 tests).
- Unit: `tests/test_api.py::test_bulk_sets_starts_and_priority_for_the_row_keys` — `POST /api/tasks/bulk` takes `starts` and `priority` (the `s` and `p` keys over a selection), resolves a start phrase once per request, and accepts a priority-only body, which the grouped cycle and the grouped undo both send.

## Result

verified — e2e walk + screenshots on the seeded instance (light and dark), unit suite green, headed walk on the real install. Date: 2026-09-01.

**Deliberate limits:** the Tree takes no action keys (its keyboard model is navigation-first — ↑↓→← Enter — and the issue keeps it that way); no new arrow navigation on the other tabs (Tab moves, the Table grid keeps the ↑↓ it already had); undo is single-level with no redo, and expires with its toast rather than on a timer of its own; the keys are a desktop affordance — a phone has no keyboard row to reach them from, and the touch surfaces (row select, snooze button, plan targets) are unchanged.
