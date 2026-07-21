"""Read-only iCal feed aggregation and recurrence expansion."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from dateutil.rrule import rrulestr
from icalendar import Calendar

from app.core.config import Settings


class CalendarError(RuntimeError):
    pass


def _aware(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _text(component: Any, key: str, default: str = "") -> str:
    value = component.get(key)
    return str(value) if value is not None else default


def parse_ics_events(
    payload: bytes | str, window_start: datetime, window_end: datetime
) -> list[dict[str, Any]]:
    """Normalize VEVENTs whose occurrences overlap the half-open window."""
    window_start, window_end = _aware(window_start), _aware(window_end)
    calendar = Calendar.from_ical(payload)
    calendar_name = _text(calendar, "X-WR-CALNAME", "Calendar")
    events: list[dict[str, Any]] = []

    for component in calendar.walk("VEVENT"):
        raw_start = component.decoded("DTSTART")
        start = _aware(raw_start)
        all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)

        if component.get("DTEND") is not None:
            end = _aware(component.decoded("DTEND"))
        elif component.get("DURATION") is not None:
            end = start + component.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(0))
        duration = end - start

        starts = [start]
        if component.get("RRULE") is not None:
            rule = component.get("RRULE").to_ical().decode()
            # Include occurrences beginning before the window when they overlap it.
            starts = list(rrulestr(rule, dtstart=start).between(
                window_start - max(duration, timedelta(0)), window_end, inc=True
            ))

        excluded: set[datetime] = set()
        exdates = component.get("EXDATE")
        if exdates is not None:
            for entry in exdates if isinstance(exdates, list) else [exdates]:
                excluded.update(_aware(item.dt) for item in entry.dts)

        uid = _text(component, "UID", "event")
        for occurrence_start in starts:
            occurrence_start = _aware(occurrence_start)
            occurrence_end = occurrence_start + duration
            if occurrence_start in excluded:
                continue
            if occurrence_start >= window_end or occurrence_end <= window_start:
                continue
            events.append({
                "id": f"{uid}:{occurrence_start.isoformat()}",
                "title": _text(component, "SUMMARY", "Untitled event"),
                "start": occurrence_start.isoformat(),
                "end": occurrence_end.isoformat(),
                "all_day": all_day,
                "location": _text(component, "LOCATION") or None,
                "calendar_name": calendar_name,
            })
    return events


class CalendarClient:
    """Fetch and aggregate the configured private-ICS feeds."""

    def __init__(self, settings: Settings):
        self.urls = settings.calendar_urls

    async def upcoming(self, now: datetime | None = None, days: int = 14) -> list[dict[str, Any]]:
        start = _aware(now or datetime.now(timezone.utc))
        end = start + timedelta(days=days)
        events: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for url in self.urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    events.extend(parse_ics_events(response.content, start, end))
                except (httpx.HTTPError, ValueError) as exc:
                    raise CalendarError(f"calendar feed failed: {exc}") from exc
        return sorted(events, key=lambda event: (event["start"], event["title"]))


def normalize_google_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map one Google Calendar `events.list` response to the island's event
    shape. The response's top-level `summary` is the calendar's name; each
    item's start/end is either `dateTime` (timed) or `date` (all-day)."""
    calendar_name = payload.get("summary") or "Calendar"
    events: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        if item.get("status") == "cancelled":
            continue
        start_raw = item.get("start") or {}
        end_raw = item.get("end") or {}
        all_day = "date" in start_raw
        start = _aware(_parse_google_time(start_raw))
        end = _aware(_parse_google_time(end_raw)) if end_raw else start
        events.append(
            {
                "id": item.get("id", "event"),
                "title": item.get("summary") or "Untitled event",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "all_day": all_day,
                "location": item.get("location") or None,
                "calendar_name": calendar_name,
            }
        )
    return events


def _parse_google_time(node: dict[str, Any]) -> datetime:
    """A Google start/end node: `dateTime` (RFC3339) or all-day `date`."""
    if node.get("dateTime"):
        return datetime.fromisoformat(node["dateTime"])
    return datetime.fromisoformat(node["date"])  # date-only -> midnight, made aware upstream


class GoogleCalendarClient:
    """Read upcoming events via the Google Calendar API, using the OAuth token
    managed in google_oauth.py. Drop-in for CalendarClient (same upcoming())."""

    def __init__(self, pool, settings: Settings):
        self._pool = pool
        self._settings = settings

    async def upcoming(self, now: datetime | None = None, days: int = 14) -> list[dict[str, Any]]:
        from app.islands.calendar import google_oauth

        start = _aware(now or datetime.now(timezone.utc))
        end = start + timedelta(days=days)
        try:
            token = await google_oauth.valid_access_token(self._pool, self._settings)
        except google_oauth.GoogleOAuthError as exc:
            raise CalendarError(str(exc)) from exc

        events: list[dict[str, Any]] = []
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            for cal_id in self._settings.google_calendar_id_list:
                url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"
                try:
                    resp = await client.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    events.extend(normalize_google_events(resp.json()))
                except (httpx.HTTPError, ValueError) as exc:
                    raise CalendarError(f"google calendar '{cal_id}' failed: {exc}") from exc
        return sorted(events, key=lambda event: (event["start"], event["title"]))
