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
| `services/agent.py` | Claude Agent SDK dispatch + StopFailure → Qwen fallback (lazy-imported) |
| `services/checks.py` | Shells out to the repo's existing pre-push hook |
| `services/pr.py` | PR-template parsing + auto-fill |
| `services/policy.py` | Fixed policy preamble prepended to every agent dispatch |

## Data (see `migrations/001`, `002`, `003`)

`tickets`, `subtasks`, `agent_events`, `commit_plans`, `check_runs`, `pr_drafts`.
Registered `repos` live in `app/core/repos.py` (shared).

## Frontend island

`src/islands/tickets/` renders this. The desktop island's `endpoint_base` points
at `…/tickets`.

## Seams

The live agent run (`services/agent.py` + `dispatch.run_subtask`) needs the Agent
SDK + a real worktree/docker environment. Parsing teammate subtasks from the live
SDK stream is the one env-dependent seam; the lead run is a single coordination
subtask until then.
