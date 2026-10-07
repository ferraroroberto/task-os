/* task-os — the ONE table of row actions, their runner and the undo (#99, #311).
 *
 * Every surface that changes a task from a row reads this file: the keymap and
 * its shortcuts sheet (keys.js), the command palette (through keys.commands()),
 * the row's status control, and — as the row redesign lands (#311) — the ⋯ menu
 * and the swipes. An action added here shows up on all of them or on none, and
 * they share one write path instead of one per surface that must agree.
 *
 * Every write goes through POST /api/tasks/bulk, one id or fifty: the bulk
 * endpoint runs each id through the same repo path as a single-task edit
 * (activity row, recurrence roll, mirror hook), so one write path covers both
 * targets instead of two that must agree.
 *
 * Undo is the inverse write, not a client-side rollback: the server logs the
 * reversal as its own `new → old` activity row, which is the only version of
 * "undone" that survives a reload. It is single-level and expires with its
 * toast (`ACTION_TTL_MS`) — the offer on screen and the buffer in memory are
 * the same window, so `z` can never quietly revive a change scrolled past ten
 * minutes ago.
 *
 * The table itself (ACTIONS and the grouping helpers) touches no DOM, so it
 * loads bare under node for the unit tests.
 */

'use strict';

import { fmtDay, relDue } from './format.js';
import { ACTION_TTL_MS, toast } from './toast.js';

/** Ascending, wrapping at the top — one press always moves, `none` included. */
const PRIORITIES = ['none', 'low', 'medium', 'high'];
export const STATUS_KEYS = [['1', 'inbox'], ['2', 'todo'], ['3', 'standby']];
const CLOSED = { done: 1, cancelled: 1 };

function isOpen(t) { return !CLOSED[t.status]; }
function isClosed(t) { return !!CLOSED[t.status]; }

// ------------------------------------------------------------- grouping
/** `[{ids, changes}]` for one shared change. */
function oneGroup(tasks, changes) {
  return tasks.length ? [{ ids: tasks.map(function (t) { return t.id; }), changes: changes }] : [];
}

/**
 * Group tasks by what `fields` currently hold — the shape both the undo of
 * any action and the priority cycle need, because both apply a *different*
 * value per task and the endpoint takes one value per call.
 */
function groupByCurrent(tasks, fields, valueFor) {
  const out = new Map();
  tasks.forEach(function (t) {
    const changes = {};
    fields.forEach(function (f) { changes[f] = valueFor ? valueFor(t, f) : (t[f] == null ? null : t[f]); });
    const key = JSON.stringify(changes);
    if (!out.has(key)) out.set(key, { ids: [], changes: changes });
    out.get(key).ids.push(t.id);
  });
  return Array.from(out.values());
}

export function nextPriority(p) {
  const i = PRIORITIES.indexOf(p || 'none');
  return PRIORITIES[(i < 0 ? 0 : i + 1) % PRIORITIES.length];
}

// -------------------------------------------------------------- actions
/**
 * The row actions. Each declares:
 *   plan(tasks, arg)          → the groups to write
 *   invert(tasks, arg)        → the groups that put the prior values back
 *   message(tasks, arg, after)→ what the toast says (the count is prefixed by
 *                               the caller); `after` is the tasks as the server
 *                               answered, for a message that names the result
 *   applies(task)             → whether the row menu offers it for this task
 *                               (the keys act regardless: a key is a deliberate ask)
 * `menu: 'starts' | 'due'` means the action asks for a date first (snooze,
 * change date) and commits from the date picker instead of straight away.
 * `key: null` is an action no key reaches — the row menu, the palette and the
 * swipes still do.
 */
export const ACTIONS = [
  {
    id: 'complete', key: 'e', kbd: 'E', icon: 'circle-check',
    label: 'Complete task', hint: 'a recurring task rolls to its next date',
    plan: function (tasks) { return oneGroup(tasks, { status: 'complete' }); },
    invert: function (tasks) {
      // The roll moved `due` and left the status alone (tasks_repo.done); a
      // plain task closed instead. Two inverses, one per kind of task.
      const rolled = tasks.filter(function (t) { return t.recurrence; });
      const closed = tasks.filter(function (t) { return !t.recurrence; });
      return groupByCurrent(rolled, ['due']).concat(groupByCurrent(closed, ['status']));
    },
    applies: isOpen,
    message: function (tasks, arg, after) {
      // One recurring task rolled: say where it went, as the status select
      // always has (issue #54).
      const t = after && after.length === 1 ? after[0] : null;
      if (t && t.recurrence && t.due) return 'Completed — next: ' + fmtDay(t.due) + ' (' + relDue(t.due).text + ')';
      return 'Completed';
    },
  },
  {
    id: 'reopen', key: null, kbd: null, icon: 'rotate-ccw',
    label: 'Reopen task', hint: 'back to todo',
    plan: function (tasks) { return oneGroup(tasks, { status: 'todo' }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['status']); },
    applies: isClosed,
    message: function () { return 'Reopened'; },
  },
  {
    id: 'change-date', key: 'd', kbd: 'D', icon: 'calendar-days', menu: 'due',
    label: 'Change date…', hint: 'today · tomorrow · this weekend · next week · a date · no date',
    plan: function (tasks, phrase) { return oneGroup(tasks, { due: phrase }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['due']); },
    applies: isOpen,
    message: function (tasks, arg, after) {
      const d = after && after.length === 1 ? after[0].due : undefined;
      if (arg === null) return 'Due date cleared';
      return d ? 'Due ' + fmtDay(d) : 'Due date changed';
    },
  },
  {
    id: 'due-tomorrow', key: 't', kbd: 'T', icon: 'calendar-days',
    label: 'Due tomorrow', hint: null,
    plan: function (tasks) { return oneGroup(tasks, { due: 'tomorrow' }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['due']); },
    applies: isOpen,
    message: function () { return 'Due tomorrow'; },
  },
  {
    id: 'due-next-week', key: 'w', kbd: 'W', icon: 'calendar-days',
    label: 'Due next week', hint: null,
    plan: function (tasks) { return oneGroup(tasks, { due: 'next week' }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['due']); },
    applies: isOpen,
    message: function () { return 'Due next week'; },
  },
  {
    id: 'snooze', key: 's', kbd: 'S', icon: 'clock', menu: 'starts',
    label: 'Snooze…', hint: 'tomorrow · this weekend · next week · a date',
    plan: function (tasks, phrase) { return oneGroup(tasks, { starts: phrase }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['starts']); },
    applies: isOpen,
    message: function (tasks, arg, after) {
      const s = after && after.length === 1 ? after[0].starts : null;
      return s ? 'Snoozed to ' + fmtDay(s) : 'Snoozed';
    },
  },
  {
    id: 'priority', key: 'p', kbd: 'P', icon: 'activity',
    label: 'Cycle priority', hint: 'none, low, medium, then high; each task from its own',
    plan: function (tasks) {
      return groupByCurrent(tasks, ['priority'], function (t) { return nextPriority(t.priority); });
    },
    invert: function (tasks) { return groupByCurrent(tasks, ['priority']); },
    applies: function () { return true; },
    message: function (tasks) {
      return tasks.length === 1 ? 'Priority ' + nextPriority(tasks[0].priority) : 'Priority cycled';
    },
  },
];

// The statuses a row moves between by hand. Cancelled has no key (it is rare,
// and a stray digit should not close a task) but the row menu offers it.
STATUS_KEYS.concat([[null, 'cancelled']]).forEach(function (pair) {
  ACTIONS.push({
    id: 'status-' + pair[1], key: pair[0], kbd: pair[0], icon: 'circle-dot',
    label: 'Status: ' + pair[1], hint: null,
    plan: function (tasks) { return oneGroup(tasks, { status: pair[1] }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['status']); },
    // a closed row has Reopen instead of a list of statuses to land on
    applies: function (t) { return isOpen(t) && t.status !== pair[1]; },
    message: function () { return 'Status ' + pair[1]; },
  });
});

/** @returns {object|null} the action with this id */
export function actionById(id) {
  return ACTIONS.find(function (a) { return a.id === id; }) || null;
}

// --------------------------------------------------------------- results
/**
 * The failed rows of a bulk call's per-id `results` (a batch is not
 * all-or-nothing), as `{id, message}`.
 * @param {Array<object>|undefined} results
 * @returns {Array<{id:number, message:string}>}
 */
export function failedOf(results) {
  return (results || []).filter(function (r) { return !r.ok; }).map(function (r) {
    return { id: r.id, message: (r.error && r.error.message) || 'failed' };
  });
}

/**
 * The toast every bulk path shows when part of a batch failed — how many went
 * through, how many did not, and the first reason.
 * @param {number} count   how many succeeded
 * @param {string} verb    what happened to them ("updated", "deleted")
 * @param {Array<{id:number, message:string}>} failed   non-empty, from failedOf
 */
export function failureText(count, verb, failed) {
  const first = failed[0];
  return count + ' ' + verb + ' · ' + failed.length + ' failed (#' + first.id + ': ' + first.message + ')';
}

// --------------------------------------------------------------- runner
/**
 * The one runner every surface commits through: write, refresh, say what
 * happened, arm the undo.
 * @param {{write: (ids:number[], changes:object) => Promise<any>,
 *          refresh: () => Promise<any>}} handlers
 *        `write` is one POST /api/tasks/bulk; `refresh` re-reads the views.
 * @returns {{run: Function, undo: Function, undoLabel: () => (string|null), isBusy: () => boolean}}
 */
export function createActions(handlers) {
  let undoBuf = null;       // {groups, at, label} — one level, expires with its toast
  let busy = false;         // one action at a time; a held key must not double-post

  async function writeGroups(groups) {
    let updated = 0;
    const failed = [];
    const after = new Map();
    for (const g of groups) {
      if (!g.ids.length) continue;
      let res;
      try {
        res = await handlers.write(g.ids, g.changes);
      } catch (err) {
        g.ids.forEach(function (id) { failed.push({ id: id, message: err.message || 'failed' }); });
        continue;
      }
      (res.results || []).forEach(function (r) {
        if (r.ok) { updated += 1; after.set(r.id, r.task || null); }
      });
      failed.push(...failedOf(res.results));
    }
    return { updated: updated, failed: failed, after: after };
  }

  /**
   * Commit `action` on `tasks` (their current summaries — undo needs the real
   * prior values). Resolves true when it ran, false when another action was
   * still in flight (nothing was written).
   * @param {object} action        an ACTIONS entry
   * @param {Array<object>} tasks
   * @param {*} [arg]              the value a `menu` action asked for
   * @param {{afterRefresh?: () => void}} [opts]  runs once the views are rebuilt
   *        (the keymap puts focus back there), before the toast
   */
  async function run(action, tasks, arg, opts) {
    if (busy) return false;
    busy = true;
    try {
      const out = await writeGroups(action.plan(tasks, arg));
      await handlers.refresh();
      if (opts && opts.afterRefresh) opts.afterRefresh();
      if (out.failed.length) {
        toast(failureText(out.updated, 'updated', out.failed), 'error');
        undoBuf = null;                    // a half-applied change is not one thing to undo
        return true;
      }
      // Only the tasks that actually changed are worth putting back.
      const done = tasks.filter(function (t) { return out.after.has(t.id); });
      const after = done.map(function (t) { return out.after.get(t.id); }).filter(Boolean);
      const message = action.message(done.length ? done : tasks, arg, after);
      const label = tasks.length > 1 ? tasks.length + ' tasks · ' + message.toLowerCase() : message;
      undoBuf = { groups: action.invert(done, arg), at: Date.now(), label: message.toLowerCase() };
      toast(label, 'success', { label: 'Undo (Z)', onClick: function () { return undo(opts); } });
      return true;
    } finally {
      busy = false;
    }
  }

  /** Put the last change back, while its toast is still up. */
  async function undo(opts) {
    if (!undoBuf || Date.now() - undoBuf.at > ACTION_TTL_MS) {
      toast('Nothing to undo — the last change is out of the undo window', 'error');
      return;
    }
    if (busy) return;
    busy = true;
    const groups = undoBuf.groups;
    const label = undoBuf.label;
    undoBuf = null;                          // single level: no undoing the undo
    try {
      const out = await writeGroups(groups);
      await handlers.refresh();
      if (opts && opts.afterRefresh) opts.afterRefresh();
      if (out.failed.length) toast(failureText(out.updated, 'updated', out.failed), 'error');
      else toast('Undone — ' + label, 'success');
    } finally {
      busy = false;
    }
  }

  return {
    run: run,
    undo: undo,
    undoLabel: function () { return undoBuf ? undoBuf.label : null; },
    isBusy: function () { return busy; },
  };
}
