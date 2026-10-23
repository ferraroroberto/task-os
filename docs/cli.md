# CLI — `tasks`

`tasks.bat` at the repo root runs `src/cli.py` in the venv. It talks to the running app when `:8448` answers — `https://127.0.0.1` first when the cert pair exists (the tray then serves TLS), else plain `http://`. Loopback skips certificate verification, since the leaf names the tailnet host and loopback is already the owner; any other `--server URL` / `TASKOS_URL` is verified normally. When nothing answers (the app is down), it opens the database directly (`--local` forces that). `--json` on every command prints the same shapes the API returns; `--actor NAME` sets who is acting; `-v` says which backend answered.

```
tasks add "title" [--parent N] [--due <date>] [--starts <date>] [--priority high|medium|low|none]
                  [--status inbox|todo|standby|done|cancelled]   default todo
                  [--recurrence daily|weekly|monthly|quarterly|yearly]
                  [--recurrence-anchor fri | mon,tue,wed,thu,fri | day-15 | 1-sun | last-fri]
                  [--recurrence-interval N]   every N cadences (2–999)
                  [--person id|name] [--owner <member id>] [--desc "…"]   owner default: you
                  [--folder <ref|path>] [--link <url> [--link-label "…"]]   one link; its kind is inferred
tasks ls [--status todo,standby | open | all] [--project N] [--due today|week|overdue] [--person id|name]
         [--owner <member id>[,…]]   the install owner's include tasks nobody gave an owner
         [--deferred]              only the sleeping tasks (a start date still ahead)
         [--blocked]               only tasks with an open blocker
         [--updated-before <date|30d>]   only tasks last touched strictly before that day (Nd = N days ago)
tasks show N               detail with breadcrumb, children, links, comments, activity (old → new)
tasks tree [N]             nested view (everything, or N's subtree)
tasks comment N "text"     origin = cli
tasks set N [--title "…"] [--status …] [--priority …] [--desc "…"] [--folder <ref|path>|none] [--owner <member id>]
                           edit fields, one activity row each; --status done does not roll a recurring task (use done)
tasks link N <url> [--label "…"] [--kind web|folder|email|issue|ai]   kind omitted → inferred from the URL
tasks due N <date>         "none" clears
tasks starts N <date>      the day it starts mattering — snooze; "none" clears
tasks done N               recurring tasks roll forward and stay open
tasks triage               stage AI suggestions for every Inbox task, then y/n/q each one
tasks journal [--weeks N] [--project N] [--person id|name]   what got done, grouped by day, newest first (this week; N weeks back)
tasks move N --parent M    M = root for top level; cycles are refused
tasks block N --on M       N is blocked by M — refused on a self-block or a cycle
tasks unblock N M          remove M as a blocker of N
tasks rm N [--yes]         delete N and its subtree — names what goes and asks [y/N] on stderr (a refusal is exit 1, so a script that forgot --yes fails loud); alias: delete
tasks search "q" [--kind tasks|folders|emails|issues]   federated: one block per kind; unconfigured indexes say so
tasks people
tasks mirror [export|import|status]   markdown mirror: full export · one watcher pass · status (default; also the backup, folder-index, capture and voice lines)
tasks backup               copy the database to mirror.backup_dir now (tasks-YYYYMMDD.db)
tasks issues [sync|status] issue provider: one sync pass now (new / retitled / reopened / closed, ids) · status (default)
tasks issue create N --repo owner/name   open an issue from task N (title + description) and link it → coding
tasks folders [reindex|status|search "q"]   folder index: rescan search.folder_roots · status (default) · substring search → refs
```

Dates (`--due`, `--starts` — and the API's `due` / `starts` fields, and quick-add) accept natural phrases via `src/dates.py`: `today`, `tomorrow`, `fri` (the coming Friday — today if it is Friday), `next friday` (+7), `this weekend` (the coming Saturday), `next week|month|year`, `in 3 days`, `in 2 weeks`, `2w`, `+10d`, `oct 15` / `15 oct` (the coming one — next year once it has passed; add a year to pin it), and ISO `YYYY-MM-DD`. Anything else is an error, never a silently unset date. Exit codes: 0 ok · 1 error (stderr, or the JSON error envelope with `--json`) · 2 usage.
