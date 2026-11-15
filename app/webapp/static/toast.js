/* task-os — toasts for user-initiated command results and errors.
 *
 * The fleet's vendored toast (_vendored/toast) draws them: one at a time,
 * pinned above the nav, neutral unless it reports an error. This module keeps
 * the app's call shape, `toast(message, kind, action)`, for its callers.
 * Never used for passive/background status (design.md "Async data &
 * feedback") — that renders inline.
 */

'use strict';

import { showToast } from './_vendored/toast/toast.js';

// A toast carrying an action stays up long enough to notice an Undo, reach it
// and use it. Exported because the keyboard undo buffer expires with its
// toast: one window, not a second timer that could outlive the offer on screen.
export const ACTION_TTL_MS = 10000;

/**
 * @param {string} message
 * @param {'info'|'success'|'error'} [kind='info']  only 'error' tints.
 * @param {{label: string, onClick: () => any}} [action]
 *        one optional inline action — the undo a reversible command offers
 *        (snoozing a task). It runs and dismisses the toast; the caller owns
 *        what "undo" means. Never the only way to reach an outcome: the toast
 *        expires.
 */
export function toast(message, kind, action) {
  showToast(message, kind, action && action.label ? { action: action, ms: ACTION_TTL_MS } : undefined);
}
