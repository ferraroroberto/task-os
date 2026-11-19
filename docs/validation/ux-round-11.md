# UX round 11 — the task drawer restyled for speed

**Story.** The task drawer reads as one design, and the edits the owner makes most (set the status, re-plan the due date, comment, close the task) take the fewest taps and keys, on the phone and on the desktop, light and dark.

**Shape (the owner's pick among three mock-ups).** Top to bottom: the head (the breadcrumb is the parent picker's button, an *Inbox* tag on an Inbox task, ··· with *Open parent*, *Done, end the series* on a recurring task and *Delete task*, close) → the title in `heading-md` → **Status** as the vendored segmented control, *To do · Standby · Cancelled · Done* → **Due** as the date chips → **Comments** (latest three, *Show N older*; the field heads the list on a desktop and is pinned to the sheet's foot on the phone) → the **property list**, one inset group: Links (pills that open on one click, + for the folder and link editors), Due typed in place, Owner, Person, Parent, Repeat, then Priority, smaller → **Notes** (a tap edits, leaving saves) → **More fields** (starts, code, blockers, children, the issue panel) → **Activity**, folded behind its count. A drawer at least 720 px wide puts the content beside the property list.

**Owner decisions taken into the build.** Done closes the drawer and the toast offers Undo, for an Inbox task too. Keys with a task open: `X` Done, `C` comment, `L` links, `E` folder, `2` `3` To do and Standby, `1` back to Inbox, `T` `W` `D` due, `P` priority; Cancelled has no key.

**One date grid.** The row's date sheet and the drawer's Due block are the same `dateChips()` grid (`snooze.js`): a 4 × 2 grid of 44 px chips, each phrase over the day it lands on, the task's own day tinted, *Pick…* the eighth cell, *No date* a row under it in the sheet. This is the compact chip grid the date-menu issue asked for.

## Taps and keys — before and after

Counted from an open drawer, one task; typing is not counted. *Before* is the drawer this round replaces (status, priority and owner native selects; quick moves under the title; Person and Repeat under More fields after the activity log; comments under the description).

| Edit | Before · phone | After · phone | Before · desktop | After · desktop |
| --- | --- | --- | --- | --- |
| Status | 3 | **1** | 2 | **1** · key `2` `3` |
| Done, and leave the task | 4 (select ×3, close) | **1** (Done closes) | 3 | **1** · key `X` |
| Due, a shortcut | 1 | 1 | 1 (`T` `W` did not reach the open task) | 1 · key `T` `W` |
| Due, a day you pick | 2 | 2 | 2 | 2 · key `D` |
| Priority | 3 | **2** | 2 | 2 · key `P` |
| Owner | 3 | **2** | 2 | 2 |
| Person | 4 + scroll | **2** | 3 + scroll | **2** |
| Repeat | 4 + scroll | **2** | 3 + scroll | **2** |
| Parent, a recent one | 2 (+ typing the filter) | 2, no typing | 2 (+ typing) | 2, no typing |
| Parent, back to the top level | 1 | 2 (*No parent*) | 1 | 2 |
| Add a comment | 2 + scroll past the description | **2, no scroll** (field pinned) | 2 | `C`, type, Ctrl+Enter |
| Edit the notes | 2 (pencil, Save) | **1** (tap; leaving saves) | 2 | **1** |
| Delete | 2 + scroll to the foot | 3 (···, Delete, confirm), no scroll | 2 + scroll | 3, no scroll |

Two edits got one tap slower on purpose: *back to the top level* (it moved into the picker, beside the recent parents, so the head carries one control instead of three) and *Delete* (the destructive action left the drawer's body for its ··· menu, last, after a divider, as every row menu puts it).

## One type scale, one field, one button hierarchy

- Type: the title `heading-md` (20 px, 700; the token added to `base.css`), section titles `body` bold, reading text (comments, notes, property values) `body`, labels `label`, meta `body-sm`, chip dates `caption`.
- Fields: every input and select is the one native control recipe, 44 px painted in the drawer; the date shortcuts are chips (they commit on one tap), never drawn as fields.
- Buttons: **Send** is the drawer's only `button-primary`, labelled, at the field's 44 px height. *Add link*, *Add blocker*, *Add child* and *Create issue* moved to `button-surface`; every glyph-only control is the unshaded icon button.
- The vendored nav's bottom fade no longer paints over the full-screen drawer: with the pill hidden, its fade goes too, so the pinned comment field reads at full strength.

## Proof

- **e2e** (no new test function — the suite stays at 16 collected): story 04 walks the drawer on the desktop (due chips as the sheet's own grid, the current day marked, Send the one primary, Notes in place, the parent picker's Recent and *No parent*, Repeat and Done rolling a recurring task) and on the 390 px WebKit phone (segment and chip targets, the four-across grid, the comment field pinned to the foot, Send level with it, the property rows clear of it); `_drawer_key_steps.py` walks the keys on the open task (`e`, `3`, `2`, `t` + `z`, `p`, `c`, `l`, `x` + Undo) and the shortcuts sheet's *With a task open* group; story 05 walks Owner through the row menu, Delete from ···, *Done, end the series*, and `1` / `2` on the open task; stories 06, 07, 08, 09 and 20 follow the moved blocks.
- **Browser walk** (scripted, headless Chromium, on a disposable seeded instance of the branch): Standby stays open; `2`, `t` (toast with Undo), `p`; `c` then Ctrl+Enter adds a comment and *Show 1 older* appears; `l` unfolds the editors; Person through its menu; the breadcrumb's picker, Recent and *No parent*; Notes saved on leave; Done closes with *Completed · Undo (Z)* and Undo puts it back to To do; an Inbox task shows the tag with no segment raised and `X` files it as done; ··· holds Delete. No console errors. Frames read back at 390 px light and dark, 1440 and 1920 px desktop, and the Board's 440 px panel.
- **Gallery:** re-baselined for every shot the drawer or the date sheet appears in.
- **Live instance:** walked after the merge's restart, read-only (see the PR).
- **Real phone:** owner-only — the issue keeps `needs-validation` until the owner checks it on the iPhone and the desktop.
