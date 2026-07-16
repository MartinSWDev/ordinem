-- Pluggable dispatch backends.
--
-- A mini-ticket now runs through a chosen agent CLI: 'claude' (Claude Code,
-- subscription login), 'cursor' (Cursor CLI, subscription login) or 'local'
-- (Claude CLI pointed at a local Anthropic-compatible proxy). 'qwen' stays
-- valid for rows written before the rename to 'local'.

alter table subtasks drop constraint subtasks_backend_check;
alter table subtasks add constraint subtasks_backend_check
  check (backend in ('claude', 'cursor', 'local', 'qwen'));
