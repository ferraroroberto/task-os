# Story 13 — push a task to when it matters (issue #87)

> I have to renew the car insurance by 15 October, but there is nothing to do before 1 October. I add it with both dates and it goes straight to sleep — out of Today, off the Board, out of the Table — and simply turns up on 1 October. Meanwhile, three things on Today are not for today: I tap the clock on each and pick *tomorrow* / *this weekend* / *next week*, and they leave the list. One of them I pushed by mistake, so I hit **Undo** in the toast and it comes straight back.

Not a numbered build step — a feature issue validated story-style. The automated walk lives **inside `tests/e2e/test_story_04_triage.py`** (`_walk_starts_and_snooze` at the end of the desktop leg, plus the phone assertions in the phone leg): the e2e suite is capped at 15 tests and already held 14, and this story walks the same surface — the filter card, the quick-add dialog, a Today row, the drawer.

## Steps and expected

| # | Step | Expected | Shot |
| --- | --- | --- | --- |
| 1 | Today → `+` → `renew insurance due in 60 days starts in 30 days` | One line, parsed server-side by `POST /api/parse`: **both** the Due and the Starts field fill with correctable dates, not one date and a mystery. `starts` needs its keyword — a bare trailing date is still the due date | [1-desktop](../screenshots/story-13-starts-snooze-1-desktop.png) |
| 2 | Create it, then look at Today, the Board and the Table | Absent from all three. The task exists and is `todo`; it is simply not yet actionable | — |
| 3 | Tree | **Present**, wearing a quiet `starts 1 Oct` marker on its meta line. Deferred is a visible state, never a silent absence — the Tree is the map of everything, so it never prunes a sleeping task | [2-desktop](../screenshots/story-13-starts-snooze-2-desktop.png) |
| 4 | Filter card → status multi-select → **deferred** | Lists exactly the sleeping tasks (the seed's `Book boiler service` + the new one); the URL becomes `?status=deferred`, shareable like every other filter. It is a *modifier*, not a status: ticking `doing` beside it narrows to sleeping `doing` tasks | [3-desktop](../screenshots/story-13-starts-snooze-3-desktop.png) |
| 5 | Today row → the clock button | A four-option popover: *Tomorrow · This weekend · Next week · Pick a date…*. Same `<details>` idiom as the filter card's multi-select — Escape and an outside click close it | [4-desktop](../screenshots/story-13-starts-snooze-4-desktop.png) |
| 6 | Pick *Next week* | The task leaves Today; `starts` is set from the **phrase** (the server owns the date vocabulary, so the CLI, quick-add and the mirror agree); an `activity` row records `starts ∅ → …`; the toast names the day — `Snoozed to Mon 31 Aug` | — |
| 7 | **Undo** in the toast | The previous value goes back (`null` here) and the row returns to Today. The undo is the inverse `PATCH`, not a command stack — the old value is the only state it needs | — |
| 8 | Drawer on a task | **Starts** sits beside **Due**, same control, same phrases; editing either writes its own activity row | — |
| 9 | Dark + light | The popover, the trigger and the `starts` marker are defined in both themes; the marker takes no status colour (a fact, not a warning) | [5-desktop](../screenshots/story-13-starts-snooze-5-desktop.png) |
| 10 | Phone (390×844, WebKit, touch) | The snooze trigger clears the 44px floor and never overlaps the status select; the popover's options do too, and it opens without pushing the page sideways | [6-phone](../screenshots/story-13-starts-snooze-6-phone.png) · [7-phone](../screenshots/story-13-starts-snooze-7-phone.png) |

**Recurrence rule, decided and documented here:** completing a recurring task rolls its `due` one cadence forward and **leaves `starts` untouched**. A start date is an absolute one-time gate, not a cadence — it always eventually arrives, so a snoozed recurring task wakes on its start day and rolls normally from then on. Advancing it with the due would make the gate chase the task forever. Pinned by `tests/test_repo.py::test_recurrence_roll_leaves_starts_alone`.

**`include_closed` lifts the gate too.** `?include_closed=true` means "hide nothing", so it shows sleeping tasks as well — otherwise a total taken with it (the app's "any tasks at all?", the mirror's file count) would quietly omit them and report a number nobody could reconcile. Found by the story-06 mirror e2e, which timed out waiting for a file count that could never match; pinned in `test_deferred_hidden_from_lists_but_never_from_tree_or_search`.

Unit legs: `tests/test_repo.py` (field + activity + clearing; the three `deferred` modes; the status intersection; the recurrence rule; `include_closed`), `tests/test_api.py` (phrases over HTTP, the `status=deferred` pseudo-value and its intersection, the 422 on an unknown phrase, `POST /api/parse` returning both dates), `tests/test_cli.py::test_starts_and_deferred_over_both_backends` (identical `--json` on the HTTP and local backends), `tests/test_mirror.py::test_starts_round_trips_and_conflicts_like_any_field` (export → hand edit → import → conflict → convergence), `tests/test_quick_add.py::test_parse_starts` and `tests/test_dates.py` (`this weekend`, the month-name dates, and the rejections).

## Real walk (this PC, 2026-08-30)

Real Chrome against a **disposable seeded instance** on `:8459` (never the live `:8448`; mirror and backup blanked via `tests.conftest.write_test_config`, synthetic seed only), dark and light:

- Board and Today confirmed clear of the seed's `Book boiler service`; the Tree kept it with `starts 19 Sep`.
- Snooze walked three times through the real control — *This weekend* on `School enrolment forms` (→ Sat 5 Sep, the coming Saturday from a Sunday, as the rule says), *Tomorrow* on `Practice scales`, *Next week* on `Vocabulary review`. Each left Today, each confirmed against `/api/tasks/{id}` rather than only on screen.
- **Undo walked**: `Vocabulary review` snoozed to 2026-09-06, Undo clicked, `starts` back to `null` and the row back on Today.
- `?status=deferred` walked on Today and the Table — the filter summary reads `deferred · sorted by due date · 3 tasks` and every row carries its marker.
- Quick-add `renew insurance due oct 15 starts oct 1` typed into the real dialog: both fields filled (10/15/2026 and 10/01/2026), created, and confirmed absent from `/api/tasks` and `/api/board` while present under `?status=deferred`.
- Drawer opened on the deferred task: **Starts · in 3w** beside **Due · in 6w**, both editable.
- CLI walked over **both** backends against the same DB — `ls` (sleeping absent), `ls --deferred`, `ls --status all`, `show` (`starts` on the detail line), `add --starts`, `starts N <phrase>`, `starts N none` — with byte-identical `--json`.
- **Mirror round-trip walked by hand**: exported `0044-book-boiler-service.md` carries `starts: 2026-09-19`; the line was edited to the natural phrase `next friday` in the file, the watcher imported it (`applied {'starts': '2026-09-11'}`), the activity row landed with actor `md`, and the file converged to the ISO value.

Three defects found on the walk, all invisible to the tests, all fixed:

- **The Undo could not be reached.** The toast's 4.5 s TTL is enough to *read* a result but not to notice an action, move the pointer and click it — the snooze toast was gone before it could be used. A toast carrying an action now stays up 10 s (`ACTION_TTL_MS` in `toast.js`); a plain toast is unchanged.
- **"Pick a date…" read as disabled.** It was drawn in the muted text colour, which in both themes looks like a dead option. The divider above it is what sets it apart from the three phrases, so the label is now normal text and only its glyph is muted.
- **The desktop Table listed sleeping tasks without saying when they wake.** That grid has its own cells rather than the shared row, so the `starts` marker the shared row puts on its meta line was simply missing — in the one view the Deferred filter sends you to. It now carries the same marker in its title cell (`.t-starts`, the shared row's `.trow-starts` twin), pinned by an assertion in the story walk.

**Incident during this validation (recorded, not hidden):** the first attempt at the disposable instance was booted with a straight copy of `config/config.sample.json`, whose `mirror.dir` points at the **real** synced folder. That instance imported the live mirror and re-exported 44 files with a synthetic DB behind them; the live app then imported those files and cleared `person_id` on **18 real tasks**. Caught within two minutes from `/api/status` showing the real mirror path, the instance was stopped, the live DB backed up, and all 18 assignments restored from the activity log through the repo layer (`actor='repair'`) — verified: 474 tasks, 143 person assignments, no other field touched by `md` that day. The lesson is written into this record because the safe recipe already existed and was not used: **a disposable instance must build its config with `tests.conftest.write_test_config`** (which blanks `mirror.dir`, `backup_dir`, `folder_roots` and `email_db`), never a raw copy of the sample.

Result: **verified** (e2e desktop + phone legs · unit across repo, API, CLI, mirror, parser · headed desktop walk in both themes, including undo, the CLI on both backends and a hand-edited mirror round-trip) · real phone = owner's checklist. Date: 2026-08-30.
