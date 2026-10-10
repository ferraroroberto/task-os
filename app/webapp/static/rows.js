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
 *   main      the title (one line, ellipsized) over ONE quiet meta line on a
 *             budget (#392, `metaLine`): due · exception chips · one context
 *             name · at most two counts. Passive text: nothing on it is its
 *             own tap target, so the whole line opens the task
 *   verb      Move — the one visible action, on a fine pointer (#392): the
 *             date sheet, because re-dating is most of the owner's edits
 *   trailing  one 44px ⋯ kebab: every other action (rowmenu.js — status,
 *             move, snooze, priority, folder, AI, issue). Right-
 *             click and the keyboard's menu key open the same menu
 *
 * Select mode swaps the circle for the checkbox and drops the verb and the
 * kebab: there the row's one job is to tick and the bulk bar owns the actions.
 * A view may pass an `extra` line (a Search snippet, an AI suggestion) that
 * wraps under the row — the row itself never changes shape. Flat hairlines
 * between rows, no per-row box.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import {
  STATUSES, blockedLabel, breadcrumbText, fmtDay, isBlocked, isDeferred, relDue, startsLabel, toneChip,
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

/** An exception chip on the meta line (#392): the one tone chip (#391), its
 *  text in a label that ellipsizes before the chip leaves the line. */
function flagChip(cls, iconName, text, tone, title) {
  const chip = toneChip('', tone);
  chip.classList.add('trow-flag', 'trow-' + cls);
  if (iconName) chip.innerHTML = icon(iconName);
  const label = document.createElement('span');
  label.className = 'chip-label';
  label.textContent = text;
  chip.appendChild(label);
  if (title) chip.title = title;
  return chip;
}

/** The statuses that are an exception on a row, and their chip's tone: the
 *  status chip's own map (format.js). Todo is the default and done is the
 *  circle; cancelled stays a quiet word (a closed row is already muted). */
const STATUS_FLAGS = { inbox: 'accent', standby: 'neutral' };
const QUIET_STATUSES = { todo: 1, done: 1 };

function sentence(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

/**
 * Build the meta line (#392's budget): one quiet line that never loses a part
 * to the ellipsis on a 390px phone —
 *
 *   due        relative, the repeat glyph beside it when the task recurs
 *   flags      exception chips only, in the status chip's tone map: Blocked or
 *              the day a snooze ends (blocked wins, #100), an Inbox / Standby
 *              status where the view does not already say it, and High. No
 *              mark for medium or low, and no danger tone: priority is a mode,
 *              not an alarm
 *   context    ONE name, the only part that ellipsizes: the project when the
 *              view does not group by it, else the issue code
 *   counts     at most two — child tasks and comments — kept outside the
 *              ellipsis
 *
 * The link glyphs (folder, AI conversation, issue) and the person are not on
 * the row: the row menu opens each link, the drawer shows all of them.
 * @param {object} t
 * @param {{hideProject?: boolean, hideStatus?: boolean}} [opts]
 *        hideProject: the view's sub-header names the project (Today's groups);
 *        hideStatus: the view already says the status (the Board's columns)
 */
export function metaLine(t, opts) {
  const o = opts || {};
  const meta = document.createElement('span');
  meta.className = 'trow-meta action-row-meta';
  const recur = t.recurrence ? recurrenceLabel(t.recurrence, t.recurrence_anchor, t.recurrence_interval) : '';
  if (t.due) {
    const rel = relDue(t.due);
    const due = metaPart('due' + (rel.tone ? ' due-' + rel.tone : ''), null, rel.text, t.due);
    // The ISO date as a value — Today reads it for the row's overdue tint.
    due.dataset.due = t.due;
    if (recur) due.prepend(metaPart('recur', 'repeat', '', recur));
    meta.appendChild(due);
  } else if (recur) {
    meta.appendChild(metaPart('recur', 'repeat', '', recur));
  }
  // the clock says "snoozed until"; the words are on the tooltip, to keep the
  // budget at 390px
  if (isBlocked(t)) meta.appendChild(flagChip('blocked', null, 'Blocked', 'neutral', blockedLabel(t)));
  else if (isDeferred(t)) {
    meta.appendChild(flagChip('starts', 'clock', startsLabel(t.starts).replace(/^starts /, ''), 'neutral',
      'Snoozed until ' + fmtDay(t.starts)));
  }
  if (!o.hideStatus && STATUS_FLAGS[t.status]) {
    meta.appendChild(flagChip('state', null, sentence(t.status), STATUS_FLAGS[t.status], 'Status ' + t.status));
  } else if (!o.hideStatus && !QUIET_STATUSES[t.status]) {
    meta.appendChild(metaPart('state trow-ctx', null, t.status, 'Status ' + t.status));
  }
  if (t.priority === 'high') meta.appendChild(flagChip('prio', null, 'High', 'neutral', 'Priority high'));
  const project = t.root && !o.hideProject ? t.root.title : '';
  // the part names the root; its tooltip is the whole path (a journal row
  // three levels down reads "Home renovation › Kitchen" on hover, #102)
  if (project) meta.appendChild(metaPart('project trow-ctx', null, project, breadcrumbText(t.breadcrumb) || project));
  else if (t.code) meta.appendChild(metaPart('code trow-ctx', null, t.code, 'Code ' + t.code));
  if (t.child_count) meta.appendChild(metaPart('kids trow-count', 'list-tree', String(t.child_count), t.child_count + (t.child_count === 1 ? ' child task' : ' child tasks')));
  if (t.comment_count) {
    meta.appendChild(metaPart('comments trow-count', 'message-square', String(t.comment_count),
      t.last_comment ? t.last_comment.author + ': ' + (t.last_comment.body || '') : t.comment_count + (t.comment_count === 1 ? ' comment' : ' comments')));
  }
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
  btn.className = 'icon-button trow-done action-row-fav';
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
 * Move (#392): the row's one visible verb, because re-dating is most of what
 * the owner does to a task — opening the date sheet beside the row. A plain
 * 44px icon button like the kebab beside it, not the vendored
 * `.action-row-verb`: that recipe paints a tint at rest, which the design
 * rubric's COMP-05 fails on every row (the conflict is the scaffold's to
 * settle: project-scaffolding#347). A fine pointer only (styles.css): a touch screen swipes the row
 * left for the same sheet.
 */
function moveVerb(t, menu) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'icon-button trow-move';
  btn.setAttribute('aria-label', 'Move ' + t.title + ' to another date');
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.title = 'Move… (D)';
  btn.innerHTML = icon('calendar-days');
  btn.addEventListener('click', function () { menu.move(t, btn); });
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
  kebab.className = 'icon-button trow-kebab action-row-kebab';
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
 *                  toggleDone: (t:object, el:HTMLElement)=>void,
 *                  move: (t:object, el:HTMLElement)=>void}}} handlers
 *          menu (optional) is the view's row menu (rowmenu.js, #311) — the kebab,
 *          the circle and the Move verb all commit through it
 * @param {{depth?: number, extra?: HTMLElement, hideProject?: boolean,
 *          hideStatus?: boolean, draggable?: boolean, tag?: string, selectable?: boolean,
 *          selected?: boolean, swipe?: boolean, verb?: boolean}} [opts]
 *          extra      = a line that wraps under the row (a Search snippet);
 *          tag        = the element name ('li' default, 'div' for a non-list host);
 *          selectable = Select mode is on (#81): the checkbox replaces the
 *                       circle, the kebab goes, and the row gesture ticks;
 *          swipe      = false where the view owns the sideways swipe (the Board);
 *          verb       = false where a column is too narrow for a third square
 *                       (the Board's columns; the ⋯ menu and `d` still move)
 */
export function taskRow(t, handlers, opts) {
  const o = opts || {};
  const li = document.createElement(o.tag || 'li');
  li.className = 'trow action-row' + (CLOSED[t.status] ? ' is-closed' : '')
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

  if (handlers.menu && !o.selectable && !CLOSED[t.status] && o.verb !== false) li.appendChild(moveVerb(t, handlers.menu));
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
