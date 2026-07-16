-- The agent <-> human conversation loop.
--
-- A lead agent run can end awaiting the user's reply rather than done: the
-- agent closes its turn with an AWAITING_REPLY marker, the subtask parks in
-- `awaiting_input` (the UI flashes it), and the user's reply resumes the same
-- CLI session (subtasks.sdk_session_id) in the same worktree.

alter table subtasks drop constraint subtasks_status_check;
alter table subtasks add constraint subtasks_status_check
  check (status in ('proposed','pending','running','awaiting_input','done','failed','skipped'));
