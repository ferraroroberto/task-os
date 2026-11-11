# Archive states

The archive lifecycle is declared in one module, `src/archive_state.py`, at two levels: a **run** and a **mail** (an item). The tables store facts; the module is the only code that turns those facts into a mode. Every API response carries the result as an additive `state` field, and the screen reads that field instead of working it out again.

## Why it is declared

"Is a run going?" used to be two unrelated facts: the service's in-memory lock and the run row's `status`. Nothing reconciled them, so a run cut short by a restart stayed `running` forever while the Archive head read `ready`, the Settings row read `on`, and the recent-runs total skipped it. A mail's mode was worked out in two languages: a failed row with files on disk is retryable and revertible, a failed row with none is the next run's job, and a `needs_review` row with a decision is shown as reviewed. Each reader re-derived these, and they drifted.

## Run states

A run is `RunState`, derived by `derive_run_state(run_row, worker_alive)`.

| State | Facts | Meaning |
|---|---|---|
| `running` | row open, and this process holds a worker for that row | a run is in flight |
| `interrupted` | row open, no worker | the process died mid-run; nothing will close the row. Carries `state_reason` |
| `done` | row closed `done` | finished; `error` may still carry notes (a re-index that did not confirm, an unranked batch) |
| `failed` | row closed `failed` | ended with its reason in `error` |

`interrupted` is the honest answer for a row that is open with no worker. It is not stored (the column only allows `running`, `done`, `failed`): the app closes such rows when it starts (`ArchiveBatchService.close_interrupted_runs`, called from the app's startup), recording `failed` with the reason `interrupted: the app stopped during this run` and recomputing the counters from the items the run wrote. The sweep is never run by the constructor, because the `tasks` CLI builds the service to read a status while the app may be mid-run; it also does nothing while this service holds a worker.

## Mail states

A mail is `ItemState`, derived by `derive_item_state(item_row)` from `status`, `files` and `decided_at`.

| State | Facts | Allows |
|---|---|---|
| `archived` | status `archived` | revert, move |
| `moved` | status `moved` | revert, move |
| `needs_review` | status `needs_review`, no decision | accept, file it into a folder |
| `reviewed` | status `needs_review`, `decided_at` set | nothing more is asked; the server still lets it be filed |
| `failed_on_disk` | status `failed`, files written | accept, retry (when a folder was chosen), revert, move |
| `failed_clean` | status `failed`, no files | accept; the next run decides it again |
| `reverted` | status `reverted` | nothing; a later run owns it |

An unrecognised stored status raises instead of reading as some default, so a new status is a code change in this module.

## Who reads it

- Python: `archive_actions.py` guards (revert, move, retry, accept) call `derive_item_state`; `archive_store.py` adds `state` to every item it returns; `archive_batch.py` and the router add it to every run (`ArchiveBatchService.annotate`).
- JavaScript: `app/webapp/static/js/archive/state.js` mirrors the two tables and answers the questions the screen asks (`runIsLive`, `runFailed`, `isFiled`, `canMove`, `canRetry`, `needsAnswer`, `isDecided`). The head, the picker, the run poller, the report, the row actions, the state chip and the Settings row use it. `tests/archive/test_archive_state.py` fails when the two tables name different states.

A new reader asks `state`; it does not compare `status` to a word or combine `status` with `files` / `decided_at`. A new mode is a new state in the module, handled by every reader.

The machines are declared in `.fleet.toml` as `archive-run`, `archive-item` and `archive-ui-state`, so the conventions ratchet reports any other module that re-spells these states.
