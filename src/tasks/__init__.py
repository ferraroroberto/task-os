"""Domain operations over the task schema — the one place the rules live.

Every entry point takes an open ``sqlite3.Connection`` (row factory
``sqlite3.Row``) and returns plain dicts, so the REST routers, the ``tasks``
CLI in local mode, the fixture seed and the tests all share one code path.
Writes commit before returning.

Rules enforced here (plan §04):

- a task with children is a project — the ``project`` filter is "descendant
  of", the tree/breadcrumb are recursive CTEs, nesting depth is unlimited;
- ``move()`` refuses cycles (a task can't become its own descendant);
- every due / status / parent / priority (and title, type, recurrence,
  person, description, …) change writes an ``activity`` row with actor,
  field, old → new;
- ``done()`` on a recurring task rolls the *same* task's due forward to the
  next occurrence after both that due and today (``src.dates.next_due``,
  honouring the fixed-day ``recurrence_anchor`` and the every-N
  ``recurrence_interval``) and logs the completion; a
  non-recurring task becomes ``done`` with ``done_at``; the roll never
  touches ``starts``. ``done_at`` is the *closed-at* stamp (#102): entering
  ``done`` or ``cancelled`` sets it, reopening clears it — the done journal
  groups both by that local day;
- a task whose ``starts`` has not arrived is *deferred*: :func:`list_tasks`
  hides it by default, so every working view (Board, Today, the CLI)
  inherits one rule from one clause — :func:`tree` and :func:`search` read
  the table directly and keep showing it (#87);
- ``coding`` ⇔ an ``issue_refs`` row exists: attaching one sets the type,
  detaching reverts it, and setting ``type='coding'`` by hand is rejected;
- full-text search hits title / description / comment bodies via the two
  FTS5 indexes and returns a snippet per hit;
- an importer is idempotent on ``external_id`` (tasks, comments, people):
  :func:`import_task` creates with the source's own timestamps and logs ONE
  ``imported`` row, or updates the fields that changed on a re-run;
- a *capture* is idempotent on ``external_id`` too, but one-way:
  :func:`capture_task` creates the task the first time a source offers it and
  then never touches it again (#98) — an import reconciles, a capture only
  ever lands. Its key is remembered in ``capture_keys`` apart from the row,
  so deleting the task *dismisses* the capture rather than inviting the
  source to land it again (#254);
- a task's ``owner`` (#476) is a member id from the config, plugged in by
  :func:`set_members`; a NULL owner means the install owner (the first
  member), so a task nobody gave one — every task from before v20, a synced
  issue, an email capture — is the owner's without a data write. Every task
  shape carries the *effective* owner (never null), the ``owner`` filter of
  :func:`list_tasks` counts NULL as the install owner's, and setting one that
  is no member is a :class:`ValidationError`. ``owner`` is not ``person_id``,
  which stays the contact a task is about.

Timestamps come from ``src.clock``'s :func:`now_iso` (local time, second
precision, offset kept), re-exported here with :func:`use_clock` and
:func:`today` so a seed or a test still pins the clock through ``repo``.

Write hooks: every mutation ends by calling the registered write listeners
with the task ids it touched (:func:`add_write_listener`) — the markdown
mirror's debounced exporter (``src/mirror.py``) hangs off this so a change
made through the API, the CLI's local backend or an importer all reach the
mirror through the one layer that owns the rules.

Folder refs stay unresolved in the row (``{onedrive}/house`` — plan §04); two
presentation hooks, :func:`set_folder_resolver` and
:func:`set_folder_web_resolver`, let the app plug the placeholder resolution
in so every summary carries ``folder_resolved`` (this server's absolute path,
for display) and ``folder_url`` (the web link from a ``links(kind=folder)``
row when one exists, else the cloud twin derived from ``config.web_roots`` —
#28) — the UI never resolves a ref client-side (Step 9).
"""
