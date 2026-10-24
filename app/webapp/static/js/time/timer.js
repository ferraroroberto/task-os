/* task-os — the Time tab's timer writes: start (or switch), stop and save,
 * discard, and add time already spent. */

'use strict';

import { api } from '../../api.js';
import { askSwitch, openEntryEditor } from '../../time-dialogs.js';
import { fmtMinutes } from '../../time-format.js';
import { toast } from '../../toast.js';
import { nameOf, refreshLive, refreshRecent, timerOf } from './data.js';
import { renderGlance, renderStart, renderTimer } from './log.js';

export async function afterTimerChange(ctx) {
  await Promise.all([refreshLive(ctx), refreshRecent(ctx)]);
  renderGlance(ctx);
  renderTimer(ctx);
  renderStart(ctx);
}

export async function startTimer(ctx, c) {
  const st = ctx.st;
  if (st.busy) return;
  const running = timerOf(ctx, st.person);
  if (running && running.category_id === c.id) return;
  let doSwitch = false;
  if (running) {
    doSwitch = await askSwitch({ from: running.category_name, to: c.name });
    if (!doSwitch) return;
  }
  st.busy = true;
  try {
    const out = await api('/api/time/timers', {
      method: 'POST', body: { person: st.person, category_id: c.id, switch: doSwitch },
    });
    toast(out.entry ? 'Saved ' + fmtMinutes(out.entry.minutes) + ' of ' + out.entry.category_name
      + '; started ' + c.name : 'Started ' + c.name);
  } catch (err) {
    if (err.code === 'timer_running') {
      // Started on another device meanwhile: say why, then offer the switch.
      st.busy = false;
      await afterTimerChange(ctx);
      const other = timerOf(ctx, st.person);
      toast('A timer is already running for you' + (other ? ': ' + other.category_name : ''));
      if (other) return startTimer(ctx, c);
      return;
    }
    toast(err.message, 'error');
  } finally {
    st.busy = false;
  }
  await afterTimerChange(ctx);
}

export async function stopTimer(ctx) {
  const st = ctx.st;
  if (st.busy) return;
  const input = document.getElementById('timeLongMinutes');
  const body = {};
  if (input && Number(input.value) > 0) body.minutes = Math.round(Number(input.value));
  st.busy = true;
  try {
    const entry = await api('/api/time/timers/' + encodeURIComponent(st.person) + '/stop', { method: 'POST', body: body });
    toast('Saved ' + fmtMinutes(entry.minutes) + ' of ' + entry.category_name);
  } catch (err) {
    toast(err.code === 'no_timer' ? 'That timer was already stopped on another device' : err.message, 'error');
  } finally {
    st.busy = false;
  }
  await afterTimerChange(ctx);
}

export async function discardTimer(ctx) {
  const st = ctx.st;
  if (st.busy) return;
  st.busy = true;
  try {
    await api('/api/time/timers/' + encodeURIComponent(st.person), { method: 'DELETE' });
    toast('Timer discarded');
  } catch (err) {
    toast(err.code === 'no_timer' ? 'That timer was already stopped on another device' : err.message, 'error');
  } finally {
    st.busy = false;
  }
  await afterTimerChange(ctx);
}

export async function addEntry(ctx) {
  const st = ctx.st;
  const saved = await openEntryEditor({ meta: st.meta, person: st.person, today: st.today, now: st.now });
  if (!saved) return;
  toast('Saved ' + fmtMinutes(saved.minutes) + ' for ' + nameOf(ctx, saved.person));
  await afterTimerChange(ctx);
}
