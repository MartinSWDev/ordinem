-- Tickets can originate locally (personal work), not only from Jira.
--
-- A local ticket has no jira_key and no curated `jira` projection — you write
-- the title/description yourself. Postgres treats NULLs as distinct under a
-- unique constraint, so many local tickets coexist with jira_key IS NULL.
-- Everything downstream (instructions -> plan -> mini-tickets -> agents ->
-- review & ship) is identical; only the source differs.

alter table tickets alter column jira_key drop not null;

alter table tickets add column source text not null default 'jira'
  check (source in ('jira', 'local'));

-- A jira-sourced ticket must still carry its key.
alter table tickets add constraint tickets_jira_key_required
  check (source <> 'jira' or jira_key is not null);
