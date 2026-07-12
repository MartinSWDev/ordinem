# Calendar island (backend)

Read-only upcoming-events feed. Sources events from one or more **private iCal
(ICS) URLs** — Google Calendar's "Secret address in iCal format" — so there's no
OAuth flow and nothing is ever written back.

## Layout

| File | Responsibility |
| --- | --- |
| `router.py` | `GET /calendar` — normalized upcoming events |
| `service.py` | Fetch + parse the ICS feed(s), expand recurrence, normalize |

Response shape (per event): `{ id, title, start, end, all_day, location, calendar_name }`.

## Config

`CALENDAR_ICS_URLS` — one or more private iCal URLs, comma-separated.

## Data

None — stateless; fetched live from the feed(s) each request.

## Frontend island

`src/islands/calendar/` renders this, grouped by day. The island's `endpoint_base`
points at `…/calendar`.
