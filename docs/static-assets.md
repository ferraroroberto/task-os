# Static assets and the cold load

The PWA is plain files under `app/webapp/static/`, served by `CachingStaticFiles` (`app/webapp/server.py`) with the build's fleet hash stamped on every `.js` / `.css` URL (`src/static_versioning.py`): one SHA-256 over every asset, so an edit to any file rotates every stamp and the year-long `immutable` cache can never serve a stale module graph.

## One stylesheet request

`index.html` keeps one `<link rel="stylesheet">` per sheet in the source, in cascade order, because each sheet is its own file (the vendored components stay byte-for-byte and `static/styles/` stays split by concern). The served page does not ask for them one by one: `BuildInfo.stamp_html` replaces the run with a single link to `/static/bundle.css?v=<fleet hash>`, where the first link stood, and `CachingStaticFiles.get_response` answers that path with the sheets concatenated in link order, each under a `/* path */` header.

The reason is the phone's cold load, not bytes. A relaunch is served from the HTTP cache either way, but a first launch over a 4G-class link fetches around 160 files through the browser's six connections to the host; thirty of them were stylesheets that also block first paint. One request for the sheets cut the measured cold ready time by about 14% and first contentful paint by more than half, with the same cascade.

Rules that keep it honest:

- The bundle is built once at startup from the links in `index.html`, so adding a sheet is still one `<link>` line there.
- A page whose links are not exactly index.html's (the sign-in card links a different set) keeps its own links.
- A sheet missing from the hash map disables the bundle (the links stay as written) rather than sit stale behind the immutable cache.
- `/static/` is public on any client, so the bundle needs no credential, as before.

`tests/runtime/test_sheet_bundle.py` pins all of this without a clock. Module scripts are not bundled (no bundler by design); a `modulepreload` hint for the import graph was measured and made no difference, because the cost is request count, not chain depth.
