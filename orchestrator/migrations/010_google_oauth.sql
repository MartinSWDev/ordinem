-- Google Calendar OAuth (read-only) — an alternative calendar source to the
-- private-ICS feed, for calendars where the secret iCal address is disabled.
--
-- Single-user tool, so a single row (id = 'default') holds the token set. The
-- refresh_token is the long-lived credential; access_token is short-lived and
-- refreshed on demand. pending_state carries the CSRF nonce across the redirect.

create table google_oauth (
  id text primary key default 'default',
  refresh_token text,
  access_token text,
  token_expiry timestamptz,
  scopes text,
  pending_state text,
  connected_at timestamptz,
  updated_at timestamptz not null default now()
);
