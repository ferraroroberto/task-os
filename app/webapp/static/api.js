/* task-os — the one fetch wrapper for /api/*.
 *
 * Every call resolves to the parsed JSON body or throws an ApiError carrying
 * the server's one error envelope ({error: {code, message, detail?}}) so a
 * caller can show `err.message` in a toast without re-parsing anything.
 *
 * Auth (Step 7): requests ride the same-origin `taskos_token` cookie /login
 * set (loopback needs none). A 401 means this device is not signed in — the
 * page goes to /login?next=<here> and comes back on success; the pending
 * call still rejects so no caller renders a half state.
 */

'use strict';

export class ApiError extends Error {
  constructor(status, code, message, detail) {
    super(message || ('HTTP ' + status));
    this.name = 'ApiError';
    this.status = status;
    this.code = code || 'http_error';
    this.detail = detail;
  }
}

/**
 * @param {string} path      e.g. '/api/tasks?status=doing'
 * @param {{method?: string, body?: any}} [opts]
 * @returns {Promise<any>}
 */
export async function api(path, opts) {
  const o = opts || {};
  const init = { method: o.method || 'GET', headers: {}, cache: 'no-store', credentials: 'same-origin' };
  if (o.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(o.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (_) {
    throw new ApiError(0, 'unreachable', 'Server unreachable');
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch (_) { data = null; }
  }
  if (!res.ok) {
    const e = (data && data.error) || {};
    if (res.status === 401 && e.code === 'unauthorized') redirectToLogin();
    throw new ApiError(res.status, e.code, e.message || ('HTTP ' + res.status), e.detail);
  }
  return data;
}

let redirecting = false;
/** Send this device to /login once (many calls can 401 at the same time). */
export function redirectToLogin() {
  if (redirecting) return;
  redirecting = true;
  const here = location.pathname + location.search + location.hash;
  location.assign('/login?next=' + encodeURIComponent(here));
}

/** Build a query string from a plain object, skipping empty values. */
export function qs(params) {
  const p = new URLSearchParams();
  Object.keys(params || {}).forEach(function (k) {
    const v = params[k];
    if (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length)) return;
    p.set(k, Array.isArray(v) ? v.join(',') : String(v));
  });
  const s = p.toString();
  return s ? '?' + s : '';
}
