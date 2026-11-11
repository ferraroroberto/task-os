# Declared statuses

Three small lifecycles are declared once each, so no reader spells their words again. They are listed in `.fleet.toml` as `[[state_machines]]`; the convention is project-scaffolding's `docs/implicit-state-machines.md`.

## Task status

`TaskStatus` in `src/schema.py` is the `tasks.status` column's value set: `inbox` (arrived on its own, not triaged), `todo`, `standby` (parked on purpose), `done` and `cancelled`. The status is stored, not derived, and any status may move to any other (a reopened task is the same row), so the guards are the value set itself: the repo's field validation and the column's `CHECK` refuse a word outside it. `TASK_STATUSES`, `CLOSED_STATUSES` (done and cancelled, which both stamp `done_at`), `DEFAULT_STATUS` and `CAPTURE_STATUS` are all built from the enum.

The browser mirrors the five words in `app/webapp/static/js/tasks/status.js` (`Status`, `STATUSES`, `CLOSED_STATUSES`); `format.js` re-exports `STATUSES` for the views that already import it. `tests/tasks/test_task_status.py` fails if the two tables differ. A reader compares against `TaskStatus.DONE` or `Status.DONE`, never the bare word.

## AI suggestion status

`SuggestionStatus` in `src/ai/triage.py` is the `ai_suggestions.status` column: `pending` (staged, waiting), `accepted` (applied to its task) and `rejected` (dismissed). Only `pending` moves, once; `_pending` is the guard that refuses a second answer, and `list_suggestions` refuses a status outside the set.

## The in-flight flag

The Time and Email-archiving sheets each keep a `busy` flag on their state so a second click is ignored while a request runs. `app/webapp/static/js/busy.js` is its only writer (`holdBusy`, `releaseBusy`); the screens read `st.busy` and call those around the request.
