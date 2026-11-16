# `color-scheme` — native UI follows the chosen theme

The fleet's one source for the page's `color-scheme`. Three rules: `:root` is `light dark` (the fallback before `data-theme` is stamped), `:root[data-theme="light"]` is `light` and `:root[data-theme="dark"]` is `dark`.

Why it exists: native UI (a `<select>`'s option list, date and time pickers, scrollbars, form-control chrome) is drawn from `color-scheme`, not from the app's tokens. An app that declares `:root { color-scheme: light dark }` follows the OS, so a dark app theme on a light OS opens light native popups, and the reverse. The same miss was found and hand-fixed in three apps that did not carry [`base/`](../base/); this folder lets an app take the rules without taking the rest of `base`.

## Files

| File | Role |
| --- | --- |
| `color-scheme.css` | The three rules. No markup, no tokens. |

## Which one an app links

- **The app vendors [`base/`](../base/)** → nothing to add. `base.css` carries these three rules byte for byte; `tests/vendored/test_color_scheme_source.py` fails the scaffold's gate if the two ever differ.
- **The app does not vendor `base`** → vendor this folder. Copy `color-scheme/` **verbatim** into `app/webapp/static/_vendored/color-scheme/` and link it in `<head>`:
  ```html
  <link rel="stylesheet" href="/static/_vendored/color-scheme/color-scheme.css">
  ```
  Record it as `color-scheme` in the app's `.fleet.toml` `[vendored]` table so `/propagate-vendored` reaches it.

Load order does not matter: the `:root[data-theme]` selectors (specificity 0,2,0) beat an app's own bare `:root { color-scheme }` wherever it sits, so an app needs no edit to its own stylesheet. Don't restate the rules there either: a hand-copy drifts, and it is what `design_lint`'s `color-scheme-theme` contract exists to replace.

## Contract

- The page's `color-scheme` is the stamped `data-theme` on `<html>`, `light` or `dark`; native popups and scrollbars take that palette whatever the OS setting.
- With no `data-theme`, it stays `light dark` and follows the OS.
- **Stamp `data-theme` before first paint.** Until the stamp lands the page is on the fallback, so an app that sets `data-theme` from a deferred script or after a fetch draws its first frames' scrollbars and form chrome in the OS scheme, then switches. Native popups only open on a tap, so they are never wrong; the brief scrollbar mismatch is the only symptom. The inline `<head>` boot script in [`text-size/`](../text-size/) stamps it pre-paint, as `design.md` requires.
- Proven by `tests/e2e/test_vendored_base.py` against both `color-scheme.css` and `base.css`, on WebKit and Chromium: OS dark with app light, OS light with app dark, and the unstamped fallback both ways. The proof reads the `Canvas` system colour, the palette the engine hands native UI.

## Required design tokens

None.

## Static sites

A public site under `design.web.md` gets the same three selectors from `app/site/static/_vendored/site-theme/site-theme.css`, which also drives the site's sun/moon switch. Don't link this file there.

## Don't diverge

`color-scheme.css` is vendored verbatim. To change it, change it **here in `project-scaffolding`**, change `base.css` to match in the same PR, and re-vendor downstream. Streamlit POC spikes are exempt.
