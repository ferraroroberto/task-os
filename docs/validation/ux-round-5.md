# UX round 5 — the top strip: text filter always visible, quick-add behind a `+` (issue #80)

Fifth on-screen review. The finding: the Board's top strip was spent on the quick-add row — a control reached for a few times a day — while the text filter, the one reached for constantly, was hidden inside the collapsed **Filters** disclosure. This round swaps them: the text box is always on screen at the top of Board · Table · Tree · Today, and quick-add shrinks to a `+` that opens one dialog. Everything else in the filter card is unchanged and still collapsed. Judged on the seeded disposable instance (synthetic data only) at 1440×900 and 390×844, light and dark; every screenshot below was read back before the round was called done.

Desktop: [board + strip](../screenshots/ux-round-5-1-desktop-board-strip.png) · [text filter applied](../screenshots/ux-round-5-2-desktop-text-filter.png) · [quick-add dialog](../screenshots/ux-round-5-3-desktop-quick-add.png) · [folder picker inside it](../screenshots/ux-round-5-4-desktop-quick-add-picker.png) · [the task it created](../screenshots/ux-round-5-5-desktop-created.png) · [dark](../screenshots/ux-round-5-6-desktop-dark-quick-add.png) · [table strip](../screenshots/ux-round-5-7-desktop-table-strip.png) · [filter card open](../screenshots/ux-round-5-12-desktop-filters-open.png). Phone: [today strip](../screenshots/ux-round-5-8-phone-today-strip.png) · [quick-add dialog](../screenshots/ux-round-5-9-phone-quick-add.png) · [its foot](../screenshots/ux-round-5-11-phone-quick-add-foot.png) · [board strip](../screenshots/ux-round-5-10-phone-board-strip.png).

## The round

| # | Asked | Done | Seen in |
| --- | --- | --- | --- |
| 1 | The text filter always visible, no disclosure to open | `mountFilters(host, {textHost})` renders `.filter-q` into the pane's own `.pane-top` strip (`#<tab>FilterText`) instead of the card body; same `type=search`, same 250 ms debounce, same `?q=` in the URL, same shared state on every tab | [board + strip](../screenshots/ux-round-5-1-desktop-board-strip.png), [applied](../screenshots/ux-round-5-2-desktop-text-filter.png) |
| 2 | The rest of the filters stay as they were, collapsed | the card keeps project · person · due · modified · status · sort and its summary line; it just has no text field, and the summary no longer repeats the query (the box that owns it is on screen right above) | [card open](../screenshots/ux-round-5-12-desktop-filters-open.png) |
| 3 | Quick-add on demand, not a permanent row | a `button-surface` `+` at the right of the strip opens `<dialog id="quickAdd">` — the vendored editor-modal shell the command palette already uses (markup + tokens only, `modal.css` untouched). Same input, same `POST /api/parse`, same `POST /api/tasks`; Enter or the one full-width primary creates, Escape / backdrop / × discard (round 2 below grows the body) | [quick-add](../screenshots/ux-round-5-3-desktop-quick-add.png), [phone](../screenshots/ux-round-5-9-phone-quick-add.png) |
| 4 | Same treatment on Table / Tree / Today | one `.pane-top` per pane, identical markup; the four `+` buttons share the one dialog (`quickAdds[]` and the per-pane mount are gone, and so is the palette's tab-then-index lookup — *New task* just opens it) | [table strip](../screenshots/ux-round-5-7-desktop-table-strip.png), [phone today](../screenshots/ux-round-5-8-phone-today-strip.png) |
| 5 | Search unchanged | Search passes no `textHost`, so it has no second text field and no `+`; `Clear` there still leaves its query alone. Asserted in the walk: `#paneSearch .filter-q` and `#paneSearch .quick-add-btn` are both absent while its own box returns hits | — (no visual change) |
| 6 | Design tokens, no ad-hoc styling | the `+` is `button-surface` at `--control-h` with `.hit-target` on a fine pointer and **real** 44×44 geometry (`::before { inset: 0 }`) on a coarse one, so the expanded rectangles never overlap the text box beside it; the dialog is the vendored shell + its own variation class, top-anchored on the phone by the shell's own rule | [phone board](../screenshots/ux-round-5-10-phone-board-strip.png), [dark](../screenshots/ux-round-5-6-desktop-dark-quick-add.png) |

## Side effect worth recording

The text input is now built **once** and only its value is synced (skipped while it has focus), instead of being re-created on every state change. The caret-restoring hack in `mountFilters` — read `selectionStart`, re-render, `focus()` + `setSelectionRange()` — is gone with it. Walked deliberately: typing `kitchen` a character at a time at 140 ms (so several list re-renders land mid-word) leaves the box holding `kitchen`, still focused, with `?q=kitchen` in the URL.

## Verification

- Screenshots above: captured in a headed Chrome (desktop) and WebKit (phone) walk on the seeded disposable instance, read back one by one; no page errors in either leg.
- `scripts\verify-before-ship.ps1` green: byte-compile · ruff · 269 unit · e2e full tier, 14 tests. The stories carry the new DOM: story 04 opens the dialog from the Table's `+` and adds through it, story 05 types in the Board strip with the card provably still collapsed and opens/discards the dialog, story 07 adds from Today on the phone and checks the strip's two controls for the 44 px floor and non-overlap.
- Not verified here: the same walk on the real phone over the tailnet (owner-only — the standing item in [validation.md](../validation.md)'s owner checklist).

## Round 2 (owner feedback on the walk)

> *"When I add the new task, I would like to be able to add a date and state — inbox and no date by default, but able to change it at the moment of putting the task. Also the folder, so I don't have to open it again. The most used fields should be modifiable in the first moment: the folder, the name, the description, the date and the state. Also the ability to add one link, so if you don't have a folder but you have a conversation, we can add the link."*

The `+` dialog was a one-line box, so every task still needed a second trip through the drawer to become useful. This pass makes it a real editor — the **editor-modal** contract it already wore, now with the rows the contract describes.

| # | Asked | Done | Seen in |
| --- | --- | --- | --- |
| 1 | Date settable at creation, no date by default | a `type=date` **Due** row, empty unless the natural-language line fills it: `"renew passport next friday"` puts `2026-09-04` *in the field*, where it can be corrected. The date chip is gone — the field is the one truth. A hand-set date is sticky: once touched, later keystrokes in the title never overwrite it | [dialog](../screenshots/ux-round-5-3-desktop-quick-add.png) |
| 2 | State settable at creation, `inbox` by default | a **Status** select over the six statuses, `inbox` preselected | [dialog](../screenshots/ux-round-5-3-desktop-quick-add.png) |
| 3 | Folder, so the drawer is not the next stop | a **Folder** row: type a `{placeholder}/…` ref or paste an absolute path (folded through `POST /api/resolve`, never client-side), or **Pick from index** — the drawer's own folder-index search, now shared rather than copied | [picker](../screenshots/ux-round-5-4-desktop-quick-add-picker.png) |
| 4 | Description | a two-row textarea, markdown as everywhere else | [dialog](../screenshots/ux-round-5-3-desktop-quick-add.png) |
| 5 | One link, for when there is a conversation and no folder | a **Link** row (url + optional label). The `kind` (`folder` · `email` · `ai` · `issue` · `web`) is classified by the same rule the drawer uses, so a pasted Claude/ChatGPT URL becomes an `ai` link here too | [dialog](../screenshots/ux-round-5-3-desktop-quick-add.png), [created](../screenshots/ux-round-5-5-desktop-created.png) |
| 6 | Still fast for the one-liner | everything but the title is optional and starts empty; the title still enables the primary on its own and `Enter` still submits from any single-line field. The phone fits all six rows without scrolling at 390×844 | [phone](../screenshots/ux-round-5-9-phone-quick-add.png) |

**Duplication avoided, not created.** The folder-index picker and the link-kind rule were the drawer's private code; adding a second copy for the dialog would have been two behaviours drifting apart. Both moved out instead — `folderpick.js` (`mountFolderPicker` + `resolveFolderRef`, ~90 lines) and `format.js`'s `linkKind` — and the drawer now imports them. Net: the drawer lost more lines than the dialog gained.

**Write path.** One `POST /api/tasks` carries title · status · due · description · parent · folder_ref (the create endpoint already accepted all of them), then one `POST /api/tasks/{id}/links` only when a URL was given. No repo or router change: the domain rules stay in `src/tasks_repo.py`, exactly where the issue's constraints put them. A link that fails does **not** lose the task — it is created, said so, and the link failure is its own message.

**Escape is layered.** With the folder picker open, Escape closes the picker and keeps the draft; a second Escape closes the dialog. This needs a capture-phase handler, not the dialog's `cancel` event: the picker's own Escape handler runs first on the way to the target, so `cancel` would see an already-closed picker and let the whole dialog go — which is exactly what the first attempt did, and what the walk caught.

### Round 2 verification

- Headed walk (Chrome desktop + WebKit phone), asserted on the way through: the parse fills Due; a hand-set date survives a re-parse of the title; Escape closes the picker and leaves the draft intact; the created task comes back from the API carrying `status=todo`, the hand-set due, the description, `folder_ref={onedrive}/house` and one `ai` link. No page errors in either leg.
- `scriptserify-before-ship.ps1` green: byte-compile · ruff · 269 unit · e2e full tier, 14 tests. Story 04 now fills every field in the dialog and asserts all five landed on the created task in one go.
- Not verified here: the real phone over the tailnet (owner-only).
