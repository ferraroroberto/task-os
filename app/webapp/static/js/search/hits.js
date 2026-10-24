/* task-os — Search: one hit as a row. Every hit is the ONE task row shape
 * (rows.js): a title line and one muted meta line, no glyphs, no buttons.
 * Each builder takes `ctx` first (the composer's shared state: `opts`,
 * `hitByIdx`) and registers the hit under its index for the keyboard. */

'use strict';

import { escapeHtml, folderChip } from '../../format.js';
import { taskRow } from '../../rows.js';
import { markHtml } from './text.js';

function snippetLine(h, title) {
  const snippet = h.snippet || '';
  if (!snippet || snippet.replace(/[\[\]]/g, '') === title) return null;
  const el = document.createElement('div');
  el.className = 'search-hit-snippet';
  el.innerHTML = (h.matched_in ? '<span class="muted">' + escapeHtml(h.matched_in) + ': </span>' : '') + markHtml(snippet);
  return el;
}

/** A task hit = the shared row + the matched snippet under it. */
export function taskHitRow(ctx, t, idx) {
  const opts = ctx.opts;
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
  ctx.hitByIdx.set(idx, h);
  return li;
}

/** The hit's title link: the opener for a folder / email, the task for a listed issue, else the issue page. */
function hitLink(ctx, h, snippetIsTitle) {
  const snippet = h.snippet || '';
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
    link.addEventListener('click', function (ev) { ev.preventDefault(); ev.stopPropagation(); ctx.opts.onOpenTask(h.task_id); });
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
  return link;
}

/** The meta line's pieces for a folder / email / issue hit. */
function metaBits(h) {
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
  return bits;
}

/** A folder / email / issue hit in the same row shape: title line + meta line. */
export function hitRow(ctx, h, idx) {
  const li = document.createElement('li');
  li.className = 'trow search-hit';
  li.dataset.kind = h.kind;
  li.dataset.idx = String(idx);
  ctx.hitByIdx.set(idx, h);
  const main = document.createElement('div');
  main.className = 'trow-main';
  main.setAttribute('role', 'button');
  main.tabIndex = 0;
  const title = document.createElement('span');
  title.className = 'trow-title';
  const snippet = h.snippet || '';
  const snippetIsTitle = snippet && snippet.replace(/[\[\]]/g, '') === h.title;
  const link = hitLink(ctx, h, snippetIsTitle);
  title.appendChild(link);
  main.appendChild(title);
  li.appendChild(main);

  // the meta line sits inside the row's main column, as on a task row (#311)
  const metaLine = document.createElement('span');
  metaLine.className = 'trow-meta';
  const bits = metaBits(h);
  // a snippet that is just the path (a folder hit) marks the path on the
  // meta line instead of repeating it underneath
  const plain = snippet.replace(/[\[\]]/g, '');
  const snippetIsPath = plain && bits.length && plain === bits[0];
  bits.forEach(function (b, i) {
    const s = document.createElement('span');
    s.className = 'search-hit-meta';
    if (i === 0 && snippetIsPath) s.innerHTML = markHtml(snippet); else s.textContent = b;
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
