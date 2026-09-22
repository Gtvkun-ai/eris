"""Regression tests for V104 local-workspace coordinator cutover."""
from __future__ import annotations

from pathlib import Path

import pytest

from gitpilot.agent_events import AgentEventBus, EventType
from gitpilot.agent_executor import StreamingAgentExecutor
from gitpilot.workspace import WorkspaceInfo


class _RecordingBus(AgentEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list = []

    async def emit(self, event) -> None:  # type: ignore[override]
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type.value if hasattr(e.type, "value") else str(e.type) for e in self.events]


def _workspace(tmp_path: Path) -> WorkspaceInfo:
    return WorkspaceInfo(
        owner="local", repo="repo", path=tmp_path, branch="main", remote_url="",
    )


@pytest.mark.anyio
async def test_local_session_uses_main_coordinator_not_fixed_team(tmp_path, monkeypatch):
    bus = _RecordingBus()
    executor = StreamingAgentExecutor(bus=bus, gate=object(), workspace=_workspace(tmp_path))
    called = {}

    async def fake_coordinator(*, user_message: str, mode: str):
        called.update(message=user_message, mode=mode)
        return {"summary": "coordinator ran", "pipeline": "coordinator_loop_v2"}

    async def forbidden_team(**kwargs):
        raise AssertionError("legacy Explorer->Planner->Developer->Reviewer must not be the default path")

    monkeypatch.setattr(executor, "_execute_local_coordinator", fake_coordinator)
    monkeypatch.setattr(executor, "_execute_local_team", forbidden_team)

    result = await executor.execute(user_message="fix the bug", repo_full_name="")

    assert result == {"summary": "coordinator ran", "pipeline": "coordinator_loop_v2"}
    assert called == {"message": "fix the bug", "mode": "auto"}


@pytest.mark.anyio
async def test_greeting_also_enters_coordinator_in_local_workspace(tmp_path, monkeypatch):
    bus = _RecordingBus()
    executor = StreamingAgentExecutor(bus=bus, gate=object(), workspace=_workspace(tmp_path))
    called = []

    async def fake_coordinator(*, user_message: str, mode: str):
        called.append(user_message)
        return {"summary": "hello with awareness", "pipeline": "coordinator_loop_v2"}

    monkeypatch.setattr(executor, "_execute_local_coordinator", fake_coordinator)
    result = await executor.execute(user_message="xin chào", repo_full_name="")

    assert result["pipeline"] == "coordinator_loop_v2"
    assert called == ["xin chào"]


@pytest.mark.anyio
async def test_coordinator_failure_emits_error_instead_of_hanging_stream(tmp_path, monkeypatch):
    bus = _RecordingBus()
    executor = StreamingAgentExecutor(bus=bus, gate=object(), workspace=_workspace(tmp_path))

    async def broken_coordinator(*, user_message: str, mode: str):
        raise RuntimeError("Coordinator failed")

    monkeypatch.setattr(executor, "_execute_local_coordinator", broken_coordinator)
    result = await executor.execute(user_message="xin chao", repo_full_name="")

    assert result is None
    assert EventType.ERROR.value in bus.types()
    assert "Coordinator failed" in bus.events[-1].data["error"]
    assert EventType.DONE.value not in bus.types()


@pytest.mark.anyio
async def test_repo_less_session_without_workspace_fails_clearly():
    bus = _RecordingBus()
    executor = StreamingAgentExecutor(bus=bus, gate=object(), workspace=None)

    result = await executor.execute(user_message="hi", repo_full_name="")

    assert result is None
    assert EventType.ERROR.value in bus.types()
    assert EventType.DONE.value not in bus.types()


def test_legacy_local_sequence_is_retained_only_for_rollback_compatibility():
    sequence = StreamingAgentExecutor._local_sequence("feature_builder", "auto")
    assert sequence[:4] == ["explorer", "planner", "developer", "reviewer"]
    assert "git_agent" not in sequence
