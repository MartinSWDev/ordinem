"""Read-only Todoist task and project aggregation."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings

TODOIST_API_BASE = "https://api.todoist.com/rest/v2"


class TodoistError(RuntimeError):
    pass


class TodoistClient:
    """Fetch and normalize active Todoist tasks without writing to Todoist."""

    def __init__(self, settings: Settings):
        self.token = settings.todoist_api_token

    async def tasks(self) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with httpx.AsyncClient(
                base_url=TODOIST_API_BASE, headers=headers, timeout=10.0
            ) as client:
                projects_response = await client.get("/projects")
                projects_response.raise_for_status()
                tasks_response = await client.get("/tasks")
                tasks_response.raise_for_status()
                projects = projects_response.json()
                tasks = tasks_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TodoistError(f"Todoist request failed: {exc}") from exc

        project_names = {str(project["id"]): project["name"] for project in projects}
        return [self._normalize(task, project_names) for task in tasks]

    @staticmethod
    def _normalize(
        task: dict[str, Any], project_names: dict[str, str]
    ) -> dict[str, Any]:
        project_id = str(task.get("project_id", ""))
        due = task.get("due") or {}
        return {
            "id": str(task["id"]),
            "content": task.get("content", ""),
            "project_id": project_id,
            "project_name": project_names.get(project_id, "Unknown project"),
            "due": due.get("datetime") or due.get("date"),
            "priority": task.get("priority", 1),
            "url": task.get("url", ""),
        }
