# Story 05 — Board day

**Issue:** #6 (Step 5/13). **Test:** `tests/e2e/test_story_05_board.py` (2 tests: the desktop leg at 1440×900 Chromium, the phone leg at 390×844 WebKit with touch), against the **seeded** disposable instance (`tests/fixtures/seed.py`, synthetic data only). Unit coverage for the new pieces: `tests/test_views.py` (`tasks_repo.board` / `today_view` — the done-today boundary at local midnight, status change moves the card, project / person filters, grouping by root with recurring first and overdue first, a recurring done rolls out of Today, the `/api/board` + `/api/today` route shapes).

**Steps → expected**

1. Open `/` on the desktop → the Board tab is active; **five columns** Inbox · Todo · Doing · Standby · Done today sit side by side across the full width (equal widths, one row), each header carries its count and the counts equal `GET /api/board`; *Done today* is empty (the seed's done tasks are weeks old) and shows the small empty state. A card shows its project line (*Home renovation*), the person, the due badge (overdue in the danger tone), the priority marker, the folder chip in the last comment, the issue chip (`example/garden-bot#12` → GitHub), the children count. No horizontal page scroll.
2. Pick *Home renovation* in the project select → the URL becomes `?project=<id>`, every card is a descendant of that project, the counts match `GET /api/board?project=<id>`; the **Table** tab's own project select shows the same choice (shared filter state); Clear returns to `/`.
3. Drag *Get three quotes* from Doing onto Standby → the card renders under Standby, Doing's count −1, Standby's +1; `GET /api/tasks/{id}` says `status = standby` and the newest activity row is `status doing → standby` (also first in `GET /api/activity?task=`).
4. Click the card → the drawer opens as the right-hand panel (`#task/{id}` in the URL, the columns stay visible to its left); its activity log's first row reads `status doing → standby` with actor and time.
5. Today tab → header `3 overdue · 5 due today`; groups by root project ordered by earliest due (*Home renovation* first — both rows overdue), then the loose tasks (*No project*), *Family admin*, *Learning*; inside *Family admin* the recurring *Dentist check-up* precedes *School enrolment forms* (person shown); *Later this week* is collapsed with its count.
6. Tick the recurring *Vocabulary review* (weekly, due today) → toast `Done — next: <today+7> (in 7d)`; the API shows the due rolled one week and status still `todo`, activity `due old → new`; the row leaves the due list and appears under *Later this week* once expanded; the header count drops to `4 due today`.
7. Tick *Return library books* (plain, overdue) → toast `Done: Return library books`; it leaves Today; the Board's **Done today** column shows it with count 1.
8. Phone (390 wide, touch, nothing persisted): the app **lands on Today**; rows and their checkboxes ≥ 44 px, non-overlapping, no horizontal overflow.
9. Phone Board: the count strip has five buttons (≥ 44 px, non-overlapping) and the columns are a **scroll-snap carousel** — one column as wide as the container, exactly one in view; tapping *Doing* on the strip scrolls the carousel to it and marks it active; each card carries a status select (≥ 44 px) as the touch stand-in for the drag.

**Screenshots (desktop 1440×900, phone 390×844) — saved by the test, same names the headed walk observed**

| Step | Desktop |
| --- | --- |
| 1 five columns, full width | [story-05-board-1-desktop.png](../screenshots/story-05-board-1-desktop.png) |
| 2 project chip filter (`?project=`) | [story-05-board-2-desktop.png](../screenshots/story-05-board-2-desktop.png) |
| 3 dragged doing → standby, counts updated | [story-05-board-3-desktop.png](../screenshots/story-05-board-3-desktop.png) |
| 4 drawer with the status activity row | [story-05-board-4-desktop.png](../screenshots/story-05-board-4-desktop.png) |
| 5 Today grouped by project | [story-05-board-5-desktop.png](../screenshots/story-05-board-5-desktop.png) |
| 6 recurring task rolled to next week | [story-05-board-6-desktop.png](../screenshots/story-05-board-6-desktop.png) |
| 7 Done today holds the ticked task | [story-05-board-7-desktop.png](../screenshots/story-05-board-7-desktop.png) |

| Phone | |
| --- | --- |
| 8 Today as the landing tab | [story-05-board-8-phone.png](../screenshots/story-05-board-8-phone.png) |
| 9 Board carousel, one column + strip | [story-05-board-9-phone.png](../screenshots/story-05-board-9-phone.png) |

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. `test_views`), the routed e2e (full tier: smoke + stories 01, 04, 05, Chromium desktop + WebKit phone).
- [x] On screen: walked headed (Chromium, 1440×900, then a 390×844 touch context) on a disposable instance of this build over a freshly seeded scratch database on another port (`TASKOS_DB_PATH` → scratch; never `data/tasks.db`): observed = expected on every step above — the Standby column lit up as the drop target while the card hovered, `status doing → standby · Roberto Ferraro · 17 Aug 11:04` in the drawer, the toasts `Done — next: 2026-08-24 (in 7d)` and `Done: Return library books`, *Return library books* under Done today, light and dark. Extras seen: quick-add on the Board (`walk the dog tomorrow`) focuses the new Inbox card; on the phone the carousel keeps its column across a re-render and a card's status select moves the card (Standby count 4 → 3). Zero page errors in the console.
- [x] Live app: `tray.bat --restart` → `/api/version` `git_sha == HEAD` (recorded in the PR).
- Not verified in this step: the geometry matrix on 320 / 430 / 772 (only 390 was walked and asserted); a real touch swipe on a physical phone (the carousel was driven with a programmatic scroll and the strip taps — Step 7 walks it on the device); drag-and-drop with a touch pointer (deliberately replaced by the status select on coarse pointers); the folder chip is display-only (opener = Step 9); the issue chip links to GitHub but nothing syncs (Step 8); the Board's `person` / text filters and Today's `?person=` were exercised through the unit tests and the API, not on screen.
