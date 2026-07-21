#!/usr/bin/env bash
# One-shot orchestrator bootstrap for a new machine (e.g. the work PC).
# Idempotent: safe to re-run. Does the deterministic setup and tells you the
# two things only you can decide (DATABASE_URL and the repos row).
set -euo pipefail

cd "$(dirname "$0")"
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

# 1. Tooling ------------------------------------------------------------------
command -v uv >/dev/null || { warn "install uv first: https://docs.astral.sh/uv/"; exit 1; }

say "Installing Python deps (uv sync)…"
uv sync

# 2. Agent CLIs (the billing setup — subscription logins, no API key) ---------
check_cli() {
  if command -v "$1" >/dev/null; then
    say "found '$1' ($(command -v "$1"))"
  else
    warn "'$1' not on PATH — $2"
  fi
}
check_cli claude "install + log in: npm i -g @anthropic-ai/claude-code && claude"
check_cli cursor-agent "install + log in: curl https://cursor.com/install -fsS | bash && cursor-agent login"

# 3. .env ---------------------------------------------------------------------
if [ -f .env ]; then
  say ".env already exists — leaving it untouched"
else
  cp .env.example .env
  say "created .env from .env.example"
  warn "edit .env: set DATABASE_URL to your Postgres (keep DB_SCHEMA=work)"
fi

# 4. Migrations ---------------------------------------------------------------
# They apply automatically on first startup, so just remind the user to run it.
say "Setup done. Migrations apply automatically when you start the server."
cat <<'NEXT'

Next:
  1. Edit orchestrator/.env  → DATABASE_URL = your Postgres
  2. Seed one repos row (per work repo the agents will touch):
       insert into work.repos (name, jira_project_key, git_remote_url, local_path, default_branch)
       values ('my-app', 'PROJ', 'git@github.com:you/my-app.git', '/abs/path/to/checkout', 'main');
     -- local_path is REQUIRED: agents run there; worktrees branch off default_branch.
  3. Run it:
       uv run uvicorn app.main:app --port 8787
  4. Verify backends:  curl http://127.0.0.1:8787/tickets/backends
  5. On your dashboard machine, point the tickets island's endpoint_base at
     this PC (localhost here, or its Tailscale address from another device).
NEXT
