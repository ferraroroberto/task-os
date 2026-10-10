/* task-os — the Search tab: one box over four indexes (Step 10).
 *
 * `mountSearch(box, host, opts)` wires the box (`#searchInput` + `#searchMeta`)
 * and renders `GET /api/search?q=` into `host` (#395, the full-app review's
 * Search plan):
 *   before a query   one hint line naming what the box searches, and the
 *                    kinds this install has not set up folded into one line
 *                    with a link to Settings — no group shells waiting empty
 *   with a query     one group per kind that has hits, Tasks · Folders ·
 *                    Emails · Issues in that order, each a flat section headed
 *                    by an `overline` with its count (the shared section
 *                    header, #391), open; every kind without hits — none
 *                    matched, all hidden by the filters or the scope, not set
 *                    up — folds into ONE line under them, so nothing goes
 *                    silent and nothing takes a card to say "nothing". A
 *                    kind that failed says so on its own line, in the danger
 *                    tone: that is a fault, not an empty result.
 *
 * Every hit is the ONE task row shape (rows.js, #48): a title line and one
 * muted meta line, no glyphs, no buttons.
 *   tasks    the shared row itself (status select, meta line) + the matched
 *            snippet, narrowed by the shared filter state and the scope
 *            switch (Mine · Issues · All) and sorted by it
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

import { api } from './api.js';
import { collapsibleCard } from './collapsible.js';
import { escapeHtml, folderChip } from './format.js';
import { matchesFilters, matchesScope } from './filters.js';
import { sortItems, taskRow } from './rows.js';

const KINDS = [
  { kind: 'tasks', label: 'Tasks' },
  { kind: 'folders', label: 'Folders' },
  { kind: 'emails', label: 'Emails' },
  { kind: 'issues', label: 'Issues' },
];
const DEBOUNCE_MS = 200;
const LIMIT = 20;
const HINT = 'Searches your tasks, folders, emails and issues as you type.';

/** `[match]` marks → <mark>, everything else escaped. */
export function markHtml(text) {
  return escapeHtml(text).replace(/\[([^\[\]]+)\]/g, '<mark>$1</mark>');
}

/** "a", "a and b", "a, b and c" — lower-cased kind labels for a sentence. */
function listWords(words) {
  const w = words.map(function (s) { return s.toLowerCase(); });
  return w.length < 2 ? w.join('') : w.slice(0, -1).join(', ') + ' and ' + w[w.length - 1];
}

/**
 * What one folded line says about the kinds without a group (#395). Pure, so
 * the wording is tested without a browser.
 * @param {{none?: string[], hidden?: number, off?: string[]}} fold
 *        none   labels of the kinds that matched nothing (a configured-but-not-
 *               ready kind carries its note: "Folders (index still building)")
 *        hidden task hits the filters or the scope hid
 *        off    labels of the kinds not set up on this install
 * @returns {string[]}  the sentences, joined with " · " on screen; the Settings
 *          link follows the last one when `off` is non-empty
 */
export function foldParts(fold) {
  const parts = [];
  if (fold.none && fold.none.length) parts.push('No matches in ' + listWords(fold.none));
  if (fold.hidden) parts.push(fold.hidden + ' task ' + (fold.hidden === 1 ? 'hit' : 'hits') + ' hidden by the filters or the scope');
  if (fold.off && fold.off.length) parts.push('Not set up: ' + listWords(fold.off));
  return parts;
}

/**
 * @param {HTMLElement} box   the search card (holds #searchInput + #searchMeta)
 * @param {HTMLElement} host  where the results render
 * @param {{onOpenTask: (id:number) => void, onQuery: (q:string) => void,
 *          filters: () => object, onStatus: (id:number, status:string) => Promise<any>,
 *          menu?: object}} opts   (menu: the Search tab's row menu, rowmenu.js — #311)
 */
export function mountSearch(box, host, opts) {
  const input = box.querySelector('#searchInput');
  const meta = box.querySelector('#searchMeta');
  let timer = null;
  let seq = 0;
  let last = null;        // the last rendered result
  let status = null;      // /api/search/status → adapters (idle view)
  const hitByIdx = new Map();

  // ------------------------------------------------------------ fetch
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(function () { run(input.value); }, DEBOUNCE_MS);
  }

  // `quiet` = a re-read of the query already on screen after a write: no
  // "searching…" flash, and a failure keeps the rows that are showing.
  async function run(raw, quiet) {
    const q = String(raw || '').trim();
    if (!quiet) opts.onQuery(q);
    const my = ++seq;
    if (!q) { last = null; renderIdle(); return; }
    if (!quiet) meta.textContent = 'searching…';
    let res;
    try {
      res = await api('/api/search?q=' + encodeURIComponent(q) + '&limit=' + LIMIT);
    } catch (err) {
      if (my !== seq || quiet) return;
      meta.textContent = 'search failed';
      host.replaceChildren(note('search-err', err.message || 'Search failed'));
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
  function note(cls, text) {
    const p = document.createElement('p');
    p.className = cls;
    p.textContent = text;
    return p;
  }

  /** The one folded line, with the Settings link after "Not set up: …". */
  function foldLine(fold) {
    const parts = foldParts(fold);
    if (!parts.length) return null;
    const p = note('search-fold muted', parts.join(' · '));
    if (fold.off && fold.off.length) {
      p.appendChild(document.createTextNode(' · '));
      const a = document.createElement('a');
      a.href = '#settings/search';
      a.textContent = 'Settings';
      p.appendChild(a);
    }
    return p;
  }

  /** One kind's hits: a flat section under an overline header with its count. */
  function group(k, countText, countLabel) {
    const parts = collapsibleCard({
      className: 'disclosure-flat search-group', title: k.label, titleClass: 'overline',
      count: countText, countClass: 'section-count search-group-count', bodyClass: 'search-body',
    });
    parts.card.dataset.kind = k.kind;
    parts.card.open = true;
    parts.count.setAttribute('aria-label', countLabel);
    return parts;
  }

  function renderIdle() {
    meta.textContent = '';
    hitByIdx.clear();
    const off = (status || []).filter(function (a) { return !a.configured; }).map(function (a) {
      const k = KINDS.find(function (x) { return x.kind === a.kind; });
      return k ? k.label : a.kind;
    });
    const nodes = [note('search-hint muted', HINT)];
    const fold = foldLine({ off: off });
    if (fold) nodes.push(fold);
    host.replaceChildren.apply(host, nodes);
  }

  function taskHits(g) {
    const f = opts.filters ? opts.filters() : null;
    const tasks = (g.hits || []).map(function (h) {
      const t = Object.assign({}, h.task || {}, { id: h.task_id, _hit: h });
      if (!t.title) t.title = h.title;
      return t;
    });
    if (!f) return tasks;
    const kept = tasks.filter(function (t) { return matchesScope(t, f.scope) && matchesFilters(t, f); });
    return sortItems(kept, f.sort);
  }

  function hitWord(n) { return n + (n === 1 ? ' hit' : ' hits'); }

  function render(res) {
    hitByIdx.clear();
    let total = 0;
    let idx = 0;
    const groups = [];
    const errors = [];
    const fold = { none: [], hidden: 0, off: [] };
    KINDS.forEach(function (k) {
      const g = res.groups.find(function (x) { return x.kind === k.kind; }) || { kind: k.kind, configured: false, reason: 'no answer', hits: [] };
      if (!g.configured) { fold.off.push(k.label); return; }
      if (g.error) { errors.push(note('search-err', k.label + ' failed — ' + g.error)); return; }
      const all = g.hits || [];
      const rows = k.kind === 'tasks' ? taskHits(g) : all;
      if (k.kind === 'tasks' && !rows.length) fold.hidden = all.length;   // a partial cut shows as "3 of 5" on the group
      if (!rows.length) {
        if (k.kind !== 'tasks' || !all.length) fold.none.push(g.note ? k.label + ' (' + g.note + ')' : k.label);
        return;
      }
      const n = k.kind === 'tasks' ? rows.length : (g.count || rows.length);
      total += n;
      let countText = k.kind === 'tasks' && rows.length !== all.length ? rows.length + ' of ' + all.length : String(n);
      if (g.note) countText += ' · ' + g.note;
      const parts = group(k, countText, hitWord(n));
      const ul = document.createElement('ul');
      ul.className = 'trows search-hits';
      ul.setAttribute('role', 'list');
      rows.forEach(function (h) { ul.appendChild(k.kind === 'tasks' ? taskHitRow(h, idx++) : hitRow(h, idx++)); });
      parts.body.appendChild(ul);
      groups.push(parts.card);
    });
    meta.textContent = hitWord(total);
    const nodes = groups.slice();
    const line = foldLine(fold);
    if (line) nodes.push(line);
    host.replaceChildren.apply(host, nodes.concat(errors));
    if (opts.menu) opts.menu.endRender();
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
    // A hit's row is rebuilt from `h.task` on every render, so a write from the
    // row (#107) reaches it through `rerun()` — the app re-reads the query once
    // the write has landed, instead of patching this cache by hand.
    const li = taskRow(t, { onOpen: opts.onOpenTask, onStatus: opts.onStatus, menu: opts.menu },
      extra ? { extra: extra } : undefined);
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
      // phone opens the web twin, else the path-to-copy popover — folderChip's own rule)
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

    // the meta line sits inside the row's main column, as on a task row (#311)
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
    if (metaLine.childNodes.length) main.appendChild(metaLine);
    const sn = snippetIsPath ? null : snippetLine(h, h.title);
    if (sn) { sn.classList.add('trow-extra'); li.appendChild(sn); }

    // the whole row opens, like a task row; the link element carries the real href
    function openIt(ev) {
      if (ev.target.closest('a')) return;
      link.click();
    }
    main.addEventListener('click', openIt);
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
    /** The shared filters changed: re-apply them to the task hits. */
    refilter() { if (last) render(last); },
    /** Re-run the query on screen against the server (after a write), quietly. */
    rerun() { if (last) return run(input.value, true); return Promise.resolve(); },
    reloadStatus: loadStatus,
  };
}
