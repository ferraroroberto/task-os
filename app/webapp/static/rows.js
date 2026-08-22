/* task-os — the ONE task row every view renders (issue #46).
 *
 * Board, Table (phone), Tree, Today and the Search tab's task hits are
 * different *renderings* of the same list, not different features — so they
 * share one row, one status control and one sort, built here:
 *
 *   line 1  the title (one line, ellipsized) + the status select, right-aligned
 *           on the same line (the Board control, issue #27/#32 — now everywhere,
 *           fine and coarse pointers alike; a view with drag-and-drop keeps it too)
 *   line 2  the meta line: code (coding tasks) · project (root title) · due ·
 *           priority · recurrence · folder chip · issue chip · children ·
 *           comments · person — only the parts that have content
 *
 * Flat hairline separators between rows, no per-row box, the priority accent
 * on the left edge of a high-priority row. A view passes a `prefix` element
 * (the Tree's expand toggle) and/or an `extra` line (a Search snippet) — the
 * row itself never changes shape.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES, chipFor, issueChip, relDue } from './format.js';

export const SORTS = [
  ['due', 'due date'], ['priority', 'priority'], ['updated', 'last modified'], ['created', 'created'], ['title', 'title'],
];
const PRIO_RANK = { high: 0, medium: 1, low: 2, none: 3 };
export const CLOSED = { done: 1, cancelled: 1 };

// ------------------------------------------------------------------ sort
function cmpDue(a, b) {
  if (!a.due && !b.due) return 0;
  if (!a.due) return 1;
  if (!b.due) return -1;
  return a.due.localeCompare(b.due);
}
function cmpPrio(a, b) { return (PRIO_RANK[a.priority] ?? 3) - (PRIO_RANK[b.priority] ?? 3); }

/** The comparator behind `sort` — one rule for flat lists, board columns,
 *  Today groups and every Tree level, so "sorted by due" means the same
 *  thing on every tab. */
export function compareItems(sort) {
  switch (sort) {
    case 'priority': return function (a, b) { return cmpPrio(a, b) || cmpDue(a, b) || (a.id - b.id); };
    case 'updated': return function (a, b) { return (b.updated_at || '').localeCompare(a.updated_at || '') || (b.id - a.id); };
    case 'created': return function (a, b) { return (b.created_at || '').localeCompare(a.created_at || '') || (b.id - a.id); };
    case 'title': return function (a, b) { return (a.title || '').localeCompare(b.title || '') || (a.id - b.id); };
    default: return function (a, b) { return cmpDue(a, b) || cmpPrio(a, b) || (a.id - b.id); };
  }
}

export function sortItems(items, sort) {
  return items.slice().sort(compareItems(sort));
}

export function sortLabel(sort) {
  const s = SORTS.find(function (x) { return x[0] === sort; });
  return s ? s[1] : 'due date';
}

// --------------------------------------------------------- status select
/**
 * The status control — the same compact select on every row.
 * @param {object} t
 * @param {(id:number, status:string) => Promise<any>} onStatus
 */
export function statusSelect(t, onStatus) {
  const sel = document.createElement('select');
  sel.className = 'select-native trow-status';
  sel.setAttribute('aria-label', 'Status of ' + t.title);
  STATUSES.forEach(function (s) {
    const o = document.createElement('option');
    o.value = s; o.textContent = s; o.selected = s === t.status;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () {
    sel.disabled = true;
    Promise.resolve(onStatus(t.id, sel.value))
      .catch(function () { sel.value = t.status; })
      .finally(function () { sel.disabled = false; });
  });
  return sel;
}

// ------------------------------------------------------------------- row
function metaPart(cls, iconName, text, title) {
  const el = document.createElement('span');
  el.className = 'trow-' + cls;
  if (iconName) el.innerHTML = icon(iconName);
  if (text != null && text !== '') el.appendChild(document.createTextNode(text));
  if (title) el.title = title;
  return el;
}

/**
 * Build the meta line (line 2). Exported so the Table's desktop grid can
 * reuse the same parts in its cells if it ever needs to.
 * @param {object} t
 * @param {{hideProject?: boolean}} [opts]
 */
export function metaLine(t, opts) {
  const o = opts || {};
  const meta = document.createElement('span');
  meta.className = 'trow-meta';
  if (t.code) meta.appendChild(metaPart('code', null, t.code, 'code'));
  const project = t.root ? t.root.title : '';
  if (project && !o.hideProject) meta.appendChild(metaPart('project', null, project, project));
  if (t.due) {
    const rel = relDue(t.due);
    const due = metaPart('due' + (rel.tone ? ' due-' + rel.tone : ''), 'calendar-days', rel.text, t.due);
    meta.appendChild(due);
  }
  if (t.priority && t.priority !== 'none') meta.appendChild(metaPart('prio prio-' + t.priority, null, t.priority, 'priority ' + t.priority));
  if (t.recurrence) meta.appendChild(metaPart('recur', 'repeat', '', t.recurrence));
  if (t.folder_ref) meta.appendChild(chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url }));
  // the code already names the issue — no duplicate chip
  if (t.issue_ref && !t.code) meta.appendChild(issueChip(t.issue_ref));
  if (t.child_count) meta.appendChild(metaPart('kids', 'list-tree', String(t.child_count), t.child_count + (t.child_count === 1 ? ' child task' : ' child tasks')));
  if (t.comment_count) {
    meta.appendChild(metaPart('comments', 'message-square', String(t.comment_count),
      t.last_comment ? t.last_comment.author + ': ' + (t.last_comment.body || '') : t.comment_count + (t.comment_count === 1 ? ' comment' : ' comments')));
  }
  if (t.person) meta.appendChild(metaPart('person', 'user', t.person.name, t.person.name));
  return meta;
}

/**
 * One task row.
 * @param {object} t                    a list summary (/api/tasks item, board/today item, search hit)
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>}} handlers
 * @param {{prefix?: HTMLElement, depth?: number, extra?: HTMLElement, hideProject?: boolean,
 *          draggable?: boolean, tag?: string}} [opts]
 *          prefix = an element before the title (the Tree's toggle);
 *          extra  = a third line under the meta (a Search snippet);
 *          tag    = the element name ('li' default, 'div' for a non-list host)
 */
export function taskRow(t, handlers, opts) {
  const o = opts || {};
  const li = document.createElement(o.tag || 'li');
  li.className = 'trow' + (t.priority === 'high' ? ' is-high' : '') + (CLOSED[t.status] ? ' is-closed' : '') + (o.prefix ? ' has-prefix' : '');
  li.dataset.id = String(t.id);
  li.dataset.status = t.status;
  if (o.depth != null) li.style.setProperty('--depth', String(o.depth));
  if (o.draggable) li.draggable = true;

  if (o.prefix) {
    o.prefix.classList.add('trow-prefix');
    li.appendChild(o.prefix);
  }

  const main = document.createElement('div');
  main.className = 'trow-main';
  main.setAttribute('role', 'button');
  main.tabIndex = 0;
  main.setAttribute('aria-label', t.title);
  const title = document.createElement('span');
  title.className = 'trow-title';
  title.textContent = t.title;
  title.title = t.title;
  main.appendChild(title);
  li.appendChild(main);

  li.appendChild(statusSelect(t, handlers.onStatus));

  const meta = metaLine(t, o);
  if (meta.childNodes.length) li.appendChild(meta);
  if (o.extra) {
    o.extra.classList.add('trow-extra');
    li.appendChild(o.extra);
  }

  main.addEventListener('click', function (ev) {
    if (ev.target.closest('a, select, button')) return;
    handlers.onOpen(t.id);
  });
  main.addEventListener('keydown', function (ev) {
    if (ev.target !== main) return;
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); handlers.onOpen(t.id); }
  });
  // a click on the meta line (not on a chip) opens too — the whole row is the target
  meta.addEventListener('click', function (ev) {
    if (ev.target.closest('a, select, button')) return;
    handlers.onOpen(t.id);
  });
  return li;
}

/**
 * A flat list of rows.
 * @param {Array<object>} items
 * @param {{onOpen: Function, onStatus: Function}} handlers
 * @param {object} [opts]  forwarded to every row
 */
export function rowList(items, handlers, opts) {
  const ul = document.createElement('ul');
  ul.className = 'trows';
  ul.setAttribute('role', 'list');
  items.forEach(function (t) { ul.appendChild(taskRow(t, handlers, opts)); });
  return ul;
}
