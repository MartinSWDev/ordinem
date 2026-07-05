-- Support the "my tickets across all projects" sync model.
--
-- Tickets can now exist without a registered repo: you see your whole backlog,
-- but a ticket is only "actionable" (dispatchable to an agent) once its project
-- has a repos row. So repo_id becomes nullable, and we denormalize the Jira
-- project key onto the ticket so the island can group/filter by project even
-- when no repo is registered yet.

alter table tickets alter column repo_id drop not null;

alter table tickets add column jira_project_key text;

-- Backfill existing rows from their linked repo.
update tickets t
set jira_project_key = r.jira_project_key
from repos r
where r.id = t.repo_id;

create index tickets_project_idx on tickets (jira_project_key);
