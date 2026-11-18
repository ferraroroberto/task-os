# Story 05 — Board day

**Issue:** #6 (Step 5/13). **Test:** `tests/e2e/test_story_05_board.py` (2 tests: the desktop leg at 1440×900 Chromium, the phone leg at 390×844 WebKit with touch), against the **seeded** disposable instance (`tests/fixtures/seed.py`, synthetic data only). Unit coverage for the new pieces: `tests/test_views.py` (`tasks_repo.board` / `today_view` — the done-today boundary at local midnight, status change moves the card, project / person filters, grouping by root with recurring first and overdue first, a recurring done rolls out of Today, the `/api/board` + `/api/today` route shapes).

**Steps → expected**

1. Open `/` on the desktop → the Board tab is active; **four columns** Inbox · Todo · Standby · Done today sit side by side across the full width (equal widths, one row), each header carries its count and the counts equal `GET /api/board`; *Done today* is empty (the seed's done tasks are weeks old) and shows the small empty state. A card shows its project line (*Home renovation*), the person, the due badge (overdue in the danger tone), the priority marker, the folder chip in the last comment, the issue chip (`example/garden-bot#12` → GitHub), the children count. No horizontal page scroll.
2. Pick *Home renovation* in the project select → the URL becomes `?project=<id>`, every card is a descendant of that project, the counts match `GET /api/board?project=<id>`; the **Today** tab's own project select shows the same choice (shared filter state); Clear returns to `/`.
3. Drag *Get three quotes* from Todo onto Standby → the card renders under Standby, Todo's count −1, Standby's +1; `GET /api/tasks/{id}` says `status = standby` and the newest activity row is `status todo → standby` (also first in `GET /api/activity?task=`).
4. Click the card → the drawer opens as the right-hand panel (`#task/{id}` in the URL, the columns stay visible to its left); its activity log's first row reads `status todo → standby` with actor and time.
5. Today tab → header `3 overdue · 5 due today`; groups by root project ordered by earliest due (*Home renovation* first — both rows overdue), then the loose tasks (*No project*), *Family admin*, *Learning*; inside *Family admin*, both due today, *School enrolment forms* (high priority, person shown) precedes the recurring *Dentist check-up* — the tie breaks on priority, not on which row recurs (#116); *Later this week* is collapsed with its count.
6. Tick the recurring *Vocabulary review* (weekly, due today) → toast `Done — next: <today+7> (in 7d)`; the API shows the due rolled one week and status still `todo`, activity `due old → new`; the row leaves the due list and appears under *Later this week* once expanded; the header count drops to `4 due today`.
7. Tick *Return library books* (plain, overdue) → toast `Done: Return library books`; it leaves Today; the Board's **Done today** column shows it with count 1.
8. Phone (390 wide, touch, nothing persisted): the app **lands on Today**; rows and their checkboxes ≥ 44 px, non-overlapping, no horizontal overflow.
9. Phone Board: the count strip has four buttons (≥ 44 px, non-overlapping) and the columns are a **scroll-snap carousel** — one column as wide as the container, exactly one in view; tapping *Standby* on the strip scrolls the carousel to it and marks it active; each card carries a status select (≥ 44 px) as the touch stand-in for the drag.

**Screenshots (desktop 1440×900, phone 390×844) — saved by the test, same names the headed walk observed**

| Step | Desktop |
| --- | --- |
| 1 four columns, full width | [story-05-board-1-desktop.png](../screenshots/story-05-board-1-desktop.png) |
| 2 project chip filter (`?project=`) | [story-05-board-2-desktop.png](../screenshots/story-05-board-2-desktop.png) |
| 3 dragged todo → standby, counts updated | [story-05-board-3-desktop.png](../screenshots/story-05-board-3-desktop.png) |
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
- [x] On screen: walked headed (Chromium, 1440×900, then a 390×844 touch context) on a disposable instance of this build over a freshly seeded scratch database on another port (`TASKOS_DB_PATH` → scratch; never `data/tasks.db`): observed = expected on every step above — the Standby column lit up as the drop target while the card hovered, `status todo → standby · Roberto Ferraro · 17 Aug 11:04` in the drawer, the toasts `Done — next: 2026-08-24 (in 7d)` and `Done: Return library books`, *Return library books* under Done today, light and dark. Extras seen: quick-add on the Board (`walk the dog tomorrow`) focuses the new Inbox card; on the phone the carousel keeps its column across a re-render and a card's status select moves the card (Standby count 4 → 3). Zero page errors in the console.
- [x] Live app: `tray.bat --restart` → `/api/version` `git_sha == HEAD` (recorded in the PR).
- Not verified in this step: the geometry matrix on 320 / 430 / 772 (only 390 was walked and asserted); a real touch swipe on a physical phone (the carousel was driven with a programmatic scroll and the strip taps — Step 7 walks it on the device); drag-and-drop with a touch pointer (deliberately replaced by the status select on coarse pointers); the folder chip is display-only (opener = Step 9); the issue chip links to GitHub but nothing syncs (Step 8); the Board's `person` / text filters and Today's `?person=` were exercised through the unit tests and the API, not on screen.

**2026-10-05 (#350):** the Table view (grid and Tree) was removed. Step 2's shared-filter check reads Today's card instead of the Table's.

**2026-10-11 (#396):** the Board is a week planner with the status columns behind a **Week · Status** segment (Week the default, remembered on the device) and the Mine · Issues · All switch beside it. Step 1 now opens on Week: the seven lanes of the anchor Monday side by side, each holding exactly the open Mine tasks due in its days (checked against `/api/tasks` with the lane rule stated as dates), the header *4 in Inbox · 3 overdue* (accent, then attention); dragging *Book appointment* from Tomorrow onto This weekend moves its due to Saturday and changes nothing else (every other field compared before and after, the newest activity row `due`), the toast reads *Due Sat 12 Sep*, and Undo puts it back. Then the Status segment: the four columns as before, the empty Done today collapsed to its header, Triage on the mode line. A column the text filter empties collapses; a filter that empties every lane shows one *Nothing on the board* state whose action opens quick-add (the per-column *Add to …* actions went; quick-add's Status select still files a task into any column). The phone leg adds Week mode as one list of lane sections (shot 14 phone), then Status with the empty Done column out of the strip and the carousel. [Shot 14 desktop](../screenshots/story-05-board-14-desktop.png) · [shot 14 phone](../screenshots/story-05-board-14-phone.png).

**2026-10-12 (#414):** the Week board fits the window. The seven lanes overflowed sideways (each non-empty lane was forced to 18rem, so the board scrolled at 1280 and at 1920px: `scrollWidth` 2016 against `clientWidth` 1161 and 1801); *No date* is folded into the end of *Later* under a sub-heading, leaving six lanes that share the width. Step 1 now asserts the six lanes, `scrollWidth <= clientWidth` on the week board at 1280, 1920 and 1440px, and the *No date* group after the dated tasks in *Later* (the lane count holding both); the same step moves *Repaint ceiling* to *No date* through the row menu and the Move sheet (the toast reads *Due date cleared*, the task lands under the sub-heading, Undo restores its date). Run against the old code the test fails on the lane list. Re-baselined: the desktop shots that show the Week board ([shot 14 desktop](../screenshots/story-05-board-14-desktop.png), stories 09, 11, 13 and 20). Phone layout unchanged. Not verified: a headed walk on the real install.

**2026-10-18, #476 (an owner per task, Step 3/4 of #471):** two steps folded in, with no new test function (the suite is over its target). Desktop step 11b: two cards ticked, the bulk bar's **Set owner…** (a person-glyph square, only with two or more members; its options *Person 1 · Person 2*) picks *Person 2* → both tasks are `p2` on the server, each with an `owner p1 → p2` activity row, and the third card stays `p1`. Desktop step 15 and phone step 11b (`_walk_drawer_owner`): the drawer head carries **Owner** on the same row as Status and Priority; picking the other member answers 200, the activity log reads `owner Person 2 → Person 1` by name, and a reload keeps the pick (desktop panel and the phone's full-screen drawer, the select a 44px target there, no sideways scroll). The bar's geometry checks now count five controls; on the phone, with the owner square showing, the count drops the word *selected* so *Set status…* stays readable. New shots [story-05-board-15-desktop.png](../screenshots/story-05-board-15-desktop.png) · [story-05-board-15-phone.png](../screenshots/story-05-board-15-phone.png); every drawer and bulk-bar shot that shows the new control is re-baselined. Dark theme looked at on a disposable seeded instance (drawer head at 1440 and 390, the bulk bar with the owner square focused): the select takes the dark control tokens and the focus ring shows. Screenshots reviewed in the session, not committed. Unit: `tests/test_owner.py` (the v19 → v20 migration keeps every table's row count, every `person_id` and every `time_entries.person`; the NULL rule; create as the member behind a spoofed non-loopback token and as the owner on loopback; a subtask is its creator's; PATCH, bulk and the 422; the `owner` filter with NULL counting as the install owner's; one member; `migrate_dry_run.py` leaves the source's mtime and hash alone; `assign_owner.py` writes nothing without `--apply`) and `tests/test_cli.py::test_owner_over_both_backends`. Result: **verified** (unit, e2e desktop and phone). **Not verified:** the second person's real phone on the live install.

**2026-10-18, #477 (Mine by default, Everyone on one tap, Step 4/4 of #471):** folded into the existing test, no new test function (the suite is over its target). The existing scope reads **Tasks · Issues · All** (ids and the `?scope=` URL key unchanged) and a separate **Mine · Everyone** switch sits beside it on Today and the Board, only with two or more members. Desktop step 11c: the two tasks the bulk bar just handed to *Person 2* are off the owner's Board, one tap on Everyone brings them back and the walk goes on under it. `_walk_whose_switch` (after step 15): the pick is on the URL (`?whose=everyone`, Mine writes no key) and on the device (`task-os.whose`); a reload with no key keeps Everyone; an explicit `?whose=mine` beats the stored Everyone and never rewrites it; the journal follows (a closed task handed to the second member is off it on Mine, on it under Everyone); an explicit `?whose=everyone` beats a stored Mine; the task is handed back at the end. `_walk_second_member_phone`: a WebKit phone presenting the second member's token (`GET /api/me` says `p2`) opens Today on *Water the ferns* and *Order paint samples* only, no picker step, labels inside their segments, 44px targets, no sideways scroll; one tap on Everyone shows both members' tasks and writes `?whose=everyone`; the Board shares the pick and a reload keeps it; a second device (no member token, fresh store) opens on Mine, the owner's tasks, none of theirs; the Board in dark. `_walk_one_member`: a throwaway instance with one member has no `.whose-switch` on Today or the Board. The phone Board puts the two scope switches on one row and Week · Status on the one under it (seven segments on one 390px row ran *Mine* into *Everyone* in the first dark shot; fixed, and `_assert_labels_fit` now pins it). New shots [story-05-board-16-desktop.png](../screenshots/story-05-board-16-desktop.png) · [story-05-board-17-phone.png](../screenshots/story-05-board-17-phone.png) · [story-05-board-18-phone.png](../screenshots/story-05-board-18-phone.png) · [story-05-board-19-phone-dark.png](../screenshots/story-05-board-19-phone-dark.png); the renamed label and the new switch shifted 102 existing shots across the gallery (re-baselined, listed in the PR). Unit: `tests/test_scope.py` (the `whose` URL key written only for Everyone, an explicit value beating the stored pick, the stored pick's fallbacks including a throwing store, never counted as a filter, `ownerOf` / `listParams` narrowing only with two or more members and a known viewer). Result: **verified** (unit, e2e desktop and phone, both themes on the phone Board; the shots reviewed in the session). **Not verified:** a headed manual walk, and the second person's real phone on the live install (the owner's step).

## Board order and pills (2026-11-15)

**Story:** the owner reads a lane for what is due first. Rows no longer cluster by project: a project's item due in two days no longer sits below another project's item due in three.

**Steps:** open the Board on Week → inside each lane the rows run by due day; within one day the tasks with no project come first, then the projects A–Z, then the title A–Z → each row leads its title with its project as a pill (the vendored chip) → switch to Everyone → each row also carries a neutral pill naming its assignee, on the meta line → back to Mine → no assignee pill, because every row is yours → pick a sort in the filter sheet (priority, modified …) → that order replaces the day order. The project filter is the filter button beside the text field, one tap from the Board, and its sheet holds the Project select.

**Expected:** `sortBoardItems` (`rows.js`) orders by due day, then project name (none first), then title, both name keys case-insensitive with digit runs read as numbers, then id; any sort other than the default `due` keeps its own meaning. The project leaves the meta line for the pill, and a task with a project shows no issue code in its place. The assignee pill exists only while the whose switch is on Everyone with two or more members.

**Screenshots:** [Everyone, Status columns](../screenshots/story-05-board-16-desktop.png) · [Week list on the phone](../screenshots/story-05-board-14-phone.png) · [Week lanes on the desktop](../screenshots/story-05-board-14-desktop.png); every other Board shot now shows the pills.

**Test:** `tests/webapp/test_board_order.py` (the comparator under node, written red first: all eight cases failed on the missing function before the code existed); `tests/e2e/test_story_05_board.py` — the Everyone step asserts the assignee pill on the handed-over row and the Mine step asserts none; the project assertions in stories 04 and 08 read the pill.

**Result:** the unit and e2e legs pass on the disposable seeded instance, synthetic data only. The first layout put both pills before the title and the narrow desktop lanes squeezed them to blank stubs, so the assignee sits on the meta line, and a lane under 280px wide (the six Week lanes of a desktop window) shows the project pill there too, in the context slot, so the title keeps its width; a wider lane leads the title with it. **Not verified:** a headed walk by hand, the dark-mode pills beyond the tokens the chip already carries, and a real phone. Date: 2026-11-15.

### Person row: several people on the Board at once (Today shares it)

**Story:** the Board is shared by several people, and the owner wants to look at another person's tasks, or a few people side by side, without opening the filter sheet. The Mine · Everyone switch becomes a row of person pills: Mine first, each member, Everyone last; a tap toggles a person, so two or more can be on at once.

**Steps:** open the Board as the first member → the row reads Mine · Person 2 · Everyone with Mine filled → Everyone → both members' tasks, each card naming its assignee → Person 2 → only their tasks → Mine as well → both filled, the URL carries `owner=p2,p1`, each card names its assignee, a reload keeps it → Person 2 again → Mine alone, no key. On the second member's phone the row reads Mine · Person 1 · Everyone and scrolls sideways if it must. On an install with eight members the row reads Mine · five people · +2 more · Everyone; +2 more opens a sheet with a name filter, ticking a person there puts them in the row and in the URL, and they lead the row after a reload.

**Expected:** `filters.js` (`toggleOwner`, `pickedOwners`, `showsAssignees`, `visibleOwners`) and the `owner` key behave as `tests/test_scope.py` pins them under node; the pill row (`js/app/owners.js`) draws that state and nothing else; every pill is a 44px target and no label is clipped.

**Screenshots:** [Mine and Person 2 on the Board](../screenshots/story-05-board-20-desktop.png) · [the row on the phone](../screenshots/story-05-board-17-phone.png) · [dark](../screenshots/story-05-board-19-phone-dark.png)

**Test:** `tests/test_scope.py` (the pure rules, written with the code); `tests/e2e/test_story_05_board.py` — `_walk_whose_switch` (picking two people), `_walk_second_member_phone`, `_walk_many_members` (the "+N more" sheet); folded into the existing test, no new test function.

**Result:** the unit and e2e legs pass on disposable seeded instances, synthetic data only; the desktop, phone and dark shots were looked at. **Not verified:** a headed walk by hand, a real phone's sideways scroll, and the "+N more" sheet's phone layout (it reuses the parent picker's full-screen shell; no shot). Date: 2026-11-15.

## The person row is the segmented control (#696)

**Story:** the owner wants the person switcher above the Board and Today to look and behave like the Tasks · Issues · All switch under it.

**Steps:** Today as the second member on a 390px phone → the row reads Mine · Person 1 · Everyone as the vendored segmented control, same track, height, radius and raised selected segment as the scope switch under it, in light and dark → a tap on Person 1 raises that segment alone and lists only their tasks (`owner=p1`) → Everyone again. On the desktop Board, Everyone → Person 2 alone (no assignee pill, every card is theirs; a reload keeps it) → a link naming two people (`owner=p1,p2`) lists both with no segment raised → Mine, no key. On an install with eight members the row holds five segments, Mine · Person 2 · Person 3 · +5 more · Everyone; +5 more opens the sheet, a tick there picks several people and +5 more is the raised segment, the picked person leads the row after a reload, and a tap on a person in the row picks that one alone.

**Expected:** the row is single-choice (several people are picked only in the "+N more" sheet); every segment is a 44px target and no label runs into the next; the row keeps one line on a 390px phone with no sideways scroll; the choice is still remembered per device (`task-os.whose`) and in the URL.

**Screenshots:** [the row on the phone, light](../screenshots/story-05-board-17-phone.png) · [dark](../screenshots/story-05-board-19-phone-dark.png) · [one person on the Board](../screenshots/story-05-board-20-desktop.png)

**Test:** `tests/e2e/test_story_05_board.py` — `_walk_whose_switch` (one person at a time), `_walk_second_member_phone` (a person tap on the phone), `_walk_many_members` (the "+N more" sheet); folded into the existing test, no new test function. Every Board, Today, Search and keyboard-triage shot that shows the row is re-baselined.

**Result:** the e2e legs pass on disposable seeded instances, synthetic data only; the phone shots were looked at in light and dark. **Not verified:** a headed walk by hand, a real phone. Date: 2026-11-15.

## One Filters & sort sheet for Today and Board (#744)

**Story:** the owner wants one filter field and then the content on Today and the Board: the Week · Status switch, Tasks · Issues · All, the person row and Triage no longer sit in rows above the list.

**Steps:** Today and the Board on a 390px phone (844 and 664 tall), light and dark → one strip of controls above the list (the filter field, the filter button, Select, +) and nothing under it → the filter button opens **Filters & sort**: Sort, then on the Board Layout (Week · Status) and AI triage (Status layout, Inbox not empty), then Kind of task and Whose tasks, then the filters → Issues and Everyone each raise the filter button's count (2 with both), Clear resets them, Done closes → the Board's Layout is remembered per device and is neither counted nor cleared → AI triage closes the sheet when pressed.

**Expected:** every control that was above the list is reachable in the sheet and keeps its state (the URL's `scope` / `whose` / `owner`, the device's `task-os.whose`, `task-os.board.mode`); the sheet fits the viewport at 390x664 and 390x844 with Clear and Done on screen; the count shows in both themes and shows nothing when no filter is on.

**Screenshots:** [the Today sheet on the phone](../screenshots/story-05-board-8-phone.png) · [the second member's Board sheet, dark](../screenshots/story-05-board-19-phone-dark.png) · [the Board's person row on the desktop](../screenshots/story-05-board-20-desktop.png). The Today, Board and keyboard-triage shots that showed the rows above the list are re-baselined.

**Test:** `tests/e2e/test_story_05_board.py` — `_walk_scope_switch` (the strip holds the strip only; the count and the key), `_walk_whose_switch`, `_second_member_sees_their_own`, `_owner_phone_is_unaffected` (the count and Clear in dark); `test_story_23_ai_triage.py` (the Triage row); `tests/test_scope.py` (the view-toggle count); folded into the existing tests, no new test function.

**Result:** the unit and e2e legs pass on disposable seeded instances, synthetic data only; Today and the Board at 390x844 and 390x664 in light and dark were looked at, with the active-count state, and the sheet's height measured against the viewport (it fits, Done on screen, in all eight). **Not verified:** a real iPhone. Date: 2026-11-17.

## Select tasks is a row of the Filters & sort sheet

**Story:** the owner wants the phone strip to read filter field, filter button and `+`, with Select tucked into the sheet that already holds the other view toggles.

**Steps:** Today and the Board on a 390px phone (844 and 664 tall), light and dark → the strip shows no Select → the filter button opens **Filters & sort** with a **Select tasks** row under Sort → pressing it closes the sheet and turns Select mode on: the rows become tick targets and the strip shows **Done** → ticking a task brings up the bulk bar, whose ✕ leaves → with nothing ticked, **Done** leaves and the strip returns to its three controls. On a wide screen the strip keeps its Select toggle.

**Expected:** the sheet still fits 390x664 and 390x844 with Done on screen in both themes; Select is never on the phone strip outside Select mode; **Done** is 44px tall like the `+`, and its label holds 4.5:1 on its tint.

**Test:** `tests/e2e/test_story_04_triage.py` — `_phone_board_rows` (strip without Select, entering from the sheet, the Done label's contrast, leaving); `tests/e2e/test_story_05_board.py` — `_phone_select_and_owner` (entering from the sheet, then the bulk bar); folded into the existing tests, no new test function. The sheet-fit walk of `test_story_07_phone.py` covers the sheet's size.

**Result:** the e2e legs above pass (full suite, 16 tests, 2026-11-18). Walked in headless WebKit (a scripted run, not a headed walk) at the four phone cells against the synthetic seed: the sheet fits with Done visible in all eight cells, the row enters Select mode and closes the sheet, Done leaves.

## Board columns run to the window bottom

**Story:** the owner wants the Board's columns on the web to run to the bottom of the window and scroll all the way, not stop 300px above it with an empty band under them.

**Steps:** the Board at 1280×800, 1440×900 and 1440×600, Week and Status, light and dark → the header and filters stay put, every column ends 33px above the window edge with only the slim build line under it, the page does not scroll, and each column scrolls inside its own box to its last card. The phone (390×844) is unchanged.

**Expected:** column bottom = window height − 33px at every size and in both modes; the document is exactly one window tall; `overflow-y: auto` on each column.

**Test:** `tests/e2e/test_story_05_board.py` — `_status_columns` in `tests/e2e/_board_steps.py` (the columns reach the window bottom, the page is one window tall); it fails on the old fixed cap and passes with the shared page-high layout. No new test function.

**Result:** **verified** (full e2e, 16 tests, and a headless Chromium measurement against the synthetic seed, 2026-11-18); the 50 desktop shots that show the Board are re-baselined; owner's check on desktop not yet done.
