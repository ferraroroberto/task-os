/* task-os — the command palette (Ctrl+K / ⌘K, Step 10).
 *
 * A vendored editor-modal shell (`<dialog class="detail-dialog palette-dialog">`,
 * native showModal / close, Esc closes) holding one input and a list:
 *
 *   plain text   jump to a task — GET /api/search?kinds=tasks&limit=8, one row
 *                per hit (title · breadcrumb · status pill), Enter opens it
 *   >text        commands — the list `opts.commands()` returns ({id, label,
 *                hint, icon, run}), filtered by substring; empty `>` lists all
 *   (empty)      the command list, so the palette is discoverable
 *
 * ↑↓ move, Enter runs the active row, Esc closes, click runs. Works from any
 * tab (the caller binds the shortcut + the header button); on the phone the
 * dialog is a full-width sheet (styles/overlays.css).
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { api } from './api.js';
import { breadcrumbText, statusMark } from './format.js';
import { closeOnBackdrop } from './modal.js';

const DEBOUNCE_MS = 150;
const TASK_LIMIT = 8;

/** One palette row: icon, label (+ status mark), hint, key. */
function itemEl(it, isActive) {
  const li = document.createElement('li');
  li.className = 'palette-item' + (isActive ? ' is-active' : '');
  li.dataset.kind = it.kind;
  li.setAttribute('role', 'option');
  li.setAttribute('aria-selected', isActive ? 'true' : 'false');
  li.innerHTML = icon(it.icon || (it.kind === 'task' ? 'list-checks' : 'chevron-right'), 'palette-item-icon');
  const main = document.createElement('div');
  main.className = 'palette-item-main';
  const label = document.createElement('div');
  label.className = 'palette-item-label';
  label.textContent = it.label;
  if (it.status) label.appendChild(statusMark(it.status));
  main.appendChild(label);
  if (it.hint) {
    const hint = document.createElement('div');
    hint.className = 'palette-item-hint muted';
    hint.textContent = it.hint;
    main.appendChild(hint);
  }
  li.appendChild(main);
  if (it.kbd) {
    const k = document.createElement('kbd');
    k.textContent = it.kbd;
    li.appendChild(k);
  }
  return li;
}

/** The commands whose label or hint holds `filter`, as palette items. */
function commandItems(commands, filter) {
  const f = (filter || '').trim().toLowerCase();
  return commands
    .filter(function (c) { return !f || (c.label + ' ' + (c.hint || '')).toLowerCase().indexOf(f) >= 0; })
    .map(function (c) { return { kind: 'command', label: c.label, hint: c.hint, icon: c.icon || 'chevron-right', run: c.run, kbd: c.kbd }; });
}

/** A task search hit as a palette item. */
function taskItem(h, onOpenTask) {
  return {
    kind: 'task', label: h.title, status: h.status,
    hint: [breadcrumbText(h.breadcrumb), h.code].filter(Boolean).join(' · ') || null,
    icon: 'list-checks',
    run: function () { onOpenTask(h.task_id); },
  };
}

/** The dialog's card: one input and the list `paint()` fills. The `#palette`
 *  shell in index.html stays empty, like every other editor-modal dialog there. */
const CARD_HTML = `
  <div class="detail-card palette-card">
    <div class="palette-input-row">
      <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-search"></use></svg>
      <input id="paletteInput" class="palette-input" type="text" autocomplete="off" spellcheck="false"
             placeholder="Jump to a task… or type > for commands" aria-label="Command palette"
             role="combobox" aria-expanded="true" aria-controls="paletteList" aria-autocomplete="list">
      <button type="button" class="icon-button detail-close" aria-label="Close">
        <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-x"></use></svg>
      </button>
    </div>
    <ul id="paletteList" class="palette-list" role="listbox"></ul>
    <p class="palette-foot muted"><kbd aria-label="Up"><svg class="icon" aria-hidden="true"><use href="#i-arrow-up"></use></svg></kbd><kbd aria-label="Down"><svg class="icon" aria-hidden="true"><use href="#i-arrow-down"></use></svg></kbd> move · <kbd>Enter</kbd> run · <kbd>&gt;</kbd> commands · <kbd>Esc</kbd> close</p>
  </div>
`;

/**
 * @param {HTMLDialogElement} dialog
 * @param {{commands: () => Array<{id:string,label:string,hint?:string,icon?:string,run:() => any}>,
 *          onOpenTask: (id:number) => void}} opts
 */
export function createPalette(dialog, opts) {
  dialog.innerHTML = CARD_HTML;
  const input = dialog.querySelector('#paletteInput');
  const list = dialog.querySelector('#paletteList');
  let items = [];        // [{label, hint, icon, run, kind}]
  let active = 0;
  let timer = null;
  let seq = 0;

  function paint() {
    list.replaceChildren();
    if (!items.length) {
      const li = document.createElement('li');
      li.className = 'palette-empty muted';
      li.textContent = input.value.trim().charAt(0) === '>' ? 'No command matches.' : (input.value.trim() ? 'No task matches.' : 'Type to jump to a task, or > for commands.');
      list.appendChild(li);
      return;
    }
    items.forEach(function (it, i) {
      const li = itemEl(it, i === active);
      li.addEventListener('mousemove', function () { if (active !== i) { active = i; paint(); } });
      li.addEventListener('click', function () { run(it); });
      list.appendChild(li);
    });
    const el = list.children[active];
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }

  async function taskItems(q) {
    const my = ++seq;
    let res;
    try {
      res = await api('/api/search?q=' + encodeURIComponent(q) + '&kinds=tasks&limit=' + TASK_LIMIT);
    } catch (_) {
      return;
    }
    if (my !== seq || dialog.open === false) return;
    const g = (res.groups || []).find(function (x) { return x.kind === 'tasks'; });
    items = ((g && g.hits) || []).map(function (h) { return taskItem(h, opts.onOpenTask); });
    active = 0;
    paint();
  }

  function refresh() {
    clearTimeout(timer);
    const v = input.value;
    const command = v.trim().charAt(0) === '>';
    if (command || !v.trim()) {
      seq++;                                   // drop any task answer in flight
      items = commandItems(opts.commands(), command ? v.trim().slice(1) : '');
      active = 0;
      paint();
      return;
    }
    timer = setTimeout(function () { taskItems(v.trim()); }, DEBOUNCE_MS);
  }

  function run(it) {
    close();
    try {
      const r = it.run();
      if (r && typeof r.catch === 'function') r.catch(function () {});
    } catch (_) { /* the command toasts its own failure */ }
  }

  function open(prefill) {
    if (!dialog.open) dialog.showModal();
    input.value = prefill || '';
    refresh();
    input.focus();
    input.select();
  }

  function close() {
    if (dialog.open) dialog.close();
  }

  input.addEventListener('input', refresh);
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); if (items.length) { active = (active + 1) % items.length; paint(); } }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (items.length) { active = (active - 1 + items.length) % items.length; paint(); } }
    else if (ev.key === 'Enter') { ev.preventDefault(); if (items[active]) run(items[active]); }
    else if (ev.key === 'Home' && items.length) { ev.preventDefault(); active = 0; paint(); }
    else if (ev.key === 'End' && items.length) { ev.preventDefault(); active = items.length - 1; paint(); }
  });
  dialog.querySelector('.detail-close').addEventListener('click', close);
  closeOnBackdrop(dialog, close);
  dialog.addEventListener('close', function () { clearTimeout(timer); seq++; });

  return {
    open: open,
    close: close,
    toggle: function () { if (dialog.open) close(); else open(''); },
    isOpen: function () { return !!dialog.open; },
  };
}
