/* task-os — the task drawer.
 *
 * A right-hand side panel on desktop (>= 1024px; the content shrinks so the
 * list stays visible), a full-screen sheet on the phone. Deep-linkable as
 * #task/<id> (app.js owns the hash). Top to bottom: breadcrumb → editable
 * title → fields row (status, priority, due, recurrence, person, code) →
 * folder (the ref as an opener chip + resolved path, an editor that folds a
 * pasted absolute path onto the placeholders, a picker over the folder
 * index — Step 9) → description (markdown, edit/preview) → links (add/remove) → comments
 * newest-first with URLs as clickable chips + composer (Ctrl+Enter sends,
 * origin=ui) → activity log (field old → new · actor · time) → children
 * (click to navigate, add child) → issue panel (placeholder until Step 8).
 *
 * Every write goes through the API and then `refresh()`, and the caller's
 * `onChanged` re-renders the Table / Tree so the three surfaces never drift.
 */

'use strict';

import { api } from './api.js';
import { icon } from './_vendored/icons/icons.js';
import {
  PRIORITIES, RECURRENCES, STATUSES, chipFor, copyText, fmtTs, linkify, relDue, renderMarkdown, statusPill,
} from './format.js';
import { toast } from './toast.js';

/**
 * @param {HTMLElement} el     the <aside id="taskDrawer">
 * @param {{onChanged: () => void, onOpen: (id:number) => void, onClose: () => void, people: () => Array<{id:number,name:string}>}} opts
 */
export function createDrawer(el, opts) {
  let current = null;      // the detail payload
  let descEditing = false;
  let pickerOpen = false;  // the folder-index picker under the Folder field

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
    const title = document.createElement('input');
    title.type = 'text';
    title.id = 'drawerTitle';
    title.className = 'drawer-title';
    title.value = t.title;
    title.setAttribute('aria-label', 'Title');
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
    fields.appendChild(selectField('Status', 'status', STATUSES, t.status));
    fields.appendChild(selectField('Priority', 'priority', PRIORITIES, t.priority));
    const dueRel = relDue(t.due);
    fields.appendChild(textField('Due' + (t.due && dueRel.text ? ' · ' + dueRel.text : ''), 'due', t.due, 'tomorrow · fri · 2026-09-01'));
    fields.appendChild(selectField('Repeat', 'recurrence', RECURRENCES, t.recurrence || '', function (v) { return v || 'never'; }));
    const people = [{ id: '', name: '—' }].concat(opts.people() || []);
    fields.appendChild(selectField('Person', 'person_id', people.map(function (p) { return p.id; }), t.person_id == null ? '' : t.person_id, function (v) {
      const p = people.find(function (x) { return String(x.id) === String(v == null ? '' : v); });
      return p ? p.name : '—';
    }));
    fields.appendChild(textField('Code', 'code', t.code, 'optional'));
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
      row.appendChild(chipFor(l.url, l.label || null));
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'icon-btn hit-target';
      rm.setAttribute('aria-label', 'Remove link ' + (l.label || l.url));
      rm.innerHTML = icon('trash-2');
      rm.addEventListener('click', async function () {
        try {
          await api('/api/tasks/' + t.id + '/links/' + l.id, { method: 'DELETE' });
          await refresh();
        } catch (err) { toast(err.message, 'error'); }
      });
      row.appendChild(rm);
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
      const kind = /^\{/.test(u) ? 'folder' : (/^mail(to:|:\/\/)/i.test(u) ? 'email' : (/github\.com\/[^/]+\/[^/]+\/issues\/\d+/.test(u) ? 'issue' : 'web'));
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
    ta.placeholder = 'Add a comment… (Ctrl+Enter to send; links become chips)';
    ta.setAttribute('aria-label', 'New comment');
    const send = document.createElement('button');
    send.type = 'submit';
    send.className = 'button-primary comment-send';
    send.setAttribute('aria-label', 'Send comment');
    send.innerHTML = icon('send-horizontal');
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
      const f = document.createElement('strong');
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

    // ---- issue panel (Step 8 wires the providers)
    const issue = section('issue', 'Issue', 'git-branch');
    const ib = document.createElement('div');
    ib.className = 'issue-panel';
    if (t.issue_ref) {
      const ref = t.issue_ref;
      const chip = chipFor(ref.url || ('https://github.com/' + ref.repo + '/issues/' + ref.number), ref.repo + '#' + ref.number);
      ib.appendChild(chip);
      const st = document.createElement('span');
      st.className = 'pill pill-' + (ref.state === 'closed' ? 'done' : 'doing');
      st.textContent = ref.state || 'unknown';
      ib.appendChild(st);
    } else {
      ib.className += ' muted';
      ib.textContent = 'No issue linked.';
    }
    issue.appendChild(ib);
    el.appendChild(issue);
  }

  // ---- folder section: chip + resolved path + editor + folder-index picker
  function folderSection(t) {
    const sec = section('folder', 'Folder', 'folder');
    const body = document.createElement('div');
    body.className = 'drawer-folder';
    if (t.folder_ref) {
      const cur = document.createElement('div');
      cur.className = 'folder-current';
      cur.appendChild(chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url }));
      const path = document.createElement('code');
      path.className = 'folder-resolved' + (t.folder_resolved ? '' : ' muted');
      path.textContent = t.folder_resolved || 'placeholder not configured on this server';
      path.title = t.folder_resolved ? 'this server resolves the ref to this path' : 'add the placeholder to config.placeholders';
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'button-ghost folder-copy';
      copy.innerHTML = icon('copy') + ' Copy path';
      copy.addEventListener('click', function () { copyText(t.folder_resolved || t.folder_ref, copy); });
      cur.append(path, copy);
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
    pick.innerHTML = icon('search') + ' Pick from folder index…';
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
    if (pickerOpen) mountPicker(picker);
    pick.addEventListener('click', function () {
      pickerOpen = !pickerOpen;
      picker.hidden = !pickerOpen;
      pick.setAttribute('aria-expanded', String(pickerOpen));
      if (pickerOpen) { mountPicker(picker); picker.querySelector('input').focus(); }
    });
    body.appendChild(picker);
    sec.appendChild(body);
    return sec;
  }

  /** Empty / a ref / an absolute path → the ref the task stores (absolute paths
   *  fold onto the placeholders via GET /api/resolve — never resolved client-side). */
  async function commitFolder(value) {
    if (!value) { await patch({ folder_ref: null }); return; }
    let ref = value;
    if (!/^\{/.test(value)) {
      try {
        const r = await api('/api/resolve?ref=' + encodeURIComponent(value));
        ref = r.ref;
        if (ref !== value) toast('Stored as ' + ref, 'info');
      } catch (err) { toast(err.message || 'Could not resolve the path', 'error'); return; }
    }
    pickerOpen = false;
    await patch({ folder_ref: ref });
  }

  function mountPicker(host) {
    if (host.dataset.mounted) return;
    host.dataset.mounted = '1';
    const q = document.createElement('input');
    q.type = 'search';
    q.className = 'input-native folder-picker-q';
    q.placeholder = 'Search folders… (Enter attaches the first hit)';
    q.setAttribute('aria-label', 'Search the folder index');
    const list = document.createElement('ul');
    list.className = 'folder-picker-list';
    list.setAttribute('role', 'listbox');
    const note = document.createElement('p');
    note.className = 'muted folder-picker-note';
    note.textContent = 'Type to search the folder index.';
    host.append(q, list, note);
    let timer = null;
    let items = [];
    let active = -1;
    function paint() {
      list.innerHTML = '';
      items.forEach(function (it, i) {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.className = 'folder-picker-item' + (i === active ? ' is-active' : '');
        li.dataset.ref = it.ref;
        li.title = it.path;
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'folder-picker-btn';
        b.innerHTML = icon('folder');
        const name = document.createElement('span');
        name.className = 'folder-picker-name';
        name.textContent = it.name;
        const ref = document.createElement('span');
        ref.className = 'folder-picker-ref';
        ref.textContent = it.ref;
        b.append(name, ref);
        b.addEventListener('click', function () { commitFolder(it.ref); });
        li.appendChild(b);
        list.appendChild(li);
      });
    }
    async function search() {
      const text = q.value.trim();
      if (!text) { items = []; active = -1; paint(); note.textContent = 'Type to search the folder index.'; return; }
      try {
        const r = await api('/api/folders/search?q=' + encodeURIComponent(text) + '&limit=15');
        items = r.items || [];
        active = items.length ? 0 : -1;
        paint();
        note.textContent = items.length
          ? r.count + ' hit(s)' + (r.indexing ? ' · index still building' : '')
          : (r.indexing ? 'No hits yet — the index is still building.' : 'No folder matches.');
      } catch (err) {
        items = []; active = -1; paint();
        note.textContent = err.code === 'folders_disabled'
          ? 'Folder index not configured — set search.folder_roots in config.json (' + err.message + ').'
          : ('Search failed: ' + err.message);
      }
    }
    q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(search, 220); });
    q.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowDown' && items.length) { ev.preventDefault(); active = (active + 1) % items.length; paint(); }
      else if (ev.key === 'ArrowUp' && items.length) { ev.preventDefault(); active = (active - 1 + items.length) % items.length; paint(); }
      else if (ev.key === 'Enter') { ev.preventDefault(); if (active >= 0 && items[active]) commitFolder(items[active].ref); }
      else if (ev.key === 'Escape') { pickerOpen = false; host.hidden = true; }
    });
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
      try {
        const data = await api('/api/tasks/' + id);
        current = data;
        render();
        el.hidden = false;
        document.body.dataset.drawer = 'open';
        el.scrollTop = 0;
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
    },
    refresh: refresh,
    currentId() { return current ? current.id : null; },
  };
}
