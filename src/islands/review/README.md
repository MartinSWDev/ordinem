# Review island (frontend)

The pre-PR reviewer UI: pick a registered repo, optionally set base/head
branches, run a review, and read the findings grouped by severity. The review
runs entirely on the machine (code only ever goes to the configured LLM).

## Files

| File | Responsibility |
| --- | --- |
| `ReviewIsland.vue` | Repo picker + branch inputs + run button + findings (grouped high/medium/low) |
| `api.ts` | `useReview(island)` — `listRepos` / `runReview` / `getReview` over `islandClient` |
| `types.ts` | `RepoRef` / `ReviewFinding` / `ReviewResult` / `Review` |

## Wiring

Registered in `src/App.vue` under `component: "review"`. The manifest island's
`endpoint_base` points at the orchestrator's `/reviews`. Repos come from
`GET /reviews/repos`; a repo needs a registered `local_path` to be reviewable.

Backend: `orchestrator/app/islands/review/`.
