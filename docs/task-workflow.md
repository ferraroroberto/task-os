# Task workflow

## Start dates & snooze

A task can carry a **start date** (`starts`) — the day it starts mattering. Until then it is **deferred**: absent from the working views (Board, Today, `tasks ls`), present everywhere that claims to show everything (the Board under the `deferred` filter pill, search, `tasks show`, `tasks ls --status all`), and back on its own on the day it starts. "Renew car insurance, due 15 Oct, nothing to do before 1 Oct" is created asleep and simply appears on 1 Oct.

Deferred is a **visible state, never a silent absence**. Wherever a sleeping task still shows it wears a quiet `starts 5 Sep` marker on its meta line, and the filter sheet's status ticks carry a **`deferred`** entry that lists exactly those tasks. That entry is a *modifier*, not a status: it flips the list from awake to sleeping and intersects with any real statuses ticked beside it, so `?status=deferred` is the sleeping open tasks and `?status=deferred,todo` the sleeping ones that are `todo`. Like every filter, the state is the URL.

**Snooze** is that same field worn as a row control, not a second mechanism, reached from the row's ⋯ menu (*Snooze*) or the `S` key: *Tomorrow · This weekend · Next week · Pick a date…* — one tap sets `starts`, the task leaves the list, and a toast names where it went (`Snoozed to Sat 5 Sep`) with an **Undo** that puts the old value back. **A snooze never strands a task (#486):** when the new start day is after the task's due date, the due date moves to the same day (the toast says `due moved too`, Undo restores both) — so the task reappears on its due day instead of coming back overdue; a later due date, a task with no due date, and any request that names `due` itself are left exactly as sent. The rule lives in `update_task`, so the Board, Today, the keys, the bulk bar, the CLI and the drawer all follow it. The drawer edits **Starts** beside **Due** with the same control, and quick-add takes both off one line — `renew insurance due oct 15 starts oct 1` (a bare trailing date is still the *due* date; a start date says `starts`).

Everywhere a date is typed it is the one vocabulary from `src/dates.py` — `tomorrow`, `fri`, `next friday`, `this weekend`, `in 2 weeks`, `oct 15`, `2026-10-01`, `none` to clear — resolved server-side, so the UI, the CLI, quick-add and the markdown mirror cannot disagree.

**Recurrence:** the drawer's **Repeat** field is a cadence — `daily · weekly · monthly · quarterly · yearly` — then an **Every** count for how many of that cadence to wait (#229; empty or 1 is every one), and, for weekly and monthly, an **On** picker for the fixed day it lands on (#112):

| Cadence | On | Stored as | Means |
|---|---|---|---|
| weekly | every Friday | `fri` | that weekday, every week |
| weekly | weekday (Mon–Fri) | `mon,tue,wed,thu,fri` | any of those days |
| monthly | the 15th | `day-15` | the 15th, clamped to the end of a shorter month |
| monthly | the first Sunday · the last Friday | `1-sun` · `last-fri` | the nth (1–4) or last such weekday |
| daily / quarterly / yearly | — | `null` | a plain offset from the due date |

**Every N** composes with any cadence, anchored or not — *every 3 days*, *every 2 quarters*, *every 2 months on the 15th*, *every 7 weeks on Saturday* — and is stored beside the cadence in `recurrence_interval` (`null` = every one). An anchored interval takes its rhythm from the **due date**: that due's week (Monday-first) or month counts, and so does every Nth one after it. The roll lands on the anchored day in the next qualifying week or month, so completing early, on the day or weeks late never shifts the rhythm, and editing the due by hand deliberately re-sets it. A due that is not on the anchored day settles onto it within its own week first (as without an interval), and steps whole intervals from there. Clearing Repeat clears the interval; switching cadence keeps it.

Completing a recurring task rolls its `due` to the **first occurrence after both the completed due and today**. So a weekly review anchored on Friday, ticked on a Monday, lands on the coming Friday rather than the next Monday — and a task three weeks overdue catches up into the future instead of rolling onto another overdue date. An anchor never retroactively moves the due you already have; the next roll settles onto it. Changing the cadence to one that cannot carry the anchor clears it (with its own activity row).

The roll **leaves `starts` untouched**. A start date is an absolute one-time gate, not a cadence: it always eventually arrives, so a snoozed recurring task wakes on its start day and rolls normally from then on. (Advancing it with the due would make the gate chase the task forever.)

From the terminal:

```powershell
tasks add "Book boiler service" --due "in 40 days" --starts "in 20 days"
tasks ls --deferred        # exactly the sleeping tasks
tasks starts 7 "next week" # snooze; `none` clears it
tasks add "Treat clothes against moths" --due sat --recurrence weekly --recurrence-anchor sat --recurrence-interval 7
```

## Blocked-by dependencies

A task can name another task as its **blocker** — "Order tiles" can't happen until "Confirm measurements" is done. While any blocker is still open, the dependent is **blocked**: absent from the working views (Board, Today, `tasks ls`) exactly like a deferred task, present everywhere that claims to show everything (the Board under the `blocked` filter pill, search, `tasks show`, `tasks ls --status all`) wearing a lock glyph and a **blocked by N** count, and back on its own the moment the last open blocker closes — a pure query, no event machinery. A closed blocker (done or cancelled) doesn't count: only an *open* one gates.

Blocked is its own edge graph (`task_blocks`), separate from the parent tree, so a blocker may sit anywhere — a sibling, a cousin project, unrelated entirely. Adding one is refused with a `cycle` (409) on a self-block or on anything that would make the two tasks wait on each other, the same guard shape as `move`'s parent-tree cycle check but walked over its own graph. Deleting a blocker task frees whatever it blocked and logs a `blocked_by` old→None row on the survivor, so the log says why it woke up.

**Blocked wins over deferred.** A task that is both asleep (`starts` in the future) and blocked shows the lock, not the clock — it's the harder gate, and there's only one marker's worth of room on the row.

The drawer's **Blocked by** section lists the open and closed blockers (click to navigate, a trash icon to remove) and a picker to add one that searches every open task. The filter sheet's status ticks carry a **`blocked`** entry (a modifier, not a status, exactly like `deferred`): `?status=blocked` is the locked tasks, `?status=blocked,todo` the locked ones that are `todo`.

```powershell
tasks block 12 --on 7      # 12 is now blocked by 7 — refused on a cycle
tasks ls --blocked         # exactly the blocked tasks
tasks unblock 12 7         # 7 is no longer a blocker of 12
```

The markdown mirror carries it as `blocked_by: [7, 9]` in the frontmatter — an inline list of task ids, diffed against the stored edges on import and applied add/remove through the same cycle-guard rejection path `parent` gets (a rejected edit becomes a `mirror_events` row, never a comment).

## Calendar beside Today

On the desktop, once `calendar.ics_url` is set, Today carries a slim **Calendar** lane beside the task list — today's events from your real calendar, read-only, so the day is read against the free time that actually exists. All-day events sit on a strip at the top; timed ones are listed with their local times, a meeting that runs past midnight says *ends tomorrow*. Nothing is ever written to the calendar. The phone skips the lane for now. Because Today is split in half on the desktop (#336), the lane sits above the task stack instead of beside it. With no calendar configured there is no lane at all (#320): the task column takes the full width and the setup hint lives in **Settings → Calendar**; a configured calendar that fails keeps the lane and says why.

Point `calendar.ics_url` at a private ICS address and restart. The feed is read with the standard library: all-day and timed events, UTC / floating / `TZID` times (the feed's own `VTIMEZONE` first, so Outlook's Windows zone names work), cancelled events, `EXDATE`, `RDATE`, and a moved occurrence of a recurring meeting (it shows once, where it moved to). Recurring rules are expanded when they are daily or weekly (`INTERVAL`, `UNTIL`, `COUNT`, `BYDAY`); anything else — monthly, yearly, *the first Monday* — is **counted, never dropped**: the lane says *1 recurring event could not be checked* rather than implying a free afternoon.

**An empty lane never means a free day by accident.** *No events today* is drawn only after a good fetch; every failure is its own sentence with the reason and since when — *Calendar address refused* (not an http(s) address, or a 4xx — revoked or mistyped), *Calendar unreachable* (no connection, a dropped one, a 5xx), *Calendar did not answer in time* (nothing complete within `timeout_seconds`) and *Calendar feed unreadable* (an answer that is not a calendar, like a sign-in page). A failure after a good fetch keeps that copy on screen, marked with the failure and *Showing the copy from 09:00*. The same state is in Settings → **Calendar** (with *Refresh now*) and `GET /api/status` → `calendar`.

**Today never waits on it.** A good copy is served for `refresh_minutes`; once it expires, Today answers at once with the copy marked *refreshing* while one background fetch replaces it. Only with nothing to show yet does a request wait for the fetch, and never longer than `timeout_seconds`.

## Keyboard triage

Every row action is one key, so a triage pass is keys instead of mouse trips. `Tab` moves between rows on the Board, Today and the Search tab's task hits; the focused row is tinted, and after a change focus stays on it — or on whatever takes its place when the task leaves the view — so `e e e` walks a column.

| Key | On the focused row (or the whole ticked selection) |
| --- | --- |
| `E` | complete — a recurring task rolls to its next date, exactly as its row select's `complete` does |
| `1` `2` `3` | status inbox · todo · standby |
| `T` / `W` | due tomorrow / next week |
| `S` | the snooze menu — *tomorrow · this weekend · next week · pick a date* |
| `P` | cycle priority none → low → medium → high; over a selection each task moves from **its own** value |
| `Z` | undo the last change |
| `?` | the shortcuts sheet |

With tasks ticked ([Select several tasks at once](views.md#views)) the same key applies to the set, and the ticks stay — keys come in runs (a status, then a due date, then a snooze) over one picked set. The keys are inert wherever text is being typed and while the drawer, the palette or the quick-add dialog is open.

**Undo** is a real write, not a client-side rollback: the inverse goes back through the API, so the reversal gets its own `new → old` activity row and survives a reload. It is single-level and lives exactly as long as its toast — over a selection it puts each task's own prior value back, one call per group of tasks that shared one. Completing a recurring task undoes to the *pre-roll* due date.

The same actions are listed in the command palette (`Ctrl+K` / `⌘K`), each showing its key — that is where a shortcut is discovered; `?` is the reference card.
