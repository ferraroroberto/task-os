/* task-os — snooze and change-date: the one date picker a row action opens (#87, #311).
 *
 * Snooze is not a field of its own — it is `starts` worn as a row action. The
 * menu offers four options; picking one PATCHes `{starts: <phrase>}` and the
 * task leaves the working views until that day. Re-dating (#311) is the
 * same menu over `due`, with Today in front and a way to clear the date. The
 * options send the *phrase*, not a date the browser computed: `src/dates.py`
 * owns the date vocabulary for the CLI, quick-add, the drawer and the mirror,
 * and a second implementation here would be a second set of rules to keep in
 * step.
 *
 * The menu is the shadcn Select/Popover shape the filter card's multi-select
 * also uses (a grouped list, Escape closes, a click outside closes), so the app
 * has one popover idiom rather than a bespoke one per feature. `Pick a date…`
 * hands off to `duePicker()` from dueinput.js — the calendar button with the coarse-pointer
 * branch — instead of hand-rolling a third native-picker call site.
 *
 * A row action that asks for a date (the `s` and `d` keys, the ⋯ menu's
 * Snooze… and Move…, a swipe, the desktop row's Move button and Select mode's
 * Move, #392) opens the same menu through
 * `openDatePicker()`: anchored beside the row on a fine pointer, in the
 * vendored editor modal on a phone (#311's plan, question 5).
 *
 * The date sheet (#391): every phrase shows the date it resolves to today,
 * and the push-out phrases come first — most re-dates push a task out. The
 * dates come from the server (`GET /api/dates`, the same `parse_date` the
 * write runs), read once per local day into a cache the app primes at every
 * refresh, so the sheet opens with them already filled in.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { api, qs } from './api.js';
import { duePicker } from './dueinput.js';
import { fmtDay, todayISO } from './format.js';
import { closeOnBackdrop, modalCard } from './modal.js';

/** [phrase sent to the API, what the button says]. */
export const SNOOZE_OPTIONS = [
  ['tomorrow', 'Tomorrow'],
  ['this weekend', 'This weekend'],
  ['next week', 'Next week'],
];

/** Re-dating offers one step sooner than snoozing — "do it today" is a due
 *  date — after the push-outs, which are most re-dates (#391). */
export const DUE_OPTIONS = SNOOZE_OPTIONS.concat([['today', 'Today']]);

// ------------------------------------------------- what each phrase means
const PHRASES = DUE_OPTIONS.map(function (opt) { return opt[0]; });
let phraseDates = null;   // {day, dates: {phrase: ISO}} — the server's answer for one local day
let phraseLoad = null;    // the read in flight, if any

/**
 * Read what each sheet phrase resolves to today, once per local day. Never
 * throws: a failed read leaves the sheet without dates (the phrase alone is
 * still the right pick), logs why, and the next call asks again.
 * @returns {Promise<Object<string,string>|null>}
 */
export function loadPhraseDates() {
  const day = todayISO();
  if (phraseDates && phraseDates.day === day) return Promise.resolve(phraseDates.dates);
  if (phraseLoad) return phraseLoad;
  phraseLoad = api('/api/dates' + qs({ phrases: PHRASES })).then(function (res) {
    phraseDates = { day: day, dates: res.dates || {} };
    return phraseDates.dates;
  }).catch(function (err) {
    console.warn('task-os: date phrases not resolved', err);
    return null;
  }).finally(function () { phraseLoad = null; });
  return phraseLoad;
}

/** Fill each option's date, now if today's answer is cached, else when it lands. */
function fillDates(buttons) {
  const fill = function (dates) {
    if (!dates) return;
    buttons.forEach(function (b) {
      const iso = dates[b.dataset.phrase];
      const slot = b.querySelector('.snooze-opt-date');
      if (iso && slot) { slot.textContent = fmtDay(iso); slot.dataset.date = iso; }
    });
  };
  if (phraseDates && phraseDates.day === todayISO()) fill(phraseDates.dates);
  else loadPhraseDates().then(fill);
}

/**
 * The phrases as buttons: each one's label, and the date it resolves to today
 * once that is known. The sheet below lists them; the drawer lays the same
 * buttons out as its quick moves under Due (#394), so a phrase means one date
 * wherever it is offered.
 * @param {Array<[string,string]>} options   [phrase, label] pairs
 * @param {(phrase:string) => void} onPick
 * @returns {HTMLButtonElement[]}
 */
export function phraseButtons(options, onPick) {
  const buttons = options.map(function (opt) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'snooze-opt';
    b.dataset.phrase = opt[0];
    const label = document.createElement('span');
    label.className = 'snooze-opt-label';
    label.textContent = opt[1];
    const when = document.createElement('span');
    when.className = 'snooze-opt-date';
    b.append(label, when);
    b.addEventListener('click', function () { onPick(opt[0]); });
    return b;
  });
  fillDates(buttons);
  return buttons;
}

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
    name: function (t) { return 'Move ' + t.title + ' to another date'; },
    pickName: function (t) { return 'Due date of ' + t.title + ': a date you pick'; },
    heading: 'Move to a date',
  },
};

/**
 * One date field's options as a menu, with no trigger attached.
 *
 * One options list, one commit path: `openDatePicker()` mounts it beside
 * whatever row asked (a popover on a fine pointer, the modal on a phone). A
 * second list would be a second date vocabulary to keep in step, which is the
 * whole reason the phrases go to the server.
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

  menu.append(...phraseButtons(spec.options, onPick));

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

  // `clearable`: a selection (#392) — its tasks' dates are not known here,
  // so "No date" is always offered; clearing an undated task changes nothing
  if (field === 'due' && (t.due || t.clearable)) {
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
