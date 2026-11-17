/* task-os — the view toggles of the Filters & sort sheet.
 *
 * Today and Board each have more than one way to narrow or lay out their list,
 * so the pane shows only the filter field and the add button and every other
 * toggle is a row of the one sheet the filter button opens:
 *
 *   Layout      Week · Status                (Board; remembered per device)
 *   AI triage   the Inbox action             (Board, Status layout, Inbox not empty)
 *   Kind        Tasks · Issues · All         (`scope`, scope.js)
 *   Whose       Mine · people · Everyone     (`whose` + `owners`, owners.js; two
 *                                             or more members)
 *
 * The state is the shared filter's (filters.js) except the Board layout, which
 * board.js keeps. This file builds the rows, applies a tap through the app's one
 * filter path and reports how many toggles are off their default, for the
 * button's badge: the kind of task and whose tasks narrow the list, so they
 * count and Clear resets them; the layout only arranges it, so it does neither.
 * `createViewRows(app)` is built once by app.js, which hands each tab's `views`
 * to `mountFilters`.
 */

'use strict';

import {
  RECENT_OWNERS_KEY, WHOSE_KEY, activeViewCount, bumpRecentOwner, describeViews, pickOwner, sheetRow, toggleOwner,
} from '../../filters.js';
import { mountScope } from '../../scope.js';
import { mountOwners, openOwnerSheet } from './owners.js';

/** A row whose control is a segmented group: the label above it. */
function stackedRow(name, label, control) {
  const row = sheetRow(name, label, control);
  row.classList.add('is-stacked');
  return row;
}

/**
 * What the person row does with a tap, over the app's one filter path.
 * @param {object} app  the composer's `app`
 * @returns {{onPick: Function, onEveryone: Function, openMore: Function, adopt: Function}}
 *   `adopt(row)` hands over the person row the open sheet drew (`openMore` lists its members)
 */
function createOwnerActions(app) {
  const state = app.state;
  let ownerRow = null;

  /** The person row moved: the pick narrows the server's list, so the lists and
   *  the journal are read again under it. Search never follows. Mine and Everyone
   *  are also kept per device (`WHOSE_KEY`); a picked person goes to the front of
   *  the row's recents. */
  function applyOwners(next, picked) {
    try {
      if (!next.owners.length) localStorage.setItem(WHOSE_KEY, next.whose);
      if (picked) {
        state.recentOwners = bumpRecentOwner(state.recentOwners, picked);
        localStorage.setItem(RECENT_OWNERS_KEY, JSON.stringify(state.recentOwners));
      }
    } catch (_) { /* private mode: this page only */ }
    app.onFilterChange(Object.assign({}, state.filters, next));
  }

  /** A tap on a person segment: that person alone. */
  function onOwnerPick(id) {
    applyOwners(pickOwner(id, state.viewer), id === state.viewer ? null : id);
  }

  /** A tick in the "+N more" sheet: toggle them in the set. */
  function onOwnerToggle(id) {
    const next = toggleOwner(state.filters, id, state.viewer);
    const added = next.owners.indexOf(id) >= 0 && state.filters.owners.indexOf(id) < 0;
    applyOwners(next, added ? id : null);
  }

  function onEveryone() {
    if (state.filters.whose === 'everyone' && !state.filters.owners.length) return;
    applyOwners({ owners: [], whose: 'everyone' }, null);
  }

  function openMoreOwners() {
    openOwnerSheet({
      people: ownerRow ? ownerRow.ordered() : [],
      picked: function () { return state.filters.owners; },
      onToggle: onOwnerToggle,
    });
  }

  return { onPick: onOwnerPick, onEveryone: onEveryone, openMore: openMoreOwners, adopt: function (row) { ownerRow = row; } };
}

/**
 * @param {object} app  the composer's `app`: `state`, `board`, `search`, and the
 *   render calls the scope and person rows make back (`syncUrl`, `renderFilters`,
 *   `renderBoardPane`, `renderTodayPane`, `onFilterChange`)
 * @returns {{today: object, board: object, renderSearchScope: () => void}}
 *   the two tabs' `views` (see `mountFilters`) and the Search box's own scope switch
 */
export function createViewRows(app) {
  const state = app.state;
  let searchScope = null;   // the Search pane's switch, mounted once
  const owners = createOwnerActions(app);

  /** The scope moved: it is applied in the browser, so the list the server sent
   *  stays; only the URL key and the views that read it change. */
  function onScopeChange(scope) {
    state.filters = Object.assign({}, state.filters, { scope: scope });
    app.syncUrl();
    app.renderFilters();
    app.renderBoardPane();
    app.renderTodayPane();
    renderSearchScope();
    if (app.search) app.search.refilter();
  }

  function renderSearchScope() {
    const host = app.els.searchScope;
    if (!host) return;
    if (!searchScope) searchScope = mountScope(host, onScopeChange);
    searchScope.render(state.filters.scope);
    host.hidden = false;
  }

  function ownerContext() {
    return { members: state.members, viewer: state.viewer, recent: state.recentOwners };
  }

  /** One tab's `views` for `mountFilters`. */
  function forTab(tab) {
    let scope = null;     // the open sheet's rows, null while it is closed
    let people = null;
    const board = tab === 'board';
    let triageWired = false;

    function draw(body) {
      if (board && app.board) {
        if (!triageWired) {
          // Triage starts a run rather than setting a filter: the sheet steps aside for the board
          app.board.triage.addEventListener('click', function () {
            const dialog = document.getElementById('filterSheet');
            if (dialog && dialog.open) dialog.close();
          });
          triageWired = true;
        }
        body.appendChild(stackedRow('layout', 'Layout', app.board.modes));
        // hidden with the button itself (board.js paints it); the row follows in CSS
        body.appendChild(sheetRow('triage', 'AI triage', app.board.triage));
      }
      const scopeHost = document.createElement('div');
      scope = mountScope(scopeHost, onScopeChange);
      scope.render(state.filters.scope);
      body.appendChild(stackedRow('kind', 'Kind of task', scopeHost));
      people = null;
      if (state.members.length >= 2) {
        const peopleHost = document.createElement('div');
        people = mountOwners(peopleHost, { onPick: owners.onPick, onEveryone: owners.onEveryone, onOpenMore: owners.openMore });
        owners.adopt(people);
        people.render(state.filters, ownerContext());
        body.appendChild(stackedRow('whose', 'Whose tasks', peopleHost));
      }
    }

    return {
      // The layout is a display choice like the theme: it hides nothing, so it is
      // neither counted on the button nor reset by Clear.
      count: function (f) { return activeViewCount(f, state.members.length); },
      words: function (f) { return describeViews(f, state.members); },
      live: function () {
        const f = state.filters;
        return { scope: f.scope, whose: f.whose, owners: f.owners };
      },
      draw: draw,
      sync: function (f) {
        if (scope) scope.render(f.scope);
        if (people) people.render(f, ownerContext());
      },
      clear: function () {
        try { localStorage.setItem(WHOSE_KEY, 'mine'); } catch (_) { /* private mode */ }
      },
    };
  }

  return { today: forTab('today'), board: forTab('board'), renderSearchScope: renderSearchScope };
}
