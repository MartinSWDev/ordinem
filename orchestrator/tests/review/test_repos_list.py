"""GET /reviews/repos lists registered repos (repo picker source)."""

from __future__ import annotations

import types
from uuid import uuid4

from app.core import repos as repos_mod


async def test_list_repos_maps_rows(monkeypatch):
    r1 = {"id": uuid4(), "name": "a", "jira_project_key": "A", "git_remote_url": "g",
          "docker_compose_path": None, "local_path": "/x", "default_branch": "main",
          "created_at": __import__("datetime").datetime.now()}

    class FakeConn:
        async def fetch(self, q):
            return [r1]

    out = await repos_mod.list_repos(FakeConn())
    assert len(out) == 1
    assert out[0].name == "a"
    assert out[0].local_path == "/x"
