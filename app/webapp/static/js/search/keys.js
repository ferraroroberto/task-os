/* task-os — Search: the keyboard. ↓ from the box focuses the first row; on rows
 * ↑↓ move, Enter opens, Esc / `/` go back to the box. Takes the composer's
 * `ctx` first (`input`, `host`, `opts`, `hitByIdx`, `timer`, `last`). */

'use strict';

import { run, schedule } from './load.js';

function primary(ctx, li) {
  const h = ctx.hitByIdx.get(Number(li.dataset.idx));
  if (!h) return;
  if (h.kind === 'tasks') { ctx.opts.onOpenTask(h.task_id); return; }
  const open = li.querySelector('[data-act="open"]');
  if (open) open.click();
}

function rows(ctx) { return Array.prototype.slice.call(ctx.host.querySelectorAll('.search-hit')); }

function focusRow(li) {
  if (!li) return;
  const main = li.querySelector('.trow-main');
  if (main) main.focus(); else li.focus();
}

export function wireKeys(ctx) {
  const input = ctx.input;
  input.addEventListener('input', function () { schedule(ctx); });
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown') {
      const r = rows(ctx);
      if (r.length) { ev.preventDefault(); focusRow(r[0]); }
    } else if (ev.key === 'Enter') {
      clearTimeout(ctx.timer);
      const r = rows(ctx);
      if (input.value.trim() && ctx.last && r.length) { ev.preventDefault(); primary(ctx, r[0]); }
      else run(ctx, input.value);
    } else if (ev.key === 'Escape') {
      if (input.value) { input.value = ''; run(ctx, ''); }
    }
  });
  ctx.host.addEventListener('keydown', function (ev) {
    const li = ev.target.closest('.search-hit');
    if (!li || ev.target.closest('input, textarea, select')) return;
    const r = rows(ctx);
    const i = r.indexOf(li);
    if (ev.key === 'ArrowDown') { ev.preventDefault(); focusRow(r[i + 1] || r[i]); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (i === 0) input.focus(); else focusRow(r[i - 1]); }
    else if (ev.key === 'Home') { ev.preventDefault(); focusRow(r[0]); }
    else if (ev.key === 'End') { ev.preventDefault(); focusRow(r[r.length - 1]); }
    else if (ev.key === 'Escape' || ev.key === '/') { ev.preventDefault(); input.focus(); input.select(); }
  });
}
