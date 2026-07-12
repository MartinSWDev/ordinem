"""Read-only Todoist routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings
from app.core.deps import get_config
from app.islands.todos.service import TodoistClient, TodoistError

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("")
async def list_todos(settings: Settings = Depends(get_config)) -> list[dict]:
    if not settings.todoist_configured:
        raise HTTPException(status_code=503, detail="TODOIST_API_TOKEN is not configured")
    try:
        return await TodoistClient(settings).tasks()
    except TodoistError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
