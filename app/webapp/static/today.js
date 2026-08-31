/* task-os — the Today tab: what is due, from the shared list.
 *
 * Tasks due ≤ today (overdue first, then today), grouped by root project
 * with recurring tasks first inside each group; "Later this week"
 * (tomorrow … +7 days) sits collapsed below as a flat disclosure. Rows are
 * the ONE task row (rows.js, issue #46) — title + status select (the Board
 * control; the old checkbox is gone), the meta line (project hidden — the
 * group already names it) and the snooze control (#87) — the one view that
 * carries it, because this is where "not today" gets decided. Flat hairline
 * rows, no card wrapper, group titles in the app's normal title font. This is
 * the phone's landing tab.
 *
 * My plan (#89) sits on top: the tasks committed to today (opts.plan — the
 * /api/today plan group, server-ordered, done ones included for the "n of m"
 * progress line), with drag-to-reorder and a remove control per row. When
 * the plan is empty and candidates exist, a banner offers plan mode: each
 * candidate row grows two large targets — Today (sets planned_on) and Later
 * (the existing snooze popover, #87 — one "not now" mechanism, not two). A
 * candidate planned on an earlier day wears a "planned yesterday" note, so
 * re-committing is a conscious act, never a silent carry-over. A task
 * planned today leaves the due/week buckets — it lives in the plan.
 *
 * Everything else is derived in the browser from the shared filtered list,
 * so the filter card (status · project · person · sort …) applies here like
 * on every other tab; the plan itself is your commitment list and stays
 * whole regardless of filters.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { fmtDay, relDue, todayISO } from './format.js';
import { compareItems, rowList, taskRow } from './rows.js';
import { snoozeButton } from './snooze.js';

/** Split the list into {due, week, counts} — exported for tests. A task
 *  planned today is excluded (it renders in My plan instead, #89). */
export function bucketToday(items, today, sort) {
  const t = today || todayISO();
  const end = new Date(t + 'T00:00:00');
  end.setDate(end.getDate() + 7);
  const weekEnd = todayISO(end);
  const due = [];
  const week = [];
  (items || []).forEach(function (it) {
    if (!it.due || it.planned_on === t) return;
    if (it.due <= t) due.push(it);
    else if (it.due <= weekEnd) week.push(it);
  });
  return {
    today: t,
    due: groupByRoot(due, sort),
    week: groupByRoot(week, sort),
    counts: {
      overdue: due.filter(function (it) { return it.due < t; }).length,
      today: due.filter(function (it) { return it.due === t; }).length,
      week: week.length,
    },
  };
}

/** What plan-my-day offers (#89): open overdue + due-today + inbox tasks not
 *  already planned today — exported for tests. The list order (due →
 *  priority → id, no-due last) already reads overdue → today → inbox. */
export function planCandidates(items, today) {
  const t = today || todayISO();
  return (items || []).filter(function (it) {
    if (it.status === 'done' || it.status === 'cancelled') return false;
    if (it.planned_on === t) return false;
    return (it.due && it.due <= t) || it.status === 'inbox';
  });
}

/** [{root, items}] — by top ancestor (null = no project); groups ordered by
 *  earliest due then title; inside a group recurring tasks first, then the
 *  shared sort. */
function groupByRoot(items, sort) {
  const cmp = compareItems(sort || 'due');
  const groups = new Map();
  items.forEach(function (it) {
    const key = it.root ? it.root.id : null;
    if (!groups.has(key)) groups.set(key, { root: it.root || null, items: [] });
    groups.get(key).items.push(it);
  });
  const out = Array.from(groups.values());
  out.forEach(function (g) {
    g.items.sort(function (a, b) { return ((a.recurrence ? 0 : 1) - (b.recurrence ? 0 : 1)) || cmp(a, b); });
  });
  out.sort(function (a, b) {
    const ad = a.items.reduce(function (m, it) { return m == null || it.due < m ? it.due : m; }, null) || '';
    const bd = b.items.reduce(function (m, it) { return m == null || it.due < m ? it.due : m; }, null) || '';
    return ad.localeCompare(bd) || ((a.root ? a.root.title : '').localeCompare(b.root ? b.root.title : ''));
  });
  return out;
}

/**
 * @param {HTMLElement} host
 * @param {Array<object>} items  the shared filtered list
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onSnooze?: (id:number, phrase:string)=>Promise<any>,
 *          onPlan?: (id:number)=>Promise<any>, onUnplan?: (id:number)=>Promise<any>,
 *          onReorder?: (ids:number[])=>Promise<any>, onPlanMode?: (on:boolean)=>void,
 *          onToggleSelect?: (id:number)=>void}} handlers
 * @param {{sort?: string, today?: string,
 *          plan?: {items: Array<object>, done: number, total: number},
 *          planMode?: boolean,
 *          selectable?: boolean, isSelected?: (id:number)=>boolean}} [opts]
 */
export function renderToday(host, items, handlers, opts) {
  const o = opts || {};
  const t = o.today || todayISO();
  const plan = o.plan || { items: [], done: 0, total: 0 };
  const data = bucketToday(items, t, o.sort);
  const cands = planCandidates(items, t);
  host.innerHTML = '';
  const counts = data.counts;

  if (plan.items.length || o.planMode) {
    host.appendChild(buildPlanSection(plan, cands, handlers, o));
  }
  if (o.planMode) {
    host.appendChild(buildPicker(cands, t, handlers, o));
  } else if (!plan.items.length && cands.length && handlers.onPlanMode) {
    host.appendChild(buildBanner(cands, t, handlers));
  }

  const section = document.createElement('section');
  section.className = 'today';
  const head = document.createElement('div');
  head.className = 'today-head';
  const h = document.createElement('h2');
  h.className = 'today-title';
  h.innerHTML = icon('calendar-days');
  h.appendChild(document.createTextNode('Today'));
  head.appendChild(h);
  const meta = document.createElement('span');
  meta.className = 'today-counts';
  const bits = [];
  if (counts.overdue) bits.push(counts.overdue + ' overdue');
  if (counts.today) bits.push(counts.today + ' due today');
  meta.textContent = bits.length ? bits.join(' · ') : 'nothing due';
  if (counts.overdue) meta.classList.add('has-overdue');
  head.appendChild(meta);
  section.appendChild(head);

  if (!data.due.length) {
    section.appendChild(emptyStateEl('circle-check', 'Nothing due today — all clear'));
  } else {
    data.due.forEach(function (g) { section.appendChild(buildGroup(g, handlers, o)); });
  }
  host.appendChild(section);

  // Later this week — a flat disclosure (vendored markup, hairline instead of a card box).
  const later = document.createElement('details');
  later.className = 'card card--collapsible disclosure-flat today-later';
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
  sc.textContent = counts.week + (counts.week === 1 ? ' task' : ' tasks');
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
  if (!data.week.length) {
    body.appendChild(emptyStateEl('calendar-days', 'Nothing due in the next seven days'));
  } else {
    data.week.forEach(function (g) { body.appendChild(buildGroup(g, handlers, o)); });
  }
  later.appendChild(body);
  host.appendChild(later);
}

// ------------------------------------------------------------ My plan (#89)

/** The ordered commitment list with the n-of-m progress line. Rows drag to
 *  reorder (the Board's HTML5 idiom — desktop; the phone plans in tap order)
 *  and carry a quiet remove control; the status select completes in place. */
function buildPlanSection(plan, cands, handlers, o) {
  const section = document.createElement('section');
  section.className = 'today today-plan';
  const head = document.createElement('div');
  head.className = 'today-head';
  const h = document.createElement('h2');
  h.className = 'today-title';
  h.innerHTML = icon('list-checks');
  h.appendChild(document.createTextNode('My plan'));
  head.appendChild(h);
  const meta = document.createElement('span');
  meta.className = 'today-counts';
  meta.textContent = plan.total
    ? plan.done + ' of ' + plan.total + ' done'
    : 'nothing planned yet';
  head.appendChild(meta);
  if (!o.planMode && cands.length && handlers.onPlanMode) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'plan-more hit-target';
    more.title = 'Plan more';
    more.setAttribute('aria-label', 'Plan more tasks');
    more.innerHTML = icon('plus');
    more.addEventListener('click', function () { handlers.onPlanMode(true); });
    head.appendChild(more);
  }
  section.appendChild(head);

  if (!plan.items.length) {
    section.appendChild(emptyStateEl('list-checks', 'Pick the tasks you intend to do today'));
    return section;
  }

  const ul = document.createElement('ul');
  ul.className = 'trows today-list plan-list';
  ul.setAttribute('role', 'list');
  let dragging = null;
  const startOrder = plan.items.map(function (t) { return t.id; }).join(',');

  ul.addEventListener('dragover', function (ev) {
    if (!dragging) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    const over = ev.target.closest('.trow');
    if (!over || over === dragging || over.parentElement !== ul) return;
    const rect = over.getBoundingClientRect();
    const after = ev.clientY > rect.top + rect.height / 2;
    ul.insertBefore(dragging, after ? over.nextSibling : over);
  });
  ul.addEventListener('drop', function (ev) { ev.preventDefault(); });

  plan.items.forEach(function (t) {
    // Select mode (#81): the row is a plain tick target — the grip, the
    // remove control and the drag all step aside, the Board's rule.
    if (o.selectable) {
      ul.appendChild(taskRow(t, handlers, {
        selectable: true, selected: !!(o.isSelected && o.isSelected(t.id)),
      }));
      return;
    }
    const grip = document.createElement('span');
    grip.className = 'plan-grip';
    grip.setAttribute('aria-hidden', 'true');
    grip.innerHTML = icon('grip-vertical');
    const row = taskRow(t, handlers, { prefix: grip, draggable: true });
    row.classList.add('is-plan');
    if (handlers.onUnplan) {
      const un = document.createElement('button');
      un.type = 'button';
      un.className = 'plan-unplan hit-target';
      un.title = 'Remove from plan';
      un.setAttribute('aria-label', 'Remove ' + t.title + ' from the plan');
      un.innerHTML = icon('x');
      un.addEventListener('click', function () { handlers.onUnplan(t.id); });
      row.insertBefore(un, row.querySelector('.trow-status'));
    }
    row.addEventListener('dragstart', function (ev) {
      ev.dataTransfer.setData('text/plain', String(t.id));
      ev.dataTransfer.effectAllowed = 'move';
      dragging = row;
      row.classList.add('is-dragging');
    });
    row.addEventListener('dragend', function () {
      row.classList.remove('is-dragging');
      dragging = null;
      const ids = Array.from(ul.querySelectorAll('.trow')).map(function (r) {
        return Number(r.dataset.id);
      });
      if (handlers.onReorder && ids.join(',') !== startOrder) handlers.onReorder(ids);
    });
    ul.appendChild(row);
  });
  section.appendChild(ul);
  return section;
}

/** "Plan your day — 3 overdue · 5 due today · 4 new in Inbox" + the button. */
function buildBanner(cands, t, handlers) {
  const wrap = document.createElement('div');
  wrap.className = 'plan-banner';
  const text = document.createElement('span');
  text.className = 'plan-banner-text';
  text.innerHTML = icon('list-checks');
  const overdue = cands.filter(function (c) { return c.due && c.due < t; }).length;
  const dueToday = cands.filter(function (c) { return c.due === t; }).length;
  const inbox = cands.filter(function (c) { return c.status === 'inbox' && (!c.due || c.due > t); }).length;
  const bits = [];
  if (overdue) bits.push(overdue + ' overdue');
  if (dueToday) bits.push(dueToday + ' due today');
  if (inbox) bits.push(inbox + ' new in Inbox');
  text.appendChild(document.createTextNode('Plan your day — ' + bits.join(' · ')));
  wrap.appendChild(text);
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'button-surface plan-banner-btn';
  btn.textContent = 'Plan my day';
  btn.addEventListener('click', function () { handlers.onPlanMode(true); });
  wrap.appendChild(btn);
  return wrap;
}

/** Plan mode: the candidates, each with the two large targets — Today (sets
 *  planned_on) and Later (the snooze popover, #87). */
function buildPicker(cands, t, handlers, o) {
  const section = document.createElement('section');
  section.className = 'today plan-picker';
  const head = document.createElement('div');
  head.className = 'today-head';
  const h = document.createElement('h2');
  h.className = 'today-title';
  h.innerHTML = icon('list-checks');
  h.appendChild(document.createTextNode('Plan your day'));
  head.appendChild(h);
  const meta = document.createElement('span');
  meta.className = 'today-counts';
  meta.textContent = cands.length + (cands.length === 1 ? ' candidate' : ' candidates');
  head.appendChild(meta);
  const done = document.createElement('button');
  done.type = 'button';
  done.className = 'button-surface plan-done-btn';
  done.textContent = 'Done planning';
  done.addEventListener('click', function () { handlers.onPlanMode(false); });
  head.appendChild(done);
  section.appendChild(head);

  if (!cands.length) {
    section.appendChild(emptyStateEl('circle-check', 'Nothing left to plan — all committed'));
    return section;
  }

  const ul = document.createElement('ul');
  ul.className = 'trows today-list plan-cands';
  ul.setAttribute('role', 'list');
  cands.forEach(function (c) {
    const extra = document.createElement('div');
    extra.className = 'plan-targets';
    if (c.planned_on && c.planned_on < t) {
      const note = document.createElement('span');
      note.className = 'plan-note';
      const y = new Date(t + 'T00:00:00');
      y.setDate(y.getDate() - 1);
      note.textContent = (c.planned_on === todayISO(y) ? 'planned yesterday' : 'planned ' + fmtDay(c.planned_on)) + ' — not finished';
      extra.appendChild(note);
    }
    const pick = document.createElement('button');
    pick.type = 'button';
    pick.className = 'button-surface plan-target';
    pick.setAttribute('aria-label', 'Plan ' + c.title + ' for today');
    pick.innerHTML = icon('sun');
    pick.appendChild(document.createTextNode('Today'));
    pick.addEventListener('click', function () {
      pick.disabled = true;
      Promise.resolve(handlers.onPlan(c.id)).finally(function () { pick.disabled = false; });
    });
    extra.appendChild(pick);
    if (handlers.onSnooze) {
      const later = snoozeButton(c, handlers.onSnooze);
      later.classList.add('plan-later');
      const sum = later.querySelector('.snooze-summary');
      // in plan mode Later IS a large boxed target (deliberately, next to
      // Today) — re-add the surface the row control just dropped
      sum.classList.add('plan-target', 'button-surface');
      sum.appendChild(document.createTextNode('Later'));
      extra.appendChild(later);
    }
    ul.appendChild(taskRow(c, handlers, {
      extra: extra,
      selectable: !!(o && o.selectable),
      selected: !!(o && o.selectable && o.isSelected && o.isSelected(c.id)),
    }));
  });
  section.appendChild(ul);
  return section;
}

function buildGroup(group, handlers, o) {
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
  const list = rowList(group.items, handlers, {
    hideProject: true, snooze: true,
    selectable: !!(o && o.selectable), isSelected: o && o.isSelected,
  });
  list.classList.add('today-list');
  list.querySelectorAll('.trow').forEach(function (row) {
    const rel = relDue(row.querySelector('.trow-due') ? row.querySelector('.trow-due').title : '');
    if (rel.tone) row.classList.add('is-' + rel.tone);
  });
  wrap.appendChild(list);
  return wrap;
}
