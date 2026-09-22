"""V105 regression tests for the coordinator-centric local runtime."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gitpilot.agent_events import AgentEventBus, EventType
from gitpilot.approval_protocol import ApprovalGate
from gitpilot.coordinator_runtime import LocalCoordinatorRuntime
from gitpilot.workspace import WorkspaceInfo, WorkspaceManager


class RecordingBus(AgentEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.events = []

    async def emit(self, event) -> None:  # type: ignore[override]
        self.events.append(event)
        await super().emit(event)


def make_repo(tmp_path: Path) -> tuple[WorkspaceInfo, WorkspaceManager]:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    ws = WorkspaceInfo(
        owner="local", repo="demo", path=tmp_path, branch="working-tree", remote_url=""
    )
    return ws, WorkspaceManager(root=tmp_path / ".wm")


@pytest.mark.anyio
async def test_greeting_still_gets_workspace_awareness_before_main_reply(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    seen_prompt = {}

    async def llm(system: str, user: str) -> str:
        seen_prompt["user"] = user
        return '{"kind":"respond","answer":"Chào. Repo đang ở đây rồi.","repo_claims":false,"grounded_in":[]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws,
        bus=bus,
        gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager,
        llm_call=llm,
    )
    result = await runtime.run("xin chào")

    assert result["pipeline"] == "coordinator_loop_v4"
    assert "EVIDENCE COUNT: 2" in seen_prompt["user"]
    assert "workspace_map" in seen_prompt["user"]
    assert all(e.type is not EventType.PHASE_SUMMARY for e in bus.events)
    assert result["summary"] == "Chào. Repo đang ở đây rồi."


@pytest.mark.anyio
async def test_repo_claim_without_real_evidence_id_is_rejected_and_loop_continues(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    calls = 0

    async def llm(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return '{"kind":"respond","answer":"Bug chắc chắn ở app.py","repo_claims":true,"grounded_in":["e999"]}'
        if calls == 2:
            return '{"kind":"continue","actions":[{"type":"read","paths":["src/app.py"]}]}'
        return '{"kind":"respond","answer":"Đã đọc app.py trước khi kết luận.","repo_claims":true,"grounded_in":["e4"]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws, bus=bus, gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager, llm_call=llm,
    )
    result = await runtime.run("bug nằm đâu?")

    assert calls == 3
    assert result["summary"] == "Đã đọc app.py trước khi kết luận."
    assert result["metadata"]["turns"] == 3


@pytest.mark.anyio
async def test_main_can_spawn_more_than_four_subagents_and_scheduler_only_caps_concurrency(tmp_path: Path, monkeypatch):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    monkeypatch.setenv("GITPILOT_COORDINATOR_PARALLELISM", "2")
    main_calls = 0
    active = 0
    peak = 0
    completed = 0

    async def llm(system: str, user: str) -> str:
        nonlocal main_calls, active, peak, completed
        if "PRIVATE READ-ONLY research subagent" in system:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            completed += 1
            return '{"kind":"report","summary":"nhánh đã kiểm tra","claims":[],"new_frontiers":[]}'

        main_calls += 1
        if main_calls == 1:
            jobs = ",".join(
                '{"label":"branch-%d","goal":"check branch %d","hint_paths":["src/app.py"],"search_terms":[]}' % (i, i)
                for i in range(7)
            )
            return '{"kind":"continue","actions":[{"type":"delegate","jobs":[' + jobs + ']}]}'
        if main_calls == 2:
            return '{"kind":"continue","actions":[{"type":"await_subagents","job_ids":[]}]}'
        return '{"kind":"respond","answer":"Đã gom các nhánh nghiên cứu.","repo_claims":true,"grounded_in":["e4"]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws, bus=bus, gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager, llm_call=llm,
    )
    result = await runtime.run("điều tra nhiều nhánh")

    assert completed == 7, "logical subagent count must not be fixed at four"
    assert peak == 2, "provider concurrency is a resource cap, not a cognitive cap"
    assert result["metadata"]["subagent_reports"] == 7


@pytest.mark.anyio
async def test_coordinator_has_no_fixed_twelve_turn_stop(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    calls = 0

    async def llm(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        if calls <= 14:
            return '{"kind":"continue","actions":[{"type":"git_status"}]}'
        return '{"kind":"respond","answer":"Đủ context sau vòng dài.","repo_claims":false,"grounded_in":[]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws, bus=bus, gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager, llm_call=llm,
    )
    result = await runtime.run("điều tra đến khi đủ")

    assert result["metadata"]["turns"] == 15
    assert result["summary"] == "Đủ context sau vòng dài."


@pytest.mark.anyio
async def test_background_reviewer_does_not_block_main_loop(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    main_calls = 0
    reviewer_started = asyncio.Event()
    reviewer_finished = asyncio.Event()
    main_observed_reviewer_running = False

    async def llm(system: str, user: str) -> str:
        nonlocal main_calls, main_observed_reviewer_running
        if "PRIVATE READ-ONLY research subagent" in system:
            reviewer_started.set()
            await asyncio.sleep(0.05)
            reviewer_finished.set()
            return '{"kind":"report","summary":"review xong","claims":[],"new_frontiers":[]}'

        main_calls += 1
        if main_calls == 1:
            return '{"kind":"continue","actions":[{"type":"delegate","jobs":[{"label":"review","goal":"review code","hint_paths":["src/app.py"]}]}]}'
        if main_calls == 2:
            # Nhường event loop một nhịp: Main vẫn đang ở turn kế tiếp trong khi
            # reviewer chạy nền, không await report của nó.
            await asyncio.sleep(0.005)
            main_observed_reviewer_running = reviewer_started.is_set() and not reviewer_finished.is_set()
            return '{"kind":"continue","actions":[{"type":"git_status"}]}'
        if main_calls == 3:
            return '{"kind":"continue","actions":[{"type":"await_subagents","job_ids":[]}]}'
        return '{"kind":"respond","answer":"Main đã nhận review.","repo_claims":true,"grounded_in":["e4"]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws, bus=bus, gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager, llm_call=llm,
    )
    result = await runtime.run("review ngầm")

    assert main_observed_reviewer_running is True
    assert result["summary"] == "Main đã nhận review."


@pytest.mark.anyio
async def test_only_main_answer_is_streamed_not_private_subagent_report(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    main_calls = 0

    async def llm(system: str, user: str) -> str:
        nonlocal main_calls
        if "PRIVATE READ-ONLY research subagent" in system:
            return '{"kind":"report","summary":"SECRET INTERNAL REPORT","claims":[],"new_frontiers":[]}'
        main_calls += 1
        if main_calls == 1:
            return '{"kind":"continue","actions":[{"type":"delegate","jobs":[{"label":"x","goal":"inspect","hint_paths":["src/app.py"]}]}]}'
        if main_calls == 2:
            return '{"kind":"continue","actions":[{"type":"await_subagents","job_ids":[]}]}'
        return '{"kind":"respond","answer":"Public answer only.","repo_claims":true,"grounded_in":["e4"]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws, bus=bus, gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager, llm_call=llm,
    )
    await runtime.run("inspect")

    visible = "".join(e.data.get("text", "") for e in bus.events if e.type is EventType.TEXT_DELTA)
    assert visible == "Public answer only."
    assert "SECRET INTERNAL REPORT" not in visible
    assert all(e.type is not EventType.PHASE_SUMMARY for e in bus.events)

@pytest.mark.anyio
async def test_v105_persistent_main_reuses_repo_map_and_investigation_graph(tmp_path: Path):
    """Executor có thể chết giữa HTTP turn nhưng Main memory không reset về số 0."""
    ws, manager = make_repo(tmp_path)
    bus1 = RecordingBus()
    calls1 = 0

    async def llm1(system: str, user: str) -> str:
        nonlocal calls1
        calls1 += 1
        if calls1 == 1:
            return '{"kind":"continue","graph":{"frontiers":[{"topic":"trace hello caller","priority":0.8}]},"actions":[{"type":"read","paths":["src/app.py"]}]}'
        return '{"kind":"respond","answer":"Đã hiểu app.py.","repo_claims":true,"grounded_in":["e3"],"graph":{"claims":[{"statement":"hello() returns hi","confidence":0.95,"evidence":["e3"],"status":"supported"}]}}'

    first = LocalCoordinatorRuntime(
        workspace=ws, bus=bus1, gate=ApprovalGate(bus1, mode="auto"),
        ws_manager=manager, llm_call=llm1,
    )
    result1 = await first.run("đọc app")
    memory = dict(first.memory_snapshot)
    assert result1["metadata"]["persistent_claims"] == 1
    assert result1["metadata"]["persistent_frontiers"] == 1

    bus2 = RecordingBus()
    seen = {}

    async def llm2(system: str, user: str) -> str:
        seen["prompt"] = user
        return '{"kind":"respond","answer":"Tôi vẫn nhớ nhánh điều tra trước.","repo_claims":false,"grounded_in":[]}'

    second = LocalCoordinatorRuntime(
        workspace=ws, bus=bus2, gate=ApprovalGate(bus2, mode="auto"),
        ws_manager=manager, llm_call=llm2, memory=memory,
        conversation_messages=[
            {"role":"user","content":"đọc app"},
            {"role":"assistant","content":"Đã hiểu app.py."},
        ],
    )
    await second.run("còn nhớ không?")

    assert "hello() returns hi" in seen["prompt"]
    assert "trace hello caller" in seen["prompt"]
    assert "RECENT SESSION CONVERSATION" in seen["prompt"]
    # Revision không đổi => map persistent được tái sử dụng thay vì coi Main như turn đầu.
    assert "workspace_map_cache" in seen["prompt"]


@pytest.mark.anyio
async def test_generic_workspace_metadata_cannot_ground_detailed_repo_claim(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    bus = RecordingBus()
    calls = 0

    async def llm(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            # e1/e2 chỉ là status/map: không đủ chứng minh implementation claim.
            return '{"kind":"respond","answer":"hello chắc chắn trả bye","repo_claims":true,"grounded_in":["e1"]}'
        if calls == 2:
            return '{"kind":"continue","actions":[{"type":"read","paths":["src/app.py"]}]}'
        return '{"kind":"respond","answer":"hello trả hi theo source.","repo_claims":true,"grounded_in":["e4"]}'

    runtime = LocalCoordinatorRuntime(
        workspace=ws, bus=bus, gate=ApprovalGate(bus, mode="auto"),
        ws_manager=manager, llm_call=llm,
    )
    result = await runtime.run("hello trả gì?")
    assert calls == 3
    assert result["summary"] == "hello trả hi theo source."
