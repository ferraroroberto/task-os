# Story 32 — track time and compare shares (#457)

**Story.** A Time tab sits third in the nav (Today · Board · Time · Search). The first visit on a device asks who is tracking time there, a label for that device and not a sign-in. Log shows today per person, starts a timer with one tap and switches it in one call, and stops and saves it. Add time already spent saves an entry whose end follows from its start and minutes. History lists every entry by day with its clock range; any entry, whoever logged it, can be edited (moved to the other person, for one) or deleted from its row menu. Totals opens on the Home area at 30 days and compares the people's logged shares and hide the other person's guess until yours is locked in. In Settings → Time categories, a category is added with a subtitle that shows under its name in Log, the subtitle is cleared from its Edit dialog, and a category added by mistake can be deleted; one with entries cannot (#463).

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open the app on Today | Four tabs; no `/api/time/` request until Time is opened |
| 2 | Open Time | The header reads *Time*; the person picker stands in for the views; picking *Person 1* stores `task-os.time.person` |
| 3 | Read Log | *Today so far*: Person 1 45m, Person 2 1h (the seed); the header line *45m today* |
| 4 | Tap *Cooking and dishes* | The timer card, clock 0:00 (both clocks pinned); the header *1 running* |
| 5 | The other device starts Person 2's timer; a second start for Person 1 | 201 for Person 2; 409 `timer_running` for Person 1 |
| 6 | Reload | Both timers are still running and named on the glance rows; the header *2 running* |
| 7 | Tap *Laundry and ironing* | *A timer is running* asks to stop it and start Laundry; confirming saves Cooking (the 1-minute floor) and starts Laundry in one call |
| 8 | Stop and save; the other device stops again | The card goes, Person 1 reads 47m; the second stop is 409 `no_timer` and saves nothing |
| 9 | Add time already spent: Cleaning, 30 | The start defaults to 08:30 (it just ended at the pinned 09:00); saved |
| 10 | History, edit that entry to Person 2 | The row read *08:30 to 09:00 · 30m · Person 1*, then *… · Person 2*; Person 1's today drops by exactly 30 and Person 2's rises by 30; the row menu holds Edit, Start again, Delete |
| 11 | Totals (it opens on Home at 30 days, #463), guess 40 | The head-to-head, split bar and coverage line; no table until the guess is locked; then Person 2's 60% shows and *The guesses add up to 100%*; the CSV link carries the period and area |
| 11a | Settings → Time categories: add *Made by mistake* to Home with the subtitle *one to delete*; open Log; Edit it and empty the subtitle (#463) | The subtitle shows under the name in Settings and on its Log start row; Edit opens with it filled, and after Save the row has no subtitle |
| 11b | Open the same category's menu, Delete, confirm (#463) | *Cooking and dishes* (it has entries) offers no Delete; the new one does, the confirm reads *Delete Made by mistake?*, and the row goes; `DELETE` on a used category is 409 `category_in_use` |
| 12 | Phone (390, dark), pick Person 2 | Log fits with no sideways scroll; the view segments are 44px targets |

## Proof

- Screenshots: [story-32-time-1-desktop.png](../screenshots/story-32-time-1-desktop.png) (Log, two timers running) · [story-32-time-2-desktop.png](../screenshots/story-32-time-2-desktop.png) (History, the moved entry) · [story-32-time-3-desktop.png](../screenshots/story-32-time-3-desktop.png) (Totals on Home, guesses revealed) · [story-32-time-4-phone.png](../screenshots/story-32-time-4-phone.png) (Log on the phone, dark)
- Test: `tests/e2e/test_story_32_time.py`. To stay within the suite's node count, story 07's `/login` walk was folded into its phone test function (the #96 / #279 precedent): 16 collected tests, one per file, its two `/login` shots byte-identical.
- Unit: `tests/test_time.py` (one timer per person, an interrupted stop, a double stop on two connections, switch, midnight crossing, the server's today, edits that move an entry between people or move its end, duration-only entries never gaining a range, archived categories still counted, the CSV equal to the totals, guesses hidden until yours) · `tests/test_import_time_prototype.py` · the v19 case in `tests/test_schema.py`.
- Scripted walk on a disposable instance (seeded scratch DB, a test config): the picker, Log, a running timer, the Switch offer, Totals on Home, History, the edit sheet and Settings → Time categories, at 1440 light and 390 dark, no console errors, no `/api/time` call before the tab. Screenshots reviewed in the session, not committed.

**2026-10-18, before closing #457:** a second scripted walk on two disposable instances covered what the story's pinned clocks cannot. With the browser in another time zone (UTC−11, a day behind the server), Add time already spent defaults to the server's day and the entry lands on it. A timer aged four hours on the server shows the forgotten-timer warning, and the corrected 25 minutes are what is saved, on the day the timer started (the day before: the midnight rule, live). A category archived from Settings → Time categories leaves the start list and still shows in History and Totals. An instance with no `time` block has no picker, one *Me* row, and no head-to-head, guess card or Me · Everyone switch.

Result: **verified** (e2e desktop and phone, unit, scripted walk, 2026-10-18). **Not verified:** two real devices at the same moment on the live install (a timer started on the phone and stopped on the PC, an edit moving an entry between people). The walk on the live install would write to the real database, so it is the owner's checklist below.

**2026-10-18, #463 (delete an empty category):** step 11b runs after the last desktop shot, so the gallery is unchanged. Unit: `test_only_a_category_nothing_points_at_can_be_deleted` (an entry or a running timer blocks it, archived or not; the area closes the gap; a discarded timer frees it) and the delete leg of `test_api_area_and_category_admin` (204, 404, 409 `category_in_use`, `in_use` in the meta). Result: **verified** (e2e desktop, unit).

**2026-10-18, #463 (category subtitle):** step 11a, also after the last desktop shot; the category it adds is deleted in 11b, so the phone shot is unchanged. Unit: `test_a_category_subtitle_is_set_changed_and_cleared` (trimmed, kept by a rename, cleared by an empty one, 80 characters at most) and the 422 in `test_api_area_and_category_admin`. Result: **verified** (e2e desktop, unit).

**2026-10-18, #463 (Totals defaults):** step 11 no longer picks Home; it asserts Home and 30 days are the defaults and the CSV link carries `period=30`. `story-32-time-3-desktop.png` is re-baselined deliberately (30 days instead of 7; two runs byte-identical). Scripted look on a disposable instance with every time entry and guess removed, at 1440 light and 390 dark: the comparison shows both people at *0m · nothing logged*, the guess card offers Lock in, and the empty state sits where the bars would be; no console errors. The empty period is not an e2e step (it would need its own instance). Result: **verified** (e2e desktop, scripted look).

### Owner's checklist

- [ ] Add the `time` block to `config/config.json` (two people, ids matching the prototype's keys), `tray.bat --restart`, open Time on the phone and on the PC and pick a person on each.
- [ ] Start a timer on the phone, see it on the PC within 15 s, stop it on the PC; the phone shows it stopped.
- [ ] Both people's timers running at once from two devices; a switch on one; an edit moving an entry to the other person.
- [ ] Import the prototype's final export (`scripts/import_time_prototype.py`), compare the Home totals with the prototype, then stop using the prototype.
