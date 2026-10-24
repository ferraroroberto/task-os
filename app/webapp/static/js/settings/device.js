/* task-os — the controls that belong to this device: the palette's phone entry
 * and the text size. */

'use strict';

import { bindTextSize } from '../../_vendored/text-size/text-size.js';

/** The palette's phone entry (#316) — the card only hosts the button. */
export function wirePaletteOpen(ctx) {
  ctx.els.paletteOpen.addEventListener('click', function () { ctx.opts.onOpenPalette(); });
}

/** Text size (#314): inline in its row since #397 — the control is its own
 *  value; the vendored binding does the storing and stamping. */
export function wireTextSize(ctx) {
  bindTextSize(ctx.els.textSizeControl, 'task-os');
}
