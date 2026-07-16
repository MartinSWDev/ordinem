"""Dispatch backends: stream classification, availability probing, and the
fix-it messages a missing CLI produces."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.islands.tickets.services import backends as backends_mod
from app.islands.tickets.services.backends import (
    BackendUnavailable,
    build_backend,
    classify_line,
    list_backends,
)


def _settings(**over) -> Settings:
    base = dict(_env_file=None)
    base.update(over)
    return Settings(**base)


# --- stream-json classification ----------------------------------------------


def test_result_success_is_stop():
    event, _ = classify_line({"type": "result", "subtype": "success"})
    assert event == "stop"


def test_result_error_is_stop_failure():
    for line in (
        {"type": "result", "subtype": "error_during_execution"},
        {"type": "result", "subtype": "success", "is_error": True},
        {"type": "result", "subtype": "error_max_turns"},
    ):
        event, _ = classify_line(line)
        assert event == "stop_failure", line


def test_assistant_tool_use_vs_message():
    tool = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    text = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
    assert classify_line(tool)[0] == "tool_use"
    assert classify_line(text)[0] == "message"


def test_user_turn_is_tool_result_and_unknown_is_message():
    assert classify_line({"type": "user", "message": {}})[0] == "tool_result"
    assert classify_line({"type": "wat"})[0] == "message"
    assert classify_line({})[0] == "message"


# --- backend construction ------------------------------------------------------


def test_missing_cli_raises_with_install_hint(monkeypatch):
    monkeypatch.setattr(backends_mod.shutil, "which", lambda _: None)
    with pytest.raises(BackendUnavailable, match="install Claude Code"):
        build_backend(_settings(), "claude")
    with pytest.raises(BackendUnavailable, match="Cursor CLI"):
        build_backend(_settings(), "cursor")


def test_local_requires_proxy_url(monkeypatch):
    monkeypatch.setattr(backends_mod.shutil, "which", lambda c: f"/usr/bin/{c}")
    with pytest.raises(BackendUnavailable, match="LOCAL_PROXY_URL"):
        build_backend(_settings(), "local")


def test_local_falls_back_to_qwen_proxy_url(monkeypatch):
    monkeypatch.setattr(backends_mod.shutil, "which", lambda c: f"/usr/bin/{c}")
    backend = build_backend(_settings(qwen_proxy_url="http://qwen.local"), "local")
    assert backend.env_overrides["ANTHROPIC_BASE_URL"] == "http://qwen.local"


def test_claude_backend_bills_subscription_not_api_key(monkeypatch):
    """The whole point of the claude backend: the CLI's subscription login,
    never the orchestrator's API key or base-url override."""
    monkeypatch.setattr(backends_mod.shutil, "which", lambda c: f"/usr/bin/{c}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://somewhere")
    backend = build_backend(_settings(), "claude")
    env = backend._env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_BASE_URL" not in env


def test_unknown_backend_rejected():
    with pytest.raises(BackendUnavailable, match="unknown backend"):
        build_backend(_settings(), "gpt")


# --- availability listing -------------------------------------------------------


async def test_list_backends_reports_unavailable_with_reason(monkeypatch):
    monkeypatch.setattr(backends_mod.shutil, "which", lambda _: None)
    out = await list_backends(_settings())
    assert [b.name for b in out] == ["claude", "cursor", "local"]
    assert all(not b.available for b in out)
    assert all(b.detail for b in out)


async def test_list_backends_probes_local_proxy(monkeypatch):
    monkeypatch.setattr(backends_mod.shutil, "which", lambda c: f"/usr/bin/{c}")

    async def dead_proxy(settings):
        return "proxy at http://x not responding (ConnectError)"

    monkeypatch.setattr(backends_mod, "_local_proxy_alive", dead_proxy)
    out = await list_backends(_settings(local_proxy_url="http://x"))
    by_name = {b.name: b for b in out}
    assert by_name["claude"].available
    assert by_name["cursor"].available
    assert not by_name["local"].available
    assert "not responding" in (by_name["local"].detail or "")
