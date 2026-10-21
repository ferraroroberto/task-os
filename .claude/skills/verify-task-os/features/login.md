# login

<!-- gen:begin feature -->
**Seeded from:** key views

**How a user reaches it**

- Open the route `/login` (sign-in card: token or password → cookie).

| Sub-feature | Surface name | Driving test node(s) |
| --- | --- | --- |
| sign-in card: token or password → cookie | - | none: see Drive below |

**Drive:** no `surface()` name covers this view yet, so no test drives it. Launch an instance and reach it as described above; to make it testable, add a test that opens it and calls `surface()`.
<!-- gen:end feature -->

## Gotchas

- **The `/login` walk exists but is untagged.** `tests/e2e/test_story_07_phone.py::test_phone_install_metadata_and_story` renders `/login` and signs in with the token on its own token-configured instance (`authed_webapp`), yet calls no `surface()`, so the map shows no node and Drive's single command does not run it. Run it by name. It is not a Maintain-mapped node: a red one will not turn `MAINTAIN` blocked.
- **The browser on a disposable instance is the owner.** The instance binds `127.0.0.1` and loopback needs no credential, so nothing redirects to `/login` and the page signs in only against an instance whose config carries a token. There is no auth-disable switch; do not look for one.
