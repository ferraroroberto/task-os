# Story 04 — Monday triage

**Issue:** #5 (Step 4/13). **Test:** `tests/e2e/test_story_04_triage.py` (2 tests: the desktop leg at 1440×900 Chromium, the phone leg at 390×844 WebKit with touch), against the **seeded** disposable instance (`tests/fixtures/seed.py`, synthetic data only). Unit coverage for the new pieces: `tests/test_quick_add.py` (the one-line parser + parent resolution), `tests/test_api.py` (list items carry `breadcrumb` / `root` / `last_comment`, natural `due` on create/update, `POST /api/parse`).

**Steps → expected**

1. Open `/?status=todo` → the Board tab, the `todo` status picked in the shared filter card: only the Todo column is up, holding exactly the `todo` tasks; no horizontal page scroll.
2. *Get three quotes* → ⋯ → **Change date** → **Pick a date…** opens the native calendar (`showPicker()`); the picked day lands — the row's date reads it and `GET /api/tasks/{id}` confirms it.
3. Click the row → the drawer opens as a **right-hand panel** (≥ 400 px, the Board stays fully visible to its left) with the breadcrumb `Home renovation › Kitchen`; the URL gains `#task/{id}`; the activity log's first row reads `due <old> → <new>` with actor and time.
4. Type a comment containing `https://example.com/passport-office`, Ctrl+Enter → it appears first (newest first) with `origin = ui`; the URL is an `<a target=_blank rel=noopener>` chip; clicking the chip opens the link in a new tab.
5. Quick-add: type `renew passport next friday` → a date chip appears under the bar with next Friday's ISO date and the phrase `(next friday)`.
6. Enter → toast `Added #N renew passport`; the task exists with that due and no parent (the `todo` filter hides a standby task; **Clear** shows it and returns to the default `/` view).
7. Open *renew passport* → the drawer's **Move to** → *Family admin* → toast `Moved "renew passport" under Family admin`; the API shows `parent_id = Family admin` and an activity row `parent`; the drawer's breadcrumb and the row's project both read `Family admin`. *Home renovation* moved under its own child *Kitchen* is refused with a `cycle` toast, nothing changed.
8. A fresh load of `/#task/N` opens the drawer with the clickable breadcrumb `Family admin`.
9. Phone (390 wide, touch): the Board's Todo column as the shared rows (circle · title over one meta line · ⋯), 44px targets that never overlap, the strip's filter · Select · `+` at the touch floor, Select's pressed label 4.5:1, no horizontal overflow.
10. Phone: tapping a row opens the drawer as a **full-screen sheet** (the bottom pill hides while it is up); close, select, send controls ≥ 44 px; closing brings the pill back.

**Screenshots (desktop 1440×900, phone 390×844) — saved by the test, same names the headed walk observed**

| Step | Desktop |
| --- | --- |
| 1 Board `status:todo` | [story-04-triage-1-desktop.png](../screenshots/story-04-triage-1-desktop.png) |
| 2 due changed from the row's ⋯ | [story-04-triage-2-desktop.png](../screenshots/story-04-triage-2-desktop.png) |
| 3 drawer + activity old → new | [story-04-triage-3-desktop.png](../screenshots/story-04-triage-3-desktop.png) |
| 4 comment with link chip | [story-04-triage-4-desktop.png](../screenshots/story-04-triage-4-desktop.png) |
| 5 quick-add parsed date chip | [story-04-triage-5-desktop.png](../screenshots/story-04-triage-5-desktop.png) |
| 6 created, filter cleared | [story-04-triage-6-desktop.png](../screenshots/story-04-triage-6-desktop.png) |
| 7 moved under *Family admin* (drawer's Move to) | [story-04-triage-7-desktop.png](../screenshots/story-04-triage-7-desktop.png) |
| 8 deep link with the breadcrumb | [story-04-triage-8-desktop.png](../screenshots/story-04-triage-8-desktop.png) |

| Phone | |
| --- | --- |
| 9 the Board's rows | [story-04-triage-9-phone.png](../screenshots/story-04-triage-9-phone.png) |
| 10 drawer as full-screen sheet | [story-04-triage-10-phone.png](../screenshots/story-04-triage-10-phone.png) |

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. `test_quick_add`, the new `test_api` cases), the routed e2e (full tier: smoke + story 01 + story 04, Chromium desktop + WebKit phone).
- [x] On screen: walked headed (Chromium, 1440×900, then the drawer at 390) on a disposable instance of this build over a freshly seeded scratch database on another port (`TASKOS_DB_PATH` → scratch; never `data/tasks.db`): observed = expected on every step above — `2026-08-20 → 2026-08-28` in the activity row with actor + time, two chips in the new comment (URL + folder ref), the quick-add chip `2026-08-28 · in 11d (next friday)`, the move toast, the cycle refusal, the breadcrumb in the Table, the deep link, light and dark. Zero page errors in the console.
- [x] Live app: `tray.bat --restart` → `/api/version` `git_sha == HEAD` (recorded in the PR).
- Not verified in this step: the geometry matrix on 320 / 430 / 772 (only 390 was walked and asserted); the folder chip is display-only (the per-machine opener is Step 9); the issue panel shows the seed's `issue_ref` but no provider sync (Step 8); phone drag-and-drop (HTML5 DnD needs a pointer — the phone re-parents through the desktop or a future long-press); Board / Today / Search panes show a "arrives with a later step" placeholder.

**2026-10-05 (#350):** the Table tab (grid and Tree) was removed. The story runs on the Board: the due change goes through the row's ⋯ → Change date (the grid's due cell is gone), the re-parent through the drawer's Move to (the Tree's drag is gone), and the grid-only checks — the breadcrumb, project and last-comment columns and their chips — are dropped with the grid. Re-walked by the e2e suite; shots re-baselined.

**2026-10-10 (#391):** the date sheet. *Change date* lists the push-outs first, *Tomorrow · This weekend · Next week · Today*, each with the date it resolves to beside it, read from `GET /api/dates` (the same `src/dates.py` rule and clock the write uses). Step 2 asserts the order and every date against the API (`assert_date_sheet` in `tests/e2e/conftest.py`), plus *Tomorrow* = the anchor + 1 day. Unit: `tests/test_api.py::test_dates_endpoint_*` (a Saturday clock: *this weekend* is today; the date shown for *next week* is the date the PATCH writes). Result: **verified** (e2e desktop).
