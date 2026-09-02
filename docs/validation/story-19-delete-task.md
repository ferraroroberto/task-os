# Story 19 — Delete a task (#121)

**Story.** A task made by mistake — a test, a duplicate, a quick-add typo — can now leave the app from where you are looking at it. The drawer's foot carries a quiet **Delete task**; the confirmation names the task and, when it has one, its subtree (*Its 2 child tasks go with it*), says plainly that nothing can be undone, and — for a synced coding task whose issue is still open — that the next sync will recreate it, so unlink first or close the issue. Escape, the × or the backdrop mean "no" and leave everything as it was; **Delete** removes the task with its comments, links and history, closes the drawer, clears the hash, refreshes every view and toasts how much went. A batch of mistakes goes through the Select bar's fourth square, one confirmation with the count, the same per-id report as every bulk action. `tasks rm N` does the same from the terminal: it names what goes on stderr, asks `[y/N]`, and a refusal is exit 1 with the error envelope so a script that forgot `--yes` fails loud.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open a project's drawer (`#task/<id>`), click **Delete task** at the foot | The dialog: *Delete "Repaint the garden fence"?* · *Its 2 child tasks go with it.* · *This cannot be undone …*; no warning line (not a synced coding task); the single primary is the danger-tinted **Delete**; focus is on the × so Enter cannot confirm unread |
| 2 | Press Escape | The dialog closes, the drawer stays open, `GET /api/tasks/<id>` is still 200 |
| 3 | **Delete task** → **Delete** | The drawer closes, the hash clears, the toast reads `Deleted "Repaint the garden fence" · 3 tasks`, the task and its children answer 404, the Board no longer shows them |
| 4 | Table → Select mode → tick two rows → the bar's trash square | *Delete 2 tasks?* with the no-undo line; confirm → `2 tasks deleted`, the rows are gone, the selection is empty but Select mode stays on |
| 5 | A synced coding task with an open issue → **Delete task** | The dialog carries the red warning: the next issue sync recreates it while `repo#N` stays open — unlink first, or close the issue |
| 6 | Terminal: `tasks rm N` | stderr: the task line, `and its N child tasks`, the coding warning when it applies, `delete? This cannot be undone. [y/N]`; `n` → `error: #N not deleted`, exit 1 (`{"error": {"code": "cancelled"}}` under `--json`); `y` → `#N deleted (3 tasks)`; `--yes` asks nothing; `delete` is the alias; an unknown id → exit 1, `not_found` |
| 7 | Mirror | The deleted subtree's markdown files are removed on the next export tick (existing behaviour, `tests/test_mirror.py`) |

## Proof

- Screenshots: [story-19-delete-task-1-desktop.png](../screenshots/story-19-delete-task-1-desktop.png) (the drawer's confirmation naming the subtree, light) · [2](../screenshots/story-19-delete-task-2-desktop.png) (the Select bar's batch confirmation over the Table).
- E2e: `_walk_delete_task` inside `tests/e2e/test_story_05_board.py` (§ #121 — rides the Board story, so the suite stays at 14 tests). The walk makes its own tasks over the API so the seed stays whole for the other walks.
- Unit: `tests/test_repo.py::test_bulk_delete_names_the_gone_and_folds_a_child_into_its_parent` (`descendant_count` on the detail; the per-id report; a ticked child whose parent went first is `ok, deleted: 0`, an unknown id is named, duplicates collapse) · `tests/test_api.py::test_bulk_delete_reports_per_id` (the route's shape and counts, an empty `ids` is 422) · `tests/test_cli.py::test_rm_over_both_backends` (the dialogue on stderr, the refusal as exit 1, the alias, `--yes`, an unknown id) · `tests/test_mirror.py` already proves a repo delete removes the mirror file.

## Result

verified — e2e walk + screenshots on the seeded instance (desktop light), unit suite green, headed walk on the real install with a throwaway task (drawer dialog, cancel, confirm, toast; the Select bar's dialog opened and cancelled). Steps 5 and 6's warning line: unit-tested on the CLI (the dialogue text), read in the code for the drawer — the seed's one synced coding task rides the other walks, so it was not deleted on screen. Date: 2026-09-02.

**Deliberate limits:** no trash, no restore, no activity record of the deletion (nothing is left to hang it on); no delete key in the keymap (a destructive action stays a click plus a confirmation); the open-issue case warns rather than refuses — the delete is the owner's call, the warning is what keeps a resurrection from looking like a failed delete; the confirmation keeps no state — every ask is built fresh into the one dialog shell.
