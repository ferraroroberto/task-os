/* task-os — the ONE task row every view renders (issue #46, #311).
 *
 * Board, Today, the done journal and the Search tab's
 * task hits are different *renderings* of the same list, not different
 * features — so they share one row and one sort, built here. The row is the
 * fleet's vendored action-row (#311): tapping it opens the task, and
 *
 *   leading   the completion circle — the one toggle a row shows: an open
 *             task completes (a recurring one rolls to its next date), a
 *             closed one reopens; both through the shared action runner, so
 *             both come with Undo
 *   main      the title (one line, ellipsized) over ONE quiet meta line: due ·
 *             blocked or asleep · project · code · status (where the view does
 *             not imply it) · priority · then glyphs — recurrence,
 *             children, comments, folder, AI conversation, issue — and the
 *             person. Passive text: nothing on it is its own tap target, so
 *             the whole line opens the task
 *   trailing  one 44px ⋯ kebab: every other action (rowmenu.js — status,
 *             change date, snooze, priority, folder, AI, issue). Right-
 *             click and the keyboard's menu key open the same menu
 *
 * Select mode swaps the circle for the checkbox and drops the kebab: there the
 * row's one job is to tick and the bulk bar owns the actions. A view may pass an
 * `extra` line (a Search snippet, an AI suggestion) that
 * wraps under the row — the row itself never changes shape. Flat hairlines
 * between rows, no per-row box, the priority accent on the left edge of a
 * high-priority row.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import {
  STATUSES, blockedLabel, breadcrumbText, isBlocked, isDeferred, providerIcon, relDue, startsLabel,
} from './format.js';
import { recurrenceLabel } from './recurrence.js';

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
 *  and Today groups, so "sorted by due" means the same
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
 * The status options for a task: the plain statuses, plus a `complete`
 * pseudo-action spliced in right before `done` when the task recurs — never
 * a persisted status (issue #54), just a trigger for the roll-forward
 * `POST /tasks/{id}/done`. `done` itself always means closed for good, for
 * a recurring task too.
 * @param {object} t
 * @returns {Array<[string,string]>} [value, label]
 */
export function statusOptions(t) {
  const opts = [];
  STATUSES.forEach(function (s) {
    if (s === 'done' && t.recurrence) opts.push(['complete', 'complete']);
    opts.push([s, s]);
  });
  return opts;
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

/** Statuses the row never spells out: todo is the default, done is the circle. */
const QUIET_STATUSES = { todo: 1, done: 1 };

/**
 * Build the meta line: one line of quiet text, only the parts with content.
 * A glyph stands for each link the task carries (folder, AI conversation,
 * issue) — what to *do* with it lives in the row menu (#311).
 * @param {object} t
 * @param {{hideProject?: boolean, hideStatus?: boolean}} [opts]
 *        hideStatus: the view already says the status (the Board's columns)
 */
export function metaLine(t, opts) {
  const o = opts || {};
  const meta = document.createElement('span');
  meta.className = 'trow-meta action-row-meta';
  if (t.due) {
    const rel = relDue(t.due);
    const due = metaPart('due' + (rel.tone ? ' due-' + rel.tone : ''), null, rel.text, t.due);
    // The ISO date as a value — Today reads it for the row's overdue tint.
    due.dataset.due = t.due;
    meta.appendChild(due);
  }
  // Blocked wins over deferred (#100) — it's the harder gate: a task both
  // asleep and blocked shows the lock, not the clock, wherever either still
  // shows (a search hit, the Deferred/blocked filters). Right after
  // the date, because it says when the task can be worked at all, and a
  // narrow Board column must not ellipsize it away.
  if (isBlocked(t)) meta.appendChild(metaPart('blocked', 'lock', blockedLabel(t), blockedLabel(t)));
  else if (isDeferred(t)) meta.appendChild(metaPart('starts', 'clock', startsLabel(t.starts), 'starts ' + t.starts));
  const project = t.root ? t.root.title : '';
  // the part names the root; its tooltip is the whole path (a journal row
  // three levels down reads "Home renovation › Kitchen" on hover, #102)
  if (project && !o.hideProject) meta.appendChild(metaPart('project', null, project, breadcrumbText(t.breadcrumb) || project));
  if (t.code) meta.appendChild(metaPart('code', null, t.code, 'code'));
  if (!o.hideStatus && !QUIET_STATUSES[t.status]) meta.appendChild(metaPart('state', null, t.status, 'status ' + t.status));
  if (t.priority && t.priority !== 'none') meta.appendChild(metaPart('prio prio-' + t.priority, null, t.priority, 'priority ' + t.priority));
  if (t.recurrence) meta.appendChild(metaPart('recur', 'repeat', '', recurrenceLabel(t.recurrence, t.recurrence_anchor, t.recurrence_interval)));
  if (t.child_count) meta.appendChild(metaPart('kids', 'list-tree', String(t.child_count), t.child_count + (t.child_count === 1 ? ' child task' : ' child tasks')));
  if (t.comment_count) {
    meta.appendChild(metaPart('comments', 'message-square', String(t.comment_count),
      t.last_comment ? t.last_comment.author + ': ' + (t.last_comment.body || '') : t.comment_count + (t.comment_count === 1 ? ' comment' : ' comments')));
  }
  if (t.folder_ref) meta.appendChild(metaPart('folder', 'folder', '', 'Folder ' + t.folder_ref));
  if (t.ai_url) meta.appendChild(metaPart('ai', 'bot', '', 'AI conversation' + (t.ai_label ? ' — ' + t.ai_label : '')));
  // the code already names the issue — no second mark for it
  if (t.issue_ref && !t.code) {
    const ref = t.issue_ref;
    meta.appendChild(metaPart('issue', providerIcon(ref.provider), '', ref.repo + '#' + ref.number + ' · ' + (ref.state || 'state unknown')));
  }
  if (t.person) meta.appendChild(metaPart('person', 'user', t.person.name, t.person.name));
  return meta;
}

/**
 * The completion circle: the row's one leading toggle. Pressed = closed. A
 * tap completes an open task (a recurring one rolls instead) and reopens a
 * closed one — through the view's row menu, which commits through the shared
 * runner (toast + Undo); a view without one falls back to the status call.
 */
function doneToggle(t, handlers) {
  const closed = !!CLOSED[t.status];
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'trow-done action-row-fav';
  btn.setAttribute('aria-pressed', closed ? 'true' : 'false');
  btn.setAttribute('aria-label', 'Complete ' + t.title);
  btn.title = closed ? 'Reopen' : (t.recurrence ? 'Complete — rolls to the next date' : 'Complete');
  btn.innerHTML = icon('circle', 'action-row-fav-off') + icon('circle-check', 'action-row-fav-on');
  btn.addEventListener('click', function () {
    if (handlers.menu) { handlers.menu.toggleDone(t, btn); return; }
    Promise.resolve(handlers.onStatus(t.id, closed ? 'todo' : (t.recurrence ? 'complete' : 'done')))
      .catch(function () { /* the caller toasts the failure */ });
  });
  return btn;
}

/**
 * The row's ⋯ kebab, wired to the view's menu. A right-click on the row (and
 * the menu key, which the browser sends as the same event) opens that menu
 * too — on a fine pointer only: a touch long-press is kept free.
 */
function rowKebab(t, menu, li) {
  const kebab = document.createElement('button');
  kebab.type = 'button';
  kebab.className = 'trow-kebab action-row-kebab';
  kebab.setAttribute('aria-label', 'More actions for ' + t.title);
  kebab.innerHTML = icon('ellipsis-vertical');
  menu.attach(t, kebab);
  li.addEventListener('contextmenu', function (ev) {
    if (!window.matchMedia('(pointer: fine)').matches) return;
    if (ev.target.closest('a, input, select, textarea')) return;   // the browser's own menu there
    ev.preventDefault();
    if (kebab.getAttribute('aria-expanded') !== 'true') kebab.click();
  });
  return kebab;
}

/**
 * One task row.
 * @param {object} t                    a list summary (/api/tasks item, board/today item, search hit)
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onToggleSelect?: (id:number)=>void,
 *          menu?: {attach: (t:object, kebab:HTMLElement)=>void,
 *                  toggleDone: (t:object, el:HTMLElement)=>void}}} handlers
 *          menu (optional) is the view's row menu (rowmenu.js, #311) — the kebab
 *          and the circle both commit through it
 * @param {{depth?: number, extra?: HTMLElement, hideProject?: boolean,
 *          hideStatus?: boolean, draggable?: boolean, tag?: string, selectable?: boolean,
 *          selected?: boolean, swipe?: boolean}} [opts]
 *          extra      = a line that wraps under the row (a Search snippet);
 *          tag        = the element name ('li' default, 'div' for a non-list host);
 *          selectable = Select mode is on (#81): the checkbox replaces the
 *                       circle, the kebab goes, and the row gesture ticks;
 *          swipe      = false where the view owns the sideways swipe (the Board)
 */
export function taskRow(t, handlers, opts) {
  const o = opts || {};
  const li = document.createElement(o.tag || 'li');
  li.className = 'trow action-row' + (t.priority === 'high' ? ' is-high' : '') + (CLOSED[t.status] ? ' is-closed' : '')
    + (o.selectable ? ' has-select' : '') + (o.selected ? ' is-selected' : '');
  li.dataset.id = String(t.id);
  li.dataset.status = t.status;
  if (o.depth != null) li.style.setProperty('--depth', String(o.depth));
  if (o.draggable) li.draggable = true;

  // In Select mode the whole row is a tick target — the same gesture that
  // opens the task otherwise. One affordance for the Board's cards AND
  // Today's rows, because both render this row.
  const activate = function () {
    if (o.selectable) handlers.onToggleSelect(t.id); else handlers.onOpen(t.id);
  };

  if (o.selectable) {
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'check trow-check';
    box.checked = !!o.selected;
    box.setAttribute('aria-label', 'Select ' + t.title);
    box.addEventListener('change', function () { handlers.onToggleSelect(t.id); });
    li.appendChild(box);
  }

  if (!o.selectable) li.appendChild(doneToggle(t, handlers));

  const main = document.createElement('button');
  main.type = 'button';
  main.className = 'trow-main action-row-main';
  main.setAttribute('aria-label', (o.selectable ? 'Select ' : '') + t.title);
  const title = document.createElement('span');
  title.className = 'trow-title action-row-title';
  title.textContent = t.title;
  title.title = t.title;
  main.appendChild(title);
  const meta = metaLine(t, o);
  if (meta.childNodes.length) main.appendChild(meta);
  main.addEventListener('click', activate);
  li.appendChild(main);

  if (handlers.menu && !o.selectable) li.appendChild(rowKebab(t, handlers.menu, li));
  // A touch swipe runs a row action (swipe.js, #311) — an open task's row
  // only (a closed one's circle reopens it), never in Select mode, and not
  // where the view swipes sideways itself (the phone Board's carousel).
  if (handlers.menu && !o.selectable && !CLOSED[t.status] && o.swipe !== false) handlers.menu.swipe(t, li);
  if (o.extra) {
    o.extra.classList.add('trow-extra');
    li.appendChild(o.extra);
  }
  return li;
}

/**
 * A flat list of rows.
 * @param {Array<object>} items
 * @param {{onOpen: Function, onStatus: Function, onToggleSelect?: Function, menu?: object}} handlers
 * @param {object} [opts]  forwarded to every row; `isSelected(id)` resolves
 *                         each row's `selected` flag (#81)
 */
export function rowList(items, handlers, opts) {
  const o = opts || {};
  const ul = document.createElement('ul');
  ul.className = 'trows';
  ul.setAttribute('role', 'list');
  items.forEach(function (t) {
    const rowOpts = o.isSelected ? Object.assign({}, o, { selected: o.isSelected(t.id) }) : o;
    ul.appendChild(taskRow(t, handlers, rowOpts));
  });
  return ul;
}
