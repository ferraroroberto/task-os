/* task-os — the task drawer.
 *
 * A right-hand side panel on desktop (>= 1024px; the content shrinks so the
 * list stays visible), a full-screen sheet on the phone. Deep-linkable as
 * #task/<id> (app.js owns the hash).
 *
 * Ordered by how often each part is used (#394, decision 7 on #390): most
 * edits are a due date pushed out, so Due comes first with its quick moves.
 * Top to bottom: breadcrumb → its parent tools (Change parent, and Remove
 * parent when there is one, #468) → editable title → Due (the field, then the date
 * sheet's phrases as one-tap moves, push-outs first, each with its date) →
 * status and priority (and owner, with two or more members — #476) → links as pills (the folder, the linked issue, every
 * link: open-only, the editors are under More fields) → description
 * (markdown, edit/preview) → comments newest-first with URLs as clickable
 * chips + composer (Ctrl+Enter sends, origin=ui) — each row carries a pencil
 * (edit the body in place; the author, time and origin stay) and a trash
 * (asks first) → activity log (field old → new · actor · time; the issue
 * sync's rows fold behind one toggle) → **More fields**, closed until opened
 * and then kept open for the page's life: starts, recurrence + its every-N
 * interval + its fixed-day anchor when the cadence takes one, person, code,
 * folder (the ref as an opener chip, an editor that folds a pasted absolute path onto the
 * placeholders, a picker over the folder index — Step 9) → link editor
 * (label edit, remove, add) → blocked by (#100) → children (click to
 * navigate, add child) → issue panel: the linked issue (provider glyph,
 * repo#N link, state, labels from the last sync, last synced, unlink) or —
 * for a plain task — "Create issue…" and "Link existing" → delete.
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
import { renderDrawer } from './js/drawer/render.js';

/**
 * @param {HTMLElement} el     the <aside id="taskDrawer">
 * @param {{onChanged: () => void, onOpen: (id:number) => void, onClose: () => void,
 *          people: () => Array<{id:number,name:string}>,
 *          members: () => Array<{id:string,name:string}>,
 *          parentTargets: (id:number) => Array<{id:number,title:string,depth:number,path:string}>,
 *          allTasks: () => Array<{id:number,title:string,depth?:number}>,
 *          onMove: (id:number, parentId:number|null) => Promise<any>,
 *          onStatus: (id:number, status:string) => Promise<any>,
 *          issues: () => ({enabled:boolean, reason?:string, provider?:string, repos?:string[]}|null),
 *          onSyncIssues: () => Promise<any>}} opts
 */
export function createDrawer(el, opts) {
  // Every load of the payload takes a number, and only the newest may render
  // (#236). One hash navigation fires `popstate` *and* `hashchange`, so
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
    descEditing: false,
    pickerOpen: false,         // the folder-index picker under the Folder field
    editingLinkId: null,
    editingCommentId: null,    // the comment whose body sits in the inline editor (#155)
    syncShown: false,          // the issue sync's activity rows, unfolded (#394)
    render: function () { renderDrawer(ctx); },
    refresh: refresh,
    patch: patch,
  };

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
      const data = await api('/api/tasks/' + id);
      if (seq === loads && ctx.current && ctx.current.id === id) { ctx.current = data; ctx.render(); }
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
      try {
        const data = await api('/api/tasks/' + id);
        if (seq !== loads) return;   // a newer open, or a close, took over meanwhile
        ctx.current = data;
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
  };
}
