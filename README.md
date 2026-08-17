# task-os

A personal, open-source task manager: one master list for everything, self-hosted on your own PC. Nested tasks that become projects by having children, comments with clickable links, an activity log, local-folder links that resolve per machine, GitHub/GitLab issues as first-class tasks, and one search box over tasks, folders, emails and issues. PC-first and full-width; the phone gets the same views as an installable PWA over Tailscale; an LLM reaches it through a CLI, a JSON API and a markdown mirror.

Built step by step — each step is a GitHub issue with a user story that is proven on screen before it closes ([`docs/validation.md`](docs/validation.md)). Shipped so far: **Step 1** the shell, **Step 2** the core — SQLite schema, JSON API and the `tasks` CLI, **Step 3** the one-shot Notion importer, **Step 4** the PC-first views — Table, Tree, the task drawer and quick-add, **Step 5** the Board and Today views, **Step 6** the markdown mirror + nightly backup, **Step 7** phone access — Tailscale HTTPS, token / password sign-in, the installable PWA. Internal map: [`docs/architecture.mmd`](docs/architecture.mmd).

## Stack

Python 3.14 · FastAPI + uvicorn · stdlib `sqlite3` (WAL, FTS5) · vanilla-JS static PWA (no bundler, no framework) · pystray tray · Windows-first, no Docker. Visual identity and UI components come from the fleet design system (`project-scaffolding`'s vendored components, byte-for-byte — see `.fleet.toml` `[vendored]`).

## Quick start (Windows)

```powershell
git clone https://github.com/ferraroroberto/task-os E:\automation\task-os
cd E:\automation\task-os
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config\config.sample.json config\config.json      # then edit paths for this machine

tray.bat            # tray icon → owns the webapp on :8448 (HTTPS once a cert exists — see "Phone access & auth")
```

Left-click the tray icon (or **Open task-os**) to open the app; **Copy URL** puts the same address on the clipboard for the phone. `tray.bat` is idempotent — a second run is a no-op while a tray is up. Without the tray: `webapp.bat` runs uvicorn in the foreground.

From a terminal, `tasks.bat` (put the repo on `PATH` or alias it) is the CLI — it works whether or not the app is running:

```powershell
tasks add "Renew passport" --due fri
tasks add "Book appointment" --parent 1
tasks comment 2 "called the office"
tasks tree
tasks due 2 2026-09-01
tasks show 2            # activity log shows due: ∅ → 2026-09-01
tasks mirror status     # markdown mirror + backup: enabled? where? last export / import
```

Playwright browsers for the e2e suite: `& .\.venv\Scripts\python.exe -m playwright install chromium webkit` (once).

## Views

PC-first and full-width; the phone gets the same views as an adaptive second rendering (bottom pill, table as cards, drawer as a full-screen sheet).

- **Board** — five status columns over `/api/board`: **Inbox · Todo · Doing · Standby · Done today** (done today = completed on the current local day; older done tasks never show). On a wide screen (≥ 1024 px) all five sit side by side using the full width, each scrolling on its own under a sticky header with its count; on the phone the columns are a one-column scroll-snap carousel and the count strip above doubles as the column switcher (the fleet launcher's board layout, ported). Cards show the project (top ancestor) line, person, title, due (relative, overdue in the danger tone), priority marker, repeat glyph, folder / issue chips, children count and the last comment. Click a card to open the drawer; **drag a card onto another column** to change its status (`PATCH`, an activity row, a toast on error) — on a touch device each card carries a status select instead. The filter row (project · person · text) is shared with the Table and encoded in the URL (`?project=12`); the status / due / sort filters stay Table-only.
- **Today** — open tasks due ≤ today (overdue first, then today) grouped by root project, recurring tasks first inside each group; each row: a checkbox to mark done (a recurring task rolls its due one cadence forward instead of closing — toast `Done — next: <date>`), title, breadcrumb, due badge, person. **Later this week** (tomorrow … +7 days) sits collapsed below. This is the phone's landing tab: on a first visit a touch device opens on Today, the desktop on the Board (the last tab is remembered after that).
- **Table** — one full-width grid over `/api/tasks`: code · title (breadcrumb `Parent › Child` under it) · due (relative, ISO on hover, overdue in the danger tone) · status (inline select) · priority · person · project (the top ancestor) · folder chip · last comment (links rendered as chips) · next action. The filter bar (status chips, project, person, due window, text, sort) **is the URL** — `?status=doing&project=12` is a shareable, bookmarkable view; the default is open tasks. Click the due cell to edit it inline: type a natural phrase (`tomorrow`, `fri`, `in 2 weeks`) or pick a date. Row click / Enter opens the drawer.
- **Tree** — the whole hierarchy as an outliner: indent = nesting, collapse/expand persists, every node with children carries a **project** chip and a rollup (open descendants, nearest due). Drag a row onto another to re-parent it (`POST /api/tasks/{id}/move`; a cycle is refused with a toast); drop on the dashed zone at the bottom to move to the top level. Keyboard: ↑/↓ walk, →/← expand/collapse, Enter opens.
- **Task drawer** — a right-hand side panel on desktop (≥ 1024 px, the list stays visible beside it), full-screen on the phone; deep-linkable as `#task/42`. Breadcrumb (clickable) → editable title → fields (status, priority, due, repeat, person, code) → description (markdown, edit/preview) → links (add/remove) → comments newest-first with URLs / `{folder}` refs / `repo#N` as clickable chips + a composer (Ctrl+Enter sends, `origin = ui`) → activity log (`field old → new · actor · time`) → children (click to navigate, add child) → issue panel (placeholder until Step 8).
- **Quick-add** — the `+ Add task…` bar at the top of Board / Table / Tree. One line of natural language, parsed server-side by `POST /api/parse` (so the CLI and the UI agree) and previewed as chips before you press Enter:

  | You type | Result |
  | --- | --- |
  | `renew passport next friday` | title `renew passport`, due = next Friday |
  | `pay water bill by tomorrow` · `… on fri` · `… in 2 weeks` | trailing date phrase (optional `on` / `by` / `due` lead-in) — every phrase `src/dates.py` knows |
  | `order sensor #12` | nested under task 12 |
  | `order sensor › garden-bot` (or `> garden-bot`) | nested under the open task whose title matches (exact title wins, then a task that already has children) |
  | `fix tap › Bathroom tomorrow` | parent **and** date |

  A parent that matches nothing shows as a red chip and nothing is created. Enter creates the task and focuses its row.

## Layout

```
launcher.py               entrypoint: `tray` (default) | `webapp`
tray.bat / webapp.bat     tray lifecycle (from the fleet template) / foreground dev server
tasks.bat                 the `tasks` CLI (→ python -m src.cli)
app/webapp/               FastAPI app: server.py (create_app, CachingStaticFiles, AuthMiddleware, JSON error envelope),
                          event_loop.py, manager.py (adopt-or-spawn uvicorn; cert --check → --ssl-* when a cert exists)
app/webapp/routers/       misc (shell, /healthz, /api/version) · auth (/login, /api/login|logout) · tasks (/api/tasks…,
                          /api/activity) · people · search · views (/api/board, /api/today)
                          · mirror (/api/status — install status incl. https + auth, /api/mirror/export|import, /api/backup)
app/webapp/static/        the PWA: index.html, login.html, styles.css (fleet tokens), app.js (state + routing), board.js,
                          table.js, tree.js, today.js, drawer.js, quickadd.js, format.js, api.js, toast.js, manifest, icons/, _vendored/
app/tray/                 tray.py + vendored single_instance.py / watchdog.py
src/                      schema.py (versioned migrations) · db.py (get_db, WAL) · tasks_repo.py (domain rules + write hooks)
                          dates.py (natural dates, recurrence) · quick_add.py (one-line parser) · cli.py · config.py
                          mirror.py (markdown mirror: export / watcher import) · backup.py (dated .db copies, daily job)
                          auth.py (loopback owner · bearer / cookie gate) · certs.py (cert pair, auto-renew hook)
                          logger.py · static_versioning.py
scripts/                  verify-before-ship.ps1, classify_e2e.py, gen_icons.py, import_notion.py (+ .bat),
                          gen_tailscale_cert.py (vendored from the scaffold), gen_token.py, set_password.py
tests/                    unit (hermetic) + fixtures/seed.py (synthetic dataset) + e2e/ (Playwright, one story test per step)
docs/                     validation.md (the story record) + screenshots/ + architecture.mmd
config/                   config.sample.json (committed) → config.json (yours, gitignored)
brand/ assets/            Lucide list-checks master → favicon / touch icons / tray .ico
data/                     tasks.db, logs, avatars, backups — gitignored, never committed
webapp/                   certificates/{cert,key}.pem (the Tailscale leaf), watchdog.log — gitignored
```

## Configuration — `config/config.json`

| Key | Meaning |
| --- | --- |
| `site` | `home` or a second site name — selects nothing yet; later steps key providers on it |
| `port` | webapp port (default **8448**) |
| `issues` | `provider` (`github`/`gitlab`), `owner`, `assignee`, `sync_minutes` — Step 8 |
| `placeholders` | `{onedrive}`, `{user}`, … expanded in folder refs per machine — Step 9 |
| `mirror` | `dir` — the markdown mirror folder (one `.md` per task); `backup_dir` — where the dated `.db` copies go. Both take `{placeholders}`; either blank / unresolved / with a missing parent folder = that service off, with the reason in `/api/status` and `tasks mirror status`. See [Markdown mirror](#markdown-mirror) and [Backups](#backups) |
| `search` | folder roots + email index path for federated search — Step 10 |
| `team` | shared install for a small team: `enabled`, `people` — Step 12 |
| `auth` | `token` (the bearer secret `scripts/gen_token.py` writes) · `password_hash` (optional, `scripts/set_password.py`). Both empty in the sample = only this PC can use the app |

Secrets (the Notion token for the one-shot import — `NOTION_API_TOKEN`, optionally `NOTION_TASKS_DB_ID`) go in `.env` (or any dotenv passed with `--env-file`), never in config. `TASKOS_CONFIG_PATH` / `TASKOS_DB_PATH` env vars override the config/db location (the test harness uses them for isolation).

## Data model

One SQLite file (`data/tasks.db`, WAL, FTS5), migrated by `src/schema.py` (`settings.schema_version`, currently **4**):

`tasks(id, parent_id, code, title, type task|coding|note, status inbox|todo|doing|standby|done|cancelled, priority high|medium|low|none, due, recurrence daily|weekly|monthly|quarterly|yearly, description, folder_ref, next_action, person_id, created_by, created_at, updated_at, done_at, external_id)` · `links(task_id, url, label, kind web|folder|email|issue)` · `comments(task_id, author, ts, body, origin ui|cli|md|notion|import|sync, external_id)` · `activity(task_id, ts, actor, field, old_value, new_value)` · `people(name, email, avatar_path, external_id)` · `issue_refs(task_id, provider, repo, number, state, url, last_synced)` · `mirror_state(task_id, path, exported_at, file_mtime_ns, content_hash)` (v4 — what the markdown mirror last wrote per task) · `tasks_fts` + `comments_fts` (FTS5, trigger-synced).

Rules the repo layer enforces (`src/tasks_repo.py`): a task with children **is** a project (the `project` filter means "descendant of"); `move` refuses cycles; every due / status / parent / priority (and title, type, recurrence, person, description) change writes an `activity` row; `done` on a recurring task rolls the **same** task's due one cadence forward from its due date (month-end clamps) and logs the completion, otherwise it sets `done` + `done_at`; `type = coding` **iff** an `issue_refs` row exists (attach an issue to make a task coding — setting the type by hand is rejected); deleting a task deletes its subtree.

## API

All under `/api/`, JSON in and out; errors are one envelope everywhere: `{"error": {"code", "message", "detail"?}}` (404 `not_found`, 422 `validation_error`, 409 `cycle`). The actor recorded on activity/comments is the body's `actor`/`author`, else the `X-Actor` header, else the first `team.people` entry in config.

| Method · path | What |
| --- | --- |
| `GET /api/version` | `{git_sha, built_at, asset_hash, schema_version}` — the build-identity contract the restart recipe checks |
| `GET /api/tasks?status=&parent=&project=&due=&due_from=&due_to=&type=&person=&q=&include_closed=&limit=` | filtered flat list (summaries with `child_count`, `is_project`, `issue_ref`, `person`, `breadcrumb`, `root` = top ancestor, `last_comment`). `status` repeatable/comma (`open` = not done/cancelled — the default); `parent=root`; `project` = descendant-of; `due` = `today` · `week` · `overdue` · a date |
| `POST /api/tasks` | create → 201 (`title` + any task field; `due` accepts the natural phrases below, `""` clears) |
| `GET /api/tasks/tree?root=&include_closed=` | nested forest (`children`, `depth`); closed leaves pruned by default |
| `GET /api/tasks/{id}` | detail: task + `breadcrumb`, `children`, `links`, `comments` (thread order), `activity` (newest first) |
| `PATCH /api/tasks/{id}` · `DELETE /api/tasks/{id}` | partial update (fields present only; `parent_id` goes through the cycle guard; `due` natural or ISO) · delete subtree |
| `POST /api/tasks/{id}/move` `{parent_id\|null}` · `POST /api/tasks/{id}/done` | re-parent · complete (recurring → roll) |
| `GET/POST /api/tasks/{id}/comments` `{body, origin?, author?}` | thread · add → 201 |
| `GET/POST /api/tasks/{id}/links` `{url, label?, kind?}` · `DELETE …/links/{lid}` | links |
| `PUT /api/tasks/{id}/issue` `{provider?, repo, number, url?, state?}` · `DELETE …/issue` | attach (→ `coding`) · detach (→ `task`) |
| `GET /api/activity?task=&limit=` | activity log, newest first (all tasks when no `task`) |
| `POST /api/parse` `{text, today?}` | quick-add split → `{title, due, due_phrase, parent_ref, parent}` (`parent` resolved to `{id, title}` or `null`) |
| `GET/POST /api/people` · `GET/PATCH/DELETE /api/people/{id}` | people CRUD (`open_tasks` count included) |
| `GET /api/board?project=&person=&q=` | `{today, columns: {inbox, todo, doing, standby, done}}` — the Board's buckets, same enriched summaries as the list; `done` = completed on the current local day only |
| `GET /api/today?person=` | `{today, due: [{root, items}], week: [{root, items}], counts: {overdue, today, week}}` — open tasks due ≤ today grouped by root project (recurring first inside a group), plus tomorrow … +7 days in the same shape |
| `GET /api/search?q=&limit=` | full text over title / description / comment bodies → hits with `snippet` (`[match]`), `matched_in`, `breadcrumb` |
| `GET /api/status` | `{https, auth: {enabled, password, client}, mirror: {enabled, dir, files, last_export, last_import, errors, error_files, watching, …}, backup: {enabled, dir, last_file, next_run, last_error, …}}` — how this request came in (`client`: `loopback` · `token` · `public`) and what the install accepts; a disabled service carries its `reason` |
| `POST /api/mirror/export` · `POST /api/mirror/import` · `POST /api/backup` | run a full export / one watcher pass / one backup now (409 `mirror_disabled` / `backup_disabled` when not configured) |
| `POST /api/login` `{secret}` · `POST /api/logout` | token or password → the 90-day `taskos_token` cookie · clear it |

Also `GET /` shell · `GET /login` sign-in page · `GET /healthz` liveness. Every `/api/` route except `/api/version` and `/api/login` needs the caller to be loopback or to carry the token (see "Phone access & auth").

## CLI — `tasks`

`tasks.bat` at the repo root runs `src/cli.py` in the venv. It talks to the running app over HTTP when `:8448` answers (`--server URL` / `TASKOS_URL` to point elsewhere) and falls back to opening the database directly when the app is down (`--local` forces that). `--json` on every command prints the same shapes the API returns; `--actor NAME` sets who is acting; `-v` says which backend answered.

```
tasks add "title" [--parent N] [--due <date>] [--priority high|medium|low|none]
                  [--recurrence daily|weekly|monthly|quarterly|yearly] [--person id|name] [--desc "…"]
tasks ls [--status todo,doing | open | all] [--project N] [--due today|week|overdue] [--person id|name]
tasks show N               detail with breadcrumb, children, links, comments, activity (old → new)
tasks tree [N]             nested view (everything, or N's subtree)
tasks comment N "text"     origin = cli
tasks due N <date>         "none" clears
tasks done N               recurring tasks roll forward and stay open
tasks move N --parent M    M = root for top level; cycles are refused
tasks search "q"           full text incl. comments, with the matched snippet
tasks people
tasks mirror [export|import|status]   markdown mirror: full export · one watcher pass · status (default)
tasks backup               copy the database to mirror.backup_dir now (tasks-YYYYMMDD.db)
```

Dates (`--due`, `due` — and the API's `due` field, and quick-add) accept natural phrases via `src/dates.py`: `today`, `tomorrow`, `fri` (the coming Friday — today if it is Friday), `next friday` (+7), `next week|month|year`, `in 3 days`, `in 2 weeks`, `2w`, `+10d`, and ISO `YYYY-MM-DD`. Anything else is an error, never a silently unset date. Exit codes: 0 ok · 1 error (stderr, or the JSON error envelope with `--json`) · 2 usage.

## Markdown mirror

The database is canonical; the mirror is a folder with **one `.md` per task** — `<mirror.dir>/<id:04d>-<slug>.md` — that a human, an editor, `grep` or an LLM can read and edit, and that a sync client (OneDrive, a shared drive) can carry to another machine. Point `mirror.dir` in `config/config.json` at a folder whose parent exists (`{onedrive}/task-os/mirror` with `placeholders.onedrive` set — create `{onedrive}/task-os` once; the leaf is created for you) and restart: the app exports every task on startup, then keeps the folder current.

```markdown
---
id: 3
external_id: null
parent: 2
title: Get three quotes
code: null
type: task
status: doing
priority: none
due: 2026-08-20
recurrence: null
person: Sam Rivera
folder_ref: null
next_action: null
links:
  - url: https://example.com/quotes/1
    label: null
    kind: web
created_at: 2026-07-18T00:03:00+02:00
updated_at: 2026-07-18T00:47:00+02:00
done_at: null
exported_at: 2026-08-17T11:12:03+02:00
---

## Description

Markdown, free.

## Comments

- 2026-07-18T00:45:00+02:00 · Sam Rivera · ui: First quote in: https://example.com/quotes/1 — a bit high.
- 2026-07-18T00:47:00+02:00 · Alex Chen · ui: Plans are in {onedrive}/house/kitchen/plans

## Log

- 2026-07-18T00:03:00+02:00 · seed · created: ∅ → Get three quotes
```

**Export** runs in full on startup and on `tasks mirror export`, and **debounced (~1 s) after every write** through the repo layer's write hook — API, CLI and importers alike — for the touched tasks only. Output is deterministic (same DB state → byte-identical file; an unchanged task is not rewritten, so a synced folder does not churn); a title change renames the file (the id prefix keeps it findable), a deleted task removes it. `mirror_state` (schema v4) records what was written per task: path, `exported_at`, the file's mtime, a content hash.

**Import** — a watcher polls the folder's mtimes every 2 s (stdlib, no extra dependency; also on startup, so edits made while the app was down are picked up before the export) and, for a file that changed since it was written:

- **frontmatter fields** `title`, `code`, `status`, `priority`, `due` (ISO or a natural phrase — `tomorrow`, `next friday`), `recurrence`, `person` (by name), `folder_ref`, `next_action`, `parent` (id; the cycle guard applies) and the **`## Description`** body are applied through the same repo layer as the UI, with **actor `md`** — every change lands in the activity log like any other;
- **new lines under `## Comments`** become comments with `origin = md`: a bare `- your text` (author = the first `team.people` entry, time = now) or a full `- <ISO ts> · <author> · md: text` line; a body may continue on lines indented by two spaces. Comments are **append-only** — a deleted line is not a deletion, an edited existing line reads as a new comment (the original stays);
- `id`, `external_id`, `type` (derived from the issue link), `links`, the timestamps, `## Log` and any unknown section are read-only / ignored.

After a successful import the file is **re-exported**, so it always converges to the canonical form above (your `due: tomorrow` becomes the ISO date, your bare comment line gains its timestamp and author).

**Conflict policy** — per field: if the database changed that field *after* the file was written (the latest `activity` row for the field is newer than the file's `exported_at`), **the database wins** and the rejected file value is kept as a comment `origin = md`: `import conflict on due: file said 2026-10-10, kept 2026-11-11`. A value the rules refuse (an unknown status or person, a parent that would make a cycle) is recorded the same way — `import rejected on status: file said later (…), kept todo`. Nothing is silently lost, and the file converges to the value that won.

**Failure mode** — a file that does not parse (broken frontmatter, no integer `id`) is **skipped**: one warning in the log per changed version, the file counted under `errors` / `error_files` in `/api/status`, `tasks mirror status` and the Settings tab; the app never crashes on a bad file, and fixing the file is picked up on the next tick. A file in the folder that matches no task is left alone. Not configured (blank `mirror.dir`, an unresolved `{placeholder}`, a missing parent folder) is a **visible** state — the reason is logged at startup and shown in the same three places — never a silent no-op.

## Backups

`src/backup.py` copies `data/tasks.db` to `<mirror.backup_dir>/tasks-YYYYMMDD.db` with SQLite's online backup API (a consistent snapshot while the app keeps writing under WAL), via a temp file + atomic rename, and keeps the **newest 30** dated copies. Two ways to run it:

- **In-app (default):** the webapp runs it **daily at 03:00 local** while it is up, plus once at startup when today's copy is missing (a PC that was off at 03:00 still gets one). Status — last file, next run, last error — in `/api/status` and the Settings tab; `POST /api/backup` runs one now.
- **From a scheduler:** `tasks backup` does the same from the terminal (over HTTP when the app is up, else against the file directly) — put `E:utomation	ask-os	asks.bat backup` in Windows Task Scheduler / an app-launcher job if you would rather not depend on the app being up at 03:00; the pruning keeps both paths at 30 files.

Point `mirror.backup_dir` at a synced folder (`{onedrive}/task-os/backup`); the database itself stays out of the sync client by design — only the mirror and the dated copies travel.

## Importing from Notion

`scripts/import_notion.py` (`scripts\import_notion.bat`) is a one-shot, idempotent importer for a Notion tasks database — the way an existing Notion list becomes the master list here. It reads every page with its comments, body blocks and people relation over the Notion REST API (stdlib `urllib`, no SDK), maps them onto the schema and writes through the same `src/tasks_repo.py` layer the API uses.

```powershell
# token: NOTION_API_TOKEN in the OS env or a dotenv file (--env-file, default ./.env)
# database id: --database-id, or NOTION_TASKS_DB_ID in the env / env-file
scripts\import_notion.bat --dry-run --database-id <id> --env-file E:\path\.env    # report only, writes nothing
scripts\import_notion.bat --database-id <id> --env-file E:\path\.env              # import into data\tasks.db
scripts\import_notion.bat --database-id <id> --env-file … --limit 20 --json-dump E:\tmp\export.json   # smoke + keep the raw export
scripts\import_notion.bat --from-json E:\tmp\export.json --db E:\tmp\other.db     # replay a saved export, no API call
```

| Notion | task-os |
| --- | --- |
| `status` not started · In progress · Done | `todo` · `doing` · `done` (+ `done_at` = page `last_edited_time`) |
| `status` empty | `todo` — or `inbox` when `priority` = inbox |
| `priority` high · medium · low · backlog · inbox | `high` · `medium` · `low` · `none` · `none` |
| `recurrent` daily · weekly · monthly · three months · yearly | `daily` · `weekly` · `monthly` · `quarterly` · `yearly` |
| `Date.start` | `due` (date part) |
| `link` | `links` (`kind = web`) |
| page body (paragraph, headings, lists, to-do, quote, code, table, image, divider; nested children) | `description` as markdown — unknown block types degrade to their text |
| comments | `comments` (`author` = the commenter's display name, `ts` = original time, `origin = notion`) in created order |
| first `connection` relation | `people` row (`external_id` = the person's page id) + `person_id` |
| further relations | a comment `also linked: <name>` |
| `created_time` / `last_edited_time` | `created_at` / `updated_at` |

Idempotent on the Notion ids: `tasks.external_id` and `comments.external_id` (schema v3), `people.external_id`. A re-run updates the fields that changed in Notion (logged per field like any other change) and never duplicates a task, comment, link or person; an identical page touches nothing. The first import writes **one** activity row per task (`actor = notion-import`, `field = imported`). `--dry-run` prints the report — counts per status / priority / recurrence, comments, people, anything unmapped or skipped, and what a write would create / update / leave alone — and writes nothing, not even the migration. Unmapped select values are counted and fall back to the default (never dropped silently). The running app picks the new schema up on its next restart (`tray.bat --restart`).

## Fixture data

`tests/fixtures/seed.py` is the **only** dataset allowed in tests, e2e runs and screenshots (the repo is public): a deterministic synthetic set — four projects nested to depth 3, ~40 tasks, three people, comments with web / folder / issue links, activity, recurring, done and cancelled tasks, one `coding` task. `python -m tests.fixtures.seed --db E:/tmp/tasks.db --reset [--anchor YYYY-MM-DD]` seeds a file; point `TASKOS_DB_PATH` at it (or `TASKOS_URL` at a disposable instance) to drive the CLI or the app against it. Never a real import.

## Verify, restart, prove

```powershell
& .\scripts\verify-before-ship.ps1     # byte-compile → ruff → pytest → routed e2e (disposable instance)
tray.bat --restart                     # orphan-proof reclaim-then-start; verifies /api/version git_sha == HEAD
```

The e2e suite boots its own disposable webapp on a free port with a temp DB; it never touches the live `:8448`. `TASKOS_E2E_LIVE=1` runs it read-only against the live instance instead. Screenshots the story tests save under `docs/screenshots/` are the on-screen proof linked from `docs/validation.md`.

## Phone access & auth

The phone reaches the same app over **Tailscale**, as an installed PWA. Three pieces, all optional for a PC-only install:

**1. HTTPS — a real certificate for the tailnet name.** Once per tailnet, enable *HTTPS Certificates* in the Tailscale admin console (DNS page). Then, on the host:

```powershell
& .\.venv\Scripts\python.exe scripts\gen_tailscale_cert.py     # tailscale cert → webapp/certificates/{cert,key}.pem
tray.bat --restart
```

`gen_tailscale_cert.py` (vendored verbatim from `project-scaffolding`) detects this machine's MagicDNS name and asks `tailscale cert` for a Let's Encrypt leaf — trusted by every device on the tailnet, **zero per-device trust steps**. With the pair present the launcher (the tray's `manager.py`, `launcher.py webapp`, `webapp.bat` — all agree) serves **`https://<your-host>.ts.net:8448`**; without it the app serves plain HTTP and says so loudly in the log and in `GET /api/status` (`https: false`). The leaf lives ~90 days: every launcher runs `gen_tailscale_cert.py --check` **before uvicorn binds**, which renews a `.ts.net` cert expiring within ~30 days and never blocks a start. `localhost` is not in the cert — the tray's **Open task-os** / **Copy URL** use the `.ts.net` name (it resolves on the host too), the restart probe uses loopback and skips verification.

**2. Who may call the API.** Loopback (this PC — the browser on it, the tray, the `tasks` CLI, the restart probe) is the owner and needs nothing. **Any other client must present the bearer token**, either as `Authorization: Bearer <token>` (scripts, an LLM on another machine) or as the `taskos_token` cookie the sign-in page sets. With no token configured — the committed sample — the gate is **closed**: non-loopback gets `401` on `/api/*` and is sent to `/login`, which explains what to run.

```powershell
& .\.venv\Scripts\python.exe scripts\gen_token.py                # writes auth.token into config/config.json (created from the sample if missing)
& .\.venv\Scripts\python.exe scripts\set_password.py <password>  # optional: a memorable secret to type instead (PBKDF2 hash stored, never the password)
tray.bat --restart                                               # config is read at startup
```

`gen_token.py --force` rotates the token and signs every device out at once (the cookie *is* the token); `--clear` goes back to loopback-only. `set_password.py --clear` removes the password. Failed and successful sign-ins are logged with the client address in `data/logs/task-os.log`.

**3. Sign in and install.** On the phone (Tailscale connected) open `https://<your-host>.ts.net:8448` → the sign-in card → paste the token or type the password → this device stays signed in for **90 days** (HttpOnly cookie, `Secure` over HTTPS). Then:

- **iOS (Safari):** Share → **Add to Home Screen** — the app launches full-screen (`display: standalone`), lands on **Today**, keeps the bottom pill above the home indicator.
- **Android (Chrome):** page menu → **Install app**.

Settings → **Phone access** shows what this connection is (`this PC` · `signed in`), whether HTTPS and the token are on, and a **Sign out on this device** button when signed in with the cookie.

**What stays public** on any client: the static assets under `/static/` (the manifest and icons a phone needs before it can sign in), `/healthz`, `/api/version` (the build-identity contract), the `/login` page and `/api/login` itself. Everything else under `/api/` is gated; a page request from a signed-out phone redirects to `/login?next=…` and comes back where it started.

## Roadmap

Issue #1 in this repo lists the 13 steps (home v1 → integrations → a second site with a small team). Each step closes with its automated story test, on-screen screenshots and a `docs/validation.md` entry.
