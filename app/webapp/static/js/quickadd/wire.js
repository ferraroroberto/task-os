/* task-os — quick-add: the listeners the dialog's own controls carry. */

'use strict';

import { closeOnBackdrop } from '../../modal.js';
import { setPicker } from './folder.js';
import { resetForm } from './form.js';
import { parseNow } from './preview.js';

const PARSE_DEBOUNCE_MS = 180;

export function wireQuickAdd(ctx) {
  const { input, submit, due, starts, pick, picker, folder } = ctx.els;
  const dialog = ctx.dialog;
  const st = ctx.st;

  input.addEventListener('input', function () {
    // Typing over a partial makes it yours: it stops being provisional the
    // moment you edit it, whatever the recorder does next.
    input.classList.remove('is-dictating', 'is-enriching');
    submit.disabled = !input.value.trim();
    window.clearTimeout(st.timer);
    st.timer = window.setTimeout(function () { parseNow(ctx); }, PARSE_DEBOUNCE_MS);
  });
  due.addEventListener('input', function () { st.touched.due = true; due.title = ''; });
  starts.addEventListener('input', function () { st.touched.starts = true; starts.title = ''; });
  pick.addEventListener('click', function () { setPicker(ctx, picker.hidden); });

  // Escape closes the folder picker first, the dialog second — one keystroke
  // per thing open, so it never discards a draft the user was still filling.
  // Capture, not `cancel`: the picker's own Escape handler (folderpick.js) runs
  // on the way to the target and would already have hidden it, leaving `cancel`
  // to see a closed picker and let the dialog go.
  dialog.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape' || picker.hidden) return;
    ev.preventDefault();          // ... and so the dialog's own close-request too
    ev.stopPropagation();
    setPicker(ctx, false);
    folder.focus();
  }, true);
  dialog.querySelector('.detail-close').addEventListener('click', ctx.close);
  closeOnBackdrop(dialog, ctx.close);
  // Escape / backdrop / × / a successful add all discard the draft (the
  // editor-modal contract: nothing persists but the primary action).
  dialog.addEventListener('close', function () {
    window.clearTimeout(st.timer);
    st.seq++;
    st.enrichSeq++;                     // a late model answer has nowhere to land
    ctx.voice.cancel();                 // never leave the microphone open
    resetForm(ctx);
  });
}
