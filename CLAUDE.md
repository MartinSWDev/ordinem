# CLAUDE.md

## Island architecture (read before adding features)

This app is built from **islands** — each feature is a self-contained frontend
folder (`src/islands/<name>/`) and backend package
(`orchestrator/app/islands/<name>/`), each with its own `README.md`, over a thin
shared core (`src/core` + `src/ui`; `orchestrator/app/core`).

**When adding a feature, add an island — do not scatter its code across shared
files or import between islands.** Follow the structure and checklist in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Backend island packages use
absolute imports (`from app.core...`, `from app.islands.<name>...`); shared
across-island data (registered repos) lives in `app/core/repos.py`; migrations
stay central and numbered.

## Commits

- Author is always martinswdev. Never add a `Co-Authored-By` trailer or any
  co-author line to commits in this repo.
- Commit messages are short (a single summary line, no body unless truly
  needed) and use a conventional-commit-style prefix: `feat:`, `fix:`,
  `chore:`, `refactor:`, `docs:`, `test:`, etc.
