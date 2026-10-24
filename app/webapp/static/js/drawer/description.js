/* task-os — the drawer's description: markdown, edit / preview. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { renderMarkdown } from '../../format.js';
import { section } from './dom.js';

export function descriptionSection(ctx, t) {
  const desc = section('description', 'Description', 'file-text');
  const descTools = document.createElement('div');
  descTools.className = 'drawer-tools';
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'button-ghost';
  toggle.innerHTML = icon(ctx.descEditing ? 'eye' : 'pencil') + ' ' + (ctx.descEditing ? 'Preview' : 'Edit');
  desc.querySelector('h3').appendChild(descTools);
  descTools.appendChild(toggle);
  const body = document.createElement('div');
  body.className = 'drawer-desc';
  if (ctx.descEditing) {
    const ta = document.createElement('textarea');
    ta.className = 'input-native drawer-desc-edit';
    ta.value = t.description || '';
    ta.rows = 6;
    ta.placeholder = 'Markdown: **bold**, - lists, `code`, links…';
    ta.setAttribute('aria-label', 'Description');
    body.appendChild(ta);
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'button-tint drawer-desc-save';
    save.textContent = 'Save';
    save.addEventListener('click', function () {
      ctx.descEditing = false;
      ctx.patch({ description: ta.value });
    });
    ta.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save.click(); }
    });
    body.appendChild(save);
    toggle.addEventListener('click', function () { ctx.descEditing = false; ctx.render(); });
  } else {
    const view = document.createElement('div');
    view.className = 'markdown';
    if ((t.description || '').trim()) view.innerHTML = renderMarkdown(t.description);
    else { view.classList.add('muted'); view.textContent = 'No description yet.'; }
    body.appendChild(view);
    toggle.addEventListener('click', function () {
      ctx.descEditing = true;
      ctx.render();
      ctx.el.querySelector('.drawer-desc-edit').focus();
    });
  }
  desc.appendChild(body);
  return desc;
}
