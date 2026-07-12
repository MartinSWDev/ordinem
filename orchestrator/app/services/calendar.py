"""Read-only iCal feed aggregation and recurrence expansion."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from dateutil.rrule import rrulestr
from icalendar import Calendar

from ..config import Settings


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
    """Fetch configured ICS feeds. TODO: add an interchangeable Google OAuth source."""

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
