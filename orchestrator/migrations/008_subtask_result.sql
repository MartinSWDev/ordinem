-- The agent's final report, shown in the UI.
--
-- A subtask that "completes" may have declined to write code (blocked, premise
-- wrong, needs a human call) — the run finishing is not the work being done.
-- Storing the closing message on the row makes the outcome reviewable without
-- digging through agent_events.

alter table subtasks add column result text;
