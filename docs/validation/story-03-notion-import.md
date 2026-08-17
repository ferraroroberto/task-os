# Story 03 — Import my Notion

**Issue:** #4 (Step 3/13). **Tests:** `tests/test_import_notion.py` (mapping table for status / priority / recurrence, block → markdown incl. nested children and tables, the whole synthetic export `tests/fixtures/notion_export.json` mapped and written, comment ordering + author fallback, idempotency — run twice, same counts, no duplicates — a re-import that applies source changes without duplicating, `--dry-run` writes nothing (not even a file), `--limit` + `--json-dump` round-trip, migration v2 → v3 + idempotent + the unique index), plus the bumped `test_schema.py` / `test_api.py` (`schema_version` 3). No browser leg — this step has no UI surface of its own; the on-screen proof is the terminal transcript below and the CLI read-back through the running app.

**Steps → expected**

1. `import_notion --dry-run --database-id <id> --env-file <path>\.env --db <live db>` → the report: page count, counts per status / priority / recurrence, comments, people, anything unmapped or skipped, and the plan (create / update / unchanged); nothing written, no migration.
2. The real import → schema migrated to v3, every page a task with status, priority, due, recurrence, description, links, comments (original timestamps, `origin = notion`, thread order), the linked person; one `imported` activity row per task.
3. Re-run the same command → tasks created 0 · updated 0 · unchanged N; comments existing N; nothing changes.
4. `tasks ls` / `tasks show` through the running app → the counts, a long comment thread intact and in order with dates, a task with a person shows the name, recurring cadences set.

**Transcript — 2026-08-17 10:34–10:47 (+02:00), Windows, `scripts/import_notion.py` from the worktree against the live `data/tasks.db` (app on `:8448` running throughout; WAL).** Real data stayed off the repo: this record carries **counts only** — no titles, names, links or ids. The private screenshots / full transcript went to the issue, not here.

*Step 1 — dry run (fetch + map + report, 215 pages, 575 API calls, ~3 min):*

```
Notion import — DRY RUN (nothing written)
  pages      : 215
  status     : todo 111 · done 104   (source: null 109 · Done 104 · not started 2)
  priority   : none 150 · low 37 · medium 20 · high 8   (source: null 121 · low 37 · backlog 29 · medium 20 · high 8)
  recurrence : none 194 · weekly 8 · quarterly 5 · monthly 4 · yearly 3 · daily 1
               (source: null 194 · weekly 8 · three months 5 · monthly 4 · yearly 3 · daily 1)
  due dates  : 182 set
  links      : 134 pages with a link
  body       : 52 pages with content
  comments   : 281 on 69 pages (longest thread 95)
  people     : 134 distinct in relations · 143 pages get a person · 0 extra relations → 'also linked' comments
  notes      : unknown block 9 · empty title 2
               unknown block: video
  plan       : tasks create 215 · update 0 · unchanged 0 · comments add 281 (existing 0) · also-linked add 0
```

DB before: `schema_version 2`, tasks 0 · people 0 · comments 0 · links 0 · activity 0 — unchanged after the dry run (the log said "is at schema v2 (< 3) — plan assumes nothing imported yet"; no migration ran).

*Step 2 — the real import (same command without `--dry-run`):*

```
ℹ️ db: schema_version 2 → 3
Notion import — applied
  … (same counts as the dry run) …
  result     : tasks created 215 · updated 0 · unchanged 0 · comments added 281 (existing 0) · also-linked 0
             · links 134 · people created 134 (linked 0)
```

DB after: `schema_version 3`, tasks 215 · people 134 · comments 281 · links 134 · activity 215 (all `actor = notion-import`, `field = imported` — one per task); 0 duplicate `external_id` in tasks or comments; 0 `done` tasks without `done_at`.

*Step 3 — the second run:*

```
  result     : tasks created 0 · updated 0 · unchanged 215 · comments added 0 (existing 281) · also-linked 0 · links 0 · people created 0 (linked 0)
```

Table counts identical to the ones after step 2.

*Step 4 — read back through the running app (`tasks … --json`, `[tasks] via http: http://127.0.0.1:8448`):*

- `tasks ls --status all --json` → 215 tasks: status `todo 111 · done 104`; priority `none 150 · low 37 · medium 20 · high 8`; recurrence `weekly 8 · quarterly 5 · monthly 4 · yearly 3 · daily 1`; 143 with a `person`. `tasks ls --json` (open) → 111. `tasks people --json` → 134 people, 66 with open tasks.
- `tasks show <longest thread>` → 95 comments, all `origin = notion`, timestamps ascending (first 2024-08, last 2026-08), local ISO with offset; exactly one activity row (`notion-import · imported`); status `todo`, priority `high`, recurrence `weekly`, one link.
- `tasks show <a task with a person and a recurrence>` → the person's name present, `recurrence = yearly`, `created_at` from 2024 (the source's own timestamp), `external_id` set.
- `GET /api/version` on the running instance → `schema_version: 3`.

Observed = expected on every step. Two source pages have an empty title (imported as `(untitled)`, reported); nine `video` blocks degraded to their text (reported); no unmapped status / priority / recurrence values in the real data.

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite incl. the new `test_import_notion.py` (mapping, comments ordering, idempotency, dry-run, migration v3), e2e routed by the classifier for a backend/docs/scripts diff.
- [x] Dry run against the real database: report shown, nothing written.
- [x] Real import, second run a no-op, counts read back through the running app; long thread in order, person names, cadences.
- Not verified here: the imported table and thread **on screen in the browser** — the app's Board/Table/drawer views arrive with Step 4; this step's proof is the CLI/API read-back above.
