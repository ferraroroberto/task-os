# Story 04 — Monday triage

**Issue:** #5 (Step 4/13). **Test:** `tests/e2e/test_story_04_triage.py` (2 tests: the desktop leg at 1440×900 Chromium, the phone leg at 390×844 WebKit with touch), against the **seeded** disposable instance (`tests/fixtures/seed.py`, synthetic data only). Unit coverage for the new pieces: `tests/test_quick_add.py` (the one-line parser + parent resolution), `tests/test_api.py` (list items carry `breadcrumb` / `root` / `last_comment`, natural `due` on create/update, `POST /api/parse`).

**Steps → expected**

1. Open `/?status=doing` → the Table tab is active with the `doing` chip pressed; only `doing` rows (7 in the seed); nested titles show their breadcrumb (`Home renovation › Kitchen` under *Get three quotes*), the project column is the top ancestor, the last comment renders its `{onedrive}/…` reference as a folder chip; no horizontal page scroll.
2. Click the due cell of *Get three quotes*, type `in 2 weeks`, Enter → the cell shows the new date (ISO in the tooltip); `GET /api/tasks/{id}` confirms it.
3. Click the row → the drawer opens as a **right-hand panel** (≥ 400 px, the table stays fully visible to its left); the URL gains `#task/{id}`; the activity log's first row reads `due <old> → <new>` with actor and time.
4. Type a comment containing `https://example.com/passport-office`, Ctrl+Enter → it appears first (newest first) with `origin = ui`; the URL is an `<a target=_blank rel=noopener>` chip; the Table's *last comment* cell shows the same chip; clicking the chip opens the link in a new tab.
5. Quick-add: type `renew passport next friday` → a date chip appears under the bar with next Friday's ISO date and the phrase `(next friday)`.
6. Enter → toast `Added #N renew passport`; the task exists with that due and no parent (the `doing` filter hides an inbox task; **Clear** shows it and returns to the default `/` view).
7. Tree tab → collapse the four projects (state persists in `localStorage`) → drag *renew passport* onto *Family admin* → toast `Moved "renew passport" under Family admin`; the API shows `parent_id = Family admin`, an activity row `parent ∅ → id`; expanding *Family admin* shows the node nested at level 2 with the rollup updated. Dragging *Family admin* onto its own child is refused with a toast naming the cycle; nothing changes.
8. Table tab → the row *renew passport* now carries the breadcrumb `Family admin` and project `Family admin`. A fresh load of `/#task/N` opens the drawer with the clickable breadcrumb.
9. Phone (390 wide, touch): the table renders as stacked cards (no header row, secondary columns hidden), no horizontal overflow, quick-add / filter chips / status selects / due buttons ≥ 44 px, non-overlapping.
10. Phone: tapping a row opens the drawer as a **full-screen sheet** (the bottom pill hides while it is up); close, select, send controls ≥ 44 px; closing brings the pill back.

**Screenshots (desktop 1440×900, phone 390×844) — saved by the test, same names the headed walk observed**

| Step | Desktop |
| --- | --- |
| 1 Table `status:doing` | [story-04-triage-1-desktop.png](../screenshots/story-04-triage-1-desktop.png) |
| 2 inline due edit | [story-04-triage-2-desktop.png](../screenshots/story-04-triage-2-desktop.png) |
| 3 drawer + activity old → new | [story-04-triage-3-desktop.png](../screenshots/story-04-triage-3-desktop.png) |
| 4 comment with link chip | [story-04-triage-4-desktop.png](../screenshots/story-04-triage-4-desktop.png) |
| 5 quick-add parsed date chip | [story-04-triage-5-desktop.png](../screenshots/story-04-triage-5-desktop.png) |
| 6 created, filter cleared | [story-04-triage-6-desktop.png](../screenshots/story-04-triage-6-desktop.png) |
| 7 dragged under *Family admin* | [story-04-triage-7-desktop.png](../screenshots/story-04-triage-7-desktop.png) |
| 8 breadcrumb in the Table | [story-04-triage-8-desktop.png](../screenshots/story-04-triage-8-desktop.png) |

| Phone | |
| --- | --- |
| 9 table as cards | [story-04-triage-9-phone.png](../screenshots/story-04-triage-9-phone.png) |
| 10 drawer as full-screen sheet | [story-04-triage-10-phone.png](../screenshots/story-04-triage-10-phone.png) |

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. `test_quick_add`, the new `test_api` cases), the routed e2e (full tier: smoke + story 01 + story 04, Chromium desktop + WebKit phone).
- [x] On screen: walked headed (Chromium, 1440×900, then the drawer at 390) on a disposable instance of this build over a freshly seeded scratch database on another port (`TASKOS_DB_PATH` → scratch; never `data/tasks.db`): observed = expected on every step above — `2026-08-20 → 2026-08-28` in the activity row with actor + time, two chips in the new comment (URL + folder ref), the quick-add chip `2026-08-28 · in 11d (next friday)`, the move toast, the cycle refusal, the breadcrumb in the Table, the deep link, light and dark. Zero page errors in the console.
- [x] Live app: `tray.bat --restart` → `/api/version` `git_sha == HEAD` (recorded in the PR).
- Not verified in this step: the geometry matrix on 320 / 430 / 772 (only 390 was walked and asserted); the folder chip is display-only (the per-machine opener is Step 9); the issue panel shows the seed's `issue_ref` but no provider sync (Step 8); phone drag-and-drop (HTML5 DnD needs a pointer — the phone re-parents through the desktop or a future long-press); Board / Today / Search panes show a "arrives with a later step" placeholder.
