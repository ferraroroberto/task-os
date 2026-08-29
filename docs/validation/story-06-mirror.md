# Story 06 — Edit in a text editor

**Issue:** #7 (Step 6/13). **Test:** `tests/e2e/test_story_06_mirror.py` (1 test, 1440×900 Chromium) against the **mirrored** disposable instance (conftest `mirrored_webapp`: the synthetic seed with `mirror.dir` / `mirror.backup_dir` under a temp folder — never a real synced folder, never `data/tasks.db`). Unit coverage: `tests/test_mirror.py` (frontmatter round-trip, deterministic/idempotent export, rename + delete, changed `due` with actor `md`, natural phrase + person by name, description, appended comment lines, deleted lines are not deletions, conflict-as-event, rejected-as-event no comment, malformed file skipped, watcher tick, pending-edit-before-export, disabled reasons, migration v4/v6, `/api/status` + on-demand runs, CLI), `tests/test_backup.py` (dated copy, prune to 30, scheduler due logic + thread).

**Steps → expected**

1. The app starts with `mirror.dir` configured → within a couple of seconds the folder holds one `.md` per task (`0003-get-three-quotes.md`, …); Settings shows the *Markdown mirror & backup* card with both services **enabled**, the folders, the file count, and *both on*.
2. Open a task's file in an editor → change `due:` to `2026-12-24` and add a line `- checked the tiles supplier, they deliver on Fridays` under `## Comments` → save.
3. Within seconds (the watcher polls every 2 s) the app shows both: `GET /api/tasks/{id}` has the new due, the top activity row is `due 2026-08-20 → 2026-12-24` with **actor `md`**, and a comment `origin = md` (author = the configured owner) with the typed text; the file is re-exported to canonical form (the bare line gains its timestamp / author / `md`). The drawer (`#task/{id}`) shows the comment with the `md` badge and the activity row `md · <time>`.
4. Conflicting edit: the app changes the due to `2026-11-11` (a UI edit) and, right after, the file — still carrying the older export — is saved with `due: 2026-10-10` → the **DB wins**: the due stays `2026-11-11`, and the rejected file value is recorded as a `mirror_events` row (`GET /api/mirror/events`: `field=due, file_value=2026-10-10, kept_value=2026-11-11`) — **not** a comment on the task (the comment thread is untouched). The Settings mirror card shows *"1 since the last review"* with an inline preview; **Clear import conflicts** empties it. The file converges to `due: 2026-11-11`. Nothing lost.
5. The backup folder holds `tasks-YYYYMMDD.db` (the startup pass writes today's copy when missing); `/api/status` reports it as `last_file`. A malformed file (`title: [oops`, unterminated frontmatter) is **skipped**: `errors: 1` + its name in `error_files`, one log warning, `/healthz` still OK; the Settings card shows *enabled · 1 file(s) skipped* with the file name (dark theme).

**Screenshots (desktop 1440×900) — saved by the test**

| Step | Desktop |
| --- | --- |
| 1 Settings card, both on, 43 files | [story-06-mirror-1-desktop.png](../screenshots/story-06-mirror-1-desktop.png) |
| 3 drawer: the comment typed in the file, `md` badge | [story-06-mirror-2-desktop.png](../screenshots/story-06-mirror-2-desktop.png) |
| 3 drawer: activity `due 2026-08-20 → 2026-12-24 · md` | [story-06-mirror-3-desktop.png](../screenshots/story-06-mirror-3-desktop.png) |
| 4 Settings card: the import conflict, inspect + clear | [story-06-mirror-4-desktop.png](../screenshots/story-06-mirror-4-desktop.png) |
| 5 Settings (dark): backup file · 1 file skipped | [story-06-mirror-5-desktop.png](../screenshots/story-06-mirror-5-desktop.png) |

**Headed walk — editor + app side by side (1920-wide screen capture, taskbar cropped; a disposable seeded instance on another port over a scratch DB + temp mirror folder; Notepad on the left, headed Chromium on the right)**

| Moment | Capture |
| --- | --- |
| before: Notepad on `0003-get-three-quotes.md`, drawer beside it | [story-06-mirror-6-desktop.png](../screenshots/story-06-mirror-6-desktop.png) |
| after the file save: drawer shows the `md` comment + `due … → 2026-12-24 · md`; the file re-opened shows the canonical re-export | [story-06-mirror-7-desktop.png](../screenshots/story-06-mirror-7-desktop.png) |
| after the conflicting edit: Settings card shows the import conflict (not a comment — the drawer's comment thread is unchanged), `due: 2026-11-11` | [story-06-mirror-8-desktop.png](../screenshots/story-06-mirror-8-desktop.png) |

Backup folder after the walk (`tasks backup` against the scratch instance, then a listing):

```
tasks backup → backup written: <temp>\backup\tasks-20260817.db
tasks mirror status →
mirror   enabled · <temp>\mirror · 43 file(s) · last export 2026-08-17T11:21:03+02:00 · last import 2026-08-17T11:21:03+02:00 · errors 0 · watching
backup   enabled · <temp>\backup · last tasks-20260817.db · next 2026-08-18T03:00
backup dir: [('tasks-20260817.db', 135168)]
```

**Result — 2026-08-17: verified (with one honest caveat below).**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. `test_mirror`, `test_backup`, the schema v4 cases), the routed e2e (full tier: smoke + stories 01, 04, 06).
- [x] On screen: walked headed (Chromium 1440-wide viewport in a 960-px window beside Notepad, then the full drawer) on a disposable instance of this build over a freshly seeded scratch database and a temp mirror folder (`TASKOS_DB_PATH` / `TASKOS_CONFIG_PATH` → scratch; never `data/tasks.db`, never a real synced folder): observed = expected on every step — the folder filled on startup, the edited `due` and the typed comment line appeared in the drawer within ~2 s with actor `md`, the file was rewritten to canonical form, the conflict landed as a comment in both the drawer and the file, the backup file existed, the malformed file was skipped and shown on the Settings card. Zero page errors in the console.
- [ ] **Not verified — typing inside the editor window itself.** The agent's harness cannot inject keystrokes into other desktop windows (SendInput from it never reaches Notepad / VS Code, confirmed with a probe), so in the headed walk the *save* was performed by the walk script (`write_text` + a saved mtime — byte-for-byte what an editor's Ctrl+S produces) while Notepad displayed the file before and after. What the app does with a saved file is exactly what was walked; the human keystroke → save step is the one thing not seen. A five-second manual check (open the file, change `due:`, save, watch the drawer) closes it.
- [x] Live app: not restarted from this worktree by design — the orchestrator restarts after the squash-merge; `/api/version` will report `schema_version: 4` on the new build.
- Not verified in this step: the mirror against a real OneDrive-synced folder over days (the sample config's `{onedrive}/task-os` does not exist on this machine, so the live app reports *mirror: not configured — parent folder missing* until the folder is created — a visible state, by design); the 03:00 scheduler firing at 03:00 (unit-tested `due_now` / `next_run_after` + the startup pass observed; the daily tick was not waited for); a second site's teammate editing the mirror over SharePoint (Step 12).

**Result — 2026-08-29: re-verified after issue #84 (import diagnostics moved out of the comment thread).**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the full unit suite (269 tests, incl. `test_mirror`'s conflict/rejected-as-event and dedupe-on-repeat cases, the schema v6 case), the routed e2e (full tier, 14 tests — the diff touched `app/webapp/routers/mirror.py` and `tests/e2e/test_story_06_mirror.py`).
- [x] On screen: the updated step 4 of `test_edit_in_a_text_editor` walked a real (headless) Chromium session against a disposable instance — conflicting edit → `GET /api/mirror/events` shows exactly one `{field: due, file_value: 2026-10-10, kept_value: 2026-11-11}` row, the task's comment thread is unchanged (still just the step-3 `md` comment), the Settings mirror card reads *"1 since the last review — due: file said 2026-10-10, kept 2026-11-11"* in both themes, and **Clear import conflicts** empties it (`0`, toast confirms). Screenshots 1–5 regenerated (`story-06-mirror-4-desktop.png` re-shot to show the Settings card instead of the old conflict comment) and inspected in-session.
- [x] Live app: not restarted from this worktree by design — the orchestrator restarts after the squash-merge; `/api/version` will report `schema_version: 6` on the new build.
- Not re-verified in this pass (unchanged from 2026-08-17, still open): typing inside a real editor window, the mirror against a real OneDrive-synced folder, the 03:00 scheduler tick, a second site's teammate editing over SharePoint.
