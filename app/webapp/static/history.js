/* task-os — the History tab: what I changed, newest first.
 *
 * A reading view over `GET /api/history` (src/tasks/history.py owns the
 * feed: whose changes, the day of each, the kind of each, the grouping). One
 * overline per local day, a card of rows under it; a row is one task and the
 * run of consecutive changes made to it, its newest change on the meta line.
 * A row with more than one change expands (the trailing chevron) to list them
 * all; the row itself opens the task's drawer.
 *
 * The kind chips (All · Date moved · Closed/reopened · Status · Priority ·
 * Moved · Comments) re-read the feed with `kind=`, so the grouping is always
 * the server's over what is shown; the choice is remembered on this device.
 * The page is a window of days ending today; "Show the day before" widens it
 * up to the server's cap. Whether anything older exists is the server's
 * `older`, so the end of the history is only stated when it said so.
 *
 * Nothing loads until the tab is first shown, and nothing polls: the feed is
 * re-read when the tab is shown again and after any write (app.js).
 * A read that fails is its own state — the reason and Try again — never an
 * empty day.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { api, qs } from './api.js';
import { addDays, fmtDay, todayISO } from './format.js';
import { dayLabel } from './journal.js';
import { fieldWords } from './js/drawer/activity.js';

const KIND_KEY = 'task-os.history.kind';
// The server's window cap (src/tasks/history.py MAX_WINDOW_DAYS).
const MAX_DAYS = 31;

/** The chips, in the issue's order; `all` is no filter. */
export const KINDS = [
  { key: 'all', label: 'All' },
  { key: 'dates', label: 'Date moved' },
  { key: 'closed', label: 'Closed/reopened' },
  { key: 'status', label: 'Status' },
  { key: 'priority', label: 'Priority' },
  { key: 'moved', label: 'Moved' },
  { key: 'comment', label: 'Comments' },
];

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function storedKind() {
  let k = null;
  try { k = localStorage.getItem(KIND_KEY); } catch (_) { /* private mode */ }
  return KINDS.some(function (x) { return x.key === k; }) ? k : 'all';
}

function dateWord(v) { return v ? fmtDay(v) : 'none'; }

/** One change in words: "Due 17 Aug → 20 Aug", "Moved to Home", "Comment: …". */
export function changeText(e) {
  switch (e.field) {
    case 'due': return 'Due ' + dateWord(e.old) + ' → ' + dateWord(e.new);
    case 'starts': return 'Start ' + dateWord(e.old) + ' → ' + dateWord(e.new);
    case 'done': return 'Completed, next due ' + dateWord(e.new);
    case 'parent': return 'Moved ' + (e.old_label || 'from the top level') + ' → ' + (e.new_label || 'the top level');
    case 'comment': return 'Comment: ' + (e.new || '');
    case 'created': return 'Created';
    case 'imported': return 'Imported';
    case 'description': return 'Notes edited';
    case 'title': return 'Renamed from ' + (e.old || '∅');
    case 'blocked_by': return e.new ? 'Blocked by ' + (e.new_label || e.new) : 'Unblocked from ' + (e.old_label || e.old);
    case 'blocks': return e.new ? 'Now blocks ' + (e.new_label || e.new) : 'No longer blocks ' + (e.old_label || e.old);
    default: {
      const w = fieldWords(e.field);
      return w.charAt(0).toUpperCase() + w.slice(1) + ' ' + (e.old == null || e.old === '' ? '∅' : e.old) + ' → ' + (e.new == null || e.new === '' ? '∅' : e.new);
    }
  }
}

function timeOf(ts) { return (ts || '').slice(11, 16); }

/**
 * @param {{onOpen: (id: number) => void, onHead: () => void}} opts
 * @returns {{show: () => void, hide: () => void, refresh: () => Promise<void>, headText: () => string}}
 */
export function mountHistory(opts) {
  const kindsHost = document.getElementById('historyKinds');
  const host = document.getElementById('historyHost');
  const st = { shown: false, kind: storedKind(), days: 1, feed: null, error: null, open: new Set(), seq: 0 };

  function renderKinds() {
    const counts = st.feed ? st.feed.counts : null;
    kindsHost.replaceChildren.apply(kindsHost, KINDS.map(function (k) {
      const b = el('button', 'button-surface history-kind');
      b.type = 'button';
      b.dataset.kind = k.key;
      b.dataset.track = 'history.kind';
      b.setAttribute('aria-pressed', String(k.key === st.kind));
      b.appendChild(el('span', null, k.label));
      if (counts && counts[k.key] != null) b.appendChild(el('span', 'history-kind-count', String(counts[k.key])));
      b.addEventListener('click', function () {
        if (st.kind === k.key) return;
        st.kind = k.key;
        try { localStorage.setItem(KIND_KEY, k.key); } catch (_) { /* private mode */ }
        st.open.clear();
        renderKinds();
        load();
      });
      return b;
    }));
  }

  function entryLine(e) {
    const li = el('li', 'history-entry');
    li.dataset.kind = e.kind;
    li.append(el('span', 'history-entry-text', changeText(e)), el('span', 'history-entry-time', timeOf(e.ts)));
    return li;
  }

  // A group is named by its day and place in it: one task can have several runs in a day, all in one second.
  function groupRow(day, g, at) {
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
    main.addEventListener('click', function () { opts.onOpen(g.task_id); });
    li.appendChild(main);
    const frag = [li];
    if (g.entries.length > 1) {
      const open = st.open.has(key);
      const toggle = el('button', 'icon-button action-row-verb history-expand');
      toggle.type = 'button';
      toggle.dataset.track = 'history.expand';
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' the ' + g.entries.length + ' changes');
      toggle.innerHTML = icon(open ? 'chevron-up' : 'chevron-down');
      toggle.addEventListener('click', function () {
        if (st.open.has(key)) st.open.delete(key); else st.open.add(key);
        render();
      });
      li.appendChild(toggle);
      if (open) {
        const detail = el('li', 'history-detail');
        const list = el('ul', 'history-entries');
        g.entries.forEach(function (e) { list.appendChild(entryLine(e)); });
        detail.appendChild(list);
        frag.push(detail);
      }
    }
    return frag;
  }

  function kindLabel() {
    const k = KINDS.find(function (x) { return x.key === st.kind; });
    return k && k.key !== 'all' ? k.label.toLowerCase() + ' ' : '';
  }

  function render() {
    const parts = [];
    if (st.error) {
      parts.push(emptyStateEl('triangle-alert', 'Could not read your history: ' + st.error, {
        actionLabel: 'Try again', onAction: load,
      }));
      host.dataset.state = 'error';
      host.replaceChildren.apply(host, parts);
      return;
    }
    const feed = st.feed;
    if (!feed) { host.dataset.state = 'loading'; host.replaceChildren(); return; }
    const today = todayISO();
    if (!feed.days.length) {
      const when = feed.from === feed.to ? (feed.to === today ? 'today' : 'on ' + fmtDay(feed.to)) : 'since ' + fmtDay(feed.from);
      parts.push(emptyStateEl('history', 'No ' + kindLabel() + 'changes ' + when, st.kind === 'all' ? undefined : {
        actionLabel: 'Show all changes', onAction: function () { kindsHost.querySelector('[data-kind="all"]').click(); },
      }));
      host.dataset.state = 'empty';
    } else {
      host.dataset.state = 'ok';
    }
    feed.days.forEach(function (d) {
      const head = el('h3', 'overline history-day-title', dayLabel(d.day, today));
      head.appendChild(el('span', 'history-day-count', d.count + (d.count === 1 ? ' change' : ' changes')));
      const card = el('section', 'card action-list history-day');
      card.dataset.day = d.day;
      const list = el('ul', 'action-rows');
      d.groups.forEach(function (g, at) { groupRow(d.day, g, at).forEach(function (n) { list.appendChild(n); }); });
      card.appendChild(list);
      parts.push(head, card);
    });
    const foot = el('div', 'history-foot');
    if (feed.older === false) {
      foot.appendChild(el('span', 'muted', 'That is everything — nothing changed before ' + fmtDay(feed.from)));
    } else if (st.days < MAX_DAYS) {
      const older = el('button', 'button-surface history-older', 'Show the day before');
      older.type = 'button';
      older.dataset.track = 'history.older';
      older.addEventListener('click', function () { older.disabled = true; st.days += 1; load(); });
      foot.appendChild(older);
    }
    parts.push(foot);
    host.replaceChildren.apply(host, parts);
  }

  async function load() {
    const seq = ++st.seq;
    const to = todayISO();
    try {
      const feed = await api('/api/history' + qs({ from: addDays(to, -(st.days - 1)), to: to, kind: st.kind }));
      if (seq !== st.seq) return;
      st.feed = feed;
      st.error = null;
    } catch (err) {
      if (seq !== st.seq) return;
      st.error = (err && err.message) || 'the server did not answer';
    }
    renderKinds();
    render();
    opts.onHead();
  }

  renderKinds();
  return {
    show: function () { st.shown = true; load(); },
    hide: function () { st.shown = false; },
    refresh: function () { return st.shown ? load() : Promise.resolve(); },
    headText: function () {
      if (st.error) return 'History unreadable';
      if (!st.feed) return '';
      const n = st.feed.counts.all;
      const span = st.days === 1 ? ' today' : ' in ' + st.days + ' days';
      return n + (n === 1 ? ' change' : ' changes') + span;
    },
  };
}
