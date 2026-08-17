# Validation — every step is a user story, proven on screen

Technical green is not enough. Each build step (a "Step N/13" issue) has a story — the sequence a user actually performs — and the step is done only when that sequence has been (a) walked by the automated Playwright test `tests/e2e/test_story_NN_<slug>.py`, which saves numbered screenshots, and (b) walked live on screen with the same shots kept here as proof. Phases close with a full storyboard re-run (Phase A: stories 1–7; B: 8–10; C: 11–13).

Rules: screenshots come from a **synthetic / empty fixture**, never real data (this repo is public); real-data checks are walked too but their shots go on the private issue, not here. `[x]` means "walked and seen". Anything that could not be walked is written **not verified**, never as passed.

| # | Story | Test | Result | Date |
| --- | --- | --- | --- | --- |
| 01 | [Open the app](validation/story-01-open.md) | `tests/e2e/test_story_01_open.py` | verified | 2026-08-17 |
| 02 | [Add and nest from the terminal](validation/story-02-terminal.md) | `tests/test_cli.py::test_story_02_add_nest_comment_tree_due_show` · `tests/test_api.py::test_story_02_over_http` | verified | 2026-08-17 |
| 03 | [Import my Notion](validation/story-03-notion-import.md) | `tests/test_import_notion.py` | verified | 2026-08-17 |
| 04 | [Monday triage](validation/story-04-triage.md) | `tests/e2e/test_story_04_triage.py` | verified | 2026-08-17 |
| 05 | [Board day](validation/story-05-board.md) | `tests/e2e/test_story_05_board.py` | verified | 2026-08-17 |

Each story's full write-up (steps, expected, transcript/screenshots, result) lives in `docs/validation/story-NN-<slug>.md`; this file is the index. New stories: add a row here and a file there.
