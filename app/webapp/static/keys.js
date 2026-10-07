/* task-os — single-key row actions, one-level undo, and the shortcuts sheet (#99).
 *
 * Triage speed without a mouse: with a row focused (Board · Today · the
 * Search tab's task hits) one key does the thing —
 *
 *   e  complete   1-3 status   t/w due tomorrow / next week
 *   s  snooze     p   priority cycle          z undo     ? this list
 *
 * and with tasks ticked (Select mode, #81) the same key does it to the whole
 * selection.
 *
 * The actions themselves, their one write path and the undo live in
 * actions.js (#311), which the row's own controls read too. This file owns
 * what is keyboard-only: which row a key means, putting focus back after the
 * write, the snooze popover a key opens, the shortcuts sheet, and the palette
 * entries (`commands()`, which is how the keys are *visible* rather than
 * folklore) — a key added to the table shows up in all three or in none.
 */

'use strict';

import { ACTIONS } from './actions.js';
import { modalCard } from './modal.js';
import * as selection from './selection.js';
import { closeDatePicker, isDatePickerOpen, openDatePicker } from './snooze.js';
import { toast } from './toast.js';

/** A task row in a view whose rows are action targets. */
const ROW = '.trow[data-id]';
/** Focus inside one of these belongs to the widget, not to the keymap. */
const OWNS_ITS_KEYS = '.snooze, .snooze-pop, .row-menu, .msel, .folder-picker, .toast, .bulk-bar';


/** The keys that are not row actions — shown in the sheet, handled elsewhere. */
const GETTING_AROUND = [
  ['Tab', 'move between rows'],
  ['Enter', 'open the focused task'],
  ['Space', 'tick the row while Select mode is on'],
  ['Ctrl K', 'the command palette (Cmd K on a Mac)'],
  ['Esc', 'close the drawer, then leave Select mode'],
];

// ---------------------------------------------------------------- mount
/**
 * @param {HTMLDialogElement} helpDialog   the (empty) shortcuts sheet shell
 * @param {{actions: ReturnType<import('./actions.js').createActions>,
 *          resolveTask: (id:number) => Promise<object|null>,
 *          isBlocked: () => boolean}} handlers
 *        `actions` is the app's one runner (actions.js); `isBlocked` is true
 *        while something else owns the keyboard (the drawer).
 * @returns {{commands: () => Array<object>, openHelp: () => void}}
 */
export function mountKeys(helpDialog, handlers) {
  const actions = handlers.actions;
  let resolving = false;    // a key's tasks are being looked up; a held key must not double-post
  let lastRowId = null;     // the row that had focus before the palette took it

  // ------------------------------------------------------------ targets
  function rowOf(el) {
    const row = el && el.closest ? el.closest(ROW) : null;
    return row || null;
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

  /** The runner's options for a write whose focus belongs back on `rec`. */
  function refocus(rec) {
    return { afterRefresh: function () { restoreFocus(rec); } };
  }

  /** The row the palette should act on: the live focus, else the last one. */
  function rememberedRow() {
    const live = rowOf(document.activeElement);
    if (live) return live;
    if (lastRowId == null) return null;
    const all = document.querySelectorAll('.trow[data-id="' + lastRowId + '"]');
    return Array.from(all).find(function (r) { return r.offsetParent !== null; }) || null;
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

  function runUndo() {
    return actions.undo(refocus(focusRecord(rowOf(document.activeElement))));
  }

  // ---------------------------------------------------------- date picker
  /** The date picker beside whatever is focused (snooze.js) — the tabs whose
   *  rows carry no date control get the same options. */
  function askDate(action, tasks, rec, anchor) {
    openDatePicker(tasks[0], action.menu, anchor, function (phrase) {
      actions.run(action, tasks, phrase, refocus(rec));
    });
  }

  // ------------------------------------------------------------ perform
  async function perform(action, source) {
    if (resolving || isDatePickerOpen() || actions.isBusy()) return;
    const tgt = target(source);
    if (!tgt) {
      toast('Focus a task row first — Tab moves between rows, ? lists the keys', 'error');
      return;
    }
    const rec = focusRecord(tgt.row);
    resolving = true;
    let tasks;
    try {
      const resolved = await Promise.all(tgt.ids.map(function (id) { return handlers.resolveTask(id); }));
      tasks = resolved.filter(Boolean);
    } finally {
      resolving = false;
    }
    if (!tasks.length) {
      toast('That task is no longer on the list', 'error');
      return;
    }
    // While the picker is up, it is what blocks a second action.
    if (action.menu) {
      askDate(action, tasks, rec, tgt.row || document.querySelector('.bulk-bar:not([hidden])'));
      return;
    }
    await actions.run(action, tasks, undefined, refocus(rec));
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
    const card = modalCard({
      cardClass: 'keys-card', title: 'Keyboard shortcuts', titleId: 'keysHelpTitle',
      closeLabel: 'Close', onClose: function () { helpDialog.close(); },
    }).card;

    const lead = document.createElement('p');
    lead.className = 'keys-lead muted';
    lead.textContent = 'With a row focused these act on that task; with tasks ticked they act on the whole selection.';
    card.appendChild(lead);

    const acts = document.createElement('div');
    acts.className = 'keys-rows';
    ACTIONS.forEach(function (a) { if (a.kbd) acts.appendChild(keyRow(a.kbd, a.label, a.hint)); });
    acts.appendChild(keyRow('.', 'The row menu (⋯)', 'every action for the focused row; also the menu key or Shift F10'));
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

  /** `.` opens the focused row's ⋯ menu — its kebab's own toggle, so the
   *  keyboard gets exactly the menu a tap gets (the menu key and Shift F10
   *  arrive as a contextmenu event on the row, which rows.js routes the same
   *  way). A desktop grid row has no menu; the key then does nothing. */
  function openRowMenu(ev) {
    const row = rowOf(document.activeElement);
    const kebab = row ? row.querySelector('.trow-kebab') : null;
    if (!kebab) return;
    ev.preventDefault();
    kebab.click();
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
      // Escape closes the date picker and stops there: app.js's Escape would
      // otherwise also leave Select mode, throwing away the very selection
      // this menu was about to snooze. This listener is registered *before*
      // that one (see boot()), which is what lets it stop the chain.
      if (isDatePickerOpen()) { closeDatePicker(); ev.stopImmediatePropagation(); }
      return;
    }
    if (isTyping(ev.target)) return;
    if (ev.target.closest && ev.target.closest(OWNS_ITS_KEYS)) return;
    if (helpDialog.open) return;
    if (document.querySelector('dialog[open]')) return;   // the palette, quick-add
    if (handlers.isBlocked()) return;                     // the drawer owns the keys
    if (ev.key === '?') { ev.preventDefault(); openHelp(); return; }
    if (ev.key === 'z' || ev.key === 'Z') { ev.preventDefault(); runUndo(); return; }
    if (ev.key === '.') { openRowMenu(ev); return; }
    const action = ACTIONS.find(function (a) { return a.key === ev.key.toLowerCase(); });
    if (!action) return;
    ev.preventDefault();
    perform(action, 'key');
  });


  return {
    openHelp: openHelp,
    /** Is there a row focused / ticked — i.e. would a key do anything now? */
    hasTarget: function () { return !!target('palette'); },
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
        hint: actions.undoLabel() || 'nothing to undo',
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
