/* task-os — Search: the results, or the idle view before a query.
 *
 *   before a query   one hint line naming what the box searches, and the kinds
 *                    this install has not set up folded into one line with a
 *                    link to Settings — no group shells waiting empty
 *   with a query     one group per kind that has hits, Tasks · Folders · Emails
 *                    · Issues in that order, each a flat section headed by an
 *                    `overline` with its count, open; every kind without hits
 *                    folds into ONE line under them. A kind that failed says so
 *                    on its own line, in the danger tone: a fault, not an empty
 *                    result.
 *
 * Takes the composer's `ctx` first (`host`, `meta`, `opts`, `status`,
 * `hitByIdx`). */

'use strict';

import { collapsibleCard } from '../../collapsible.js';
import { matchesFilters, matchesScope } from '../../filters.js';
import { sortItems } from '../../rows.js';
import { hitRow, taskHitRow } from './hits.js';
import { HINT, KINDS, foldParts, hitWord } from './text.js';

export function note(cls, text) {
  const p = document.createElement('p');
  p.className = cls;
  p.textContent = text;
  return p;
}

/** The one folded line, with the Settings link after "Not set up: …". */
function foldLine(fold) {
  const parts = foldParts(fold);
  if (!parts.length) return null;
  const p = note('search-fold muted', parts.join(' · '));
  if (fold.off && fold.off.length) {
    p.appendChild(document.createTextNode(' · '));
    const a = document.createElement('a');
    a.href = '#settings/search';
    a.textContent = 'Settings';
    p.appendChild(a);
  }
  return p;
}

/** One kind's hits: a flat section under an overline header with its count. */
function group(k, countText, countLabel) {
  const parts = collapsibleCard({
    className: 'disclosure-flat search-group', title: k.label, titleClass: 'overline',
    count: countText, countClass: 'section-count search-group-count', bodyClass: 'search-body',
  });
  parts.card.dataset.kind = k.kind;
  parts.card.open = true;
  parts.count.setAttribute('aria-label', countLabel);
  return parts;
}

export function renderIdle(ctx) {
  ctx.meta.textContent = '';
  ctx.hitByIdx.clear();
  const off = (ctx.status || []).filter(function (a) { return !a.configured; }).map(function (a) {
    const k = KINDS.find(function (x) { return x.kind === a.kind; });
    return k ? k.label : a.kind;
  });
  const nodes = [note('search-hint muted', HINT)];
  const fold = foldLine({ off: off });
  if (fold) nodes.push(fold);
  ctx.host.replaceChildren.apply(ctx.host, nodes);
}

/** The task hits as rows' data, narrowed by the shared filter state and the scope, and sorted by it. */
function taskHits(ctx, g) {
  const f = ctx.opts.filters ? ctx.opts.filters() : null;
  const tasks = (g.hits || []).map(function (h) {
    const t = Object.assign({}, h.task || {}, { id: h.task_id, _hit: h });
    if (!t.title) t.title = h.title;
    return t;
  });
  if (!f) return tasks;
  const kept = tasks.filter(function (t) { return matchesScope(t, f.scope) && matchesFilters(t, f); });
  return sortItems(kept, f.sort);
}

export function render(ctx, res) {
  ctx.hitByIdx.clear();
  let total = 0;
  let idx = 0;
  const groups = [];
  const errors = [];
  const fold = { none: [], hidden: 0, off: [] };
  KINDS.forEach(function (k) {
    const g = res.groups.find(function (x) { return x.kind === k.kind; }) || { kind: k.kind, configured: false, reason: 'no answer', hits: [] };
    if (!g.configured) { fold.off.push(k.label); return; }
    if (g.error) { errors.push(note('search-err', k.label + ' failed — ' + g.error)); return; }
    const all = g.hits || [];
    const rows = k.kind === 'tasks' ? taskHits(ctx, g) : all;
    if (k.kind === 'tasks' && !rows.length) fold.hidden = all.length;   // a partial cut shows as "3 of 5" on the group
    if (!rows.length) {
      if (k.kind !== 'tasks' || !all.length) fold.none.push(g.note ? k.label + ' (' + g.note + ')' : k.label);
      return;
    }
    const n = k.kind === 'tasks' ? rows.length : (g.count || rows.length);
    total += n;
    let countText = k.kind === 'tasks' && rows.length !== all.length ? rows.length + ' of ' + all.length : String(n);
    if (g.note) countText += ' · ' + g.note;
    const parts = group(k, countText, hitWord(n));
    const ul = document.createElement('ul');
    ul.className = 'trows search-hits';
    ul.setAttribute('role', 'list');
    rows.forEach(function (h) { ul.appendChild(k.kind === 'tasks' ? taskHitRow(ctx, h, idx++) : hitRow(ctx, h, idx++)); });
    parts.body.appendChild(ul);
    groups.push(parts.card);
  });
  ctx.meta.textContent = hitWord(total);
  const nodes = groups.slice();
  const line = foldLine(fold);
  if (line) nodes.push(line);
  ctx.host.replaceChildren.apply(ctx.host, nodes.concat(errors));
  if (ctx.opts.menu) ctx.opts.menu.endRender();
}
