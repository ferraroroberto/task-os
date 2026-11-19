/* task-os — the drawer's single-field editors.
 *
 * Every builder takes the drawer's `ctx` (see drawer.js) first: `ctx.patch`
 * is the one write path, `ctx.opts` the caller's hooks.
 */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { duePicker } from '../../dueinput.js';
import { intervalUnit } from '../../recurrence.js';
import { DUE_OPTIONS, dateChips, keyHint } from '../../snooze.js';
import { Status } from '../tasks/status.js';

/** The statuses a task is moved between by hand, with the key each answers
 *  to while the task is open. Inbox is where a task waits to be filed, not a
 *  state to pick, so it has no segment (the head tags an Inbox task, and the
 *  `1` key still sends one back); Cancelled is rare and has no key, so a stray
 *  key never closes a task. */
const STATUS_SEGMENTS = [
  [Status.TODO, 'To do', '2'],
  [Status.STANDBY, 'Standby', '3'],
  [Status.CANCELLED, 'Cancelled', null],
  [Status.DONE, 'Done', 'X'],
];

/** Status as the vendored segmented control: the raised segment is the
 *  state, one tap moves it. Done closes the drawer (ctx.setStatus). */
export function statusSegment(ctx, t) {
  const group = document.createElement('div');
  group.className = 'segmented segmented--verbs drawer-status';
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Status');
  group.dataset.field = 'status';
  STATUS_SEGMENTS.forEach(function (s) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'segmented-item';
    b.dataset.track = 'drawer.status';
    b.dataset.status = s[0];
    b.setAttribute('aria-pressed', String(t.status === s[0]));
    if (s[0] === Status.DONE) b.innerHTML = icon('check');
    b.appendChild(document.createTextNode(s[1]));
    if (s[2]) {
      b.setAttribute('aria-keyshortcuts', s[2]);
      b.appendChild(keyHint(s[2]));
    }
    b.addEventListener('click', function () { ctx.setStatus(s[0]); });
    group.appendChild(b);
  });
  return group;
}

/** Due's one-tap moves: the date chips the row's date menu shows too, each
 *  over the day it lands on, the task's own day marked. */
export function dueBlock(ctx, t) {
  const wrap = document.createElement('div');
  wrap.className = 'drawer-due';
  const label = document.createElement('div');
  label.className = 'drawer-label';
  label.textContent = 'Due';
  const chips = dateChips(DUE_OPTIONS, {
    onPick: function (phrase) { ctx.patch({ due: phrase }); },
    current: t.due,
    pickLabel: 'Pick a due date',
    keys: true,
  });
  chips.grid.setAttribute('aria-label', 'Move the due date');
  wrap.append(label, chips.grid, chips.picker);
  return wrap;
}

/** How many cadences a recurrence waits between occurrences — "Every
 *  [7] weeks", between Repeat and On so the three read as one sentence.
 *
 *  Empty (or 1) is every cadence and PATCHes null; the unit follows the
 *  cadence. A digit keypad on the phone (`inputmode`) rather than
 *  `type=number`, whose desktop spinner and wheel-scrolling would change the
 *  value by accident. A bad value is the server's 422, toasted, and the
 *  refresh puts the stored interval back.
 */
export function intervalField(ctx, t) {
  const wrap = document.createElement('label');
  wrap.className = 'field';
  const l = document.createElement('span');
  l.className = 'field-label';
  l.textContent = 'Every';
  const row = document.createElement('span');
  row.className = 'field-interval-row';
  const input = document.createElement('input');
  input.type = 'text';
  input.inputMode = 'numeric';
  input.pattern = '[0-9]*';
  input.className = 'input-native field-control';
  input.dataset.field = 'recurrence_interval';
  input.placeholder = '1';
  const stored = t.recurrence_interval ? String(t.recurrence_interval) : '';
  input.value = stored;
  const unit = document.createElement('span');
  unit.className = 'field-unit';
  unit.textContent = intervalUnit(t.recurrence);
  function commit() {
    const v = input.value.trim();
    if (v === stored || (v === '1' && stored === '')) { input.value = stored; return; }
    ctx.patch({ recurrence_interval: v === '' || v === '1' ? null : (/^\d+$/.test(v) ? Number(v) : v) });
  }
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { input.value = stored; input.blur(); }
  });
  input.addEventListener('blur', commit);
  row.append(input, unit);
  wrap.append(l, row);
  return wrap;
}

/** The fixed day a recurrence lands on — the Repeat field's second half.
 *
 *  Its own builder rather than `selectField` because the monthly vocabulary
 *  is long enough to need `<optgroup>`s; the PATCH it sends is the same
 *  single-field one.
 */
export function anchorField(ctx, t, groups) {
  const wrap = document.createElement('label');
  wrap.className = 'field';
  const l = document.createElement('span');
  l.className = 'field-label';
  l.textContent = 'On';
  const sel = document.createElement('select');
  sel.dataset.track = 'drawer.recurrence-anchor';
  sel.className = 'select-native field-control';
  sel.dataset.field = 'recurrence_anchor';
  groups.forEach(function (group) {
    const target = group.label ? document.createElement('optgroup') : sel;
    if (group.label) target.label = group.label;
    group.options.forEach(function (pair) {
      const o = document.createElement('option');
      o.value = pair[0];
      o.textContent = pair[1];
      if (pair[0] === (t.recurrence_anchor || '')) o.selected = true;
      target.appendChild(o);
    });
    if (group.label) sel.appendChild(target);
  });
  sel.addEventListener('change', function () {
    ctx.patch({ recurrence_anchor: sel.value === '' ? null : sel.value });
  });
  wrap.append(l, sel);
  return wrap;
}

export function textField(ctx, label, name, value, placeholder) {
  const wrap = document.createElement('label');
  wrap.className = 'field';
  const l = document.createElement('span');
  l.className = 'field-label';
  l.textContent = label;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'input-native field-control';
  input.dataset.field = name;
  input.value = value || '';
  input.placeholder = placeholder || '';
  function commit() {
    const v = input.value.trim();
    if (v === (value || '')) return;
    const body = {};
    body[name] = v === '' ? null : v;
    ctx.patch(body);
  }
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { input.value = value || ''; input.blur(); }
  });
  input.addEventListener('blur', commit);
  wrap.append(l, input);
  return wrap;
}

/** A date field: a picker by default (the calendar button opens the native
 *  one), typing still works — `tomorrow`, `fri`, `in 2 weeks`, ISO. **Starts**
 *  uses it; the calendar is `duePicker()`'s, so the coarse-pointer branch
 *  lives once for the whole app.
 * @param {object} ctx
 * @param {object} t
 * @param {string} field   the task field this edits ('due' | 'starts')
 * @param {string} label   the field label
 * @param {string} caption optional suffix on the label ("· in 3d")
 */
export function dateField(ctx, t, field, label, caption) {
  const value = t[field] || '';
  const wrap = document.createElement('label');
  wrap.className = 'field field-date field-' + field;
  const l = document.createElement('span');
  l.className = 'field-label';
  l.textContent = label + (value && caption ? ' · ' + caption : '');
  const row = document.createElement('span');
  row.className = 'field-due-row';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'input-native field-control';
  input.dataset.field = field;
  input.value = value;
  input.placeholder = 'tomorrow · fri · 2026-09-01';
  input.setAttribute('aria-label', label);
  function commit(v) {
    if (v === value) return;
    ctx.patch(Object.fromEntries([[field, v === '' ? null : v]]));
  }
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { input.value = value; input.blur(); }
  });
  input.addEventListener('blur', function () { commit(input.value.trim()); });
  const pick = duePicker({
    className: 'icon-button field-due-btn',     // the one icon button
    track: 'drawer.date-pick',
    value: value,
    ariaLabel: 'Pick a ' + label.toLowerCase() + ' date',
    onPick: commit,
  });
  row.append(input, pick.button, pick.picker);
  wrap.append(l, row);
  return wrap;
}

/** A member id as the name the members list gives it — the id itself once
 *  that member is gone (an old activity row, a task never reassigned). */
export function memberName(ctx, id) {
  const m = (ctx.opts.members() || []).find(function (x) { return x.id === id; });
  return m ? m.name : (id || '—');
}
