# board

<!-- gen:begin feature -->
**Seeded from:** surface()

**How a user reaches it**

- Not declared in `.fleet.toml` or `CLAUDE.md`. Read the driving test: it opens the surface before it calls `surface()`.

| Sub-feature | Surface name | Driving test node(s) |
| --- | --- | --- |
| columns | `board.columns` | `tests/e2e/test_story_05_board.py::test_desktop_board_day` |
| drawer | `board.drawer` | `tests/e2e/test_story_04_triage.py::test_desktop_triage` |
| select-bar | `board.select-bar` | `tests/e2e/test_story_05_board.py::test_desktop_board_day` |

**Drive:** `.\.venv\Scripts\python.exe -m pytest tests/e2e/test_story_04_triage.py::test_desktop_triage tests/e2e/test_story_05_board.py::test_desktop_board_day -q --browser chromium` (the suite boots its own disposable instance).
<!-- gen:end feature -->

## Gotchas

_None recorded yet._ Add one line per trap: the symptom, then the fix. Regeneration never touches this section.
