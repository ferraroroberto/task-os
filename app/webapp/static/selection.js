/* task-os — the ONE selection, shared by every view that can multi-select (#81).
 *
 * Select mode turns a card/row from "open the task" into "tick the task", and
 * the ticked set is state, not DOM: Board and Table read the same store, so
 * picking three cards on the Board and switching to Table finds the same three
 * ticked — the acceptance criterion that rules out a per-view set.
 *
 * A module singleton, deliberately: the app has exactly one selection the way
 * it has exactly one filter state, and two stores could disagree. It holds no
 * DOM and no fetch — `app.js` subscribes, re-renders, and owns the POST.
 *
 * Leaving Select mode clears the set: a hidden selection that survives to the
 * next entry would apply a bulk change to tasks the user can no longer see.
 */

'use strict';

let active = false;
const ids = new Set();
const listeners = [];

function notify(kind) {
  listeners.forEach(function (fn) { fn(kind); });
}

/**
 * @param {(kind: 'mode'|'ids') => void} fn
 *   `mode` = Select mode came on or off, so every row changes shape and the
 *   views must be rebuilt; `ids` = only which rows are ticked changed, which
 *   a caller can reflect in place. The distinction is not an optimisation
 *   detail: rebuilding the views on every tick would also throw away the
 *   focused checkbox mid-keyboard-selection.
 */
export function subscribe(fn) {
  listeners.push(fn);
}

export function isActive() { return active; }

/** Enter/leave Select mode; leaving always clears the set. */
export function setActive(on) {
  const next = !!on;
  if (next === active) return;
  active = next;
  if (!active) ids.clear();
  notify('mode');
}

export function has(id) { return ids.has(Number(id)); }

export function size() { return ids.size; }

/** The ticked ids, in the order they were ticked. */
export function selectedIds() { return Array.from(ids); }

export function toggle(id) {
  const n = Number(id);
  if (ids.has(n)) ids.delete(n); else ids.add(n);
  notify('ids');
}

export function clear() {
  if (!ids.size) return;
  ids.clear();
  notify('ids');
}

/** Keep only the ids still present in `valid` (a Set), silently.
 *
 *  Called after every refresh: a task deleted in another tab, or filtered out
 *  of the current view, must not ride along in the next bulk POST as an id
 *  that will simply 404. Silent — this is bookkeeping, not a user action — so
 *  it notifies only when it actually dropped something. */
export function keepOnly(valid) {
  let dropped = false;
  Array.from(ids).forEach(function (id) {
    if (!valid.has(id)) { ids.delete(id); dropped = true; }
  });
  if (dropped) notify('ids');
}
