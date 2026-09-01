/* task-os — single-key row actions, one-level undo, and the shortcuts sheet (#99).
 *
 * Triage speed without a mouse: with a row focused (Board · Table · Today ·
 * the Search tab's task hits) one key does the thing —
 *
 *   e  complete   1-4 status   t/w due tomorrow / next week
 *   s  snooze     p   priority cycle          z undo     ? this list
 *
 * and with tasks ticked (Select mode, #81) the same key does it to the whole
 * selection. The Tree is deliberately not a target: its keyboard model is
 * navigation-first (↑↓→← Enter) and stays that way.
 *
 * ONE table drives three surfaces. `ACTIONS` below is read by the keydown
 * handler, by the shortcuts sheet, and by the command palette (`commands()`,
 * which is how the keys are *visible* rather than folklore) — a key added
 * here shows up in all three or in none.
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
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { fmtDay } from './format.js';
import * as selection from './selection.js';
import { snoozeMenu } from './snooze.js';
import { ACTION_TTL_MS, toast } from './toast.js';

/** Ascending, wrapping at the top — one press always moves, `none` included. */
const PRIORITIES = ['none', 'low', 'medium', 'high'];
const STATUS_KEYS = [['1', 'inbox'], ['2', 'todo'], ['3', 'doing'], ['4', 'standby']];
/** A task row in a view whose rows are action targets. */
const ROW = '.trow[data-id], tr.task-row[data-id]';
const NOT_A_TARGET = '#paneTree';
/** Focus inside one of these belongs to the widget, not to the keymap. */
const OWNS_ITS_KEYS = '.snooze, .snooze-pop, .msel, .folder-picker, .toast, .bulk-bar';

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

function nextPriority(p) {
  const i = PRIORITIES.indexOf(p || 'none');
  return PRIORITIES[(i < 0 ? 0 : i + 1) % PRIORITIES.length];
}

// -------------------------------------------------------------- actions
/**
 * The keymap. Each action declares:
 *   plan(tasks, arg)   → the groups to write
 *   invert(tasks, arg) → the groups that put the prior values back
 *   message(tasks, arg)→ what the toast says (the count is prefixed by the caller)
 * `menu: true` means the action asks for a value first (snooze) and commits
 * from the popover instead of straight away.
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
    message: function () { return 'Completed'; },
  },
  {
    id: 'due-tomorrow', key: 't', kbd: 'T', icon: 'calendar-days',
    label: 'Due tomorrow', hint: null,
    plan: function (tasks) { return oneGroup(tasks, { due: 'tomorrow' }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['due']); },
    message: function () { return 'Due tomorrow'; },
  },
  {
    id: 'due-next-week', key: 'w', kbd: 'W', icon: 'calendar-days',
    label: 'Due next week', hint: null,
    plan: function (tasks) { return oneGroup(tasks, { due: 'next week' }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['due']); },
    message: function () { return 'Due next week'; },
  },
  {
    id: 'snooze', key: 's', kbd: 'S', icon: 'clock', menu: true,
    label: 'Snooze…', hint: 'tomorrow · this weekend · next week · a date',
    plan: function (tasks, phrase) { return oneGroup(tasks, { starts: phrase }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['starts']); },
    message: function (tasks) {
      const s = tasks.length === 1 ? tasks[0].starts : null;
      return s ? 'Snoozed to ' + fmtDay(s) : 'Snoozed';
    },
  },
  {
    id: 'priority', key: 'p', kbd: 'P', icon: 'activity',
    label: 'Cycle priority', hint: 'none → low → medium → high, each task from its own',
    plan: function (tasks) {
      return groupByCurrent(tasks, ['priority'], function (t) { return nextPriority(t.priority); });
    },
    invert: function (tasks) { return groupByCurrent(tasks, ['priority']); },
    message: function (tasks) {
      return tasks.length === 1 ? 'Priority ' + nextPriority(tasks[0].priority) : 'Priority cycled';
    },
  },
];

STATUS_KEYS.forEach(function (pair) {
  ACTIONS.push({
    id: 'status-' + pair[1], key: pair[0], kbd: pair[0], icon: 'circle-dot',
    label: 'Status: ' + pair[1], hint: null,
    plan: function (tasks) { return oneGroup(tasks, { status: pair[1] }); },
    invert: function (tasks) { return groupByCurrent(tasks, ['status']); },
    message: function () { return 'Status ' + pair[1]; },
  });
});

/** The keys that are not row actions — shown in the sheet, handled elsewhere. */
const GETTING_AROUND = [
  ['Tab', 'move between rows'],
  ['Enter', 'open the focused task'],
  ['Space', 'tick the row while Select mode is on'],
  ['Ctrl K', 'the command palette (⌘K on a Mac)'],
  ['Esc', 'close the drawer, then leave Select mode'],
];

// ---------------------------------------------------------------- mount
/**
 * @param {HTMLDialogElement} helpDialog   the (empty) shortcuts sheet shell
 * @param {{write: (ids:number[], changes:object) => Promise<any>,
 *          refresh: () => Promise<any>,
 *          resolveTask: (id:number) => Promise<object|null>,
 *          isBlocked: () => boolean}} handlers
 *        `write` is one POST /api/tasks/bulk; `isBlocked` is true while
 *        something else owns the keyboard (the drawer).
 * @returns {{commands: () => Array<object>, openHelp: () => void}}
 */
export function mountKeys(helpDialog, handlers) {
  let undo = null;          // {groups, at, label} — one level, expires with its toast
  let busy = false;         // one action at a time; a held key must not double-post
  let lastRowId = null;     // the row that had focus before the palette took it
  let pop = null;           // the open snooze popover, if any

  // ------------------------------------------------------------ targets
  function rowOf(el) {
    const row = el && el.closest ? el.closest(ROW) : null;
    if (!row || row.closest(NOT_A_TARGET)) return null;
    return row;
  }

  function paneIdOf(row) {
    const pane = row.closest('.pane');
    return pane ? pane.id : null;
  }

  /** Where focus should land again once the views have been rebuilt. */
  function focusRecord(row) {
    if (!row) return null;
    const paneId = paneIdOf(row);
    if (!paneId) return null;
    const rows = Array.from(document.getElementById(paneId).querySelectorAll(ROW));
    return { paneId: paneId, id: Number(row.dataset.id), index: Math.max(0, rows.indexOf(row)) };
  }

  /** The same task after a re-render, else whatever took its place — so `e`
   *  three times in a row walks a column instead of dropping focus on <body>. */
  function restoreFocus(rec) {
    if (!rec) return;
    const pane = document.getElementById(rec.paneId);
    if (!pane || pane.hidden) return;
    const rows = Array.from(pane.querySelectorAll(ROW));
    if (!rows.length) return;
    const same = rows.find(function (r) { return Number(r.dataset.id) === rec.id; });
    const row = same || rows[Math.min(rec.index, rows.length - 1)];
    const el = row.matches('tr') ? row : row.querySelector('.trow-main');
    if (!el) return;
    el.tabIndex = 0;
    el.focus({ preventScroll: true });
    el.scrollIntoView({ block: 'nearest' });
  }

  /** The row the palette should act on: the live focus, else the last one. */
  function rememberedRow() {
    const live = rowOf(document.activeElement);
    if (live) return live;
    if (lastRowId == null) return null;
    const all = document.querySelectorAll('.trow[data-id="' + lastRowId + '"], tr.task-row[data-id="' + lastRowId + '"]');
    return Array.from(all).find(function (r) { return !r.closest(NOT_A_TARGET) && r.offsetParent !== null; }) || null;
  }

  /** `{ids, row}` — the selection when there is one, else the focused row.
   *
   *  A keyed action leaves the ticks alone (the bulk bar clears them, because
   *  there the value control was the whole gesture): keys are meant to come in
   *  runs — status, then a due date, then a snooze — over one picked set. */
  function target(source) {
    if (selection.isActive() && selection.size()) {
      return { ids: selection.selectedIds(), row: rememberedRow() };
    }
    const row = source === 'key' ? rowOf(document.activeElement) : rememberedRow();
    if (!row) return null;
    return { ids: [Number(row.dataset.id)], row: row };
  }

  // ------------------------------------------------------------- writing
  async function writeGroups(groups) {
    let updated = 0;
    const failed = [];
    const okIds = new Set();
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
        if (r.ok) { updated += 1; okIds.add(r.id); } else {
          failed.push({ id: r.id, message: (r.error && r.error.message) || 'failed' });
        }
      });
    }
    return { updated: updated, failed: failed, okIds: okIds };
  }

  function failureText(out) {
    const first = out.failed[0];
    return out.updated + ' updated · ' + out.failed.length + ' failed (#' + first.id + ': ' + first.message + ')';
  }

  /** Write, refresh, put focus back, say what happened, arm the undo. */
  async function commit(action, tasks, arg, rec) {
    const out = await writeGroups(action.plan(tasks, arg));
    await handlers.refresh();
    restoreFocus(rec);
    if (out.failed.length) {
      toast(failureText(out), 'error');
      undo = null;                       // a half-applied change is not one thing to undo
      return;
    }
    // Only the tasks that actually changed are worth putting back.
    const done = tasks.filter(function (t) { return out.okIds.has(t.id); });
    const message = action.message(done.length ? done : tasks, arg);
    const label = tasks.length > 1 ? tasks.length + ' tasks · ' + message.toLowerCase() : message;
    undo = { groups: action.invert(done, arg), at: Date.now(), label: message.toLowerCase() };
    toast(label, 'success', { label: 'Undo (Z)', onClick: runUndo });
  }

  async function runUndo() {
    if (!undo || Date.now() - undo.at > ACTION_TTL_MS) {
      toast('Nothing to undo — the last change is out of the undo window', 'error');
      return;
    }
    if (busy) return;
    busy = true;
    const groups = undo.groups;
    const label = undo.label;
    undo = null;                          // single level: no undoing the undo
    const rec = focusRecord(rowOf(document.activeElement));
    try {
      const out = await writeGroups(groups);
      await handlers.refresh();
      restoreFocus(rec);
      if (out.failed.length) toast(failureText(out), 'error');
      else toast('Undone — ' + label, 'success');
    } finally {
      busy = false;
    }
  }

  // -------------------------------------------------------- snooze popover
  function closePop() {
    if (!pop) return;
    pop.remove();
    pop = null;
  }

  /** The row's snooze menu, mounted beside whatever is focused — the tabs
   *  whose rows carry no snooze button get the same four options. */
  function openSnooze(action, tasks, rec, anchor) {
    closePop();
    pop = document.createElement('div');
    pop.className = 'snooze-pop';
    pop.appendChild(snoozeMenu(tasks[0], function (phrase) {
      closePop();
      busy = true;
      commit(action, tasks, phrase, rec).finally(function () { busy = false; });
    }));
    document.body.appendChild(pop);
    const r = (anchor || document.body).getBoundingClientRect();
    const w = pop.offsetWidth;
    pop.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + 'px';
    pop.style.top = Math.min(r.bottom + 4, window.innerHeight - pop.offsetHeight - 8) + 'px';
    const first = pop.querySelector('.snooze-opt');
    if (first) first.focus();
  }

  // ------------------------------------------------------------ perform
  async function perform(action, source) {
    if (busy || pop) return;
    const tgt = target(source);
    if (!tgt) {
      toast('Focus a task row first — Tab moves between rows, ? lists the keys', 'error');
      return;
    }
    const rec = focusRecord(tgt.row);
    busy = true;
    try {
      const resolved = await Promise.all(tgt.ids.map(function (id) { return handlers.resolveTask(id); }));
      const tasks = resolved.filter(Boolean);
      if (!tasks.length) {
        toast('That task is no longer on the list', 'error');
        return;
      }
      if (action.menu) {
        openSnooze(action, tasks, rec, tgt.row || document.querySelector('.bulk-bar:not([hidden])'));
        return;
      }
      await commit(action, tasks, undefined, rec);
    } finally {
      // The popover path releases the lock here and re-takes it when it
      // commits; while it is up, `pop` is what blocks a second action.
      busy = false;
    }
  }

  // --------------------------------------------------------- help sheet
  function keyRow(keyText, label, hint) {
    const row = document.createElement('div');
    row.className = 'keys-row';
    const combo = document.createElement('span');
    combo.className = 'keys-combo';
    keyText.split(' ').forEach(function (k) {
      const kbd = document.createElement('kbd');
      kbd.textContent = k;
      combo.appendChild(kbd);
    });
    row.appendChild(combo);
    const main = document.createElement('div');
    main.className = 'keys-main';
    const l = document.createElement('div');
    l.className = 'keys-label';
    l.textContent = label;
    main.appendChild(l);
    if (hint) {
      const h = document.createElement('div');
      h.className = 'keys-hint muted';
      h.textContent = hint;
      main.appendChild(h);
    }
    row.appendChild(main);
    return row;
  }

  function buildHelp() {
    const card = document.createElement('div');
    card.className = 'detail-card keys-card';

    const head = document.createElement('div');
    head.className = 'detail-header';
    const h = document.createElement('h2');
    h.id = 'keysHelpTitle';
    h.textContent = 'Keyboard shortcuts';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'detail-close';
    close.setAttribute('aria-label', 'Close');
    close.innerHTML = icon('x');
    close.addEventListener('click', function () { helpDialog.close(); });
    head.append(h, close);
    card.appendChild(head);

    const lead = document.createElement('p');
    lead.className = 'keys-lead muted';
    lead.textContent = 'With a row focused these act on that task; with tasks ticked they act on the whole selection. Not on the Tree, where the arrows walk the outline.';
    card.appendChild(lead);

    const acts = document.createElement('div');
    acts.className = 'keys-rows';
    ACTIONS.forEach(function (a) { acts.appendChild(keyRow(a.kbd, a.label, a.hint)); });
    acts.appendChild(keyRow('Z', 'Undo the last change', 'one level, while its toast is up'));
    acts.appendChild(keyRow('?', 'This list', null));
    card.appendChild(acts);

    const nav = document.createElement('h3');
    nav.className = 'keys-sub';
    nav.textContent = 'Getting around';
    card.appendChild(nav);
    const around = document.createElement('div');
    around.className = 'keys-rows';
    GETTING_AROUND.forEach(function (p) { around.appendChild(keyRow(p[0], p[1], null)); });
    card.appendChild(around);

    helpDialog.replaceChildren(card);
  }

  function openHelp() {
    if (helpDialog.open) return;
    if (!helpDialog.firstElementChild) buildHelp();
    helpDialog.showModal();
  }

  // ------------------------------------------------------------- wiring
  function isTyping(el) {
    if (!el || !el.closest) return false;
    return !!el.closest('input, textarea, select, [contenteditable="true"]');
  }

  document.addEventListener('focusin', function (ev) {
    const row = rowOf(ev.target);
    if (row) lastRowId = Number(row.dataset.id);
  });

  document.addEventListener('keydown', function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === 'Escape') {
      // Escape closes the popover and stops there: app.js's Escape would
      // otherwise also leave Select mode, throwing away the very selection
      // this menu was about to snooze. This listener is registered *before*
      // that one (see boot()), which is what lets it stop the chain.
      if (pop) { closePop(); ev.stopImmediatePropagation(); }
      return;
    }
    if (isTyping(ev.target)) return;
    if (ev.target.closest && ev.target.closest(OWNS_ITS_KEYS)) return;
    if (helpDialog.open) return;
    if (document.querySelector('dialog[open]')) return;   // the palette, quick-add
    if (handlers.isBlocked()) return;                     // the drawer owns the keys
    if (ev.key === '?') { ev.preventDefault(); openHelp(); return; }
    if (ev.key === 'z' || ev.key === 'Z') { ev.preventDefault(); runUndo(); return; }
    const action = ACTIONS.find(function (a) { return a.key === ev.key.toLowerCase(); });
    if (!action) return;
    ev.preventDefault();
    perform(action, 'key');
  });

  // An outside click or a scroll closes the popover — it is pinned to the
  // viewport, so a scrolled page would leave it hanging beside nothing.
  document.addEventListener('click', function (ev) {
    if (pop && !pop.contains(ev.target)) closePop();
  });
  window.addEventListener('scroll', closePop, true);

  return {
    openHelp: openHelp,
    /**
     * The same actions as palette commands, each carrying its key — the
     * palette is where a shortcut is *discovered* (the sheet is the reference
     * card). Built per palette open, so the hint names what it will act on.
     */
    commands: function () {
      const tgt = target('palette');
      const n = tgt ? tgt.ids.length : 0;
      const title = tgt && tgt.row ? tgt.row.querySelector('.trow-title, .t-title-text') : null;
      const where = !tgt ? 'focus a row first'
        : (n > 1 ? n + ' selected' : (title ? title.textContent : '#' + tgt.ids[0]));
      return ACTIONS.map(function (a) {
        return {
          id: 'key-' + a.id,
          label: a.label,
          hint: where + (a.hint ? ' · ' + a.hint : ''),
          icon: a.icon,
          kbd: a.kbd,
          run: function () { perform(a, 'palette'); },
        };
      }).concat([{
        id: 'key-undo',
        label: 'Undo the last change',
        hint: undo ? undo.label : 'nothing to undo',
        icon: 'rotate-ccw',
        kbd: 'Z',
        run: runUndo,
      }, {
        id: 'key-help',
        label: 'Keyboard shortcuts',
        hint: 'every key and what it does',
        icon: 'keyboard',
        kbd: '?',
        run: openHelp,
      }]);
    },
  };
}
