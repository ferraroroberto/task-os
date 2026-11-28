# Story 03 — Import my Notion

**Issue:** #4 (Step 3/13). **Tests:** `tests/test_import_notion.py` (mapping table for status / priority / recurrence, block → markdown incl. nested children and tables, the whole synthetic export `tests/fixtures/notion_export.json` mapped and written, comment ordering + author fallback, idempotency — run twice, same counts, no duplicates — a re-import that applies source changes without duplicating, `--dry-run` writes nothing (not even a file), `--limit` + `--json-dump` round-trip, migration v2 → v3 + idempotent + the unique index), plus the bumped `test_schema.py` / `test_api.py` (`schema_version` 3). No browser leg — this step has no UI surface of its own; the on-screen proof is the terminal transcript below and the CLI read-back through the running app.

**Steps → expected**

1. `import_notion --dry-run --database-id <id> --env-file <path>\.env --db <live db>` → the report: page count, counts per status / priority / recurrence, comments, people, anything unmapped or skipped, and the plan (create / update / unchanged); nothing written, no migration.
2. The real import → schema migrated to v3, every page a task with status, priority, due, recurrence, description, links, comments (original timestamps, `origin = notion`, thread order), the linked person; one `imported` activity row per task.
3. Re-run the same command → tasks created 0 · updated 0 · unchanged N; comments existing N; nothing changes.
4. `tasks ls` / `tasks show` through the running app → the counts, a long comment thread intact and in order with dates, a task with a person shows the name, recurring cadences set.

**Walk — 2026-08-17, Windows, `scripts/import_notion.py` against a real database, app running throughout.** All four steps observed as expected: the dry run reported and wrote nothing, the real run migrated the schema and created every page as a task with its fields, comments and person, the second run changed nothing, and the CLI read the same totals back through the running app. Counts and content from that run are not recorded here.

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite incl. the new `test_import_notion.py` (mapping, comments ordering, idempotency, dry-run, migration v3), e2e routed by the classifier for a backend/docs/scripts diff.
- [x] Dry run against the real database: report shown, nothing written.
- [x] Real import, second run a no-op, counts read back through the running app; long thread in order, person names, cadences.
- Not verified here: the imported table and thread **on screen in the browser** — the app's Board/Table/drawer views arrive with Step 4; this step's proof is the CLI/API read-back above.
