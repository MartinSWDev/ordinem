from datetime import datetime, timezone

import httpx

from app.core.config import Settings
from app.islands.calendar.service import CalendarClient, parse_ics_events

ICS = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
X-WR-CALNAME:Work\r
BEGIN:VEVENT\r
UID:standup\r
DTSTART:20260713T093000Z\r
DTEND:20260713T100000Z\r
RRULE:FREQ=DAILY;COUNT=4\r
EXDATE:20260715T093000Z\r
SUMMARY:Standup\r
LOCATION:Meet\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:holiday\r
DTSTART;VALUE=DATE:20260714\r
DTEND;VALUE=DATE:20260715\r
SUMMARY:Away\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:later\r
DTSTART:20260801T090000Z\r
DTEND:20260801T100000Z\r
SUMMARY:Too late\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_normalizes_window_all_day_and_recurrence():
    start = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
    events = parse_ics_events(ICS, start, datetime(2026, 7, 26, 12, tzinfo=timezone.utc))
    assert [event["title"] for event in events] == ["Standup", "Standup", "Standup", "Away"]
    assert sum(event["title"] == "Standup" for event in events) == 3
    away = next(event for event in events if event["title"] == "Away")
    assert away["all_day"] is True
    assert away["calendar_name"] == "Work"
    assert events[0]["location"] == "Meet"


async def test_fetches_all_configured_feeds_and_applies_14_day_window(monkeypatch):
    calls = []

    async def fake_get(self, url):
        calls.append(url)
        return httpx.Response(200, content=ICS, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = CalendarClient(Settings(calendar_ics_urls="https://one.test/a.ics, https://two.test/b.ics"))
    events = await client.upcoming(datetime(2026, 7, 12, 12, tzinfo=timezone.utc))
    assert calls == ["https://one.test/a.ics", "https://two.test/b.ics"]
    assert len(events) == 8
    assert all(event["start"] < "2026-07-26T12:00:00+00:00" for event in events)
    assert events == sorted(events, key=lambda event: (event["start"], event["title"]))
