/* task-os — Settings → Available features: one row per coarse feature block
 * (src/features.py), each with the vendored switch. A switch applies on the
 * spot: the server saves it to this machine's config and starts or stops the
 * block's background work, and the page hides or restores the block's UI with
 * no reload. A block whose dependency is missing here says so on its row.
 *
 * The group is built here because index.html is at its size limit; the rows of
 * the blocks that are off are hidden from the other Settings groups by tagging
 * them `data-feature` (the same attribute that hides the tab). */

'use strict';

import { setSwitch, switchEl } from '../../_vendored/switch/switch.js';
import { api } from '../../api.js';
import { toast } from '../../toast.js';
import { featureOn, setFeaturesOff } from '../features.js';

//: The Settings rows each block owns, by their `data-settings-sheet` key.
const SHEET_OWNER = {
  issues: 'issues', calendar: 'calendar', capture: 'email', archive: 'email',
  voice: 'ai', ai: 'ai', mirror: 'mirror', timecats: 'time',
};

/** Tag every Settings row whose block can be switched off, so CSS hides it with the block. */
function tagOwnedRows(pane) {
  Object.keys(SHEET_OWNER).forEach(function (sheet) {
    const row = pane.querySelector('[data-settings-sheet="' + sheet + '"]');
    if (row) row.dataset.feature = SHEET_OWNER[sheet];
  });
}

/** Hide a group, and its label above it, while every one of its rows belongs to a block that
 *  is off; `data-empty` is what the CSS keys on, so a switch coming back restores both. */
function syncEmptyGroups(pane) {
  pane.querySelectorAll('.settings-group').forEach(function (group) {
    const rows = Array.from(group.querySelectorAll('.settings-row'));
    const empty = rows.length > 0 && rows.every(function (row) {
      return row.dataset.feature && !featureOn(row.dataset.feature);
    });
    const label = group.previousElementSibling;
    [group, label && label.classList.contains('settings-group-label') ? label : null].forEach(function (el) {
      if (!el) return;
      if (empty) el.dataset.empty = '';
      else delete el.dataset.empty;
    });
  });
}

/** One block's row (the settings-group switch row): its name, one hint line
 *  under it, the switch trailing; a tap anywhere on the row toggles it. */
function rowEl(f, onToggle) {
  const row = document.createElement('label');
  row.className = 'settings-row settings-feature';
  row.dataset.featureKey = f.key;
  const text = document.createElement('span');
  text.className = 'settings-row-text';
  const title = document.createElement('span');
  title.className = 'settings-row-label';
  title.textContent = f.label;
  // One hint line: what the block covers, then its state when that is not the plain "on".
  const meta = document.createElement('span');
  meta.className = 'settings-row-hint';
  const summary = document.createElement('span');
  summary.className = 'settings-feature-summary';
  summary.textContent = f.summary;
  meta.append(summary);
  const state = document.createElement('span');
  state.className = 'settings-feature-state';
  meta.append(state);
  text.append(title, meta);
  const sw = switchEl(f.enabled, { label: f.label, onToggle: onToggle });
  // dynamic-id-exempt: the id is the block key, a fixed set of six
  sw.dataset.track = 'settings.feature-' + f.key;
  row.append(text, sw);
  return row;
}

/** The state on a row's one meta line: off closes it after the summary; on but unavailable
 *  here replaces the summary with the reason, the part to act on (the summary stays in the
 *  tooltip); a block that is simply on says nothing more, the switch already shows it. */
function paintState(row, f) {
  const state = row.querySelector('.settings-feature-state');
  const meta = state.parentElement;
  meta.title = '';
  delete row.dataset.state;
  if (!f.enabled) {
    state.textContent = 'Off on this machine';
    delete state.dataset.tone;
  } else if (!f.available) {
    state.textContent = 'On, unavailable here: ' + f.reason;
    state.dataset.tone = 'attention';
    row.dataset.state = 'unavailable';
    meta.title = f.summary + ' ' + state.textContent;
  } else {
    state.textContent = '';
    delete state.dataset.tone;
  }
  setSwitch(row.querySelector('.toggle'), f.enabled);
}

/** Build the group before "This install", tag the owned rows, load the state.
 *  Returns `{refresh}` for the bootstrap to call when Settings opens. */
export function mountFeatures(ctx) {
  const anchor = document.getElementById('settingsGroupInstall');
  const heading = document.createElement('h3');
  heading.className = 'settings-group-label';
  heading.id = 'settingsGroupFeatures';
  heading.textContent = 'Available features';
  const list = document.createElement('section');
  list.className = 'card settings-group';
  list.setAttribute('aria-labelledby', heading.id);
  const note = document.createElement('p');
  note.className = 'settings-footnote settings-features-note';
  note.setAttribute('role', 'status');
  anchor.before(heading, list, note);
  tagOwnedRows(ctx.els.pane);
  syncEmptyGroups(ctx.els.pane);

  let busy = false;
  let current = [];

  function paint(features) {
    current = features;
    list.replaceChildren();
    features.forEach(function (f) {
      const row = rowEl(f, function (next) { toggle(f, next); });
      list.appendChild(row);
      paintState(row, f);
    });
    setFeaturesOff(features.filter(function (f) { return !f.enabled; }).map(function (f) { return f.key; }));
    syncEmptyGroups(ctx.els.pane);
  }

  async function toggle(f, next) {
    if (busy) return;
    busy = true;
    note.textContent = '';
    try {
      const res = await api('/api/features/' + f.key, { method: 'PUT', body: { enabled: next } });
      paint(res.features);
      // The rows were redrawn: keep the keyboard where it was.
      const again = list.querySelector('[data-feature-key="' + f.key + '"] .toggle');
      if (again) again.focus({ preventScroll: true });
      note.textContent = f.label + (next ? ' is on.' : ' is off: its screens are hidden and its background work has stopped.');
      ctx.opts.onFeatures(f.key, next);
    } catch (err) {
      note.textContent = err.message || 'Could not save the switch';
      toast(err.message || 'Could not save the switch', 'error');
    }
    busy = false;
  }

  async function refresh() {
    try {
      paint((await api('/api/features')).features);
    } catch (err) {
      list.replaceChildren();
      note.textContent = 'Features unknown — ' + (err.message || 'unreachable');
    }
  }

  refresh();
  return { refresh: refresh, current: function () { return current; } };
}
