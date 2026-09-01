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
 * The four options as a menu, with no trigger attached.
 *
 * One options list, one commit path: the Today row's button below mounts it
 * inside its `<details>`, and the `s` key (issue #99) mounts the same element
 * in a popover beside whatever row is focused — on a tab whose rows carry no
 * snooze button at all. A second list would be a second date vocabulary to
 * keep in step, which is the whole reason the phrases go to the server.
 *
 * @param {object} t                          a task summary (only `title` is read)
 * @param {(phrase:string) => void} onPick    a phrase, or an ISO date from the picker
 * @returns {HTMLElement} a `<div class="snooze-menu">`
 */
export function snoozeMenu(t, onPick) {
  const menu = document.createElement('div');
  menu.className = 'snooze-menu';
  menu.setAttribute('role', 'group');
  menu.setAttribute('aria-label', 'Snooze ' + t.title + ' until');

  SNOOZE_OPTIONS.forEach(function (opt) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'snooze-opt';
    b.textContent = opt[1];
    b.addEventListener('click', function () { onPick(opt[0]); });
    menu.appendChild(b);
  });

  // "Pick a date…" — the same calendar button every other date control opens.
  const pick = duePicker({
    className: 'snooze-opt snooze-pick',
    title: 'Pick a date',
    ariaLabel: 'Snooze ' + t.title + ' until a date you pick',
    onPick: function (iso) { if (iso) onPick(iso); },
  });
  pick.button.innerHTML = icon('calendar-days');
  pick.button.appendChild(document.createTextNode('Pick a date…'));
  menu.append(pick.button, pick.picker);
  return menu;
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

  function commit(phrase) {
    d.open = false;
    summary.setAttribute('aria-busy', 'true');
    Promise.resolve(onSnooze(t.id, phrase))
      .catch(function () { /* the caller toasts the failure */ })
      .finally(function () { summary.removeAttribute('aria-busy'); });
  }

  d.appendChild(snoozeMenu(t, commit));
  return d;
}
