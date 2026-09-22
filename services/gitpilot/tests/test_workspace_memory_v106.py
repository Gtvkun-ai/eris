"""V106 workspace-scoped long-term coordinator memory regression tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from gitpilot.agent_events import AgentEventBus
from gitpilot.approval_protocol import ApprovalGate
from gitpilot.coordinator.state import CoordinatorMemory, Evidence
from gitpilot.coordinator.workspace_memory import WorkspaceMemoryStore
from gitpilot.coordinator_runtime import LocalCoordinatorRuntime
from gitpilot.workspace import WorkspaceInfo, WorkspaceManager


class RecordingBus(AgentEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.events = []

    async def emit(self, event) -> None:  # type: ignore[override]
        self.events.append(event)
        await super().emit(event)


def make_repo(tmp_path: Path, name: str = "demo") -> tuple[WorkspaceInfo, WorkspaceManager]:
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    ws = WorkspaceInfo(
        owner="local", repo=name, path=root, branch="working-tree", remote_url=""
    )
    return ws, WorkspaceManager(root=tmp_path / f".wm-{name}")


@pytest.mark.anyio
async def test_new_session_reuses_workspace_context_without_session_blob(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    store = WorkspaceMemoryStore(root=tmp_path / "memory")
    first_calls = 0

    async def first_llm(system: str, user: str) -> str:
        nonlocal first_calls
        first_calls += 1
        if first_calls == 1:
            return '{"kind":"continue","graph":{"frontiers":[{"topic":"trace hello caller","priority":0.9}]},"actions":[{"type":"read","paths":["src/app.py"]}]}'
        return '{"kind":"respond","answer":"Đã hiểu app.py.","repo_claims":true,"grounded_in":["e3"],"graph":{"claims":[{"statement":"hello() returns hi","confidence":0.97,"evidence":["e3"],"status":"supported"}]}}'

    bus1 = RecordingBus()
    first = LocalCoordinatorRuntime(
        workspace=ws,
        bus=bus1,
        gate=ApprovalGate(bus1, mode="auto"),
        ws_manager=manager,
        llm_call=first_llm,
        workspace_memory_store=store,
    )
    await first.run("đọc app")

    # Brand-new runtime + no session memory. Durable workspace memory alone must
    # restore the repo model.
    seen = {}

    async def second_llm(system: str, user: str) -> str:
        seen["prompt"] = user
        return '{"kind":"respond","answer":"Tôi nhớ workspace này.","repo_claims":false,"grounded_in":[]}'

    bus2 = RecordingBus()
    second = LocalCoordinatorRuntime(
        workspace=ws,
        bus=bus2,
        gate=ApprovalGate(bus2, mode="auto"),
        ws_manager=manager,
        llm_call=second_llm,
        workspace_memory_store=store,
        memory=None,
        conversation_messages=[],
    )
    result = await second.run("còn nhớ repo không?")

    assert result["summary"] == "Tôi nhớ workspace này."
    assert "hello() returns hi" in seen["prompt"]
    assert "trace hello caller" in seen["prompt"]
    assert "workspace_map_cache" in seen["prompt"]
    assert "Loaded reusable long-term context" in seen["prompt"]
    assert "WORKSPACE LONG-TERM HISTORY" in seen["prompt"]
    assert "đọc app" in seen["prompt"]


def test_workspace_identity_is_scoped_to_exact_working_tree(tmp_path: Path):
    ws1, _ = make_repo(tmp_path, "a")
    ws2, _ = make_repo(tmp_path, "b")
    store = WorkspaceMemoryStore(root=tmp_path / "memory")
    assert store.identity_for(ws1).key != store.identity_for(ws2).key


def test_merge_rewrites_colliding_evidence_ids_and_claim_refs():
    left = CoordinatorMemory()
    e1 = Evidence(id="e1", kind="file", source="a.py", summary="left", detail="A", revision="r1")
    left.remember_evidence(e1)
    left.next_evidence_seq = 1
    left.graph.add_claim("left claim", confidence=0.9, evidence_ids=["e1"], status="supported")

    right = CoordinatorMemory()
    other = Evidence(id="e1", kind="file", source="b.py", summary="right", detail="B", revision="r1")
    right.remember_evidence(other)
    right.next_evidence_seq = 1
    right.graph.add_claim("right claim", confidence=0.9, evidence_ids=["e1"], status="supported")

    left.merge_from(right)

    assert len(left.evidence_digest) == 2
    right_claim = next(c for c in left.graph.claims.values() if c.statement == "right claim")
    assert right_claim.evidence_ids != ["e1"]
    assert right_claim.evidence_ids[0] in {x["id"] for x in left.evidence_digest}


def test_compaction_keeps_evidence_referenced_by_supported_claim():
    memory = CoordinatorMemory()
    for i in range(12):
        item = Evidence(
            id=f"e{i+1}", kind="file", source=f"f{i}.py", summary=f"s{i}",
            detail="x", revision="r1", created_at=float(i),
        )
        memory.remember_evidence(item)
        memory.next_evidence_seq = i + 1
    memory.graph.add_claim(
        "important old claim", confidence=0.95, evidence_ids=["e1"], status="supported"
    )

    memory.compact(max_evidence=3, max_claims=10)
    ids = {x["id"] for x in memory.evidence_digest}
    assert "e1" in ids
    assert {"e11", "e12"}.issubset(ids)


@pytest.mark.anyio
async def test_revision_change_stales_durable_claim_before_reuse(tmp_path: Path):
    ws, manager = make_repo(tmp_path)
    store = WorkspaceMemoryStore(root=tmp_path / "memory")
    calls = 0

    async def first_llm(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return '{"kind":"continue","actions":[{"type":"read","paths":["src/app.py"]}]}'
        return '{"kind":"respond","answer":"hi","repo_claims":true,"grounded_in":["e3"],"graph":{"claims":[{"statement":"hello returns hi","confidence":0.99,"evidence":["e3"],"status":"supported"}]}}'

    bus1 = RecordingBus()
    first = LocalCoordinatorRuntime(
        workspace=ws, bus=bus1, gate=ApprovalGate(bus1, mode="auto"),
        ws_manager=manager, llm_call=first_llm, workspace_memory_store=store,
    )
    await first.run("đọc")

    # Change the working tree. The next runtime must remember the claim but mark
    # it stale before Main is allowed to use it as current proof.
    (ws.path / "src" / "app.py").write_text("def hello():\n    return 'bye'\n", encoding="utf-8")
    seen = {}

    async def second_llm(system: str, user: str) -> str:
        seen["prompt"] = user
        return '{"kind":"respond","answer":"Tôi sẽ xác minh lại khi cần.","repo_claims":false,"grounded_in":[]}'

    bus2 = RecordingBus()
    second = LocalCoordinatorRuntime(
        workspace=ws, bus=bus2, gate=ApprovalGate(bus2, mode="auto"),
        ws_manager=manager, llm_call=second_llm, workspace_memory_store=store,
    )
    await second.run("còn nhớ không")

    assert "[stale]" in seen["prompt"]
    assert "hello returns hi" in seen["prompt"]
    assert "PRIOR MEMORY REVISION MATCHES: False" in seen["prompt"]
