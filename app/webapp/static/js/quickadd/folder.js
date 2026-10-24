/* task-os — quick-add: the Folder field's picker. Type a ref / an absolute
 * path, or search the index (folderpick.js, the same picker the drawer's
 * Folder section uses). */

'use strict';

import { mountFolderPicker } from '../../folderpick.js';

export function setPicker(ctx, open) {
  const { picker, pick, folder } = ctx.els;
  picker.hidden = !open;
  pick.setAttribute('aria-expanded', String(open));
  if (!open) return;
  mountFolderPicker(picker, {
    onPick: function (ref) { folder.value = ref; setPicker(ctx, false); folder.focus(); },
    onClose: function () { pick.setAttribute('aria-expanded', 'false'); },
  });
  picker.querySelector('input').focus();
}
