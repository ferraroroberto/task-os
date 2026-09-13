# Story 26 — Same app at a second site (GitLab)

**Issue:** #12 (Step 11/13). **Tests:** `tests/test_issues_gitlab.py` (7) — the GitLab provider over **recorded `glab api` JSON** (synthetic: shaped after GitLab's REST v4 issue and user objects, on an invented host `gitlab.example.com` and group `example-group/platform`; no real host, group or token anywhere): the list call's argv (`--hostname`, `--paginate`, `groups/<group>/issues?state=opened&scope=assigned_to_me…`) and its two pages printed back to back, `iid` → number, `opened` → open, labels as names or objects, a sub-group project's full path as `repo`; the one-issue read; *create* as `GET user` once (cached) then one `POST` answered with the issue (no read-back); a username assignee (`scope=all&assignee_username=…`, user lookup, `not_found` when unknown) and the default host; the named failures `not_installed` · `timeout` · `not_authenticated` · `rate_limited` · `not_found` · `error` (incl. non-JSON output); the not-configured states (blank group, `glab` not on PATH); the config switch (`site = second`, `provider = gitlab`, `host`) and GitHub ignoring `host`; and **the unchanged sync rules driven by it** — two new coding tasks in To do with `code = <project>#<iid>` and the self-hosted URL, a close on the forge confirmed with one read → the task done, and a GitHub ref already in the database never polled. The GitHub path keeps its own tests unchanged in `tests/test_issues.py` (the one edit there: the "gitlab → not supported yet" assertion now uses an unknown provider name).

No e2e story test: the suite is already over its budget (see `CLAUDE.md`), and the only browser-visible change is the drawer's *Link existing* parser.

**Steps → expected (the acceptance story)**

1. Clone on another machine → `config/config.json` with `site = second`, `issues.provider = gitlab`, `issues.owner = <group>`, `issues.host = <your-gitlab-host>`, `placeholders` pointing at that site's synced folder; `glab auth login --hostname <your-gitlab-host>` once.
2. Settings → *Issues as tasks*: **enabled · gitlab · every 10 min**.
3. **↻** in the header → toast *Issues synced: N open · N new* → the open issues assigned to you across the group (sub-groups included) become **coding** tasks in To do, each with a chip that opens the issue on that host.
4. Close one issue on GitLab → **↻** → the task is **done** (activity by `sync`).
5. A plain task → *Create issue* in `<group>/<project>` → an issue on GitLab assigned to you, the task coding with `code = <project>#<iid>`; *Link existing* with a GitLab issue URL (`…/-/issues/N`) → linked as a GitLab ref.
6. The markdown mirror folder fills in that site's synced folder (`mirror.dir` under its `placeholders`).

**Result**

| Leg | Result |
| --- | --- |
| Unit — `tests/test_issues_gitlab.py` (7) + `tests/test_issues.py` unchanged | verified 2026-09-13 |
| CLI probe — the real `tasks` CLI (`--local`, scratch DB, second-site config) with a stand-in `glab.exe` on PATH that answers the same synthetic JSON: `issues status` → *gitlab · every 10 min*; `issues sync` → *2 open issue(s) · 2 new* (`garden-bot#14`, `home-dashboard#3` — a sub-group project — both `gitlab`, self-hosted URLs); close on the stand-in forge → `issues sync` → *1 closed*, task done; `issue create 3 --repo example-group/platform/garden-bot` → `garden-bot#50`. The argv the stand-in received shows the real Windows spawn keeps `&` and spaces intact in `-f title=…` | verified 2026-09-13 (stand-in forge, not GitLab) |
| Browser walk — headless Chromium 1440×900 against a disposable instance (synthetic seed, second-site config, the same stand-in `glab.exe`): ↻ → *Issues synced: 2 open · 2 new*, the seeded GitHub coding task untouched; the drawer's issue chip → `https://gitlab.example.com/…/-/issues/14`; *Link existing* with `https://gitlab.example.com/example-group/platform/api/-/issues/7` → *Linked example-group/platform/api#7*, the follow-up sync fills state `open` + the self-hosted URL, chip `api#7`; no page errors. Screenshots inspected in-session, not committed | verified 2026-09-13 (stand-in forge, not GitLab) |
| **On screen at a second site — a real GitLab host, `glab` authenticated, steps 1–6 above** | **not verified** — no machine with `glab` and a GitLab host was available; deferred until one is (issue #12) |
