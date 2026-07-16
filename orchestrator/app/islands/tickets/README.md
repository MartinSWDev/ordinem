# Tickets island (backend)

The Jira ticket → AI agent → reviewed diff pipeline. This is the largest island;
it owns ticket ingestion, the agent dispatch, and the review-and-ship stage.

## Layout

| File | Responsibility |
| --- | --- |
| `router.py` | `/tickets` routes: ingest, sync, list, detail, attachment proxy, process, events (SSE), checks, commit-plan, pr-draft |
| `projects.py` | `/projects/{key}/sync` — bulk-pull one project's issues |
| `commit_plans.py` | `/commit-plans/{id}/approve` — human gate before a local commit |
| `schemas.py` | Pydantic row/request/response models for the island |
| `repository.py` | All ticket/subtask/agent-event/commit-plan/check-run/pr-draft data access |
| `state_machine.py` | Ticket + subtask status transitions (validated centrally) |
| `dispatch.py` | Section-7 orchestration: preconditions, transitions, `run_ticket_agent` |
| `services/jira.py` | Jira Cloud REST client (search/fetch, curated normalization, attachment proxy) |
| `services/agent.py` | Runs one subtask through a backend CLI + StopFailure → local fallback |
| `services/backends.py` | Dispatch backends: Claude Code / Cursor / local proxy, probing + stream-json classification |
| `services/checks.py` | Shells out to the repo's existing pre-push hook |
| `services/pr.py` | PR-template parsing + auto-fill |
| `services/policy.py` | Fixed policy preamble prepended to every agent dispatch |

## Data (see `migrations/001`, `002`, `003`, `005`, `006`)

`tickets`, `subtasks`, `agent_events`, `commit_plans`, `check_runs`, `pr_drafts`.
Registered `repos` live in `app/core/repos.py` (shared).

## Ticket sources

`tickets.source` is `jira` (ingested read-only; `jira_key` required) or `local`
(self-authored via `POST /tickets/local`; no `jira_key`, never refreshed against
Jira). See `migrations/005_local_tickets.sql`.

## Plan -> gate -> dispatch

`POST /tickets/{id}/plan` asks a planner (services/planner.py) to decompose the
ticket into mini-tickets, stored as subtasks in `proposed` — an inert status the
dispatcher ignores. `POST /tickets/{id}/plan/approve` is the human gate: the
user's final, possibly-edited list replaces the proposal as `pending` work
(an empty list rejects the plan). `POST /tickets/{id}/dispatch` then runs each
approved mini-ticket in its own agent session and worktree, concurrently —
except `needs_docker` ones, which serialize against the single active OrbStack
project while the rest proceed alongside them.

The state machine enforces the gate: `proposed -> running` is not a legal
transition, so no route can dispatch unapproved work. See
`migrations/006_plan_dispatch.sql`.

## Frontend island

`src/islands/tickets/` renders this. The desktop island's `endpoint_base` points
at `…/tickets`.

## Dispatch backends

A dispatched mini-ticket runs through a headless agent CLI spawned in the
repo's `local_path` (`services/backends.py`). One-time setup per machine, then
the UI picker (`GET /tickets/backends`) shows what's available:

- **claude** — Claude Code CLI, billed to the logged-in Claude subscription
  (`npm i -g @anthropic-ai/claude-code`, run `claude` once to log in).
- **cursor** — Cursor CLI (`curl https://cursor.com/install -fsS | bash`,
  `cursor-agent login`).
- **local** — Claude CLI pointed at `LOCAL_PROXY_URL` (LiteLLM in front of a
  local model); listed as available only while the proxy answers a probe.

A rate-limit/auth stop on a subscription backend re-dispatches the subtask on
`local` when configured (section 7.6). Parsing teammate subtasks from the live
stream is still an open seam; a `/process` run is a single coordination
subtask until then.
