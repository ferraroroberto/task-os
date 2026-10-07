/* task-os — the one outside-click / Escape closer for `<details>` popovers.
 *
 * The filter card's multi-select (filters.js) is the shadcn Select/Popover
 * shape: a summary that opens a list, a click outside or Escape closes it. A
 * second popover (the row snooze menu, since removed) once had its own private
 * `wireOutside()` — a verbatim twin differing only by the selector — so the page
 * carried two identical pairs of document listeners (#191). This is that
 * behaviour in one place: a caller registers its selector, and exactly one pair
 * of document listeners closes every family registered, however many there are.
 *
 * Popover-shaped disclosures only. A `card--collapsible` (collapsible.js) is a
 * section the reader opens and means to keep open — closing it on the next
 * click elsewhere would be a bug, so it never registers here.
 */

'use strict';

/** One `<details>` popover family per registered selector. */
const families = new Set();
let wired = false;

/**
 * Close every open popover of every registered family.
 * @param {Event|null} ev  a click whose target is left open if it is inside
 *                         the popover; `null` closes all of them (Escape).
 */
function closeOpen(ev) {
  families.forEach(function (selector) {
    document.querySelectorAll(selector + '[open]').forEach(function (d) {
      if (!ev || !d.contains(ev.target)) d.open = false;
    });
  });
}

/**
 * Register a `<details>` popover family for outside-click / Escape close.
 *
 * Idempotent, and cheap enough to call once per element built: the selector lands in a set, and the document listeners are wired on
 * the first call only, for the whole app.
 *
 * @param {string} selector  the family, e.g. `.msel` — matched
 *                           with `[open]` appended, so only open ones are read
 */
export function closeOnOutside(selector) {
  families.add(selector);
  if (wired) return;
  wired = true;
  document.addEventListener('click', function (ev) { closeOpen(ev); });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') closeOpen(null);
  });
}
