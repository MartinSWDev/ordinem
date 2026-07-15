# Review island (backend)

Local pre-PR reviewer: reviews a repo's branch diff against device-global company
semantics (`~/.ordinem/review.md`) plus general best practice. Runs on the work
Mac so code only ever leaves for the LLM you chose (Claude, or the Qwen proxy
fallback).

## Layout

| File | Responsibility |
| --- | --- |
| `router.py` | `/reviews` routes: run a review, fetch a review by id |
| `schemas.py` | `ReviewFinding` / `ReviewResult` / request + row models |
| `repository.py` | The `reviews` log (create / get) |
| `services/git.py` | Read-only branch diff (`git diff --merge-base`) |
| `services/review.py` | Structured-output review via the Anthropic SDK + Qwen fallback |

## Data (see `migrations/004`)

`reviews` (findings JSON), plus `repos.local_path` (the checkout to diff).

## Config

`ANTHROPIC_API_KEY` (or an `ant auth login` session), `REVIEW_MODEL`,
`ANTHROPIC_BASE_URL`, `QWEN_PROXY_URL`. Company semantics: `~/.ordinem/review.md`.

## Frontend island

`src/islands/review/` renders this (repo picker → run review → findings by
severity). The island's `endpoint_base` points at `…/reviews`.
