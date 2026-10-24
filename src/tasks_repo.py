"""Compatibility shim: the task domain layer now lives in the :mod:`src.tasks` package.
Every name callers import from ``src.tasks_repo`` is re-exported here unchanged, so the
routers, the CLI, the seed and the tests keep their imports until they move over.
"""

# Pure re-export module: nothing here is used locally.
# ruff: noqa: F401

from __future__ import annotations

# `use_clock` is re-exported too: the seed and the tests pin the clock through
# `repo.use_clock(...)`.
from src.clock import now_iso, today, use_clock
from src.tasks.mutations import (
    add_blocker,
    bulk_delete,
    bulk_update,
    capture_task,
    create_task,
    delete_task,
    done,
    import_diff,
    import_task,
    move,
    remove_blocker,
    set_due,
    set_priority,
    set_starts,
    set_status,
    update_task,
)
from src.tasks.queries import (
    BOARD_COLUMNS,
    _fts_query,
    board,
    captured_keys,
    count_mirror_events,
    counts,
    find_by_external_id,
    get_person,
    get_task,
    list_activity,
    list_blockers,
    list_comments,
    list_issue_refs,
    list_links,
    list_mirror_events,
    list_people,
    list_tasks,
    projects,
    search,
    today_view,
    tree,
    would_cycle,
)
from src.tasks.related import (
    MIRROR_EVENT_KINDS,
    MIRROR_EVENTS_CAP,
    add_comment,
    add_link,
    clear_mirror_events,
    create_person,
    delete_comment,
    delete_person,
    infer_link_kind,
    record_mirror_event,
    remove_issue_ref,
    remove_link,
    rename_external_id,
    rename_link,
    rename_link_url,
    resolve_mirror_field,
    set_issue_ref,
    touch_issue_ref,
    update_comment,
    update_person,
)
from src.tasks.schema import (
    DATE_FIELDS,
    DEFAULT_ACTOR,
    CaptureDismissed,
    CycleError,
    FolderResolver,
    NotFound,
    RepoError,
    ValidationError,
    WriteListener,
    _descendant_ids,
    add_write_listener,
    install_owner,
    remove_write_listener,
    set_folder_resolver,
    set_folder_web_resolver,
    set_members,
)
