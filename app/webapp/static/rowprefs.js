/* task-os — what the row's swipes do and what its ⋯ menu lists (#311).
 *
 * Settings → Row actions lets the owner pick, per device, the action a swipe
 * right and a swipe left run, and which of the row actions the ⋯ menu lists
 * and in what order. The choices are ids from the ONE action table
 * (actions.js), so swipes, menu, keys and palette stay one source. Stored in
 * localStorage beside the text size (`task-os.textsize`) — a per-device
 * convenience: a missing, unreadable or blocked store just means the defaults.
 *
 * One rule a choice cannot break: every action stays reachable without a
 * gesture (WCAG 2.5.1). The keys and the palette list every action whatever
 * the menu says; on top of that, an action a swipe runs is always in the menu
 * (`menuOrder()` puts it back if the list left it out), so the touch-only
 * owner of a swipe never loses its tap path. A swipe set to nothing does
 * nothing.
 *
 * The normalisation is pure (no DOM, no storage) and loads bare under node.
 */

'use strict';

import { ACTIONS } from './actions.js';

export const STORAGE_KEY = 'task-os.rowactions';

/** The plan's choices (#311): right completes, left changes the date, and the
 *  menu lists these in this order. */
export const DEFAULTS = Object.freeze({
  right: 'complete',
  left: 'change-date',
  menu: Object.freeze([
    'complete', 'reopen', 'change-date', 'snooze',
    'status-inbox', 'status-todo', 'status-standby', 'status-cancelled', 'priority',
  ]),
});

function known(id) {
  return ACTIONS.some(function (a) { return a.id === id; });
}

/**
 * Any stored value → a valid choice: unknown ids are dropped, a duplicate
 * keeps its first place, a side that is not a known id or '' (nothing) falls
 * back to its default, and a missing menu list is the default list.
 * @param {*} raw
 * @returns {{right: string, left: string, menu: string[]}}
 */
export function normalizeRowPrefs(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const side = function (v, dflt) { return v === '' || known(v) ? v : dflt; };
  const menu = Array.isArray(r.menu) ? r.menu : DEFAULTS.menu;
  const seen = new Set();
  return {
    right: side(r.right, DEFAULTS.right),
    left: side(r.left, DEFAULTS.left),
    menu: menu.filter(function (id) {
      if (typeof id !== 'string' || !known(id) || seen.has(id)) return false;
      seen.add(id);
      return true;
    }),
  };
}

/** The ids the menu lists: the chosen list, then any swipe action it left out. */
export function menuOrder(prefs) {
  const out = prefs.menu.slice();
  [prefs.right, prefs.left].forEach(function (id) {
    if (id && out.indexOf(id) < 0) out.push(id);
  });
  return out;
}

/** Is this the plan's default (Settings says "Default" then)? */
export function isDefault(prefs) {
  return prefs.right === DEFAULTS.right && prefs.left === DEFAULTS.left
    && prefs.menu.join(',') === DEFAULTS.menu.join(',');
}

// ------------------------------------------------------------- the store
let current = null;

/** The choice in force (read once, then kept). */
export function rowPrefs() {
  if (!current) {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (_) { /* private mode, bad JSON */ }
    current = normalizeRowPrefs(raw);
  }
  return current;
}

/** Store a new choice; returns it normalised. `null` goes back to the defaults. */
export function setRowPrefs(next) {
  current = normalizeRowPrefs(next);
  try {
    if (next == null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch (_) { /* private mode: the choice holds for this page */ }
  return current;
}
