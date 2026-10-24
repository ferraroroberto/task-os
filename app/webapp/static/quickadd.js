/* task-os — quick-add: the fields worth setting while the task is still in
 * your head, in one dialog (#80).
 *
 * The + button in every pane's top strip opens `<dialog id="quickAdd">` — the
 * same vendored editor-modal shell the command palette uses (native showModal
 * / close, Esc closes; markup in index.html, so this module is behaviour only).
 *
 * Line 1 stays the natural-language line: POST /api/parse splits it
 * server-side (so the CLI and the UI agree on what "next friday" means) and
 * the result lands where it can still be changed — the dates it finds fill the
 * **Due** and **Starts** fields, the parent shows as a chip. Under it, the
 * fields that used to force a second trip through the drawer (#80 round 2):
 * description, due, starts (#87), status, folder (with the shared
 * folder-index picker) and one link.
 * Everything but the title is optional and sensible by default — no date,
 * status To Do — so `type · Enter` is still the whole fast path.
 *
 * Submit is one POST /api/tasks with every field the form holds, then (only
 * when a URL was given) one POST /api/tasks/{id}/links. A link that fails does
 * NOT lose the task: it is created, said so, and the link failure is its own
 * message.
 *
 * The mic beside line 1 (#92, behaviour in voice.js) fills that same line by
 * voice: click to start, and the words appear **while you speak** (#146) —
 * shown provisionally under `.is-dictating` until you click again, when the
 * final transcript settles with the parse already applied, the identical
 * preview typing it would have produced, one confirming Enter away. Dictation
 * appends to whatever was already on the line rather than replacing it.
 * Nothing else about the dialog changes.
 *
 * This file is the composer: it builds the `ctx` its parts share (the dialog,
 * the looked-up fields, the draft state) and hands back `open` / `close`. Each
 * part lives in js/quickadd/<part>.js and takes `ctx` as its first argument; a
 * call that would make two parts import each other goes through a `ctx` slot.
 */

'use strict';

import { STATUSES } from './format.js';
import { mountDictation } from './js/quickadd/dictate.js';
import { resetForm, wireSubmit } from './js/quickadd/form.js';
import { showDate } from './js/quickadd/preview.js';
import { wireQuickAdd } from './js/quickadd/wire.js';

// To Do, not Inbox (#148): Inbox is the arrivals tray for what came in on
// its own, and a task you are typing here has already been triaged by the
// act of writing it. The select still opens on this, so it stays one change
// away — and the server's own default (tasks_repo.DEFAULT_STATUS) is the
// same value, so a create that omits the field agrees with this one.
const DEFAULT_STATUS = 'todo';

/**
 * @param {HTMLDialogElement} dialog  the `#quickAdd` shell (index.html)
 * @param {{onCreated: (task: object) => void}} opts
 * @returns {{open: (preset?: {status?: string, due?: string}) => void, close: () => void}}
 */
export function createQuickAdd(dialog, opts) {
  const q = function (sel) { return dialog.querySelector(sel); };
  const ctx = {
    dialog: dialog,
    opts: opts,
    defaultStatus: DEFAULT_STATUS,
    els: {
      form: q('.quickadd-card'),
      input: q('.quick-add-input'),
      submit: q('.quick-add-submit'),
      chips: q('.quick-add-chips'),
      desc: q('.quick-add-desc'),
      due: q('.quick-add-due'),
      starts: q('.quick-add-starts'),
      status: q('.quick-add-status'),
      folder: q('.quick-add-folder'),
      pick: q('.quick-add-pick'),
      picker: q('.quick-add-picker'),
      link: q('.quick-add-link-url'),
      linkLabel: q('.quick-add-link-label'),
      mic: q('.quick-add-mic'),
      voiceHint: q('.quick-add-voice-hint'),
    },
    st: {
      parsed: null,
      timer: 0,
      seq: 0,
      enrichSeq: 0,
      // Once a date is set by hand the parser stops writing it — one flag per
      // field, so correcting the due never freezes the start date too (#87).
      touched: { due: false, starts: false },
      // What line 1 held when recording started; dictation appends after it.
      spokenPrefix: '',
    },
    voice: null,
    // the call the submit listener and the dialog's wiring share
    close: close,
  };
  const els = ctx.els;

  STATUSES.forEach(function (s) {
    const o = document.createElement('option');
    o.value = s;
    o.textContent = s;
    if (s === DEFAULT_STATUS) o.selected = true;
    els.status.appendChild(o);
  });

  wireSubmit(ctx);
  ctx.voice = mountDictation(ctx);
  wireQuickAdd(ctx);

  /** @param {{status?: string, due?: string}} [preset] where the add came
   *  from (#339): an empty Board column presets its status, Today's empty
   *  list today's date. A preset date is a choice already made, so the
   *  parse of the typed line does not clear it (the field still edits). */
  function open(preset) {
    const p = preset || {};
    if (p.status && STATUSES.indexOf(p.status) >= 0) els.status.value = p.status;
    if (p.due) { showDate(els.due, p.due, ''); ctx.st.touched.due = true; }
    if (!dialog.open) dialog.showModal();
    ctx.voice.refresh();
    els.input.focus();
    els.input.select();
  }

  function close() {
    if (dialog.open) dialog.close();
  }

  resetForm(ctx);
  return { open: open, close: close };
}
