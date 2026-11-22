"""``js/poll.js`` — the one repeating read: single-flight, silent while hidden, one catch-up on return.

Loaded bare under node with a fake clock and a fake ``document``, so each case
counts reads exactly instead of timing them.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.node_js import call_js, requires_node

pytestmark = requires_node

MODULE = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "js" / "poll.js"

# A fake timer list and a fake document; every step answers the read count and
# the number of live interval timers so a case reads as the budget it spends.
_RUNNER = """
const timers = new Map();
let nextId = 1;
globalThis.window = {
  setInterval(fn) { const id = nextId++; timers.set(id, fn); return id; },
  clearInterval(id) { timers.delete(id); },
};
const listeners = [];
globalThis.document = {
  hidden: false,
  addEventListener(type, fn) { if (type === 'visibilitychange') listeners.push(fn); },
  removeEventListener(type, fn) { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); },
};
const flush = () => new Promise((r) => setImmediate(r));
const tick = async (n = 1) => { for (let i = 0; i < n; i++) { for (const fn of [...timers.values()]) fn(); await flush(); } };
const setHidden = async (h) => { document.hidden = h; for (const fn of [...listeners]) fn(); await flush(); };

const { createPoll } = await import(process.argv[1]);
const snap = (reads) => ({ reads, timers: timers.size, listeners: listeners.length });
const out = {};

// visible: one read per tick
{ let reads = 0; const p = createPoll(() => { reads++; }, 1000); p.start(); await tick(3);
  out.visible = snap(reads); p.stop(); out.stopped = snap(reads); }

// single-flight: a slow read swallows the ticks that arrive while it runs
{ let reads = 0; let release; const p = createPoll(() => { reads++; return new Promise((r) => { release = r; }); }, 1000);
  p.start(); await tick(4); out.inFlight = snap(reads);
  release(); await flush(); await tick(1); out.afterRelease = snap(reads); p.stop(); }

// hidden: no timer, no read; back: exactly one catch-up read, then the interval resumes
{ let reads = 0; const p = createPoll(() => { reads++; }, 1000); p.start(); await tick(1);
  await setHidden(true); await tick(10); out.hidden = snap(reads);
  await setHidden(false); out.catchUp = snap(reads);
  await tick(2); out.resumed = snap(reads); p.stop(); }

// started while hidden: nothing until the tab is shown
{ document.hidden = true; let reads = 0; const p = createPoll(() => { reads++; }, 1000);
  p.start(); await tick(5); out.startedHidden = snap(reads);
  await setHidden(false); out.shown = snap(reads); p.stop(); document.hidden = false; }

// a rejected read is the next tick's retry, not a dead poll
{ let reads = 0; const p = createPoll(() => { reads++; return Promise.reject(new Error('down')); }, 1000);
  p.start(); await tick(3); out.rejected = snap(reads); p.stop(); }

process.stdout.write(JSON.stringify([out]));
"""


def _run() -> dict:
    return call_js(MODULE, _RUNNER, [])[0]


def test_a_visible_poll_reads_once_per_tick_and_stop_releases_everything() -> None:
    got = _run()
    assert got["visible"] == {"reads": 3, "timers": 1, "listeners": 1}
    assert got["stopped"] == {"reads": 3, "timers": 0, "listeners": 0}


def test_a_slow_read_is_never_overlapped() -> None:
    got = _run()
    assert got["inFlight"]["reads"] == 1  # four ticks, one request
    assert got["afterRelease"]["reads"] == 2


def test_a_hidden_tab_makes_no_requests_apart_from_one_catch_up_read() -> None:
    got = _run()
    assert got["hidden"] == {"reads": 1, "timers": 0, "listeners": 1}  # ten hidden ticks: no timer to fire
    assert got["catchUp"]["reads"] == 2  # exactly one catch-up on return
    assert got["resumed"]["reads"] == 4  # …and the interval is back


def test_a_poll_started_in_a_hidden_tab_waits_to_be_shown() -> None:
    got = _run()
    assert got["startedHidden"] == {"reads": 0, "timers": 0, "listeners": 1}
    assert got["shown"]["reads"] == 1


def test_a_failed_read_does_not_stop_the_poll() -> None:
    assert _run()["rejected"]["reads"] == 3
