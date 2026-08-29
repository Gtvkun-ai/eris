"""Regression tests cho V78 local-workspace cutover.

Trước V78, session không có ``owner/repo`` kết thúc SSE ngay và client rơi xuống
``/api/chat/send`` direct LLM. Điều đó làm local coding bỏ qua GitPilot team.

Sau V78, nếu session có WorkspaceInfo local thì StreamingAgentExecutor phải chuyển
sang local multi-agent path; chỉ session thật sự không có workspace mới fail rõ.
"""

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
        owner="local",
        repo="repo",
        path=tmp_path,
        branch="main",
        remote_url="",
    )


@pytest.mark.anyio
async def test_local_session_uses_local_team_instead_of_batch_fallback(tmp_path, monkeypatch):
    bus = _RecordingBus()
    executor = StreamingAgentExecutor(bus=bus, gate=object(), workspace=_workspace(tmp_path))
    called = {}

    async def fake_local_team(*, user_message: str, mode: str, topology_id: str):
        called.update(message=user_message, mode=mode, topology_id=topology_id)
        return {"summary": "local team ran"}

    monkeypatch.setattr(executor, "_execute_local_team", fake_local_team)

    result = await executor.execute(
        user_message="fix the bug",
        repo_full_name="",
        topology_id="feature_builder",
    )

    assert result == {"summary": "local team ran"}
    assert called == {
        "message": "fix the bug",
        "mode": "auto",
        "topology_id": "feature_builder",
    }


@pytest.mark.anyio
async def test_repo_less_session_without_workspace_fails_clearly():
    bus = _RecordingBus()
    executor = StreamingAgentExecutor(bus=bus, gate=object(), workspace=None)

    result = await executor.execute(user_message="hi", repo_full_name="")

    assert result is None
    assert EventType.ERROR.value in bus.types()
    assert EventType.DONE.value not in bus.types(), "không được giả vờ task đã hoàn tất"


def test_local_feature_builder_keeps_only_local_engineering_roles():
    sequence = StreamingAgentExecutor._local_sequence("feature_builder", "auto")

    assert sequence[:4] == ["explorer", "planner", "developer", "reviewer"]
    assert "git_agent" not in sequence, "local mode không được tự push/PR"


def test_plan_and_inspect_are_read_only_sequences():
    assert StreamingAgentExecutor._local_sequence("feature_builder", "plan_only") == ["explorer", "planner"]
    assert StreamingAgentExecutor._local_sequence("feature_builder", "inspect") == ["explorer", "reviewer"]
