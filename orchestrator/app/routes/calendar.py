"""Read-only calendar feed route."""

from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings
from ..deps import get_config
from ..services.calendar import CalendarClient, CalendarError

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("")
async def upcoming_events(settings: Settings = Depends(get_config)) -> list[dict]:
    if not settings.calendar_urls:
        raise HTTPException(status_code=503, detail="CALENDAR_ICS_URLS is not configured")
    try:
        return await CalendarClient(settings).upcoming()
    except CalendarError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
