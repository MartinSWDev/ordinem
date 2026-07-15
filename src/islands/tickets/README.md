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

## Ticket sources

Tickets are either **Jira** (`source: "jira"`, synced read-only via
"Sync from Jira", grouped by project key) or **local** (`source: "local"`,
written here via "New ticket", grouped under "Local"). A local ticket has no
`jira_key` and no curated `jira` view, so the Jira-only chrome hides itself;
everything downstream — instructions, agents, review & ship — is identical.

## Plan -> gate -> dispatch

"Propose mini-tickets" asks the planner to decompose the ticket; the proposals
render as an **editable** list that has not run and will not run until you press
Approve. You can rewrite any of them, drop them, or write your own from scratch
— approving is what turns them into real work, and approving nothing rejects the
plan. Each approved mini-ticket then gets its own agent and worktree, in
parallel, except `needs_docker` ones which run one at a time.

Only subtasks past the gate appear under "Agent subtasks"; `proposed` ones stay
in the editor, so a proposal survives reselecting the ticket.

## Wiring

Registered in `src/App.vue` under `component: "tickets"`. The manifest island's
`endpoint_base` points at the orchestrator's `/tickets`. Shared design-system
components come from `src/ui/`; the request plumbing from `src/core/api.ts`.

Backend: `orchestrator/app/islands/tickets/`.
