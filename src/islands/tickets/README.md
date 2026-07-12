# Tickets island (frontend)

The clickable ticket-workflow board: Jira backlog grouped by project → ticket
detail (curated Jira view: comments, acceptance criteria, labels, links, proxied
attachment images) → **process** (launch the agent) → **review & ship** (checks,
commit plan, PR draft).

## Files

| File | Responsibility |
| --- | --- |
| `TicketsIsland.vue` | The whole island UI (master list + detail + process + ship) |
| `api.ts` | `useTickets(island)` — typed calls over the shared `islandClient` |
| `types.ts` | Ticket / Jira / check / commit-plan / PR-draft types |

## Wiring

Registered in `src/App.vue` under `component: "tickets"`. The manifest island's
`endpoint_base` points at the orchestrator's `/tickets`. Shared design-system
components come from `src/ui/`; the request plumbing from `src/core/api.ts`.

Backend: `orchestrator/app/islands/tickets/`.
