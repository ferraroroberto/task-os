# task-os feature map

One file per view. Seeded from the repo's committed inventories, never hand-written: the e2e suite's `surface()` names first, then `[[design.review.extra_steps]]`, then the `## UX surface` key views in `CLAUDE.md`. Regenerate with project-scaffolding's `scripts/gen_verify_skill.py`; add traps to a view's `## Gotchas`, the only hand-written part.

The step-by-step user stories this map sits beside, with their screenshots, test names and results, are in [`docs/validation.md`](../../../../docs/validation.md). It is linked by hand: the generator does not parse it.

<!-- gen:begin index -->
| Feature | Sub-features | Driving nodes | Seeded from |
| --- | --- | --- | --- |
| [app](app.md) | 3 | 2 | surface() |
| [board](board.md) | 3 | 2 | surface() |
| [board-status](board-status.md) | 1 | 0 | extra_steps |
| [drawer](drawer.md) | 1 | 0 | extra_steps |
| [drawer-more](drawer-more.md) | 1 | 0 | extra_steps |
| [filter-sheet](filter-sheet.md) | 1 | 0 | extra_steps |
| [home](home.md) | 1 | 0 | key views |
| [login](login.md) | 1 | 0 | key views |
| [row-menu](row-menu.md) | 1 | 0 | extra_steps |
| [search](search.md) | 1 | 1 | surface() |
| [select](select.md) | 1 | 0 | extra_steps |
| [settings](settings.md) | 1 | 1 | surface() · extra_steps |
| [settings-archive](settings-archive.md) | 1 | 0 | extra_steps |
| [settings-opener](settings-opener.md) | 1 | 0 | extra_steps |
| [time](time.md) | 4 | 1 | surface() |
| [today](today.md) | 5 | 3 | surface() |

**Not mapped** (a `surface()` call the generator cannot turn into a driving node):

- `tests/e2e/test_story_04_triage.py::_walk_phone_rows_and_drawer_sheet`: `today.date-sheet` is called outside a test function
- `tests/e2e/test_story_04_triage.py::_walk_starts_and_snooze`: `today.row-menu` is called outside a test function
- `tests/e2e/test_story_04_triage.py::_walk_today_split`: `today.drawer-empty` is called outside a test function
- `tests/e2e/test_story_04_triage.py::_walk_today_split`: `today.split-drawer` is called outside a test function
- `tests/e2e/test_story_05_board.py::_walk_delete_task`: `app.confirm-delete` is called outside a test function
- `tests/e2e/test_story_05_board.py::_walk_done_journal`: `journal.done-days` is called outside a test function
- `tests/e2e/test_story_05_board.py::_walk_keyboard_actions`: `app.keys-help` is called outside a test function
- `tests/e2e/test_story_05_board.py::_walk_keyboard_actions`: `app.palette` is called outside a test function
<!-- gen:end index -->
