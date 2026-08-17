# Story 08 — An issue becomes a task

**Issue:** #9 (Step 8/13). **Test:** `tests/e2e/test_story_08_issues.py` (1 test, 1440×900 Chromium) against the **issues** disposable instance (conftest `issues_webapp`: the synthetic seed + the file-backed fake provider `src/issues/fake.py` — the "forge" is a temp JSON file the test edits between syncs; never `gh`, never the network, never `data/tasks.db`). Unit coverage: `tests/test_issues.py` (sync creates coding tasks in Inbox with code / description / issue link and dedupes on a re-run; title change lands on the task; closed → done + `sync` activity, skipped when already done / cancelled; reopened → `todo`; missing-from-the-list but still open is **not** closed; a lookup error leaves the task alone and is reported; a listing failure changes nothing and is a status; a manually linked ref is confirmed and filled; the service's not-configured states and the scheduler thread; the GitHub provider over recorded `gh` JSON — search / view / create argv and parsing — and its named failures: `not_installed` · `timeout` · `not_authenticated` · `rate_limited` · `not_found` · `error`; the routes incl. `already_linked` / `issues_disabled` / `provider_error`; the CLI `issues sync|status` and `issue create`).

**Steps → expected**

1. Board → **↻** in the header (visible only when the provider is configured) → toast *Issues synced: 3 open · 2 new* → the two open issues without a task become **coding** tasks in **Inbox** (title = issue title, `code = repo#N`, description = the issue body, an `issue` link, `created_by = sync`), each with a GitHub chip; the seeded coding task (`garden-bot#12`, already linked) is matched, not duplicated.
2. Open one → the drawer's **Issue** panel: provider glyph, `repo#N` chip linking to the issue, `open` pill, the labels from the last sync (`enhancement`), *github · last synced …*, **Sync now**, **Unlink**.
3. Tree → drag it under *Side project: garden-bot* → nested, the chip travels with it, activity `parent`.
4. The issue is **closed on the forge** (the test edits the fake's file) → **↻** → toast *… 1 closed* → the task is **done** (`done_at` set, ref `closed`); activity `status inbox → done · sync` and `issue_state open → closed · sync`; the drawer shows status *done*, the `closed` pill and the muted chip with a check. The seeded coding task, still open on the forge, is untouched.
5. A plain task's Issue panel offers **Create issue** (repo from the last-seen list or typed) and **Link existing** (`owner/repo#N` or URL) → *Create issue* in `example/garden-bot` → toast *Created example/garden-bot#15* → the task is coding, `code = garden-bot#15`, the chip is in the panel and on its Board card; the forge file gained issue 15 with the task's title.
6. Settings (dark) → *Issues as tasks* card: **enabled · github · every 10 min · next …**, last sync with the counts (*2 open issue(s) · 0 new · 0 retitled · 0 reopened · 1 closed*), the repos seen, **Sync now** enabled.

**Screenshots (desktop 1440×900) — saved by the test**

| Step | Desktop |
| --- | --- |
| 1 Board after ↻: two coding cards in Inbox, toast | [story-08-issues-1-desktop.png](../screenshots/story-08-issues-1-desktop.png) |
| 2 drawer: issue panel — chip, open, label, last synced | [story-08-issues-2-desktop.png](../screenshots/story-08-issues-2-desktop.png) |
| 3 Tree: the issue task nested under the project | [story-08-issues-3-desktop.png](../screenshots/story-08-issues-3-desktop.png) |
| 4 drawer after the close: done · activity by `sync` · closed chip | [story-08-issues-4-desktop.png](../screenshots/story-08-issues-4-desktop.png) |
| 5 drawer: a plain task's panel — Create issue / Link existing | [story-08-issues-5-desktop.png](../screenshots/story-08-issues-5-desktop.png) |
| 5 drawer after Create issue: linked, code, open chip | [story-08-issues-6-desktop.png](../screenshots/story-08-issues-6-desktop.png) |
| 6 Settings (dark): provider enabled, last sync counts | [story-08-issues-7-desktop.png](../screenshots/story-08-issues-7-desktop.png) |

**Real-provider walk — 2026-08-17 (headed Chromium + the CLI, against a disposable instance of this build over a *scratch copy* of the real database, config `issues.provider = github`, `owner = ferraroroberto`, `gh` authenticated as the owner; screenshots kept off the repo — counts only, no titles)**

| Step | Observed |
| --- | --- |
| `tasks issues sync` on a DB with 0 issue refs | `72 open issue(s) · 72 new` in 1.9 s (one `gh search issues` call) — 72 coding tasks in Inbox across 40 repos; Board Inbox count 1 → 73 |
| `tasks issues sync` again | `73 open · 0 new` — nothing duplicated |
| `tasks add "test: sync probe (auto-closed)"` → `tasks issue create 288 --repo ferraroroberto/task-os` | `gh issue create` opened **task-os#22** (assigned to the owner), the task became coding, `code task-os#22`, activity `issue ∅ → ferraroroberto/task-os#22`; the drawer's panel showed the chip, `open`, *last synced* |
| ↻ from the drawer panel right after `gh issue close 22` | *73 open · nothing changed* — GitHub's **search index lags a close by ~30 s** (documented in the README); the task stayed inbox |
| `tasks issues sync` ~45 s later | `72 open issue(s) · 1 closed · done: #288` — task done, activity `status inbox → done · sync` + `issue_state open → closed · sync` |

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. the 22 `test_issues` cases), the routed e2e (full tier: smoke + stories 01, 04, 05, 06, 08).
- [x] On screen (fake provider): the story test's seven shots above, zero page errors.
- [x] On screen (real provider): the headed walk in the table above — the owner's real open issues appeared as coding tasks in Inbox after one ↻, a probe issue created **from a task** with the real `gh issue create`, closed on GitHub, and marked done by the next sync with actor `sync`.
- [x] Live app: not restarted from this worktree by design — the orchestrator restarts after the squash-merge; the live sync starts 10 s after that restart and creates the coding tasks in the real database then.
- Not verified in this step: the 10-minute scheduler tick was not waited for (unit-tested with a short interval; the startup pass was observed); a reopened issue on the real forge (unit-tested against the fake only); the phone rendering of the issue panel (no phone-specific markup was added — the drawer sheet is the Step 4 one); GitLab (Step 11).
