# Story 33 — Import a SharePoint list with its comments and history

**Issue:** #668. **Tests:** `tests/imports/test_import_sharepoint.py` (the synthetic dump `tests/fixtures/sharepoint_export.json` mapped and written; comment order with each reply after its parent; an append column read as one comment per version, by prefix, by suffix and rewritten; links from text and attachments without repeats; owner and unknown-member handling; a re-run changes nothing, byte for byte; a changed source updates only what changed; `--dry-run` writes nothing, not even the file; a missing dump exits 1; `sharepoint` accepted as a comment origin; the v20 → v21 rebuild keeps comments, their search, the unique key and the check), plus the bumped `tests/test_schema.py` (`schema_version` 21). No browser suite leg: the step adds no UI of its own, and the e2e suite is already over its target. The on-screen proof is the terminal transcript and a drawer read below, against a disposable instance.

**Real data stayed out.** No SharePoint list was read, fetched or imported at any point; the browser export script in `docs/sharepoint-import.md` was **not run** against a site. Every figure below comes from the synthetic dump. A first import of the owner's real list is the owner's check.

**Steps → expected**

1. `import_sharepoint --from-json <dump> --mapping config\sharepoint-mapping.sample.json --dry-run` against an empty scratch path → the report with counts and the unmapped values; the database file is not created.
2. The same command without `--dry-run` → schema v21, four tasks, eleven comments, seven links, one `imported` activity row per task.
3. The same command again → tasks created 0 · updated 0 · unchanged 4; comments existing 11; nothing added.
4. A disposable instance over that database (own port, scratch config with the mirror and backups blanked, never `:8448`), the first task opened by `#task/1` → the drawer shows the comments with their authors and original times, the `sharepoint` origin tag, the item, URL and attachment links, the contact, and the single `imported` row.

**Transcript — 2026-11-14, Windows, `scripts\import_sharepoint.bat` from the worktree, scratch database.**

*Step 1 — dry run (nothing written; the database file was not created):*

```
SharePoint import — DRY RUN (nothing written)
  items      : 4
  status     : todo 3 · done 1   (source: Completed 1 · In progress 1 · On hold 1 · null 1)
  priority   : none 2 · high 1 · medium 1   (source: (1) High 1 · (2) Normal 1 · (9) Odd 1 · null 1)
  due dates  : 2 set · body 1 · contact 2 · owner 1
  links      : 7 (item link, URLs in text, attachments)
  comments   : 11 on 3 items (versions read: 7)
  notes      : append column rewritten 1 · empty comment 1 · empty title 1 · extra people 1 · unmapped owner 1 · unmapped priority 1 · unmapped status 1
               unmapped status: On hold
               unmapped priority: (9) Odd
               unmapped owner: Person Z
  per item   : id comments versions → 1 7 3 · 2 2 2 · 3 2 2 · 4 0 0
  plan       : tasks create 4 · update 0 · unchanged 0 · comments add 11 (existing 0)
```

*Step 2 — import:* `result : tasks created 4 · updated 0 · unchanged 0 · comments added 11 (existing 0) · links 7 · people created 1 (linked 0)`.

*Step 3 — re-run:* `result : tasks created 0 · updated 0 · unchanged 4 · comments added 0 (existing 11) · links 0 · people created 0 (linked 0)`.

*Step 4 — the instance reported `schema_version 21`; the drawer of task 1 listed seven comments, newest first as the drawer always shows them, each tagged `sharepoint`: the three version entries held only their new text ("Kicked off.", the review line, "Sent for sign-off."), the thread kept its reply order, and the blank comment was absent.*

**Gallery.** Settings → Database prints the schema version, so six committed shots (stories 06, 09 and 24) moved from `version 20` to `version 21` and were re-baselined; a pixel crop of the changed region on one of them shows only that digit. The full e2e suite (16 tests) passed before and after.

**Not verified:** the console export script against a live SharePoint site, a first import of a real list, and a restart of the owner's tray on this build (the post-merge step records that separately).

**Result:** verified on synthetic data · the real-list import is the owner's checklist.
