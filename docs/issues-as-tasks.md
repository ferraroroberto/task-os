# Issues as tasks

A coding task **is** an issue: `type = coding` ⇔ an `issue_refs` row (provider, `owner/repo`, number, state, url, last synced). The sync keeps the two in step, **read-mostly** — task-os never edits an issue's title, labels or state on the forge; the one write is *Create issue* below.

**Provider** — `config/config.json → issues`: `provider` (`github` or `gitlab`; blank / `none` = off), `owner` (whose repositories are searched), `assignee` (`@me`), `sync_minutes` (default 10), `host` (GitLab only). GitHub goes through the **`gh` CLI** (`gh auth login` once; no token in config): `gh search issues --assignee @me --state open --owner <owner> --json …`, `gh issue view`, `gh issue create` — each a subprocess with a 20 s timeout, never on a poll. Not configured (blank owner, `gh` not on PATH) and every failure (`not_authenticated`, `timeout`, `rate_limited`, `not_found`, `error` — classified from `gh`'s stderr) are **visible states**: `GET /api/issues/status`, Settings → *Issues as tasks* and `tasks issues status` say which; a failed listing changes nothing — never an empty list read as "no issues".

**GitLab (a second site)** — the same app, switched by config only; the sync, auto-close, *Create issue*, the chips and search are unchanged. It goes through **`glab api`** (`glab auth login --hostname <your-gitlab-host>` once; no token in config), with the same 20 s timeout, the same classified failures and the same visible not-configured states (blank `owner`, `glab` not on PATH). `owner` is the **group path** (`my-group` or `my-group/sub-group` — the group's issue list includes its sub-groups' projects), `assignee` is `@me` or a GitLab username, `host` is the instance's hostname (blank = `gitlab.com`; it is always passed as `--hostname`, so the process's working directory never picks the forge). Listing: `GET groups/<group>/issues?state=opened&scope=assigned_to_me` (`--paginate`); confirming a close: `GET projects/<path>/issues/<iid>`; *Create issue*: `POST projects/<path>/issues` with the task's title and description, assigned by user id. A GitLab issue's `iid` is the task's number, its full project path the `repo` (so `code` = `<project>#<iid>`). A second site's `config.json`:

```json
{
  "site": "second",
  "port": 8448,
  "issues": { "provider": "gitlab", "host": "gitlab.example.com", "owner": "example-group", "assignee": "@me", "sync_minutes": 10 },
  "placeholders": { "onedrive": "D:/Synced" },
  "mirror": { "dir": "{onedrive}/task-os/mirror", "backup_dir": "{onedrive}/task-os/backup" }
}
```

Refs are keyed by provider, so a database that once synced GitHub keeps those tasks as they are; a GitLab pass never polls them.

**Sync** — a pass runs 10 s after startup, then every `sync_minutes` while the app is up, and on demand: *Sync now* in Settings → *Issues as tasks* or in a task's issue panel, `POST /api/issues/sync`, `tasks issues sync`. One pass:

| On the forge | In task-os |
| --- | --- |
| an open issue assigned to you with no task | a new **coding** task in **To do**: `title` = the issue title, `code` = `<repo>#<n>` (short repo name), `description` = the issue body, a link (`kind = issue`), the ref (state `open`, url); `created_by = sync`. Dedupe key = (provider, repo, number) — a re-run touches nothing it already made |
| the issue's **title changed** | the task title follows (activity `title` by `sync`) — the issue title is canonical for a coding task; rename it on the forge |
| an issue that was **closed** is open again | the ref goes `open`; a task that was done / cancelled is **reopened** to `todo` (activity by `sync`) |
| a ref that should be open is **missing from the list** | confirmed first with one `gh issue view` (GitLab: one issue read): **closed** → the ref goes `closed` and the task is **done** (skipped when already done / cancelled; activity `status … → done · sync` + `issue_state open → closed · sync`); still open (unassigned from you, another owner) → nothing but `last_synced` moves; the lookup failed → the task is left alone and the error is in the result. Closed refs are not polled again |

GitHub's search index is eventually consistent — an issue closed seconds ago can still be listed *open* for ~30 s; the next pass catches it. Every task the sync creates or changes goes through the same repo layer as the UI, so the activity log, the markdown mirror and the Board see it like any other write.

**Create / link / unlink** — in the drawer's issue panel of a plain task: *Create issue* (repo from the last-seen list or typed as `owner/repo`) runs `gh issue create` (GitLab: the `POST` above) with the task's title and description, assigns it to you and links it — the task becomes coding with `code = repo#N` (`tasks issue create N --repo owner/name` from the terminal). *Link existing* takes `owner/repo#N` (a nested GitLab path too) or the issue URL on any host — a URL with GitLab's `/-/issues/` is a GitLab ref (`PUT /api/tasks/{id}/issue`) — the next sync fills state and url. *Unlink* (`DELETE`) makes it a plain task again; the issue is untouched. Board and Today rows carry the chip (`repo#N`, provider glyph, muted with a check once closed) that opens the issue.

**Never written back:** titles, labels, state, assignees, comments. A local rename of a coding task is overwritten by the next sync; a task marked done locally does **not** close its issue.
