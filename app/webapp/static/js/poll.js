/* task-os — the one repeating read: single-flight, silent while the tab is hidden,
 * one catch-up read when it comes back. */

'use strict';

/**
 * `read` returns a promise (or a value) and is called every `everyMs` while the
 * poll is started and the tab is visible. A tick that arrives while the previous
 * read is still in flight is dropped, so a slow server never gets a queue of
 * requests. A hidden tab arms no timer at all; coming back runs one read at
 * once, then the interval resumes. A rejected read is swallowed: the next tick
 * is the retry.
 */
export function createPoll(read, everyMs) {
  let timer = 0;
  let started = false;
  let inFlight = false;

  function fire() {
    if (inFlight || document.hidden) return;
    inFlight = true;
    Promise.resolve().then(read).catch(function () {}).finally(function () { inFlight = false; });
  }

  function disarm() {
    if (timer) window.clearInterval(timer);
    timer = 0;
  }

  function onVisibility() {
    if (!started) return;
    disarm();
    if (document.hidden) return;
    fire();
    timer = window.setInterval(fire, everyMs);
  }

  return {
    start: function () {
      if (started) return;
      started = true;
      document.addEventListener('visibilitychange', onVisibility);
      if (!document.hidden) timer = window.setInterval(fire, everyMs);
    },
    stop: function () {
      started = false;
      disarm();
      document.removeEventListener('visibilitychange', onVisibility);
    },
  };
}
