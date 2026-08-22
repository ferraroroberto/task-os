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
 * Every hit is the ONE task row shape (rows.js, #48): a title line and one
 * muted meta line, no glyphs, no buttons.
 *   tasks    the shared row itself (status select, meta line) + the matched
 *            snippet, filtered and sorted by the shared filter card
 *   folders  name · full path — the title is a taskos:// link the per-PC
 *            opener opens on a PC; on the phone it shows the path to copy
 *   emails   subject · sender · date · folder — same link, the .msg opens
 *   issues   title · repo#N · state — the title opens the linked task when
 *            there is one, else the issue page
 * Keyboard: ↓ from the box focuses the first row; on rows ↑↓ move, Enter
 * opens, Esc / `/` go back to the box.
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
 * @param {{onOpenTask: (id:number) => void, onQuery: (q:string) => void,
 *          filters: () => object, onStatus: (id:number, status:string) => Promise<any>}} opts
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
        ul.className = 'trows search-hits';
        ul.setAttribute('role', 'list');
        g.hits.forEach(function (h) { ul.appendChild(hitRow(h, idx++)); });
        body.appendChild(ul);
      }
      wrap.appendChild(card);
    });
    meta.textContent = total + ' hit' + (total === 1 ? '' : 's');
    host.replaceChildren(wrap);
  }

  function snippetLine(h, title) {
    const snippet = h.snippet || '';
    if (!snippet || snippet.replace(/[\[\]]/g, '') === title) return null;
    const el = document.createElement('div');
    el.className = 'search-hit-snippet';
    el.innerHTML = (h.matched_in ? '<span class="muted">' + escapeHtml(h.matched_in) + ': </span>' : '') + markHtml(snippet);
    return el;
  }

  /** A task hit = the shared row + the matched snippet under it. */
  function taskHitRow(t, idx) {
    const h = t._hit;
    const extra = snippetLine(h, t.title);
    const li = taskRow(t, { onOpen: opts.onOpenTask, onStatus: opts.onStatus }, extra ? { extra: extra } : undefined);
    li.classList.add('search-hit');
    li.dataset.kind = 'tasks';
    li.dataset.idx = String(idx);
    const snippet = h.snippet || '';
    if (snippet && snippet.replace(/[\[\]]/g, '') === t.title) li.querySelector('.trow-title').innerHTML = markHtml(snippet);
    hitByIdx.set(idx, h);
    return li;
  }

  /** A folder / email / issue hit in the same row shape: title line + meta line. */
  function hitRow(h, idx) {
    const li = document.createElement('li');
    li.className = 'trow search-hit';
    li.dataset.kind = h.kind;
    li.dataset.idx = String(idx);
    hitByIdx.set(idx, h);
    const main = document.createElement('div');
    main.className = 'trow-main';
    main.setAttribute('role', 'button');
    main.tabIndex = 0;
    const title = document.createElement('span');
    title.className = 'trow-title';
    const snippet = h.snippet || '';
    const snippetIsTitle = snippet && snippet.replace(/[\[\]]/g, '') === h.title;
    let link;
    if (h.kind === 'folders' || h.kind === 'emails') {
      // the title IS the opener link (a PC opens Explorer / the .msg; the
      // phone gets the path-to-copy popover — folderChip's own rule)
      link = folderChip(h.ref, { resolved: h.path || null, label: h.kind === 'folders' ? (h.name || h.title) : h.title });
      link.classList.add('search-hit-link');
      link.title = (h.kind === 'emails' ? 'Open the .msg on this PC — ' : 'Open the folder on this PC — ') + (h.path || h.ref);
      link.dataset.act = 'open';
      if (snippetIsTitle && h.kind === 'emails') { const lbl = link.querySelector('.chip-label'); if (lbl) lbl.innerHTML = markHtml(snippet); }
    } else if (h.task_id != null) {
      // an issue already on the list: the title opens its task (the issue
      // chip inside the task is the forge link)
      link = document.createElement('a');
      link.className = 'search-hit-link';
      link.href = '#task/' + h.task_id;
      link.dataset.act = 'open';
      if (snippetIsTitle) link.innerHTML = markHtml(snippet); else link.textContent = h.title;
      link.addEventListener('click', function (ev) { ev.preventDefault(); ev.stopPropagation(); opts.onOpenTask(h.task_id); });
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
    li.appendChild(main);

    const metaLine = document.createElement('span');
    metaLine.className = 'trow-meta';
    const bits = [];
    if (h.kind === 'folders') bits.push(h.path || h.ref);
    else if (h.kind === 'emails') {
      if (h.sender) bits.push(h.sender);
      if (h.date) bits.push(String(h.date).slice(0, 10));
      if (h.folder) bits.push(h.folder);
    } else {
      if (h.ref) bits.push(h.ref);
      if (h.state) bits.push(h.state);
      if (h.task_id != null) bits.push('task #' + h.task_id);
    }
    // a snippet that is just the path (a folder hit) marks the path on the
    // meta line instead of repeating it underneath
    const plain = (h.snippet || '').replace(/[\[\]]/g, '');
    const snippetIsPath = plain && bits.length && plain === bits[0];
    bits.forEach(function (b, i) {
      const s = document.createElement('span');
      s.className = 'search-hit-meta';
      if (i === 0 && snippetIsPath) s.innerHTML = markHtml(h.snippet); else s.textContent = b;
      s.title = b;
      metaLine.appendChild(s);
    });
    if (metaLine.childNodes.length) li.appendChild(metaLine);
    const sn = snippetIsPath ? null : snippetLine(h, h.title);
    if (sn) { sn.classList.add('trow-extra'); li.appendChild(sn); }

    // the whole row opens, like a task row; the link element carries the real href
    function openIt(ev) {
      if (ev.target.closest('a')) return;
      link.click();
    }
    main.addEventListener('click', openIt);
    metaLine.addEventListener('click', openIt);
    main.addEventListener('keydown', function (ev) {
      if (ev.target !== main) return;
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); link.click(); }
    });
    return li;
  }

  // ------------------------------------------------------------ actions
  function primary(li) {
    const h = hitByIdx.get(Number(li.dataset.idx));
    if (!h) return;
    if (h.kind === 'tasks') { opts.onOpenTask(h.task_id); return; }
    const open = li.querySelector('[data-act="open"]');
    if (open) open.click();
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
    else if (ev.key === 'Escape' || ev.key === '/') { ev.preventDefault(); input.focus(); input.select(); }
  });

  loadStatus();
  renderIdle();

  return {
    /** Set the box and run (used by the ?q= deep link and the palette). */
    setQuery(q) { input.value = q || ''; clearTimeout(timer); run(input.value); },
    getQuery() { return input.value.trim(); },
    focus() { input.focus(); input.select(); },
    /** Kept for the caller: rows carry no per-task actions any more (#48). */
    refreshActions() { /* no-op */ },
    /** The shared filters changed: re-apply them to the task hits. */
    refilter() { if (last) render(last); },
    reloadStatus: loadStatus,
  };
}
