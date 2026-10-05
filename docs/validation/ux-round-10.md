# UX round 10 — one icon button, one pill (issue #357)

Tenth on-screen review, filed by the owner from the task drawer: the Folder block's delete was a filled square while the Links rows' pencil and trash were plain glyphs; the folder itself was a large accent-filled box while the AI-conversation link beside it was a small outlined pill; and the date calendars were filled squares wherever they met the 44 px floor. The owner's call: the Links row's glyph is the right size, icons are never shaded even when their target is 44 px, the folder takes the AI pill's look, and the fix is one system for the whole app rather than a patch on the drawer.

The design review ran first (`/design-review task-os`, live, rubric 1.13.0): grade A 97, 66/66 screens, failing TYPE-01 (spec-owned) and COMP-01. Its rubric has no rule for a button's fill at rest or for chip uniformity, and its walk never opens the drawer, where most of these controls live, so the inventory below comes from the code and from a computed-style probe on the disposable instance. The probe is now pinned in story 09 (`tests/e2e/_uniform.py`).

Shots: [drawer with folder and links, light](../screenshots/story-11-ai-links-3-desktop.png) · [the same drawer layout, dark](../screenshots/story-09-folders-6-desktop.png) · [phone drawer](../screenshots/story-09-folders-7-phone.png) · [Board strip, rows and toasts](../screenshots/story-05-board-7-desktop.png) · [Today's plan rows](../screenshots/story-29-row-actions-1-desktop.png).

## Icon buttons — before and after

Before: seven recipes. After: one, `.icon-btn` in `styles.css` — no fill, border or shadow at rest, a 16 px glyph (`--icon-inline`, the Links row's size), hover and press change only the glyph's colour, the app's one `:focus-visible` ring, and an invisible `::before` that grows whatever box the context picks (`--icon-btn-box`, 28 px by default) to the 44 px floor. Two icon buttons side by side sit `--icon-btn-gap` apart, so their targets touch and never overlap. `.is-danger` turns the glyph to the danger tone on hover.

| Control | Before | After |
| --- | --- | --- |
| Drawer: Folder delete, Blocked-by remove | `.icon-btn`: 34 px `card-off` square with a hairline | `.icon-btn.is-danger` |
| Drawer: Due / Starts calendars | `.icon-btn.field-due-btn`: 44 px `card-off` square with a hairline | `.icon-btn` |
| Drawer: Links and comments, edit and delete | `.link-rm`: 26 px, unshaded, hover always red | `.icon-btn` (pencil), `.icon-btn.is-danger` (trash) |
| Strip: quick-add `+` | `.button-surface.quick-add-btn`: 36/44 px filled square, 18 px glyph | `.icon-btn` on the strip's 36/44 px box |
| Bulk bar: date, delete, leave | `.button-surface.strip-square`: filled squares, 18 px glyph | `.icon-btn` (delete `.is-danger`) |
| Toast × | `.toast-close`: 34 px, unshaded | `.icon-btn` |
| Settings → Row actions: tick, up, down | `.icon-btn`: filled squares, ticked = accent tint | `.icon-btn`, ticked = the pressed glyph colour |
| Quick-add mic | 44 px, unshaded, hover and disabled filled | `.icon-btn` on a 44 px box; only recording paints |
| Today plan: `+`, row × | `.plan-more` (24 px) / `.plan-unplan` (44 px), unshaded | `.icon-btn` / `.icon-btn.is-danger` on a 44 px box |
| AI triage suggestion actions | `.button-ghost` with the border made transparent | `.icon-btn` on a 44 px box |
| Folder picker on the phone (glyph only) | ghost button with a hairline | the hairline goes at ≤ 520 px |
| Header theme / Settings, every modal × (vendored) | filled `--close-bg` square | `--close-bg: transparent` — the token, no vendored file touched |
| Row ⋮, completion circle (vendored action-row) | already unshaded, 44 px, 16 px glyph | unchanged: the reference the recipe matches |
| Snooze trigger (a `<summary>`) | already the same recipe: 28 px, `::before` to 44, 16 px glyph | unchanged |

Labelled buttons keep their tiers (`button-surface`, `button-ghost`, `button-tint`, `button-primary`): the Select toggle, *Change*, *Add link*, *Edit*, *Send*. The header toggles and the modal × keep the 18 px glyph their vendored component ships.

## Pills — before and after

Before: the chip and the status pill had two geometries, and four contexts restyled a chip. After: one shape for `.chip` and `.pill` (pill radius, hairline, caption step, `2px 8px`), and only colour says what a pill is — a reference (`<a>`: folder, AI conversation, issue, link, email) is the AI pill's accent-text on the accent tint, anything else the neutral chip, a status pill its status colour.

| Pill | Before | After |
| --- | --- | --- |
| Drawer folder | the chip forced into a 44 px, `radius-md`, label-size box | the reference pill, identical to the AI pill beside it |
| Calendar all-day events | `.cal-chip`: its own pill, accent tint, 600 weight, no border | `.chip` |
| Comment origin (`ui`, `cli`, `md`) | `.comment-origin`: a bordered pill with no fill, `0 6px` | `.chip` |
| Issue labels | `.chip-label-tag`: muted text, `0 6px` | `.chip` (fg text: muted fails AA on the chip fill) |
| Project chip in the drawer title | `0 6px` padding | `.chip` |
| Status pills | `1px 8px` padding, their own rule | the shared shape, their own colours and weight |

## Pinned

`tests/e2e/_uniform.py`, called from story 09 (no new test function — the suite stays at 16 collected):

- `assert_icon_buttons_uniform` — every visible icon-only button in the scope, at rest: no fill, border or shadow, an effective target of at least 44 px, one glyph size (vendored controls excepted from the size only). Run over the desktop drawer, the Board (header, strip, rows) and the phone drawer.
- `assert_focus_ring` — keyboard focus on the folder's trash draws a 2 px outline.
- `pill_style` — the folder pill's computed look equals the AI pill's, on the desktop and on the phone.

**Red first:** against the pre-change CSS, story 09 failed on the folder chip being a control-height box (`align["chip"][2] < align["input"][2]`, 44 vs 44), and, with that line skipped, on `icon buttons painted at rest` naming the drawer ×, both calendars and the folder trash.

## Verification

- `pytest tests/e2e`: 16 passed on 4 workers; the gallery re-baselined for the shots this round redraws.
- `scripts/verify-before-ship.ps1` on the branch: see the PR.
- Live instance: not walked before merge; the dispatched run restarts the tray once after its last merge, and the closing `/design-review task-os` runs against it.
- Real phone: owner-only.
