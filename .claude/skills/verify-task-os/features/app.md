# app

<!-- gen:begin feature -->
**Seeded from:** surface()

**How a user reaches it**

- Not declared in `.fleet.toml` or `CLAUDE.md`. Read the driving test: it opens the surface before it calls `surface()`.

| Sub-feature | Surface name | Driving test node(s) |
| --- | --- | --- |
| parent-picker | `app.parent-picker` | `tests/e2e/test_story_04_triage.py::test_desktop_triage` |
| quick-add | `app.quick-add` | `tests/e2e/test_story_04_triage.py::test_desktop_triage` |
| team-name-picker | `app.team-name-picker` | `tests/e2e/test_story_27_team.py::test_teammate_signs_in_picks_a_name_and_comments` |

**Drive:** `.\.venv\Scripts\python.exe -m pytest tests/e2e/test_story_04_triage.py::test_desktop_triage tests/e2e/test_story_27_team.py::test_teammate_signs_in_picks_a_name_and_comments -q --browser chromium` (the suite boots its own disposable instance).
<!-- gen:end feature -->

## Gotchas

_None recorded yet._ Add one line per trap: the symptom, then the fix. Regeneration never touches this section.
