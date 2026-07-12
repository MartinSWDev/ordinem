import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.islands.todos.router import list_todos
from app.islands.todos.service import TodoistClient


async def test_fetches_projects_and_normalizes_tasks(monkeypatch):
    calls = []

    async def fake_get(self, path):
        calls.append((path, self.headers["Authorization"]))
        payload = (
            [{"id": "project-1", "name": "Ordinem"}]
            if path == "/projects"
            else [
                {
                    "id": "task-1",
                    "content": "Build Todos island",
                    "project_id": "project-1",
                    "due": {"date": "2026-07-13"},
                    "priority": 4,
                    "url": "https://todoist.com/showTask?id=task-1",
                },
                {
                    "id": "task-2",
                    "content": "Review dashboard",
                    "project_id": "missing-project",
                    "due": None,
                    "priority": 1,
                    "url": "https://todoist.com/showTask?id=task-2",
                },
            ]
        )
        request = httpx.Request("GET", f"https://api.todoist.com/rest/v2{path}")
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    tasks = await TodoistClient(Settings(todoist_api_token="secret-token")).tasks()

    assert calls == [
        ("/projects", "Bearer secret-token"),
        ("/tasks", "Bearer secret-token"),
    ]
    assert tasks == [
        {
            "id": "task-1",
            "content": "Build Todos island",
            "project_id": "project-1",
            "project_name": "Ordinem",
            "due": "2026-07-13",
            "priority": 4,
            "url": "https://todoist.com/showTask?id=task-1",
        },
        {
            "id": "task-2",
            "content": "Review dashboard",
            "project_id": "missing-project",
            "project_name": "Unknown project",
            "due": None,
            "priority": 1,
            "url": "https://todoist.com/showTask?id=task-2",
        },
    ]


async def test_unconfigured_token_returns_clear_error():
    with pytest.raises(HTTPException) as exc_info:
        await list_todos(Settings(todoist_api_token=""))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "TODOIST_API_TOKEN is not configured"
