/* task-os — the "one action in flight" flag the Time and Email-archiving
 * sheets keep on their state. This module is the only writer: a screen asks
 * `st.busy` before it starts and calls these around the request, so a second
 * click is ignored until the first has finished (or failed). */

'use strict';

export function holdBusy(st) {
  st.busy = true;
}

export function releaseBusy(st) {
  st.busy = false;
}
