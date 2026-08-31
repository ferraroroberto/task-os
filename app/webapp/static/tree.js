/* task-os — the Tree tab: the shared list as an outliner.
 *
 * Indent = nesting, with a subtle vertical guide per depth level; a node with
 * children carries an expand toggle — this is where "a task becomes a project"
 * is visible. Rows are the ONE task row (rows.js, issue #46): title + status
 * select, the meta line (project hidden — the nesting already says it).
 *
 * The forest comes from /api/tasks/tree (every task, closed ones included);
 * the caller passes `keep` = the ids of the shared filtered list, and the
 * tree is pruned to those nodes plus the ancestors they need — an ancestor
 * that is itself filtered out renders muted as context. Every level is
 * ordered by the shared `sort` (filters.js), so "sorted by due date" in the
 * filter card is the Tree's order too. Collapse state persists per node in
 * localStorage. On a fine pointer, drag a node onto another to re-parent it
 * (HTML5 DnD → the caller's onMove → POST /api/tasks/{id}/move; a cycle comes
 * back as a toast) — the top-level drop zone only appears during an active
 * drag. Coarse pointers get no DnD affordances; re-parenting lives in the
 * drawer's "Move to…" field. Keyboard: ↑/↓ walk visible nodes, →/← expand /
 * collapse, Enter opens.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { compareItems, taskRow } from './rows.js';

const COLLAPSE_KEY = 'task-os.tree.collapsed';

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

/**
 * Prune the forest to `keep` + the ancestors they need; nodes merge the
 * enriched summary from `byId` (the shared list) when they have one.
 * @returns {Array<object>} a new forest ({...node, children, _context})
 */
export function pruneForest(forest, keep, byId) {
  function walk(nodes) {
    const out = [];
    nodes.forEach(function (n) {
      const kids = walk(n.children || []);
      const kept = !keep || keep.has(n.id);
      if (!kept && !kids.length) return;
      const merged = Object.assign({}, n, byId && byId[n.id] ? byId[n.id] : {}, { children: kids, depth: n.depth });
      merged._context = !kept;
      out.push(merged);
    });
    return out;
  }
  return walk(forest);
}

/** Sort every level with the shared comparator. */
export function sortForest(nodes, sort) {
  const cmp = compareItems(sort);
  nodes.sort(cmp);
  nodes.forEach(function (n) { if (n.children && n.children.length) sortForest(n.children, sort); });
  return nodes;
}

/**
 * @param {HTMLElement} host
 * @param {Array<object>} forest      /api/tasks/tree items (full)
 * @param {{onOpen: (id:number)=>void, onMove: (id:number, parentId:number|null)=>Promise<any>,
 *          onStatus: (id:number, status:string)=>Promise<any>,
 *          onToggleSelect?: (id:number)=>void}} handlers
 * @param {{keep?: Set<number>|null, byId?: object, sort?: string,
 *          selectable?: boolean, isSelected?: (id:number)=>boolean}} [opts]
 */
export function renderTree(host, forest, handlers, opts) {
  const o = opts || {};
  host.innerHTML = '';
  const collapsed = loadCollapsed();
  // No pointer to drag with → no DnD affordances at all (re-parenting lives
  // in the drawer's "Move to…" field). Select mode also parks the drag —
  // a row that both drags and ticks turns every slightly-moved tap into a
  // move (#81, the Board's rule).
  const canDrag = !window.matchMedia('(pointer: coarse)').matches && !o.selectable;
  const tree = document.createElement('div');
  tree.className = 'tree';
  tree.setAttribute('role', 'tree');
  tree.setAttribute('aria-label', 'Task tree');
  const pruned = sortForest(pruneForest(forest, o.keep || null, o.byId || null), o.sort || 'due');
  pruned.forEach(function (n) { tree.appendChild(buildNode(n, collapsed, handlers, canDrag, o)); });

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
  host.appendChild(tree);
  // roving tabindex: first node reachable by Tab
  const first = tree.querySelector('.tree-node > .trow > .trow-main');
  if (first) first.tabIndex = 0;
  return pruned.length;
}

function buildNode(node, collapsed, handlers, canDrag, sel) {
  const item = document.createElement('div');
  item.className = 'tree-node' + (node._context ? ' is-context' : '');
  item.setAttribute('role', 'treeitem');
  item.dataset.id = String(node.id);
  const hasKids = (node.children || []).length > 0;
  const isCollapsed = hasKids && collapsed.has(node.id);
  if (hasKids) item.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  item.setAttribute('aria-level', String((node.depth || 0) + 1));

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'tree-toggle' + (hasKids ? '' : ' is-leaf');
  toggle.tabIndex = -1;
  toggle.setAttribute('aria-label', isCollapsed ? 'Expand' : 'Collapse');
  toggle.innerHTML = icon(isCollapsed ? 'chevron-right' : 'chevron-down');
  if (!hasKids) toggle.disabled = true;
  toggle.addEventListener('click', function (ev) {
    ev.stopPropagation();
    setCollapsed(item, node.id, !collapsed.has(node.id), collapsed);
  });

  const row = taskRow(node, handlers, {
    prefix: toggle, depth: node.depth || 0, hideProject: true, draggable: canDrag,
    selectable: !!(sel && sel.selectable),
    selected: !!(sel && sel.selectable && sel.isSelected && sel.isSelected(node.id)),
  });
  row.classList.add('tree-row');
  item.appendChild(row);

  if (hasKids) {
    const group = document.createElement('div');
    group.className = 'tree-children';
    group.setAttribute('role', 'group');
    group.hidden = isCollapsed;
    node.children.forEach(function (c) { group.appendChild(buildNode(c, collapsed, handlers, canDrag, sel)); });
    item.appendChild(group);
  }

  // ---- drag source (fine pointers only; dragstart/dragend bubble up to the
  // tree container, which shows the root drop zone while a drag is live)
  if (canDrag) {
    row.addEventListener('dragstart', function (ev) {
      ev.stopPropagation();
      ev.dataTransfer.setData('text/plain', String(node.id));
      ev.dataTransfer.effectAllowed = 'move';
      row.classList.add('is-dragging');
    });
    row.addEventListener('dragend', function () { row.classList.remove('is-dragging'); });
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
  // Only clear when the pointer actually left the row — crossing into a nested
  // child (title, chip, select) fires dragleave too and would flicker the
  // highlight. Same containment guard board.js's wireDropTarget already has.
  el.addEventListener('dragleave', function (ev) {
    if (!el.contains(ev.relatedTarget)) el.classList.remove('is-drop-target');
  });
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
  const toggle = item.querySelector(':scope > .trow > .tree-toggle');
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
  if (ev.target.closest('select, input, a')) return;
  const item = ev.target.closest('.tree-node');
  if (!item) return;
  const nodes = visibleNodes(tree);
  const idx = nodes.indexOf(item);
  const id = Number(item.dataset.id);
  const mainOf = function (n) { return n ? n.querySelector(':scope > .trow > .trow-main') : null; };
  const focusAt = function (n) {
    const m = mainOf(n);
    if (m) { const cur = mainOf(item); if (cur) cur.tabIndex = -1; m.tabIndex = 0; m.focus(); }
  };
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
      if (ev.target.closest('.trow-main')) return;    // the row handles its own Enter
      ev.preventDefault();
      handlers.onOpen(id);
      break;
    default:
  }
}
