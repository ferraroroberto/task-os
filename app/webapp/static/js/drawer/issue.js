/* task-os — the drawer's issue panel: the linked issue, or Create / Link
 * for a plain task. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { fmtTs, issueChip, providerIcon, toneChip } from '../../format.js';
import { toast } from '../../toast.js';
import { formButton, section } from './dom.js';

/** The "Sync now" tool in the section title; off while no provider is configured. */
function syncTools(ctx, st, configured) {
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
    try { await ctx.opts.onSyncIssues(); await ctx.refresh(); } finally { sync.disabled = !configured; sync.classList.remove('is-busy'); }
  });
  tools.appendChild(sync);
  return tools;
}

/** The linked issue: chip, state, labels, last sync and Unlink. */
function linkedIssue(ctx, t, ib) {
  const ref = t.issue_ref;
  const head = document.createElement('div');
  head.className = 'issue-head';
  head.appendChild(issueChip(ref));
  // Open and closed are the issue's normal states, a quiet word; a state
  // the sync never established is the exception, a neutral chip.
  let stMark;
  if (ref.state === 'open' || ref.state === 'closed') {
    stMark = document.createElement('span');
    stMark.className = 'status-word';
    stMark.textContent = ref.state;
  } else {
    stMark = toneChip('state unknown', 'neutral');
  }
  stMark.classList.add('issue-state');
  head.appendChild(stMark);
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
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) { toast(err.message || 'Unlink failed', 'error'); }
  });
  actions.appendChild(unlink);
  ib.appendChild(actions);
  // labels + the forge's updated time from the last sync (cached server-side; async, best effort)
  api('/api/tasks/' + t.id + '/issue').then(function (res) {
    if (!ctx.current || ctx.current.id !== t.id || !res || !res.info) return;
    (res.info.labels || []).forEach(function (name) {
      const l = document.createElement('span');
      l.className = 'chip chip-label-tag';
      l.textContent = name;
      labels.appendChild(l);
    });
    if (res.info.updated_at) meta.textContent += ' · updated ' + fmtTs(res.info.updated_at);
  }).catch(function () { /* the panel already shows the stored ref */ });
}

/** Create an issue from this task. */
function createIssueForm(ctx, t, st, configured) {
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
  const createBtn = formButton(createForm, 'button-surface', icon('plus') + ' Create issue');
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
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) {
      toast(err.message || 'Could not create the issue', 'error');
      createBtn.disabled = !configured;
    }
  });
  return createForm;
}

/** Link an existing issue by `owner/repo#N` or its URL. */
function linkIssueForm(ctx, t, st, configured) {
  const linkForm = document.createElement('form');
  linkForm.className = 'issue-form issue-link';
  const refInput = document.createElement('input');
  refInput.type = 'text';
  refInput.className = 'input-native';
  refInput.placeholder = 'link existing: owner/repo#12 or its URL';
  refInput.setAttribute('aria-label', 'Existing issue reference');
  linkForm.append(refInput, formButton(linkForm, 'button-surface', icon('link') + ' Link'));
  linkForm.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const v = refInput.value.trim();
    // GitLab paths nest (group/sub-group/project) and hosts self-host, so the
    // path may have more than two segments and the URL any host; a URL
    // with GitLab's `/-/issues/` separator is a GitLab issue.
    const m = /^([\w.-]+(?:\/[\w.-]+)+)#(\d+)$/.exec(v) || /^(?:https?:\/\/)?[\w-]+(?:\.[\w-]+)+(?::\d+)?\/([^\s#?]+?)\/(?:-\/)?issues\/(\d+)/.exec(v);
    if (!m) { toast('Use owner/repo#N or the issue URL', 'error'); refInput.focus(); return; }
    const provider = /gitlab\.com|\/-\/issues\//.test(v) ? 'gitlab' : (/github\.com\//.test(v) ? 'github' : ((st && st.provider) || 'github'));
    try {
      await api('/api/tasks/' + t.id + '/issue', { method: 'PUT', body: { provider: provider, repo: m[1], number: Number(m[2]) } });
      toast('Linked ' + m[1] + '#' + m[2], 'success');
      if (configured) { try { await ctx.opts.onSyncIssues(); } catch (_) { /* the sync toast said it */ } }
      await ctx.refresh();
      ctx.opts.onChanged();
    } catch (err) { toast(err.message || 'Link failed', 'error'); }
  });
  return linkForm;
}

export function renderIssuePanel(ctx, t) {
  const st = (ctx.opts.issues && ctx.opts.issues()) || null;
  const configured = !!(st && st.enabled);
  const issue = section('issue', 'Issue', t.issue_ref ? providerIcon(t.issue_ref.provider) : 'git-branch');
  issue.querySelector('h3').appendChild(syncTools(ctx, st, configured));

  const ib = document.createElement('div');
  ib.className = 'issue-panel';
  if (t.issue_ref) {
    linkedIssue(ctx, t, ib);
  } else {
    const none = document.createElement('p');
    none.className = 'muted drawer-none';
    none.textContent = configured ? 'No issue linked.' : ('No issue linked. Issue provider not configured' + (st && st.reason ? ' — ' + st.reason : '') + '.');
    ib.appendChild(none);
    ib.appendChild(createIssueForm(ctx, t, st, configured));
    ib.appendChild(linkIssueForm(ctx, t, st, configured));
  }
  issue.appendChild(ib);
  return issue;
}
