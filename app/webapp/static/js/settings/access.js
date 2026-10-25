/* task-os — the Phone access sheet: https + auth (Step 7), who this browser
 * is, and "Sign out on this device". */

'use strict';

import { api } from '../../api.js';
import { toast } from '../../toast.js';

function accessRow(label, ok, text) {
  const dt = document.createElement('dt');
  dt.textContent = label;
  const dd = document.createElement('dd');
  dd.className = ok === null ? '' : (ok ? 'ok' : 'warn');
  dd.textContent = text;
  return [dt, dd];
}

// Team mode (Step 12): a row only when it is on — who this browser writes
// as, and the way back to the pick-your-name step. `team` is GET /api/team's
// body, or an Error when that call failed (its own "unknown" state).
function teamRow(team) {
  if (team instanceof Error) return accessRow('Team', false, 'unknown — ' + team.message);
  if (!team || !team.enabled) return [];
  const [dt, dd] = accessRow('Team', null, team.you ? 'you are ' + team.you + ' · ' : 'on — no name picked on this browser · ');
  const change = document.createElement('a');
  change.href = '/login?step=name&next=' + encodeURIComponent('/#settings/access');
  change.textContent = team.you ? 'change name' : 'pick one';
  dd.appendChild(change);
  return [dt, dd];
}

// Who this browser is: a row only once the install has two or more
// members. `me` is GET /api/me's body, or an Error when that call failed.
function meRow(me) {
  if (me instanceof Error) return accessRow('Signed in as', false, 'unknown — ' + me.message);
  if (!me || !me.name || !me.people || me.people.length < 2) return [];
  return accessRow('Signed in as', null, me.name);
}

export function renderAccessCard(ctx, st, team, me) {
  const client = { loopback: 'this PC', token: 'signed in', team: 'team member', public: 'public', denied: 'denied' }[st.auth.client] || st.auth.client;
  ctx.els.accessClient.textContent = client;
  ctx.els.accessRows.replaceChildren(
    ...meRow(me),
    ...accessRow('HTTPS', st.https, st.https ? 'on — Tailscale certificate' : 'off — plain HTTP (run scripts/gen_tailscale_cert.py)'),
    ...accessRow('Access token', st.auth.enabled, st.auth.enabled ? 'configured — other devices sign in at /login' : 'not set — only this PC can use the app (scripts/gen_token.py)'),
    ...accessRow('Password', null, st.auth.password ? 'set — accepted at /login' : 'not set (optional; scripts/set_password.py)'),
    ...teamRow(team),
  );
  ctx.els.signOutBtn.hidden = st.auth.client !== 'token' && st.auth.client !== 'team';
}

export function renderAccessUnknown(ctx, message) {
  ctx.els.accessRows.replaceChildren(...accessRow('Status', false, 'unknown — ' + message));
}

export function wireSignOut(ctx) {
  ctx.els.signOutBtn.addEventListener('click', async function () {
    try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { toast(err.message, 'error'); return; }
    location.assign('/login');
  });
}
