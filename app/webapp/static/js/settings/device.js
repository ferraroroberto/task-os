/* task-os — the controls that belong to this device: the palette's phone entry,
 * the text size and full screen on Edge. */

'use strict';

import { bindFullscreen } from '../../_vendored/fullscreen/fullscreen.js';
import { bindTextSize } from '../../_vendored/text-size/text-size.js';

/** The palette's phone entry — the card only hosts the button. */
export function wirePaletteOpen(ctx) {
  ctx.els.paletteOpen.addEventListener('click', function () { ctx.opts.onOpenPalette(); });
}

/** Text size: inline in its row — the control is its own
 *  value; the vendored binding does the storing and stamping. */
export function wireTextSize(ctx) {
  bindTextSize(ctx.els.textSizeControl, 'task-os');
}

/** Full screen on Edge: the vendored binding shows the row in Edge only and
 *  keeps the choice per device under task-os.fullscreen. */
export function wireFullscreen(ctx) {
  bindFullscreen(ctx.els.fullscreenRow, 'task-os');
}
