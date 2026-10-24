/* task-os — the drawer's comments: newest first, the composer, and the
 * pencil / trash on each row. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { confirmDialog } from '../../confirm.js';
import { fmtTs, linkify } from '../../format.js';
import { toast } from '../../toast.js';
import { formButton, section } from './dom.js';

/** The new-comment form: Ctrl+Enter sends, origin=ui. */
function commentComposer(ctx, t) {
  const composer = document.createElement('form');
  composer.className = 'comment-composer';
  const ta = document.createElement('textarea');
  ta.className = 'input-native comment-input';
  ta.rows = 2;
  ta.placeholder = 'Add a comment… (Ctrl+Enter to send)';
  ta.setAttribute('aria-label', 'New comment');
  ta.title = 'Ctrl+Enter to send; links become chips';
  // Same tier and metrics as the Description "Edit" button — quiet, not a
  // full-height primary block.
  const send = formButton(composer, 'button-ghost comment-send', icon('send-horizontal') + ' Send');
  send.setAttribute('aria-label', 'Send comment');
  composer.append(ta, send);
  composer.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const bodyText = ta.value.trim();
    if (!bodyText) return;
    send.disabled = true;
    try {
      await api('/api/tasks/' + t.id + '/comments', { method: 'POST', body: { body: bodyText, origin: 'ui' } });
      ta.value = '';
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) {
      toast(err.message || 'Comment failed', 'error');
    } finally { send.disabled = false; }
  });
  ta.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); composer.requestSubmit(); }
  });
  return composer;
}

/** The pencil's inline editor (#155).
 *
 *  It IS the composer, re-pointed at an existing body: same `.comment-composer`
 *  row, same `.comment-input` textarea, same `.comment-send` buttons on the
 *  line beside it — so the thread never grows a second control vocabulary and
 *  the phone never spends a row on a button bar. Save keeps the accent tint
 *  (the committing action) as *colour only*; the geometry stays Send's.
 */
function commentEditor(ctx, t, c) {
  const wrap = document.createElement('div');
  wrap.className = 'comment-composer comment-edit-wrap';
  const ta = document.createElement('textarea');
  ta.className = 'input-native comment-input comment-edit';
  ta.rows = 2;
  ta.value = c.body;
  ta.setAttribute('aria-label', 'Edit comment by ' + c.author);
  ta.title = 'Ctrl+Enter to save, Escape to cancel';
  const cancel = function () { ctx.editingCommentId = null; ctx.render(); };
  const save = async function () {
    const v = ta.value.trim();
    if (!v) { toast('A comment cannot be empty', 'error'); ta.focus(); return; }
    if (v === c.body) { cancel(); return; }
    try {
      await api('/api/tasks/' + t.id + '/comments/' + c.id, { method: 'PATCH', body: { body: v } });
      // only now: a failed save leaves the editor open with the text still in
      // it, so a rejected or dropped request never eats what was typed
      ctx.editingCommentId = null;
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) {
      toast(err.message || 'Edit failed', 'error');
    }
  };
  ta.addEventListener('keydown', function (ev) {
    // stopPropagation for the same reason the link-label editor does it: the
    // handlers below re-render the drawer synchronously and detach this
    // textarea, so app.js's document-level Escape would no longer see a field
    // owning the key and would close the drawer on top of the cancelled edit.
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); ev.stopPropagation(); save(); }
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); cancel(); }
  });
  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'button-ghost comment-send comment-edit-save';
  saveBtn.setAttribute('aria-label', 'Save comment');
  saveBtn.title = 'Ctrl+Enter';
  saveBtn.innerHTML = icon('check') + ' Save';
  saveBtn.addEventListener('click', save);
  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'button-ghost comment-send';
  cancelBtn.setAttribute('aria-label', 'Cancel editing');
  cancelBtn.title = 'Escape';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', cancel);
  wrap.append(ta, saveBtn, cancelBtn);
  requestAnimationFrame(function () {
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  });
  return wrap;
}

/** The trash: asks first, as Delete task does — there is no undo (#155). */
async function deleteComment(ctx, t, c) {
  const preview = c.body.length > 80 ? c.body.slice(0, 80).trim() + '…' : c.body;
  const ok = await confirmDialog({
    title: 'Delete this comment?',
    lines: ['"' + preview + '"', 'This cannot be undone.'],
    action: 'Delete',
  });
  if (!ok || !ctx.current || ctx.current.id !== t.id) return;
  try {
    await api('/api/tasks/' + t.id + '/comments/' + c.id, { method: 'DELETE' });
    await ctx.refresh();
    ctx.opts.onChanged();
    toast('Comment deleted', 'success');
  } catch (err) {
    toast(err.message || 'Delete failed', 'error');
    await ctx.refresh();
  }
}

/** One comment: author · time · origin, the pencil and the trash, then the
 *  body (links as chips) or the inline editor. */
function commentRow(ctx, t, c) {
  const row = document.createElement('article');
  row.className = 'comment';
  row.dataset.commentId = String(c.id);
  const meta = document.createElement('div');
  meta.className = 'comment-meta';
  const who = document.createElement('strong');
  who.textContent = c.author;
  const when = document.createElement('time');
  when.dateTime = c.ts;
  when.textContent = fmtTs(c.ts);
  const origin = document.createElement('span');
  origin.className = 'chip comment-origin';   // the one pill (#357)
  origin.textContent = c.origin;
  meta.append(who, when, origin);
  // Two icons and no more (#155) — the Links row's pair, the one icon
  // button (#357). An edit rewrites the text only: author, time and
  // origin stay, so the meta line above never changes under it.
  const actions = document.createElement('div');
  actions.className = 'comment-actions';
  const edit = document.createElement('button');
  edit.type = 'button';
  edit.className = 'icon-button';
  edit.setAttribute('aria-label', 'Edit comment by ' + c.author);
  edit.title = 'Edit';
  edit.innerHTML = icon('pencil');
  edit.addEventListener('click', function () { ctx.editingCommentId = c.id; ctx.render(); });
  const rm = document.createElement('button');
  rm.type = 'button';
  rm.className = 'icon-button danger';
  rm.setAttribute('aria-label', 'Delete comment by ' + c.author);
  rm.title = 'Delete';
  rm.innerHTML = icon('trash-2');
  rm.addEventListener('click', function () { deleteComment(ctx, t, c); });
  actions.append(edit, rm);
  meta.appendChild(actions);
  row.appendChild(meta);
  if (ctx.editingCommentId === c.id) {
    row.appendChild(commentEditor(ctx, t, c));
  } else {
    const bodyEl = document.createElement('div');
    bodyEl.className = 'comment-body';
    bodyEl.appendChild(linkify(c.body));
    row.appendChild(bodyEl);
  }
  return row;
}

export function commentsSection(ctx, t) {
  const comments = section('comments', 'Comments', 'message-square');
  comments.appendChild(commentComposer(ctx, t));
  const clist = document.createElement('div');
  clist.className = 'comment-list';
  const ordered = (t.comments || []).slice().reverse();
  ordered.forEach(function (c) { clist.appendChild(commentRow(ctx, t, c)); });
  if (!ordered.length) {
    const none = document.createElement('p');
    none.className = 'muted drawer-none';
    none.textContent = 'No comments yet.';
    clist.appendChild(none);
  }
  comments.appendChild(clist);
  return comments;
}
