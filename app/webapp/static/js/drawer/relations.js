/* task-os — the drawer's task relations: Blocked by and Children. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { relDue, statusMark } from '../../format.js';
import { toast } from '../../toast.js';
import { formButton, section } from './dom.js';

/** "Blocked by" (#100): the open blockers as removable rows, a select
 *  to add one — the server's cycle guard answers a bad pick, same as it
 *  answers a bad re-parent from Change parent. */
function blockerRow(ctx, t, b) {
  const row = document.createElement('div');
  row.className = 'blocker-row';
  const link = document.createElement('button');
  link.type = 'button';
  link.className = 'blocker-title';
  link.textContent = b.title;
  link.addEventListener('click', function () { ctx.opts.onOpen(b.id); });
  row.appendChild(link);
  row.appendChild(statusMark(b.status));
  const rm = document.createElement('button');
  rm.type = 'button';
  rm.className = 'icon-button danger';
  rm.setAttribute('aria-label', 'Remove blocker ' + b.title);
  rm.innerHTML = icon('trash-2');
  rm.addEventListener('click', async function () {
    try {
      await api('/api/tasks/' + t.id + '/blockers/' + b.id, { method: 'DELETE' });
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) { toast(err.message || 'Remove blocker failed', 'error'); }
  });
  row.appendChild(rm);
  return row;
}

function blockerForm(ctx, t, blockers) {
  const form = document.createElement('form');
  form.className = 'blocker-form';
  const sel = document.createElement('select');
  sel.className = 'select-native field-control';
  sel.setAttribute('aria-label', 'Add a blocker');
  const taken = new Set(blockers.map(function (b) { return b.id; }));
  const optDefault = document.createElement('option');
  optDefault.value = '';
  optDefault.textContent = 'pick a task…';
  sel.appendChild(optDefault);
  (ctx.opts.allTasks ? ctx.opts.allTasks() : []).forEach(function (p) {
    if (p.id === t.id || taken.has(p.id)) return;
    const o = document.createElement('option');
    o.value = String(p.id);
    o.textContent = (p.depth ? ' '.repeat(p.depth) : '') + p.title;
    sel.appendChild(o);
  });
  form.append(sel, formButton(form, 'button-surface', 'Add blocker'));
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const v = sel.value;
    if (!v) return;
    try {
      await api('/api/tasks/' + t.id + '/blockers', { method: 'POST', body: { blocker_id: Number(v) } });
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) { toast(err.message || 'Add blocker failed', 'error'); }
  });
  return form;
}

export function blockedBySection(ctx, t) {
  const sec = section('blocked', 'Blocked by', 'lock');
  const list = document.createElement('div');
  list.className = 'drawer-blockers';
  const blockers = t.blocked_by || [];
  blockers.forEach(function (b) { list.appendChild(blockerRow(ctx, t, b)); });
  if (!blockers.length) {
    const none = document.createElement('p');
    none.className = 'muted drawer-none';
    none.textContent = 'Not blocked by anything.';
    list.appendChild(none);
  }
  sec.appendChild(list);
  sec.appendChild(blockerForm(ctx, t, blockers));
  return sec;
}

function childRow(ctx, c) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'child-row';
  const ct = document.createElement('span');
  ct.className = 'child-title';
  ct.textContent = c.title;
  b.appendChild(ct);
  if (c.due) {
    const d = relDue(c.due);
    const cd = document.createElement('span');
    cd.className = 'child-due' + (d.tone ? ' due-' + d.tone : '');
    cd.textContent = d.text;
    cd.title = c.due;
    b.appendChild(cd);
  }
  b.appendChild(statusMark(c.status));
  b.addEventListener('click', function () { ctx.opts.onOpen(c.id); });
  return b;
}

export function childrenSection(ctx, t) {
  const children = section('children', 'Children', 'corner-down-right');
  const kids = document.createElement('div');
  kids.className = 'children-list';
  (t.children || []).forEach(function (c) { kids.appendChild(childRow(ctx, c)); });
  children.appendChild(kids);
  const addChild = document.createElement('form');
  addChild.className = 'child-add';
  const ci = document.createElement('input');
  ci.type = 'text';
  ci.className = 'input-native';
  ci.placeholder = 'Add child task…';
  ci.setAttribute('aria-label', 'Add child task');
  addChild.append(ci, formButton(addChild, 'button-surface', 'Add child'));
  addChild.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const v = ci.value.trim();
    if (!v) return;
    try {
      await api('/api/tasks', { method: 'POST', body: { title: v, parent_id: t.id } });
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) { toast(err.message, 'error'); }
  });
  children.appendChild(addChild);
  return children;
}
