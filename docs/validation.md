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
| 06 | [Edit in a text editor](validation/story-06-mirror.md) | `tests/e2e/test_story_06_mirror.py` | verified (typing inside the editor window itself not verified — see record) | 2026-08-29 |
| 07 | [Phone](validation/story-07-phone.md) | `tests/e2e/test_story_07_phone.py` · `tests/test_auth.py` | verified in the browser · **real phone not verified** (owner's checklist in the write-up) | 2026-08-17 |
| 08 | [An issue becomes a task](validation/story-08-issues.md) | `tests/e2e/test_story_08_issues.py` | verified (fake provider on screen + real GitHub walk, counts only) | 2026-08-17 |
| 09 | [Open a folder](validation/story-09-folders.md) | `tests/e2e/test_story_09_folders.py` · `tests/test_opener.py` · `tests/test_placeholders.py` · `tests/test_folder_index.py` | verified on PC #1 (browser → opener → Explorer) · **second PC not verified** (steps in the write-up) | 2026-08-17 |
| 10 | [Find anything](validation/story-10-search.md) | `tests/e2e/test_story_10_search.py` · `tests/test_search_adapters.py` | verified (fixture indexes on screen · real email index via CLI, counts only) · **opening a `.msg` through the opener not verified** | 2026-08-17 |
| 11 | [The AI conversation on the task (#77)](validation/story-11-ai-links.md) | inside `tests/e2e/test_story_09_folders.py` (§ #77) · `tests/test_schema.py` · `tests/test_opener.py::test_resume_*` | verified (e2e + real-transcript dry-run + live walk + real terminal spawn) · **real phone = owner's checklist** | 2026-08-26 |

Each story's full write-up (steps, expected, transcript/screenshots, result) lives in `docs/validation/story-NN-<slug>.md`; this file is the index. New stories: add a row here and a file there.

## UX rounds

Owner-feedback polish rounds after a phase closes — story-level validation (adjusted story assertions + a headed phone walk), recorded like a story but numbered per round.

| Round | Scope | Record | Result | Date |
| --- | --- | --- | --- | --- |
| 1 | Board density + flat separators, comment composer, activity weight, tree clarity (order · guides · no idle drop zone · drawer "Move to"), one-line Today rows (#27) | [ux-round-1.md](validation/ux-round-1.md) | verified (browser walk + e2e) · real-phone re-check owner-only | 2026-08-19 |
| 2 | Board matched to the launcher's flat dense board against reference screenshots: row density (comment count, one-line titles), no card containers (flat columns + filter bar), compact select on the text block, drawer title wrap on phone, composer hint (#32, re-does part of #27) | [ux-round-2.md](validation/ux-round-2.md) | verified (pixel loop vs reference + e2e) · real-phone re-check owner-only | 2026-08-19 |
| 3 | One task row + one status select + one filter card (collapsed, sort included, finished items findable) shared by Board · Table · Tree · Today · Search; flat views, no caps titles, standard pill / bar sizes; Settings cards collapsible with state words; Search without timings, title-as-link, collapsible groups; drawer description icon, one-line links, due picker (#46) | [ux-round-3.md](validation/ux-round-3.md) | verified (screenshots phone + desktop on the seeded instance + e2e) · real-phone re-check owner-only | 2026-08-22 |
| 4 | Filter card as a two-by-two grid on the phone with person + status multi-selects; no line under the filter card on the Table; search hits for folders / emails / issues as plain title + meta rows, no glyphs or buttons; Settings body text at the row meta size, coloured words bold (#48) | [ux-round-3.md — round 4](validation/ux-round-3.md#round-4-issue-48) | verified (screenshots + e2e) · real-phone re-check owner-only | 2026-08-22 |
| 5 | Board (and Table · Tree · Today): the text filter promoted out of the collapsed card into an always-visible top strip, quick-add shrunk to a `+` that opens one dialog — then (round 2, owner feedback) that dialog grown into a real editor: description · due · status · folder · one link, set before the task exists; Search untouched (#80) | [ux-round-5.md](validation/ux-round-5.md) | verified (headed desktop + phone walk, screenshots read back + e2e) · real-phone re-check owner-only | 2026-08-28 |

## Phase gates

| Phase | Stories | Gate run | Result |
| --- | --- | --- | --- |
| A — v1 | 01–07 | 2026-08-17 13:1x local, `scripts\verify-before-ship.ps1` on `main` `3d37a86`: byte-compile · ruff · 253 unit · e2e full tier 14 tests (~43 s), all green in one sitting | **closed** — with the owner's checklist below still open |
| B — integrations | 08–10 | same run | **closed** — same checklist |
| C — second site | 11–13 | not started | open — needs a machine with a GitLab host / a second person / the real list export |

### Owner's checklist — the on-screen items only the owner can walk

- [ ] **Phone (Story 07):** open `https://<your-host>.ts.net:8448` on the phone (on the tailnet) → sign in with the token/password → Add to Home Screen → launch standalone → quick-add, Board swipe, drawer, folder-chip long-press → theme persists.
- [ ] **Second PC (Story 09):** paste the one-line install from `opener/install.txt` (or run `opener/install_opener.py`) → click a folder chip in the browser → the browser's one-time prompt → Explorer opens that PC's synced copy.
- [ ] **Email through the opener (Story 10):** click an email hit's chip → the `.msg` opens in the mail client.
- [ ] **Story 06:** type in a real editor window and save (the harness could only script the save).

Each item's exact steps are in the story's write-up. Tick here (and in the story) when walked; the tick means "seen", not "should work".
