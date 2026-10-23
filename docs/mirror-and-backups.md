# Markdown mirror, backups and usage log

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
status: todo
priority: none
due: 2026-08-20
starts: null
recurrence: null
recurrence_anchor: null
recurrence_interval: null
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

- **frontmatter fields** `title`, `code`, `status`, `priority`, `due`, `starts` (ISO or a natural phrase — `tomorrow`, `next friday`, `oct 1`), `recurrence` + `recurrence_anchor` + `recurrence_interval`, `person` (by name), `folder_ref`, `next_action`, `parent` (id; the cycle guard applies) and the **`## Description`** body are applied through the same repo layer as the UI, with **actor `md`** — every change lands in the activity log like any other;
- **new lines under `## Comments`** become comments with `origin = md`: a bare `- your text` (author = the first `team.people` entry, time = now) or a full `- <ISO ts> · <author> · md: text` line; a body may continue on lines indented by two spaces. Comments are **append-only** *on this path* — a deleted line is not a deletion, an edited existing line reads as a new comment (the original stays). Editing and deleting a comment is the drawer's pencil and trash; either write re-exports the file, so the next import sees the corrected thread rather than resurrecting the old line;
- `id`, `external_id`, `type` (derived from the issue link), `links`, the timestamps, `## Log` and any unknown section are read-only / ignored.

After a successful import the file is **re-exported**, so it always converges to the canonical form above (your `due: tomorrow` becomes the ISO date, your bare comment line gains its timestamp and author).

**Conflict policy** — per field: if the database changed that field *after* the file was written (the latest `activity` row for the field is newer than the file's `exported_at`), **the database wins** and the rejected file value is kept as a `mirror_events` row (schema v6) — `import conflict on due: file said 2026-10-10, kept 2026-11-11`. A value the rules refuse (an unknown status or person, a parent that would make a cycle) is recorded the same way — `import rejected on status: file said later (…), kept todo`. Nothing is silently lost, but it is **never written to the task's comment thread** — a conflicting or rejected value is a sync diagnostic, not the owner's own writing. Deduped on (task, field, file value) so a permanently unresolvable value is one standing row, not one per import pass, and cleared once that field imports cleanly. The count and the events themselves are visible at app level: `/api/status` → `mirror.events`, `GET /api/mirror/events` to inspect, `DELETE /api/mirror/events` to clear — Settings → *Mirror and backup* shows the count with the same actions. The file still converges to the value that won.

**Provenance rule** — the file's `exported_at` is the one line no human edit touches, so it says whose rendering a file is. Equal to what the app last wrote: its own file, edited. Older: a stale copy of its own file (a sync client restoring a previous version) — still an edit, judged against *that* snapshot, so anything the database changed since it wins. **Newer: the app never wrote it** — another task-os instance rendered *its* database into the folder (a fresh checkout on the sample config, a test harness pointed at the real folder). That is not an edit: nothing is applied, every differing value becomes a `conflict` event (`import conflict on person: file said ∅ (written by another task-os instance …), kept Alex Chen`), the file is re-exported to canonical — or, under a name the app never wrote, skipped and listed under `error_files`. Two boundaries keep a disposable instance out of the real folder in the first place: an instance on an overridden database (`TASKOS_DB_PATH`) only mirrors and backs up to a folder **beside that database** (anything else is refused with the reason in `/api/status`), and the committed sample config never enables either service — a checkout without its own `config/config.json` boots with the mirror and backup off.

**Failure mode** — a file that does not parse (broken frontmatter, no integer `id`) is **skipped**: one warning in the log per changed version, the file counted under `errors` / `error_files` in `/api/status`, `tasks mirror status` and Settings; the app never crashes on a bad file, and fixing the file is picked up on the next tick. A file in the folder that matches no task is left alone. Not configured (blank `mirror.dir`, an unresolved `{placeholder}`, a missing parent folder) is a **visible** state — the reason is logged at startup and shown in the same three places — never a silent no-op.

## Backups

`src/backup.py` copies `data/tasks.db` to `<mirror.backup_dir>/tasks-YYYYMMDD.db` with SQLite's online backup API (a consistent snapshot while the app keeps writing under WAL), via a temp file + atomic rename, and keeps the **newest 30** dated copies. Two ways to run it:

- **In-app (default):** the webapp runs it **daily at 03:00 local** while it is up, plus once at startup when today's copy is missing (a PC that was off at 03:00 still gets one). Status — last file, next run, last error — in `/api/status` and Settings; `POST /api/backup` runs one now.
- **From a scheduler:** `tasks backup` does the same from the terminal (over HTTP when the app is up, else against the file directly) — put `E:\automation\task-os\tasks.bat backup` in Windows Task Scheduler / an app-launcher job if you would rather not depend on the app being up at 03:00; the pruning keeps both paths at 30 files.

Point `mirror.backup_dir` at a synced folder (`{onedrive}/task-os/backup`); the database itself stays out of the sync client by design — only the mirror and the dated copies travel.

## Usage log

The app records which views and controls you actually use, and on which device class, so a design review reads frequency instead of asking (the vendored `usage-log` client + `src/usage_log.py`, from project-scaffolding). Views are the three tabs, `settings`, `settings.<sheet>` and `journal`; taps are the controls carrying a constant `data-track` id (theme, Settings, Select, +, the filter button, the row ⋯, the Board layout and scope segments, text size, the quick-add mic and Add, and each Settings sheet's run / sync / refresh button). Events are batched to the app's own `POST /api/usage/events` and land in `usage.sqlite3` **beside the task database** (`<fleet runtime-data root>/task-os/`; beside `TASKOS_DB_PATH` when that is set, so a test instance never writes the real one). Nothing else is stored, and nothing goes to any other origin: no content, names, queries, form values, URLs, IPs or user-agent, only the event kind, view id, control id, a per-visit random session id, device / OS class and the server's timestamp. `GET /api/usage/summary?days=30` reads it back (owner on loopback, else the token, like every `/api/` route); rows older than 365 days or past 200,000 are pruned on insert. Losing the file loses history, not function.
