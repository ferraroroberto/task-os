/* task-os — Row actions: the two swipes and the ⋯ menu's list. */

'use strict';

import { ACTIONS, actionById } from '../../actions.js';
import { icon } from '../../_vendored/icons/icons.js';
import { isDefault, rowPrefs, setRowPrefs } from '../../rowprefs.js';

/** Row actions: the two swipes and the ⋯ menu's list, choices from
 *  the one action table. Every change is stored at once (rowprefs.js) and
 *  handed to `ctx.opts.onRowActions`, which redraws the rows — a menu reads its
 *  list when its row is drawn. An action a swipe runs is ticked and locked
 *  in the list, so the menu always keeps the tap path to it (WCAG 2.5.1). */
function renderRowActions(ctx, focusId, focusDir) {
  const p = rowPrefs();
  ctx.els.rowActionsMeta.textContent = isDefault(p) ? 'Default' : 'Custom';
  [[ctx.els.swipeRight, p.right], [ctx.els.swipeLeft, p.left]].forEach(function (pair) {
    const sel = pair[0];
    sel.replaceChildren();
    [['', 'Nothing']].concat(ACTIONS.map(function (a) { return [a.id, a.label]; })).forEach(function (o) {
      const opt = document.createElement('option');
      opt.value = o[0];
      opt.textContent = o[1];
      opt.selected = o[0] === pair[1];
      sel.appendChild(opt);
    });
  });
  // the chosen list in its order, then every other action, unticked
  const rest = ACTIONS.map(function (a) { return a.id; }).filter(function (id) { return p.menu.indexOf(id) < 0; });
  const ids = p.menu.concat(rest);
  ctx.els.rowMenuList.replaceChildren();
  ids.forEach(function (id, i) {
    const a = actionById(id);
    const shown = p.menu.indexOf(id) >= 0;
    const swipe = id === p.right ? 'swipe right' : (id === p.left ? 'swipe left' : null);
    const li = document.createElement('li');
    li.className = 'row-actions-item';
    li.dataset.action = id;
    // A pressed-state square, not a bare checkbox: the .icon-button box is a real
    // 44px target (34 painted + its expansion), which a 16px checkbox is not.
    const listed = shown || !!swipe;
    const tick = document.createElement('button');
    tick.type = 'button';
    tick.className = 'icon-button row-actions-tick';
    tick.setAttribute('aria-pressed', listed ? 'true' : 'false');
    tick.setAttribute('aria-label', 'Show ' + a.label + ' in the menu');
    tick.innerHTML = icon(listed ? 'square-check' : 'square');
    tick.disabled = !!swipe;
    tick.addEventListener('click', function () { toggleMenu(ctx, id, !listed, 'tick'); });
    const name = document.createElement('span');
    name.className = 'row-actions-name';
    name.textContent = a.label;
    li.append(tick, name);
    if (swipe) {
      const hint = document.createElement('span');
      hint.className = 'row-actions-hint muted';
      hint.textContent = 'used by ' + swipe;
      li.appendChild(hint);
    }
    [['up', -1, 'chevron-up'], ['down', 1, 'chevron-down']].forEach(function (m) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'icon-button row-actions-move';
      b.dataset.move = m[0];
      b.setAttribute('aria-label', 'Move ' + a.label + ' ' + m[0]);
      b.innerHTML = icon(m[2]);
      // only a listed action has a place to move; the first can't go up, the last can't go down
      b.disabled = !shown || (m[1] < 0 ? i === 0 : i === p.menu.length - 1);
      b.addEventListener('click', function () { move(ctx, id, m[1], m[0]); });
      li.appendChild(b);
    });
    ctx.els.rowMenuList.appendChild(li);
  });
  if (focusId) {
    // the control just used, on its rebuilt row (a move keeps its direction
    // while it still can go that way)
    const row = '[data-action="' + focusId + '"] ';
    const back = focusDir === 'tick' ? ctx.els.rowMenuList.querySelector(row + '.row-actions-tick')
      : (ctx.els.rowMenuList.querySelector(row + '[data-move="' + focusDir + '"]:not(:disabled)')
        || ctx.els.rowMenuList.querySelector(row + '[data-move]:not(:disabled)'));
    if (back) back.focus();
  }
}

function saveRowActions(ctx, next, focusId, focusDir) {
  setRowPrefs(next);
  renderRowActions(ctx, focusId, focusDir);
  if (ctx.opts.onRowActions) ctx.opts.onRowActions();
}

function toggleMenu(ctx, id, on) {
  const p = rowPrefs();
  const menu = p.menu.filter(function (x) { return x !== id; });
  if (on) menu.push(id);
  saveRowActions(ctx, Object.assign({}, p, { menu: menu }), id, 'tick');
}

function move(ctx, id, by, dir) {
  const p = rowPrefs();
  const menu = p.menu.slice();
  const i = menu.indexOf(id);
  const j = i + by;
  if (i < 0 || j < 0 || j >= menu.length) return;
  menu.splice(i, 1);
  menu.splice(j, 0, id);
  saveRowActions(ctx, Object.assign({}, p, { menu: menu }), id, dir);
}

export function wireRowActions(ctx) {
  ctx.els.swipeRight.addEventListener('change', function () {
    saveRowActions(ctx, Object.assign({}, rowPrefs(), { right: ctx.els.swipeRight.value }));
  });
  ctx.els.swipeLeft.addEventListener('change', function () {
    saveRowActions(ctx, Object.assign({}, rowPrefs(), { left: ctx.els.swipeLeft.value }));
  });
  ctx.els.rowActionsReset.addEventListener('click', function () {
    setRowPrefs(null);
    renderRowActions(ctx);
    if (ctx.opts.onRowActions) ctx.opts.onRowActions();
  });
  renderRowActions(ctx);
}
