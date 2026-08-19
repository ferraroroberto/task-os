/* task-os — the Tree tab: an outliner over /api/tasks/tree.
 *
 * Indent = nesting, with a subtle vertical guide per depth level; each node
 * carries a rollup (open descendants, nearest due); a node with children
 * shows the "project" chip — this is where "a task becomes a project" is
 * visible. Ordering is deterministic at every level: open before closed,
 * then by due (none last), then title. Collapse state persists per node in
 * localStorage. On a fine pointer, drag a node onto another to re-parent it
 * (HTML5 DnD → the caller's onMove → POST /api/tasks/{id}/move; a cycle
 * comes back as a toast) — the top-level drop zone only appears during an
 * active drag. Coarse pointers get no DnD affordances at all; re-parenting
 * lives in the drawer's "Move to…" field. Keyboard: ↑/↓ walk visible nodes,
 * →/← expand/collapse, Enter opens.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { issueChip, relDue, statusPill } from './format.js';

const COLLAPSE_KEY = 'task-os.tree.collapsed';
const CLOSED = { done: 1, cancelled: 1 };

function loadCollapsed() {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr.map(Number) : []);
  } catch (_) { return new Set(); }
}
function saveCollapsed(set) {
  try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(Array.from(set))); } catch (_) { /* private mode */ }
}

/** Deterministic order at every level: open first, then due (none last),
 *  then title — the same rule for roots and children, so the tree reads the
 *  same on every load. */
function sortForest(nodes) {
  nodes.sort(function (a, b) {
    const ac = CLOSED[a.status] ? 1 : 0;
    const bc = CLOSED[b.status] ? 1 : 0;
    if (ac !== bc) return ac - bc;
    if ((a.due || '') !== (b.due || '')) {
      if (!a.due) return 1;
      if (!b.due) return -1;
      return a.due < b.due ? -1 : 1;
    }
    return (a.title || '').localeCompare(b.title || '');
  });
  nodes.forEach(function (n) { if (n.children && n.children.length) sortForest(n.children); });
}

/** Open-descendant count + nearest open due, computed over the pruned forest. */
function rollup(node) {
  let open = 0;
  let nearest = null;
  (node.children || []).forEach(function (c) {
    const r = rollup(c);
    if (!CLOSED[c.status]) {
      open += 1;
      if (c.due && (!nearest || c.due < nearest)) nearest = c.due;
    }
    open += r.open;
    if (r.nearest && (!nearest || r.nearest < nearest)) nearest = r.nearest;
  });
  node._rollup = { open: open, nearest: nearest };
  return node._rollup;
}

/**
 * @param {HTMLElement} host
 * @param {Array<object>} forest
 * @param {{onOpen: (id:number)=>void, onMove: (id:number, parentId:number|null)=>Promise<any>}} handlers
 */
export function renderTree(host, forest, handlers) {
  host.innerHTML = '';
  const collapsed = loadCollapsed();
  // No pointer to drag with → no DnD affordances at all (re-parenting lives
  // in the drawer's "Move to…" field).
  const canDrag = !window.matchMedia('(pointer: coarse)').matches;
  const card = document.createElement('div');
  card.className = 'card tree-card';
  const tree = document.createElement('div');
  tree.className = 'tree';
  tree.setAttribute('role', 'tree');
  tree.setAttribute('aria-label', 'Task tree');
  sortForest(forest);
  forest.forEach(function (n) { rollup(n); tree.appendChild(buildNode(n, collapsed, handlers, canDrag)); });

  if (canDrag) {
    // Root drop zone: only visible during an active drag (CSS keys on the
    // is-dragging class the bubbled drag events toggle here).
    const rootZone = document.createElement('div');
    rootZone.className = 'tree-root-drop';
    rootZone.innerHTML = icon('corner-down-right');
    const rz = document.createElement('span');
    rz.textContent = 'Drop here to move to the top level';
    rootZone.appendChild(rz);
    wireDropTarget(rootZone, null, handlers);
    tree.appendChild(rootZone);
    // Capture phase: the node's own dragstart stops propagation (nested
    // items would double-fire otherwise), so the bubble never arrives here.
    tree.addEventListener('dragstart', function () { tree.classList.add('is-dragging'); }, true);
    tree.addEventListener('dragend', function () { tree.classList.remove('is-dragging'); }, true);
  }

  tree.addEventListener('keydown', function (ev) { onTreeKey(ev, tree, collapsed, handlers); });
  card.appendChild(tree);
  host.appendChild(card);
  // roving tabindex: first node reachable by Tab
  const first = tree.querySelector('.tree-node');
  if (first) first.tabIndex = 0;
}

function buildNode(node, collapsed, handlers, canDrag) {
  const item = document.createElement('div');
  item.className = 'tree-node' + (CLOSED[node.status] ? ' is-closed' : '');
  item.setAttribute('role', 'treeitem');
  item.dataset.id = String(node.id);
  item.tabIndex = -1;
  item.style.setProperty('--depth', String(node.depth || 0));
  const hasKids = (node.children || []).length > 0;
  const isCollapsed = hasKids && collapsed.has(node.id);
  if (hasKids) item.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  item.setAttribute('aria-level', String((node.depth || 0) + 1));
  item.draggable = !!canDrag;

  const row = document.createElement('div');
  row.className = 'tree-row';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'tree-toggle hit-target' + (hasKids ? '' : ' is-leaf');
  toggle.tabIndex = -1;
  toggle.setAttribute('aria-label', isCollapsed ? 'Expand' : 'Collapse');
  toggle.innerHTML = icon(isCollapsed ? 'chevron-right' : 'chevron-down');
  if (!hasKids) toggle.disabled = true;
  toggle.addEventListener('click', function (ev) {
    ev.stopPropagation();
    setCollapsed(item, node.id, !collapsed.has(node.id), collapsed);
  });
  row.appendChild(toggle);

  if (canDrag) {
    const grip = document.createElement('span');
    grip.className = 'tree-grip';
    grip.innerHTML = icon('grip-vertical');
    grip.title = 'Drag to move under another task';
    row.appendChild(grip);
  }

  const title = document.createElement('span');
  title.className = 'tree-title';
  title.textContent = node.title;
  row.appendChild(title);

  if (node.is_project || hasKids) {
    const chip = document.createElement('span');
    chip.className = 'chip chip-project';
    chip.textContent = 'project';
    row.appendChild(chip);
  }
  if (node.issue_ref) {
    const ic = issueChip(node.issue_ref);
    ic.addEventListener('click', function (ev) { ev.stopPropagation(); });
    row.appendChild(ic);
  }

  const meta = document.createElement('span');
  meta.className = 'tree-meta';
  const r = node._rollup || { open: 0, nearest: null };
  if (hasKids) {
    const open = document.createElement('span');
    open.className = 'tree-rollup';
    open.textContent = r.open + ' open';
    meta.appendChild(open);
    if (r.nearest) {
      const nd = relDue(r.nearest);
      const near = document.createElement('span');
      near.className = 'tree-rollup' + (nd.tone ? ' due-' + nd.tone : '');
      near.title = 'nearest due ' + r.nearest;
      near.textContent = (nd.tone === 'overdue' ? 'due ' : 'next ') + nd.text;
      meta.appendChild(near);
    }
  }
  if (node.due) {
    const d = relDue(node.due);
    const due = document.createElement('span');
    due.className = 'tree-due' + (d.tone ? ' due-' + d.tone : '');
    due.title = node.due;
    due.innerHTML = icon('calendar-days');
    const l = document.createElement('span');
    l.textContent = d.text;
    due.appendChild(l);
    meta.appendChild(due);
  }
  meta.appendChild(statusPill(node.status));
  row.appendChild(meta);
  item.appendChild(row);

  if (hasKids) {
    const group = document.createElement('div');
    group.className = 'tree-children';
    group.setAttribute('role', 'group');
    group.hidden = isCollapsed;
    node.children.forEach(function (c) { group.appendChild(buildNode(c, collapsed, handlers, canDrag)); });
    item.appendChild(group);
  }

  row.addEventListener('click', function (ev) {
    if (ev.target.closest('button')) return;
    handlers.onOpen(node.id);
  });

  // ---- drag source (fine pointers only; dragstart/dragend bubble up to the
  // tree container, which shows the root drop zone while a drag is live)
  if (canDrag) {
    item.addEventListener('dragstart', function (ev) {
      ev.stopPropagation();
      ev.dataTransfer.setData('text/plain', String(node.id));
      ev.dataTransfer.effectAllowed = 'move';
      item.classList.add('is-dragging');
    });
    item.addEventListener('dragend', function () { item.classList.remove('is-dragging'); });
    wireDropTarget(row, node.id, handlers);
  }
  return item;
}

function wireDropTarget(el, targetId, handlers) {
  el.addEventListener('dragover', function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    ev.dataTransfer.dropEffect = 'move';
    el.classList.add('is-drop-target');
  });
  el.addEventListener('dragleave', function () { el.classList.remove('is-drop-target'); });
  el.addEventListener('drop', function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    el.classList.remove('is-drop-target');
    const id = Number(ev.dataTransfer.getData('text/plain'));
    if (!id || id === targetId) return;
    handlers.onMove(id, targetId);
  });
}

function setCollapsed(item, id, collapse, collapsed) {
  const group = item.querySelector(':scope > .tree-children');
  if (!group) return;
  if (collapse) collapsed.add(id); else collapsed.delete(id);
  saveCollapsed(collapsed);
  group.hidden = collapse;
  item.setAttribute('aria-expanded', collapse ? 'false' : 'true');
  const toggle = item.querySelector(':scope > .tree-row > .tree-toggle');
  toggle.innerHTML = icon(collapse ? 'chevron-right' : 'chevron-down');
  toggle.setAttribute('aria-label', collapse ? 'Expand' : 'Collapse');
}

function visibleNodes(tree) {
  return Array.from(tree.querySelectorAll('.tree-node')).filter(function (n) {
    let p = n.parentElement;
    while (p && p !== tree) { if (p.hidden) return false; p = p.parentElement; }
    return true;
  });
}

function onTreeKey(ev, tree, collapsed, handlers) {
  const item = ev.target.closest('.tree-node');
  if (!item) return;
  const nodes = visibleNodes(tree);
  const idx = nodes.indexOf(item);
  const id = Number(item.dataset.id);
  const focusAt = function (n) { if (n) { item.tabIndex = -1; n.tabIndex = 0; n.focus(); } };
  switch (ev.key) {
    case 'ArrowDown': ev.preventDefault(); focusAt(nodes[idx + 1]); break;
    case 'ArrowUp': ev.preventDefault(); focusAt(nodes[idx - 1]); break;
    case 'ArrowRight':
      ev.preventDefault();
      if (item.getAttribute('aria-expanded') === 'false') setCollapsed(item, id, false, collapsed);
      else focusAt(item.querySelector(':scope > .tree-children > .tree-node'));
      break;
    case 'ArrowLeft':
      ev.preventDefault();
      if (item.getAttribute('aria-expanded') === 'true') setCollapsed(item, id, true, collapsed);
      else focusAt(item.parentElement.closest('.tree-node'));
      break;
    case 'Enter':
    case ' ':
      ev.preventDefault();
      handlers.onOpen(id);
      break;
    default:
  }
}
