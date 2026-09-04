/* task-os — the ONE task row every view renders (issue #46).
 *
 * Board, Table (phone), Tree, Today and the Search tab's task hits are
 * different *renderings* of the same list, not different features — so they
 * share one row, one status control and one sort, built here:
 *
 *   line 1  the title (one line, ellipsized) + the status select, right-aligned
 *           on the same line (the Board control, issue #27/#32 — now everywhere,
 *           fine and coarse pointers alike; a view with drag-and-drop keeps it too),
 *           preceded on Today by the snooze control (#87)
 *   line 2  the meta line: code (coding tasks) · project (root title) · due ·
 *           blocked (lock, only while an open blocker gates it — wins over
 *           starts, #100) · starts (only while the task is still asleep) ·
 *           priority · recurrence · folder chip · issue chip · children ·
 *           comments · person — only the parts that have content
 *
 * Three of the meta line's parts are their own tap targets, not just text: the
 * due date opens the date picker (#107), the folder chip its twin/popover and
 * the AI chip its conversation. They are laid out so no two of their expanded
 * surfaces share a pixel — see `.trow-due-box` / `.trow-folder` / `.trow-ai`
 * in styles.css.
 *
 * Flat hairline separators between rows, no per-row box, the priority accent
 * on the left edge of a high-priority row. A view passes a `prefix` element
 * (the Tree's expand toggle) and/or an `extra` line (a Search snippet) — the
 * row itself never changes shape.
 */

'use strict';

import { duePicker } from './dueinput.js';
import { icon } from './_vendored/icons/icons.js';
import {
  STATUSES, aiChip, blockedLabel, breadcrumbText, chipFor, isBlocked, isDeferred, issueChip,
  recurrenceLabel, relDue, startsLabel,
} from './format.js';
import { snoozeButton } from './snooze.js';

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

/**
 * The status control — the same compact select on every row.
 * @param {object} t
 * @param {(id:number, status:string) => Promise<any>} onStatus
 */
export function statusSelect(t, onStatus) {
  const sel = document.createElement('select');
  sel.className = 'select-native trow-status';
  sel.setAttribute('aria-label', 'Status of ' + t.title);
  statusOptions(t).forEach(function (v) {
    const o = document.createElement('option');
    o.value = v[0]; o.textContent = v[1]; o.selected = v[0] === t.status;
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
 * The due chip. Given an `onDue` handler it IS the date picker's trigger
 * (#107) — tapping the date on the row opens the same native picker the card's
 * Due field opens, so re-planning costs one gesture instead of open-the-card-
 * then-click-the-date. Without one it stays the plain span it always was: a
 * view that wires no `onPatch`, and Select mode, where every row gesture has
 * to tick rather than do something of its own.
 *
 * The picker comes from `duePicker()` and not from a fourth hand-rolled call:
 * the coarse-pointer branch that makes a native date input actually open on
 * touch (#50) lives there once, and a copy here is exactly the drift its
 * header warns about.
 * @param {object} t
 * @param {{text: string, tone: string}} rel        relDue(t.due)
 * @param {((id:number, iso:string) => any)|null} onDue
 */
function dueChip(t, rel, onDue) {
  const cls = 'due' + (rel.tone ? ' due-' + rel.tone : '');
  if (!onDue) {
    const span = metaPart(cls, 'calendar-days', rel.text, t.due);
    span.dataset.due = t.due;
    return span;
  }
  const box = document.createElement('span');
  box.className = 'trow-due-box';
  const pick = duePicker({
    className: 'trow-' + cls + ' hit-target',
    value: t.due,
    // The bare ISO date, exactly the tooltip the span twin carries: the chip
    // is one line of a dense row, and the aria-label below is where "you can
    // change this" belongs. The Table's roomier cell says it in words.
    title: t.due,
    ariaLabel: 'Due ' + rel.text + ' — change the due date of ' + t.title,
    onPick: function (iso) { if (iso) onDue(t.id, iso); },
  });
  // The label goes after the glyph, exactly as metaPart builds the span twin,
  // and it is what gives the accessible name its visible text (WCAG 2.5.3).
  pick.button.appendChild(document.createTextNode(rel.text));
  // The ISO date, for anything that needs the value rather than the words.
  // It used to be readable only off the chip's `title`, which made the tooltip
  // load-bearing: widening it to say the chip is clickable silently cost Today
  // its overdue tint, because that is where today.js read the date from.
  pick.button.dataset.due = t.due;
  // The coarse branch reveals the native input in order to click it. Put it
  // back out of the flow once the sheet closes — a cancelled pick must not
  // leave a date box sitting in the meta line until the next render.
  pick.picker.addEventListener('blur', function () { pick.picker.classList.remove('is-visible'); });
  box.append(pick.button, pick.picker);
  return box;
}

/**
 * Build the meta line (line 2). Exported so the Table's desktop grid can
 * reuse the same parts in its cells if it ever needs to.
 * @param {object} t
 * @param {{hideProject?: boolean, onDue?: (id:number, iso:string) => any}} [opts]
 *        onDue (optional) turns the due chip into the picker's trigger (#107)
 */
export function metaLine(t, opts) {
  const o = opts || {};
  const meta = document.createElement('span');
  meta.className = 'trow-meta';
  if (t.code) meta.appendChild(metaPart('code', null, t.code, 'code'));
  const project = t.root ? t.root.title : '';
  // the part names the root; its tooltip is the whole path (a journal row
  // three levels down reads "Home renovation › Kitchen" on hover, #102)
  if (project && !o.hideProject) meta.appendChild(metaPart('project', null, project, breadcrumbText(t.breadcrumb) || project));
  if (t.due) meta.appendChild(dueChip(t, relDue(t.due), o.onDue || null));
  // Blocked wins over deferred (#100) — it's the harder gate: a task both
  // asleep and blocked shows the lock, not the clock, wherever either still
  // shows (the Tree, a search hit, the Deferred/blocked filters).
  if (isBlocked(t)) meta.appendChild(metaPart('blocked', 'lock', blockedLabel(t), blockedLabel(t)));
  else if (isDeferred(t)) meta.appendChild(metaPart('starts', 'clock', startsLabel(t.starts), 'starts ' + t.starts));
  if (t.priority && t.priority !== 'none') meta.appendChild(metaPart('prio prio-' + t.priority, null, t.priority, 'priority ' + t.priority));
  if (t.recurrence) meta.appendChild(metaPart('recur', 'repeat', '', recurrenceLabel(t.recurrence, t.recurrence_anchor)));
  if (t.folder_ref) {
    // The phone renders this one icon-only with a 44px tap surface (#74) — the
    // truncated ref reads as noise there — so the name lives on aria-label, not
    // on the (hidden) chip text. Desktop keeps the label; the name still
    // contains it, so WCAG 2.5.3 holds either way.
    const fc = chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url });
    fc.classList.add('trow-folder');
    fc.setAttribute('aria-label', 'Folder ' + t.folder_ref);
    meta.appendChild(fc);
  }
  if (t.ai_url) {
    // Same phone treatment as the folder chip: icon-only, the name on aria-label.
    const ac = aiChip(t.ai_url, t.ai_label);
    ac.classList.add('trow-ai');
    ac.setAttribute('aria-label', 'AI conversation' + (t.ai_label ? ' — ' + t.ai_label : ''));
    meta.appendChild(ac);
  }
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
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onToggleSelect?: (id:number)=>void, onSnooze?: (id:number, phrase:string)=>Promise<any>,
 *          onPatch?: (id:number, patch:object)=>Promise<any>}} handlers
 *          onPatch (optional) makes the due chip the date picker's trigger (#107)
 * @param {{prefix?: HTMLElement, depth?: number, extra?: HTMLElement, hideProject?: boolean,
 *          draggable?: boolean, tag?: string, selectable?: boolean, selected?: boolean,
 *          snooze?: boolean}} [opts]
 *          prefix     = an element before the title (the Tree's toggle);
 *          extra      = a third line under the meta (a Search snippet);
 *          tag        = the element name ('li' default, 'div' for a non-list host);
 *          selectable = Select mode is on (#81): the row grows a leading
 *                       checkbox and the row gesture ticks instead of opening;
 *          snooze     = show the snooze control (#87) — Today passes it, so
 *                       "push this away" lives where the day's list is read
 */
export function taskRow(t, handlers, opts) {
  const o = opts || {};
  const withSnooze = !!(o.snooze && handlers.onSnooze && !o.selectable);
  const li = document.createElement(o.tag || 'li');
  li.className = 'trow' + (t.priority === 'high' ? ' is-high' : '') + (CLOSED[t.status] ? ' is-closed' : '')
    + (o.prefix ? ' has-prefix' : '') + (o.selectable ? ' has-select' : '') + (o.selected ? ' is-selected' : '')
    + (withSnooze ? ' has-snooze' : '');
  li.dataset.id = String(t.id);
  li.dataset.status = t.status;
  if (o.depth != null) li.style.setProperty('--depth', String(o.depth));
  if (o.draggable) li.draggable = true;

  // In Select mode the whole row is a tick target — the same gesture that
  // opens the task otherwise. One affordance for the Board's cards AND the
  // Table's phone rows, because both render this row.
  const activate = function () {
    if (o.selectable) handlers.onToggleSelect(t.id); else handlers.onOpen(t.id);
  };

  if (o.selectable) {
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'trow-check';
    box.checked = !!o.selected;
    box.setAttribute('aria-label', 'Select ' + t.title);
    box.addEventListener('change', function () { handlers.onToggleSelect(t.id); });
    li.appendChild(box);
  }

  if (o.prefix) {
    o.prefix.classList.add('trow-prefix');
    li.appendChild(o.prefix);
  }

  const main = document.createElement('div');
  main.className = 'trow-main';
  main.setAttribute('role', 'button');
  main.tabIndex = 0;
  main.setAttribute('aria-label', (o.selectable ? 'Select ' : '') + t.title);
  const title = document.createElement('span');
  title.className = 'trow-title';
  title.textContent = t.title;
  title.title = t.title;
  main.appendChild(title);
  li.appendChild(main);

  // Snooze sits before the status select, so the two row controls read
  // left-to-right as "later" then "where is it now".
  if (withSnooze) li.appendChild(snoozeButton(t, handlers.onSnooze));
  li.appendChild(statusSelect(t, handlers.onStatus));

  // The due chip re-plans in place (#107) wherever the view wired a patch —
  // never in Select mode, where the row's one job is to tick. The meta line's
  // own click handler already ignores buttons, so the picker's trigger stops
  // opening the drawer without a second rule.
  const meta = metaLine(t, !handlers.onPatch || o.selectable ? o : Object.assign({}, o, {
    onDue: function (id, iso) { return handlers.onPatch(id, { due: iso }); },
  }));
  if (meta.childNodes.length) li.appendChild(meta);
  if (o.extra) {
    o.extra.classList.add('trow-extra');
    li.appendChild(o.extra);
  }

  main.addEventListener('click', function (ev) {
    if (ev.target.closest('a, select, button, input')) return;
    activate();
  });
  main.addEventListener('keydown', function (ev) {
    if (ev.target !== main) return;
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(); }
  });
  // a click on the meta line (not on a chip) opens too — the whole row is the target
  meta.addEventListener('click', function (ev) {
    if (ev.target.closest('a, select, button, input')) return;
    activate();
  });
  return li;
}

/**
 * A flat list of rows.
 * @param {Array<object>} items
 * @param {{onOpen: Function, onStatus: Function, onToggleSelect?: Function}} handlers
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
