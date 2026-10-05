/* task-os — the keyboard walk of a data grid (#339).
 *
 * The desktop Archive table is a data table, not an action list: every cell
 * holds a value, and some values are live — a file chip, a mail's Accept /
 * Move buttons. It is an ARIA grid, so those controls are the cells' widgets rather than a list row's
 * action budget (design.md action-row: "a list is not a spreadsheet"), and
 * the keyboard reaches them the grid way:
 *
 *   on a row       ↓ ↑  next / previous row     Home / End  first / last row
 *                  →    the row's first control
 *   on a control   → ←  next / previous control in the row; ← from the first
 *                       one goes back to the row
 *
 * A select keeps ↑ ↓ (they change its value) and passes → ← on; a text field
 * would keep every arrow (its caret's). Esc is left alone: it already closes
 * the folder popover, the drawer and Select mode. Tab still walks the rows,
 * as the shortcuts sheet says.
 */

'use strict';

/** A row's cell widgets. The due cell's native date input is the picker's
 *  hidden proxy, never a stop of its own. */
const CONTROLS = 'a[href], button:not([disabled]), select:not([disabled]), '
  + 'input:not([type="hidden"]):not(.due-date), textarea';
/** Widgets whose → ← are their own (the caret's). */
const OWN_ARROWS = 'input:not([type="checkbox"]), textarea';

/**
 * Mark `table` as a data grid named `label` and give its body rows the walk.
 * Rows take part when they are focusable (`tabIndex = 0`) and shown.
 * @param {HTMLTableElement} table
 * @param {string} label
 */
export function markGrid(table, label) {
  table.setAttribute('role', 'grid');
  table.setAttribute('aria-label', label);
  table.addEventListener('keydown', onKey);
}

function rowsOf(row) {
  return Array.from(row.parentElement.children).filter(function (r) {
    return r.tabIndex >= 0 && !r.hidden;
  });
}

function controlsOf(row) {
  return Array.from(row.querySelectorAll(CONTROLS)).filter(function (el) {
    return el.getClientRects().length > 0;
  });
}

function go(el) {
  if (!el) return;
  el.focus();
  el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function onKey(ev) {
  if (ev.defaultPrevented || ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
  const row = ev.target.closest('tbody > tr');
  if (!row || row.tabIndex < 0) return;
  let to = null;
  if (ev.target === row) {
    const rows = rowsOf(row);
    const i = rows.indexOf(row);
    if (ev.key === 'ArrowDown') to = rows[i + 1];
    else if (ev.key === 'ArrowUp') to = rows[i - 1];
    else if (ev.key === 'Home') to = rows[0];
    else if (ev.key === 'End') to = rows[rows.length - 1];
    else if (ev.key === 'ArrowRight') to = controlsOf(row)[0];
    else return;
  } else {
    const own = ev.target.matches(OWN_ARROWS);
    const ctl = controlsOf(row);
    const i = ctl.indexOf(ev.target);
    if (own || i < 0) return;
    if (ev.key === 'ArrowRight') to = ctl[i + 1];
    else if (ev.key === 'ArrowLeft') to = i === 0 ? row : ctl[i - 1];
    else return;
  }
  ev.preventDefault();
  go(to);
}
