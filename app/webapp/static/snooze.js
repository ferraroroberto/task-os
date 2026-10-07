/* task-os — snooze and change-date: the one date picker a row action opens (#87, #311).
 *
 * Snooze is not a field of its own — it is `starts` worn as a row control. The
 * button opens a four-option menu; picking one PATCHes `{starts: <phrase>}` and
 * the task leaves the working views until that day. Re-dating (#311) is the
 * same menu over `due`, with Today in front and a way to clear the date. The
 * options send the *phrase*, not a date the browser computed: `src/dates.py`
 * owns the date vocabulary for the CLI, quick-add, the drawer and the mirror,
 * and a second implementation here would be a second set of rules to keep in
 * step.
 *
 * The menu is the `<details>` disclosure the filter card's multi-select already
 * uses (shadcn Select/Popover shape: a summary that opens a grouped list,
 * Escape closes, a click outside closes), so the app has one popover idiom
 * rather than a bespoke one per feature — and one implementation of it too:
 * the close-on-outside half lives in popover.js, registered per family rather
 * than re-wired here (#191). `Pick a date…` hands off to
 * `duePicker()` from dueinput.js — the calendar button with the coarse-pointer
 * branch — instead of hand-rolling a third native-picker call site.
 *
 * A row action that asks for a date (the `s` and `d` keys, the ⋯ menu's
 * Snooze… and Change date…, a swipe) opens the same menu through
 * `openDatePicker()`: anchored beside the row on a fine pointer, in the
 * vendored editor modal on a phone (#311's plan, question 5).
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { duePicker } from './dueinput.js';
import { closeOnBackdrop, modalCard } from './modal.js';
import { closeOnOutside } from './popover.js';

/** [phrase sent to the API, what the button says]. */
export const SNOOZE_OPTIONS = [
  ['tomorrow', 'Tomorrow'],
  ['this weekend', 'This weekend'],
  ['next week', 'Next week'],
];

/** Re-dating starts one step sooner than snoozing: "do it today" is a due date. */
export const DUE_OPTIONS = [['today', 'Today']].concat(SNOOZE_OPTIONS);

/** What each date field's menu says about itself. */
const FIELDS = {
  starts: {
    options: SNOOZE_OPTIONS,
    name: function (t) { return 'Snooze ' + t.title + ' until'; },
    pickName: function (t) { return 'Snooze ' + t.title + ' until a date you pick'; },
    heading: 'Snooze until',
  },
  due: {
    options: DUE_OPTIONS,
    name: function (t) { return 'Change the due date of ' + t.title; },
    pickName: function (t) { return 'Due date of ' + t.title + ': a date you pick'; },
    heading: 'Change date',
  },
};

/**
 * One date field's options as a menu, with no trigger attached.
 *
 * One options list, one commit path: the Today row's button below mounts it
 * inside its `<details>`, and `openDatePicker()` mounts the same element
 * beside whatever row asked — on a tab whose rows carry no date control at
 * all. A second list would be a second date vocabulary to keep in step, which
 * is the whole reason the phrases go to the server.
 *
 * @param {object} t                          a task summary (`title`, and `due` for the clear option)
 * @param {'starts'|'due'} field
 * @param {(phrase:string|null) => void} onPick  a phrase, an ISO date from the picker,
 *        or null ("No date" — due only, and only while the task has one)
 * @returns {HTMLElement} a `<div class="snooze-menu">`
 */
export function dateMenu(t, field, onPick) {
  const spec = FIELDS[field];
  const menu = document.createElement('div');
  menu.className = 'snooze-menu';
  menu.dataset.field = field;
  // The same popover role as the filter card's multi-select (shadcn Popover,
  // role="dialog"): a non-modal layer over the rows, never part of them (#281).
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-label', spec.name(t));

  spec.options.forEach(function (opt) {
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
    ariaLabel: spec.pickName(t),
    value: field === 'due' ? t.due : null,
    onPick: function (iso) { if (iso) onPick(iso); },
  });
  pick.button.innerHTML = icon('calendar-days');
  pick.button.appendChild(document.createTextNode('Pick a date…'));
  menu.append(pick.button, pick.picker);

  if (field === 'due' && t.due) {
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'snooze-opt snooze-clear';
    clear.innerHTML = icon('x');
    clear.appendChild(document.createTextNode('No date'));
    clear.addEventListener('click', function () { onPick(null); });
    menu.appendChild(clear);
  }
  return menu;
}

/** The snooze menu — `dateMenu` over `starts`. */
export function snoozeMenu(t, onPick) {
  return dateMenu(t, 'starts', onPick);
}

/**
 * The snooze control for one row.
 * @param {object} t                                     a task summary
 * @param {(id:number, phrase:string) => Promise<any>} onSnooze
 *        resolves once the PATCH landed; the caller owns the toast + undo.
 * @returns {HTMLElement} a `<details class="snooze">`
 */
export function snoozeButton(t, onSnooze) {
  closeOnOutside('.snooze');
  const d = document.createElement('details');
  d.className = 'snooze';
  d.dataset.id = String(t.id);
  // One snooze menu open at a time across the list (an exclusive `<details
  // name>` group), the same rule popover.js applies on an outside click (#281).
  d.setAttribute('name', 'task-os-snooze');

  // A quiet inline icon, not a boxed button (the folder-glyph pattern): the
  // visible footprint stays icon-sized so rows keep their height, while the
  // .hit-target ::before expansion supplies the real click/touch area.
  const summary = document.createElement('summary');
  summary.className = 'snooze-summary hit-target';
  summary.setAttribute('role', 'button');
  summary.setAttribute('aria-haspopup', 'dialog');
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

// ------------------------------------------------------- the open picker
let open = null;   // {close} — the one date picker on screen, if any

/** Is a date picker up? (The keymap stops while it is.) */
export function isDatePickerOpen() { return !!open; }

/** Close the date picker without a pick. */
export function closeDatePicker() { if (open) open.close(); }

function markRow(anchor) {
  const row = anchor && anchor.closest ? anchor.closest('.trow') : null;
  // The menu takes focus, so the row loses its :focus-within tint just as the
  // user is about to pick a date for it — keep it marked explicitly.
  if (row) row.classList.add('is-key-target');
  return function () { if (row) row.classList.remove('is-key-target'); };
}

/** Fine pointer: the menu pinned beside the anchor, closed by an outside
 *  click, a scroll (it is pinned to the viewport) or Escape. */
function openPopover(t, field, anchor, onPick) {
  const pop = document.createElement('div');
  pop.className = 'snooze-pop';
  const unmark = markRow(anchor);
  function close() {
    if (open !== handle) return;
    open = null;
    pop.remove();
    unmark();
    document.removeEventListener('click', onOutside, true);
    window.removeEventListener('scroll', close, true);
  }
  function onOutside(ev) { if (!pop.contains(ev.target)) close(); }
  const handle = { close: close };
  pop.appendChild(dateMenu(t, field, function (phrase) { close(); onPick(phrase); }));
  document.body.appendChild(pop);
  const r = (anchor || document.body).getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + 'px';
  pop.style.top = Math.max(8, Math.min(r.bottom + 4, window.innerHeight - pop.offsetHeight - 8)) + 'px';
  // registered after this tick, so the click that opened it does not close it
  setTimeout(function () {
    if (open !== handle) return;
    document.addEventListener('click', onOutside, true);
    window.addEventListener('scroll', close, true);
  }, 0);
  open = handle;
  const first = pop.querySelector('.snooze-opt');
  if (first) first.focus();
}

/** Coarse pointer: the vendored editor modal, top-anchored on the phone. */
function openDialog(t, field, onPick) {
  const dialog = document.getElementById('dateDialog');
  if (!dialog) return;
  const card = modalCard({
    cardClass: 'date-card', title: FIELDS[field].heading, titleId: 'dateDialogTitle',
    closeLabel: 'Cancel', onClose: function () { dialog.close(); },
  }).card;
  const name = document.createElement('p');
  name.className = 'date-card-task muted';
  name.textContent = t.title;
  let picked;   // undefined = nothing picked; null is a pick ("No date")
  const menu = dateMenu(t, field, function (phrase) { picked = phrase; dialog.close(); });
  menu.classList.add('date-sheet');
  card.append(name, menu);
  const handle = { close: function () { dialog.close(); } };
  const offBackdrop = closeOnBackdrop(dialog);
  dialog.addEventListener('close', function onClose() {
    dialog.removeEventListener('close', onClose);
    offBackdrop();
    dialog.replaceChildren();
    if (open === handle) open = null;
    if (picked !== undefined) onPick(picked);
  });
  dialog.replaceChildren(card);
  open = handle;
  dialog.showModal();
}

/**
 * Ask for a date for one task: a phrase, an ISO date, or null to clear `due`.
 * Nothing is written here — `onPick` runs only on a pick, never on a cancel.
 * @param {object} t
 * @param {'starts'|'due'} field
 * @param {HTMLElement|null} anchor   what the popover sits beside (a row, a kebab, the bulk bar)
 * @param {(phrase:string|null) => void} onPick
 */
export function openDatePicker(t, field, anchor, onPick) {
  closeDatePicker();
  if (window.matchMedia('(pointer: coarse)').matches) openDialog(t, field, onPick);
  else openPopover(t, field, anchor, onPick);
}
