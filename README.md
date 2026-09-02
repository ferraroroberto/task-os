# task-os

A personal, open-source task manager: one master list for everything, self-hosted on your own PC. Nested tasks that become projects by having children, comments with clickable links, an activity log, local-folder links that resolve per machine, GitHub/GitLab issues as first-class tasks, and one search box over tasks, folders, emails and issues. PC-first and full-width; the phone gets the same views as an installable PWA over Tailscale; an LLM reaches it through a CLI, a JSON API and a markdown mirror.

Built step by step — each step is a GitHub issue with a user story that is proven on screen before it closes ([`docs/validation.md`](docs/validation.md)). Shipped so far: **Step 1** the shell, **Step 2** the core — SQLite schema, JSON API and the `tasks` CLI, **Step 3** the one-shot Notion importer, **Step 4** the PC-first views — Table, Tree, the task drawer and quick-add, **Step 5** the Board and Today views, **Step 6** the markdown mirror + nightly backup, **Step 7** phone access — Tailscale HTTPS, token / password sign-in, the installable PWA, **Step 8** GitHub issues as coding tasks, **Step 9** folders that open on any PC — placeholders, the `taskos://` opener, the folder index, **Step 10** federated search — one box over tasks, folders, emails and issues. Internal map: [`docs/architecture.mmd`](docs/architecture.mmd).

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

Left-click the tray icon (or **Open task-os**) to open the app; **Copy URL** puts the same address on the clipboard for the phone. `tray.bat` is idempotent — a second run is a no-op while a tray is up. Without the tray: `webapp.bat` runs uvicorn in the foreground (a thin wrapper over `launcher.py webapp`, so it serves on the configured `port`, not a hardcoded one).

From a terminal, `tasks.bat` (put the repo on `PATH` or alias it) is the CLI — it works whether or not the app is running:

```powershell
tasks add "Renew passport" --due fri
tasks add "Book appointment" --parent 1
tasks comment 2 "called the office"
tasks tree
tasks due 2 2026-09-01
tasks show 2            # activity log shows due: ∅ → 2026-09-01
tasks mirror status     # markdown mirror + backup: enabled? where? last export / import
tasks issues sync       # my open GitHub issues → coding tasks in To do; closed ones → done
tasks folders search kitchen   # the folder index (search.folder_roots) — refs you can paste on a task
```

Playwright browsers for the e2e suite: `& .\.venv\Scripts\python.exe -m playwright install chromium webkit` (once).

## Views

PC-first and full-width; the phone gets the same views as an adaptive second rendering (bottom pill, table as cards, drawer as a full-screen sheet).

- **One row, one filter card, every view** (#46) — Board, Table, Tree, Today and the Search tab's task hits are *renderings* of the same filtered list, drawn with the same row (`rows.js`): line 1 is the one-line ellipsized title with the **status select** right-aligned beside it (the one status control, on every row, mouse or touch); line 2 is the meta line — code (coding tasks) · project · due (relative, overdue in the danger tone) · priority marker · repeat glyph · folder chip · issue chip · children count · comment count (the drawer shows the comments, never the row) · person. **The date on that line is a control, not a label** (#107): click or tap it and the same picker the drawer's Due field opens comes up, so re-planning a task costs one gesture instead of opening the card and finding the field. It looks exactly as it did — only its tap area grew, and it, the folder chip and the AI chip are laid out so no two of their touch areas overlap. Flat hairlines between rows, no card boxes. Above every view sits a **top strip** — the live **text filter**, always on screen because it is the one reached for most, and the quick-add `+` (#80) — and under it the same **filter card** (`filters.js`), collapsed by default with its state spelled out on the summary line (`doing · Home renovation · sorted by due date · 12 tasks`): project, **person (multi-select — one click each, several allowed: *Anyone* / the name / *2 people*)**, due window, modified window (incl. its inverse — **untouched > 30/60/90 days**, the weekly stale pass: do it, defer it with a start date, or admit it's dead; any write counts as a touch, sync and mirror included, so a GitHub-synced task never looks stale), **status (multi-select, incl. `done` / `cancelled`, so finished items are findable)** and **sort**; on the phone the strip keeps the text box + `+` on one line and the card's controls sit two per line at equal widths (due · priority · last modified · created · title — the Tree's order comes from here too). The state **is the URL** — `?status=doing&project=12&sort=updated&updated=week` is the same shareable view on every tab; the default is open tasks (plus today's done tasks for the Board's last column).
- **Board** — the status columns: **Inbox · Todo · Doing · Standby · Done today** (done today = completed on the current local day; press the `done` pill to see all done tasks instead). On a wide screen (≥ 1024 px) the columns sit side by side using the full width, each scrolling on its own under a sticky header with its count; on the phone they are a one-column scroll-snap carousel and the count strip above doubles as the column switcher (the fleet launcher's board layout, ported). Flat regions split by 1px hairlines. Status pills hide the columns not selected. **Drag a row onto another column** to change its status (`PATCH`, an activity row, a toast on error) or use the row's select.
- **Select several tasks at once** (#81) — the checklist toggle in the Board's and the Table's top strip turns every card/row into a tick target (drag is off while it is on, and a tap on the phone selects rather than opening — the horizontal swipe still belongs to the Board's carousel). It is **one selection**: tick three cards on the Board, switch to the Table, and the same three are ticked there. With at least one ticked, the bulk bar takes the top strip over, on **one line** with every control at the strip's own square height — *N selected* · **set status** (`complete` included, so a recurring task in the selection rolls its due instead of closing, exactly as its own row select would) · **set due** (the native date picker; the natural phrases stay where you type — quick-add, the drawer, the CLI and the API) · ✕ to leave. One `POST /api/tasks/bulk` per action, applied through the same repo layer as a single-task edit, so every task gets its own activity row. A task that fails — deleted in another tab, say — is **named in the toast** (`1 updated · 1 failed (#36: …)`), never dropped in silence; Escape leaves Select mode.
- **One key per action** (#99) — with a row focused, `e` completes, `1`–`4` set the status, `t` / `w` set the due date, `s` snoozes, `p` cycles priority, `z` undoes, `?` lists them; with tasks ticked the same key acts on the whole selection. See [Keyboard triage](#keyboard-triage).
- **Today** — tasks due ≤ today (overdue first, then today) grouped by root project, recurring tasks first inside each group, the same rows (status changed through the select — a recurring task also gets a **complete** option that rolls its due one cadence forward instead of closing; **done** always closes for good, recurring or not); group titles in the app's normal title font, a flat heading line with the overdue / due-today counts. Each row also carries the **snooze** control — *Tomorrow · This weekend · Next week · Pick a date…* — which sets the task's start date and takes it off the list, with an Undo in the toast (see [Start dates & snooze](#start-dates--snooze)). **My plan** sits on top — the tasks committed to today, ordered, with the *n of m done* progress line and the plan-your-day banner when the plan is empty (see [Plan my day](#plan-my-day)); a task planned today lives there instead of in the due groups. **Later this week** (tomorrow … +7 days) sits collapsed below as a flat disclosure. This is the phone's landing tab: on a first visit a touch device opens on Today, the desktop on the Board (the last tab is remembered after that).
- **Table** — the same list as a flat full-width grid on a wide screen: code · title (breadcrumb `Parent › Child` under it) · due (relative, ISO on hover, overdue in the danger tone) · status (the same select) · priority · person · project (the top ancestor) · folder chip · last comment (links rendered as chips) · next action. Click the due cell and the date picker opens on the spot (#107) — pick a day and it is saved. Row click / Enter opens the drawer. In Select mode the grid grows a leading checkbox column of its own (the shared row's checkbox belongs to the phone rendering). Under 768 px the grid has no room, so the Table renders the shared rows — identical to the Board's.
- **Tree** — the whole hierarchy as an outliner: indent = nesting with a subtle guide line per depth, collapse/expand persists, every node with children carries a **project** chip and a rollup (open descendants, nearest due). Every level orders the same way: open before closed, then by due (none last), then title. On a fine pointer, drag a row onto another to re-parent it (`POST /api/tasks/{id}/move`; a cycle is refused with a toast) — a dashed top-level drop zone appears while a drag is live; on a touch device there is no drag at all: re-parent from the drawer's **Move to** field. Keyboard: ↑/↓ walk, →/← expand/collapse, Enter opens.
- **Task drawer** — a right-hand side panel on desktop (≥ 1024 px, the list stays visible beside it), full-screen on the phone; deep-linkable as `#task/42`. Breadcrumb (clickable) → editable title → fields (status, priority, due, starts, repeat, person, code, move-to — projects + top level, the re-parent path that needs no drag) → description (markdown, edit/preview) → links (add/remove; an AI-conversation URL is recognised and wears the bot chip — see [AI conversation links](#ai-conversation-links)) → comments newest-first with URLs / `{folder}` refs / `repo#N` as clickable chips + a composer (Ctrl+Enter sends, `origin = ui`) → activity log (`field old → new · actor · time`) → children (click to navigate, add child) → **issue panel**: the linked issue (provider glyph, `repo#N` chip, state pill, labels, last synced, *Sync now*, *Unlink*) or, for a plain task, *Create issue* (repo from the last-seen list or typed) and *Link existing* (`owner/repo#N` or the URL). See [Issues as tasks](#issues-as-tasks).
- **Search** — one box over four indexes (tasks · folders · emails · issues), results as one card per kind, full width; each row opens, attaches to the task in the drawer, or becomes a task. `Ctrl+K` / `⌘K` (or the ⌘ button in the header) opens the **command palette** from any tab: type to jump to a task, `>` for commands. See [Search everything](#search-everything).
- **Quick-add** — the `+` in every pane's top strip (Board / Table / Tree / Today) opens one dialog (#80): line 1 is natural language, parsed server-side by `POST /api/parse` (so the CLI and the UI agree) — the dates it finds land in the **Due** and **Starts** fields where you can still correct them, the parent shows as a chip. Under it sit the fields worth setting while the task is still in your head, all optional and empty by default (no date, status `inbox`): **description**, **due**, **starts**, **status**, **folder** (typed as a ref / an absolute path, or picked from the folder index — the same picker the drawer uses) and **one link** (url + label; its kind is classified the same way the drawer classifies a pasted link). `type · Enter` is still the whole fast path. Escape, the backdrop and the × discard the draft; Escape closes the folder picker first when it is open:

  | You type | Result |
  | --- | --- |
  | `renew passport next friday` | title `renew passport`, due = next Friday |
  | `pay water bill by tomorrow` · `… on fri` · `… in 2 weeks` | trailing date phrase (optional `on` / `by` / `due` lead-in) — every phrase `src/dates.py` knows |
| `renew insurance due oct 15 starts oct 1` | both dates off one line — `starts` needs its keyword, a bare trailing date is the due date ([Start dates & snooze](#start-dates--snooze)) |
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
app/webapp/routers/       misc (shell, /healthz, /api/version, /opener/opener.{cmd,ps1}) · auth (/login, /api/login|logout) · tasks
                          (/api/tasks…, /api/activity) · people · search · views (/api/board, /api/today)
                          · mirror (/api/status — install status incl. https + auth + folders + opener, /api/mirror/export|import,
                          GET/DELETE /api/mirror/events, /api/backup) · folders (/api/resolve, /api/folders/search, /api/folders/reindex)
                          · issues (/api/issues/status|sync, GET/POST /api/tasks/{id}/issue)
                          · search (/api/search — federated, /api/search/status)
app/webapp/static/        the PWA: index.html, login.html, styles.css (fleet tokens), app.js (state + routing), board.js,
                          table.js, tree.js, today.js, drawer.js, quickadd.js, search.js (the Search tab),
                          settings.js (the Settings tab), palette.js (Ctrl+K), format.js, api.js, toast.js,
                          manifest, icons/, _vendored/
app/tray/                 tray.py + vendored single_instance.py / watchdog.py
src/                      schema.py (versioned migrations) · db.py (get_db, WAL) · tasks_repo.py (domain rules + write hooks)
                          dates.py (natural dates, recurrence) · quick_add.py (one-line parser) · cli.py · config.py
                          mirror.py (markdown mirror: export / watcher import) · backup.py (dated .db copies, daily job)
                          auth.py (loopback owner · bearer / cookie gate) · certs.py (cert pair, auto-renew hook)
                          issues/ (IssueProvider contract · github.py via gh · fake.py for tests) · issue_sync.py (sync pass + scheduler)
                          placeholders.py (folder ref ↔ path) · folder_index.py (roots, index file, search) · opener.py
                          (install command / env template for Settings) · vendor/foldersearcher_core.py (verbatim)
                          search/ (federated search: base.py adapter contract · tasks / folders / emails / issues adapters ·
                          federated.py — concurrent, grouped, unconfigured = visible) · logger.py · static_versioning.py
opener/                   the per-PC folder opener: opener.ps1 (the registered launcher) · opener.cmd (the handler) · install.txt (one-line PowerShell
                          install / uninstall) · install_opener.py (same via winreg) · README.md
scripts/                  verify-before-ship.ps1, classify_e2e.py, gen_icons.py, import_notion.py (+ .bat),
                          gen_tailscale_cert.py (copy-to-adapt from the scaffold, not vendor-verbatim), gen_token.py, set_password.py
tests/                    unit (hermetic) + fixtures/seed.py (synthetic dataset) + fixtures/emails_fixture.py (a tiny synthetic
                          email-archiver index) + e2e/ (Playwright, one story test per step)
docs/                     validation.md (the story record) + screenshots/ + architecture.mmd
config/                   config.sample.json (committed) → config.json (yours, gitignored)
brand/ assets/            Lucide list-checks master → favicon / touch icons / tray .ico
data/                     tasks.db, folder_index.txt, logs, avatars, backups — gitignored, never committed
webapp/                   certificates/{cert,key}.pem (the Tailscale leaf), watchdog.log — gitignored
```

## Configuration — `config/config.json`

| Key | Meaning |
| --- | --- |
| `site` | `home` or a second site name — selects nothing yet; later steps key providers on it |
| `port` | webapp port (default **8448**) |
| `issues` | `provider` (`github`; `gitlab` arrives with Step 11; blank = off), `owner` (whose repos are searched), `assignee` (`@me`), `sync_minutes` (default 10). See [Issues as tasks](#issues-as-tasks) |
| `placeholders` | `onedrive`, `user`, and a `sharepoint` map (`{"docs": "E:/…"}` → `{sharepoint:docs}`) — what **this** server expands folder refs with for display; the opener on each PC expands the same tokens from its own environment. See [Folders that open on any PC](#folders-that-open-on-any-pc) |
| `web_roots` | optional cloud *web* equivalent per placeholder, same shape (`{"onedrive": "https://…", "sharepoint": {"docs": "https://…"}}`). A ref starting with a mapped token gets its provider **web URL** derived (root + the percent-encoded rest) as `folder_url` — the phone popover's **Open web link** — unless the task carries an explicit folder web link, which always wins. Empty (the sample) = no derivation. Only refs whose root has a web twin are covered |
| `mirror` | `dir` — the markdown mirror folder (one `.md` per task); `backup_dir` — where the dated `.db` copies go. Both take `{placeholders}`; either blank / unresolved / with a missing parent folder = that service off, with the reason in `/api/status` and `tasks mirror status`. See [Markdown mirror](#markdown-mirror) and [Backups](#backups) |
| `search` | `folder_roots` — placeholder-aware roots the folder index scans (`["{onedrive}/Documentos"]`; empty = index off, visibly); `email_db` — the [email-archiver](https://github.com/ferraroroberto/email-archiver) `emails.db` the emails adapter reads **read-only** (`file:…?mode=ro`); blank / missing = that group says *not configured*. See [Search everything](#search-everything) |
| `team` | shared install for a small team: `enabled`, `people` — Step 12 |
| `auth` | `token` (the bearer secret `scripts/gen_token.py` writes) · `password_hash` (optional, `scripts/set_password.py`). Both empty in the sample = only this PC can use the app |

Secrets (the Notion token for the one-shot import — `NOTION_API_TOKEN`, optionally `NOTION_TASKS_DB_ID`) go in `.env` (or any dotenv passed with `--env-file`), never in config; the GitHub side needs no token of its own — it is the `gh` CLI's login. `TASKOS_CONFIG_PATH` / `TASKOS_DB_PATH` env vars override the config/db location, `TASKOS_ISSUE_PROVIDER=none|fake` (+ `TASKOS_ISSUE_FAKE_PATH`) overrides the issue provider (the test harness uses all three for isolation).

## Data model

One SQLite file (`data/tasks.db`, WAL, FTS5), migrated by `src/schema.py` (`settings.schema_version`, currently **9**):

`tasks(id, parent_id, code, title, type task|coding|note, status inbox|todo|doing|standby|done|cancelled, priority high|medium|low|none, due, starts (v7 - the day it starts mattering; see [Start dates & snooze](#start-dates--snooze)), planned_on + plan_order (v8 - the day it was committed to and its position in that day's plan; see [Plan my day](#plan-my-day)), recurrence daily|weekly|monthly|quarterly|yearly + recurrence_anchor (v9 — the fixed day a weekly/monthly recurrence lands on; see [Start dates & snooze](#start-dates--snooze)), description, folder_ref, next_action, person_id, created_by, created_at, updated_at, done_at, external_id)` · `links(task_id, url, label, kind web|folder|email|issue|ai)` (v5 adds `ai` — an AI-conversation link, see [AI conversation links](#ai-conversation-links)) · `comments(task_id, author, ts, body, origin ui|cli|md|notion|import|sync, external_id)` · `activity(task_id, ts, actor, field, old_value, new_value)` · `people(name, email, avatar_path, external_id)` · `issue_refs(task_id, provider, repo, number, state, url, last_synced)` · `mirror_state(task_id, path, exported_at, file_mtime_ns, content_hash)` (v4 — what the markdown mirror last wrote per task) · `mirror_events(task_id, kind conflict|rejected, field, file_value, kept_value, ts)` (v6 — a mirror import conflict/rejection, deduped on task+field+file value; issue #84) · `tasks_fts` + `comments_fts` (FTS5, trigger-synced).

Rules the repo layer enforces (`src/tasks_repo.py`): a task with children **is** a project (the `project` filter means "descendant of"); `move` refuses cycles; every due / status / parent / priority (and title, type, recurrence, person, description) change writes an `activity` row; `POST .../done` on a recurring task rolls the **same** task's due to the next occurrence after both that due and today (the `recurrence_anchor`'s fixed day when it has one; month-end clamps) and logs the completion, otherwise it sets `done` + `done_at` (the web app's status select reaches this via a recurring task's **complete** option; picking `done` there is always a plain status change — closed for good, recurring or not); `type = coding` **iff** an `issue_refs` row exists (attach an issue to make a task coding — setting the type by hand is rejected); a task whose `starts` day has not arrived is hidden from the working views by `list_tasks` (see [Start dates & snooze](#start-dates--snooze)); planning appends to the day's `plan_order`, snoozing a planned task un-plans it, planning a deferred task wakes it (see [Plan my day](#plan-my-day)); deleting a task deletes its subtree.

## API

All under `/api/`, JSON in and out; errors are one envelope everywhere: `{"error": {"code", "message", "detail"?}}` (404 `not_found`, 422 `validation_error`, 409 `cycle`). The actor recorded on activity/comments is the body's `actor`/`author`, else the `X-Actor` header, else the first `team.people` entry in config.

| Method · path | What |
| --- | --- |
| `GET /api/version` | `{git_sha, built_at, asset_hash, schema_version}` — the build-identity contract the restart recipe checks |
| `GET /api/tasks?status=&parent=&project=&due=&due_from=&due_to=&type=&person=&q=&updated_since=&updated_before=&done_on=&include_closed=&limit=` (`person` repeatable / comma-separated) | filtered flat list (summaries with `child_count`, `is_project`, `issue_ref`, `person`, `breadcrumb`, `root` = top ancestor, `last_comment`, `comment_count`). `status` repeatable/comma (`open` = not done/cancelled — the default) and takes the pseudo-value `deferred` ([Start dates & snooze](#start-dates--snooze)); `parent=root`; `project` = descendant-of; `due` = `today` · `week` · `overdue` · a date; `updated_since` = a date (modified on/after — the filter card's *modified* window); `updated_before` = a date (last touched strictly before — the *untouched > 30/60/90 days* stale windows compute it client-side, so the wire is a plain shareable date; any write counts as a touch, sync and mirror included, so a GitHub-synced task never looks stale); `done_on` = a date (the Board's *Done today* column) |
| `POST /api/tasks` | create → 201 (`title` + any task field; `due`, `starts` and `planned_on` accept the natural phrases below, `""` clears) |
| `POST /api/tasks/bulk` `{ids, status?, due?, actor?}` | one change applied to many tasks (the Board/Table selection) → `{results: [{id, ok, task} \| {id, ok:false, error}], updated, failed}`. Every id is attempted and **200 is the partial-success code** — a bad id comes back as its own failure row rather than aborting or silently dropping the batch. `status: "complete"` rolls a recurring task's due (the row select's option, in bulk); `due` takes the natural phrases, resolved once for the request, `""`/`null` clears. Refused with 422: no `ids`, neither field, `complete` together with a `due`, or an unparseable phrase |
| `GET /api/tasks/tree?root=&include_closed=` | nested forest (`children`, `depth`); closed leaves pruned by default |
| `GET /api/tasks/{id}` | detail: task + `breadcrumb`, `children`, `links`, `comments` (thread order), `activity` (newest first) |
| `PATCH /api/tasks/{id}` · `DELETE /api/tasks/{id}` | partial update (fields present only; `parent_id` goes through the cycle guard; `due`, `starts` and `planned_on` natural or ISO, `""` clears — the plan rules of [Plan my day](#plan-my-day) apply) · delete subtree |
| `POST /api/tasks/{id}/move` `{parent_id\|null}` · `POST /api/tasks/{id}/done` | re-parent · complete (recurring → roll) |
| `GET/POST /api/tasks/{id}/comments` `{body, origin?, author?}` | thread · add → 201 |
| `GET/POST /api/tasks/{id}/links` `{url, label?, kind?}` · `DELETE …/links/{lid}` | links |
| `PUT /api/tasks/{id}/issue` `{provider?, repo, number, url?, state?}` · `DELETE …/issue` | attach an existing issue (→ `coding`; the next sync fills state / url) · detach (→ `task`; the issue is untouched) |
| `GET /api/tasks/{id}/issue` · `POST /api/tasks/{id}/issue` `{repo}` | the drawer's panel: `{ref, info}` (the stored ref + the last-seen labels / updated time from the sync cache; `?live=1` asks the provider now) · **create an issue from the task** (title + description → `gh issue create`, assigned to you) and link it → 201 with the task (`409 already_linked` / `issues_disabled`, `502 provider_error`) |
| `GET /api/issues/status` · `POST /api/issues/sync` | `{provider, enabled, reason, sync_minutes, last_sync, last_result, last_error, last_error_code, next_run, repos}` · one sync pass now → the result counts (`409 issues_disabled` when not configured, `502 provider_error` with the classified `code` when `gh` fails) |
| `GET /api/activity?task=&limit=` | activity log, newest first (all tasks when no `task`) |
| `POST /api/parse` `{text, today?}` | quick-add split → `{title, due, due_phrase, starts, starts_phrase, parent_ref, parent}` (`parent` resolved to `{id, title}` or `null`) |
| `GET/POST /api/people` · `GET/PATCH/DELETE /api/people/{id}` | people CRUD (`open_tasks` count included) |
| `GET /api/board?project=&person=&q=` | `{today, columns: {inbox, todo, doing, standby, done}}` — the Board's buckets, same enriched summaries as the list; `done` = completed on the current local day only |
| `GET /api/today?person=` | `{today, plan: {items, done, total}, due: [{root, items}], week: [{root, items}], counts: {overdue, today, week}}` — `plan` = the tasks committed to today ordered by `plan_order`, done ones included for the progress line ([Plan my day](#plan-my-day)); `due` = open tasks due ≤ today grouped by root project (recurring first inside a group), minus what is planned today; `week` = tomorrow … +7 days in the same shape (the CLI's shape; the web app derives the due/week buckets from the filtered list itself and reads only `plan` from here) |
| `GET /api/plan/candidates?person=` | `{items, count}` — what plan-my-day offers: open overdue + due-today + inbox tasks not already planned today; a candidate whose `planned_on` is an earlier day wears the "planned yesterday" note |
| `POST /api/plan/reorder` `{ids}` | rewrite today's plan order → `{planned: n}`; `ids` must be a permutation of every task planned today (422 otherwise) |
| `GET /api/search?q=&kinds=&limit=` · `GET /api/search/status` | **federated search** → `{q, took_ms, groups: [{kind, configured, reason, note, hits, count, took_ms, error, skipped}]}` — always the four groups `tasks · folders · emails · issues` in that order; an index that is not configured on this install is `configured:false` + `reason` (never silently absent), a failing one carries `error`; `kinds=tasks,emails` narrows which adapters run (the rest come back `skipped:true`); `limit` is per group. Every hit: `kind, title, subtitle, snippet` (`[match]` marks), `ref` (what attach stores: task id · folder ref · `.msg` ref · `owner/repo#N`), `url` (what open follows: `#task/id` · `taskos://open?ref=…` · the issue URL), `score` + kind-specific fields (`task_id, status, matched_in, breadcrumb` · `path, name` · `sender, date, folder, path` · `provider, repo, number, state, labels, task_id`) · the per-adapter configured / reason list for Settings |
| `GET /api/status` | `{https, auth: {enabled, password, client}, mirror: {enabled, dir, files, last_export, last_import, errors, error_files, watching, events, …}, backup: {enabled, dir, last_file, next_run, last_error, …}, folders: {enabled, roots, entries, last_indexed, indexing, stale, reason}, opener: {install, uninstall, env_template, installed_here, mode}, placeholders}` — how this request came in (`client`: `loopback` · `token` · `public`) and what the install accepts; a disabled service carries its `reason`. `opener.mode` is `launcher` · `fallback` · `null` — which registration shape this PC uses (see [Folders that open on any PC](#folders-that-open-on-any-pc)). `mirror.events` is the standing import-conflict/rejection count (issue #84) |
| `POST /api/mirror/export` · `POST /api/mirror/import` · `POST /api/backup` | run a full export / one watcher pass / one backup now (409 `mirror_disabled` / `backup_disabled` when not configured) |
| `GET /api/mirror/events` · `DELETE /api/mirror/events` | inspect every standing import conflict/rejection (most recent first) · clear all of them → `{cleared}` |
| `POST /api/resolve` `{ref}` | a folder ref **or** an absolute path → `{ref, path, resolved, unresolved, href}`: `ref` folded onto the placeholders (`E:\onedrive\house` → `{onedrive}/house`), `path` this server's absolute path (display only), `href` the `taskos://open?ref=…` link. The value rides the body, not a `?ref=` query — that parameter name is on every tracking-parameter blocklist, so a URL-cleaning browser extension strips it off the URL before the request leaves the browser (#66). Task payloads carry `folder_resolved` + `folder_url` (a `links(kind=folder)` web URL, when one exists) so no client resolves a ref itself |
| `GET /api/folders/search?q=&limit=` · `POST /api/folders/reindex` | the folder index: substring AND over every indexed path → `{items: [{path, ref, name, depth}], count, indexing}` · rescan `search.folder_roots` now (409 `folders_disabled` when no root is configured / usable) |
| `POST /api/login` `{secret}` · `POST /api/logout` | token or password → the 90-day `taskos_token` cookie · clear it |

Also `GET /` shell · `GET /login` sign-in page · `GET /healthz` liveness · `GET /opener/opener.cmd` and `GET /opener/opener.ps1` (the per-PC opener's handler and launcher, public so a second PC's install one-liner can download them). Every `/api/` route except `/api/version` and `/api/login` needs the caller to be loopback or to carry the token (see "Phone access & auth").

## CLI — `tasks`

`tasks.bat` at the repo root runs `src/cli.py` in the venv. It talks to the running app over HTTP when `:8448` answers (`--server URL` / `TASKOS_URL` to point elsewhere) and falls back to opening the database directly when the app is down (`--local` forces that). `--json` on every command prints the same shapes the API returns; `--actor NAME` sets who is acting; `-v` says which backend answered.

```
tasks add "title" [--parent N] [--due <date>] [--starts <date>] [--priority high|medium|low|none]
                  [--recurrence daily|weekly|monthly|quarterly|yearly]
                  [--recurrence-anchor fri | mon,tue,wed,thu,fri | day-15 | 1-sun | last-fri]
                  [--person id|name] [--desc "…"]
tasks ls [--status todo,doing | open | all] [--project N] [--due today|week|overdue] [--person id|name]
         [--deferred]              only the sleeping tasks (a start date still ahead)
         [--updated-before <date|30d>]   only tasks last touched strictly before that day (Nd = N days ago)
tasks show N               detail with breadcrumb, children, links, comments, activity (old → new)
tasks tree [N]             nested view (everything, or N's subtree)
tasks comment N "text"     origin = cli
tasks due N <date>         "none" clears
tasks starts N <date>      the day it starts mattering — snooze; "none" clears
tasks done N               recurring tasks roll forward and stay open
tasks plan                 plan the day: y/n/s over the candidates (see Plan my day)
tasks plan ls              today's plan, ordered, with the n-of-m progress line
tasks move N --parent M    M = root for top level; cycles are refused
tasks search "q" [--kind tasks|folders|emails|issues]   federated: one block per kind; unconfigured indexes say so
tasks people
tasks mirror [export|import|status]   markdown mirror: full export · one watcher pass · status (default)
tasks backup               copy the database to mirror.backup_dir now (tasks-YYYYMMDD.db)
tasks issues [sync|status] issue provider: one sync pass now (new / retitled / reopened / closed, ids) · status (default)
tasks issue create N --repo owner/name   open an issue from task N (title + description) and link it → coding
tasks folders [reindex|status|search "q"]   folder index: rescan search.folder_roots · status (default) · substring search → refs
```

Dates (`--due`, `--starts` — and the API's `due` / `starts` / `planned_on` fields, and quick-add) accept natural phrases via `src/dates.py`: `today`, `tomorrow`, `fri` (the coming Friday — today if it is Friday), `next friday` (+7), `this weekend` (the coming Saturday), `next week|month|year`, `in 3 days`, `in 2 weeks`, `2w`, `+10d`, `oct 15` / `15 oct` (the coming one — next year once it has passed; add a year to pin it), and ISO `YYYY-MM-DD`. Anything else is an error, never a silently unset date. Exit codes: 0 ok · 1 error (stderr, or the JSON error envelope with `--json`) · 2 usage.

## Start dates & snooze

A task can carry a **start date** (`starts`) — the day it starts mattering. Until then it is **deferred**: absent from the working views (Board, Today, Table, `tasks ls`), present everywhere that claims to show everything (the Tree, search, `tasks show`, `tasks ls --status all`), and back on its own on the day it starts. "Renew car insurance, due 15 Oct, nothing to do before 1 Oct" is created asleep and simply appears on 1 Oct.

Deferred is a **visible state, never a silent absence**. Wherever a sleeping task still shows it wears a quiet `starts 5 Sep` marker on its meta line, and the filter card's status multi-select carries a **`deferred`** entry that lists exactly those tasks. That entry is a *modifier*, not a status: it flips the list from awake to sleeping and intersects with any real statuses ticked beside it, so `?status=deferred` is the sleeping open tasks and `?status=deferred,doing` the sleeping ones that are `doing`. Like every filter, the state is the URL.

**Snooze** is that same field worn as a row control, not a second mechanism. Today rows carry a clock button: *Tomorrow · This weekend · Next week · Pick a date…* — one tap sets `starts`, the task leaves the list, and a toast names where it went (`Snoozed to Sat 5 Sep`) with an **Undo** that puts the old value back. The drawer edits **Starts** beside **Due** with the same control, and quick-add takes both off one line — `renew insurance due oct 15 starts oct 1` (a bare trailing date is still the *due* date; a start date says `starts`).

Everywhere a date is typed it is the one vocabulary from `src/dates.py` — `tomorrow`, `fri`, `next friday`, `this weekend`, `in 2 weeks`, `oct 15`, `2026-10-01`, `none` to clear — resolved server-side, so the UI, the CLI, quick-add and the markdown mirror cannot disagree.

**Recurrence:** the drawer's **Repeat** field is a cadence — `daily · weekly · monthly · quarterly · yearly` — and, for weekly and monthly, an **On** picker for the fixed day it lands on (#112):

| Cadence | On | Stored as | Means |
|---|---|---|---|
| weekly | every Friday | `fri` | that weekday, every week |
| weekly | weekday (Mon–Fri) | `mon,tue,wed,thu,fri` | any of those days |
| monthly | the 15th | `day-15` | the 15th, clamped to the end of a shorter month |
| monthly | the first Sunday · the last Friday | `1-sun` · `last-fri` | the nth (1–4) or last such weekday |
| daily / quarterly / yearly | — | `null` | a plain offset from the due date |

Completing a recurring task rolls its `due` to the **first occurrence after both the completed due and today**. So a weekly review anchored on Friday, ticked on a Monday, lands on the coming Friday rather than the next Monday — and a task three weeks overdue catches up into the future instead of rolling onto another overdue date. An anchor never retroactively moves the due you already have; the next roll settles onto it. Changing the cadence to one that cannot carry the anchor clears it (with its own activity row).

The roll **leaves `starts` untouched**. A start date is an absolute one-time gate, not a cadence: it always eventually arrives, so a snoozed recurring task wakes on its start day and rolls normally from then on. (Advancing it with the due would make the gate chase the task forever.)

From the terminal:

```powershell
tasks add "Book boiler service" --due "in 40 days" --starts "in 20 days"
tasks ls --deferred        # exactly the sleeping tasks
tasks starts 7 "next week" # snooze; `none` clears it
```

## Plan my day

Due dates are commitments; the **plan** is what you actually intend to do *today*. A task carries a `planned_on` date (v8), and Today shows **My plan** on top — the tasks committed to today, in your order, with an *n of m done* progress line. Completing a planned task moves the line; the done item stays on the list, struck through. Rows drag to reorder (desktop; the phone plans in tap order) and carry a quiet × that removes the commitment — activity-logged like any field change.

When the plan is empty and candidates exist, a banner offers the morning ritual: **Plan your day — 3 overdue · 5 due today · 4 new in Inbox**. Plan mode lists the candidates (overdue + due today + inbox), each with two large targets — **Today** commits it, **Later** is the same snooze popover from [Start dates & snooze](#start-dates--snooze) (one "not now" mechanism, not two). A task planned on an earlier day and left unfinished reappears as a candidate wearing a **planned yesterday — not finished** note: re-committing is a conscious act, never a silent carry-over.

The rules live in the repo layer, so every surface agrees: planning appends to the day's order; snoozing a planned task to a future day **un-plans** it (Later means "not today"); planning a deferred task **wakes** it (the gate is moot once you commit). `plan_order` is presentation-level ordering — never PATCHed directly, never mirrored (`planned_on` is mirrored like any field; mirroring the order would churn every synced file on every drag). The Board is untouched by all of this.

From the terminal, `tasks plan` walks the candidates interactively — `y` plans, `n` skips, `s` snoozes (any date phrase), `q` stops — and `tasks plan ls` prints the ordered plan with the progress line; `--json` returns the API shapes over both backends.

## Keyboard triage

Every row action is one key, so a triage pass is keys instead of mouse trips. `Tab` moves between rows on the Board, the Table, Today and the Search tab's task hits (the Tree keeps its own ↑↓→← outline walk and takes no action keys); the focused row is tinted, and after a change focus stays on it — or on whatever takes its place when the task leaves the view — so `e e e` walks a column.

| Key | On the focused row (or the whole ticked selection) |
| --- | --- |
| `E` | complete — a recurring task rolls to its next date, exactly as its row select's `complete` does |
| `1` `2` `3` `4` | status inbox · todo · doing · standby |
| `T` / `W` | due tomorrow / next week |
| `S` | the snooze menu — *tomorrow · this weekend · next week · pick a date* |
| `P` | cycle priority none → low → medium → high; over a selection each task moves from **its own** value |
| `Z` | undo the last change |
| `?` | the shortcuts sheet |

With tasks ticked ([Select several tasks at once](#views)) the same key applies to the set, and the ticks stay — keys come in runs (a status, then a due date, then a snooze) over one picked set. The keys are inert wherever text is being typed and while the drawer, the palette or the quick-add dialog is open.

**Undo** is a real write, not a client-side rollback: the inverse goes back through the API, so the reversal gets its own `new → old` activity row and survives a reload. It is single-level and lives exactly as long as its toast — over a selection it puts each task's own prior value back, one call per group of tasks that shared one. Completing a recurring task undoes to the *pre-roll* due date.

The same actions are listed in the command palette (`Ctrl+K` / `⌘K`), each showing its key — that is where a shortcut is discovered; `?` is the reference card.

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
starts: null
planned_on: null
recurrence: null
recurrence_anchor: null
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

- **frontmatter fields** `title`, `code`, `status`, `priority`, `due`, `starts` and `planned_on` (ISO or a natural phrase — `tomorrow`, `next friday`, `oct 1`), `recurrence` + `recurrence_anchor`, `person` (by name), `folder_ref`, `next_action`, `parent` (id; the cycle guard applies) and the **`## Description`** body are applied through the same repo layer as the UI, with **actor `md`** — every change lands in the activity log like any other (`plan_order` is deliberately **not** in the file: presentation-level ordering, and mirroring it would churn every synced file on every drag);
- **new lines under `## Comments`** become comments with `origin = md`: a bare `- your text` (author = the first `team.people` entry, time = now) or a full `- <ISO ts> · <author> · md: text` line; a body may continue on lines indented by two spaces. Comments are **append-only** — a deleted line is not a deletion, an edited existing line reads as a new comment (the original stays);
- `id`, `external_id`, `type` (derived from the issue link), `links`, the timestamps, `## Log` and any unknown section are read-only / ignored.

After a successful import the file is **re-exported**, so it always converges to the canonical form above (your `due: tomorrow` becomes the ISO date, your bare comment line gains its timestamp and author).

**Conflict policy** — per field: if the database changed that field *after* the file was written (the latest `activity` row for the field is newer than the file's `exported_at`), **the database wins** and the rejected file value is kept as a `mirror_events` row (schema v6, issue #84) — `import conflict on due: file said 2026-10-10, kept 2026-11-11`. A value the rules refuse (an unknown status or person, a parent that would make a cycle) is recorded the same way — `import rejected on status: file said later (…), kept todo`. Nothing is silently lost, but it is **never written to the task's comment thread** — a conflicting or rejected value is a sync diagnostic, not the owner's own writing. Deduped on (task, field, file value) so a permanently unresolvable value is one standing row, not one per import pass, and cleared once that field imports cleanly. The count and the events themselves are visible at app level: `/api/status` → `mirror.events`, `GET /api/mirror/events` to inspect, `DELETE /api/mirror/events` to clear — the Settings mirror card shows the count with the same actions. The file still converges to the value that won.

**Failure mode** — a file that does not parse (broken frontmatter, no integer `id`) is **skipped**: one warning in the log per changed version, the file counted under `errors` / `error_files` in `/api/status`, `tasks mirror status` and the Settings tab; the app never crashes on a bad file, and fixing the file is picked up on the next tick. A file in the folder that matches no task is left alone. Not configured (blank `mirror.dir`, an unresolved `{placeholder}`, a missing parent folder) is a **visible** state — the reason is logged at startup and shown in the same three places — never a silent no-op.

## Backups

`src/backup.py` copies `data/tasks.db` to `<mirror.backup_dir>/tasks-YYYYMMDD.db` with SQLite's online backup API (a consistent snapshot while the app keeps writing under WAL), via a temp file + atomic rename, and keeps the **newest 30** dated copies. Two ways to run it:

- **In-app (default):** the webapp runs it **daily at 03:00 local** while it is up, plus once at startup when today's copy is missing (a PC that was off at 03:00 still gets one). Status — last file, next run, last error — in `/api/status` and the Settings tab; `POST /api/backup` runs one now.
- **From a scheduler:** `tasks backup` does the same from the terminal (over HTTP when the app is up, else against the file directly) — put `E:\automation\task-os\tasks.bat backup` in Windows Task Scheduler / an app-launcher job if you would rather not depend on the app being up at 03:00; the pruning keeps both paths at 30 files.

Point `mirror.backup_dir` at a synced folder (`{onedrive}/task-os/backup`); the database itself stays out of the sync client by design — only the mirror and the dated copies travel.

## Issues as tasks

A coding task **is** an issue: `type = coding` ⇔ an `issue_refs` row (provider, `owner/repo`, number, state, url, last synced). The sync keeps the two in step, **read-mostly** — task-os never edits an issue's title, labels or state on the forge; the one write is *Create issue* below.

**Provider** — `config/config.json → issues`: `provider` (`github` today; `gitlab` arrives with Step 11; blank / `none` = off), `owner` (whose repositories are searched), `assignee` (`@me`), `sync_minutes` (default 10). GitHub goes through the **`gh` CLI** (`gh auth login` once; no token in config): `gh search issues --assignee @me --state open --owner <owner> --json …`, `gh issue view`, `gh issue create` — each a subprocess with a 20 s timeout, never on a poll. Not configured (blank owner, `gh` not on PATH) and every failure (`not_authenticated`, `timeout`, `rate_limited`, `not_found`, `error` — classified from `gh`'s stderr) are **visible states**: `GET /api/issues/status`, the Settings card *Issues as tasks* and `tasks issues status` say which; a failed listing changes nothing — never an empty list read as "no issues".

**Sync** — a pass runs 10 s after startup, then every `sync_minutes` while the app is up, and on demand: **↻** in the header, *Sync now* on the Settings card or in a task's issue panel, `POST /api/issues/sync`, `tasks issues sync`. One pass:

| On the forge | In task-os |
| --- | --- |
| an open issue assigned to you with no task | a new **coding** task in **To do**: `title` = the issue title, `code` = `<repo>#<n>` (short repo name), `description` = the issue body, a link (`kind = issue`), the ref (state `open`, url); `created_by = sync`. Dedupe key = (provider, repo, number) — a re-run touches nothing it already made |
| the issue's **title changed** | the task title follows (activity `title` by `sync`) — the issue title is canonical for a coding task; rename it on the forge |
| an issue that was **closed** is open again | the ref goes `open`; a task that was done / cancelled is **reopened** to `todo` (activity by `sync`) |
| a ref that should be open is **missing from the list** | confirmed first with one `gh issue view`: **closed** → the ref goes `closed` and the task is **done** (skipped when already done / cancelled; activity `status … → done · sync` + `issue_state open → closed · sync`); still open (unassigned from you, another owner) → nothing but `last_synced` moves; the lookup failed → the task is left alone and the error is in the result. Closed refs are not polled again |

GitHub's search index is eventually consistent — an issue closed seconds ago can still be listed *open* for ~30 s; the next pass catches it. Every task the sync creates or changes goes through the same repo layer as the UI, so the activity log, the markdown mirror and the Board see it like any other write.

**Create / link / unlink** — in the drawer's issue panel of a plain task: *Create issue* (repo from the last-seen list or typed as `owner/repo`) runs `gh issue create` with the task's title and description, assigns it to you and links it — the task becomes coding with `code = repo#N` (`tasks issue create N --repo owner/name` from the terminal). *Link existing* takes `owner/repo#N` or the issue URL (`PUT /api/tasks/{id}/issue`) — the next sync fills state and url. *Unlink* (`DELETE`) makes it a plain task again; the issue is untouched. Board / Table / Tree cards carry the chip (`repo#N`, provider glyph, muted with a check once closed) that opens the issue.

**Never written back:** titles, labels, state, assignees, comments. A local rename of a coding task is overwritten by the next sync; a task marked done locally does **not** close its issue.
## Folders that open on any PC

A task's **folder** is stored as a portable ref — `{onedrive}/house/kitchen`, `{user}/code/garden-bot`, `{sharepoint:docs}/plans` — never as one machine's path. Two things resolve it, never the browser:

- **This server**, for display: `config.placeholders` (`onedrive`, `user`, and a `sharepoint` map whose keys become `{sharepoint:<name>}`) turn the ref into `folder_resolved` on every task payload — the chip's tooltip, the drawer's Folder section, the phone's copy popover. A token missing from the config is reported (`unresolved`), never guessed. Paste an absolute path in the drawer's Folder field and it is folded back onto the longest matching placeholder (`E:\onedrive\house` → `{onedrive}/house`) before it is stored (`POST /api/resolve`).
- **The per-PC opener**, for opening: the folder chip is `<a href="taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen">`. A browser cannot touch the file system, so Windows hands the URL to a tiny launcher registered for **your user** — [`opener/opener.ps1`](opener/opener.ps1), which passes it to [`opener/opener.cmd`](opener/opener.cmd) through the environment — which URL-decodes the ref, expands `{onedrive}` from `%OneDriveCommercial%` (when set) else `%OneDrive%`, `{user}` from `%USERNAME%`, `{sharepoint:<name>}` from a `<name>=<path>` line in `%LOCALAPPDATA%\task-os\opener.env`, and opens **that PC's** synced copy in Explorer (a file opens with its default app). A path that is not synced there gets a visible console notice with the resolved path to copy. Same mechanism on the server PC and on any other machine.

**Install the opener — 30 s per PC, no admin, no Python:** Settings → **Folder opener** shows the one-line PowerShell command from [`opener/install.txt`](opener/install.txt) with this install's address filled in (Copy → paste into PowerShell → Enter). It copies `opener.cmd` + `opener.ps1` to `%LOCALAPPDATA%\task-os\`, creates an empty `opener.env` and registers `HKCU\Software\Classes\taskos` through the registry API (`New-Item` / `Set-ItemProperty`) — the route that keeps working where `reg.exe` / regedit are blocked; the pasted line is an inline command, so no execution policy applies to the install itself. On a PC with Python, `python opener\install_opener.py` (`--dry-run` prints the plan, `--uninstall` removes it) does the same via `winreg`.

What gets registered is `opener.ps1`, which receives the URL as an **argument**. Pointing the scheme straight at the `.cmd` instead would hand it to a command interpreter as a *string* that is re-parsed, so a quote inside the URL could start a second command — measured against every such shape on Windows 11 and none of them safe ([`opener/README.md`](opener/README.md#why-a-launcher-and-not-the-handler-directly) has the grid). Where a machine policy blocks running a script file the installers fall back to the old `.cmd` registration and **say so** (`mode: FALLBACK`, `FALLBACK mode` at the end of the pasted line, a `fallback mode` chip in Settings) — a degraded install is never silent. Then click any folder chip: the browser asks once *"Open task-os opener?"* (tick *always allow*), and Explorer opens. If nothing opens, a one-time hint appears under the chip pointing at the Settings card. Details, what was verified and the caveats: [`opener/README.md`](opener/README.md).

**`opener.env`** — one `name=path` line per placeholder that PC needs beyond the two Windows knows: `docs=C:\Users\me\Tenant\docs - Documents` serves `{sharepoint:docs}` (and `{docs}`); `onedrive=D:\OneDrive` overrides the environment; values may use `%VARS%`. The Settings card shows a template built from this install's placeholders.

## AI conversation links

Paste the URL of an AI conversation into a task's links — Claude Code / claude.ai, ChatGPT, Gemini, GitHub Copilot, Microsoft Copilot are all recognised and stored as one kind (`ai`), no per-provider split — and the task wears a **bot chip** on the Board / Table / Tree rows, same as the folder chip. A Claude Code session page shows the full transcript even after the local session ended (archived sessions stay readable), so the link never rots.

- **Phone (coarse pointer):** tapping the chip opens the conversation in a new tab — there is no CLI to resume into.
- **Desktop:** clicking the chip opens a small popover — **Open conversation** (the usual choice, new tab) and, for a `claude.ai/code/session_…` URL, **Resume in CLI on this PC** (`taskos://resume?session=…`). The same per-PC opener that opens folders searches `%USERPROFILE%\.claude\projects` for the transcript carrying that session id, and reopens it in a terminal (`wt` when installed) running `claude --resume <local-session-uuid>` **in the repo the session ran in**. A session this PC never saw falls back to opening the web page, with a visible notice. The pure-`cmd` fallback registration cannot search transcripts — it says so instead of degrading silently.

Where to get the URL: every Claude Code commit carries a `Claude-Session: https://claude.ai/code/session_…` trailer, the session list at claude.ai/code shows it, or ask the session itself for its link. List summaries carry `ai_url` + `ai_label` (the first `ai` link) so rows never scan the links table client-side.

**Phone / tablet:** no Explorer to open — tapping the chip opens its **web twin** directly in one tap: an explicit folder link on the task, or the URL derived from `config.web_roots` when the ref's placeholder has a cloud web equivalent (`{"onedrive": "https://<your-cloud>/…"}` → `{onedrive}/house` opens `https://<your-cloud>/…/house`); a chip that carries no link (an email `.msg` ref, an attached file) asks `POST /api/resolve` first. Only a ref with no web twin at all falls back to the popover with the resolved path and a **Copy** button.

**Folder index** — `search.folder_roots` (placeholder-aware, `["{onedrive}/Documentos"]`) is scanned into `data/folder_index.txt` by the vendored `foldersearcher_core` (the GUI-free half of the fleet's folder searcher): at startup when the file is missing or older than 24 h (in the background), on **Reindex folders now** in Settings, `POST /api/folders/reindex` or `tasks folders reindex`. Search is substring-AND over every path (`kitchen plans`), each hit carrying the portable `ref` — the drawer's **Pick from folder index…** attaches one with Enter; `tasks folders search "q"` prints them. Not configured / no usable root is a visible state in `/api/status`, Settings and `tasks folders`, never an empty result.

## Search everything

One box, four indexes, results grouped by kind — full width on the PC, one column on the phone. `src/search/` holds one **adapter** per index behind one contract (`base.py`: `is_configured() → (ok, reason)`, `search(q, limit) → hits`); `federated.py` runs the configured ones **concurrently** (a thread pool, 2 s per adapter — a cold email index cannot hold the tasks answer hostage) and always answers with the four groups in order:

| Kind | Index | Configured when | Hit → open · attach · new task |
| --- | --- | --- | --- |
| **Tasks** | `tasks_fts` + `comments_fts` (title · description · comment bodies), the FTS5 snippet with the match marked | always | open = the drawer |
| **Folders** | the folder index (Step 9, `search.folder_roots`), substring AND, each hit with its portable ref + this PC's path | a root is configured and usable here | open = the `taskos://` opener chip · attach = the task's **folder** (or a folder link when it already has one) · new = a task titled like the folder, with the ref |
| **Emails** | the [email-archiver](https://github.com/ferraroroberto/email-archiver) `emails.db` (`search.email_db`) — opened **read-only** (`file:…?mode=ro`, a fresh connection per query, never a write), FTS5 `MATCH` ranked with the archiver's own weights `bm25(subject 10 · sender 3 · recipients 3 · body 1)`; falls back to `LIKE` when the FTS table is missing (older archiver builds) | the file exists and has an `emails` table | the hit is subject · sender · date · folder; its `ref` is the `.msg` path folded onto the placeholders (`{onedrive}/…/mail.msg` when it lies under a configured root) — open = the same opener chip (Windows opens the file with its default app), attach = `links(kind=email, url=<ref>, label=subject)`, new = a task titled like the subject with *From email: sender · date* and the link |
| **Issues** | `issue_refs` joined to their tasks + the sync's cached open list (Step 8) — title, `owner/repo#N`, labels; **never a forge call per keystroke** | the issue provider is | open = the issue URL (or the linked task) · attach = *link existing* (`PUT /api/tasks/{id}/issue`) · new = a coding task with the ref |

**Not configured is a visible state**, never an empty result: the group renders a quiet *not configured — reason · Settings* row (Settings → **Search** lists the four with their reasons and `GET /api/search/status` returns the same); a broken index shows *error — …*; a folder index still building says so next to the count. Marked terms come back as `[match]` and render as `<mark>`.

**Search tab** — autofocus box (the header bar's height), 200 ms debounce, `?q=` in the URL while the tab is showing (`/?q=kitchen#search` is a deep link). The four result groups are collapsible cards, collapsed by default and remembered per kind, each summary carrying its hit count (no timings on screen). **Every hit is the same row shape** (#48): a title line and one muted meta line, no glyphs, no buttons. Task hits are the row every other view shows (status select, meta line) plus the matched snippet, filtered and sorted by the shared filter card under the box; a folder hit is *name · full path* and an email hit *subject · sender · date · folder*, their title being the `taskos://` link (a PC opens Explorer / the `.msg`, the phone shows the path to copy); an issue hit is *title · repo#N · state* — the title opens the linked task when there is one, else the issue page. Keyboard: `↓` from the box focuses the first row; on rows `↑↓` move, `Enter` opens, `Esc` / `/` back to the box.

**Command palette** — `Ctrl+K` / `⌘K` anywhere, or the ⌘ button in the header (the vendored editor-modal shell; a full-width sheet on the phone). Type to **jump to a task** (the tasks adapter, top 8: title · breadcrumb · status; `Enter` opens it); `>` lists **commands** filtered as you type: *New task* (opens the quick-add dialog), *Go to Board / Table / Tree / Today / Search / Settings*, *Filter: status inbox|todo|doing|standby|done* / *Filter: clear* (the Table), *Sync issues*, *Reindex folders*, *Export mirror*, *Open folder of current task* (emits the drawer's `taskos://` chip click), *Toggle theme*, *Sign out*. `↑↓` move, `Enter` runs, `Esc` closes.

**Terminal** — `tasks search "q" [--kind emails]` prints one block per kind (unconfigured indexes on their own line) and `--json` returns the API's shape; with the app down it builds the same adapters locally (the folder index loaded from its file, the issue cache cold — local refs only, the email index read-only).

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

`gen_tailscale_cert.py` (copied from `project-scaffolding` and adapted here — copy-to-adapt, not vendor-verbatim; project-scaffolding#232) detects this machine's MagicDNS name and asks `tailscale cert` for a Let's Encrypt leaf — trusted by every device on the tailnet, **zero per-device trust steps**. With the pair present the launcher (the tray's `manager.py` and `launcher.py webapp` — the two spawn points; `webapp.bat` is a wrapper over the latter) serves **`https://<your-host>.ts.net:8448`**; without it the app serves plain HTTP and says so loudly in the log and in `GET /api/status` (`https: false`). The leaf lives ~90 days: every launcher runs `gen_tailscale_cert.py --check` **before uvicorn binds**, which renews a `.ts.net` cert expiring within ~30 days and never blocks a start. `localhost` is not in the cert — the tray's **Open task-os** / **Copy URL** use the `.ts.net` name (it resolves on the host too), the restart probe uses loopback and skips verification.

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
