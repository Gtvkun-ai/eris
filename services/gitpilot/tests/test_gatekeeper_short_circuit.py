"""Regression tests for the gatekeeper conversational short-circuit.

Context: greetings were already classified correctly by ``gatekeeper.py``, but
that decision was only consumed by ``POST /api/chat/plan``.  The
``StreamingAgentExecutor`` — entry point behind the SSE chat route and the v2
websocket session route — never consulted the gatekeeper, so ``xin chào`` fell
through to the full Explorer/Planner/Coder/Reviewer crew with a write-capable
Coder agent.

These tests pin the two failure classes the seam must prevent:

1. **Over-short-circuiting.**  Terse but real requests ("fix it", "do thing",
   "sửa lỗi …") must still reach the normal pipeline.  The ``>= 0.95``
   threshold — not the whole conversational route — is the load-bearing guard.
2. **Regressing into the old behaviour.**  A greeting must produce a direct
   answer with zero repo I/O, zero plan steps, no write tools, no approval
   request, and it must do so before any LLM/provider is constructed.
"""
from __future__ import annotations

import pytest

from gitpilot.agent_events import AgentEventBus, EventType
from gitpilot.agent_executor import StreamingAgentExecutor, conversational_short_circuit
from gitpilot.approval_protocol import ApprovalGate
from gitpilot.gatekeeper import _rule_based_classify
from gitpilot.pipelines.direct_reply import _INSTANT_REPLIES

# (user message as typed, instant-map key after diacritic normalisation)
INSTANT_CASES = [
    ("xin chào", "xin chao"),
    ("xin chao", "xin chao"),
    ("chào bạn", "chao ban"),
    ("hello", "hello"),
    ("cảm ơn", "cam on"),
    ("tam biet", "tam biet"),
]

# Real work the seam must NOT swallow.
REAL_REQUESTS = [
    "fix the timeout bug in inference_broker.py",
    "fix it",
    "do thing",
    "sửa lỗi trong agentic.py",
    "tai sao orchestrator bi crash",
    "explain how the dialog system works",
]


@pytest.fixture(autouse=True)
def _clean_gatekeeper_flag():
    """A leaked override from another test must not skew these cases."""
    from gitpilot import flags

    flags.clear_override("gatekeeper")
    yield
    flags.clear_override("gatekeeper")


def _drain(queue) -> list:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ── V1: the seam itself (no LLM, no CrewAI, no repo) ────────────────────────


@pytest.mark.parametrize("goal,key", INSTANT_CASES)
async def test_instant_greetings_short_circuit_to_exact_reply(goal, key) -> None:
    """Exact string pins the instant map + diacritic normalisation + 0 LLM."""
    assert key in _INSTANT_REPLIES
    assert await conversational_short_circuit(goal) == _INSTANT_REPLIES[key]


async def test_prefix_tier_greeting_short_circuits_without_llm() -> None:
    """0.95 prefix tier ("xin chào bạn khoẻ không") is conversational too.

    Not in ``_INSTANT_REPLIES``, so it yields direct_reply's generic text —
    identical to today's ``/api/chat/plan`` behaviour.  No LLM is wired in.
    """
    reply = await conversational_short_circuit("xin chào bạn khoẻ không")
    assert reply == "Tôi hiểu. Bạn có thể nói thêm hoặc mô tả task cụ thể hơn không?"


@pytest.mark.parametrize("goal", REAL_REQUESTS)
async def test_real_requests_are_not_short_circuited(goal) -> None:
    assert await conversational_short_circuit(goal) is None


async def test_threshold_0_95_is_the_load_bearing_guard() -> None:
    """The 0.80 heuristic tier must never short-circuit (boundary case)."""
    decision = _rule_based_classify("do thing")
    assert decision is not None
    assert decision.route == "conversational"
    assert decision.confidence == 0.80
    assert await conversational_short_circuit("do thing") is None


# ── V2: flag parity with the /api/chat/plan block ───────────────────────────


async def test_flag_off_disables_the_seam() -> None:
    from gitpilot import flags

    assert await conversational_short_circuit("xin chào") is not None
    flags.set_override("gatekeeper", False)
    try:
        assert await conversational_short_circuit("xin chào") is None
    finally:
        flags.clear_override("gatekeeper")


# ── V3: executor integration — answer, not a plan ───────────────────────────


async def test_execute_greeting_streams_answer_not_plan(monkeypatch) -> None:
    bus = AgentEventBus()
    _sub_id, queue = bus.subscribe()
    executor = StreamingAgentExecutor(bus=bus, gate=ApprovalGate(bus))

    async def _never(*args, **kwargs):
        raise AssertionError("the coding team must not run for a greeting")

    monkeypatch.setattr(executor, "_execute_local_team", _never)

    result = await executor.execute("xin chào", "", mode="auto")

    assert result == {
        "summary": _INSTANT_REPLIES["xin chao"],
        "roles": [],
        "pipeline": "direct_reply",
    }

    events = _drain(queue)
    types = [e.type for e in events]
    assert types.count(EventType.DONE) == 1
    for forbidden in (
        EventType.PLAN_STEP,
        EventType.TOOL_START,
        EventType.TOOL_RESULT,
        EventType.APPROVAL_NEEDED,
        EventType.FILE_WRITE,
    ):
        assert forbidden not in types

    streamed = "".join(
        e.data["text"] for e in events if e.type is EventType.TEXT_DELTA
    )
    assert streamed == _INSTANT_REPLIES["xin chao"]
    statuses = [e.data.get("status") for e in events if e.type is EventType.STATUS_CHANGE]
    assert statuses == ["conversational"]


async def test_execute_greeting_short_circuits_on_github_sessions_too(monkeypatch) -> None:
    """One call site must cover both session kinds (local team + GitHub plan)."""
    bus = AgentEventBus()
    executor = StreamingAgentExecutor(bus=bus, gate=ApprovalGate(bus))

    async def _never(*args, **kwargs):
        raise AssertionError("planner / local team must not run for a greeting")

    monkeypatch.setattr(executor, "_generate_plan", _never)
    monkeypatch.setattr(executor, "_execute_local_team", _never)

    result = await executor.execute("xin chào", "owner/repo", mode="auto")
    assert result is not None
    assert result["pipeline"] == "direct_reply"


async def test_execute_real_request_still_reaches_the_team(monkeypatch) -> None:
    """Guard against over-short-circuiting in production wiring, not just V1."""
    bus = AgentEventBus()
    executor = StreamingAgentExecutor(bus=bus, gate=ApprovalGate(bus))
    sentinel = {"summary": "team ran", "roles": ["explorer"], "pipeline": "local_team"}
    seen = {}

    async def _team(*, user_message, mode, topology_id):
        seen["user_message"] = user_message
        return sentinel

    monkeypatch.setattr(executor, "_execute_local_team", _team)

    goal = "fix the timeout bug in inference_broker.py"
    result = await executor.execute(goal, "", mode="auto")

    assert result is sentinel
    assert seen["user_message"] == goal


# ── V3b: import safety — the gate must precede _build_llm() ─────────────────


async def test_greeting_works_without_crewai_or_litellm(monkeypatch) -> None:
    """A greeting must not need crewai/litellm (today it would raise there)."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.split(".")[0] in {"crewai", "litellm"}:
            raise ImportError(f"blocked {name} for this test")
        return real_import(name, *args, **kwargs)

    bus = AgentEventBus()
    executor = StreamingAgentExecutor(bus=bus, gate=ApprovalGate(bus))
    monkeypatch.setattr(builtins, "__import__", _blocked)

    result = await executor.execute("xin chào", "", mode="auto")
    assert result == {
        "summary": _INSTANT_REPLIES["xin chao"],
        "roles": [],
        "pipeline": "direct_reply",
    }
