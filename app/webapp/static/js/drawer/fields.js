/* task-os — the drawer's single-field editors.
 *
 * Every builder takes the drawer's `ctx` (see drawer.js) first: `ctx.patch`
 * is the one write path, `ctx.opts` the caller's hooks.
 */

'use strict';

import { duePicker } from '../../dueinput.js';
import { intervalUnit } from '../../recurrence.js';
import { statusOptions } from '../../rows.js';
import { DUE_OPTIONS, phraseButtons } from '../../snooze.js';

export function selectField(ctx, label, name, values, value, format) {
  const wrap = document.createElement('label');
  wrap.className = 'field';
  const l = document.createElement('span');
  l.className = 'field-label';
  l.textContent = label;
  const sel = document.createElement('select');
  sel.className = 'select-native field-control';
  sel.dataset.field = name;
  values.forEach(function (v) {
    const o = document.createElement('option');
    o.value = v == null ? '' : String(v);
    o.textContent = format ? format(v) : (v || '—');
    if (String(v == null ? '' : v) === String(value == null ? '' : value)) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () {
    const v = sel.value === '' ? null : (name === 'person_id' ? Number(sel.value) : sel.value);
    const body = {};
    body[name] = v;
    ctx.patch(body);
  });
  wrap.append(l, sel);
  return wrap;
}

/** How many cadences a recurrence waits between occurrences (#229) — "Every
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

/** The fixed day a recurrence lands on (#112) — the Repeat field's second half.
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

/** Status: the shared options (a recurring task also gets `complete`,
 *  the roll-forward action — issue #54) through `opts.onStatus`, same
 *  handler every other view uses, instead of a plain field PATCH. */
export function statusField(ctx, t) {
  const wrap = document.createElement('label');
  wrap.className = 'field';
  const l = document.createElement('span');
  l.className = 'field-label';
  l.textContent = 'Status';
  const sel = document.createElement('select');
  sel.className = 'select-native field-control';
  sel.dataset.field = 'status';
  statusOptions(t).forEach(function (v) {
    const o = document.createElement('option');
    o.value = v[0]; o.textContent = v[1]; o.selected = v[0] === t.status;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () {
    sel.disabled = true;
    Promise.resolve(ctx.opts.onStatus(t.id, sel.value))
      .catch(function () { sel.value = t.status; })
      .finally(function () { sel.disabled = false; });
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
 *  one), typing still works — `tomorrow`, `fri`, `in 2 weeks`, ISO
 *  (issue #46). Both dates the drawer edits go through this one builder —
 *  **Due** and, beside it, **Starts** (#87) — so they cannot drift into
 *  behaving differently — and the calendar is `duePicker()`'s, so the
 *  coarse-pointer branch (#50) lives once for the whole app.
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
    className: 'icon-button field-due-btn',     // the one icon button (#357)
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

/** The date sheet's phrases as one-tap moves under Due (#394): push-outs
 *  first, each with the date it resolves to, sent as the phrase so
 *  `src/dates.py` stays the one date vocabulary. */
export function quickMoves(ctx) {
  const row = document.createElement('div');
  row.className = 'quick-moves';
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', 'Move the due date');
  phraseButtons(DUE_OPTIONS, function (phrase) { ctx.patch({ due: phrase }); }).forEach(function (b) {
    b.classList.add('quick-move');
    row.appendChild(b);
  });
  return row;
}
