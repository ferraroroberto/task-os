# `fullscreen` — the "Full screen on Edge" setting

A managed Android phone runs the fleet's web apps in the work profile's Edge, which cannot install them as apps (the self-signed certificate is not trusted there), so every app sits under Edge's address bar and toolbar. This is the shared escape: a **Settings row with a switch** that asks the Fullscreen API to hide them. The row appears **only in Edge**, is **off by default** and is **saved per device**.

## Files

| File | Role |
| --- | --- |
| `fullscreen.js` | `bindFullscreen(row, app, ua?)` wires the row and the re-entry tap and returns whether the row is shown; `isEdge(ua?)` and `readFullscreen(app)` are exported too. Imports `setSwitch` from the sibling `switch/`. |
| `fullscreen.css` | Keeps the row hidden when it is (a `.settings-row` sets its own `display`) and shows the "tap anywhere" sentence only while the setting is armed. |
| `fullscreen.html` | The row: a `settings-group` row with the `maximize` glyph, label, hint and a `switch`, plus the one-line binding. |

## How to vendor

1. Copy this `fullscreen/` folder **verbatim** into your app's static dir (`app/webapp/static/_vendored/fullscreen/`). Do **not** edit `fullscreen.css` or `fullscreen.js` per-app. It needs the vendored [`switch`](../switch/) (the JS imports `../switch/switch.js`, so keep the two folders as siblings), [`settings-group`](../settings-group/) for the row's look and [`icons`](../icons/) for the `maximize` glyph on the page.
2. Link the CSS (order doesn't matter):
   ```html
   <link rel="stylesheet" href="/static/_vendored/fullscreen/fullscreen.css">
   ```
3. Paste the row from `fullscreen.html` into a `settings-group` card in your Settings (next to the text-size control), and bind it with your localStorage prefix, the same one `text-size` uses:
   ```js
   import { bindFullscreen } from '/static/_vendored/fullscreen/fullscreen.js';
   bindFullscreen(document.getElementById('fullscreenRow'), 'app-launcher');
   ```
   Keep the row's `hidden` attribute, the `data-fullscreen-toggle` attribute on the switch and the `.fullscreen-armed` span; labels may be translated. The switch carries `data-track="settings.fullscreen"` like any other control.

## Contract

- **Edge only.** The row is shown when the user agent carries `Edg/` (desktop Edge) or `EdgA/` (Edge on Android) and the browser offers `document.fullscreenEnabled`. Any other browser keeps the row hidden and nothing changes. `EdgiOS/` is not matched: iOS offers no page full screen.
- **Key and value:** `localStorage['<app>.fullscreen']` is `1` when on; absent is off, including an unreadable store. It is per device, never synced.
- **Entering needs a gesture.** The switch's own tap enters. After a reload the page is out of full screen while the setting is still on, so the **first tap anywhere** (one capture-phase listener; the tap still reaches its target) enters again. A tap inside the row is the switch's own and never re-enters.
- **Leaving by hand does not turn it off.** The back gesture or Esc leaves full screen and `fullscreenchange` re-arms the row; the next tap re-enters. The **switch is the one way to turn it off** (it also exits full screen at once).
- **The armed hint.** While the setting is on and the page is not in full screen the row carries `data-armed="true"` and its hint adds "Tap anywhere to go full screen." (an `aria-live="polite"` region).

## Required design tokens

None of its own: the row borrows `settings-group`'s tokens and `switch`'s (`--control-border`, `--toggle-knob`, `--accent-fill`; see those READMEs), so light and dark follow the theme. The glyph is Lucide `maximize` from the vendored `icons` sprite.

## Don't diverge

`fullscreen.css` and `fullscreen.js` are vendored verbatim; the only per-app part is the `app` prefix. To change the behaviour, the detection or the row, change it **here in `project-scaffolding`** and re-vendor downstream. Don't write a per-app fullscreen switch. Streamlit POC spikes are exempt.
