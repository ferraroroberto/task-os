/* task-os — quick-add: the draft. `resetForm` empties every field back to its
 * default; the submit listener turns what the form holds into one POST
 * /api/tasks, then (only when a URL was given) one link POST. */

'use strict';

import { api } from '../../api.js';
import { resolveFolderRef } from '../../folderpick.js';
import { toast } from '../../toast.js';
import { setPicker } from './folder.js';
import { renderChips, showDate } from './preview.js';

export function resetForm(ctx) {
  const { input, desc, due, starts, status, folder, link, linkLabel, submit } = ctx.els;
  const st = ctx.st;
  input.value = '';
  input.classList.remove('is-dictating');
  st.spokenPrefix = '';
  desc.value = '';
  showDate(due, '', '');
  showDate(starts, '', '');
  status.value = ctx.defaultStatus;
  folder.value = '';
  link.value = '';
  linkLabel.value = '';
  setPicker(ctx, false);
  st.parsed = null;
  st.touched.due = false;
  st.touched.starts = false;
  submit.disabled = true;
  renderChips(ctx);
}

export function wireSubmit(ctx) {
  const { form, input, desc, due, starts, status, folder, link, linkLabel, submit } = ctx.els;
  const st = ctx.st;
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    window.clearTimeout(st.timer);
    // Make sure the parse reflects the final text before creating.
    if (!st.parsed || st.parsed._for !== text) {
      try {
        st.parsed = await api('/api/parse', { method: 'POST', body: { text: text } });
        st.parsed._for = text;
      } catch (_) { st.parsed = null; }
    }
    const parsed = st.parsed;
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
          body: { url: url, label: linkLabel.value.trim() || null },
        });
      } catch (err) {
        toast('Added #' + task.id + ', but the link failed: ' + (err.message || 'unknown error'), 'error');
      }
    }
    ctx.close();                        // the `close` listener clears the draft
    toast('Added #' + task.id + ' ' + task.title, 'success');
    if (ctx.opts && ctx.opts.onCreated) ctx.opts.onCreated(task);
  });
}
