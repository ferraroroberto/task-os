/* task-os — the drawer's property list: one inset group of rows, in the order
 * the owner reaches for them (Links, Due, Owner, Person, Parent, Repeat, then
 * Priority, last and smaller because it is rarely changed).
 *
 * A row that picks one value from a short list (Owner, Person, Repeat,
 * Priority) is one button opening the vendored row menu: two taps, where a
 * native select takes three on the phone. Parent opens the parent picker. Due
 * takes a typed date in place (`src/dates.py` reads it). The Links row shows
 * the folder and every link as pills that open on one click; its + unfolds the
 * folder and link editors under the group.
 */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { createRowMenu } from '../../_vendored/row-menu/row-menu.js';
import { PRIORITIES, fmtDay, issueChip, relDue } from '../../format.js';
import { openParentPicker } from '../../parentpick.js';
import { RECURRENCES, anchorOptions } from '../../recurrence.js';
import { keyHint } from '../../snooze.js';
import { anchorField, intervalField, memberName } from './fields.js';
import { folderSection } from './folder.js';
import { folderChip, linkChip, linksSection } from './links.js';

// One menu for every row: at most one is open, and only one drawer exists.
const propMenu = createRowMenu({ className: 'prop-menu' });

/** Ask for the task's parent and move it there (null is the top level). */
export function pickParent(ctx, t) {
  const opts = ctx.opts;
  openParentPicker(t, opts.parentTargets ? opts.parentTargets(t.id) : [], function (parentId) {
    opts.onMove(t.id, parentId);   // toasts + refreshes; a cycle comes back as a toast
  });
}

/** A row's leading glyph and name. */
function rowKey(row, glyph, label, key) {
  row.insertAdjacentHTML('beforeend', icon(glyph));
  const k = document.createElement('span');
  k.className = 'prop-key';
  k.textContent = label;
  if (key) k.appendChild(keyHint(key));
  row.appendChild(k);
}

/**
 * A row that opens a menu of values; the one in force carries the check.
 * @param {object} ctx
 * @param {string} field     the task field (also the row's `data-field`)
 * @param {string} glyph
 * @param {string} label
 * @param {Array<*>} values
 * @param {*} value          the current value
 * @param {(v:*) => string} name
 * @param {(v:*) => void} onPick
 * @param {{track: string, key?: string, low?: boolean}} o  `track` the row's usage id
 */
function menuRow(ctx, field, glyph, label, values, value, name, onPick, o) {
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'prop-row prop-pick' + (o.low ? ' prop-low' : '');
  row.dataset.field = field;
  row.dataset.value = value == null ? '' : String(value);
  row.dataset.track = o.track;
  rowKey(row, glyph, label, o.key);
  const v = document.createElement('span');
  v.className = 'prop-val';
  v.textContent = name(value);
  row.appendChild(v);
  row.insertAdjacentHTML('beforeend', icon('chevron-down'));
  row.setAttribute('aria-label', label + ': ' + name(value));
  if (o.key) row.setAttribute('aria-keyshortcuts', o.key);
  const same = function (a) { return String(a == null ? '' : a) === String(value == null ? '' : value); };
  propMenu.attach('prop-' + field, row, values.map(function (x) {
    return {
      label: name(x),
      glyph: same(x) ? 'circle-check' : 'circle',
      dataset: { value: x == null ? '' : String(x), track: 'drawer.prop-option' },
      onTap: function () { if (!same(x)) onPick(x); },
    };
  }), { header: label });
  return row;
}

/** Due, typed in place: the row shows the day and how far off it is; a
 *  focus selects it so a typed phrase ("fri", "in 2 weeks") replaces it. The
 *  chips above are the one-tap moves; this row is for any other day, and for
 *  clearing it. */
function dueRow(ctx, t) {
  const row = document.createElement('div');
  row.className = 'prop-row field-due';
  rowKey(row, 'calendar-days', 'Due');
  const shown = t.due ? fmtDay(t.due) + ' · ' + relDue(t.due).text : '';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'input-native prop-input';
  input.dataset.field = 'due';
  input.dataset.date = t.due || '';
  input.value = shown;
  input.placeholder = 'No date · type tomorrow, fri, 2026-09-01';
  input.setAttribute('aria-label', 'Due date');
  input.addEventListener('focus', function () { input.select(); });
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { input.value = shown; input.blur(); }
  });
  input.addEventListener('blur', function () {
    const v = input.value.trim();
    if (v === shown) return;
    if (v === '' && !t.due) return;
    ctx.patch({ due: v === '' ? null : v });
  });
  row.appendChild(input);
  if (t.due) {
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.dataset.track = 'drawer.due-clear';
    clear.className = 'icon-button prop-clear';
    clear.setAttribute('aria-label', 'No date');
    clear.title = 'No date';
    clear.innerHTML = icon('x');
    clear.addEventListener('click', function () { ctx.patch({ due: null }); });
    row.appendChild(clear);
  }
  return row;
}

/** Links: the folder, the linked issue and every link as pills that open
 *  on one click (one home per fact), then + for the editors. */
function linksRow(ctx, t) {
  const row = document.createElement('div');
  row.className = 'prop-row prop-links';
  rowKey(row, 'link', 'Links', 'L');
  const pills = document.createElement('div');
  pills.className = 'prop-val drawer-pill-row folder-chips';
  if (t.folder_ref) {
    const chip = folderChip(t);
    chip.classList.add('drawer-folder-chip');   // the one the `e` key follows
    chip.setAttribute('aria-keyshortcuts', 'E');
    pills.append(chip, keyHint('E'));
  }
  let issueHref = null;
  if (t.issue_ref) {
    const ic = issueChip(t.issue_ref);
    issueHref = ic.href;
    pills.appendChild(ic);
  }
  (t.links || []).forEach(function (l) {
    // linking an issue also stores it as an `issue` link; the issue chip
    // above already is that link, with its state
    if (l.kind === 'issue' && issueHref && new URL(l.url, location.href).href === issueHref) return;
    pills.appendChild(linkChip(l));
  });
  if (!pills.childElementCount) {
    const none = document.createElement('span');
    none.className = 'prop-none';
    none.textContent = 'None';
    pills.appendChild(none);
  }
  row.appendChild(pills);
  const add = document.createElement('button');
  add.type = 'button';
  add.dataset.track = 'drawer.links-edit';
  add.className = 'icon-button prop-links-edit';
  add.setAttribute('aria-label', 'Edit the folder and links');
  add.setAttribute('aria-expanded', String(!!ctx.linksEditing));
  add.setAttribute('aria-keyshortcuts', 'L');
  add.title = 'Edit the folder and links (L)';
  add.innerHTML = icon(ctx.linksEditing ? 'chevron-up' : 'plus');
  add.addEventListener('click', function () { ctx.toggleLinks(); });
  row.appendChild(add);
  return row;
}

/** Repeat's every-N and fixed day, as two more rows once there is a cadence. */
function repeatDetail(ctx, t) {
  const rows = [];
  if (t.recurrence) rows.push(intervalField(ctx, t));
  const anchorGroups = anchorOptions(t.recurrence);
  if (anchorGroups.length) rows.push(anchorField(ctx, t, anchorGroups));
  return rows.map(function (field) {
    const row = document.createElement('div');
    row.className = 'prop-row prop-sub';
    row.appendChild(field);
    return row;
  });
}

/** The keys that act on the open task, under the list on a fine pointer. */
function keyLegend() {
  const p = document.createElement('p');
  p.className = 'drawer-key-legend';
  const parts = [[['2', '3', 'X'], 'status'], [['T', 'W', 'D'], 'due'], [['C'], 'comment'],
    [['E'], 'folder'], [['L'], 'links'], [['Esc'], 'close']];
  p.appendChild(document.createTextNode('Keys act on this task: '));
  parts.forEach(function (part, i) {
    if (i) p.appendChild(document.createTextNode(' · '));
    part[0].forEach(function (k) {
      const kbd = document.createElement('kbd');
      kbd.className = 'key-hint';
      kbd.textContent = k;
      p.append(kbd, ' ');
    });
    p.appendChild(document.createTextNode(part[1]));
  });
  return p;
}

export function propsSection(ctx, t) {
  const wrap = document.createElement('div');
  wrap.className = 'drawer-props';
  const list = document.createElement('div');
  list.className = 'prop-list';
  list.appendChild(linksRow(ctx, t));
  list.appendChild(dueRow(ctx, t));
  // Whose task it is. One member has nobody to hand it to, so no row.
  const members = ctx.opts.members() || [];
  if (members.length > 1) {
    list.appendChild(menuRow(ctx, 'owner', 'user', 'Owner', members.map(function (m) { return m.id; }), t.owner,
      function (id) { return memberName(ctx, id); },
      function (id) { ctx.patch({ owner: id }); },
      { track: 'drawer.prop-owner' }));
  }
  const people = ctx.opts.people() || [];
  list.appendChild(menuRow(ctx, 'person_id', 'user', 'Person', [null].concat(people.map(function (p) { return p.id; })), t.person_id,
    function (id) {
      const p = people.find(function (x) { return x.id === id; });
      return p ? p.name : '—';
    },
    function (id) { ctx.patch({ person_id: id }); },
    { track: 'drawer.prop-person' }));
  const parent = document.createElement('button');
  parent.type = 'button';
  parent.className = 'prop-row prop-pick';
  parent.dataset.field = 'parent';
  parent.dataset.track = 'drawer.prop-parent';
  rowKey(parent, 'corner-down-right', 'Parent');
  const pv = document.createElement('span');
  pv.className = 'prop-val';
  pv.textContent = (t.breadcrumb || []).length
    ? t.breadcrumb.map(function (c) { return c.title; }).join(' › ')
    : 'None (top level)';
  parent.appendChild(pv);
  parent.insertAdjacentHTML('beforeend', icon('chevron-down'));
  parent.setAttribute('aria-label', 'Parent: ' + pv.textContent);
  parent.addEventListener('click', function () { pickParent(ctx, t); });
  list.appendChild(parent);
  list.appendChild(menuRow(ctx, 'recurrence', 'repeat', 'Repeat', RECURRENCES, t.recurrence || '',
    function (v) { return v || 'never'; },
    function (v) { ctx.patch({ recurrence: v || null }); },
    { track: 'drawer.prop-repeat' }));
  repeatDetail(ctx, t).forEach(function (row) { list.appendChild(row); });
  list.appendChild(menuRow(ctx, 'priority', 'activity', 'Priority', PRIORITIES.slice().reverse(), t.priority || 'none',
    function (v) { return v.charAt(0).toUpperCase() + v.slice(1); },
    function (v) { ctx.patch({ priority: v }); },
    { track: 'drawer.prop-priority', key: 'P', low: true }));
  propMenu.endRender();
  wrap.appendChild(list);
  if (ctx.linksEditing) {
    const editor = document.createElement('div');
    editor.className = 'drawer-links-editor';
    editor.append(folderSection(ctx, t), linksSection(ctx, t));
    wrap.appendChild(editor);
  }
  wrap.appendChild(keyLegend());
  return wrap;
}
