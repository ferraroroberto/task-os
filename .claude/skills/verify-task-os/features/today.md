# today

<!-- gen:begin feature -->
**Seeded from:** surface()

**How a user reaches it**

- Not declared in `.fleet.toml` or `CLAUDE.md`. Read the driving test: it opens the surface before it calls `surface()`.

| Sub-feature | Surface name | Driving test node(s) |
| --- | --- | --- |
| calendar-lane | `today.calendar-lane` | `tests/e2e/test_story_28_calendar.py::test_today_calendar_lane` |
| calendar-unavailable | `today.calendar-unavailable` | `tests/e2e/test_story_28_calendar.py::test_today_calendar_lane` |
| date-popover | `today.date-popover` | `tests/e2e/test_story_05_board.py::test_desktop_board_day` |
| empty-install | `today.empty-install` | `tests/e2e/test_story_01_open.py::test_story_01_open` |
| soon | `today.soon` | `tests/e2e/test_story_05_board.py::test_desktop_board_day` |

**Drive:** `.\.venv\Scripts\python.exe -m pytest tests/e2e/test_story_01_open.py::test_story_01_open tests/e2e/test_story_05_board.py::test_desktop_board_day tests/e2e/test_story_28_calendar.py::test_today_calendar_lane -q --browser chromium` (the suite boots its own disposable instance).
<!-- gen:end feature -->

## Gotchas

- **Desktop Today preselects a task in the drawer.** After a `#task/<id>` hash navigation, wait on `#drawerTitle` for the target task, not on the drawer being visible: it is visible already, showing the first due task.
- **`today.split-drawer`, `today.drawer-empty`, `today.row-menu` and `today.date-sheet` are not in the table above.** Their `surface()` calls sit in `_walk_*` helpers of `test_desktop_triage` and `test_desktop_board_day` (listed under "Not mapped" in `features/README.md`), so the generator cannot attach a node. Those two tests walk them anyway: run them and read the helper for what is asserted.
- **The drawer, More fields, row menu, Select mode and filter sheet have their own files** (`drawer`, `drawer-more`, `row-menu`, `select`, `filter-sheet`) seeded from `[[design.review.extra_steps]]`, so they show no node of their own. They are read-only clicks on this view's first row or filter button; the walk to drive is `test_desktop_triage`.
