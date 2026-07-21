# Calendar island (backend)

Read-only upcoming-events feed from one of two interchangeable sources:

1. **Private iCal (ICS) URLs** — Google Calendar's "Secret address in iCal
   format". No OAuth; nothing is written back.
2. **Google Calendar via OAuth** (read-only) — for calendars whose secret iCal
   address is disabled. When configured **and** connected it takes precedence;
   otherwise the ICS feeds are used, so switching sources is non-breaking.

## Layout

| File | Responsibility |
| --- | --- |
| `router.py` | `GET /calendar` (source-selecting) + the `/calendar/oauth/*` connect flow |
| `service.py` | ICS fetch/parse/recurrence (`CalendarClient`) and Google API fetch/normalize (`GoogleCalendarClient`) |
| `google_oauth.py` | OAuth 2.0 authorization-code flow + token lifecycle (refresh) |

Response shape (per event): `{ id, title, start, end, all_day, location, calendar_name }`.

## Config

- **ICS**: `CALENDAR_ICS_URLS` — private iCal URLs, comma-separated.
- **Google OAuth**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_OAUTH_REDIRECT_URI` (default `http://127.0.0.1:8787/calendar/oauth/callback`),
  `GOOGLE_CALENDAR_IDS` (comma-separated; `primary` = your main calendar).

## Connect (Google OAuth)

One-time, per machine. In the Google Cloud Console: enable the Calendar API,
create a **Web application** OAuth client with the redirect URI above and the
`calendar.readonly` scope, and set the two secrets in `.env`. Then open
`http://127.0.0.1:8787/calendar/oauth/start` in a browser, approve, and you're
connected. `GET /calendar/oauth/status` reports configured/connected state.

## Data

- ICS source: stateless (fetched live per request).
- OAuth source: the token set persists in the `google_oauth` table
  (`migrations/010`); a single row holds the refresh token, and the short-lived
  access token is refreshed on demand.

## Frontend island

`src/islands/calendar/` renders this, grouped by day. The island's `endpoint_base`
points at `…/calendar`. Connecting Google is a browser visit to `/oauth/start`;
once connected, events flow through the same `GET /calendar` unchanged.
