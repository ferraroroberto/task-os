/* task-os — the task drawer.
 *
 * A right-hand side panel on desktop (>= 1024px; the content shrinks so the
 * list stays visible), a full-screen sheet on the phone. Deep-linkable as
 * #task/<id> (app.js owns the hash).
 *
 * Ordered by the owner's usual flow on a task: set its status, re-plan its
 * due date, read and add a comment, close it. Top to bottom: the head (the
 * breadcrumb, which is the parent picker's button; an "Inbox" tag on an Inbox
 * task; ⋯ with Open parent and Delete; close) → the editable title → Status
 * as a segmented control (To do · Standby · Cancelled · Done; Done closes the
 * drawer with an Undo toast) → Due as the date chips the row menu shows too →
 * Comments, newest three then "Show N older" (the composer heads them, or on
 * the phone is pinned to the drawer's foot; Send is the drawer's one primary
 * button) → the property list (Links as one-click pills with + for the folder
 * and link editors, Due typed in place, Owner, Person, Parent, Repeat with
 * its every-N and fixed day, then Priority) → Notes (a tap edits, leaving
 * saves) → **More fields**, closed until opened and then kept open for the
 * page's life: starts, code, blocked by, children, the issue panel →
 * Activity, folded behind its count. A wide drawer lays the content and the
 * properties side by side (styles/drawer.css).
 *
 * With a task open, the row keys act on it (keys.js asks `handleKey`): 1 · 2
 * · 3 status, X done, T · W due, D a picked date, P priority, C comment, E
 * the folder, L the folder and link editors.
 *
 * Every write goes through the API and then `refresh()`, and the caller's
 * `onChanged` re-renders the lists so the surfaces never drift.
 *
 * This file is the composer: it owns the open / close / refresh lifecycle and
 * the `ctx` object (the caller's `opts`, the loaded task and the few pieces of
 * view state that survive a re-render). Each part of the body lives in
 * js/drawer/<part>.js and takes `ctx` as its first argument.
 */

'use strict';

import { api } from './api.js';
import { toast } from './toast.js';
import { handleKey, setStatus, toggleLinks } from './js/drawer/flow.js';
import { SHEET_QUERY, renderDrawer } from './js/drawer/render.js';

/** The task payload and who is looking. The author is read on every open and
 *  every refresh, not once at start, because Settings' "Your name" changes it
 *  live under a drawer that stays open; a failed read is an unknown author,
 *  never a failed load. */
async function loadTask(id) {
  const [task, me] = await Promise.all([api('/api/tasks/' + id), api('/api/me').catch(function () { return null; })]);
  return { task: task, author: me && me.author ? me.author : null };
}

/** A fresh task starts with every piece of view state folded.
 *
 *  Why the drawer numbers its loads: one hash navigation fires `popstate`
 *  *and* `hashchange`, so an open could run twice for one click and fetch
 *  twice; the slower answer, read before an edit, then painted over the
 *  edit's own refresh and showed a value the server had already changed. So
 *  every load takes a number and only the newest renders, and `opening` (the
 *  id an open is still fetching) drops the navigation's second arrival. */
function resetView(ctx) {
  ctx.descEditing = false;
  ctx.pickerOpen = false;
  ctx.editingLinkId = null;
  ctx.editingCommentId = null;
  ctx.syncShown = false;
  ctx.linksEditing = false;
  ctx.commentsAll = false;
}

/**
 * @param {HTMLElement} el     the <aside id="taskDrawer">
 * @param {{onChanged: () => void, onOpen: (id:number) => void, onClose: () => void,
 *          people: () => Array<{id:number,name:string}>,
 *          members: () => Array<{id:string,name:string}>,
 *          onPc: () => boolean,
 *          parentTargets: (id:number) => Array<{id:number,title:string,depth:number,path:string}>,
 *          allTasks: () => Array<{id:number,title:string,depth?:number}>,
 *          onMove: (id:number, parentId:number|null) => Promise<any>,
 *          onStatus: (id:number, status:string) => Promise<any>,
 *          issues: () => ({enabled:boolean, reason?:string, provider?:string, repos?:string[]}|null),
 *          onSyncIssues: () => Promise<any>}} opts
 */
export function createDrawer(el, opts) {
  // Only the newest load may render, and a second arrival of one navigation
  // is dropped (resetView says why).
  let loads = 0;
  let opening = null;

  const ctx = {
    el: el,
    opts: opts,
    current: null,             // the detail payload
    author: null,              // /api/me's author: the name this device's comments are signed with
    descEditing: false,
    pickerOpen: false,         // the folder-index picker under the Folder field
    editingLinkId: null,
    editingCommentId: null,    // the comment whose body sits in the inline editor
    syncShown: false,          // the issue sync's activity rows, unfolded
    linksEditing: false,       // the folder and link editors under the Links row
    commentsAll: false,        // every comment, not only the latest three
    render: function () { renderDrawer(ctx); },
    refresh: refresh,
    patch: patch,
    setStatus: function (status, o) { return setStatus(ctx, status, o); },
    toggleLinks: function () { toggleLinks(ctx); },
  };

  // The comment field moves between the list and the sheet's foot as the
  // window crosses the sheet breakpoint.
  window.matchMedia(SHEET_QUERY).addEventListener('change', function () { if (ctx.current) ctx.render(); });

  async function patch(changes) {
    if (!ctx.current) return;
    try {
      await api('/api/tasks/' + ctx.current.id, { method: 'PATCH', body: changes });
      await refresh();
      opts.onChanged();
    } catch (err) {
      toast(err.message || 'Update failed', 'error');
      await refresh();
    }
  }

  async function refresh() {
    // an open still in flight is about to render a fresh payload of its own
    if (ctx.current == null || opening != null) return;
    const id = ctx.current.id;
    const seq = ++loads;
    try {
      const loaded = await loadTask(id);
      if (seq === loads && ctx.current && ctx.current.id === id) { ctx.current = loaded.task; ctx.author = loaded.author; ctx.render(); }
    } catch (err) {
      toast(err.message || 'Could not load the task', 'error');
    }
  }

  return {
    async open(id) {
      if (opening === id) return;
      opening = id;
      const seq = ++loads;
      resetView(ctx);
      try {
        const loaded = await loadTask(id);
        if (seq !== loads) return;   // a newer open, or a close, took over meanwhile
        ctx.current = loaded.task; ctx.author = loaded.author;
        ctx.render();
        el.hidden = false;
        document.body.dataset.drawer = 'open';
        el.scrollTop = 0;
      } catch (err) {
        if (seq !== loads) return;
        toast(err.message || 'Task not found', 'error');
        opts.onClose();
      } finally {
        if (seq === loads) opening = null;
      }
    },
    close() {
      loads++;
      opening = null;
      ctx.current = null;
      el.hidden = true;
      el.innerHTML = '';
      delete document.body.dataset.drawer;
    },
    refresh: refresh,
    currentId() { return ctx.current ? ctx.current.id : null; },
    handleKey(key) { return handleKey(ctx, key); },
  };
}
