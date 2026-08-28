/* task-os — the ONE folder-index picker, shared by the drawer's Folder section
 * and the quick-add dialog (#80 round 2).
 *
 * Two pieces, so a caller only takes what it needs:
 *
 *   resolveFolderRef(value)   an empty string / a `{placeholder}/…` ref / an
 *                             absolute path → the ref a task stores. Absolute
 *                             paths fold onto the placeholders through
 *                             POST /api/resolve — never resolved client-side;
 *                             a body, not `?ref=`, because URL-cleaning
 *                             extensions strip that parameter name off every
 *                             http(s) URL (#66).
 *   mountFolderPicker(host, opts)   the search box + hit list + keyboard
 *                             (↑↓ move · Enter takes the active hit · Escape
 *                             closes) over GET /api/folders/search. Mounts
 *                             once per host; `opts.onPick(ref)` does the
 *                             attaching, `opts.onClose()` lets the caller keep
 *                             its own open/closed flag in step.
 *
 * Both were the drawer's private code until the quick-add dialog needed the
 * same picker — one copy, not two, so the index search behaves identically
 * wherever a folder is attached.
 */

'use strict';

import { api } from './api.js';
import { icon } from './_vendored/icons/icons.js';
import { toast } from './toast.js';

const SEARCH_DEBOUNCE_MS = 220;

/**
 * @param {string} value  '' · a `{placeholder}/…` ref · an absolute path
 * @returns {Promise<string|null>}  the ref to store (`null` for empty), or
 *          `undefined` when the fold failed (the reason is already toasted)
 */
export async function resolveFolderRef(value) {
  if (!value) return null;
  if (/^\{/.test(value)) return value;
  try {
    const r = await api('/api/resolve', { method: 'POST', body: { ref: value } });
    if (r.ref !== value) toast('Stored as ' + r.ref, 'info');
    return r.ref;
  } catch (err) {
    toast(err.message || 'Could not resolve the path', 'error');
    return undefined;
  }
}

/**
 * Mount the folder-index search into `host` (idempotent — a second call on the
 * same host is a no-op, so a caller can toggle its visibility freely).
 * @param {HTMLElement} host
 * @param {{onPick: (ref: string) => void, onClose?: () => void}} opts
 */
export function mountFolderPicker(host, opts) {
  if (host.dataset.mounted) return;
  host.dataset.mounted = '1';
  const q = document.createElement('input');
  q.type = 'search';
  q.className = 'input-native folder-picker-q';
  q.placeholder = 'Search folders… (Enter attaches the first hit)';
  q.setAttribute('aria-label', 'Search the folder index');
  const list = document.createElement('ul');
  list.className = 'folder-picker-list';
  list.setAttribute('role', 'listbox');
  const note = document.createElement('p');
  note.className = 'muted folder-picker-note';
  note.textContent = 'Type to search the folder index.';
  host.append(q, list, note);
  let timer = null;
  let items = [];
  let active = -1;

  function paint() {
    list.innerHTML = '';
    items.forEach(function (it, i) {
      const li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.className = 'folder-picker-item' + (i === active ? ' is-active' : '');
      li.dataset.ref = it.ref;
      li.title = it.path;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'folder-picker-btn';
      b.innerHTML = icon('folder');
      const name = document.createElement('span');
      name.className = 'folder-picker-name';
      name.textContent = it.name;
      const ref = document.createElement('span');
      ref.className = 'folder-picker-ref';
      ref.textContent = it.ref;
      b.append(name, ref);
      b.addEventListener('click', function () { opts.onPick(it.ref); });
      li.appendChild(b);
      list.appendChild(li);
    });
  }

  async function search() {
    const text = q.value.trim();
    if (!text) { items = []; active = -1; paint(); note.textContent = 'Type to search the folder index.'; return; }
    try {
      const r = await api('/api/folders/search?q=' + encodeURIComponent(text) + '&limit=15');
      items = r.items || [];
      active = items.length ? 0 : -1;
      paint();
      note.textContent = items.length
        ? r.count + ' hit(s)' + (r.indexing ? ' · index still building' : '')
        : (r.indexing ? 'No hits yet — the index is still building.' : 'No folder matches.');
    } catch (err) {
      items = []; active = -1; paint();
      note.textContent = err.code === 'folders_disabled'
        ? 'Folder index not configured — set search.folder_roots in config.json (' + err.message + ').'
        : ('Search failed: ' + err.message);
    }
  }

  q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(search, SEARCH_DEBOUNCE_MS); });
  q.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown' && items.length) { ev.preventDefault(); active = (active + 1) % items.length; paint(); }
    else if (ev.key === 'ArrowUp' && items.length) { ev.preventDefault(); active = (active - 1 + items.length) % items.length; paint(); }
    else if (ev.key === 'Enter') { ev.preventDefault(); if (active >= 0 && items[active]) opts.onPick(items[active].ref); }
    else if (ev.key === 'Escape') { host.hidden = true; if (opts.onClose) opts.onClose(); }
  });
}
