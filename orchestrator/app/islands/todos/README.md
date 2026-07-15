# Todos island (backend)

Read-only Todoist task rollup. It fetches active tasks and projects from the
Todoist REST API v2, joins each task to its project name, and never writes back.

## Layout

| File | Responsibility |
| --- | --- |
| `router.py` | `GET /todos` — normalized active tasks |
| `service.py` | Fetch tasks/projects from Todoist and normalize them |

Response shape (per task):
`{ id, content, project_id, project_name, due, priority, url }`. `due` is an ISO
date or datetime, or `null`; priority is Todoist's `1`–`4` value.

## Config

`TODOIST_API_TOKEN` — a Todoist personal API token. It stays in the orchestrator
and is sent only to Todoist as a bearer token. The endpoint returns `503` when
it is not configured.

## Data

None — stateless; fetched live from Todoist each request.

## Frontend island

`src/islands/todos/` renders this, grouped by project. The island's
`endpoint_base` points at `…/todos`.
