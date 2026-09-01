/* task-os — the Table tab: the shared list as a grid.
 *
 * Desktop: a full-width flat grid (no card wrapper — hairline rows under a
 * sticky header, issue #46) with columns code · title (+ breadcrumb) · due
 * (relative, ISO tooltip, overdue tinted — the cell opens the date picker,
 * #107) · status (the shared status select) · priority · person · project (top
 * ancestor) · folder chip · last comment (links as chips) · next action. Due
 * edits go through the caller's `onPatch`; status goes through `onStatus` (the
 * shared handler every view uses — issue #54's `complete` vs `done` split
 * lives there, not per-view).
 *
 * Phone (< 768px): the grid has no room, so the same items render as the ONE
 * task row (rows.js) — identical to the Board's rows. The caller decides
 * which (`opts.phone`) and re-renders when the breakpoint flips.
 *
 * Filters and sort live in the shared filter card (filters.js); the list
 * arrives already filtered and sorted.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { duePicker } from './dueinput.js';
import {
  PRIORITIES, aiChip, breadcrumbText, chipFor, isDeferred, issueChip, linkify, priorityLabel,
  relDue, startsLabel, statusPill,
} from './format.js';
import { rowList, statusSelect } from './rows.js';

const COMMENT_MAX = 90;

const COLUMNS = [
  ['code', 'Code'], ['title', 'Title'], ['due', 'Due'], ['status', 'Status'], ['priority', 'Priority'],
  ['person', 'Person'], ['project', 'Project'], ['folder', 'Folder'], ['comment', 'Last comment'], ['next', 'Next action'],
];

/**
 * @param {HTMLElement} host
 * @param {Array<object>} items      already filtered/sorted list items
 * @param {{onOpen: (id:number)=>void, onPatch: (id:number, changes:object)=>Promise<any>,
 *          onStatus: (id:number, status:string)=>Promise<any>,
 *          onToggleSelect?: (id:number)=>void}} handlers
 * @param {{phone?: boolean, selectable?: boolean, isSelected?: (id:number)=>boolean}} [opts]
 *        phone = render the shared rows instead of the grid;
 *        selectable = Select mode is on (#81), so rows tick instead of opening
 */
export function renderTable(host, items, handlers, opts) {
  host.innerHTML = '';
  const o = opts || {};
  const selectable = !!o.selectable;
  const isSelected = o.isSelected || function () { return false; };
  const rowHandlers = {
    onOpen: handlers.onOpen,
    onPatch: handlers.onPatch,          // the phone row's due chip re-plans too (#107)
    onStatus: handlers.onStatus,
    onToggleSelect: handlers.onToggleSelect,
  };
  if (o.phone) {
    // the phone renders the ONE task row, so the checkbox comes from rows.js —
    // the same affordance the Board shows, built once (#81)
    const list = rowList(items, rowHandlers, { selectable: selectable, isSelected: isSelected });
    list.classList.add('table-rows');
    host.appendChild(list);
    return;
  }
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
  const scroller = document.createElement('div');
  scroller.className = 'table-scroll';
  const table = document.createElement('table');
  table.className = 'task-table' + (selectable ? ' is-selectable' : '');
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  if (selectable) {
    // The desktop grid is a real <table>, so its checkbox is its own leading
    // column — not the rows.js one. No select-all here: selection is per row,
    // identical on Board and Table.
    const th = document.createElement('th');
    th.className = 'c-sel';
    th.scope = 'col';
    th.setAttribute('aria-label', 'Select');
    hr.appendChild(th);
  }
  COLUMNS.forEach(function (c) {
    const th = document.createElement('th');
    th.className = 'c-' + c[0];
    th.scope = 'col';
    th.textContent = c[1];
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  items.forEach(function (t) {
    tbody.appendChild(buildRow(t, handlers, rowHandlers, selectable, isSelected(t.id)));
  });
  table.appendChild(tbody);
  scroller.appendChild(table);
  wrap.appendChild(scroller);
  host.appendChild(wrap);
}

function td(cls, label) {
  const el = document.createElement('td');
  el.className = 'c-' + cls;
  el.dataset.label = label;
  return el;
}

function buildRow(t, handlers, rowHandlers, selectable, selected) {
  const tr = document.createElement('tr');
  tr.className = 'task-row' + (selected ? ' is-selected' : '');
  tr.dataset.id = String(t.id);
  tr.tabIndex = 0;
  tr.setAttribute('aria-label', selectable ? 'Select ' + t.title : t.title);

  if (selectable) {
    const sel = td('sel', 'Select');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'row-check';
    box.checked = !!selected;
    box.setAttribute('aria-label', 'Select ' + t.title);
    box.addEventListener('change', function () { rowHandlers.onToggleSelect(t.id); });
    sel.appendChild(box);
    tr.appendChild(sel);
  }

  // code
  const code = td('code', 'Code');
  code.textContent = t.code || ('#' + t.id);
  if (!t.code) code.classList.add('muted');
  tr.appendChild(code);

  // title + breadcrumb
  const title = td('title', 'Title');
  const tt = document.createElement('div');
  tt.className = 't-title';
  const span = document.createElement('span');
  span.className = 't-title-text';
  span.textContent = t.title;
  tt.appendChild(span);
  if (t.is_project) {
    const pc = document.createElement('span');
    pc.className = 'chip chip-project';
    pc.textContent = 'project';
    tt.appendChild(pc);
  }
  if (t.issue_ref) tt.appendChild(issueChip(t.issue_ref));
  else if (t.type === 'coding') {
    const cc = document.createElement('span');
    cc.className = 'chip chip-type';
    cc.innerHTML = icon('git-branch');
    cc.title = 'coding task';
    tt.appendChild(cc);
  }
  title.appendChild(tt);
  if (t.breadcrumb && t.breadcrumb.length) {
    const bc = document.createElement('div');
    bc.className = 't-crumb';
    bc.textContent = breadcrumbText(t.breadcrumb);
    bc.title = bc.textContent;
    title.appendChild(bc);
  }
  // A sleeping task says when it wakes here too (#87). The desktop grid has
  // its own cells rather than the shared row, so the marker the shared row
  // puts on its meta line has to be placed explicitly — and the Deferred
  // filter's own list is exactly where the date matters most.
  if (isDeferred(t)) {
    const st = document.createElement('div');
    st.className = 't-starts';
    st.innerHTML = icon('clock');
    st.appendChild(document.createTextNode(startsLabel(t.starts)));
    st.title = 'starts ' + t.starts;
    title.appendChild(st);
  }
  tr.appendChild(title);

  // due — inline editable
  const due = td('due', 'Due');
  due.appendChild(buildDueCell(t, handlers));
  tr.appendChild(due);

  // status — the shared select
  const status = td('status', 'Status');
  status.appendChild(statusSelect(t, rowHandlers.onStatus));
  tr.appendChild(status);

  // priority
  const prio = td('priority', 'Priority');
  prio.textContent = priorityLabel(t.priority);
  prio.classList.add('prio-' + (t.priority || 'none'));
  tr.appendChild(prio);

  // person
  const person = td('person', 'Person');
  person.textContent = t.person ? t.person.name : '';
  tr.appendChild(person);

  // project = top ancestor
  const project = td('project', 'Project');
  project.textContent = t.root ? t.root.title : '';
  tr.appendChild(project);

  // folder chip → taskos://open?ref=… (the per-PC opener); tooltip = the resolved path
  const folder = td('folder', 'Folder');
  if (t.folder_ref) folder.appendChild(chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url }));
  if (t.ai_url) {
    // the AI-conversation chip (#77) shares the chips cell with the folder
    const ac = aiChip(t.ai_url, t.ai_label);
    ac.setAttribute('aria-label', 'AI conversation' + (t.ai_label ? ' — ' + t.ai_label : ''));
    folder.appendChild(ac);
  }
  tr.appendChild(folder);

  // last comment
  const comment = td('comment', 'Last comment');
  if (t.last_comment) {
    const body = t.last_comment.body || '';
    const short = body.length > COMMENT_MAX ? body.slice(0, COMMENT_MAX - 1) + '…' : body;
    const c = document.createElement('div');
    c.className = 't-comment';
    c.appendChild(linkify(short));
    c.title = t.last_comment.author + ': ' + body;
    comment.appendChild(c);
    const meta = document.createElement('div');
    meta.className = 't-comment-meta';
    meta.textContent = t.last_comment.author;
    comment.appendChild(meta);
  }
  tr.appendChild(comment);

  // next action
  const next = td('next', 'Next action');
  next.textContent = t.next_action || '';
  tr.appendChild(next);

  // open on click / Enter, unless the click landed on a control — in Select
  // mode the same gesture ticks the row instead (#81)
  const activate = function () {
    if (selectable) rowHandlers.onToggleSelect(t.id); else handlers.onOpen(t.id);
  };
  tr.addEventListener('click', function (ev) {
    if (ev.target.closest('select, input, button, a')) return;
    activate();
  });
  tr.addEventListener('keydown', function (ev) {
    if (ev.target !== tr) return;
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(); }
    if (ev.key === 'ArrowDown' && tr.nextElementSibling) { ev.preventDefault(); tr.nextElementSibling.focus(); }
    if (ev.key === 'ArrowUp' && tr.previousElementSibling) { ev.preventDefault(); tr.previousElementSibling.focus(); }
  });
  return tr;
}

/** The due cell: a button showing the relative date; click → text + date inputs. */
/* The due cell IS the picker's trigger (#107): one click opens the same native
 * calendar the card's Due field opens, instead of swapping the cell for a text
 * box you then have to type a date into. Re-planning is the most frequent thing
 * done while reading a list, so it costs one gesture; the phrase vocabulary
 * (`tomorrow`, `fri`, `in 2 weeks`) still lives in the drawer and quick-add,
 * which is where a date gets *typed* rather than picked. */
function buildDueCell(t, handlers) {
  const box = document.createElement('div');
  box.className = 'due-cell';
  const rel = relDue(t.due);
  const pick = duePicker({
    className: 'due-btn' + (rel.tone ? ' due-' + rel.tone : '') + (t.due ? '' : ' due-none'),
    value: t.due || '',
    title: t.due ? t.due + ' — click to change' : 'No due date — click to set',
    ariaLabel: 'Due date of ' + t.title + (t.due ? ': ' + t.due : ': none'),
    onPick: function (iso) { if (iso) handlers.onPatch(t.id, { due: iso }); },
  });
  const btn = pick.button;
  const lbl = document.createElement('span');
  lbl.className = 'due-label';
  lbl.textContent = t.due ? rel.text : '—';
  btn.appendChild(lbl);
  if (t.recurrence) {
    const r = document.createElement('span');
    r.className = 'due-recur';
    r.innerHTML = icon('repeat');
    r.title = t.recurrence;
    btn.appendChild(r);
  }
  // The coarse branch reveals the native input to click it; a cancelled pick
  // must not leave a date box sitting in the cell until the next render.
  pick.picker.addEventListener('blur', function () { pick.picker.classList.remove('is-visible'); });
  box.append(btn, pick.picker);
  return box;
}

export { statusPill, PRIORITIES };
