# `page-foot` — the build-identity footer

The fleet's canonical **page-foot**: a centered, quiet footer line — `Build: <sha> · YYYY-MM-DD HH:MM` — showing which build the PWA is running. This is the difference between "the tray restarted" and "the *new* build is live" (see project-scaffolding's `CLAUDE.md` "Build-identity footer" convention): a `/healthz` 200 passes on a stale process, a matching `git_sha` does not. Normalized from home-automation's shipped footer; whatsapp-radar#122's first feedback item was precisely a footer-format divergence from a private re-implementation of the same text — this component is that one shared function, written once.

## Files

| File | Role |
| --- | --- |
| `page-foot.css` | Visual contract — centered layout, muted/caption text. Self-contained (doesn't depend on external `.muted`/`.small` utility classes). References design tokens only. |
| `page-foot.js` | ESM — `fmtBuildTime(iso)` + `buildReadoutText(sha, builtAtIso)`, the one shared text formatter so the footer string can't drift between apps. |
| `page-foot.html` | Markup skeleton to copy and adapt. |

## How to vendor

1. Copy this `page-foot/` folder **verbatim** into your app's static dir (`app/webapp/static/_vendored/page-foot/`). Do **not** edit `page-foot.css` / `page-foot.js` per-app.
2. Link the CSS and paste the skeleton as the last child of `<main>`:
   ```html
   <link rel="stylesheet" href="/static/_vendored/page-foot/page-foot.css">
   ...
   <footer class="page-foot">
     <p id="buildReadout"></p>
   </footer>
   ```
3. Wire your own version fetch (still your app's job — the endpoint is auth-gated per project-scaffolding's `/api/version` convention):
   ```js
   import { buildReadoutText } from '/static/_vendored/page-foot/page-foot.js';

   async function fetchVersion() {
     try {
       const body = await jsonApi('/api/version');
       els.buildReadout.textContent = buildReadoutText(body.git_sha || 'unknown', body.built_at || '');
     } catch (_) {
       els.buildReadout.textContent = '';
     }
   }
   ```

## Markup contract

```html
<footer class="page-foot">
  <p id="buildReadout"></p>
</footer>
```

- Lives **outside every card**, as the last element of `<main>` — it's app-wide identity, not a section's content.
- The `<p>`'s text is set entirely by `buildReadoutText()`; no additional class is needed (the styling is self-contained in `page-foot.css`, not borrowed from generic `.muted`/`.small` utilities).
- Any reload-on-stale-asset logic (e.g. home-automation's asset-hash comparison that triggers one automatic reload after a deploy) is orthogonal to the footer text and stays app-specific — out of scope here.

## Required design tokens

| Token | Light value | Used for |
| --- | --- | --- |
| `--muted` | `#656d76` | readout text color |
| `--font-caption` | `0.78rem` | readout text size |
| `--space-md` | `16px` | outer vertical margin |
| `--space-xs` | `4px` | outer horizontal margin |

## Don't diverge

`page-foot.css` / `page-foot.js` are vendored verbatim — to change the contract (text format, styling), change it **here in `project-scaffolding`** and re-vendor downstream. In particular, don't re-implement `fmtBuildTime` per-app — that private-reimplementation drift is exactly what whatsapp-radar#122 caught and this component removes. If your own CSS declares the same selector this file touches (e.g. `.app`, `.card`), use longhand properties or a disjoint media condition — a shorthand property at equal specificity is decided by source order, and can silently override a rule you didn't intend to touch. Streamlit POC spikes are exempt.
