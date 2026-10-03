/* task-os — the task row's ⋯ menu (#311).
 *
 * Every action a row offers, behind one trailing kebab: the menu is the
 * vendored data-driven row-menu (project-scaffolding#317), and its items are
 * built here from two sources —
 *
 *   the ACTIONS table (actions.js)  complete / reopen, change date, snooze,
 *                                   the statuses, priority — the same entries
 *                                   the keys, the palette and the swipes read,
 *                                   committed through the same runner, so a
 *                                   menu tap gets the same toast and Undo
 *   the row's own links             plan for today, open folder, open the AI
 *                                   conversation (resume it in a CLI on a PC),
 *                                   open the issue, open details
 *
 * Each item shows only when it applies to the task (`applies()` on an action;
 * a link only when the task has one). Which actions the menu lists, and in
 * what order, comes from `order()` — the plan's default until Settings says
 * otherwise.
 *
 * One menu per rendered list (`createTaskMenu` per view): `attach()` while the
 * list is built, `endRender()` once it is, so an open menu follows its row
 * across a re-render or closes when the row has left.
 */

'use strict';

import { createRowMenu } from './_vendored/row-menu/row-menu.js';
import { actionById } from './actions.js';
import { aiResumeHref, followLink, issueUrl, openTaskFolder, providerIcon, todayISO } from './format.js';
import { openDatePicker } from './snooze.js';

/** The actions the menu lists, in order, until Settings changes it (#311 plan §2). */
export const MENU_DEFAULT = [
  'complete', 'reopen', 'change-date', 'snooze',
  'status-inbox', 'status-todo', 'status-standby', 'status-cancelled', 'priority',
];

const CLOSED = { done: 1, cancelled: 1 };

/**
 * @param {{actions: ReturnType<import('./actions.js').createActions>,
 *          onOpen: (id:number) => void,
 *          onPlan?: (id:number) => any, onUnplan?: (id:number) => any,
 *          order?: () => string[]}} ctx
 * @returns {{attach: (t:object, kebab:HTMLElement) => void, endRender: () => void, close: () => void}}
 */
export function createTaskMenu(ctx) {
  const ctl = createRowMenu({ className: 'task-menu' });

  /** After the write the list is rebuilt and the kebab the menu handed focus
   *  back to is gone: put focus on the same row's new kebab, if it stayed. */
  function refocus(t, kebab) {
    const pane = kebab.closest('.pane');
    return {
      afterRefresh: function () {
        if (!pane || pane.hidden) return;
        const next = pane.querySelector('.trow[data-id="' + t.id + '"] .trow-kebab');
        if (next) next.focus({ preventScroll: true });
      },
    };
  }

  function run(action, t, kebab) {
    if (action.menu) {
      openDatePicker(t, action.menu, kebab.closest('.trow') || kebab, function (phrase) {
        ctx.actions.run(action, [t], phrase, refocus(t, kebab));
      });
      return;
    }
    ctx.actions.run(action, [t], undefined, refocus(t, kebab));
  }

  function items(t, kebab) {
    const open = !CLOSED[t.status];
    const order = ctx.order ? ctx.order() : MENU_DEFAULT;
    const list = order.map(actionById).filter(Boolean).map(function (a) {
      return {
        label: a.label, glyph: a.icon, dataset: { action: a.id },
        hidden: function () { return !a.applies(t); },
        onTap: function () { run(a, t, kebab); },
      };
    });
    const planned = t.planned_on === todayISO();
    if (ctx.onPlan && open && !planned) {
      list.push({ label: 'Plan for today', glyph: 'list-checks', dataset: { action: 'plan' },
        onTap: function () { ctx.onPlan(t.id); } });
    }
    if (ctx.onUnplan && planned) {
      list.push({ label: 'Remove from plan', glyph: 'x', dataset: { action: 'unplan' },
        onTap: function () { ctx.onUnplan(t.id); } });
    }
    if (t.folder_ref) {
      list.push({ label: 'Open folder', glyph: 'folder', dataset: { action: 'folder' },
        onTap: function () { openTaskFolder(t, kebab); } });
    }
    if (t.ai_url) {
      list.push({ label: 'Open AI conversation', glyph: 'bot', dataset: { action: 'ai' },
        onTap: function () { window.open(t.ai_url, '_blank', 'noopener'); } });
      const resume = aiResumeHref(t.ai_url);
      // a phone has no CLI to resume into
      if (resume && !window.matchMedia('(pointer: coarse)').matches) {
        list.push({ label: 'Resume in CLI', glyph: 'terminal', dataset: { action: 'resume' },
          onTap: function () { followLink(resume); } });
      }
    }
    if (t.issue_ref) {
      const ref = t.issue_ref;
      list.push({
        label: 'Open issue ' + String(ref.repo || '').split('/').pop() + '#' + ref.number,
        glyph: providerIcon(ref.provider), dataset: { action: 'issue' },
        onTap: function () { window.open(ref.url || issueUrl(ref.provider, ref.repo, ref.number), '_blank', 'noopener'); },
      });
    }
    list.push({ label: 'Open details', glyph: 'file-text', dataset: { action: 'open' },
      onTap: function () { ctx.onOpen(t.id); } });
    return list;
  }

  return {
    attach: function (t, kebab) { ctl.attach(String(t.id), kebab, items(t, kebab)); },
    endRender: function () { ctl.endRender(); },
    close: function () { ctl.close(); },
  };
}
