"""Auto-repo discovery, path-guessing, and the actionable gate."""

from __future__ import annotations

import datetime
from uuid import uuid4

from app.core import repos
from app.islands.tickets import schemas


def _make_repo(tmp_path, name: str) -> None:
    (tmp_path / name / ".git").mkdir(parents=True)


def test_discover_lists_only_git_checkouts(tmp_path):
    _make_repo(tmp_path, "ordinem")
    _make_repo(tmp_path, "jourpath-sites")
    (tmp_path / "not-a-repo").mkdir()  # plain dir, ignored
    (tmp_path / "notes.txt").write_text("x")  # file, ignored

    found = repos.discover_local_repos(str(tmp_path))
    assert [c.name for c in found] == ["jourpath-sites", "ordinem"]
    assert all(c.path.endswith(c.name) for c in found)


def test_discover_missing_base_dir_is_empty(tmp_path):
    assert repos.discover_local_repos(str(tmp_path / "nope")) == []


def test_guess_matches_by_name_case_insensitively(tmp_path):
    _make_repo(tmp_path, "ordinem")
    assert repos.guess_local_path(str(tmp_path), "Ordinem", "ORD") == str(tmp_path / "ordinem")


def test_guess_matches_by_project_key(tmp_path):
    _make_repo(tmp_path, "proj")
    assert repos.guess_local_path(str(tmp_path), "Some Display Name", "PROJ") == str(
        tmp_path / "proj"
    )


def test_guess_returns_none_when_no_match(tmp_path):
    _make_repo(tmp_path, "something-else")
    assert repos.guess_local_path(str(tmp_path), "Ordinem", "ORD") is None


# --- the actionable gate ------------------------------------------------------


def _ticket_row(**over):
    base = dict(
        id=uuid4(), repo_id=uuid4(), jira_project_key="ORD", jira_key="ORD-1",
        source="jira", title="t", description=None, jira=None,
        processing_instructions=None, branch_name=None, status="new",
        created_at=datetime.datetime.now(), updated_at=datetime.datetime.now(),
    )
    base.update(over)
    return schemas.TicketRow(**base)


def test_actionable_requires_a_bound_checkout():
    # repo auto-created but no checkout yet -> not actionable (show the picker)
    assert _ticket_row(repo_local_path=None).actionable is False
    # checkout bound -> actionable
    assert _ticket_row(repo_local_path="/Users/me/Repos/app").actionable is True
    # no repo at all -> not actionable
    assert _ticket_row(repo_id=None, repo_local_path=None).actionable is False
