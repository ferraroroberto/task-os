/* task-os — History's drawing: the kind chips and the day cards. Each
 * function takes the composer's `ctx` first (history.js). */

'use strict';

import { emptyStateEl } from '../../_vendored/empty-state/empty-state.js';
import { icon } from '../../_vendored/icons/icons.js';
import { fmtDay, todayISO } from '../../format.js';
import { dayLabel } from '../../journal.js';
import { KINDS, changeText, timeOf } from './text.js';

// The server's window cap (src/tasks/history.py MAX_WINDOW_DAYS).
const MAX_DAYS = 31;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export function renderKinds(ctx) {
  const st = ctx.st;
  const counts = st.feed ? st.feed.counts : null;
  ctx.els.kinds.replaceChildren.apply(ctx.els.kinds, KINDS.map(function (k) {
    const b = el('button', 'button-surface history-kind');
    b.type = 'button';
    b.dataset.kind = k.key;
    b.dataset.track = 'history.kind';
    b.setAttribute('aria-pressed', String(k.key === st.kind));
    b.appendChild(el('span', null, k.label));
    if (counts && counts[k.key] != null) b.appendChild(el('span', 'history-kind-count', String(counts[k.key])));
    b.addEventListener('click', function () { ctx.pickKind(k.key); });
    return b;
  }));
}

function entryLine(e) {
  const li = el('li', 'history-entry');
  li.dataset.kind = e.kind;
  li.append(el('span', 'history-entry-text', changeText(e)), el('span', 'history-entry-time', timeOf(e.ts)));
  return li;
}

function expandButton(ctx, key, n) {
  const open = ctx.st.open.has(key);
  const toggle = el('button', 'icon-button action-row-verb history-expand');
  toggle.type = 'button';
  toggle.dataset.track = 'history.expand';
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' the ' + n + ' changes');
  toggle.innerHTML = icon(open ? 'chevron-up' : 'chevron-down');
  toggle.addEventListener('click', function () {
    if (ctx.st.open.has(key)) ctx.st.open.delete(key); else ctx.st.open.add(key);
    render(ctx);
  });
  return toggle;
}

/** One run of changes to one task: the row, and its list when opened. A group
 *  is named by its day and place in it — one task can have several runs in a
 *  day, all in one second. */
function groupRows(ctx, day, g, at) {
  const key = day + ':' + at + ':' + g.task_id;
  const li = el('li', 'action-row history-row');
  li.dataset.id = String(g.task_id);
  const main = el('button', 'action-row-main');
  main.type = 'button';
  main.dataset.track = 'history.open';
  const text = el('span', 'action-row-text');
  const newest = g.entries[0];
  const more = g.entries.length > 1 ? ' · ' + g.entries.length + ' changes' : '';
  text.append(el('span', 'action-row-title', g.title), el('span', 'action-row-meta', changeText(newest) + ' · ' + timeOf(newest.ts) + more));
  main.appendChild(text);
  main.addEventListener('click', function () { ctx.onOpen(g.task_id); });
  li.appendChild(main);
  if (g.entries.length < 2) return [li];
  li.appendChild(expandButton(ctx, key, g.entries.length));
  if (!ctx.st.open.has(key)) return [li];
  const detail = el('li', 'history-detail');
  const list = el('ul', 'history-entries');
  g.entries.forEach(function (e) { list.appendChild(entryLine(e)); });
  detail.appendChild(list);
  return [li, detail];
}

function emptyDay(ctx, feed) {
  const today = todayISO();
  const k = KINDS.find(function (x) { return x.key === ctx.st.kind; });
  const what = k && k.key !== 'all' ? k.label.toLowerCase() + ' ' : '';
  const when = feed.from === feed.to ? (feed.to === today ? 'today' : 'on ' + fmtDay(feed.to)) : 'since ' + fmtDay(feed.from);
  return emptyStateEl('history', 'No ' + what + 'changes ' + when, ctx.st.kind === 'all' ? undefined : {
    actionLabel: 'Show all changes', onAction: function () { ctx.pickKind('all'); },
  });
}

function foot(ctx, feed) {
  const f = el('div', 'history-foot');
  if (feed.older === false) {
    f.appendChild(el('span', 'muted', 'That is everything — nothing changed before ' + fmtDay(feed.from)));
  } else if (ctx.st.days < MAX_DAYS) {
    const older = el('button', 'button-surface history-older', 'Show the day before');
    older.type = 'button';
    older.dataset.track = 'history.older';
    older.addEventListener('click', function () { older.disabled = true; ctx.st.days += 1; ctx.load(); });
    f.appendChild(older);
  }
  return f;
}

/** The list under the chips: the unreadable state, the empty day, or the day cards. */
export function render(ctx) {
  const host = ctx.els.host;
  const st = ctx.st;
  if (st.error) {
    host.dataset.state = 'error';
    host.replaceChildren(emptyStateEl('triangle-alert', 'Could not read your history: ' + st.error, {
      actionLabel: 'Try again', onAction: function () { ctx.load(); },
    }));
    return;
  }
  const feed = st.feed;
  // Not read yet: no state is claimed, and nothing is drawn.
  if (!feed) { delete host.dataset.state; host.replaceChildren(); return; }
  const parts = [];
  host.dataset.state = feed.days.length ? 'ok' : 'empty';
  if (!feed.days.length) parts.push(emptyDay(ctx, feed));
  const today = todayISO();
  feed.days.forEach(function (d) {
    const head = el('h3', 'overline history-day-title', dayLabel(d.day, today));
    head.appendChild(el('span', 'history-day-count', d.count + (d.count === 1 ? ' change' : ' changes')));
    const card = el('section', 'card action-list history-day');
    card.dataset.day = d.day;
    const list = el('ul', 'action-rows');
    d.groups.forEach(function (g, at) { groupRows(ctx, d.day, g, at).forEach(function (n) { list.appendChild(n); }); });
    card.appendChild(list);
    parts.push(head, card);
  });
  parts.push(foot(ctx, feed));
  host.replaceChildren.apply(host, parts);
}
