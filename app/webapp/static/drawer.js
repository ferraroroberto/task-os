/* task-os — the task drawer.
 *
 * A right-hand side panel on desktop (>= 1024px; the content shrinks so the
 * list stays visible), a full-screen sheet on the phone. Deep-linkable as
 * #task/<id> (app.js owns the hash). Top to bottom: breadcrumb → editable
 * title → fields row (status, priority, due, recurrence, person, code) →
 * description (markdown, edit/preview) → links (add/remove) → comments
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
import {
  PRIORITIES, RECURRENCES, STATUSES, chipFor, fmtTs, issueChip, linkify, providerIcon, relDue,
  renderMarkdown, statusPill,
} from './format.js';
import { toast } from './toast.js';

/**
 * @param {HTMLElement} el     the <aside id="taskDrawer">
 * @param {{onChanged: () => void, onOpen: (id:number) => void, onClose: () => void,
 *          people: () => Array<{id:number,name:string}>,
 *          issues: () => ({enabled:boolean, reason?:string, provider?:string, repos?:string[]}|null),
 *          onSyncIssues: () => Promise<any>}} opts
 */
export function createDrawer(el, opts) {
  let current = null;      // the detail payload
  let descEditing = false;

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

    // ---- issue panel
    el.appendChild(renderIssuePanel(t));
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
