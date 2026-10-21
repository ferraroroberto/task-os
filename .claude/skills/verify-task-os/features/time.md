# time

<!-- gen:begin feature -->
**Seeded from:** surface()

**How a user reaches it**

- Not declared in `.fleet.toml` or `CLAUDE.md`. Read the driving test: it opens the surface before it calls `surface()`.

| Sub-feature | Surface name | Driving test node(s) |
| --- | --- | --- |
| dialog-add | `time.dialog-add` | `tests/e2e/test_story_32_time.py::test_track_time_and_compare_shares` |
| dialog-running | `time.dialog-running` | `tests/e2e/test_story_32_time.py::test_track_time_and_compare_shares` |
| log-running | `time.log-running` | `tests/e2e/test_story_32_time.py::test_track_time_and_compare_shares` |
| totals | `time.totals` | `tests/e2e/test_story_32_time.py::test_track_time_and_compare_shares` |

**Drive:** `.\.venv\Scripts\python.exe -m pytest tests/e2e/test_story_32_time.py::test_track_time_and_compare_shares -q --browser chromium` (the suite boots its own disposable instance).
<!-- gen:end feature -->

## Gotchas

_None recorded yet._ Add one line per trap: the symptom, then the fix. Regeneration never touches this section.
