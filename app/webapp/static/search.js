/* task-os — the Search tab: one box over four indexes (Step 10).
 *
 * `mountSearch(box, host, opts)` wires the box (`#searchInput` + `#searchMeta`)
 * and renders `GET /api/search?q=` into `host` as one card per kind — Tasks ·
 * Folders · Emails · Issues, in that order, always all four: a kind that is
 * not configured on this install renders a quiet "not configured — reason"
 * row with a link to Settings (never a silent blank), an errored one says so.
 *
 * Each hit row: kind glyph · title · subtitle · snippet with <mark> around the
 * matched terms (the server marks them `[like this]`) · actions:
 *   Open    task → the drawer · folder / email → a taskos:// opener chip
 *           (the per-PC opener opens the folder / the .msg) · issue → its URL
 *   Attach  to the task open in the drawer: folder → the task's folder_ref (or
 *           a folder link when it already has one) · email → links(kind=email,
 *           url=<file ref>, label=subject) · issue → link existing (PUT …/issue)
 *   New     a task from it: folder → title = folder name + folder_ref · email →
 *           title = subject, description "From email …", the email link · issue →
 *           title = issue title, code repo#N, the issue link + ref
 * Keyboard: ↓ from the box focuses the first row; on rows ↑↓ move, Enter opens,
 * `a` attaches, `n` creates, Esc / `/` go back to the box.
 *
 * Debounce 200 ms; a stale answer (an older query resolving late) is dropped.
 * The URL (?q=) is the caller's job (`opts.onQuery`).
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { api } from './api.js';
import { escapeHtml, folderChip, statusPill } from './format.js';
import { toast } from './toast.js';

const KINDS = [
  { kind: 'tasks', label: 'Tasks', icon: 'list-checks' },
  { kind: 'folders', label: 'Folders', icon: 'folder' },
  { kind: 'emails', label: 'Emails', icon: 'mail' },
  { kind: 'issues', label: 'Issues', icon: 'github' },
];
const DEBOUNCE_MS = 200;
const LIMIT = 20;

/** `[match]` marks → <mark>, everything else escaped. */
export function markHtml(text) {
  return escapeHtml(text).replace(/\[([^\[\]]+)\]/g, '<mark>$1</mark>');
}

/**
 * @param {HTMLElement} box   the search card (holds #searchInput + #searchMeta)
 * @param {HTMLElement} host  where the result groups render
 * @param {{onOpenTask: (id:number) => void, currentTaskId: () => (number|null),
 *          onTaskChanged: (id:number) => void, onCreated: (task:any) => void,
 *          onQuery: (q:string) => void}} opts
 */
export function mountSearch(box, host, opts) {
  const input = box.querySelector('#searchInput');
  const meta = box.querySelector('#searchMeta');
  let timer = null;
  let seq = 0;
  let last = null;        // the last rendered result
  let status = null;      // /api/search/status → adapters (idle view)

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

  function renderIdle() {
    meta.textContent = '';
    const wrap = document.createElement('div');
    wrap.className = 'search-groups';
    KINDS.forEach(function (k) {
      const st = (status || []).find(function (a) { return a.kind === k.kind; });
      const card = groupCard(k, null);
      const body = document.createElement('p');
      if (!status) { body.className = 'search-none muted'; body.textContent = 'Type to search.'; }
      else if (st && st.configured) { body.className = 'search-none muted'; body.textContent = 'Type to search' + (st.note ? ' — ' + st.note : '') + '.'; }
      else { body.className = 'search-off muted'; offRow(body, st ? st.reason : 'unknown'); }
      card.appendChild(body);
      wrap.appendChild(card);
    });
    host.replaceChildren(wrap);
  }

  function offRow(p, reason) {
    p.textContent = 'not configured — ' + (reason || 'unknown') + ' · ';
    const a = document.createElement('a');
    a.href = '#settings/search';
    a.textContent = 'Settings';
    p.appendChild(a);
  }

  function groupCard(k, group) {
    const card = document.createElement('section');
    card.className = 'card search-group';
    card.dataset.kind = k.kind;
    const head = document.createElement('h2');
    head.className = 'search-group-head';
    head.innerHTML = icon(k.icon);
    const label = document.createElement('span');
    label.textContent = k.label;
    head.appendChild(label);
    const count = document.createElement('span');
    count.className = 'search-group-count';
    if (group && group.configured && !group.skipped) count.textContent = '(' + group.count + ')';
    head.appendChild(count);
    if (group && group.note) {
      const note = document.createElement('span');
      note.className = 'search-group-note muted';
      note.textContent = group.note;
      head.appendChild(note);
    }
    if (group && group.configured && group.took_ms != null) {
      const took = document.createElement('span');
      took.className = 'search-group-took';
      took.textContent = group.took_ms + ' ms';
      head.appendChild(took);
    }
    card.appendChild(head);
    return card;
  }

  function render(res) {
    const total = res.groups.reduce(function (n, g) { return n + (g.count || 0); }, 0);
    meta.textContent = total + ' hit' + (total === 1 ? '' : 's') + ' · ' + res.took_ms + ' ms';
    const wrap = document.createElement('div');
    wrap.className = 'search-groups';
    let idx = 0;
    KINDS.forEach(function (k) {
      const g = res.groups.find(function (x) { return x.kind === k.kind; }) || { kind: k.kind, configured: false, reason: 'no answer', hits: [] };
      const card = groupCard(k, g);
      if (!g.configured) {
        const p = document.createElement('p');
        p.className = 'search-off muted';
        offRow(p, g.reason);
        card.appendChild(p);
      } else if (g.error) {
        const p = document.createElement('p');
        p.className = 'search-err';
        p.textContent = 'error — ' + g.error;
        card.appendChild(p);
      } else if (!g.hits.length) {
        const p = document.createElement('p');
        p.className = 'search-none muted';
        p.textContent = 'No ' + k.label.toLowerCase() + ' match.';
        card.appendChild(p);
      } else {
        const ul = document.createElement('ul');
        ul.className = 'search-hits';
        ul.setAttribute('role', 'list');
        g.hits.forEach(function (h) { ul.appendChild(hitRow(h, k, idx++)); });
        card.appendChild(ul);
      }
      wrap.appendChild(card);
    });
    host.replaceChildren(wrap);
  }

  function hitRow(h, k, idx) {
    const li = document.createElement('li');
    li.className = 'search-hit';
    li.dataset.kind = h.kind;
    li.dataset.idx = String(idx);
    li.tabIndex = -1;
    li.innerHTML = icon(k.icon, 'search-hit-icon');
    const main = document.createElement('div');
    main.className = 'search-hit-main';
    // The title carries the <mark>s when the snippet *is* the title (a subject
    // / title hit); otherwise the snippet gets its own line under it.
    const snippet = h.snippet || '';
    const snippetIsTitle = snippet && snippet.replace(/[\[\]]/g, '') === h.title;
    const title = document.createElement('div');
    title.className = 'search-hit-title';
    const text = document.createElement('span');
    text.className = 'search-hit-text';
    if (snippetIsTitle) text.innerHTML = markHtml(snippet); else text.textContent = h.title;
    title.appendChild(text);
    if (h.kind === 'tasks' && h.status) title.appendChild(statusPill(h.status));
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
    li.appendChild(actions(h, li));
    main.addEventListener('click', function () { primary(h, li); });
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

  function actions(h, li) {
    const row = document.createElement('div');
    row.className = 'search-hit-actions';
    if (h.kind === 'tasks') {
      const open = ghost('Open', 'external-link', 'Open the task (Enter)');
      open.dataset.act = 'open';
      open.addEventListener('click', function (ev) { ev.stopPropagation(); opts.onOpenTask(h.task_id); });
      row.appendChild(open);
      return row;
    }
    if (h.kind === 'folders' || h.kind === 'emails') {
      const chip = folderChip(h.ref, {
        resolved: h.path || null, label: 'Open', icon: h.kind === 'emails' ? 'mail' : 'folder',
      });
      chip.classList.add('search-open');
      chip.dataset.act = 'open';
      chip.title = (h.kind === 'emails' ? 'Open the .msg on this PC — ' : 'Open the folder on this PC — ') + (h.path || h.ref);
      row.appendChild(chip);
    } else if (h.kind === 'issues') {
      const a = document.createElement('a');
      a.className = 'button-ghost search-act search-open';
      a.href = h.url;
      a.target = '_blank';
      a.rel = 'noopener';
      a.dataset.act = 'open';
      a.innerHTML = icon('external-link') + ' Open';
      a.addEventListener('click', function (ev) { ev.stopPropagation(); });
      row.appendChild(a);
      if (h.task_id != null) {
        const t = ghost('Task #' + h.task_id, 'list-checks', 'Open the linked task');
        t.dataset.act = 'task';
        t.addEventListener('click', function (ev) { ev.stopPropagation(); opts.onOpenTask(h.task_id); });
        row.appendChild(t);
        return row;               // already a task: no attach / new
      }
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
  function primary(h, li) {
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

  input.addEventListener('input', schedule);
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown') {
      const r = rows();
      if (r.length) { ev.preventDefault(); r[0].focus(); }
    } else if (ev.key === 'Enter') {
      clearTimeout(timer);
      const r = rows();
      if (input.value.trim() && last && r.length) { ev.preventDefault(); r[0].querySelector('.search-hit-main').click(); }
      else run(input.value);
    } else if (ev.key === 'Escape') {
      if (input.value) { input.value = ''; run(''); }
    }
  });
  host.addEventListener('keydown', function (ev) {
    const li = ev.target.closest('.search-hit');
    if (!li || ev.target.closest('input, textarea')) return;
    const r = rows();
    const i = r.indexOf(li);
    if (ev.key === 'ArrowDown') { ev.preventDefault(); (r[i + 1] || r[i]).focus(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (i === 0) input.focus(); else r[i - 1].focus(); }
    else if (ev.key === 'Home') { ev.preventDefault(); r[0].focus(); }
    else if (ev.key === 'End') { ev.preventDefault(); r[r.length - 1].focus(); }
    else if (ev.key === 'Enter') { ev.preventDefault(); li.querySelector('.search-hit-main').click(); }
    else if (ev.key === 'a' || ev.key === 'A') { const b = li.querySelector('[data-act="attach"]'); if (b && !b.disabled) { ev.preventDefault(); b.click(); } }
    else if (ev.key === 'n' || ev.key === 'N') { const b = li.querySelector('[data-act="new"]'); if (b) { ev.preventDefault(); b.click(); } }
    else if (ev.key === 'Escape' || ev.key === '/') { ev.preventDefault(); input.focus(); input.select(); }
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
    reloadStatus: loadStatus,
  };
}
