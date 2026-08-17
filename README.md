# task-os

A personal, open-source task manager: one master list for everything, self-hosted on your own PC. Nested tasks that become projects by having children, comments with clickable links, an activity log, local-folder links that resolve per machine, GitHub/GitLab issues as first-class tasks, and one search box over tasks, folders, emails and issues. PC-first and full-width; the phone gets the same views as an installable PWA over Tailscale; an LLM reaches it through a CLI, a JSON API and a markdown mirror.

Built step by step — each step is a GitHub issue with a user story that is proven on screen before it closes ([`docs/validation.md`](docs/validation.md)). Shipped so far: **Step 1** the shell, **Step 2** the core — SQLite schema, JSON API and the `tasks` CLI. Internal map: [`docs/architecture.mmd`](docs/architecture.mmd).

## Stack

Python 3.14 · FastAPI + uvicorn · stdlib `sqlite3` (WAL, FTS5) · vanilla-JS static PWA (no bundler, no framework) · pystray tray · Windows-first, no Docker. Visual identity and UI components come from the fleet design system (`project-scaffolding`'s vendored components, byte-for-byte — see `.fleet.toml` `[vendored]`).

## Quick start (Windows)

```powershell
git clone https://github.com/ferraroroberto/task-os E:\automation\task-os
cd E:\automation\task-os
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config\config.sample.json config\config.json      # then edit paths for this machine

tray.bat            # tray icon → owns the webapp on http://127.0.0.1:8448
```

Left-click the tray icon (or **Open task-os**) to open the app. `tray.bat` is idempotent — a second run is a no-op while a tray is up. Without the tray: `webapp.bat` runs uvicorn in the foreground.

From a terminal, `tasks.bat` (put the repo on `PATH` or alias it) is the CLI — it works whether or not the app is running:

```powershell
tasks add "Renew passport" --due fri
tasks add "Book appointment" --parent 1
tasks comment 2 "called the office"
tasks tree
tasks due 2 2026-09-01
tasks show 2            # activity log shows due: ∅ → 2026-09-01
```

Playwright browsers for the e2e suite: `& .\.venv\Scripts\python.exe -m playwright install chromium webkit` (once).

## Layout

```
launcher.py               entrypoint: `tray` (default) | `webapp`
tray.bat / webapp.bat     tray lifecycle (from the fleet template) / foreground dev server
tasks.bat                 the `tasks` CLI (→ python -m src.cli)
app/webapp/               FastAPI app: server.py (create_app, CachingStaticFiles, JSON error envelope), event_loop.py, manager.py
app/webapp/routers/       misc (shell, /healthz, /api/version) · tasks (/api/tasks…, /api/activity) · people · search
app/webapp/static/        the PWA: index.html, styles.css (fleet tokens), app.js, manifest, icons/, _vendored/
app/tray/                 tray.py + vendored single_instance.py / watchdog.py
src/                      schema.py (versioned migrations) · db.py (get_db, WAL) · tasks_repo.py (domain rules)
                          dates.py (natural dates, recurrence) · cli.py · config.py · logger.py · static_versioning.py
scripts/                  verify-before-ship.ps1, classify_e2e.py, gen_icons.py
tests/                    unit (hermetic) + fixtures/seed.py (synthetic dataset) + e2e/ (Playwright, one story test per step)
docs/                     validation.md (the story record) + screenshots/ + architecture.mmd
config/                   config.sample.json (committed) → config.json (yours, gitignored)
brand/ assets/            Lucide list-checks master → favicon / touch icons / tray .ico
data/                     tasks.db, logs, avatars, backups — gitignored, never committed
```

## Configuration — `config/config.json`

| Key | Meaning |
| --- | --- |
| `site` | `home` or a second site name — selects nothing yet; later steps key providers on it |
| `port` | webapp port (default **8448**) |
| `issues` | `provider` (`github`/`gitlab`), `owner`, `assignee`, `sync_minutes` — Step 8 |
| `placeholders` | `{onedrive}`, `{user}`, … expanded in folder refs per machine — Step 9 |
| `mirror` | markdown mirror dir + nightly backup dir — Step 6 |
| `search` | folder roots + email index path for federated search — Step 10 |
| `team` | shared install for a small team: `enabled`, `people` — Step 12 |

Secrets (a Notion token for the one-shot import) go in `.env`, never in config. `TASKOS_CONFIG_PATH` / `TASKOS_DB_PATH` env vars override the config/db location (the test harness uses them for isolation).

## Data model

One SQLite file (`data/tasks.db`, WAL, FTS5), migrated by `src/schema.py` (`settings.schema_version`, currently **2**):

`tasks(id, parent_id, code, title, type task|coding|note, status inbox|todo|doing|standby|done|cancelled, priority high|medium|low|none, due, recurrence daily|weekly|monthly|quarterly|yearly, description, folder_ref, next_action, person_id, created_by, created_at, updated_at, done_at)` · `links(task_id, url, label, kind web|folder|email|issue)` · `comments(task_id, author, ts, body, origin ui|cli|md|notion|import|sync)` · `activity(task_id, ts, actor, field, old_value, new_value)` · `people(name, email, avatar_path, external_id)` · `issue_refs(task_id, provider, repo, number, state, url, last_synced)` · `tasks_fts` + `comments_fts` (FTS5, trigger-synced).

Rules the repo layer enforces (`src/tasks_repo.py`): a task with children **is** a project (the `project` filter means "descendant of"); `move` refuses cycles; every due / status / parent / priority (and title, type, recurrence, person, description) change writes an `activity` row; `done` on a recurring task rolls the **same** task's due one cadence forward from its due date (month-end clamps) and logs the completion, otherwise it sets `done` + `done_at`; `type = coding` **iff** an `issue_refs` row exists (attach an issue to make a task coding — setting the type by hand is rejected); deleting a task deletes its subtree.

## API

All under `/api/`, JSON in and out; errors are one envelope everywhere: `{"error": {"code", "message", "detail"?}}` (404 `not_found`, 422 `validation_error`, 409 `cycle`). The actor recorded on activity/comments is the body's `actor`/`author`, else the `X-Actor` header, else the first `team.people` entry in config.

| Method · path | What |
| --- | --- |
| `GET /api/version` | `{git_sha, built_at, asset_hash, schema_version}` — the build-identity contract the restart recipe checks |
| `GET /api/tasks?status=&parent=&project=&due=&due_from=&due_to=&type=&person=&q=&include_closed=&limit=` | filtered flat list (summaries with `child_count`, `is_project`, `issue_ref`, `person`). `status` repeatable/comma (`open` = not done/cancelled — the default); `parent=root`; `project` = descendant-of; `due` = `today` · `week` · `overdue` · a date |
| `POST /api/tasks` | create → 201 (`title` + any task field) |
| `GET /api/tasks/tree?root=&include_closed=` | nested forest (`children`, `depth`); closed leaves pruned by default |
| `GET /api/tasks/{id}` | detail: task + `breadcrumb`, `children`, `links`, `comments` (thread order), `activity` (newest first) |
| `PATCH /api/tasks/{id}` · `DELETE /api/tasks/{id}` | partial update (fields present only; `parent_id` goes through the cycle guard) · delete subtree |
| `POST /api/tasks/{id}/move` `{parent_id\|null}` · `POST /api/tasks/{id}/done` | re-parent · complete (recurring → roll) |
| `GET/POST /api/tasks/{id}/comments` `{body, origin?, author?}` | thread · add → 201 |
| `GET/POST /api/tasks/{id}/links` `{url, label?, kind?}` · `DELETE …/links/{lid}` | links |
| `PUT /api/tasks/{id}/issue` `{provider?, repo, number, url?, state?}` · `DELETE …/issue` | attach (→ `coding`) · detach (→ `task`) |
| `GET /api/activity?task=&limit=` | activity log, newest first (all tasks when no `task`) |
| `GET/POST /api/people` · `GET/PATCH/DELETE /api/people/{id}` | people CRUD (`open_tasks` count included) |
| `GET /api/search?q=&limit=` | full text over title / description / comment bodies → hits with `snippet` (`[match]`), `matched_in`, `breadcrumb` |

Also `GET /` shell · `GET /healthz` liveness.

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
```

Dates (`--due`, `due`) accept natural phrases via `src/dates.py`: `today`, `tomorrow`, `fri` (the coming Friday — today if it is Friday), `next friday` (+7), `next week|month|year`, `in 3 days`, `in 2 weeks`, `2w`, `+10d`, and ISO `YYYY-MM-DD`. Anything else is an error, never a silently unset date. Exit codes: 0 ok · 1 error (stderr, or the JSON error envelope with `--json`) · 2 usage.

## Fixture data

`tests/fixtures/seed.py` is the **only** dataset allowed in tests, e2e runs and screenshots (the repo is public): a deterministic synthetic set — four projects nested to depth 3, ~40 tasks, three people, comments with web / folder / issue links, activity, recurring, done and cancelled tasks, one `coding` task. `python -m tests.fixtures.seed --db E:/tmp/tasks.db --reset [--anchor YYYY-MM-DD]` seeds a file; point `TASKOS_DB_PATH` at it (or `TASKOS_URL` at a disposable instance) to drive the CLI or the app against it. Never a real import.

## Verify, restart, prove

```powershell
& .\scripts\verify-before-ship.ps1     # byte-compile → ruff → pytest → routed e2e (disposable instance)
tray.bat --restart                     # orphan-proof reclaim-then-start; verifies /api/version git_sha == HEAD
```

The e2e suite boots its own disposable webapp on a free port with a temp DB; it never touches the live `:8448`. `TASKOS_E2E_LIVE=1` runs it read-only against the live instance instead. Screenshots the story tests save under `docs/screenshots/` are the on-screen proof linked from `docs/validation.md`.

## Phone / PWA

Arrives with Step 7: Tailscale HTTPS certificate (`gen_tailscale_cert.py`), Add-to-Home-Screen install, phone-tuned Board carousel. Until then the app is plain HTTP on the LAN/loopback; the manifest + icons already ship.

## Roadmap

Issue #1 in this repo lists the 13 steps (home v1 → integrations → a second site with a small team). Each step closes with its automated story test, on-screen screenshots and a `docs/validation.md` entry.
