/* task-os — the Today tab: what is due, over /api/today.
 *
 * Open tasks due ≤ today (overdue first, then today), grouped by root
 * project with recurring tasks first inside each group; each row is one
 * line — a checkbox to mark done (a recurring task rolls its due forward
 * instead of closing — the caller toasts the next date), the ellipsizing
 * title and the due badge. The person shows in the drawer, not the row.
 * "Later this week" (tomorrow … +7 days) sits collapsed below as a vendored
 * disclosure. This is the phone's landing tab.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { relDue } from './format.js';

/**
 * @param {HTMLElement} host
 * @param {object} data      {today, due: [{root, items}], week: [{root, items}], counts}
 * @param {{onOpen: (id:number)=>void, onDone: (id:number)=>Promise<any>}} handlers
 */
export function renderToday(host, data, handlers) {
  host.innerHTML = '';
  const counts = data.counts || {};
  const dueGroups = data.due || [];
  const weekGroups = data.week || [];

  const card = document.createElement('div');
  card.className = 'card today-card';
  const head = document.createElement('div');
  head.className = 'card-head today-head';
  const h = document.createElement('h2');
  h.className = 'card-title';
  h.innerHTML = icon('calendar-days');
  h.appendChild(document.createTextNode('Today'));
  head.appendChild(h);
  const meta = document.createElement('span');
  meta.className = 'card-head-meta today-counts';
  const bits = [];
  if (counts.overdue) bits.push(counts.overdue + ' overdue');
  if (counts.today) bits.push(counts.today + ' due today');
  meta.textContent = bits.length ? bits.join(' · ') : 'nothing due';
  if (counts.overdue) meta.classList.add('has-overdue');
  head.appendChild(meta);
  card.appendChild(head);

  if (!dueGroups.length) {
    card.appendChild(emptyStateEl('circle-check', 'Nothing due today — all clear'));
  } else {
    dueGroups.forEach(function (g) { card.appendChild(buildGroup(g, handlers)); });
  }
  host.appendChild(card);

  // Later this week — collapsed disclosure (vendored markup).
  const later = document.createElement('details');
  later.className = 'card card--collapsible today-later';
  const summary = document.createElement('summary');
  summary.className = 'collapse-summary';
  const main = document.createElement('span');
  main.className = 'collapse-main';
  main.innerHTML = icon('calendar-days');
  const st = document.createElement('h3');
  st.className = 'collapse-title';
  st.textContent = 'Later this week';
  main.appendChild(st);
  const sc = document.createElement('span');
  sc.className = 'collapse-count';
  sc.textContent = (counts.week || 0) + (counts.week === 1 ? ' task' : ' tasks');
  main.appendChild(sc);
  summary.appendChild(main);
  const chev = document.createElement('span');
  chev.className = 'collapse-chevron';
  chev.setAttribute('aria-hidden', 'true');
  chev.textContent = '›';
  summary.appendChild(chev);
  later.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'collapse-body';
  if (!weekGroups.length) {
    body.appendChild(emptyStateEl('calendar-days', 'Nothing due in the next seven days'));
  } else {
    weekGroups.forEach(function (g) { body.appendChild(buildGroup(g, handlers)); });
  }
  later.appendChild(body);
  host.appendChild(later);
}

function buildGroup(group, handlers) {
  const wrap = document.createElement('section');
  wrap.className = 'today-group';
  const rootId = group.root ? group.root.id : null;
  wrap.dataset.root = rootId == null ? '' : String(rootId);
  const title = document.createElement('h3');
  title.className = 'today-group-title';
  if (group.root) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'today-group-link';
    btn.textContent = group.root.title;
    btn.addEventListener('click', function () { handlers.onOpen(group.root.id); });
    title.appendChild(btn);
  } else {
    title.textContent = 'No project';
    title.classList.add('is-loose');
  }
  const n = document.createElement('span');
  n.className = 'today-group-count';
  n.textContent = String(group.items.length);
  title.appendChild(n);
  wrap.appendChild(title);
  const list = document.createElement('div');
  list.className = 'today-list';
  group.items.forEach(function (t) { list.appendChild(buildRow(t, handlers)); });
  wrap.appendChild(list);
  return wrap;
}

function buildRow(t, handlers) {
  const row = document.createElement('div');
  row.className = 'today-row';
  row.dataset.id = String(t.id);
  const rel = relDue(t.due);
  if (rel.tone) row.classList.add('is-' + rel.tone);

  const check = document.createElement('button');
  check.type = 'button';
  check.className = 'today-check';
  check.setAttribute('role', 'checkbox');
  check.setAttribute('aria-checked', 'false');
  check.setAttribute('aria-label', (t.recurrence ? 'Done for now: ' : 'Mark done: ') + t.title);
  check.title = t.recurrence ? 'Done — rolls to the next ' + t.recurrence + ' date' : 'Mark done';
  check.innerHTML = icon('square') + icon('square-check');
  check.addEventListener('click', function (ev) {
    ev.stopPropagation();
    check.disabled = true;
    check.setAttribute('aria-checked', 'true');
    handlers.onDone(t.id).catch(function () {
      check.disabled = false;
      check.setAttribute('aria-checked', 'false');
    });
  });
  row.appendChild(check);

  const main = document.createElement('span');
  main.className = 'today-main';
  const title = document.createElement('span');
  title.className = 'today-title';
  title.textContent = t.title;
  main.appendChild(title);
  if (t.recurrence) {
    const r = document.createElement('span');
    r.className = 'today-recur';
    r.innerHTML = icon('repeat');
    r.title = t.recurrence;
    main.appendChild(r);
  }
  if (t.breadcrumb && t.breadcrumb.length > 1) {
    const crumb = document.createElement('span');
    crumb.className = 'today-crumb';
    crumb.textContent = t.breadcrumb.slice(1).map(function (c) { return c.title; }).join(' › ');
    main.appendChild(crumb);
  }
  row.appendChild(main);

  const due = document.createElement('span');
  due.className = 'today-due' + (rel.tone ? ' due-' + rel.tone : '');
  due.title = t.due || '';
  due.textContent = rel.text;
  row.appendChild(due);

  row.addEventListener('click', function (ev) {
    if (ev.target.closest('button, a')) return;
    handlers.onOpen(t.id);
  });
  return row;
}
