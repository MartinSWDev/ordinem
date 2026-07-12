# Calendar island (frontend)

Read-only upcoming events, grouped by day. Fetches a normalized feed from the
orchestrator's `/calendar` (sourced from private iCal URLs — no OAuth).

## Files

| File | Responsibility |
| --- | --- |
| `CalendarIsland.vue` | The island UI (events grouped by day) |
| `api.ts` | `useCalendar(island)` — the read-only feed call |
| `types.ts` | `CalendarEvent` |

## Wiring

Registered in `src/App.vue` under `component: "calendar"`. Shared design-system
components come from `src/ui/`; the request plumbing from `src/core/api.ts`.

Backend: `orchestrator/app/islands/calendar/`.
