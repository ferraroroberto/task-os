/* task-os — the Table tab: a full-width grid over /api/tasks.
 *
 * Columns: code · title (+ breadcrumb) · due (relative, ISO tooltip, overdue
 * tinted) · status (inline select) · priority · person · project (top
 * ancestor) · folder chip · last comment (links as chips) · next action.
 * The filter bar above it is pure state → the caller encodes it into the URL
 * query so a view is shareable. Inline edits (due as text or date, status)
 * go through the caller's `onPatch` so every write follows one path.
 *
 * On a narrow screen the same rows render as stacked cards (styles.css).
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import {
  PRIORITIES, STATUSES, breadcrumbText, chipFor, issueChip, linkify, priorityLabel, relDue, statusPill,
} from './format.js';

export const DEFAULT_FILTERS = { status: [], project: '', person: '', due: '', q: '', sort: 'due' };
const DUE_WINDOWS = [['', 'Any due'], ['today', 'Due today'], ['week', 'Due this week'], ['overdue', 'Overdue']];
const SORTS = [['due', 'Sort: due'], ['priority', 'Sort: priority'], ['updated', 'Sort: updated']];
const PRIO_RANK = { high: 0, medium: 1, low: 2, none: 3 };
const COMMENT_MAX = 90;

export function filtersFromSearch(search) {
  const p = new URLSearchParams(search || '');
  const f = Object.assign({}, DEFAULT_FILTERS);
  const st = (p.get('status') || '').split(',').map(function (s) { return s.trim(); }).filter(function (s) { return STATUSES.indexOf(s) >= 0; });
  f.status = st;
  f.project = p.get('project') || '';
  f.person = p.get('person') || '';
  f.due = p.get('due') || '';
  f.q = p.get('q') || '';
  f.sort = SORTS.some(function (s) { return s[0] === p.get('sort'); }) ? p.get('sort') : 'due';
  return f;
}

export function filtersToSearch(f) {
  const p = new URLSearchParams();
  if (f.status.length) p.set('status', f.status.join(','));
  if (f.project) p.set('project', f.project);
  if (f.person) p.set('person', f.person);
  if (f.due) p.set('due', f.due);
  if (f.q) p.set('q', f.q);
  if (f.sort && f.sort !== 'due') p.set('sort', f.sort);
  const s = p.toString();
  return s ? '?' + s : '';
}

export function isDefaultFilters(f) {
  return filtersToSearch(f) === '';
}

// ------------------------------------------------------------- filter bar
/** One filter `<select>` (select-native) — shared with the Board's filter row. */
export function filterSelect(name, label, values, current, onChange) {
  const sel = document.createElement('select');
  sel.className = 'select-native filter-select';
  sel.name = name;
  sel.setAttribute('aria-label', label);
  values.forEach(function (v) {
    const o = document.createElement('option');
    o.value = String(v[0]);
    o.textContent = v[1];
    if (String(v[0]) === String(current)) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () { onChange(sel.value); });
  return sel;
}

/**
 * @param {HTMLElement} host
 * @param {object} filters   current state (not mutated)
 * @param {{projects: Array<{id:number,title:string,depth?:number}>, people: Array<{id:number,name:string}>, count: number}} options
 * @param {(next: object) => void} onChange
 */
export function renderFilterBar(host, filters, options, onChange) {
  host.innerHTML = '';
  host.hidden = false;
  const bar = document.createElement('div');
  bar.className = 'filter-row';

  const glyph = document.createElement('span');
  glyph.className = 'filter-glyph';
  glyph.innerHTML = icon('list-filter');
  glyph.title = 'Filters';
  bar.appendChild(glyph);

  // status: toggle chips; none active = "open" (not done/cancelled)
  const stGroup = document.createElement('div');
  stGroup.className = 'filter-status';
  stGroup.setAttribute('role', 'group');
  stGroup.setAttribute('aria-label', 'Status');
  STATUSES.forEach(function (s) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip-btn pill pill-' + s + (filters.status.indexOf(s) >= 0 ? ' active' : '');
    b.dataset.status = s;
    b.setAttribute('aria-pressed', filters.status.indexOf(s) >= 0 ? 'true' : 'false');
    b.textContent = s;
    b.addEventListener('click', function () {
      const next = Object.assign({}, filters);
      const set = filters.status.slice();
      const i = set.indexOf(s);
      if (i >= 0) set.splice(i, 1); else set.push(s);
      next.status = set;
      onChange(next);
    });
    stGroup.appendChild(b);
  });
  bar.appendChild(stGroup);

  function select(name, label, values, current) {
    return filterSelect(name, label, values, current, function (value) {
      const next = Object.assign({}, filters);
      next[name] = value;
      onChange(next);
    });
  }
  const projectValues = [['', 'All projects']].concat((options.projects || []).map(function (p) {
    return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
  }));
  bar.appendChild(select('project', 'Project', projectValues, filters.project));
  const personValues = [['', 'Anyone']].concat((options.people || []).map(function (p) { return [p.id, p.name]; }));
  bar.appendChild(select('person', 'Person', personValues, filters.person));
  bar.appendChild(select('due', 'Due window', DUE_WINDOWS, filters.due));

  const q = document.createElement('input');
  q.type = 'search';
  q.className = 'input-native filter-q';
  q.placeholder = 'Filter text…';
  q.setAttribute('aria-label', 'Filter text');
  q.value = filters.q;
  let qt = 0;
  q.addEventListener('input', function () {
    window.clearTimeout(qt);
    qt = window.setTimeout(function () {
      const next = Object.assign({}, filters);
      next.q = q.value.trim();
      onChange(next);
    }, 250);
  });
  bar.appendChild(q);

  bar.appendChild(select('sort', 'Sort', SORTS, filters.sort));

  const count = document.createElement('span');
  count.className = 'filter-count';
  count.textContent = options.count + (options.count === 1 ? ' task' : ' tasks');
  bar.appendChild(count);

  if (!isDefaultFilters(filters)) {
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'button-ghost filter-clear';
    clear.textContent = 'Clear';
    clear.addEventListener('click', function () { onChange(Object.assign({}, DEFAULT_FILTERS)); });
    bar.appendChild(clear);
  }
  host.appendChild(bar);
}

// ------------------------------------------------------------------ rows
export function sortItems(items, sort) {
  const arr = items.slice();
  if (sort === 'priority') {
    arr.sort(function (a, b) {
      return (PRIO_RANK[a.priority] - PRIO_RANK[b.priority]) || cmpDue(a, b) || (a.id - b.id);
    });
  } else if (sort === 'updated') {
    arr.sort(function (a, b) { return (b.updated_at || '').localeCompare(a.updated_at || '') || (b.id - a.id); });
  } else {
    arr.sort(function (a, b) { return cmpDue(a, b) || (PRIO_RANK[a.priority] - PRIO_RANK[b.priority]) || (a.id - b.id); });
  }
  return arr;
}
function cmpDue(a, b) {
  if (!a.due && !b.due) return 0;
  if (!a.due) return 1;
  if (!b.due) return -1;
  return a.due.localeCompare(b.due);
}

const COLUMNS = [
  ['code', 'Code'], ['title', 'Title'], ['due', 'Due'], ['status', 'Status'], ['priority', 'Priority'],
  ['person', 'Person'], ['project', 'Project'], ['folder', 'Folder'], ['comment', 'Last comment'], ['next', 'Next action'],
];

/**
 * @param {HTMLElement} host
 * @param {Array<object>} items      already filtered/sorted list items
 * @param {{onOpen: (id:number)=>void, onPatch: (id:number, changes:object)=>Promise<any>}} handlers
 */
export function renderTable(host, items, handlers) {
  host.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'card table-card';
  const scroller = document.createElement('div');
  scroller.className = 'table-scroll';
  const table = document.createElement('table');
  table.className = 'task-table';
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
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
  items.forEach(function (t) { tbody.appendChild(buildRow(t, handlers)); });
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

function buildRow(t, handlers) {
  const tr = document.createElement('tr');
  tr.className = 'task-row';
  tr.dataset.id = String(t.id);
  tr.tabIndex = 0;
  tr.setAttribute('aria-label', t.title);

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
  tr.appendChild(title);

  // due — inline editable
  const due = td('due', 'Due');
  due.appendChild(buildDueCell(t, handlers));
  tr.appendChild(due);

  // status — inline select
  const status = td('status', 'Status');
  const sel = document.createElement('select');
  sel.className = 'select-native row-select status-select pill-' + t.status;
  sel.setAttribute('aria-label', 'Status of ' + t.title);
  STATUSES.forEach(function (s) {
    const o = document.createElement('option');
    o.value = s; o.textContent = s; o.selected = s === t.status;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () {
    sel.disabled = true;
    handlers.onPatch(t.id, { status: sel.value }).catch(function () { sel.value = t.status; }).finally(function () { sel.disabled = false; });
  });
  status.appendChild(sel);
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

  // folder chip (Step 9 wires the opener; the chip renders the ref today)
  const folder = td('folder', 'Folder');
  if (t.folder_ref) folder.appendChild(chipFor(t.folder_ref));
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

  // open on click / Enter, unless the click landed on a control
  tr.addEventListener('click', function (ev) {
    if (ev.target.closest('select, input, button, a')) return;
    handlers.onOpen(t.id);
  });
  tr.addEventListener('keydown', function (ev) {
    if (ev.target !== tr) return;
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); handlers.onOpen(t.id); }
    if (ev.key === 'ArrowDown' && tr.nextElementSibling) { ev.preventDefault(); tr.nextElementSibling.focus(); }
    if (ev.key === 'ArrowUp' && tr.previousElementSibling) { ev.preventDefault(); tr.previousElementSibling.focus(); }
  });
  return tr;
}

/** The due cell: a button showing the relative date; click → text + date inputs. */
function buildDueCell(t, handlers) {
  const box = document.createElement('div');
  box.className = 'due-cell';
  const rel = relDue(t.due);
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'due-btn' + (rel.tone ? ' due-' + rel.tone : '') + (t.due ? '' : ' due-none');
  btn.title = t.due ? t.due + ' — click to change' : 'No due date — click to set';
  btn.setAttribute('aria-label', 'Due date of ' + t.title + (t.due ? ': ' + t.due : ': none'));
  btn.innerHTML = icon('calendar-days');
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
  box.appendChild(btn);

  btn.addEventListener('click', function () {
    const editor = document.createElement('span');
    editor.className = 'due-editor';
    const text = document.createElement('input');
    text.type = 'text';
    text.className = 'input-native due-text';
    text.value = t.due || '';
    text.placeholder = 'tomorrow · fri · in 2 weeks';
    text.setAttribute('aria-label', 'Due date (natural text)');
    const date = document.createElement('input');
    date.type = 'date';
    date.className = 'input-native due-date';
    date.value = t.due || '';
    date.setAttribute('aria-label', 'Due date (picker)');
    editor.append(text, date);
    box.replaceChildren(editor);
    text.focus();
    text.select();
    let done = false;
    function commit(value) {
      if (done) return;
      done = true;
      handlers.onPatch(t.id, { due: value }).catch(function () { restore(); });
    }
    function restore() { box.replaceChildren(btn); }
    text.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); commit(text.value.trim()); }
      if (ev.key === 'Escape') { ev.preventDefault(); done = true; restore(); }
    });
    date.addEventListener('change', function () { commit(date.value); });
    editor.addEventListener('focusout', function (ev) {
      if (editor.contains(ev.relatedTarget)) return;
      // leaving the editor without committing keeps the old value
      window.setTimeout(function () { if (!done && !editor.contains(document.activeElement)) { done = true; restore(); } }, 0);
    });
  });
  return box;
}

export { statusPill, PRIORITIES };
