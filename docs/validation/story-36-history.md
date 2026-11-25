# Story 36 — What did I change (#858)

**Issue:** #858. **Tests:** `tests/tasks/test_history.py` (the feed, the grouping, the kinds, the window and the endpoint's own-actor rule) and the `_history_on_phone` leg inside `tests/e2e/test_story_07_phone.py`, walked by `tests/e2e/_history_steps.py` (WebKit device emulation, 390×844, light then dark).

**User story:** I open History and see what I changed today, newest first, one entry per task, each opening its task; a chip narrows the list to one kind of change.

**Steps → expected**

1. On the seeded instance, as the loopback owner, make two tasks, re-date and re-prioritise one, comment on it, close the other.
2. Tap **History** in the pill → the header reads *History · 6 changes today*; the chips read *All 6 · Date moved 1 · Closed/reopened 1 · Status 0 · Priority 1 · Moved 0 · Comments 1*, each at least 44px tall; the seed's own activity (written by other names) is not listed.
3. The list is four rows, newest first: consecutive changes to one task fold, a later change to it starts a new row. The run of two reads *Priority none → high · 09:00 · 2 changes*; its chevron lists both changes with their times.
4. Tap the row → the task's drawer opens; Back returns to History.
5. Tap **Date moved** → one row; the choice is in `localStorage` (`task-os.history.kind`). Tap **Moved** → *No moved changes today* with **Show all changes**, which brings back all four rows.
6. In dark, the remembered chip is pressed and the list is filtered to it.
7. The feed answers 500 → *Could not read your history* with **Try again**, never an empty day; Try again once it answers → the list is back.

**Screenshots (phone 390×844)**

| Step | Phone |
| --- | --- |
| 3 a run of two expanded (light) | [story-07-phone-19-phone.png](../screenshots/story-07-phone-19-phone.png) |
| 6 filtered to Date moved (dark) | [story-07-phone-20-phone.png](../screenshots/story-07-phone-20-phone.png) |

**Result:** verified in the browser (e2e phone, light and dark, scripted walk) and by unit tests. **Not verified:** a walk on a real phone; the desktop rail rendering is held by story 01's measure check (History keeps the 772px measure), not by a screenshot. **Date:** 2026-11-25.
