/* task-os — snooze and change-date: the one date picker a row action opens.
 *
 * Every date change reached from a list moves the *due* date, so the task
 * stays on the Board in its new place; the start date is edited from the
 * drawer's field alone (a task whose start day has not come leaves the working
 * views). The menu offers the push-outs, Today and a way to clear the date. The
 * options send the *phrase*, not a date the browser computed: `src/dates.py`
 * owns the date vocabulary for the CLI, quick-add, the drawer and the mirror,
 * and a second implementation here would be a second set of rules to keep in
 * step.
 *
 * The menu is the shadcn Select/Popover shape (a grouped list, Escape
 * closes, a click outside closes). `Pick a date…`
 * hands off to `duePicker()` from dueinput.js — the calendar button with the coarse-pointer
 * branch — instead of hand-rolling a third native-picker call site.
 *
 * A row action that asks for a date (the `d` key, the ⋯ menu's Move…, a
 * swipe, the desktop row's Move button and Select mode's Move) opens the same menu through
 * `openDatePicker()`: anchored beside the row on a fine pointer, in the
 * vendored editor modal on a phone.
 *
 * The date sheet: every phrase shows the date it resolves to today, in one
 * compact grid of chips (`dateChips()`, four across and two rows, with "Pick a
 * date…" as the eighth cell). The drawer's Due block lays out the same grid,
 * so a phrase looks and means the same wherever it is offered. The
 * dates come from the server (`GET /api/dates`, the same `parse_date` the
 * write runs), read once per local day into a cache the app primes at every
 * refresh, so the sheet opens with them already filled in.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { api, qs } from './api.js';
import { duePicker } from './dueinput.js';
import { fmtDay, todayISO } from './format.js';
import { modalCard, onceClosed } from './modal.js';

/** [phrase sent to the API, what the chip says]: nearest first, read along
 *  the grid's two rows like a calendar. The labels are short so four fit
 *  across a phone; the date under each says exactly which day it is. */
export const DUE_OPTIONS = [
  ['today', 'Today'],
  ['tomorrow', 'Tomorrow'],
  ['this friday', 'This Fri'],
  ['this weekend', 'Weekend'],
  ['next week', 'Next week'],
  ['upcoming monday', 'Next Mon'],
  ['end of month', 'Month end'],
];

/** The single key a chip answers to while a task is open (keys.js routes
 *  them), shown on the chip as a hint on a fine pointer. */
const CHIP_KEYS = { tomorrow: 'T', 'next week': 'W' };

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

/** Fill each option's date, now if today's answer is cached, else when it
 *  lands; the chip whose date is `current` is marked as the one in force. */
function fillDates(buttons, current) {
  const fill = function (dates) {
    if (!dates) return;
    buttons.forEach(function (b) {
      const iso = dates[b.dataset.phrase];
      const slot = b.querySelector('.snooze-opt-date');
      if (iso && slot) { slot.textContent = fmtDay(iso); slot.dataset.date = iso; }
      if (current && iso === current) b.setAttribute('aria-current', 'date');
      else b.removeAttribute('aria-current');
    });
  };
  if (phraseDates && phraseDates.day === todayISO()) fill(phraseDates.dates);
  else loadPhraseDates().then(fill);
}

/** A key hint on a control: drawn on a fine pointer only (CSS) and kept out
 *  of the accessible name, which the control's `aria-keyshortcuts` carries. */
export function keyHint(key) {
  const k = document.createElement('kbd');
  k.className = 'key-hint';
  k.setAttribute('aria-hidden', 'true');
  k.textContent = key;
  return k;
}

/**
 * The date chips: every phrase over the date it resolves to today, then "Pick…"
 * as the last cell, in one 4×2 grid of 44px chips. The row's date menu and the
 * drawer's Due block both build it here, so the two never drift.
 * @param {Array<[string,string]>} options   [phrase, label] pairs
 * @param {{onPick: (phrase:string) => void, current?: string|null,
 *          pickLabel: string, keys?: boolean}} o
 *        `current` is the task's due date (its chip is marked); `pickLabel`
 *        the calendar chip's accessible name; `keys` adds the shortcut hints.
 * @returns {{grid: HTMLElement, picker: HTMLInputElement, pick: HTMLButtonElement}}
 *        the native date input stays outside the grid, since on a phone it
 *        shows inline under it
 */
export function dateChips(options, o) {
  const grid = document.createElement('div');
  grid.className = 'date-chips';
  grid.setAttribute('role', 'group');
  const buttons = options.map(function (opt) {
    const b = document.createElement('button');
    b.dataset.track = 'snooze.option';
    b.type = 'button';
    b.className = 'snooze-opt date-chip';
    b.dataset.phrase = opt[0];
    const label = document.createElement('span');
    label.className = 'snooze-opt-label';
    label.textContent = opt[1];
    const when = document.createElement('span');
    when.className = 'snooze-opt-date';
    b.append(label, when);
    if (o.keys && CHIP_KEYS[opt[0]]) {
      b.setAttribute('aria-keyshortcuts', CHIP_KEYS[opt[0]]);
      b.appendChild(keyHint(CHIP_KEYS[opt[0]]));
    }
    b.addEventListener('click', function () { o.onPick(opt[0]); });
    return b;
  });
  fillDates(buttons, o.current || null);
  // "Pick…": the same calendar button every other date control opens.
  const pick = duePicker({
    className: 'snooze-opt date-chip snooze-pick',
    track: 'snooze.pick-date',
    title: 'Pick a date',
    ariaLabel: o.pickLabel,
    value: o.current || null,
    onPick: function (iso) { if (iso) o.onPick(iso); },
  });
  const pickLabel = document.createElement('span');
  pickLabel.className = 'snooze-opt-label';
  pickLabel.textContent = 'Pick…';
  pick.button.appendChild(pickLabel);
  if (o.keys) {
    pick.button.setAttribute('aria-keyshortcuts', 'D');
    pick.button.appendChild(keyHint('D'));
  }
  grid.append(...buttons, pick.button);
  return { grid: grid, picker: pick.picker, pick: pick.button };
}

const DIALOG_HEADING = 'Move to a date';

/**
 * The due-date options as a menu, with no trigger attached.
 *
 * One options list, one commit path: `openDatePicker()` mounts it beside
 * whatever row asked (a popover on a fine pointer, the modal on a phone). A
 * second list would be a second date vocabulary to keep in step, which is the
 * whole reason the phrases go to the server.
 *
 * @param {object} t                          a task summary (`title`, and `due` for the clear option)
 * @param {(phrase:string|null) => void} onPick  a phrase, an ISO date from the picker,
 *        or null ("No date", only while the task has a date)
 * @returns {HTMLElement} a `<div class="snooze-menu">`
 */
export function dateMenu(t, onPick) {
  const menu = document.createElement('div');
  menu.className = 'snooze-menu';
  // The shadcn Popover role (role="dialog"): a non-modal layer over the
  // rows, never part of them.
  menu.setAttribute('role', 'dialog');
  // duplicate-surface-exempt: the mouse's popover for the one date surface a phone gets as #dateDialog in index.html
  menu.dataset.surface = 'row.date';
  menu.setAttribute('aria-label', 'Move ' + t.title + ' to another date');

  const chips = dateChips(DUE_OPTIONS, {
    onPick: onPick, current: t.due, pickLabel: 'Due date of ' + t.title + ': a date you pick',
  });
  menu.append(chips.grid, chips.picker);

  // `clearable`: a selection — its tasks' dates are not known here,
  // so "No date" is always offered; clearing an undated task changes nothing
  if (t.due || t.clearable) {
    const clear = document.createElement('button');
    clear.dataset.track = 'snooze.clear';
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
function openPopover(t, anchor, onPick) {
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
  pop.appendChild(dateMenu(t, function (phrase) { close(); onPick(phrase); }));
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
  const first = pop.querySelector('.snooze-opt[aria-current]') || pop.querySelector('.snooze-opt');
  if (first) first.focus();
}

/** Coarse pointer: the vendored editor modal, top-anchored on the phone. */
function openDialog(t, onPick) {
  const dialog = document.getElementById('dateDialog');
  if (!dialog) return;
  const card = modalCard({
    cardClass: 'date-card', title: DIALOG_HEADING, titleId: 'dateDialogTitle',
    closeLabel: 'Cancel', onClose: function () { dialog.close(); },
  }).card;
  const name = document.createElement('p');
  name.className = 'date-card-task muted';
  name.textContent = t.title;
  let picked;   // undefined = nothing picked; null is a pick ("No date")
  const menu = dateMenu(t, function (phrase) { picked = phrase; dialog.close(); });
  menu.classList.add('date-sheet');
  card.append(name, menu);
  const handle = { close: function () { dialog.close(); } };
  onceClosed(dialog, function () {
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
 * @param {HTMLElement|null} anchor   what the popover sits beside (a row, a kebab, the bulk bar)
 * @param {(phrase:string|null) => void} onPick
 */
export function openDatePicker(t, anchor, onPick) {
  closeDatePicker();
  if (window.matchMedia('(pointer: coarse)').matches) openDialog(t, onPick);
  else openPopover(t, anchor, onPick);
}
