/* task-os — the parent picker: where the drawer's "Change parent" lands a task.
 *
 * `openParentPicker(t, targets, onPick)` builds one modal sheet per ask into
 * the `<dialog id="parentDialog">` shell in index.html — the same vendored
 * editor modal confirm.js and snooze.js use (native showModal / close, Esc, the
 * × and a backdrop click all mean "cancel"). A filter field over every open
 * task in tree order, each indented by depth with its path as muted text under
 * the title; a tap commits. Nothing is written here: `onPick` gets the new
 * parent id and the drawer's `onMove` (the one `moveTask`) does the write.
 *
 * The picker narrows what it offers — never the task itself or anything under
 * it, never a closed task — but the server stays the authority:
 * `tasks_repo.move()` answers a cycle with a 409 that `moveTask` toasts.
 */

'use strict';

import { modalCard, onceClosed } from './modal.js';
import { CLOSED } from './rows.js';

/**
 * The tasks `taskId` may be filed under: every open task of `forest` in tree
 * order, minus `taskId` and its subtree. A closed ancestor of an open task is
 * not offered but still names the path (it is where the task lives).
 * @param {Array<object>} forest   `state.tree` — nodes with `id, title, status, children`
 * @param {number} taskId
 * @returns {Array<{id:number, title:string, depth:number, path:string}>}
 */
export function parentTargets(forest, taskId) {
  const out = [];
  (function walk(nodes, trail) {
    nodes.forEach(function (n) {
      if (n.id === taskId) return;   // the task and its whole subtree
      if (!CLOSED[n.status]) {
        out.push({ id: n.id, title: n.title, depth: trail.length, path: trail.join(' › ') });
      }
      if (n.children && n.children.length) walk(n.children, trail.concat(n.title));
    });
  })(forest || [], []);
  return out;
}

/** Every open task, not just projects — the blocker picker offers any
 *  open task (a closed blocker gates nothing). A closed project kept in
 *  the forest for its open descendants is context there, not an option. */
export function flattenOpen(forest) {
  const out = [];
  (function walk(nodes) {
    nodes.forEach(function (n) {
      if (!CLOSED[n.status]) out.push({ id: n.id, title: n.title, depth: n.depth || 0 });
      if (n.children && n.children.length) walk(n.children);
    });
  })(forest);
  return out;
}

/**
 * @param {{id:number, title:string, parent_id?:number|null}} t   the task being moved
 * @param {Array<{id:number, title:string, depth:number, path:string}>} targets  from parentTargets()
 * @param {(parentId:number) => void} onPick   runs on a pick only, never on a cancel
 */
export function openParentPicker(t, targets, onPick) {
  const dialog = document.getElementById('parentDialog');
  if (!dialog) return;
  const shell = modalCard({
    cardClass: 'parent-card', title: 'Change parent', titleId: 'parentDialogTitle',
    closeLabel: 'Cancel', onClose: function () { dialog.close(); },
  });
  const card = shell.card;

  const name = document.createElement('p');
  name.className = 'parent-task muted';
  name.textContent = t.title;

  const filter = document.createElement('input');
  filter.type = 'search';
  filter.className = 'parent-filter';
  filter.placeholder = 'Filter ' + targets.length + ' open ' + (targets.length === 1 ? 'task' : 'tasks');
  filter.setAttribute('aria-label', 'Filter tasks to file ' + t.title + ' under');
  filter.autocomplete = 'off';

  const list = document.createElement('div');
  list.className = 'parent-list';
  list.setAttribute('role', 'list');
  const empty = document.createElement('p');
  empty.className = 'parent-empty muted';
  empty.hidden = true;

  let picked = null;
  const rows = targets.map(function (p) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'parent-opt';
    b.dataset.id = String(p.id);
    b.style.setProperty('--depth', String(p.depth));
    b.setAttribute('role', 'listitem');
    const title = document.createElement('span');
    title.className = 'parent-opt-title';
    title.textContent = p.title;
    b.appendChild(title);
    if (p.path) {
      const path = document.createElement('span');
      path.className = 'parent-opt-path muted';
      path.textContent = p.path;
      b.appendChild(path);
    }
    if (p.id === t.parent_id) b.setAttribute('aria-current', 'true');
    b.addEventListener('click', function () { picked = p.id; dialog.close(); });
    list.appendChild(b);
    return { el: b, hay: (p.title + ' ' + p.path).toLowerCase() };
  });

  function refilter() {
    const words = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    rows.forEach(function (r) {
      const hit = words.every(function (w) { return r.hay.indexOf(w) !== -1; });
      r.el.hidden = !hit;
      if (hit) shown += 1;
    });
    empty.hidden = shown !== 0;
    empty.textContent = targets.length ? 'No open task matches' : 'There is no other open task to file this under';
  }
  filter.addEventListener('input', refilter);
  filter.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    const first = rows.find(function (r) { return !r.el.hidden; });
    if (first) first.el.click();
  });
  refilter();

  card.append(name, filter, list, empty);

  onceClosed(dialog, function () {
    if (picked !== null && picked !== t.parent_id) onPick(picked);
  });
  dialog.replaceChildren(card);
  dialog.showModal();
  // a keyboard that opens over a phone's list hides what it filters
  if (window.matchMedia('(pointer: fine)').matches) filter.focus();
}
