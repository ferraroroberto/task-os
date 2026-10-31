# Phone access, sign-in and team mode

## Phone access & auth

The phone reaches the same app over **Tailscale**, as an installed PWA. Three pieces, all optional for a PC-only install:

**1. HTTPS — a real certificate for the tailnet name.** Once per tailnet, enable *HTTPS Certificates* in the Tailscale admin console (DNS page). Then, on the host:

```powershell
& .\.venv\Scripts\python.exe scripts\gen_tailscale_cert.py     # tailscale cert → webapp/certificates/{cert,key}.pem
tray.bat --restart
```

`gen_tailscale_cert.py` (copied from `project-scaffolding` and adapted here — copy-to-adapt, not vendor-verbatim) detects this machine's MagicDNS name and asks `tailscale cert` for a Let's Encrypt leaf — trusted by every device on the tailnet, **zero per-device trust steps**. With the pair present the launcher (the tray's `manager.py` and `launcher.py webapp` — the two spawn points; `webapp.bat` is a wrapper over the latter) serves **`https://<your-host>.ts.net:8448`**; without it the app serves plain HTTP and says so loudly in the log and in `GET /api/status` (`https: false`). The leaf lives ~90 days: every launcher runs `gen_tailscale_cert.py --check` **before uvicorn binds**, which renews a `.ts.net` cert expiring within ~30 days and never blocks a start. `localhost` is not in the cert — the tray's **Open task-os** / **Copy URL** use the `.ts.net` name (it resolves on the host too), the restart probe uses loopback and skips verification.

**2. Who may call the API.** Loopback (this PC — the browser on it, the tray, the `tasks` CLI, the restart probe) is the owner and needs nothing. **Any other client must present the bearer token**, either as `Authorization: Bearer <token>` (scripts, an LLM on another machine) or as the `taskos_token` cookie the sign-in page sets. With no token configured — the committed sample — the gate is **closed**: non-loopback gets `401` on `/api/*` and is sent to `/login`, which explains what to run.

```powershell
& .\.venv\Scripts\python.exe scripts\gen_token.py                # writes auth.token into config/config.json (created from the sample if missing)
& .\.venv\Scripts\python.exe scripts\set_password.py             # optional: a memorable secret to type instead (prompts twice, no echo; PBKDF2 hash stored, never the password)
tray.bat --restart                                               # config is read at startup
```

`gen_token.py --force` rotates the token and signs every device out at once (the cookie *is* the token); `--clear` goes back to loopback-only. `set_password.py --clear` removes the password. Failed and successful sign-ins are logged with the client address (and the member's id) in `data/logs/task-os.log`.

**One token per person.** Those two secrets are the **install owner's** — the first entry of `people` (or of `time.people` while there is no `people` block). Every other member gets their own, so the credential itself says who signed in and each one revokes on its own:

```powershell
& .\.venv\Scripts\python.exe scripts\gen_token.py --person <id>                # their token (printed once; --force rotates, --clear signs them out)
& .\.venv\Scripts\python.exe scripts\set_password.py --person <id>             # optional: their own password (prompts twice, no echo)
tray.bat --restart
```

Both refuse an id that is not a member, and the owner's id (whose secrets are the plain `auth.token` / `auth.password_hash`). Only a newly generated token is ever printed. Removing someone from the members list makes their token fail the gate (`401`) at the next restart. Who a request is — that member on any client, this PC with no credential = the owner — is `GET /api/me`, and comments and activity with no explicit author are signed with that member's name (the owner keeps their current name). A person binding never grants access by itself: it is read only from a credential the gate already accepted.

**Setting up a second phone.** On the host: `gen_token.py --person <their id>` and `tray.bat --restart`. On their phone: if it was signed in with the owner's shared secret, Settings → **Phone access** → **Sign out on this device**; then at the sign-in card paste *their* token (or type their password). Settings → **Phone access** now reads **Signed in as <their name>**.

**Owners and the live migration.** Schema v20 adds `tasks.owner` when the tray restarts on that build. Rehearse it first — `scripts/migrate_dry_run.py --db <path to tasks.db>` opens the database read-only, copies it with the SQLite backup API, migrates only the copy and prints each table's row count before → after, whether the existing content is identical, whether the source's mtime moved, and how many tasks have no owner (counts only, never a title; exit 0 means restart away — it works for any later schema step too). Tasks that are really the other member's can be handed over in one pass by the contact they are about: `scripts/assign_owner.py --person-id <contact id> --to <member id>` prints how many it would change and writes nothing; `--apply` writes, through the repo layer, so each change is an activity row.

**3. Sign in and install.** On the phone (Tailscale connected) open `https://<your-host>.ts.net:8448` → the sign-in card → paste the token or type the password → this device stays signed in for **90 days** (HttpOnly cookie, `Secure` over HTTPS). Then:

- **iOS (Safari):** Share → **Add to Home Screen** — the app launches full-screen (`display: standalone`), lands on **Today**, keeps the bottom pill above the home indicator.
- **Android (Chrome):** page menu → **Install app**.

Settings → **Phone access** shows what this connection is (`this PC` · `signed in`), **Signed in as <name>** once the install has two or more members, whether HTTPS and the token are on, and a **Sign out on this device** button when signed in with the cookie.

**What stays public** on any client: the static assets under `/static/` (the manifest and icons a phone needs before it can sign in), `/healthz`, `/api/version` (the build-identity contract), the `/login` page and `/api/login` itself. Everything else under `/api/` is gated; a page request from a signed-out phone redirects to `/login?next=…` and comes back where it started.

## Team mode

A shared install for a small team on the same private network (Step 12). Off by default, and off means exactly the model above.

```powershell
# config/config.json: "team": { "enabled": true, "people": ["<owner>", "<teammate>", …] }
& .\.venv\Scripts\python.exe scripts\gen_token.py            # team sign-in needs a token to exist
& .\.venv\Scripts\python.exe scripts\set_team_password.py    # prompts twice, no echo; stores the PBKDF2 hash only
tray.bat --restart
```

- **Signing in.** A teammate opens the URL → the same sign-in card → types the **team password** → a 90-day `taskos_team` cookie (HttpOnly, `Secure` over HTTPS). It is **not** the owner's token — it grants the same access to the app while valid, but it is derived from the token and the team password hash, so rotating either (`gen_token.py --force`, or a new team password) signs every teammate out at once. It is one shared sign-in: there is no revoking a single teammate short of that rotation. With no token configured there is no team sign-in either — the gate stays closed. `set_team_password.py --clear` turns the team password off.
- **Picking a name.** Right after signing in — and on any page they open before they have — the teammate lands on *Who are you?* and picks one of `team.people` (the members' names, once a top-level `people` block exists; `GET /api/me` then maps the pick onto that member). The team cookie stays derived from the owner's token alone: a member's own token (above) is a separate, individually revocable sign-in. The choice is remembered per browser (`taskos_name`, 90 days) and becomes the author of their comments and the actor on their changes. **The name is an authorship label, not a credential**: it grants no access, only a listed name counts, and anyone who can already write could state another one through the API. Settings → *Phone access* shows *you are <name> · change name*.
- **Loopback is still the owner.** This PC never needs the password or a name; with none picked it writes as the first entry of `team.people`.
- **Avatars** (optional): `data/avatars/<slug>.png|jpg|jpeg|webp`, the slug being the name lower-cased with other characters collapsed to `-` (`Sam Rivera` → `sam-rivera.png`). Without one, the card shows initials.
- **Folders** open through each person's own opener (Folders that open on any PC): a folder chip carries the placeholder ref, so it resolves to *their* synced copy on *their* PC.
