/* task-os — the drawer's notes (the task's markdown description): a tap on
 * the text edits it in place, and leaving the field saves it. */

'use strict';

import { renderMarkdown } from '../../format.js';
import { section } from './dom.js';

function notesEditor(ctx, t) {
  const ta = document.createElement('textarea');
  ta.className = 'input-native drawer-desc-edit';
  ta.value = t.description || '';
  ta.rows = 6;
  ta.placeholder = 'Markdown: **bold**, - lists, `code`, links…';
  ta.setAttribute('aria-label', 'Notes');
  let cancelled = false;
  ta.addEventListener('keydown', function (ev) {
    // stopPropagation: the re-render detaches this field, and app.js's
    // document-level Escape would then close the drawer on top of the cancel.
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); cancelled = true; ta.blur(); }
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); ta.blur(); }
  });
  ta.addEventListener('blur', function () {
    if (!ta.isConnected) return;   // a re-render took the field away, not the owner
    ctx.descEditing = false;
    if (!cancelled && ta.value !== (t.description || '')) ctx.patch({ description: ta.value });
    else ctx.render();
  });
  requestAnimationFrame(function () { ta.focus(); });
  return ta;
}

export function descriptionSection(ctx, t) {
  const desc = section('description', 'Notes', 'file-text');
  const hint = document.createElement('span');
  hint.className = 'drawer-section-hint';
  hint.textContent = ctx.descEditing ? 'saves when you leave the field' : 'tap to edit';
  desc.querySelector('h3').appendChild(hint);
  const body = document.createElement('div');
  body.className = 'drawer-desc';
  if (ctx.descEditing) {
    body.appendChild(notesEditor(ctx, t));
  } else {
    const view = document.createElement('div');
    view.className = 'markdown drawer-desc-view';
    view.tabIndex = 0;
    view.setAttribute('role', 'button');
    view.setAttribute('aria-label', 'Edit notes');
    view.dataset.track = 'drawer.desc-edit';
    if ((t.description || '').trim()) view.innerHTML = renderMarkdown(t.description);
    else { view.classList.add('muted'); view.textContent = 'No notes yet.'; }
    const edit = function () { ctx.descEditing = true; ctx.render(); };
    view.addEventListener('click', function (ev) { if (!ev.target.closest('a')) edit(); });
    view.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); edit(); }
    });
    body.appendChild(view);
  }
  desc.appendChild(body);
  return desc;
}
