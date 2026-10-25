/* task-os — the drawer's folder editor under More fields (Step 9). */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { mountFolderPicker, resolveFolderRef } from '../../folderpick.js';
import { formButton, section } from './dom.js';
import { folderChip } from './links.js';

/** The ref the task stores (folderpick.js folds an absolute path onto the
 *  placeholders; `undefined` means the fold failed and already said so). */
async function commitFolder(ctx, value) {
  const ref = await resolveFolderRef(value);
  if (ref === undefined) return;
  ctx.pickerOpen = false;
  await ctx.patch({ folder_ref: ref });
}

/** Line 2's ref form: the input, Change / Set folder, and the picker toggle. */
function folderForm(ctx, t) {
  const form = document.createElement('form');
  form.className = 'folder-form';
  const input = document.createElement('input');
  input.type = 'text';
  input.id = 'drawerFolder';
  input.className = 'input-native';
  input.value = t.folder_ref || '';
  input.placeholder = '{onedrive}/folder  — or paste an absolute path';
  input.setAttribute('aria-label', 'Folder ref');
  const save = formButton(form, 'button-surface', t.folder_ref ? 'Change' : 'Set folder');
  const pick = document.createElement('button');
  pick.type = 'button';
  pick.className = 'button-ghost folder-pick';
  // label span, not a bare text node: the phone drops it to keep line 2 on
  // one line (styles/drawer.css) - the accessible name lives on aria-label either way
  pick.innerHTML = icon('search') + '<span class="folder-pick-label">Find in folder index</span>';
  pick.setAttribute('aria-label', 'Find in folder index');
  pick.title = 'Find in folder index';
  pick.setAttribute('aria-expanded', String(ctx.pickerOpen));
  form.append(input, save, pick);
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const v = input.value.trim();
    if (v === (t.folder_ref || '')) return;
    await commitFolder(ctx, v);
  });
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') { input.value = t.folder_ref || ''; input.blur(); }
  });
  return { form, pick };
}

// ---- folder section: two lines — [chip + delete] / [ref + Change + Pick]
// The resolved path is NOT repeated as a third line: it is already the chip's
// own `title` (format.js), and the phone reaches it through the chip's copy
// popover.
export function folderSection(ctx, t) {
  const sec = section('folder', 'Folder', 'folder');
  const body = document.createElement('div');
  body.className = 'drawer-folder';
  if (t.folder_ref) {
    const cur = document.createElement('div');
    cur.className = 'folder-current';
    cur.appendChild(folderChip(t));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'icon-button danger';
    remove.setAttribute('aria-label', 'Remove folder link');
    remove.innerHTML = icon('trash-2');
    remove.addEventListener('click', function () { commitFolder(ctx, ''); });
    cur.appendChild(remove);
    body.appendChild(cur);
  }
  const { form, pick } = folderForm(ctx, t);
  body.appendChild(form);
  const picker = document.createElement('div');
  picker.className = 'folder-picker';
  picker.hidden = !ctx.pickerOpen;
  const mount = function () {
    mountFolderPicker(picker, {
      onPick: function (value) { return commitFolder(ctx, value); },
      onClose: function () { ctx.pickerOpen = false; },
    });
  };
  if (ctx.pickerOpen) mount();
  pick.addEventListener('click', function () {
    ctx.pickerOpen = !ctx.pickerOpen;
    picker.hidden = !ctx.pickerOpen;
    pick.setAttribute('aria-expanded', String(ctx.pickerOpen));
    if (ctx.pickerOpen) { mount(); picker.querySelector('input').focus(); }
  });
  body.appendChild(picker);
  sec.appendChild(body);
  return sec;
}
