/* task-os — snooze: push a task away until it starts mattering (issue #87).
 *
 * Snooze is not a field of its own — it is `starts` worn as a row control. The
 * button opens a four-option menu; picking one PATCHes `{starts: <phrase>}` and
 * the task leaves the working views until that day. The options send the
 * *phrase*, not a date the browser computed: `src/dates.py` owns the date
 * vocabulary for the CLI, quick-add, the drawer and the mirror, and a second
 * implementation here would be a second set of rules to keep in step.
 *
 * The menu is the `<details>` disclosure the filter card's multi-select already
 * uses (shadcn Select/Popover shape: a summary that opens a grouped list,
 * Escape closes, a click outside closes), so the app has one popover idiom
 * rather than a bespoke one per feature. `Pick a date…` hands off to
 * `duePicker()` from dueinput.js — the calendar button with the coarse-pointer
 * branch — instead of hand-rolling a third native-picker call site.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { duePicker } from './dueinput.js';

/** [phrase sent to the API, what the button says]. */
export const SNOOZE_OPTIONS = [
  ['tomorrow', 'Tomorrow'],
  ['this weekend', 'This weekend'],
  ['next week', 'Next week'],
];

let wired = false;

/** One document-level listener closes any open menu — never one per row. */
function wireOutside() {
  if (wired) return;
  wired = true;
  document.addEventListener('click', function (ev) {
    document.querySelectorAll('.snooze[open]').forEach(function (d) {
      if (!d.contains(ev.target)) d.open = false;
    });
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') document.querySelectorAll('.snooze[open]').forEach(function (d) { d.open = false; });
  });
}

/**
 * The snooze control for one row.
 * @param {object} t                                     a task summary
 * @param {(id:number, phrase:string) => Promise<any>} onSnooze
 *        resolves once the PATCH landed; the caller owns the toast + undo.
 * @returns {HTMLElement} a `<details class="snooze">`
 */
export function snoozeButton(t, onSnooze) {
  wireOutside();
  const d = document.createElement('details');
  d.className = 'snooze';
  d.dataset.id = String(t.id);

  // A quiet inline icon, not a boxed button (the folder-glyph pattern): the
  // visible footprint stays icon-sized so rows keep their height, while the
  // .hit-target ::before expansion supplies the real click/touch area.
  const summary = document.createElement('summary');
  summary.className = 'snooze-summary hit-target';
  summary.setAttribute('role', 'button');
  summary.setAttribute('aria-label', 'Snooze ' + t.title);
  summary.title = 'Snooze';
  summary.innerHTML = icon('clock');
  d.appendChild(summary);

  const menu = document.createElement('div');
  menu.className = 'snooze-menu';
  menu.setAttribute('role', 'group');
  menu.setAttribute('aria-label', 'Snooze ' + t.title + ' until');

  function commit(phrase) {
    d.open = false;
    summary.setAttribute('aria-busy', 'true');
    Promise.resolve(onSnooze(t.id, phrase))
      .catch(function () { /* the caller toasts the failure */ })
      .finally(function () { summary.removeAttribute('aria-busy'); });
  }

  SNOOZE_OPTIONS.forEach(function (opt) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'snooze-opt';
    b.textContent = opt[1];
    b.addEventListener('click', function () { commit(opt[0]); });
    menu.appendChild(b);
  });

  // "Pick a date…" — the same calendar button every other date control opens.
  const pick = duePicker({
    className: 'snooze-opt snooze-pick',
    title: 'Pick a date',
    ariaLabel: 'Snooze ' + t.title + ' until a date you pick',
    onPick: function (iso) { if (iso) commit(iso); },
  });
  pick.button.innerHTML = icon('calendar-days');
  pick.button.appendChild(document.createTextNode('Pick a date…'));
  menu.append(pick.button, pick.picker);

  d.appendChild(menu);
  return d;
}
