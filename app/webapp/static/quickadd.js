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
 * Everything but the title is optional and empty by default — no date, status
 * inbox — so `type · Enter` is still the whole fast path.
 *
 * Submit is one POST /api/tasks with every field the form holds, then (only
 * when a URL was given) one POST /api/tasks/{id}/links. A link that fails does
 * NOT lose the task: it is created, said so, and the link failure is its own
 * message.
 */

'use strict';

import { api } from './api.js';
import { icon } from './_vendored/icons/icons.js';
import { STATUSES, linkKind, relDue } from './format.js';
import { mountFolderPicker, resolveFolderRef } from './folderpick.js';
import { toast } from './toast.js';

const PARSE_DEBOUNCE_MS = 180;
const DEFAULT_STATUS = 'inbox';

/**
 * @param {HTMLDialogElement} dialog  the `#quickAdd` shell (index.html)
 * @param {{onCreated: (task: object) => void}} opts
 * @returns {{open: () => void, close: () => void}}
 */
export function createQuickAdd(dialog, opts) {
  const form = dialog.querySelector('.quickadd-card');
  const input = dialog.querySelector('.quick-add-input');
  const submit = dialog.querySelector('.quick-add-submit');
  const chips = dialog.querySelector('.quick-add-chips');
  const desc = dialog.querySelector('.quick-add-desc');
  const due = dialog.querySelector('.quick-add-due');
  const starts = dialog.querySelector('.quick-add-starts');
  const status = dialog.querySelector('.quick-add-status');
  const folder = dialog.querySelector('.quick-add-folder');
  const pick = dialog.querySelector('.quick-add-pick');
  const picker = dialog.querySelector('.quick-add-picker');
  const link = dialog.querySelector('.quick-add-link-url');
  const linkLabel = dialog.querySelector('.quick-add-link-label');

  STATUSES.forEach(function (s) {
    const o = document.createElement('option');
    o.value = s;
    o.textContent = s;
    if (s === DEFAULT_STATUS) o.selected = true;
    status.appendChild(o);
  });

  let parsed = null;
  let timer = 0;
  let seq = 0;
  // Once a date is set by hand the parser stops writing it ??? one flag per
  // field, so correcting the due never freezes the start date too (#87).
  const touched = { due: false, starts: false };

  /** The parse preview: the parent only — the due is in the Due field, where
   *  it can be corrected, so a chip repeating it would be a second truth. */
  function renderChips() {
    chips.innerHTML = '';
    if (!parsed || !parsed.parent_ref) return;
    const c = document.createElement('span');
    c.className = 'chip chip-parent' + (parsed.parent ? '' : ' chip-missing');
    c.innerHTML = icon('corner-down-right');
    const t = document.createElement('span');
    t.className = 'chip-label';
    if (parsed.parent) {
      c.dataset.parentId = String(parsed.parent.id);
      t.textContent = 'in ' + parsed.parent.title + ' (#' + parsed.parent.id + ')';
    } else {
      const ref = parsed.parent_ref.id != null ? '#' + parsed.parent_ref.id : parsed.parent_ref.title;
      t.textContent = 'no such parent: ' + ref;
    }
    c.appendChild(t);
    chips.appendChild(c);
  }

  /** The phrase the parser understood, next to the date it produced. Both date
   *  fields fill this way, so `due oct 15 starts oct 1` previews as two
   *  correctable dates rather than one date and a mystery (#87). */
  function showDate(el, iso, phrase) {
    el.value = iso || '';
    const rel = iso ? relDue(iso) : { text: '' };
    el.title = iso
      ? (phrase ? '"' + phrase + '"' : '') + (rel.text ? (phrase ? ' · ' : '') + rel.text : '')
      : '';
  }

  async function parseNow() {
    const text = input.value.trim();
    const my = ++seq;
    if (!text) {
      parsed = null;
      renderChips();
      if (!touched.due) showDate(due, '', '');
      if (!touched.starts) showDate(starts, '', '');
      return;
    }
    try {
      const res = await api('/api/parse', { method: 'POST', body: { text: text } });
      if (my !== seq) return;           // a newer keystroke superseded this parse
      parsed = res;
      parsed._for = text;
      renderChips();
      if (!touched.due) showDate(due, parsed.due, parsed.due_phrase);
      if (!touched.starts) showDate(starts, parsed.starts, parsed.starts_phrase);
    } catch (_) {
      // Parsing is a convenience: a failed parse just means no preview.
      if (my === seq) { parsed = null; renderChips(); }
    }
  }

  input.addEventListener('input', function () {
    submit.disabled = !input.value.trim();
    window.clearTimeout(timer);
    timer = window.setTimeout(parseNow, PARSE_DEBOUNCE_MS);
  });
  due.addEventListener('input', function () { touched.due = true; due.title = ''; });
  starts.addEventListener('input', function () { touched.starts = true; starts.title = ''; });

  // Folder: type a ref / an absolute path, or search the index (folderpick.js,
  // the same picker the drawer's Folder section uses).
  function setPicker(open) {
    picker.hidden = !open;
    pick.setAttribute('aria-expanded', String(open));
    if (!open) return;
    mountFolderPicker(picker, {
      onPick: function (ref) { folder.value = ref; setPicker(false); folder.focus(); },
      onClose: function () { pick.setAttribute('aria-expanded', 'false'); },
    });
    picker.querySelector('input').focus();
  }
  pick.addEventListener('click', function () { setPicker(picker.hidden); });

  function reset() {
    input.value = '';
    desc.value = '';
    showDate(due, '', '');
    showDate(starts, '', '');
    status.value = DEFAULT_STATUS;
    folder.value = '';
    link.value = '';
    linkLabel.value = '';
    setPicker(false);
    parsed = null;
    touched.due = false;
    touched.starts = false;
    submit.disabled = true;
    renderChips();
  }

  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    window.clearTimeout(timer);
    // Make sure the parse reflects the final text before creating.
    if (!parsed || parsed._for !== text) {
      try {
        parsed = await api('/api/parse', { method: 'POST', body: { text: text } });
        parsed._for = text;
      } catch (_) { parsed = null; }
    }
    const body = { title: (parsed && parsed.title) || text, status: status.value };
    if (due.value) body.due = due.value;
    if (starts.value) body.starts = starts.value;
    if (desc.value.trim()) body.description = desc.value.trim();
    if (parsed && parsed.parent_ref) {
      if (!parsed.parent) {
        toast('No task matches that parent — nothing created', 'error');
        return;
      }
      body.parent_id = parsed.parent.id;
    }
    submit.disabled = true;
    const ref = folder.value.trim();
    if (ref) {
      const resolved = await resolveFolderRef(ref);
      if (resolved === undefined) { submit.disabled = false; return; }   // said why
      body.folder_ref = resolved;
    }
    let task;
    try {
      task = await api('/api/tasks', { method: 'POST', body: body });
    } catch (err) {
      toast(err.message || 'Could not add the task', 'error');
      submit.disabled = false;
      return;
    }
    // The task exists from here on: a failing link is reported on its own and
    // never rolls the task back or keeps the dialog holding a duplicate.
    const url = link.value.trim();
    if (url) {
      try {
        await api('/api/tasks/' + task.id + '/links', {
          method: 'POST',
          body: { url: url, label: linkLabel.value.trim() || null, kind: linkKind(url) },
        });
      } catch (err) {
        toast('Added #' + task.id + ', but the link failed: ' + (err.message || 'unknown error'), 'error');
      }
    }
    close();                            // the `close` listener clears the draft
    toast('Added #' + task.id + ' ' + task.title, 'success');
    if (opts && opts.onCreated) opts.onCreated(task);
  });

  function open() {
    if (!dialog.open) dialog.showModal();
    input.focus();
    input.select();
  }

  function close() {
    if (dialog.open) dialog.close();
  }

  // Escape closes the folder picker first, the dialog second — one keystroke
  // per thing open, so it never discards a draft the user was still filling.
  // Capture, not `cancel`: the picker's own Escape handler (folderpick.js) runs
  // on the way to the target and would already have hidden it, leaving `cancel`
  // to see a closed picker and let the dialog go.
  dialog.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape' || picker.hidden) return;
    ev.preventDefault();          // ... and so the dialog's own close-request too
    ev.stopPropagation();
    setPicker(false);
    folder.focus();
  }, true);
  dialog.querySelector('.detail-close').addEventListener('click', close);
  dialog.addEventListener('click', function (ev) {
    // click on the backdrop (outside the card) closes
    if (ev.target === dialog) close();
  });
  // Escape / backdrop / × / a successful add all discard the draft (the
  // editor-modal contract: nothing persists but the primary action).
  dialog.addEventListener('close', function () {
    window.clearTimeout(timer);
    seq++;
    reset();
  });

  reset();
  return { open: open, close: close };
}
