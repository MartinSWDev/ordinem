-- Ordinem orchestrator — initial schema (section 3 of claude-island-plan.MD).
-- Applied into the schema named by DB_SCHEMA (default "work"). The migration
-- runner sets search_path to that schema before executing this file, so the
-- unqualified table names below land in the right schema.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

create table repos (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  jira_project_key text not null unique,
  git_remote_url text not null,
  docker_compose_path text,
  default_branch text not null default 'main',
  created_at timestamptz not null default now()
);

create table tickets (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid not null references repos(id),
  jira_key text not null unique,
  title text not null,
  description text,
  raw_jira jsonb,
  processing_instructions text,
  branch_name text,
  status text not null default 'new'
    check (status in ('new','planned','in_progress','review','checks_failed','ready_to_push','pushed','done','abandoned')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table subtasks (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets(id) on delete cascade,
  title text not null,
  description text,
  order_index int not null default 0,
  status text not null default 'pending'
    check (status in ('pending','running','done','failed','skipped')),
  backend text check (backend in ('claude','qwen')),
  worktree_path text,
  sdk_session_id text,
  started_at timestamptz,
  finished_at timestamptz,
  error text
);

create table agent_events (
  id bigserial primary key,
  subtask_id uuid not null references subtasks(id) on delete cascade,
  event_type text not null, -- message | tool_use | tool_result | stop | stop_failure
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create table commit_plans (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets(id) on delete cascade,
  subtask_id uuid references subtasks(id),
  proposed_message text not null,
  files jsonb not null,
  status text not null default 'proposed'
    check (status in ('proposed','approved','edited','committed','rejected')),
  sha text,
  created_at timestamptz not null default now()
);

create table check_runs (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets(id) on delete cascade,
  check_name text not null,
  status text not null check (status in ('pass','fail','error')),
  output text,
  run_at timestamptz not null default now()
);

create table pr_drafts (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets(id) on delete cascade,
  template_fields jsonb not null,
  status text not null default 'draft' check (status in ('draft','opened')),
  pr_url text,
  created_at timestamptz not null default now()
);

-- Helpful indexes for the append-only event log and per-ticket lookups.
create index agent_events_subtask_idx on agent_events (subtask_id, id);
create index subtasks_ticket_idx on subtasks (ticket_id, order_index);
create index commit_plans_ticket_idx on commit_plans (ticket_id);
create index check_runs_ticket_idx on check_runs (ticket_id);
