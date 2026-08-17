/* task-os — shell bootstrap (Step 1: nav, theme, empty states, build footer).
 *
 * ES module; imports the vendored components by their static paths so the
 * server's fleet-hash stamping rewrites them (`?v=<hash>`) at serve time.
 */

'use strict';

import { initNavTabs } from './_vendored/nav/nav-tabs.js';
import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { buildReadoutText } from './_vendored/page-foot/page-foot.js';

const THEME_KEY = 'task-os.theme';
const TAB_KEY = 'task-os.tab';

const els = {
  themeToggle: document.getElementById('themeToggle'),
  buildReadout: document.getElementById('buildReadout'),
  homeHeadStatus: document.getElementById('homeHeadStatus'),
  settingsSite: document.getElementById('settingsSite'),
};

// ------------------------------------------------------------------ theme
// index.html's pre-paint script already stamped html[data-theme]; the toggle
// flips it and persists the same key. The sun/moon swap is pure CSS keyed on
// the attribute (styles.css), so nothing re-renders here.
function wireTheme() {
  els.themeToggle.addEventListener('click', function () {
    const dark = document.documentElement.dataset.theme !== 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    try { localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light'); } catch (_) { /* private mode */ }
  });
}

// ------------------------------------------------------------ empty states
// Every task pane starts empty (the schema arrives in Step 2, the first
// task in Step 4). The vendored builder is the canonical zero-items block.
function renderEmptyStates() {
  document.querySelectorAll('.pane-body[data-empty="tasks"]').forEach(function (body) {
    const card = document.createElement('div');
    card.className = 'card empty-card';
    card.appendChild(emptyStateEl('list-checks', 'Add your first task'));
    body.replaceChildren(card);
  });
}

// ---------------------------------------------------------- build identity
async function fetchVersion() {
  try {
    const res = await fetch('/api/version', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const body = await res.json();
    els.buildReadout.textContent = buildReadoutText(body.git_sha || 'unknown', body.built_at || '');
    els.homeHeadStatus.textContent = 'No tasks yet';
    if (els.settingsSite && body.schema_version != null) {
      els.settingsSite.textContent = 'schema v' + body.schema_version;
    }
  } catch (err) {
    // An unreachable version endpoint is its own visible state, never blank.
    els.buildReadout.textContent = 'Build: unknown';
    els.homeHeadStatus.textContent = 'Server unreachable';
  }
}

// ---------------------------------------------------------------- boot
initNavTabs({ storageKey: TAB_KEY });
wireTheme();
renderEmptyStates();
fetchVersion();
