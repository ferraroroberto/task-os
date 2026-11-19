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
import { SHEET_QUERY, renderDrawer } from './js/drawer/render.js';

/** The task payload and who is looking. The author is read on every open and
 *  every refresh, not once at start, because Settings' "Your name" changes it
 *  live under a drawer that stays open; a failed read is an unknown author,
 *  never a failed load. */
async function loadTask(id) {
  const [task, me] = await Promise.all([api('/api/tasks/' + id), api('/api/me').catch(function () { return null; })]);
  return { task: task, author: me && me.author ? me.author : null };
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
  // Every load of the payload takes a number, and only the newest may render.
  // One hash navigation fires `popstate` *and* `hashchange`, so
  // `open()` used to run twice for one click and fetch twice: the slower
  // answer, read before an edit, then painted over the edit's own refresh and
  // the drawer showed the old value of a field the server had already
  // changed. `opening` is the id an open is still fetching, so the second
  // arrival of the same navigation is dropped outright.
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
    setStatus: setStatus,
    toggleLinks: toggleLinks,
  };

  /** A status segment (or its key). Done is the end of the owner's flow on a
   *  task, so it closes the drawer; the action runner's toast offers Undo. A
   *  recurring task's Done is the roll to its next date (`complete`), unless
   *  `endSeries` closes it for good (the ⋯ menu). Every other status stays on
   *  the open task.
   *  @param {string} status
   *  @param {{endSeries?: boolean}} [o] */
  async function setStatus(status, o) {
    const t = ctx.current;
    if (!t || t.status === status) return;
    const value = status === 'done' && t.recurrence && !(o && o.endSeries) ? 'complete' : status;
    try {
      await opts.onStatus(t.id, value);
    } catch (_) {
      return;   // the write already said why
    }
    if (status === 'done' && ctx.current && ctx.current.id === t.id) opts.onClose();
  }

  function toggleLinks() {
    if (!ctx.current) return;
    ctx.linksEditing = !ctx.linksEditing;
    ctx.render();
    if (ctx.linksEditing) {
      const editor = el.querySelector('.drawer-links-editor');
      if (editor) editor.scrollIntoView({ block: 'nearest' });
      const first = el.querySelector('.drawer-links-editor input');
      if (first) first.focus();
    }
  }

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
      ctx.descEditing = false;
      ctx.pickerOpen = false;
      ctx.editingLinkId = null;
      ctx.editingCommentId = null;
      ctx.syncShown = false;
      ctx.linksEditing = false;
      ctx.commentsAll = false;
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
    /**
     * The drawer's own keys while a task is open: X done, C the comment field,
     * L the folder and link editors, D the calendar. The row keys that write
     * (1-3, T, W, P) go through keys.js's action runner instead, for the Undo.
     * @param {string} key  lower-cased
     * @returns {boolean} whether the key was the drawer's
     */
    handleKey(key) {
      if (!ctx.current) return false;
      if (key === 'x') { setStatus('done'); return true; }
      if (key === 'l') { toggleLinks(); return true; }
      if (key === 'c') {
        const field = el.querySelector('.comment-input');
        if (field) { field.focus(); field.scrollIntoView({ block: 'nearest' }); }
        return true;
      }
      if (key === 'd') {
        const pick = el.querySelector('.drawer-due .snooze-pick');
        if (pick) pick.click();
        return true;
      }
      return false;
    },
  };
}
