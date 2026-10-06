/* task-os — swipe a task row on a touch screen (#311).
 *
 * Swipe right and swipe left each run one row action (by default: complete,
 * and change the date). The gesture is a shortcut, never the only way: the
 * same actions are in the row's ⋯ menu, on the keys and in the palette
 * (WCAG 2.5.1). Only a touch swipes — the mouse never does, because
 * drag-and-drop owns mouse drags — and only an open task's row in a vertical
 * list: the phone Board's columns are a sideways carousel already.
 *
 * Two halves. The top of the file is a pure classifier with no DOM, loaded
 * bare under node by the unit tests: when does a touch become a swipe, which
 * way, and does its release commit. The bottom binds it to a row with Pointer
 * Events and `touch-action: pan-y` (styles.css), so the browser keeps the
 * vertical scroll and this code only ever sees sideways travel — no touchmove
 * listener, no preventDefault on a scroll.
 *
 *   slop        nothing happens for the first 10 px (app-launcher's
 *               long-press-hint MOVE_SLOP_PX)
 *   lock        then it locks sideways when |dx| > 1.5·|dy|, else yields to
 *               the scroll for good; once locked it never unlocks
 *   commit      on release, |dx| ≥ max(96 px, 35 % of the row), or a flick of
 *               ≥ 0.6 px/ms that already travelled 48 px the same way
 *   edges       a touch starting within 20 px of either screen edge is never
 *               tracked: that zone is iOS's edge-back / edge-forward gesture
 *   hold        500 ms without moving stops tracking — long-press stays free
 *
 * One action per side, no second action at a longer distance. Crossing the
 * threshold arms the reveal (its label turns to "Release to …"); backing off
 * disarms it. iOS Safari has no Vibration API, so there is no haptic.
 */

'use strict';

export const SLOP_PX = 10;
export const LOCK_RATIO = 1.5;
export const COMMIT_PX = 96;
export const COMMIT_FRACTION = 0.35;
export const FLICK_PX_PER_MS = 0.6;
export const FLICK_MIN_PX = 48;
export const EDGE_PX = 20;
export const HOLD_MS = 500;

/** May a touch that starts at `x` be tracked at all? */
export function startAllowed(x, viewportWidth) {
  return x >= EDGE_PX && x <= viewportWidth - EDGE_PX;
}

/** 'pending' inside the slop, then 'x' (a swipe) or 'y' (the scroll's). */
export function lockDirection(dx, dy) {
  if (Math.hypot(dx, dy) < SLOP_PX) return 'pending';
  return Math.abs(dx) > LOCK_RATIO * Math.abs(dy) ? 'x' : 'y';
}

/** How far a release has to travel on a row this wide. */
export function commitDistance(rowWidth) {
  return Math.max(COMMIT_PX, COMMIT_FRACTION * rowWidth);
}

/** Is a swipe this far armed (would a release commit, flick aside)? */
export function isArmed(dx, rowWidth) {
  return Math.abs(dx) >= commitDistance(rowWidth);
}

/**
 * Which side a release commits, if any.
 * @param {number} dx          travel at release, px (+ = right)
 * @param {number} rowWidth    px
 * @param {number} velocity    px/ms at release (+ = right)
 * @returns {'right'|'left'|null}
 */
export function releaseSide(dx, rowWidth, velocity) {
  const side = dx > 0 ? 'right' : 'left';
  if (dx === 0) return null;
  if (isArmed(dx, rowWidth)) return side;
  const flick = Math.abs(velocity) >= FLICK_PX_PER_MS && Math.abs(dx) >= FLICK_MIN_PX
    && Math.sign(velocity) === Math.sign(dx);
  return flick ? side : null;
}

// ------------------------------------------------------------- binding
let live = null;   // the one row being swiped; a second pointer is ignored

/**
 * Make one row swipeable.
 * @param {HTMLElement} li
 * @param {{action: (side:'right'|'left') => ({label:string, icon:string}|null),
 *          onCommit: (side:'right'|'left') => any,
 *          icon: (name:string) => string}} opts
 *        `action(side)` names what a side does (null = that side does
 *        nothing); `onCommit` runs it — a right commit after the row has
 *        slid out, a left one after it has sprung back. A right commit
 *        whose promise settles with the row still on the page (the write was
 *        refused, or the task stays — a recurring roll re-renders it) springs
 *        the row back.
 */
export function bindSwipe(li, opts) {
  li.classList.add('is-swipeable');
  let start = null;      // {x, y, t, id}
  let dir = 'pending';
  let side = null;
  let last = null;       // {x, t} — for the release velocity
  let reveal = null;
  let hold = null;

  function setX(px) { li.style.setProperty('--swipe-x', px + 'px'); }

  function paintReveal(dx) {
    const s = dx > 0 ? 'right' : 'left';
    const act = opts.action(s);
    if (!reveal) {
      reveal = document.createElement('span');
      reveal.className = 'trow-reveal';
      reveal.setAttribute('aria-hidden', 'true');
      li.appendChild(reveal);
    }
    if (side !== s) {
      side = s;
      reveal.dataset.side = s;
      reveal.innerHTML = act ? opts.icon(act.icon) : '';
      const label = document.createElement('span');
      label.className = 'trow-reveal-label';
      reveal.appendChild(label);
    }
    const armed = !!act && isArmed(dx, li.offsetWidth);
    reveal.classList.toggle('is-armed', armed);
    reveal.lastChild.textContent = !act ? '' : (armed ? 'Release: ' + act.label : act.label);
  }

  function reset(animate) {
    clearTimeout(hold);
    if (live === li) live = null;
    li.classList.remove('is-swiping');
    li.classList.toggle('is-settling', !!animate);
    setX(0);
    const r = reveal;
    reveal = null;
    side = null;
    start = null;
    dir = 'pending';
    const done = function () {
      li.classList.remove('is-settling');
      if (r && r.parentNode) r.parentNode.removeChild(r);
    };
    if (animate) setTimeout(done, 220); else done();
  }

  li.addEventListener('pointerdown', function (ev) {
    if (ev.pointerType !== 'touch' || !ev.isPrimary || live) return;
    if (!startAllowed(ev.clientX, window.innerWidth)) return;
    if (ev.target.closest('button.trow-kebab, button.trow-done, .trow-extra')) return;
    live = li;
    start = { x: ev.clientX, y: ev.clientY, id: ev.pointerId };
    last = { x: ev.clientX, t: ev.timeStamp, vx: 0 };
    dir = 'pending';
    hold = setTimeout(function () { if (dir === 'pending') reset(false); }, HOLD_MS);
  });

  li.addEventListener('pointermove', function (ev) {
    if (!start || ev.pointerId !== start.id) return;
    const dx = ev.clientX - start.x;
    const dy = ev.clientY - start.y;
    if (dir === 'pending') {
      dir = lockDirection(dx, dy);
      if (dir === 'y') { reset(false); return; }
      if (dir === 'pending') return;
      clearTimeout(hold);
      li.classList.add('is-swiping');
      try { li.setPointerCapture(ev.pointerId); } catch (_) { /* a synthetic pointer */ }
    }
    const dt = ev.timeStamp - last.t;
    if (dt > 0) last = { x: ev.clientX, t: ev.timeStamp, vx: (ev.clientX - last.x) / dt };
    setX(dx);
    paintReveal(dx);
  });

  function release(ev) {
    if (!start || ev.pointerId !== start.id) return;
    if (dir !== 'x') { reset(false); return; }
    const dx = ev.clientX - start.x;
    const s = releaseSide(dx, li.offsetWidth, last.vx);
    const act = s ? opts.action(s) : null;
    // A swipe must not also be the tap that opens the row — but only this
    // gesture's click, if the browser sends one at all: a later tap is a tap.
    const swallow = function (e) { e.stopPropagation(); e.preventDefault(); };
    li.addEventListener('click', swallow, { capture: true, once: true });
    setTimeout(function () { li.removeEventListener('click', swallow, { capture: true }); }, 400);
    if (!act) { reset(true); return; }
    if (s === 'right') {
      li.classList.remove('is-swiping');
      li.classList.add('is-leaving');
      setX(li.offsetWidth);
      setTimeout(function () {
        Promise.resolve(opts.onCommit('right')).finally(function () {
          if (li.isConnected) { li.classList.remove('is-leaving'); reset(true); }
          else if (live === li) live = null;
        });
      }, 200);
      return;
    }
    reset(true);
    opts.onCommit('left');
  }
  li.addEventListener('pointerup', release);
  li.addEventListener('pointercancel', function (ev) {
    if (start && ev.pointerId === start.id) reset(true);
  });
}
