# Story 10 — Find anything

**Issue:** #11 (Step 10/13). **Test:** `tests/e2e/test_story_10_search.py` (one Chromium walk: 1440×900 desktop, then a 390-wide touch context) against a **seeded disposable instance whose four indexes are all fixtures**: `{onedrive}` → a temp tree the folder index scans, `search.email_db` → the synthetic email-archiver index `tests/fixtures/emails_fixture.py` builds under that tree (six made-up emails, the archiver's real DDL — `emails` + FTS5 `emails_fts` + triggers), the issue provider → the file-backed fake (`TASKOS_ISSUE_PROVIDER=fake`, never `gh`). Unit coverage for the gate: `tests/test_search_adapters.py` — the four adapters (tasks on the seed; folders on the temp tree incl. the *not configured* / *index empty* states; emails on the fixture: bm25 order subject > body, prefix + AND, sender hits, ref folding onto `{onedrive}` vs an absolute path, **read-only** connection proven with a refused INSERT and no WAL sidecar, the LIKE fallback on a pre-FTS layout, the three not-configured reasons; issues over local refs merged with the cached labels, a cached issue with no task, the not-configured reason), the federated layer (always four groups in order, `kinds=` → `skipped`, `status()`, a slow adapter → `timed out` on its own group while the others answer, a raising adapter → `error`), `GET /api/search` + `/api/search/status`, `tasks search` local + `--json` + `--kind`.

**Steps → expected**

1. Search tab → the box is focused → type `kitchen` → **four cards** Tasks (3) · Folders (2) · Emails (2) · Issues (1), full width, every row with the kind glyph, title, subtitle, the matched terms as `<mark>`; `?q=kitchen` in the URL; *8 hits · N ms* in the box; Attach buttons disabled (no task open).
2. **Open** on the *Kitchen* task row → the drawer opens beside the results → the email row's **Attach** enables → click → toast *Email attached to #2: Kitchen quotes from the installer* → the drawer's Links section shows the chip (mail glyph, `taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse…`) → the API has `links(kind=email, url={onedrive}/mail/house/2026-08-10 Kitchen quotes.msg, label=subject)`.
3. **New task** on the *plans* folder row → toast *Task #47 created: plans* → the drawer opens on it with the folder chip `taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen%2Fplans`; `folder_ref` / `folder_resolved` set. The folder row's **Open** chip hands the ref to the opener (intercepted in the walk; the real hand-off is Step 9's verified leg) and the one-time hint appears. Keyboard: `↓` from the box focuses the first row, `↓` again the second, `Enter` opens that task.
4. `Ctrl+K` from the Today tab → the palette (vendored dialog shell) with the input focused → type `passports` → *Renew passports · doing · Family admin* → `Enter` → the palette closes, the drawer opens on it.
5. The ⌘ header button → `>go to` → the six *Go to …* commands (dark theme) → `Enter` on *Go to Board* → the Board tab is active. `GET /api/search?q=kitchen&kinds=tasks` returns the other three groups `skipped:true` (the API contract for "not asked" vs "empty").
6. Phone (390 wide, coarse pointer): `/?q=kitchen#search` lands on the Search tab with the box pre-filled and the four cards as a one-column list, actions under each row.
7. Phone: the ⌘ button → the palette as a full-width sheet → `water` → *Pay water bill*.
8. **Headed walk (real Chrome, disposable instance with `issues.provider` blank):** the Issues card renders *not configured — issues.provider is blank in config — no issue sync · Settings* under the three populated groups — the visible state, never a blank.
9. **Headed walk:** the *Settings* link → **Settings → Search**: *3 of 4 indexes* — Tasks ready · Folders ready · Emails ready · Issues not configured with the reason; then `Ctrl+K` → `>reindex` → `Enter` ran *Reindex folders* (toast *Folder index: 11 folder(s) in 0 s*).

**Screenshots (1440×900 unless noted) — 1–7 saved by the test, 8–9 from the headed walk**

| Step | Shot |
| --- | --- |
| 1 `kitchen`: four groups, full width | [story-10-search-1-desktop.png](../screenshots/story-10-search-1-desktop.png) |
| 2 drawer open + the email attached (link in the drawer) | [story-10-search-2-desktop.png](../screenshots/story-10-search-2-desktop.png) |
| 3 task created from a folder hit (folder chip in the drawer) | [story-10-search-3-desktop.png](../screenshots/story-10-search-3-desktop.png) |
| 4 `Ctrl+K`: jump to a task | [story-10-search-4-desktop.png](../screenshots/story-10-search-4-desktop.png) |
| 5 `Ctrl+K`: `>` commands (dark) | [story-10-search-5-desktop.png](../screenshots/story-10-search-5-desktop.png) |
| 6 phone: results (390×844) | [story-10-search-6-phone.png](../screenshots/story-10-search-6-phone.png) |
| 7 phone: the palette sheet | [story-10-search-7-phone.png](../screenshots/story-10-search-7-phone.png) |
| 8 **real Chrome**: Issues *not configured — reason · Settings* under three populated groups | [story-10-search-8-desktop.png](../screenshots/story-10-search-8-desktop.png) |
| 9 **real Chrome**: Settings → Search card, 3 of 4 indexes | [story-10-search-9-desktop.png](../screenshots/story-10-search-9-desktop.png) |

**Result — 2026-08-17: verified (fixture indexes on screen; the real email index through the CLI, counts only).**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. `test_search_adapters`), the routed e2e (full tier — the diff touches `app/webapp/`).
- [x] On screen (Chromium, then real Chrome): steps 1–9 above, shots 1–9.
- [x] **Real email index (18,332 rows), through the CLI on a disposable seeded DB with the real config** (`TASKOS_DB_PATH=<temp>`, `tasks --local search "<word>" --kind emails --json`): three everyday words → 20 · 16 · 20 hits (per-group limit 20) in **10 · 6 · 61 ms** adapter time (40–94 ms wall incl. Python start-up of the local backend). Content stays off screen; only the counts and timings are recorded. The adapter opened the file `mode=ro`; no `-wal` / `-shm` sidecar was created next to the archiver's database.
- [x] Live app after `tray.bat --restart`: `GET /api/version` `git_sha` == HEAD; `GET /api/search/status` on `:8448` reports the four adapters with this install's states (tasks · folders · emails ready; issues per the provider) — read-only checks, nothing typed into the real database.
- [ ] **Not verified — opening a `.msg` hit through the opener.** The email row's Open chip is the same `taskos://open?ref=…` link Step 9 verified for folders (Explorer on PC #1); a *file* ref goes through the same `opener.cmd` branch (`start "" "<path>"` → default app), which `tests/test_opener.py` drives dry-run for a file ref, but no real click on a real `.msg` was walked in this step. Owner's check: search a subject in the live app → **Open** on the email row → Outlook (or the default `.msg` handler) opens the message.
- Not verified, by design: the palette on a real phone (browser emulation only, same leg story 07 left open); the issue adapter against the real GitHub cache (the fake provider on screen; the real sync is Step 8's verified leg — the adapter reads its cache with no forge call).
- Deviations from the brief: none in scope. Notes — the four groups' *took_ms* are shown per card so a slow index is visible; `?q=` is owned by the Search tab only while that tab shows (the Table's filter bar owns it otherwise) and `/?q=…#search` is the deep link; the folder path in a hit is this PC's resolved path (as the Step 9 chip tooltip).
