-- Plan -> human gate -> dispatch.
--
-- A planner agent proposes mini-tickets; they land as subtasks in the new
-- `proposed` status, which is inert — nothing dispatches it. The user edits and
-- approves, which moves them to `pending`, and only then do agents run. That
-- gate is the point: an agent never sets its own work loose.
--
-- `needs_docker` marks a mini-ticket that must run against the single active
-- OrbStack env, so the dispatcher serializes those against each other while the
-- rest run in parallel.

alter table subtasks add column needs_docker boolean not null default false;

alter table subtasks drop constraint subtasks_status_check;
alter table subtasks add constraint subtasks_status_check
  check (status in ('proposed','pending','running','done','failed','skipped'));
