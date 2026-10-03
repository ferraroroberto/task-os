# `row-menu` — the kebab's floating action list

One anchor button per list row (the 44px kebab of an `action-row`, or any button) opens a vertical list of icon + label actions. **The list is data the app passes in** — the component hard-codes no item — so an app can let its user choose what the kebab holds. The open menu escapes every scrolling ancestor (a sideways column carousel, a card with overflow), follows the menu-button keyboard pattern, and keeps a destructive action last, after a divider, in `danger-text` (the `action-row` contract, `~/.claude/design.md`). Normalized from app-launcher's `row-menu.js` (`app-launcher#953/#977/#996`); the first kebab of task-os's row redesign builds on it (`project-scaffolding#317`).

## Files

| File | Role |
| --- | --- |
| `row-menu.css` | Visual contract: the raised surface, 44px rows, hover/focus/disabled/danger states. References design tokens only. |
| `row-menu.js` | ESM `createRowMenu(opts)` → `attach` / `endRender` / `close` / `isOpen`. Builds the menu, places it, owns focus and dismissal. |
| `row-menu.html` | Markup skeleton of the anchor and the menu the script builds (prefer the script). |

It also needs the vendored `icons/` sprite (`row-menu.js` imports `../icons/icons.js` for each item's `glyph`; the kebab itself is `i-ellipsis-vertical`).

## How to vendor

1. Copy this `row-menu/` folder **verbatim** into your app's `_vendored/` dir, next to `icons/`. Do **not** edit `row-menu.css` / `row-menu.js` per-app.
2. Link the CSS and import the builder:
   ```html
   <link rel="stylesheet" href="/static/_vendored/row-menu/row-menu.css">
   ```
   ```js
   import { createRowMenu } from '/static/_vendored/row-menu/row-menu.js';
   ```
3. Define the tokens below.

## API

```js
const rowMenu = createRowMenu();            // once per list

function renderRows(rows) {
  list.replaceChildren(...rows.map((row) => {
    const li = rowEl(row);                  // your row markup, including the kebab button
    rowMenu.attach(row.id, li.querySelector('.kebab'), [
      { label: 'Rename', glyph: 'pencil', onTap: () => rename(row) },
      { label: 'Pin', glyph: 'pin', hidden: () => row.pinned, onTap: () => pin(row) },
      { label: 'Delete', glyph: 'trash-2', danger: true, onTap: () => confirmDelete(row) },
    ]);
    return li;
  }));
  rowMenu.endRender();                      // once, after the list is rebuilt
}
```

- **`createRowMenu({ className? })`** returns the controller for one list; at most one of its menus is open. `className` is added to each menu as the app's own hook.
- **`attach(key, anchor, items)`** wires `anchor` to toggle a menu for the row `key` (its identity across re-renders) and returns the menu element. The menu is mounted only while open. If this row's menu was open before a re-render (a poll rebuilt the list), it reopens on the new anchor, without moving focus unless focus was already inside the menu.
- **`endRender()`** — call once after the rebuild; an open menu whose row is gone drops its state.
- **`close()`** closes any open menu; **`isOpen(key)`** reports whether that row's menu is open.

### Items

`items` is an array of plain objects, rendered in order. Every property but `label` and `onTap` is optional, and each may be a **function of no arguments**, re-evaluated every time the menu opens (so a row's glyph, caption or visibility can follow state).

| Property | Meaning |
| --- | --- |
| `label` | The caption, which is also the accessible name. Plain text, set with `textContent`. |
| `onTap()` | Runs after the menu has closed and focus is back on the anchor. |
| `glyph` | A sprite name from `icons/` without the `i-` prefix; no glyph, no icon. |
| `danger` | Destructive: moved after a divider to the end, in `--danger-text`. Any confirm is yours, inside `onTap`. |
| `disabled` | Stays visible and focusable with `aria-disabled="true"`, muted, and does nothing when chosen. |
| `hint` | The `title` shown on a disabled item, to say why. |
| `hidden` | Left out of the menu this time (detached, so a count of the menu's buttons sees only what is offered). |
| `dataset` | `data-*` attributes on the row, for your own hooks. |

## Behaviour contract

- **Placement.** The open menu is `position: fixed`, mounted on `<body>` (or on the anchor's open `<dialog>`, whose top layer would hide a body child) and placed from the anchor's rect: below it with the right edges aligned, above it when there is no room below, clamped 8px inside the viewport. It repositions on resize, on any scroll (capture) and on the visual viewport, so it follows an anchor inside a sideways-scrolling column and is never clipped by it.
- **Dismissal.** Closes on a press outside, on `Escape` (which does not also close a surrounding dialog), on a second tap of the anchor, on choosing an item, and on `Tab`.
- **Menu-button pattern.** The anchor carries `aria-haspopup="menu"`, `aria-expanded` and `aria-controls`; the list is `role="menu"` of `role="menuitem"` buttons with a roving `tabindex`. `Enter` / `Space` / a tap open it with the first item focused; `ArrowDown` / `ArrowUp` on the anchor open it on the first / last item; inside, `ArrowDown` / `ArrowUp` move (wrapping), `Home` / `End` jump. `Escape`, choosing an item and `Tab` return focus to the anchor, and a press outside leaves focus where the user put it.
- **Visible focus.** Both the anchor and each row show a 2px `--accent` ring on `:focus-visible`; the row's ring is inset so the menu's border never clips it.

## Required design tokens

| Token | Light value | Used for |
| --- | --- | --- |
| `--card` | `#ffffff` (dark `#161b22`) | menu surface |
| `--line` | `#d1d9e0` (dark `#30363d`) | menu hairline, divider |
| `--shadow` | `0 8px 24px rgba(31,35,40,.12)` | the menu's raised shadow |
| `--ink` | `#1f2328` (dark `#e6edf3`) | row text |
| `--muted` | `#656d76` (dark `#7d8590`) | disabled row |
| `--danger-text` | `#a40e26` (dark `#ff7b72`) | destructive row |
| `--accent` / `--accent-soft` | `#0969da` / 16% mix | open anchor, focus ring, hover fill |
| `--radius-md`, `--radius-sm` (fallback 8px) | `12px`, `8px` | menu / row corners |
| `--row-sm`, `--icon-inline`, `--font-body` | `44px`, `16px`, `1rem` | row height, glyph, text |

The design spec has no `row-menu` token block yet; this recipe reuses the toast's `--shadow` and the card tokens (`project-scaffolding#317`).

## Don't diverge

`row-menu.css` / `row-menu.js` are vendored verbatim — to change the contract, change it **here in `project-scaffolding`** and re-vendor downstream. Don't hand-roll a per-app menu, don't add per-app placement CSS (the script owns top/left; a `position: absolute` menu is exactly what a scrolling column clips), and don't hard-code items in the component: the app passes them in. Streamlit POC spikes are exempt.
