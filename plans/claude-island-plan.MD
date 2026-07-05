# AI dev workstation — ticket processing workflow

## Build spec for Claude Code

This document specifies the backend logic, data model, and integration points for
the "process ticket" subsystem of a personal AI dev workstation. It is scoped to
the Jira ticket → AI agent → reviewed diff pipeline only.

**Explicitly out of scope for this build pass: all visual design and styling.**
Build functional scaffolding with plain, unstyled markup (or minimal default
component library styling). The UI layer, layout, and visual design will be done
separately by hand. Prioritize correct data flow, correct API contracts, and
correct state transitions over how anything looks.

---

## 1. Context (for orientation, not to be built in this pass)

This subsystem is one "island" inside a larger personal dashboard that eventually
spans a work Mac, a personal Mac, a home PC, and an iPhone, backed by a shared
Postgres instance on a self-hosted Coolify server, connected over Tailscale.
Data is scoped per domain (work / personal / shared) via separate Postgres
schemas and separate API tokens — no UI-level hiding. The tables below live in
the `work` schema.

Other islands (Todoist-backed todo/project rollup, Google Calendar view) are
separate concerns and not part of this build pass.

---

## 2. Architecture summary

- **Environment constraint:** only one Docker/OrbStack project can be active
  locally at a time. The system must track a single "active ticket" environment
  state rather than assuming multiple concurrent live stacks.
- **Isolation for parallel subtask work:** git worktrees, not multiple Docker
  environments. Each subtask that only needs file edits gets its own worktree.
  Subtasks that require the live docker-compose stack to verify behavior queue
  sequentially against the one active environment.
- **Agent execution:** the Claude Agent SDK (Python or TypeScript), calling
  `query()` against a lead agent that plans subtasks and coordinates them via
  Agent Teams, each teammate isolated in its own worktree.
- **Model routing:** default backend is Claude (via the user's Team/Enterprise
  subscription credentials). On a `StopFailure` hook event indicating a rate
  limit or auth failure, the failed subtask is re-dispatched through a second
  SDK call with `ANTHROPIC_BASE_URL` pointed at a local LiteLLM proxy in front
  of a Qwen model server (reachable over Tailscale). Record which backend
  actually completed each subtask.
- **Push and PR remain manual.** The agent never runs `git push` or opens a PR.
  It may stage and commit locally.

---

## 3. Data model

Run this against the `work` schema.

```sql
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
```

Design notes:
- `agent_events` is append-only, used both for the live progress UI and as a
  debug log.
- `subtasks.backend` records which model actually completed the subtask, so a
  Qwen fallback is visible after the fact, not just inferred.
- `commit_plans` is separate from `subtasks` because a subtask may produce more
  than one logical commit.

---

## 4. Ticket status state machine

```
new -> planned -> in_progress -> review -> checks_failed -> in_progress (retry)
review -> ready_to_push -> pushed -> done
any state -> abandoned
```

`checks_failed` loops back to `in_progress` if the user asks the agent to fix
the failing check, or forward to manual intervention if they choose to fix it
by hand.

## 5. Subtask status state machine

```
pending -> running -> done
running -> failed -> pending (requeued, possibly with backend switched to qwen)
pending -> skipped
```

---

## 6. Ticket ingestion

- **Jira API** call on ticket open/refresh: pull `key`, `summary`, `description`,
  `acceptance criteria` (custom field, confirm field ID per Jira instance),
  comments, attachments list. Store raw payload in `tickets.raw_jira`.
- **Iframe** of the live Jira ticket URL, rendered alongside the structured
  data, for the human to read anything the API doesn't surface cleanly
  (attachments, formatting, comment threads).
- A free-text field for `processing_instructions`, editable before dispatch.

## 7. "Process ticket" trigger — sequence

1. Confirm/select the target repo (derived from `jira_project_key` →
   `repos` lookup) and confirm or create the branch name (manual, per user
   preference — do not auto-create without confirmation).
2. Confirm the docker-compose project for that repo is the currently active
   OrbStack project. If a different project is active, surface this rather
   than silently switching.
3. Compose the initial agent prompt from: ticket fields + processing
   instructions + a fixed policy preamble (see section 9).
4. Call the Agent SDK `query()` as the lead agent, instructing it to break the
   ticket into subtasks and coordinate them via Agent Teams, each teammate in
   its own worktree.
5. Persist a `subtasks` row per teammate as they're created (parse from SDK
   stream events), and append every streamed message to `agent_events`.
6. Register a `StopFailure` hook. On a rate-limit/auth-failure event for a
   given subtask: mark that subtask `failed`, set `error`, then re-dispatch it
   with `backend = 'qwen'` via a second SDK call configured with
   `ANTHROPIC_BASE_URL` set to the local LiteLLM → Qwen proxy endpoint.
7. On each subtask reaching `done`, mark ticket `review` once all subtasks in
   that ticket are `done` or `skipped`.

## 8. Review, checks, commit, PR

- **Review:** expose the worktree diff per subtask, plus an AI-generated
  summary of the change (can be produced in the same session, as the final
  message of that subtask's run).
- **Local checks:** a "run checks" action shells out to whatever pre-push
  hooks already exist in the repo (do not reimplement lint/test logic), writes
  results to `check_runs`.
- **Commit drafting:** on request, the agent (same session or a fresh one
  scoped to the full working diff) proposes a commit plan — one or more
  `commit_plans` rows, each with a message and file list. The user
  approves/edits before anything is staged. Committing is local only.
- **PR draft:** parse the existing PR template's named sections. Auto-fill
  fields derivable from ticket + commit messages (ticket link, summary).
  Leave everything else blank. Store as `pr_drafts`, status `draft` until the
  user manually opens the PR (`opened`, with `pr_url` filled in by hand or via
  a "mark as opened" action).

## 9. Fixed policy preamble (prepended to every agent dispatch)

Draft for review, adjust as needed:

```
You are working inside an isolated git worktree on branch {branch_name}.
Do not run `git push` under any circumstances. You may stage and commit
locally with clear, conventional-commit-style messages. Run the project's
existing test and lint commands before considering a subtask complete, and
report failures rather than working around them. If you are blocked or
uncertain about ticket intent, stop and report rather than guessing.
```

## 10. API surface to scaffold

```
POST   /tickets                       -- ingest/refresh a ticket from Jira
GET    /tickets/:id                   -- ticket + subtasks + status
POST   /tickets/:id/process           -- trigger the dispatch sequence (section 7)
GET    /tickets/:id/events            -- stream agent_events (SSE or polling)
POST   /tickets/:id/checks            -- run local pre-push checks
POST   /tickets/:id/commit-plan       -- request commit plan drafting
POST   /commit-plans/:id/approve      -- approve/edit and commit locally
POST   /tickets/:id/pr-draft          -- generate PR template fill
POST   /tickets/:id/pr-draft/opened   -- mark PR as opened, store pr_url
```

## 11. Configuration to be supplied (not to be hardcoded)

```
JIRA_BASE_URL
JIRA_API_TOKEN
ANTHROPIC credentials (subscription-based SDK auth)
QWEN_PROXY_URL          -- LiteLLM endpoint in front of Qwen, over Tailscale
COOLIFY_POSTGRES_URL    -- work schema connection string
repos table seed data   -- jira_project_key -> git_remote_url / compose path mapping
```

## 12. Open questions to confirm before/while building

- Exact Jira custom field ID for acceptance criteria, if used.
- Whether `checks_failed` should auto-retry via the agent or always require
  manual intervention.
- Whether Agent Teams is used for every ticket or only when the initial
  breakdown yields more than one independent subtask (single-subtask tickets
  may not need team coordination overhead).
