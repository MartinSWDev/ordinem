# Ordinem Orchestrator

The ticket-processing backend service for the Ordinem dashboard: **Jira ticket →
AI agent (worktrees + Agent Teams) → reviewed diff → local commit**. This is the
service the Tauri app's "Tickets" island fetches from over Tailscale.

Built per [../plans/claude-island-plan.MD](../plans/claude-island-plan.MD). This
pass is functional scaffolding — correct data flow, API contracts, and state
transitions. No UI, no styling.

## Stack

- **FastAPI** + uvicorn (async; SSE for the live event stream)
- **asyncpg** against Postgres (the `work` schema)
- **Pydantic v2** for typed contracts
- **Claude Agent SDK** for agent dispatch (optional dependency, lazy-imported)

## Layout

```
app/
  config.py          env-driven settings (nothing hardcoded)
  db.py              asyncpg pool + SQL migration runner
  state_machine.py   ticket + subtask state machines (sections 4-5)
  schemas.py         Pydantic row + request/response models
  repository.py      data access (status changes go through the state machine)
  dispatch.py        section-7 orchestration glue + DB event sink
  routes/            the section-10 API surface
  services/
    jira.py          Jira Cloud REST ingestion (section 6)
    agent.py         Agent SDK dispatch + StopFailure -> Qwen fallback (section 7)
    checks.py        shells out to the repo's existing pre-push hook (section 8)
    pr.py            PR template parsing + auto-fill (section 8)
    policy.py        fixed policy preamble (section 9)
migrations/          plain .sql, applied in order, tracked in schema_migrations
tests/               state-machine coverage
```

## Setup

1. **Install deps** (with [uv](https://docs.astral.sh/uv/)):
   ```sh
   cd orchestrator
   uv sync                 # base API
   uv sync --extra agent   # also install the Claude Agent SDK
   uv sync --extra dev     # also install pytest
   ```

2. **Postgres** (see "Deployment & data residency" below for where it should
   actually live). For a quick local instance via Docker:
   ```sh
   docker run -d --name ordinem-pg \
     -e POSTGRES_USER=ordinem -e POSTGRES_PASSWORD=ordinem -e POSTGRES_DB=ordinem \
     -p 5433:5432 postgres:16
   ```
   Or a Homebrew instance kept always-on at negligible cost:
   ```sh
   brew services start postgresql@16   # starts at login, ~30MB idle
   createdb ordinem
   ```

3. **Configure**:
   ```sh
   cp .env.example .env
   # set DATABASE_URL to your Postgres; fill in JIRA_*, ANTHROPIC_API_KEY,
   # QWEN_PROXY_URL as you get them
   ```

4. **Run** (migrations apply automatically on startup):
   ```sh
   uv run uvicorn app.main:app --reload --port 8787
   ```
   Open http://127.0.0.1:8787/docs for the interactive API.

5. **Test**:
   ```sh
   uv run pytest
   ```

## Repos (no manual seeding)

A `repos` row is **auto-created from tickets** on sync — one per Jira project —
so there's no `insert into repos` step. Each repo's local checkout is guessed as
`REPOS_BASE_DIR/<name>` (default `~/Repos`); when the name doesn't match, the
ticket view shows a picker listing the git repos found under `REPOS_BASE_DIR`,
and you bind the checkout once (`PATCH /tickets/repos/{id}`). A ticket is
`actionable` — dispatchable — only once its repo has a resolved checkout.

## Deployment & data residency

Work ticket details should **not** leave the work machine. So the database is
split by data-residency rather than run as one shared instance:

| Data | Where the DB lives | Where this service runs |
| --- | --- | --- |
| `work` (Jira tickets, subtasks, agent events) | **local Postgres on the work Mac** | on the work Mac |
| `personal` / `shared` (todos, calendar, stats) | shared Coolify Postgres (home server) | on the home server |

The work orchestrator + agent workers run on the work Mac anyway — the agents
check out and edit work repos there and run their docker-compose stacks there —
so work ticket data is fetched, stored, and processed entirely on the work
machine and never touches personally-hosted infrastructure. This is a
`DATABASE_URL` change only; the code is identical across deployments.

The dashboard islands (on any device) are thin viewers: the work-tickets island
points its `endpoint_base` at the work Mac (localhost, or its Tailscale address
when glancing from another device); other islands point at the home server.

**What needs to be running:**

- **Postgres → always on.** The data must persist between agent runs (the
  dashboard reads ticket state when no agent is active), and idle cost is
  negligible, so run it via launchd and forget it:
  ```sh
  brew services start postgresql@16
  ```
- **This API → always on if** you want to read ticket state from another device
  whenever the work Mac is awake; **on-demand** if you only use it at the Mac.
  Reachable from other devices only while the work Mac is awake and on Tailscale
  — for work data, that's a feature.
- **Agent workers → on-demand.** They spin up per dispatch and exit; nothing
  persistent.

## What runs now vs. what needs the live environment

- **Runs now:** migrations, all state transitions, ticket ingestion (once
  `JIRA_*` is set), checks, commit-plan gating, PR-draft generation, SSE stream.
- **Needs the SDK + a real worktree/docker environment:** the agent run itself
  (`services/agent.py` + `dispatch.run_subtask`). Install the `agent` extra and
  set Anthropic creds. Parsing teammate subtasks out of the live SDK stream is
  the one seam left marked for when that environment is wired up.

## Notes on behavior

- `checks_failed` is **manual intervention only** — it never auto-retries. The
  user chooses to re-dispatch to the agent (→ `in_progress`) or fix by hand
  (→ `ready_to_push`).
- The agent **never** runs `git push` or opens a PR (enforced by the policy
  preamble). Committing is local; opening the PR is a manual step recorded via
  `POST /tickets/:id/pr-draft/opened`.
