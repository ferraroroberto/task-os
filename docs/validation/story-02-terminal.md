# Story 02 — Add and nest from the terminal

**Issue:** #3 (Step 2/13). **Tests:** `tests/test_cli.py::test_story_02_add_nest_comment_tree_due_show` (parametrised over both CLI backends: direct DB and HTTP via the app), `tests/test_api.py::test_story_02_over_http` (the same sequence as raw REST calls). No browser leg — this step has no UI surface; the on-screen proof is the terminal transcript below.

**Steps → expected**

1. `tasks add "Renew passport" --due fri` → task #1 created, `fri` resolved to the coming Friday's ISO date.
2. `tasks add "Book appointment" --parent 1` → task #2 nested under #1.
3. `tasks comment 2 "called the office"` → a comment on #2 with `origin = cli`.
4. `tasks tree` → #2 indented under #1.
5. `tasks due 2 2026-09-01` → due set; one `activity` row `due: ∅ → 2026-09-01`.
6. `tasks show 2` → breadcrumb `in: Renew passport`, the comment, and the activity log with the due-date change **old → new** on top of `created`.

**Transcript — 2026-08-17 10:15 (+02:00), Windows PowerShell, `tasks.bat` = `src/cli.py`.** Both backends walked against scratch databases (`%TEMP%\taskos-story02\…`), never `data/tasks.db`.

*Leg A — over HTTP, against a disposable instance of this build (`TASKOS_DB_PATH` → scratch, `TASKOS_CONFIG_PATH` → the sample config, port 8471; `/api/version` reported `schema_version: 2`), reached via `TASKOS_URL`:*

```
PS> tasks -v add "Renew passport" --due fri
[tasks] via http: http://127.0.0.1:8471
added #1  Renew passport  (due 2026-08-21)
PS> tasks add "Book appointment" --parent 1
added #2  Book appointment
PS> tasks comment 2 "called the office"
commented on #2: called the office
PS> tasks tree
#1  Renew passport  (due 2026-08-21)
  #2  Book appointment
PS> tasks due 2 2026-09-01
#2 due → 2026-09-01
PS> tasks show 2
#2  Book appointment  (due 2026-09-01)
  in: Renew passport
  type task · status inbox · priority none · due 2026-09-01
  created 2026-08-17T10:15:09+02:00 by Roberto Ferraro · updated 2026-08-17T10:15:09+02:00
  comments:
    2026-08-17T10:15:09+02:00  Roberto Ferraro (cli): called the office
  activity:
    2026-08-17T10:15:09+02:00  Roberto Ferraro  due: ∅ → 2026-09-01
    2026-08-17T10:15:09+02:00  Roberto Ferraro  created: ∅ → Book appointment
PS> tasks show 2 --json      (activity excerpt)
[{"id":3,"task_id":2,"ts":"2026-08-17T10:15:09+02:00","actor":"Roberto Ferraro","field":"due","old_value":null,"new_value":"2026-09-01"},
 {"id":2,"task_id":2,"ts":"2026-08-17T10:15:09+02:00","actor":"Roberto Ferraro","field":"created","old_value":null,"new_value":"Book appointment"}]
PS> tasks search office
#2  Book appointment in Renew passport
    comment: called the [office]
```

*Leg B — the app-down path: `--local` (direct DB, `TASKOS_DB_PATH` → a second scratch file), same six commands:*

```
PS> tasks -v --local add "Renew passport" --due fri
[tasks] via local: database directly (--local)
added #1  Renew passport  (due 2026-08-21)
PS> tasks --local add "Book appointment" --parent 1
added #2  Book appointment
PS> tasks --local comment 2 "called the office"
commented on #2: called the office
PS> tasks --local tree
#1  Renew passport  (due 2026-08-21)
  #2  Book appointment
PS> tasks --local due 2 2026-09-01
#2 due → 2026-09-01
PS> tasks --local show 2
#2  Book appointment  (due 2026-09-01)
  in: Renew passport
  type task · status inbox · priority none · due 2026-09-01
  created 2026-08-17T10:15:17+02:00 by Roberto Ferraro · updated 2026-08-17T10:15:18+02:00
  comments:
    2026-08-17T10:15:17+02:00  Roberto Ferraro (cli): called the office
  activity:
    2026-08-17T10:15:18+02:00  Roberto Ferraro  due: ∅ → 2026-09-01
    2026-08-17T10:15:17+02:00  Roberto Ferraro  created: ∅ → Book appointment
```

Observed = expected on both legs (2026-08-17 is a Monday, so `fri` → `2026-08-21`).

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (`test_dates`, `test_schema`, `test_repo`, `test_api`, `test_cli`, `test_smoke`: nesting/tree/breadcrumb, cycle guard, activity on every change, recurrence roll incl. month-end for all five cadences, comments ordering + origin, FTS over title/description/comments incl. updates and deletes, migrations idempotent + v1→v2 upgrade + failed-step rollback, every CLI subcommand with `--json` on both backends, the date parser), then the routed e2e (full tier — story 01 still green with `schema_version` 2).
- [x] On screen: the transcript above, walked live in PowerShell on this build.
- [x] Live app: `tray.bat --restart` → `/api/version` `git_sha == HEAD`, `schema_version == 2` (recorded in the PR).
- Not verified in this step: the automatic HTTP → local fallback when the *real* `:8448` is down was proven by unit test (`test_pick_backend_falls_back_to_local_when_app_is_down`) and by the forced `--local` leg, not by stopping the live tray; no UI shows any of this yet (Step 4 brings the first task on screen).
