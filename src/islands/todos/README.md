# Todos island (frontend)

Read-only active Todoist tasks, grouped by project with due dates and Todoist
priority. Selecting a task opens it in Todoist; completion is intentionally not
part of v1.

## Files

| File | Responsibility |
| --- | --- |
| `TodosIsland.vue` | The neumorphic project-grouped task UI |
| `api.ts` | `useTodos(island)` — the read-only task call |
| `types.ts` | `TodoTask` |

## Wiring

Registered in `src/App.vue` under `component: "todos"`. Shared design-system
components come from `src/ui/`; request plumbing comes from `src/core/api.ts`.
The Todoist token never enters the frontend.

Backend: `orchestrator/app/islands/todos/`.
