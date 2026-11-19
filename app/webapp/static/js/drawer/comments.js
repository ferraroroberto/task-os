/* task-os — the drawer's comments: newest first, the composer, and one
 * compact row per comment with a "···" menu for edit and delete. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { confirmDialog } from '../../confirm.js';
import { createRowMenu } from '../../_vendored/row-menu/row-menu.js';
import { fmtCommentWhen, fmtTs, linkify, singleLink } from '../../format.js';
import { keyHint } from '../../snooze.js';
import { toast } from '../../toast.js';
import { formButton, section } from './dom.js';

// One menu for the whole thread: at most one comment's menu is open at a time.
const menu = createRowMenu({ className: 'comment-menu' });

/** How many comments show before "Show N older": the latest few are what
 *  a glance at a task needs. */
const RECENT_COMMENTS = 3;

/** The new-comment form: Ctrl+Enter sends, origin=ui. Send is the drawer's
 *  one primary button, labelled, at the field's own 44px height.
 *  @param {boolean} pinned  the phone's: pinned to the drawer's foot */
export function commentComposer(ctx, t, pinned) {
  const composer = document.createElement('form');
  composer.className = 'comment-composer' + (pinned ? ' comment-composer-pinned' : '');
  const ta = document.createElement('textarea');
  ta.className = 'input-native comment-input';
  ta.rows = 1;
  ta.placeholder = 'Comment or paste a link…';
  ta.setAttribute('aria-label', 'New comment');
  ta.setAttribute('aria-keyshortcuts', 'Control+Enter');
  ta.title = 'Ctrl+Enter to send; links become chips';
  const send = formButton(composer, 'button-primary comment-send', icon('send-horizontal') + ' Send', { track: 'drawer.comment-send' });
  send.setAttribute('aria-label', 'Send comment');
  send.title = 'Send (Ctrl+Enter)';
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

/** The "···" menu's inline editor.
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
  saveBtn.dataset.track = 'drawer.comment-save';
  saveBtn.type = 'button';
  saveBtn.className = 'button-ghost comment-send comment-edit-save';
  saveBtn.setAttribute('aria-label', 'Save comment');
  saveBtn.title = 'Ctrl+Enter';
  saveBtn.innerHTML = icon('check') + ' Save';
  saveBtn.addEventListener('click', save);
  const cancelBtn = document.createElement('button');
  cancelBtn.dataset.track = 'drawer.comment-cancel';
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

/** Delete: asks first, as Delete task does — there is no undo. */
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

/** The comment's text as its row shows it. A comment holding exactly one web
 *  link IS that link: the text around the URL, opening it in a new window with a
 *  small open-in-new mark, and the raw URL never shown. A comment that is only
 *  a URL, or holds several targets, keeps its chips. */
function commentText(c) {
  const wrap = document.createDocumentFragment();
  const one = singleLink(c.body);
  if (one && one.rest) {
    const a = document.createElement('a');
    a.className = 'comment-link';
    a.href = one.url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.title = one.url;
    // the last word and the mark share one nowrap span, so the mark never
    // wraps onto a line of its own
    const cut = one.rest.lastIndexOf(' ') + 1;
    const tail = document.createElement('span');
    tail.className = 'comment-link-tail';
    tail.append(one.rest.slice(cut));
    tail.insertAdjacentHTML('beforeend', icon('external-link'));
    a.append(one.rest.slice(0, cut), tail);
    wrap.appendChild(a);
  } else {
    wrap.appendChild(linkify(c.body));
  }
  return wrap;
}

/** The "···" menu's two actions on one comment: the inline editor and the
 *  delete confirm, each as the pencil and the trash were. */
function commentMenuItems(ctx, t, c) {
  return [
    { label: 'Edit', glyph: 'pencil', dataset: { action: 'edit', track: 'drawer.comment-edit' },
      onTap: function () { ctx.editingCommentId = c.id; ctx.render(); } },
    { label: 'Delete', glyph: 'trash-2', danger: true, dataset: { action: 'delete', track: 'drawer.comment-delete' },
      onTap: function () { deleteComment(ctx, t, c); } },
  ];
}

/** One comment as one row: the time in a narrow column, the text beside it
 *  (two lines, a tap on the row opens the rest), the author after it only when
 *  it is somebody else, and one "···" for edit and delete. An edit swaps the
 *  text for the inline editor; author, time and origin never change under it. */
function commentRow(ctx, t, c) {
  const row = document.createElement('article');
  row.className = 'comment';
  row.dataset.commentId = String(c.id);
  const when = document.createElement('time');
  when.className = 'comment-when';
  when.dateTime = c.ts;
  when.textContent = fmtCommentWhen(c.ts);
  when.title = fmtTs(c.ts) + ' · ' + c.origin;
  row.appendChild(when);
  if (ctx.editingCommentId === c.id) {
    row.classList.add('is-editing');
    row.appendChild(commentEditor(ctx, t, c));
    return row;
  }
  const bodyEl = document.createElement('div');
  bodyEl.className = 'comment-body';
  bodyEl.appendChild(commentText(c));
  if (!ctx.author || c.author !== ctx.author) {
    const who = document.createElement('span');
    who.className = 'comment-author';
    who.textContent = c.author;
    bodyEl.append(' ', who);
  }
  bodyEl.addEventListener('click', function (ev) {
    if (ev.target.closest('a')) return;
    row.classList.toggle('is-open');
  });
  row.appendChild(bodyEl);
  const more = document.createElement('button');
  more.dataset.track = 'drawer.comment-more';
  more.type = 'button';
  more.className = 'icon-button comment-more';
  more.setAttribute('aria-label', 'Comment actions');
  more.innerHTML = icon('ellipsis');
  row.appendChild(more);
  menu.attach('comment-' + c.id, more, commentMenuItems(ctx, t, c));
  return row;
}

/** Comments, newest first: the latest three, then "Show N older". The
 *  composer heads the list unless the phone pins it to the drawer's foot
 *  (`pinned`: the caller places it there).
 *  @param {boolean} pinned */
export function commentsSection(ctx, t, pinned) {
  const comments = section('comments', 'Comments', 'message-square');
  const ordered = (t.comments || []).slice().reverse();
  const title = comments.querySelector('h3');
  if (ordered.length) {
    const n = document.createElement('span');
    n.className = 'drawer-section-count';
    n.textContent = String(ordered.length);
    title.appendChild(n);
  }
  const hint = document.createElement('span');
  hint.className = 'drawer-section-hint';
  hint.append(keyHint('C'), ' to comment');
  title.appendChild(hint);
  if (!pinned) comments.appendChild(commentComposer(ctx, t, false));
  const clist = document.createElement('div');
  clist.className = 'comment-list';
  const shown = ctx.commentsAll ? ordered : ordered.slice(0, RECENT_COMMENTS);
  shown.forEach(function (c) { clist.appendChild(commentRow(ctx, t, c)); });
  menu.endRender();
  if (!ordered.length) {
    const none = document.createElement('p');
    none.className = 'muted drawer-none';
    none.textContent = 'No comments yet.';
    clist.appendChild(none);
  }
  comments.appendChild(clist);
  const older = ordered.length - RECENT_COMMENTS;
  if (older > 0) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.dataset.track = 'drawer.comments-older';
    toggle.className = 'drawer-more-link comments-older';
    toggle.setAttribute('aria-expanded', String(!!ctx.commentsAll));
    toggle.textContent = ctx.commentsAll ? 'Show the latest ' + RECENT_COMMENTS : 'Show ' + older + ' older';
    toggle.addEventListener('click', function () { ctx.commentsAll = !ctx.commentsAll; ctx.render(); });
    comments.appendChild(toggle);
  }
  return comments;
}
