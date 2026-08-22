# UX round 3 — one row, one filter card, flat views (issue #46)

Third on-screen review (phone + desktop). The finding behind most items: Board, Table, Tree, Today and Search had each grown their own row shape, their own status control and their own filter bar. They are *renderings* of one list, not different features — so this round made the row, the status control and the filter card shared components and re-drew every view with them. Judged on the seeded disposable instance (synthetic data only) at 390×844 with a coarse pointer and at 1440×900; every screenshot below was read back before the round was called done.

Phone: [board](../screenshots/ux-round-3-1-phone-board.png) · [table](../screenshots/ux-round-3-2-phone-table.png) · [tree](../screenshots/ux-round-3-3-phone-tree.png) · [today](../screenshots/ux-round-3-4-phone-today.png) · [search](../screenshots/ux-round-3-5-phone-search.png) · [settings](../screenshots/ux-round-3-6-phone-settings.png) · [drawer](../screenshots/ux-round-3-7-phone-drawer.png). Desktop: [board + filter card open](../screenshots/ux-round-3-8-desktop-board-filters.png) · [table](../screenshots/ux-round-3-9-desktop-table.png) · [tree](../screenshots/ux-round-3-10-desktop-tree.png) · [today](../screenshots/ux-round-3-11-desktop-today.png) · [search](../screenshots/ux-round-3-12-desktop-search.png) · [drawer](../screenshots/ux-round-3-13-desktop-drawer.png).

## Cross-cutting

| # | Asked | Done | Seen in |
| --- | --- | --- | --- |
| A1 | One task row everywhere: title + status select on line 1, meta on line 2 (person on the meta line, no third line), flat hairlines, no cards | `rows.js` — `taskRow()` / `rowList()` / `metaLine()`; Board, Table (phone), Tree, Today and Search task hits all call it. Meta = code · project · due · priority · repeat · folder chip · issue chip · children · comments · person | every phone shot; [desktop board](../screenshots/ux-round-3-8-desktop-board-filters.png) |
| A2 | One status changer — the Board select, everywhere; Today's checkbox removed | `statusSelect()` in `rows.js`; the Table grid's status cell uses it too; Today has no checkbox | [phone today](../screenshots/ux-round-3-4-phone-today.png) |
| A3 | One filter card, collapsed by default, shared by every tab, finished items findable, sort included | `filters.js` — `mountFilters()` renders the vendored disclosure into `#boardFilters / #tableFilters / #treeFilters / #todayFilters / #searchFilters`; status pills include `done` and `cancelled`; project · person · due window · **modified window** (new `updated_since` on `/api/tasks`) · text · **sort**; the summary line spells the state out (`doing · Home renovation · sorted by due date · 12 tasks`); state = the URL query on every tab | [desktop board + card open](../screenshots/ux-round-3-8-desktop-board-filters.png); collapsed on every other shot |
| A4 | No ALL-CAPS titles | Drawer section titles, Today group titles, Board column heads, Settings labels, the `project` chip — all normal case, app title font | [phone drawer](../screenshots/ux-round-3-7-phone-drawer.png), [settings](../screenshots/ux-round-3-6-phone-settings.png) |
| A5 | Standard component sizes | Filter pills are the standard `.pill`; the search box is the header bar's 52 px; selects at the control height | [phone search](../screenshots/ux-round-3-5-phone-search.png) |

## Per view

| # | Asked | Done | Seen in |
| --- | --- | --- | --- |
| B3 | Board: person onto line 2 | two-line rows everywhere; the old context line is gone (code / project lead the meta line) | [phone board](../screenshots/ux-round-3-1-phone-board.png) |
| C | Table: rows like the Board; hairlines; pills on one line at standard size | under 768 px the Table renders the shared rows; the desktop grid lost its card wrapper (flat, sticky header on the canvas); the status pills live in the shared card | [phone table](../screenshots/ux-round-3-2-phone-table.png), [desktop table](../screenshots/ux-round-3-9-desktop-table.png) |
| D | Tree: make the ordering visible, rows identical | every level ordered by the shared sort (the summary line says `sorted by due date`); rows are the shared row with the expand toggle as prefix; flat; the forest is pruned to the filtered list + ancestors (a filtered-out ancestor renders muted as context) | [phone tree](../screenshots/ux-round-3-3-phone-tree.png), [desktop tree](../screenshots/ux-round-3-10-desktop-tree.png) |
| E | Today: titles normal case, alignment, same rows, status select, "Later this week" spacing | derived in the browser from the filtered list (so the filter card applies); flat heading line with the counts; flat groups; "Later this week" is a flat disclosure with room above | [phone today](../screenshots/ux-round-3-4-phone-today.png), [desktop today](../screenshots/ux-round-3-11-desktop-today.png) |
| F | Search: no ms, counts per index, title click opens, same row info, last-modified filter, bar height, collapsible groups | `#searchMeta` says `N hits`; each group is a collapsible card with its count (collapsed by default, remembered per kind); task hits are the shared row + snippet, filtered/sorted by the shared card; folder/email/issue titles are the link; no Open button | [phone search](../screenshots/ux-round-3-5-phone-search.png), [desktop search](../screenshots/ux-round-3-12-desktop-search.png) |
| G | Settings: crowded → collapsible cards, spacing, no caps, rename, state words not counts | every card a collapsible disclosure (collapsed by default); body breathes; "Folder opener and index"; headers read `indexed` / `synced` / `on` / `off` | [phone settings](../screenshots/ux-round-3-6-phone-settings.png) |
| H | Drawer: description icon, links one line, due picker, section fonts, Sync now kept | `file-text` glyph added to the sprite; `.link-form` never wraps; due = text + a calendar button opening the native picker; section titles in the app title font; Sync now stays in the drawer and in Settings | [phone drawer](../screenshots/ux-round-3-7-phone-drawer.png), [desktop drawer](../screenshots/ux-round-3-13-desktop-drawer.png) |

## How it is wired

`app.js` keeps ONE filtered list (`/api/tasks` under the filter state — plus today's done tasks when no status pill is pressed, for the Board's last column) and one full forest (`/api/tasks/tree?include_closed=true`); each tab renders from those. A change in any tab's filter card re-fetches the list once and re-renders every tab. Search applies the same predicate (`matchesFilters()`) and sort to its task hits, which now carry the full summary (`task` on the hit).

## Verification

- Screenshots above: captured on the seeded disposable instance and read back one by one; the pictures are the proof of each row in the tables.
- `scripts/verify-before-ship.ps1`: byte-compile · ruff · unit suite (`updated_since` / `done_on` on the list API, the enriched search hit) · e2e full tier updated to the new DOM — result recorded in the PR (#46).
- Not verified here: the same walk on the real phone over the tailnet and the real data set (owner-only — the standing item in [validation.md](../validation.md)'s owner checklist).

## Round 4 (issue #48)

Follow-up review on the phone, same method (seeded instance, screenshots read back, e2e). Phone: [filter card open](../screenshots/ux-round-4-1-phone-filters.png) · [search](../screenshots/ux-round-4-2-phone-search.png) · [settings](../screenshots/ux-round-4-3-phone-settings.png). Desktop: [search hits](../screenshots/ux-round-4-4-desktop-search.png).

| # | Asked | Done | Seen in |
| --- | --- | --- | --- |
| 1 | Filter card: text first, then two-by-two symmetrical rows on the phone, equal widths; status no longer a pill row that wraps | `.filter-row` is a two-column grid under 768 px (text and Clear span both columns); status moved into a dropdown; order text · project / person · due / modified · status / sort | [phone filters](../screenshots/ux-round-4-1-phone-filters.png) |
| 2 | Person (team) and status multi-select: one click each, several allowed, "multiple" shown | `multiSelect()` in `filters.js` — a select-looking summary opening a checklist; reads *Anyone* / the name / *2 people* (*Open tasks* / *doing* / *2 statuses*); `person=1,2` in the URL; `/api/tasks` takes several `person` ids | [phone filters](../screenshots/ux-round-4-1-phone-filters.png) |
| 3 | Table: no extra heavy line under the filter card | `.table-wrap` top border dropped; the grid header's divider is the quiet hairline | — |
| 4 | Search hits for folders / emails / issues like the task rows: title + meta, no double icons, no chips, no Attach / New task; click the title opens | every hit is the `.trow` shape; folder = name · full path (the matched term marked on the path line, not repeated), email = subject · sender · date · folder, issue = title · repo#N · state (· task #N); the title is the opener link / the linked task / the issue page; Attach and New task removed (with their keyboard shortcuts) | [desktop search](../screenshots/ux-round-4-4-desktop-search.png), [phone search](../screenshots/ux-round-4-2-phone-search.png) |
| 5 | Settings: body text too big / uneven; coloured words not always bold | every Settings body text at the row meta size (`--font-caption`), state words bold in every row (Phone access included) | [phone settings](../screenshots/ux-round-4-3-phone-settings.png) |

Gate: `scripts/verify-before-ship.ps1` green — recorded in PR #49. Not verified here: the real phone over the tailnet (owner-only).
