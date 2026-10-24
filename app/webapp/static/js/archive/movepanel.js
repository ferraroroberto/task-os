/* task-os — Settings → Email archiving: the *Move to…* panel of one mail. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { mountFolderPicker } from '../../folderpick.js';
import { toast } from '../../toast.js';
import { moveItem, runAction, verbButton } from './actions.js';
import { isFiled } from './rules.js';
import { sameFolder, shortFolder } from './text.js';

const MAX_HINT = 500;

/** The *Move to…* panel: the discarded candidates the run already ranked,
 *  *Other folder…* over the shared folder-index picker, and the one optional
 *  hint that explains the correction to the next run.
 *
 *  Returned in two pieces — the toggle and the body — because the caller
 *  decides where the body goes. In the grid it is a full-width row of its
 *  own **under** the mail's row: a panel inside the last cell widened that
 *  column and squeezed *Why* down to one word a line. On the phone card it
 *  sits straight under the actions.
 *  @param {{onToggle?: (open: boolean) => void}} [hooks]
 */
export function movePanel(ctx, item, hooks) {
  const toggle = verbButton('folder', isFiled(item) ? 'Move to…' : 'File it…');
  toggle.classList.add('archive-move-toggle');
  toggle.setAttribute('aria-expanded', 'false');

  const body = document.createElement('div');
  body.className = 'archive-move-body';
  body.hidden = true;
  toggle.addEventListener('click', function () {
    const open = body.hidden;
    body.hidden = !open;
    // The engaged look is the shared `[aria-expanded="true"]` tint (#168) —
    // no second state class to keep in step with the attribute.
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (hooks && hooks.onToggle) hooks.onToggle(open);
  });

  const hint = document.createElement('input');
  hint.type = 'text';
  hint.className = 'input-native archive-hint';
  hint.maxLength = MAX_HINT;
  hint.placeholder = 'Why (optional) — remembered for the next run';
  hint.setAttribute('aria-label', 'Why this folder (optional)');

  body.appendChild(candidatesEl(ctx, item, hint));
  const folder = otherFolderEls(ctx, item, hint);
  body.append(folder.other, folder.picker);
  body.appendChild(hint);
  return { toggle: toggle, body: body };
}

/** The candidates this run already ranked and did not use. The one it did
 *  use is left out for a filed mail (the API refuses re-filing a mail into
 *  the folder it is already in) and kept for a `needs_review` one, where it
 *  is the pick the model was not confident enough about — the likeliest
 *  answer on the screen. */
function candidatesEl(ctx, item, hint) {
  const candidates = (item.candidates || []).filter(function (c) {
    return c && c.folder_path && !(isFiled(item) && sameFolder(c.folder_path, item.chosen_folder));
  });
  if (!candidates.length) {
    const none = document.createElement('p');
    none.className = 'muted archive-move-none';
    none.textContent = 'No other folder was ranked for this mail — name one below.';
    return none;
  }
  const list = document.createElement('ul');
  list.className = 'archive-cands';
  candidates.forEach(function (c) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button-ghost archive-cand';
    b.title = (isFiled(item) ? 'Move into ' : 'Archive here: ') + c.folder_path;
    const name = document.createElement('span');
    name.className = 'archive-cand-name';
    name.textContent = c.display_name || shortFolder(c.folder_path);
    const path = document.createElement('span');
    path.className = 'archive-cand-path';
    path.textContent = shortFolder(c.folder_path);
    const score = document.createElement('span');
    score.className = 'archive-cand-score';
    score.textContent = c.score == null ? '' : Number(c.score).toFixed(2);
    b.append(name, path, score);
    b.addEventListener('click', function () {
      runAction(ctx, b, function () { return moveItem(item, c.folder_path, hint.value.trim(), true); });
    });
    li.appendChild(b);
    list.appendChild(li);
  });
  return list;
}

/** Other folder…: the same field + index picker the drawer and quick-add use.
 *  `other` is the field row, `picker` the folder-index panel it opens. */
function otherFolderEls(ctx, item, hint) {
  const other = document.createElement('div');
  other.className = 'archive-other';
  const field = document.createElement('input');
  field.type = 'text';
  field.className = 'input-native archive-other-input';
  field.placeholder = '{onedrive}/… — or paste an absolute path';
  field.setAttribute('aria-label', 'Any other folder');
  const pickBtn = document.createElement('button');
  pickBtn.type = 'button';
  pickBtn.className = 'button-ghost folder-pick';
  pickBtn.setAttribute('aria-expanded', 'false');
  pickBtn.innerHTML = icon('search') + '<span class="folder-pick-label">Find in folder index</span>';
  pickBtn.setAttribute('aria-label', 'Find in folder index');
  pickBtn.title = 'Find in folder index';
  // The field and its picker are one group so the phone can draw them as one
  // box with the glyph inside the right edge (`display: contents` dissolves
  // the group again on a wide screen, where they are two controls on a row).
  const fieldGroup = document.createElement('div');
  fieldGroup.className = 'archive-other-field';
  fieldGroup.append(field, pickBtn);
  const go = document.createElement('button');
  go.type = 'button';
  go.className = 'button-surface archive-other-go';
  go.textContent = isFiled(item) ? 'Move here' : 'Archive here';
  go.addEventListener('click', function () {
    const typed = field.value.trim();
    if (!typed) { toast('Name a folder first', 'error'); return; }
    runAction(ctx, go, function () { return moveItem(item, typed, hint.value.trim(), false); });
  });
  other.append(fieldGroup, go);

  const picker = document.createElement('div');
  picker.className = 'folder-picker archive-picker';
  picker.hidden = true;
  pickBtn.addEventListener('click', function () {
    picker.hidden = !picker.hidden;
    pickBtn.setAttribute('aria-expanded', picker.hidden ? 'false' : 'true');
    if (picker.hidden) return;
    mountFolderPicker(picker, {
      onPick: function (ref) { field.value = ref; picker.hidden = true; pickBtn.setAttribute('aria-expanded', 'false'); },
      onClose: function () { pickBtn.setAttribute('aria-expanded', 'false'); },
    });
  });
  return { other: other, picker: picker };
}
