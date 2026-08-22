/* task-os — the Table tab: the shared list as a grid.
 *
 * Desktop: a full-width flat grid (no card wrapper — hairline rows under a
 * sticky header, issue #46) with columns code · title (+ breadcrumb) · due
 * (relative, ISO tooltip, overdue tinted) · status (the shared status select)
 * · priority · person · project (top ancestor) · folder chip · last comment
 * (links as chips) · next action. Inline due edits go through the caller's
 * `onPatch`; status goes through `onStatus` (the shared handler every view
 * uses — issue #54's `complete` vs `done` split lives there, not per-view).
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
import {
  PRIORITIES, breadcrumbText, chipFor, issueChip, linkify, priorityLabel, relDue, statusPill,
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
 *          onStatus: (id:number, status:string)=>Promise<any>}} handlers
 * @param {{phone?: boolean}} [opts]  phone = render the shared rows instead of the grid
 */
export function renderTable(host, items, handlers, opts) {
  host.innerHTML = '';
  const rowHandlers = {
    onOpen: handlers.onOpen,
    onStatus: handlers.onStatus,
  };
  if (opts && opts.phone) {
    const list = rowList(items, rowHandlers);
    list.classList.add('table-rows');
    host.appendChild(list);
    return;
  }
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
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
  items.forEach(function (t) { tbody.appendChild(buildRow(t, handlers, rowHandlers)); });
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

function buildRow(t, handlers, rowHandlers) {
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
