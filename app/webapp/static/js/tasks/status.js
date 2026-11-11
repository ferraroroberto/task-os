/* task-os — the task statuses: the JS mirror of src/schema.py's TaskStatus.
 * The API stores and returns these five words; this module names them so no
 * other file spells one as a bare string or re-lists the set.
 * tests/tasks/test_task_status.py keeps this table equal to Python's. */

'use strict';

export const Status = {
  INBOX: 'inbox',
  TODO: 'todo',
  STANDBY: 'standby',
  DONE: 'done',
  CANCELLED: 'cancelled',
};

export const STATUSES = Object.values(Status);

//: The statuses a task leaves the working views in; both stamp `done_at`.
export const CLOSED_STATUSES = [Status.DONE, Status.CANCELLED];

