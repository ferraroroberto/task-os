/* task-os — the Search tab: one box over four indexes (Step 10).
 *
 * `mountSearch(box, host, opts)` wires the box (`#searchInput` + `#searchMeta`)
 * and renders `GET /api/search?q=` into `host` as one collapsible group per
 * kind — Tasks · Folders · Emails · Issues, in that order, always all four:
 * a kind that is not configured on this install renders a quiet "not
 * configured — reason" row with a link to Settings (never a silent blank),
 * an errored one says so. Groups are the vendored disclosure, collapsed by
 * default and remembered per kind (issue #46): the summary carries the
 * count, so a closed group still tells you what it holds.
 *
 * Task hits are the ONE task row (rows.js) — the same row the Board shows,
 * plus the matched snippet as a third line — filtered and sorted by the
 * shared filter card (`opts.filters()`; status · project · person · due ·
 * modified · sort). Folder / email / issue hits: the title IS the link
 * (a taskos:// opener link for folders and .msg files, the issue URL),
 * then Attach (to the task open in the drawer) and New task. No separate
 * "Open" button anywhere.
 * Keyboard: ↓ from the box focuses the first row; on rows ↑↓ move, Enter opens,
 * `a` attaches, `n` creates, Esc / `/` go back to the box.
 *
 * Debounce 200 ms; a stale answer (an older query resolving late) is dropped.
 * The URL (?q=) is the caller's job (`opts.onQuery`).
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { api } from './api.js';
import { escapeHtml, folderChip } from './format.js';
import { matchesFilters } from './filters.js';
import { sortItems, taskRow } from './rows.js';
import { toast } from './toast.js';

const KINDS = [
  { kind: 'tasks', label: 'Tasks', icon: 'list-checks' },
  { kind: 'folders', label: 'Folders', icon: 'folder' },
  { kind: 'emails', label: 'Emails', icon: 'mail' },
  { kind: 'issues', label: 'Issues', icon: 'github' },
];
const DEBOUNCE_MS = 200;
const LIMIT = 20;
const OPEN_KEY = 'task-os.search.open';

/** `[match]` marks → <mark>, everything else escaped. */
export function markHtml(text) {
  return escapeHtml(text).replace(/\[([^\[\]]+)\]/g, '<mark>$1</mark>');
}

function loadOpen() {
  try { return JSON.parse(localStorage.getItem(OPEN_KEY) || '{}') || {}; } catch (_) { return {}; }
}
function saveOpen(map) {
  try { localStorage.setItem(OPEN_KEY, JSON.stringify(map)); } catch (_) { /* private mode */ }
}

/**
 * @param {HTMLElement} box   the search card (holds #searchInput + #searchMeta)
 * @param {HTMLElement} host  where the result groups render
 * @param {{onOpenTask: (id:number) => void, currentTaskId: () => (number|null),
 *          onTaskChanged: (id:number) => void, onCreated: (task:any) => void,
 *          onQuery: (q:string) => void, filters: () => object,
 *          onStatus: (id:number, status:string) => Promise<any>}} opts
 */
export function mountSearch(box, host, opts) {
  const input = box.querySelector('#searchInput');
  const meta = box.querySelector('#searchMeta');
  let timer = null;
  let seq = 0;
  let last = null;        // the last rendered result
  let status = null;      // /api/search/status → adapters (idle view)
  const openState = loadOpen();
  const hitByIdx = new Map();

  // ------------------------------------------------------------ fetch
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(function () { run(input.value); }, DEBOUNCE_MS);
  }

  async function run(raw) {
    const q = String(raw || '').trim();
    opts.onQuery(q);
    const my = ++seq;
    if (!q) { last = null; renderIdle(); return; }
    meta.textContent = 'searching…';
    let res;
    try {
      res = await api('/api/search?q=' + encodeURIComponent(q) + '&limit=' + LIMIT);
    } catch (err) {
      if (my !== seq) return;
      meta.textContent = 'search failed';
      host.replaceChildren(errCard(err.message || 'Search failed'));
      return;
    }
    if (my !== seq) return;               // a newer query is in flight / rendered
    last = res;
    render(res);
  }

  async function loadStatus() {
    try { status = (await api('/api/search/status')).adapters || []; } catch (_) { status = null; }
    if (!input.value.trim()) renderIdle();
  }

  // ----------------------------------------------------------- render
  function errCard(message) {
    const c = document.createElement('div');
    c.className = 'card search-group';
    const p = document.createElement('p');
    p.className = 'search-err';
    p.textContent = message;
    c.appendChild(p);
    return c;
  }

  function note(cls, text) {
    const p = document.createElement('p');
    p.className = cls;
    p.textContent = text;
    return p;
  }

  function offRow(p, reason) {
    p.textContent = 'not configured — ' + (reason || 'unknown') + ' · ';
    const a = document.createElement('a');
    a.href = '#settings/search';
    a.textContent = 'Settings';
    p.appendChild(a);
  }

  /** One collapsible group (vendored disclosure), remembered open / closed per kind. */
  function groupCard(k, countText) {
    const card = document.createElement('details');
    card.className = 'card card--collapsible search-group';
    card.dataset.kind = k.kind;
    card.open = !!openState[k.kind];
    card.addEventListener('toggle', function () { openState[k.kind] = card.open; saveOpen(openState); });
    const summary = document.createElement('summary');
    summary.className = 'collapse-summary';
    const main = document.createElement('span');
    main.className = 'collapse-main';
    main.innerHTML = icon(k.icon);
    const h = document.createElement('h3');
    h.className = 'collapse-title';
    h.textContent = k.label;
    main.appendChild(h);
    const count = document.createElement('span');
    count.className = 'collapse-count search-group-count';
    count.textContent = countText || '';
    main.appendChild(count);
    summary.appendChild(main);
    const chev = document.createElement('span');
    chev.className = 'collapse-chevron';
    chev.setAttribute('aria-hidden', 'true');
    chev.textContent = '›';
    summary.appendChild(chev);
    card.appendChild(summary);
    const body = document.createElement('div');
    body.className = 'collapse-body search-body';
    card.appendChild(body);
    return card;
  }

  function renderIdle() {
    meta.textContent = '';
    hitByIdx.clear();
    const wrap = document.createElement('div');
    wrap.className = 'search-groups';
    KINDS.forEach(function (k) {
      const st = (status || []).find(function (a) { return a.kind === k.kind; });
      const card = groupCard(k, !status ? '' : (st && st.configured ? 'ready' : 'not configured'));
      const body = card.querySelector('.search-body');
      if (!status) body.appendChild(note('search-none muted', 'Type to search.'));
      else if (st && st.configured) body.appendChild(note('search-none muted', 'Type to search' + (st.note ? ' — ' + st.note : '') + '.'));
      else { const p = note('search-off muted', ''); offRow(p, st ? st.reason : 'unknown'); body.appendChild(p); }
      wrap.appendChild(card);
    });
    host.replaceChildren(wrap);
  }

  function taskHits(g) {
    const f = opts.filters ? opts.filters() : null;
    const tasks = (g.hits || []).map(function (h) {
      const t = Object.assign({}, h.task || {}, { id: h.task_id, _hit: h });
      if (!t.title) t.title = h.title;
      return t;
    });
    const kept = f ? tasks.filter(function (t) { return matchesFilters(t, f); }) : tasks;
    return f ? sortItems(kept, f.sort) : kept;
  }

  function render(res) {
    hitByIdx.clear();
    let total = 0;
    const wrap = document.createElement('div');
    wrap.className = 'search-groups';
    let idx = 0;
    KINDS.forEach(function (k) {
      const g = res.groups.find(function (x) { return x.kind === k.kind; }) || { kind: k.kind, configured: false, reason: 'no answer', hits: [] };
      let countText = '';
      let rows = null;
      if (g.configured && !g.error) {
        if (k.kind === 'tasks') {
          rows = taskHits(g);
          countText = rows.length === (g.hits || []).length ? rows.length + ' hit' + (rows.length === 1 ? '' : 's')
            : rows.length + ' of ' + g.hits.length + ' hit' + (g.hits.length === 1 ? '' : 's');
          total += rows.length;
        } else {
          countText = g.count + ' hit' + (g.count === 1 ? '' : 's');
          total += g.count || 0;
        }
        if (g.note) countText += ' · ' + g.note;
      } else if (!g.configured) countText = 'not configured';
      else countText = 'error';
      const card = groupCard(k, countText);
      const body = card.querySelector('.search-body');
      if (!g.configured) {
        const p = note('search-off muted', '');
        offRow(p, g.reason);
        body.appendChild(p);
      } else if (g.error) {
        body.appendChild(note('search-err', 'error — ' + g.error));
      } else if (k.kind === 'tasks') {
        if (!rows.length) body.appendChild(note('search-none muted', g.hits.length ? 'No task matches the filters.' : 'No tasks match.'));
        else {
          const ul = document.createElement('ul');
          ul.className = 'trows search-hits';
          ul.setAttribute('role', 'list');
          rows.forEach(function (t) { ul.appendChild(taskHitRow(t, idx++)); });
          body.appendChild(ul);
        }
      } else if (!g.hits.length) {
        body.appendChild(note('search-none muted', 'No ' + k.label.toLowerCase() + ' match.'));
      } else {
        const ul = document.createElement('ul');
        ul.className = 'search-hits';
        ul.setAttribute('role', 'list');
        g.hits.forEach(function (h) { ul.appendChild(hitRow(h, k, idx++)); });
        body.appendChild(ul);
      }
      wrap.appendChild(card);
    });
    meta.textContent = total + ' hit' + (total === 1 ? '' : 's');
    host.replaceChildren(wrap);
  }

  /** A task hit = the shared row + the matched snippet under it. */
  function taskHitRow(t, idx) {
    const h = t._hit;
    let extra = null;
    const snippet = h.snippet || '';
    const snippetIsTitle = snippet && snippet.replace(/[\[\]]/g, '') === t.title;
    if (snippet && !snippetIsTitle) {
      extra = document.createElement('div');
      extra.className = 'search-hit-snippet';
      extra.innerHTML = (h.matched_in ? '<span class="muted">' + escapeHtml(h.matched_in) + ': </span>' : '') + markHtml(snippet);
    }
    const li = taskRow(t, { onOpen: opts.onOpenTask, onStatus: opts.onStatus }, extra ? { extra: extra } : undefined);
    li.classList.add('search-hit');
    li.dataset.kind = 'tasks';
    li.dataset.idx = String(idx);
    if (snippetIsTitle) li.querySelector('.trow-title').innerHTML = markHtml(snippet);
    hitByIdx.set(idx, h);
    li.addEventListener('focusin', function () { li.classList.add('is-active'); });
    li.addEventListener('focusout', function () { li.classList.remove('is-active'); });
    return li;
  }

  function hitRow(h, k, idx) {
    const li = document.createElement('li');
    li.className = 'search-hit';
    li.dataset.kind = h.kind;
    li.dataset.idx = String(idx);
    li.tabIndex = -1;
    hitByIdx.set(idx, h);
    li.innerHTML = icon(k.icon, 'search-hit-icon');
    const main = document.createElement('div');
    main.className = 'search-hit-main';
    // The title IS the link (a taskos:// opener link for folders / .msg files,
    // the issue URL); it carries the <mark>s when the snippet *is* the title.
    const snippet = h.snippet || '';
    const snippetIsTitle = snippet && snippet.replace(/[\[\]]/g, '') === h.title;
    const title = document.createElement('div');
    title.className = 'search-hit-title';
    let link;
    if (h.kind === 'folders' || h.kind === 'emails') {
      link = folderChip(h.ref, { resolved: h.path || null, label: h.title, icon: h.kind === 'emails' ? 'mail' : 'folder' });
      link.classList.add('search-hit-link');
      link.title = (h.kind === 'emails' ? 'Open the .msg on this PC — ' : 'Open the folder on this PC — ') + (h.path || h.ref);
      link.dataset.act = 'open';
      if (snippetIsTitle) { const lbl = link.querySelector('.chip-label'); if (lbl) lbl.innerHTML = markHtml(snippet); }
    } else {
      link = document.createElement('a');
      link.className = 'search-hit-link';
      link.href = h.url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.dataset.act = 'open';
      if (snippetIsTitle) link.innerHTML = markHtml(snippet); else link.textContent = h.title;
      link.addEventListener('click', function (ev) { ev.stopPropagation(); });
    }
    title.appendChild(link);
    main.appendChild(title);
    if (h.subtitle) {
      const sub = document.createElement('div');
      sub.className = 'search-hit-sub';
      sub.textContent = h.subtitle;
      main.appendChild(sub);
    }
    if (snippet && !snippetIsTitle) {
      const sn = document.createElement('div');
      sn.className = 'search-hit-snippet';
      sn.innerHTML = (h.matched_in ? '<span class="muted">' + escapeHtml(h.matched_in) + ': </span>' : '') + markHtml(snippet);
      main.appendChild(sn);
    }
    li.appendChild(main);
    li.appendChild(actions(h));
    li.addEventListener('focus', function () { li.classList.add('is-active'); });
    li.addEventListener('blur', function () { li.classList.remove('is-active'); });
    return li;
  }

  function ghost(label, iconName, title) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button-ghost search-act';
    b.innerHTML = icon(iconName) + ' ' + label;
    if (title) b.title = title;
    return b;
  }

  function actions(h) {
    const row = document.createElement('div');
    row.className = 'search-hit-actions';
    if (h.kind === 'issues' && h.task_id != null) {
      const t = ghost('Task #' + h.task_id, 'list-checks', 'Open the linked task');
      t.dataset.act = 'task';
      t.addEventListener('click', function (ev) { ev.stopPropagation(); opts.onOpenTask(h.task_id); });
      row.appendChild(t);
      return row;               // already a task: no attach / new
    }
    const attach = ghost('Attach', 'link', 'Attach to the task open in the drawer (a)');
    attach.dataset.act = 'attach';
    attach.disabled = opts.currentTaskId() == null;
    attach.addEventListener('click', function (ev) { ev.stopPropagation(); attachHit(h).catch(function () {}); });
    row.appendChild(attach);
    const create = ghost('New task', 'plus', 'Create a task from this (n)');
    create.dataset.act = 'new';
    create.addEventListener('click', function (ev) { ev.stopPropagation(); createFrom(h).catch(function () {}); });
    row.appendChild(create);
    return row;
  }

  // ------------------------------------------------------------ actions
  function primary(li) {
    const h = hitByIdx.get(Number(li.dataset.idx));
    if (!h) return;
    if (h.kind === 'tasks') { opts.onOpenTask(h.task_id); return; }
    const open = li.querySelector('[data-act="open"]');
    if (open) open.click();
  }

  async function attachHit(h) {
    const tid = opts.currentTaskId();
    if (tid == null) { toast('Open a task first — Attach adds to the task in the drawer', 'error'); return; }
    try {
      if (h.kind === 'folders') {
        const t = await api('/api/tasks/' + tid);
        if (!t.folder_ref) {
          await api('/api/tasks/' + tid, { method: 'PATCH', body: { folder_ref: h.ref } });
          toast('Folder set on #' + tid + ': ' + h.ref, 'success');
        } else {
          await api('/api/tasks/' + tid + '/links', { method: 'POST', body: { url: h.ref, label: h.name || h.title, kind: 'folder' } });
          toast('Folder link added to #' + tid + ' (it already had a folder)', 'success');
        }
      } else if (h.kind === 'emails') {
        await api('/api/tasks/' + tid + '/links', { method: 'POST', body: { url: h.ref, label: h.title, kind: 'email' } });
        toast('Email attached to #' + tid + ': ' + h.title, 'success');
      } else if (h.kind === 'issues') {
        await api('/api/tasks/' + tid + '/issue', { method: 'PUT', body: { provider: h.provider, repo: h.repo, number: h.number, url: h.url, state: h.state } });
        toast('Linked ' + h.ref + ' to #' + tid, 'success');
      } else {
        return;
      }
      opts.onTaskChanged(tid);
      if (last) render(last);       // re-render so a linked issue row flips to "Task #N"
    } catch (err) {
      toast(err.message || 'Attach failed', 'error');
      throw err;
    }
  }

  async function createFrom(h) {
    let task = null;
    try {
      if (h.kind === 'folders') {
        task = await api('/api/tasks', { method: 'POST', body: { title: h.name || h.title, folder_ref: h.ref } });
      } else if (h.kind === 'emails') {
        const when = h.date ? String(h.date).slice(0, 10) : '';
        const desc = 'From email: ' + (h.sender || 'unknown sender') + (when ? ' · ' + when : '') + '\n' + h.ref;
        task = await api('/api/tasks', { method: 'POST', body: { title: h.title, description: desc } });
        await api('/api/tasks/' + task.id + '/links', { method: 'POST', body: { url: h.ref, label: h.title, kind: 'email' } });
      } else if (h.kind === 'issues') {
        const short = String(h.repo || '').split('/').pop() + '#' + h.number;
        task = await api('/api/tasks', { method: 'POST', body: { title: h.title, code: short } });
        await api('/api/tasks/' + task.id + '/links', { method: 'POST', body: { url: h.url, label: h.ref, kind: 'issue' } });
        task = await api('/api/tasks/' + task.id + '/issue', { method: 'PUT', body: { provider: h.provider, repo: h.repo, number: h.number, url: h.url, state: h.state } });
      } else {
        return;
      }
      toast('Task #' + task.id + ' created: ' + task.title, 'success');
      opts.onCreated(task);
      if (last) render(last);
    } catch (err) {
      toast(err.message || 'Could not create the task', 'error');
      throw err;
    }
  }

  // ---------------------------------------------------------- keyboard
  function rows() { return Array.prototype.slice.call(host.querySelectorAll('.search-hit')); }
  function focusRow(li) {
    if (!li) return;
    const main = li.querySelector('.trow-main');
    if (main) main.focus(); else li.focus();
  }

  input.addEventListener('input', schedule);
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown') {
      const r = rows();
      if (r.length) { ev.preventDefault(); focusRow(r[0]); }
    } else if (ev.key === 'Enter') {
      clearTimeout(timer);
      const r = rows();
      if (input.value.trim() && last && r.length) { ev.preventDefault(); primary(r[0]); }
      else run(input.value);
    } else if (ev.key === 'Escape') {
      if (input.value) { input.value = ''; run(''); }
    }
  });
  host.addEventListener('keydown', function (ev) {
    const li = ev.target.closest('.search-hit');
    if (!li || ev.target.closest('input, textarea, select')) return;
    const r = rows();
    const i = r.indexOf(li);
    if (ev.key === 'ArrowDown') { ev.preventDefault(); focusRow(r[i + 1] || r[i]); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (i === 0) input.focus(); else focusRow(r[i - 1]); }
    else if (ev.key === 'Home') { ev.preventDefault(); focusRow(r[0]); }
    else if (ev.key === 'End') { ev.preventDefault(); focusRow(r[r.length - 1]); }
    else if (ev.key === 'Enter') { if (ev.target.closest('.trow-main')) return; ev.preventDefault(); primary(li); }
    else if (ev.key === 'a' || ev.key === 'A') { const b = li.querySelector('[data-act="attach"]'); if (b && !b.disabled) { ev.preventDefault(); b.click(); } }
    else if (ev.key === 'n' || ev.key === 'N') { const b = li.querySelector('[data-act="new"]'); if (b) { ev.preventDefault(); b.click(); } }
    else if (ev.key === 'Escape' || ev.key === '/') { ev.preventDefault(); input.focus(); input.select(); }
  });
  host.addEventListener('click', function (ev) {
    // a plain hit row (folder / email / issue): the row body opens, like a task row
    const li = ev.target.closest('.search-hit');
    if (!li || li.classList.contains('trow') || ev.target.closest('a, button, select, summary')) return;
    primary(li);
  });

  loadStatus();
  renderIdle();

  return {
    /** Set the box and run (used by the ?q= deep link and the palette). */
    setQuery(q) { input.value = q || ''; clearTimeout(timer); run(input.value); },
    getQuery() { return input.value.trim(); },
    focus() { input.focus(); input.select(); },
    /** The drawer opened / closed: the Attach buttons follow. */
    refreshActions() {
      const on = opts.currentTaskId() != null;
      host.querySelectorAll('[data-act="attach"]').forEach(function (b) { b.disabled = !on; });
    },
    /** The shared filters changed: re-apply them to the task hits. */
    refilter() { if (last) render(last); },
    reloadStatus: loadStatus,
  };
}
