"""Git diff + review orchestration (LLM call mocked)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.islands.review.services import review as review_svc
from app.islands.review.services.git import branch_diff, current_branch


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _init_repo(path: Path) -> None:
    _run("git", "init", "-q", "-b", "main", cwd=path)
    _run("git", "config", "user.email", "t@example.com", cwd=path)
    _run("git", "config", "user.name", "t", cwd=path)
    (path / "a.txt").write_text("hello\n")
    _run("git", "add", ".", cwd=path)
    _run("git", "commit", "-q", "-m", "base", cwd=path)


async def test_branch_diff_shows_branch_changes(tmp_path):
    _init_repo(tmp_path)
    _run("git", "checkout", "-q", "-b", "feature", cwd=tmp_path)
    (tmp_path / "a.txt").write_text("hello world\n")
    _run("git", "commit", "-qam", "change", cwd=tmp_path)

    assert (await current_branch(str(tmp_path))) == "feature"
    diff = await branch_diff(str(tmp_path), "main", "HEAD")
    assert "hello world" in diff
    assert "a.txt" in diff


async def test_branch_diff_empty_when_no_changes(tmp_path):
    _init_repo(tmp_path)
    diff = await branch_diff(str(tmp_path), "main", "HEAD")
    assert diff.strip() == ""


def _settings(**kw) -> Settings:
    return Settings(anthropic_api_key="k", **kw)


async def test_run_review_wraps_result(monkeypatch):
    async def fake_call(client, model, system, diff):
        return {
            "summary": "looks ok",
            "findings": [
                {"file": "a.py", "line": 3, "severity": "high", "category": "correctness",
                 "comment": "off by one", "suggestion": "use <="},
            ],
        }

    monkeypatch.setattr(review_svc, "_call", fake_call)
    result = await review_svc.run_review("diff", "be nice", _settings())
    assert result.summary == "looks ok"
    assert result.findings[0].severity == "high"


async def test_run_review_falls_back_to_qwen(monkeypatch):
    calls: list[str | None] = []

    async def fake_call(client, model, system, diff):
        # base_url lives on the client; record it to prove which endpoint ran
        base = str(getattr(client, "base_url", ""))
        calls.append(base)
        if len(calls) == 1:
            raise RuntimeError("rate limited")
        return {"summary": "via qwen", "findings": []}

    monkeypatch.setattr(review_svc, "_call", fake_call)
    result = await review_svc.run_review(
        "diff", None, _settings(qwen_proxy_url="http://qwen.local")
    )
    assert result.summary == "via qwen"
    assert len(calls) == 2
    assert "qwen.local" in calls[1]


async def test_run_review_reraises_without_qwen(monkeypatch):
    async def fake_call(client, model, system, diff):
        raise RuntimeError("boom")

    monkeypatch.setattr(review_svc, "_call", fake_call)
    with pytest.raises(RuntimeError):
        await review_svc.run_review("diff", None, _settings())
