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

2. **Local Postgres** (for dev; production points at the Coolify instance):
   ```sh
   docker run -d --name ordinem-pg \
     -e POSTGRES_USER=ordinem -e POSTGRES_PASSWORD=ordinem -e POSTGRES_DB=ordinem \
     -p 5433:5432 postgres:16
   ```

3. **Configure**:
   ```sh
   cp .env.example .env
   # fill in JIRA_*, ANTHROPIC_API_KEY, QWEN_PROXY_URL as you get them
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

## Seed data

Ticket ingestion needs a `repos` row mapping the Jira project key to a git
remote / compose path (section 11). Seed it once, e.g.:

```sql
insert into work.repos (name, jira_project_key, git_remote_url, docker_compose_path)
values ('my-app', 'PROJ', 'git@github.com:me/my-app.git', '/Users/me/repos/my-app/docker-compose.yml');
```

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
