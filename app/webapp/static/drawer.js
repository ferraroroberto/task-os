/* task-os — the task drawer.
 *
 * A right-hand side panel on desktop (>= 1024px; the content shrinks so the
 * list stays visible), a full-screen sheet on the phone. Deep-linkable as
 * #task/<id> (app.js owns the hash). Top to bottom: breadcrumb → editable
 * title → fields row (status, priority, due, starts, recurrence + its fixed-day
 * anchor when the cadence takes one, person, code,
 * move-to — re-parent without the tree drag, the phone's path) →
 * folder (the ref as an opener chip + resolved path, an editor that folds a
 * pasted absolute path onto the placeholders, a picker over the folder
 * index — Step 9) → description (markdown, edit/preview) → links (add/remove) → comments
 * newest-first with URLs as clickable chips + composer (Ctrl+Enter sends,
 * origin=ui) → activity log (field old → new · actor · time) → children
 * (click to navigate, add child) → issue panel: the linked issue (provider
 * glyph, repo#N link, state, labels from the last sync, last synced, unlink)
 * or — for a plain task — "Create issue…" (repo from the last-seen list or
 * typed) and "Link existing" (owner/repo#N).
 *
 * Every write goes through the API and then `refresh()`, and the caller's
 * `onChanged` re-renders the Table / Tree so the three surfaces never drift.
 */

'use strict';

import { api } from './api.js';
import { icon } from './_vendored/icons/icons.js';
import { confirmDialog } from './confirm.js';
import {
  PRIORITIES, RECURRENCES, aiChip, anchorOptions, chipFor, fmtTs, isDeferred, issueChip,
  linkKind, linkify, providerIcon, relDue, renderMarkdown, statusPill,
} from './format.js';
import { mountFolderPicker, resolveFolderRef } from './folderpick.js';
import { statusOptions } from './rows.js';
import { toast } from './toast.js';

/**
 * @param {HTMLElement} el     the <aside id="taskDrawer">
 * @param {{onChanged: () => void, onOpen: (id:number) => void, onClose: () => void,
 *          people: () => Array<{id:number,name:string}>,
 *          projects: () => Array<{id:number,title:string,depth?:number}>,
 *          onMove: (id:number, parentId:number|null) => Promise<any>,
 *          onStatus: (id:number, status:string) => Promise<any>,
 *          issues: () => ({enabled:boolean, reason?:string, provider?:string, repos?:string[]}|null),
 *          onSyncIssues: () => Promise<any>,
 *          onToggle?: (id:number|null) => void}} opts   onToggle fires once a task is
 *          shown (its id) and on close (null) — the Search tab's Attach buttons follow it
 */
export function createDrawer(el, opts) {
  let current = null;      // the detail payload
  let descEditing = false;
  let pickerOpen = false;  // the folder-index picker under the Folder field
  let editingLinkId = null;

  function section(name, title, iconName) {
    const s = document.createElement('section');
    s.className = 'drawer-section drawer-' + name;
    const h = document.createElement('h3');
    h.className = 'drawer-section-title';
    h.innerHTML = icon(iconName);
    const t = document.createElement('span');
    t.textContent = title;
    h.appendChild(t);
    s.appendChild(h);
    return s;
  }

  async function patch(changes) {
    if (!current) return;
    try {
      await api('/api/tasks/' + current.id, { method: 'PATCH', body: changes });
      await refresh();
      opts.onChanged();
    } catch (err) {
      toast(err.message || 'Update failed', 'error');
      await refresh();
    }
  }

  function selectField(label, name, values, value, format) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const l = document.createElement('span');
    l.className = 'field-label';
    l.textContent = label;
    const sel = document.createElement('select');
    sel.className = 'select-native field-control';
    sel.dataset.field = name;
    values.forEach(function (v) {
      const o = document.createElement('option');
      o.value = v == null ? '' : String(v);
      o.textContent = format ? format(v) : (v || '—');
      if (String(v == null ? '' : v) === String(value == null ? '' : value)) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () {
      const v = sel.value === '' ? null : (name === 'person_id' ? Number(sel.value) : sel.value);
      const body = {};
      body[name] = v;
      patch(body);
    });
    wrap.append(l, sel);
    return wrap;
  }

  /** The fixed day a recurrence lands on (#112) — the Repeat field's second half.
   *
   *  Its own builder rather than `selectField` because the monthly vocabulary
   *  is long enough to need `<optgroup>`s; the PATCH it sends is the same
   *  single-field one.
   */
  function anchorField(t, groups) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const l = document.createElement('span');
    l.className = 'field-label';
    l.textContent = 'On';
    const sel = document.createElement('select');
    sel.className = 'select-native field-control';
    sel.dataset.field = 'recurrence_anchor';
    groups.forEach(function (group) {
      const target = group.label ? document.createElement('optgroup') : sel;
      if (group.label) target.label = group.label;
      group.options.forEach(function (pair) {
        const o = document.createElement('option');
        o.value = pair[0];
        o.textContent = pair[1];
        if (pair[0] === (t.recurrence_anchor || '')) o.selected = true;
        target.appendChild(o);
      });
      if (group.label) sel.appendChild(target);
    });
    sel.addEventListener('change', function () {
      patch({ recurrence_anchor: sel.value === '' ? null : sel.value });
    });
    wrap.append(l, sel);
    return wrap;
  }

  /** Status: the shared options (a recurring task also gets `complete`,
   *  the roll-forward action — issue #54) through `opts.onStatus`, same
   *  handler every other view uses, instead of a plain field PATCH. */
  function statusField(t) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const l = document.createElement('span');
    l.className = 'field-label';
    l.textContent = 'Status';
    const sel = document.createElement('select');
    sel.className = 'select-native field-control';
    sel.dataset.field = 'status';
    statusOptions(t).forEach(function (v) {
      const o = document.createElement('option');
      o.value = v[0]; o.textContent = v[1]; o.selected = v[0] === t.status;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () {
      sel.disabled = true;
      Promise.resolve(opts.onStatus(t.id, sel.value))
        .catch(function () { sel.value = t.status; })
        .finally(function () { sel.disabled = false; });
    });
    wrap.append(l, sel);
    return wrap;
  }

  function textField(label, name, value, placeholder) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const l = document.createElement('span');
    l.className = 'field-label';
    l.textContent = label;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'input-native field-control';
    input.dataset.field = name;
    input.value = value || '';
    input.placeholder = placeholder || '';
    function commit() {
      const v = input.value.trim();
      if (v === (value || '')) return;
      const body = {};
      body[name] = v === '' ? null : v;
      patch(body);
    }
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
      if (ev.key === 'Escape') { input.value = value || ''; input.blur(); }
    });
    input.addEventListener('blur', commit);
    wrap.append(l, input);
    return wrap;
  }

  /** A date field: a picker by default (the calendar button opens the native
   *  one), typing still works — `tomorrow`, `fri`, `in 2 weeks`, ISO
   *  (issue #46). Both dates the drawer edits go through this one builder —
   *  **Due** and, beside it, **Starts** (#87) — so they cannot drift into
   *  behaving differently, and the coarse-pointer branch below lives once.
   * @param {object} t
   * @param {string} field   the task field this edits ('due' | 'starts')
   * @param {string} label   the field label
   * @param {string} caption optional suffix on the label ("· in 3d")
   */
  function dateField(t, field, label, caption) {
    const value = t[field] || '';
    const wrap = document.createElement('label');
    wrap.className = 'field field-date field-' + field;
    const l = document.createElement('span');
    l.className = 'field-label';
    l.textContent = label + (value && caption ? ' · ' + caption : '');
    const row = document.createElement('span');
    row.className = 'field-due-row';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'input-native field-control';
    input.dataset.field = field;
    input.value = value;
    input.placeholder = 'tomorrow · fri · 2026-09-01';
    input.setAttribute('aria-label', label);
    const picker = document.createElement('input');
    picker.type = 'date';
    picker.className = 'field-due-picker';
    picker.tabIndex = -1;
    picker.setAttribute('aria-hidden', 'true');
    picker.value = value;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn field-due-btn';
    btn.title = 'Pick a date';
    btn.setAttribute('aria-label', 'Pick a ' + label.toLowerCase() + ' date');
    btn.innerHTML = icon('calendar-days');
    function commit(v) {
      if (v === value) return;
      patch(Object.fromEntries([[field, v === '' ? null : v]]));
    }
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
      if (ev.key === 'Escape') { input.value = value; input.blur(); }
    });
    input.addEventListener('blur', function () { commit(input.value.trim()); });
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      // Touch/coarse-pointer WebKit reports showPicker() as a function and
      // calling it never throws, but it opens nothing — the exception-based
      // fallback below never runs (issue #50). Coarse pointers skip straight
      // to the fallback, which does open the native picker there.
      const coarse = window.matchMedia('(pointer: coarse)').matches;
      if (!coarse) {
        try { if (typeof picker.showPicker === 'function') { picker.showPicker(); return; } } catch (_) { /* fall through */ }
      }
      picker.classList.add('is-visible');
      picker.focus();
      picker.click();
    });
    picker.addEventListener('change', function () { commit(picker.value); });
    row.append(input, btn, picker);
    wrap.append(l, row);
    return wrap;
  }

  /** "Move to…" — re-parent from the drawer (the phone has no tree drag):
   *  projects + top level; the server's cycle guard answers a bad target. */
  function moveField(t) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const l = document.createElement('span');
    l.className = 'field-label';
    l.textContent = 'Move to';
    const sel = document.createElement('select');
    sel.className = 'select-native field-control';
    sel.dataset.field = 'parent';
    const options = [{ id: '', title: 'top level', depth: 0 }]
      .concat((opts.projects ? opts.projects() : []).filter(function (p) { return p.id !== t.id; }));
    options.forEach(function (p) {
      const o = document.createElement('option');
      o.value = p.id === '' ? '' : String(p.id);
      o.textContent = (p.depth ? ' '.repeat(p.depth) : '') + p.title;
      if (String(p.id) === String(t.parent_id == null ? '' : t.parent_id)) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () {
      const v = sel.value === '' ? null : Number(sel.value);
      if (v === (t.parent_id == null ? null : t.parent_id)) return;
      opts.onMove(t.id, v);   // toasts + refreshes; a cycle comes back as a toast
    });
    wrap.append(l, sel);
    return wrap;
  }

  function render() {
    const t = current;
    el.innerHTML = '';
    if (!t) return;

    // ---- head: breadcrumb + close
    const head = document.createElement('div');
    head.className = 'drawer-head';
    const crumbs = document.createElement('nav');
    crumbs.className = 'drawer-crumbs';
    crumbs.setAttribute('aria-label', 'Breadcrumb');
    (t.breadcrumb || []).forEach(function (c, i) {
      if (i) {
        const sep = document.createElement('span');
        sep.className = 'crumb-sep';
        sep.textContent = '›';
        crumbs.appendChild(sep);
      }
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'crumb';
      b.textContent = c.title;
      b.addEventListener('click', function () { opts.onOpen(c.id); });
      crumbs.appendChild(b);
    });
    if (!(t.breadcrumb || []).length) {
      const top = document.createElement('span');
      top.className = 'crumb crumb-root';
      top.textContent = 'top level';
      crumbs.appendChild(top);
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'detail-close drawer-close';
    close.setAttribute('aria-label', 'Close');
    close.innerHTML = icon('x');
    close.addEventListener('click', function () { opts.onClose(); });
    head.append(crumbs, close);
    el.appendChild(head);

    // ---- title (editable)
    const titleRow = document.createElement('div');
    titleRow.className = 'drawer-title-row';
    const code = document.createElement('span');
    code.className = 'drawer-code';
    code.textContent = t.code || ('#' + t.id);
    // A textarea, not an input: a long title wraps to 2–3 lines instead of
    // clipping off-screen on the phone (#32). Enter still commits (below),
    // never a newline; the height follows the content.
    const title = document.createElement('textarea');
    title.rows = 1;
    title.id = 'drawerTitle';
    title.className = 'drawer-title';
    title.value = t.title;
    title.setAttribute('aria-label', 'Title');
    const fitTitle = function () {
      title.style.height = 'auto';
      title.style.height = title.scrollHeight + 'px';
    };
    title.addEventListener('input', fitTitle);
    requestAnimationFrame(fitTitle);
    title.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); title.blur(); }
      if (ev.key === 'Escape') { title.value = t.title; title.blur(); }
    });
    title.addEventListener('blur', function () {
      const v = title.value.trim();
      if (v && v !== t.title) patch({ title: v });
      else title.value = t.title;
    });
    titleRow.append(code, title);
    if (t.is_project) {
      const chip = document.createElement('span');
      chip.className = 'chip chip-project';
      chip.textContent = 'project';
      titleRow.appendChild(chip);
    }
    el.appendChild(titleRow);

    // ---- fields row
    const fields = document.createElement('div');
    fields.className = 'drawer-fields';
    fields.appendChild(statusField(t));
    fields.appendChild(selectField('Priority', 'priority', PRIORITIES, t.priority));
    fields.appendChild(dateField(t, 'due', 'Due', relDue(t.due).text));
    // Starts sits right after Due — the two dates of a task, read together.
    fields.appendChild(dateField(t, 'starts', 'Starts',
      isDeferred(t) ? relDue(t.starts).text : 'passed'));
    // Repeat is a composer (#112): the cadence, then — only for the cadences
    // that can carry one — the fixed day it lands on. Switching the cadence
    // re-renders, and the server has already dropped an anchor the new
    // cadence cannot hold, so the second select never shows a stale day.
    fields.appendChild(selectField('Repeat', 'recurrence', RECURRENCES, t.recurrence || '', function (v) { return v || 'never'; }));
    const anchorGroups = anchorOptions(t.recurrence);
    if (anchorGroups.length) fields.appendChild(anchorField(t, anchorGroups));
    const people = [{ id: '', name: '—' }].concat(opts.people() || []);
    fields.appendChild(selectField('Person', 'person_id', people.map(function (p) { return p.id; }), t.person_id == null ? '' : t.person_id, function (v) {
      const p = people.find(function (x) { return String(x.id) === String(v == null ? '' : v); });
      return p ? p.name : '—';
    }));
    fields.appendChild(textField('Code', 'code', t.code, 'optional'));
    fields.appendChild(moveField(t));
    el.appendChild(fields);

    // ---- folder (Step 9)
    el.appendChild(folderSection(t));

    // ---- description
    const desc = section('description', 'Description', 'file-text');
    const descTools = document.createElement('div');
    descTools.className = 'drawer-tools';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'button-ghost';
    toggle.innerHTML = icon(descEditing ? 'eye' : 'pencil') + ' ' + (descEditing ? 'Preview' : 'Edit');
    desc.querySelector('h3').appendChild(descTools);
    descTools.appendChild(toggle);
    const body = document.createElement('div');
    body.className = 'drawer-desc';
    if (descEditing) {
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
        descEditing = false;
        patch({ description: ta.value });
      });
      ta.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save.click(); }
      });
      body.appendChild(save);
      toggle.addEventListener('click', function () { descEditing = false; render(); });
    } else {
      const view = document.createElement('div');
      view.className = 'markdown';
      if ((t.description || '').trim()) view.innerHTML = renderMarkdown(t.description);
      else { view.classList.add('muted'); view.textContent = 'No description yet.'; }
      body.appendChild(view);
      toggle.addEventListener('click', function () { descEditing = true; render(); el.querySelector('.drawer-desc-edit').focus(); });
    }
    desc.appendChild(body);
    el.appendChild(desc);

    // ---- links
    const links = section('links', 'Links', 'link');
    const linkList = document.createElement('div');
    linkList.className = 'drawer-links';
    (t.links || []).forEach(function (l) {
      const row = document.createElement('div');
      row.className = 'link-row';
      if (editingLinkId === l.id) {
        const editInput = document.createElement('input');
        editInput.type = 'text';
        editInput.className = 'input-native link-label-edit';
        editInput.value = l.label || '';
        editInput.placeholder = 'label';
        editInput.setAttribute('aria-label', 'Edit label for ' + (l.label || l.url));
        const commit = async function () {
          const v = editInput.value.trim();
          editingLinkId = null;
          if (v !== (l.label || '')) {
            try {
              await api('/api/tasks/' + t.id + '/links/' + l.id, { method: 'PATCH', body: { label: v || null } });
              await refresh();
            } catch (err) { toast(err.message, 'error'); render(); }
          } else {
            render();
          }
        };
        editInput.addEventListener('keydown', function (ev) {
          // stopPropagation, not just preventDefault: commit() re-renders the drawer
          // synchronously (even on a no-op Escape), which detaches this input before the
          // keydown finishes bubbling — app.js's document-level Escape handler would then
          // see a target it no longer recognizes as "a field owns this key" and close the
          // drawer on top of the cancelled edit.
          if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); editInput.blur(); }
          if (ev.key === 'Escape') { ev.stopPropagation(); editInput.value = l.label || ''; editInput.blur(); }
        });
        editInput.addEventListener('blur', commit);
        row.appendChild(editInput);
        linkList.appendChild(row);
        requestAnimationFrame(function () { editInput.focus(); editInput.select(); });
        return;
      }
      // an email link is a .msg ref the opener opens as a file — same chip, mail glyph;
      // an ai link keeps the bot chip + open/resume popover regardless of URL shape
      row.appendChild(l.kind === 'ai'
        ? aiChip(l.url, l.label || null)
        : chipFor(l.url, l.label || null, l.kind === 'email' ? { icon: 'mail' } : undefined));
      const actions = document.createElement('div');
      actions.className = 'link-actions';
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'link-rm';   // borderless, chip-height; ::before carries the 44px hit rect
      edit.setAttribute('aria-label', 'Edit label for ' + (l.label || l.url));
      edit.innerHTML = icon('pencil');
      edit.addEventListener('click', function () { editingLinkId = l.id; render(); });
      actions.appendChild(edit);
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'link-rm';   // borderless, chip-height; ::before carries the 44px hit rect
      rm.setAttribute('aria-label', 'Remove link ' + (l.label || l.url));
      rm.innerHTML = icon('trash-2');
      rm.addEventListener('click', async function () {
        try {
          await api('/api/tasks/' + t.id + '/links/' + l.id, { method: 'DELETE' });
          await refresh();
        } catch (err) { toast(err.message, 'error'); }
      });
      actions.appendChild(rm);
      row.appendChild(actions);
      linkList.appendChild(row);
    });
    if (!(t.links || []).length) {
      const none = document.createElement('p');
      none.className = 'muted drawer-none';
      none.textContent = 'No links.';
      linkList.appendChild(none);
    }
    links.appendChild(linkList);
    const linkForm = document.createElement('form');
    linkForm.className = 'link-form';
    const url = document.createElement('input');
    url.type = 'text';
    url.className = 'input-native';
    url.placeholder = 'https://…  or  {onedrive}/folder';
    url.setAttribute('aria-label', 'Link URL or folder');
    const label = document.createElement('input');
    label.type = 'text';
    label.className = 'input-native';
    label.placeholder = 'label (optional)';
    label.setAttribute('aria-label', 'Link label');
    const addLink = document.createElement('button');
    addLink.type = 'submit';
    addLink.className = 'button-surface';
    addLink.textContent = 'Add link';
    linkForm.append(url, label, addLink);
    linkForm.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const u = url.value.trim();
      if (!u) return;
      const kind = linkKind(u);
      try {
        await api('/api/tasks/' + t.id + '/links', { method: 'POST', body: { url: u, label: label.value.trim() || null, kind: kind } });
        await refresh();
      } catch (err) { toast(err.message, 'error'); }
    });
    links.appendChild(linkForm);
    el.appendChild(links);

    // ---- comments (newest first) + composer
    const comments = section('comments', 'Comments', 'message-square');
    const composer = document.createElement('form');
    composer.className = 'comment-composer';
    const ta = document.createElement('textarea');
    ta.className = 'input-native comment-input';
    ta.rows = 2;
    ta.placeholder = 'Add a comment… (Ctrl+Enter to send)';
    ta.setAttribute('aria-label', 'New comment');
    ta.title = 'Ctrl+Enter to send; links become chips';
    const send = document.createElement('button');
    send.type = 'submit';
    // Same tier and metrics as the Description "Edit" button — quiet, not a
    // full-height primary block.
    send.className = 'button-ghost comment-send';
    send.setAttribute('aria-label', 'Send comment');
    send.innerHTML = icon('send-horizontal') + ' Send';
    composer.append(ta, send);
    composer.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const bodyText = ta.value.trim();
      if (!bodyText) return;
      send.disabled = true;
      try {
        await api('/api/tasks/' + t.id + '/comments', { method: 'POST', body: { body: bodyText, origin: 'ui' } });
        ta.value = '';
        await refresh();
        opts.onChanged();
      } catch (err) {
        toast(err.message || 'Comment failed', 'error');
      } finally { send.disabled = false; }
    });
    ta.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); composer.requestSubmit(); }
    });
    comments.appendChild(composer);
    const clist = document.createElement('div');
    clist.className = 'comment-list';
    const ordered = (t.comments || []).slice().reverse();
    ordered.forEach(function (c) {
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
      origin.className = 'comment-origin';
      origin.textContent = c.origin;
      meta.append(who, when, origin);
      const bodyEl = document.createElement('div');
      bodyEl.className = 'comment-body';
      bodyEl.appendChild(linkify(c.body));
      row.append(meta, bodyEl);
      clist.appendChild(row);
    });
    if (!ordered.length) {
      const none = document.createElement('p');
      none.className = 'muted drawer-none';
      none.textContent = 'No comments yet.';
      clist.appendChild(none);
    }
    comments.appendChild(clist);
    el.appendChild(comments);

    // ---- activity
    const activity = section('activity', 'Activity', 'activity');
    const alist = document.createElement('div');
    alist.className = 'activity-list';
    (t.activity || []).forEach(function (a) {
      const row = document.createElement('div');
      row.className = 'activity-row';
      row.dataset.field = a.field;
      const change = document.createElement('span');
      change.className = 'activity-change';
      // One weight for the whole line — the field name is set apart by color
      // only (uniform-weight feedback, issue #27).
      const f = document.createElement('span');
      f.className = 'activity-field';
      f.textContent = a.field;
      change.appendChild(f);
      change.appendChild(document.createTextNode(' '));
      const oldV = document.createElement('span');
      oldV.className = 'activity-old';
      oldV.textContent = a.old_value == null ? '∅' : a.old_value;
      const arrow = document.createElement('span');
      arrow.className = 'activity-arrow';
      arrow.textContent = ' → ';
      const newV = document.createElement('span');
      newV.className = 'activity-new';
      newV.textContent = a.new_value == null ? '∅' : a.new_value;
      change.append(oldV, arrow, newV);
      const meta = document.createElement('span');
      meta.className = 'activity-meta';
      meta.textContent = a.actor + ' · ' + fmtTs(a.ts);
      meta.title = a.ts;
      row.append(change, meta);
      alist.appendChild(row);
    });
    activity.appendChild(alist);
    el.appendChild(activity);

    // ---- children
    const children = section('children', 'Children', 'corner-down-right');
    const kids = document.createElement('div');
    kids.className = 'children-list';
    (t.children || []).forEach(function (c) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'child-row';
      const ct = document.createElement('span');
      ct.className = 'child-title';
      ct.textContent = c.title;
      b.appendChild(ct);
      if (c.due) {
        const d = relDue(c.due);
        const cd = document.createElement('span');
        cd.className = 'child-due' + (d.tone ? ' due-' + d.tone : '');
        cd.textContent = d.text;
        cd.title = c.due;
        b.appendChild(cd);
      }
      b.appendChild(statusPill(c.status));
      b.addEventListener('click', function () { opts.onOpen(c.id); });
      kids.appendChild(b);
    });
    children.appendChild(kids);
    const addChild = document.createElement('form');
    addChild.className = 'child-add';
    const ci = document.createElement('input');
    ci.type = 'text';
    ci.className = 'input-native';
    ci.placeholder = 'Add child task…';
    ci.setAttribute('aria-label', 'Add child task');
    const cb = document.createElement('button');
    cb.type = 'submit';
    cb.className = 'button-surface';
    cb.textContent = 'Add child';
    addChild.append(ci, cb);
    addChild.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const v = ci.value.trim();
      if (!v) return;
      try {
        await api('/api/tasks', { method: 'POST', body: { title: v, parent_id: t.id } });
        await refresh();
        opts.onChanged();
      } catch (err) { toast(err.message, 'error'); }
    });
    children.appendChild(addChild);
    el.appendChild(children);

    // ---- issue panel
    el.appendChild(renderIssuePanel(t));

    // ---- delete (#121): the one destructive control, last and quiet
    el.appendChild(renderDeleteFoot(t));
  }

  /** A `Delete task` at the foot, away from the status select. The dialog
   *  names the task, the subtree that goes with it, and — for a synced coding
   *  task whose issue is still open — that the next sync brings it back
   *  (Roberto's call, never a silent resurrection). */
  function renderDeleteFoot(t) {
    const foot = document.createElement('div');
    foot.className = 'drawer-section drawer-danger';
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'button-ghost drawer-delete';
    del.innerHTML = icon('trash-2') + ' Delete task';
    del.title = 'Delete this task' + (t.descendant_count ? ' and its ' + t.descendant_count + ' child task' + (t.descendant_count === 1 ? '' : 's') : '') + ' — asks first';
    del.addEventListener('click', function () { deleteCurrent(t); });
    foot.appendChild(del);
    return foot;
  }

  async function deleteCurrent(t) {
    const n = Number(t.descendant_count) || 0;
    const ref = t.issue_ref;
    const ok = await confirmDialog({
      title: 'Delete "' + t.title + '"?',
      lines: [
        n ? 'Its ' + n + ' child task' + (n === 1 ? ' goes' : 's go') + ' with it.' : null,
        'This cannot be undone: the task, its comments, links and history are removed.',
      ],
      warn: ref && ref.state === 'open'
        ? 'Synced coding task: the next issue sync recreates it while ' + ref.repo + '#' + ref.number + ' stays open. Unlink it first, or close the issue.'
        : null,
      action: 'Delete',
    });
    if (!ok || !current || current.id !== t.id) return;
    try {
      const r = await api('/api/tasks/' + t.id, { method: 'DELETE' });
      opts.onClose();
      const gone = Number(r && r.deleted) || 1;
      toast('Deleted "' + t.title + '"' + (gone > 1 ? ' · ' + gone + ' tasks' : ''), 'success');
      opts.onChanged();
    } catch (err) {
      toast(err.message || 'Delete failed', 'error');
    }
  }

  function renderIssuePanel(t) {
    const st = (opts.issues && opts.issues()) || null;
    const configured = !!(st && st.enabled);
    const issue = section('issue', 'Issue', t.issue_ref ? providerIcon(t.issue_ref.provider) : 'git-branch');
    const tools = document.createElement('div');
    tools.className = 'drawer-tools';
    const sync = document.createElement('button');
    sync.type = 'button';
    sync.className = 'button-ghost issue-sync';
    sync.innerHTML = icon('refresh-cw') + ' Sync now';
    sync.title = configured ? 'Run an issue sync now' : ('Issue provider not configured' + (st && st.reason ? ': ' + st.reason : ''));
    sync.disabled = !configured;
    sync.addEventListener('click', async function () {
      sync.disabled = true;
      sync.classList.add('is-busy');
      try { await opts.onSyncIssues(); await refresh(); } finally { sync.disabled = !configured; sync.classList.remove('is-busy'); }
    });
    tools.appendChild(sync);
    issue.querySelector('h3').appendChild(tools);

    const ib = document.createElement('div');
    ib.className = 'issue-panel';
    if (t.issue_ref) {
      const ref = t.issue_ref;
      const head = document.createElement('div');
      head.className = 'issue-head';
      head.appendChild(issueChip(ref));
      const stPill = document.createElement('span');
      stPill.className = 'pill issue-state pill-' + (ref.state === 'closed' ? 'done' : (ref.state === 'open' ? 'doing' : 'inbox'));
      stPill.textContent = ref.state || 'state unknown';
      head.appendChild(stPill);
      const labels = document.createElement('span');
      labels.className = 'issue-labels';
      head.appendChild(labels);
      ib.appendChild(head);
      const meta = document.createElement('div');
      meta.className = 'issue-meta muted';
      meta.textContent = (ref.provider || 'issue') + ' · ' + (ref.last_synced ? 'last synced ' + fmtTs(ref.last_synced) : 'not synced yet');
      ib.appendChild(meta);
      const actions = document.createElement('div');
      actions.className = 'issue-actions';
      const unlink = document.createElement('button');
      unlink.type = 'button';
      unlink.className = 'button-ghost issue-unlink';
      unlink.innerHTML = icon('unlink') + ' Unlink';
      unlink.title = 'Detach the issue — the task becomes a plain task; the issue is untouched';
      unlink.addEventListener('click', async function () {
        try {
          await api('/api/tasks/' + t.id + '/issue', { method: 'DELETE' });
          toast('Unlinked ' + ref.repo + '#' + ref.number, 'success');
          await refresh();
          opts.onChanged();
        } catch (err) { toast(err.message || 'Unlink failed', 'error'); }
      });
      actions.appendChild(unlink);
      ib.appendChild(actions);
      // labels + the forge's updated time from the last sync (cached server-side; async, best effort)
      api('/api/tasks/' + t.id + '/issue').then(function (res) {
        if (!current || current.id !== t.id || !res || !res.info) return;
        (res.info.labels || []).forEach(function (name) {
          const l = document.createElement('span');
          l.className = 'chip chip-label-tag';
          l.textContent = name;
          labels.appendChild(l);
        });
        if (res.info.updated_at) meta.textContent += ' · updated ' + fmtTs(res.info.updated_at);
      }).catch(function () { /* the panel already shows the stored ref */ });
    } else {
      const none = document.createElement('p');
      none.className = 'muted drawer-none';
      none.textContent = configured ? 'No issue linked.' : ('No issue linked. Issue provider not configured' + (st && st.reason ? ' — ' + st.reason : '') + '.');
      ib.appendChild(none);

      // create an issue from this task
      const createForm = document.createElement('form');
      createForm.className = 'issue-form issue-create';
      const repoInput = document.createElement('input');
      repoInput.type = 'text';
      repoInput.className = 'input-native';
      repoInput.placeholder = 'owner/repo';
      repoInput.setAttribute('aria-label', 'Repository for the new issue');
      repoInput.setAttribute('list', 'issueRepos');
      const repos = (st && st.repos) || [];
      let dl = document.getElementById('issueRepos');
      if (!dl) { dl = document.createElement('datalist'); dl.id = 'issueRepos'; document.body.appendChild(dl); }
      dl.replaceChildren();
      repos.forEach(function (r) { const o = document.createElement('option'); o.value = r; dl.appendChild(o); });
      if (repos.length === 1) repoInput.value = repos[0];
      const createBtn = document.createElement('button');
      createBtn.type = 'submit';
      createBtn.className = 'button-surface';
      createBtn.innerHTML = icon('plus') + ' Create issue';
      createBtn.disabled = !configured;
      createBtn.title = configured ? "Open an issue with this task's title and description, then link it" : 'Issue provider not configured';
      createForm.append(repoInput, createBtn);
      createForm.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        const r = repoInput.value.trim();
        if (!r) { repoInput.focus(); return; }
        createBtn.disabled = true;
        try {
          const res = await api('/api/tasks/' + t.id + '/issue', { method: 'POST', body: { repo: r } });
          const ref = res.issue_ref || {};
          toast('Created ' + ref.repo + '#' + ref.number, 'success');
          await refresh();
          opts.onChanged();
        } catch (err) {
          toast(err.message || 'Could not create the issue', 'error');
          createBtn.disabled = !configured;
        }
      });
      ib.appendChild(createForm);

      // link an existing issue
      const linkForm = document.createElement('form');
      linkForm.className = 'issue-form issue-link';
      const refInput = document.createElement('input');
      refInput.type = 'text';
      refInput.className = 'input-native';
      refInput.placeholder = 'link existing: owner/repo#12 or its URL';
      refInput.setAttribute('aria-label', 'Existing issue reference');
      const linkBtn = document.createElement('button');
      linkBtn.type = 'submit';
      linkBtn.className = 'button-surface';
      linkBtn.innerHTML = icon('link') + ' Link';
      linkForm.append(refInput, linkBtn);
      linkForm.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        const v = refInput.value.trim();
        const m = /^([\w.-]+\/[\w.-]+)#(\d+)$/.exec(v) || /(?:github|gitlab)\.com\/([^/\s]+\/[^/\s#?]+)\/(?:-\/)?issues\/(\d+)/.exec(v);
        if (!m) { toast('Use owner/repo#N or the issue URL', 'error'); refInput.focus(); return; }
        const provider = /gitlab\.com/.test(v) ? 'gitlab' : ((st && st.provider) || 'github');
        try {
          await api('/api/tasks/' + t.id + '/issue', { method: 'PUT', body: { provider: provider, repo: m[1], number: Number(m[2]) } });
          toast('Linked ' + m[1] + '#' + m[2], 'success');
          if (configured) { try { await opts.onSyncIssues(); } catch (_) { /* the sync toast said it */ } }
          await refresh();
          opts.onChanged();
        } catch (err) { toast(err.message || 'Link failed', 'error'); }
      });
      ib.appendChild(linkForm);
    }
    issue.appendChild(ib);
    return issue;
  }

  // ---- folder section: two lines — [chip + delete] / [ref + Change + Pick]
  // The resolved path is NOT repeated as a third line: it is already the chip's
  // own `title` (format.js), and the phone reaches it through the chip's copy
  // popover (#74). An unresolvable ref keeps its warning ON the chip — a
  // placeholder this server does not know is a config fault, not a silent one.
  function folderSection(t) {
    const sec = section('folder', 'Folder', 'folder');
    const body = document.createElement('div');
    body.className = 'drawer-folder';
    if (t.folder_ref) {
      const cur = document.createElement('div');
      cur.className = 'folder-current';
      const chip = chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url });
      if (t.folder_resolved) {
        chip.title = t.folder_resolved + ' — the path this server resolves the ref to';
      } else {
        chip.classList.add('chip-missing');
        chip.title = t.folder_ref + ' — placeholder not configured on this server; add it to config.placeholders';
        chip.insertAdjacentHTML('beforeend', icon('triangle-alert'));
      }
      cur.appendChild(chip);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'icon-btn';
      remove.setAttribute('aria-label', 'Remove folder link');
      remove.innerHTML = icon('trash-2');
      remove.addEventListener('click', function () { commitFolder(''); });
      cur.appendChild(remove);
      body.appendChild(cur);
    }
    const form = document.createElement('form');
    form.className = 'folder-form';
    const input = document.createElement('input');
    input.type = 'text';
    input.id = 'drawerFolder';
    input.className = 'input-native';
    input.value = t.folder_ref || '';
    input.placeholder = '{onedrive}/folder  — or paste an absolute path';
    input.setAttribute('aria-label', 'Folder ref');
    const save = document.createElement('button');
    save.type = 'submit';
    save.className = 'button-surface';
    save.textContent = t.folder_ref ? 'Change' : 'Set folder';
    const pick = document.createElement('button');
    pick.type = 'button';
    pick.className = 'button-ghost folder-pick';
    // label span, not a bare text node: the phone drops it to keep line 2 on
    // one line (styles.css) - the accessible name lives on aria-label either way
    pick.innerHTML = icon('search') + '<span class="folder-pick-label">Pick from index</span>';
    pick.setAttribute('aria-label', 'Pick from folder index');
    pick.title = 'Pick from folder index';
    pick.setAttribute('aria-expanded', String(pickerOpen));
    form.append(input, save, pick);
    form.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const v = input.value.trim();
      if (v === (t.folder_ref || '')) return;
      await commitFolder(v);
    });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { input.value = t.folder_ref || ''; input.blur(); }
    });
    body.appendChild(form);
    const picker = document.createElement('div');
    picker.className = 'folder-picker';
    picker.hidden = !pickerOpen;
    const mount = function () {
      mountFolderPicker(picker, { onPick: commitFolder, onClose: function () { pickerOpen = false; } });
    };
    if (pickerOpen) mount();
    pick.addEventListener('click', function () {
      pickerOpen = !pickerOpen;
      picker.hidden = !pickerOpen;
      pick.setAttribute('aria-expanded', String(pickerOpen));
      if (pickerOpen) { mount(); picker.querySelector('input').focus(); }
    });
    body.appendChild(picker);
    sec.appendChild(body);
    return sec;
  }

  /** The ref the task stores (folderpick.js folds an absolute path onto the
   *  placeholders; `undefined` means the fold failed and already said so). */
  async function commitFolder(value) {
    const ref = await resolveFolderRef(value);
    if (ref === undefined) return;
    pickerOpen = false;
    await patch({ folder_ref: ref });
  }

  async function refresh() {
    if (current == null) return;
    const id = current.id;
    try {
      const data = await api('/api/tasks/' + id);
      if (current && current.id === id) { current = data; render(); }
    } catch (err) {
      toast(err.message || 'Could not load the task', 'error');
    }
  }

  return {
    async open(id) {
      descEditing = false;
      pickerOpen = false;
      editingLinkId = null;
      try {
        const data = await api('/api/tasks/' + id);
        current = data;
        render();
        el.hidden = false;
        document.body.dataset.drawer = 'open';
        el.scrollTop = 0;
        if (opts.onToggle) opts.onToggle(current.id);
      } catch (err) {
        toast(err.message || 'Task not found', 'error');
        opts.onClose();
      }
    },
    close() {
      current = null;
      el.hidden = true;
      el.innerHTML = '';
      delete document.body.dataset.drawer;
      if (opts.onToggle) opts.onToggle(null);
    },
    refresh: refresh,
    currentId() { return current ? current.id : null; },
  };
}
