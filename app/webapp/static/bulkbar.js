/* task-os — the bulk-action bar: what you do with a selection.
 *
 * While Select mode is on and at least one task is ticked, this bar TAKES OVER
 * the pane's top strip (the text filter and the quick-add +) rather than
 * stacking a third row above the board: the pane keeps its height, and on the
 * phone nothing lands near the floating bottom-nav pill.
 *
 *   ☑ 3 selected   📅 Move   [Set status…▾]   👤 Set owner…   🗑   ✕
 *
 * One line, and every control the same square height as the strip's own
 * buttons. Two edits, both applying the moment they are given a value — the
 * same commit gesture the single-task controls use (a status applies on
 * change; a date applies on its pick in the date sheet), so nothing here needs a Save
 * the rest of the app doesn't have. `complete` is offered alongside the plain
 * statuses because the selection may hold recurring tasks; the server decides
 * per task what it means (the single-task semantics, applied in bulk). The third
 * action, delete, is the one that asks first — the caller owns the
 * confirmation and the request; the bar only locks while it runs.
 *
 * Set owner… is there only when the install has two or more members:
 * a square like Move, so a phone strip still has one elastic control, whose
 * native select is the square's whole face (transparent) — the platform
 * picker opens on a tap, the owner applies on its pick like a status.
 *
 * Mounted once per pane (Board, Today); every instance reads the one selection
 * store, so both bars always say the same number.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES } from './format.js';
import * as selection from './selection.js';
import { openDatePicker } from './snooze.js';

const STATUS_PLACEHOLDER = '';

/** A square `.icon-button` with its glyph, tooltip and accessible name. */
function iconButton(cls, title, label, glyph) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'icon-button ' + cls;
  b.title = title;
  b.setAttribute('aria-label', label);
  b.innerHTML = icon(glyph);
  return b;
}

function setDisabled(controls, on) {
  controls.forEach(function (c) { c.disabled = on; });
}

/** "☑ N selected" — the number lives in `.bulk-n`; only the word is droppable. */
function countEl() {
  const count = document.createElement('span');
  count.className = 'bulk-count';
  count.innerHTML = icon('square-check');
  const countText = document.createElement('span');
  countText.className = 'bulk-n';
  const countWord = document.createElement('span');
  countWord.className = 'bulk-word';
  countWord.textContent = 'selected';
  count.append(countText, countWord);
  return count;
}

/** Set status…: the placeholder, then every status, `complete` included. */
function statusSelect() {
  const status = document.createElement('select');
  status.className = 'select-native bulk-status';
  status.setAttribute('aria-label', 'Set status of the selected tasks');
  const placeholder = document.createElement('option');
  placeholder.value = STATUS_PLACEHOLDER;
  placeholder.textContent = 'Set status…';
  status.appendChild(placeholder);
  STATUSES.forEach(function (s) {
    // `complete` sits where it sits on a recurring row: right before `done`
    if (s === 'done') {
      const c = document.createElement('option');
      c.value = 'complete';
      c.textContent = 'complete';
      status.appendChild(c);
    }
    const o = document.createElement('option');
    o.value = s;
    o.textContent = s;
    status.appendChild(o);
  });
  return status;
}

/** Set owner…: a square whose face is its (transparent) native select. */
function ownerControl() {
  const owner = document.createElement('label');
  owner.className = 'icon-button bulk-owner';
  owner.title = 'Set owner of the selected tasks…';
  owner.innerHTML = icon('user');
  const ownerSel = document.createElement('select');
  ownerSel.className = 'bulk-owner-select';
  ownerSel.setAttribute('aria-label', 'Set owner of the selected tasks');
  owner.appendChild(ownerSel);
  return owner;
}

/** Set owner…'s options: the placeholder, then one per member. */
function fillOwners(sel, members) {
  sel.textContent = '';
  const ph = document.createElement('option');
  ph.value = STATUS_PLACEHOLDER;
  ph.textContent = 'Set owner…';
  sel.appendChild(ph);
  members.forEach(function (m) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = m.name;
    sel.appendChild(o);
  });
}

/**
 * @param {HTMLElement} host   the `.bulk-bar` container in a pane's top strip
 * @param {{onApply: (changes: {status?: string, due?: string, owner?: string}) => Promise<any>,
 *          onDelete: () => Promise<any>,
 *          onExit: () => void,
 *          members: () => Array<{id:string,name:string}>}} handlers
 * @returns {{render: () => void}}
 */
export function mountBulkBar(host, handlers) {
  host.classList.add('bulk-bar');
  host.setAttribute('role', 'toolbar');
  host.setAttribute('aria-label', 'Bulk actions');

  // The number is the one thing that must survive a narrow phone — it is what
  // says how much this next click changes. Only the word "selected" is
  // droppable (CSS), never the count itself.
  const count = countEl();
  const countText = count.querySelector('.bulk-n');

  const status = statusSelect();

  // Move is the bar's first action, as it is the row's: the one date
  // sheet every re-date opens (snooze.js) — the push-out phrases, Pick a date…
  // and No date — so a selection moves the way a single row does.
  const move = iconButton('bulk-move', 'Move the selected tasks…', 'Move the selected tasks to another date', 'calendar-days');
  move.setAttribute('aria-haspopup', 'dialog');
  move.addEventListener('click', function () {
    if (busy) return;
    const n = selection.size();
    const subject = { title: n + ' selected task' + (n === 1 ? '' : 's'), due: null, clearable: true };
    openDatePicker(subject, 'due', host, function (phrase) { apply({ due: phrase }, function () {}); });
  });

  // Set owner…: the square's face is its native select, so the picker
  // is the platform's; its options follow the members list on every render.
  const owner = ownerControl();
  const ownerSel = owner.querySelector('select');
  let ownerKey = null;
  function syncOwners() {
    const members = (handlers.members && handlers.members()) || [];
    owner.hidden = members.length < 2;
    const key = JSON.stringify(members);
    if (key === ownerKey) return;
    ownerKey = key;
    fillOwners(ownerSel, members);
  }
  applyOnPick(ownerSel, 'owner');

  // Delete: the caller confirms and posts; this square only locks the
  // bar while that runs, exactly like an apply.
  const del = iconButton('danger bulk-delete', 'Delete the selected tasks', 'Delete the selected tasks', 'trash-2');
  del.addEventListener('click', function () { locked(function () { return handlers.onDelete(); }, function () {}); });

  // the one icon button the strip's + wears too, so the bar's three
  // glyphs are one control by construction, not by three rules agreeing
  const exit = iconButton('bulk-exit', 'Leave select mode', 'Leave select mode', 'x');
  exit.addEventListener('click', function () { handlers.onExit(); });

  applyOnPick(status, 'status');

  let busy = false;
  /** A select that applies `{[field]: value}` on its pick, then shows its placeholder again. */
  function applyOnPick(sel, field) {
    sel.addEventListener('change', function () {
      const value = sel.value;
      if (value === STATUS_PLACEHOLDER) return;
      const changes = {};
      changes[field] = value;
      apply(changes, function () { sel.value = STATUS_PLACEHOLDER; });
    });
  }
  function apply(changes, reset) {
    locked(function () { return handlers.onApply(changes); }, reset);
  }

  /** Run `work` with the controls locked, so a second click can't double-post;
   *  `reset` runs whether it succeeded or not — a control's value said what to
   *  do once, not what the selection now is. */
  function locked(work, reset) {
    if (busy) return;
    busy = true;
    const controls = [move, status, ownerSel, del];
    setDisabled(controls, true);
    Promise.resolve(work())
      .catch(function () { /* toasted by the caller */ })
      .finally(function () {
        busy = false;
        reset();
        setDisabled(controls, false);
      });
  }

  host.append(count, move, status, owner, del, exit);

  function render() {
    const n = selection.size();
    host.hidden = !(selection.isActive() && n > 0);
    syncOwners();
    countText.textContent = String(n);
    // the visible text can lose the word on a narrow phone, so the whole
    // phrase lives on the label screen readers and the tests read
    count.setAttribute('aria-label', n + ' selected');
  }

  render();
  return { render: render };
}
