# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

from runtime.capabilities import TutorCapability, WorkResult
from runtime.conversation import (
    ConversationEvent,
    ConversationKernel,
    DeliveryReceipt,
    NextConversationMove,
    NoReply,
    SurfaceEnvelope,
)
from runtime.conversation.writer import RenderedConversationMove
from runtime.tutor_research_runtime import TutorResearchRuntimeMixin
from runtime.ai_orchestrated.orchestrator import AIChatOrchestrator


class _Agent:
    def __init__(self, decision):
        self.decision = decision
        self.events = []

    def decide(self, **kwargs):
        self.events.append(kwargs["event"])
        return self.decision


class _Writer:
    def __init__(self):
        self.calls = 0

    def realize(self, **kwargs):
        self.calls += 1
        return RenderedConversationMove(surface=SurfaceEnvelope(display_text="root-owned result"))


class _Delivery:
    def __init__(self):
        self.calls = 0

    def deliver(self, **kwargs):
        self.calls += 1


def test_tutor_returns_advice_without_public_surface_methods():
    decision = SimpleNamespace(to_writer_context=lambda: {
        "move": {"kind": "probe_question", "instruction": "Ask for one example."},
        "delivery_constraints": {"requires_user_response": True},
    })
    executive = SimpleNamespace(plan_next_move=lambda *args, **kwargs: decision)
    capability = TutorCapability(executive)

    advice = capability.advise(user_text="teach me", turn_id="turn:1")

    assert advice.active is True
    assert advice.expects_learner_response is True
    assert not hasattr(capability, "commit_delivery")
    assert not hasattr(advice, "public_text")


def test_foreground_registers_capabilities_without_eager_domain_calls():
    source = inspect.getsource(AIChatOrchestrator._run_v12)

    # Router chỉ wire dependency. RootAgent mới được quyền quyết có gọi domain
    # capability hay không; small talk không được chạy TutorExecutive ngầm.
    assert "RootCapabilityRegistry" in source
    assert '"__root_capabilities": capability_registry' in source
    assert "tutor_capability.advise" not in source
    assert "work_capability.snapshot" not in source
    assert "research_capability.snapshot" not in source


def test_tutor_observes_delivery_receipt_without_receiving_public_text():
    committed = []
    decision = SimpleNamespace(to_writer_context=lambda: {"move": {}})
    executive = SimpleNamespace(
        plan_next_move=lambda *args, **kwargs: decision,
        commit_delivery=lambda pending, **kwargs: committed.append((pending, kwargs)),
    )
    capability = TutorCapability(executive)
    capability.advise(user_text="continue", turn_id="turn:2")

    capability.observe_delivery_receipt(DeliveryReceipt(
        delivery_id="d1", session_id="s", generation=1, move_id="m1", successful=True
    ))

    assert committed == [(decision, {"successful": True})]


def test_research_completion_reenters_root_before_public_delivery():
    agent = _Agent(NextConversationMove(intent="report research", say="summarize evidence"))
    writer = _Writer()
    delivery = _Delivery()
    kernel = ConversationKernel(agent, writer=writer, delivery=delivery)
    host = SimpleNamespace(
        conversation_kernel=kernel,
        _active_research_job={"job_id": "job:1", "stale": False},
        _last_tutor_research_artifact={},
        _last_tutor_research_thread={},
        _last_tutor_research_metrics={},
        _last_tutor_research_memory_decision={},
        chat_history=[],
        logger=SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None),
    )

    TutorResearchRuntimeMixin._deliver_research_followup(
        host, "topic", "evidence", mode="research", job_id="job:1"
    )

    assert agent.events[0].kind == "research_result"
    assert writer.calls == 1
    assert delivery.calls == 1


def test_duplicate_work_result_produces_at_most_one_delivery():
    agent = _Agent(NextConversationMove(intent="report work", say="summarize result"))
    writer = _Writer()
    delivery = _Delivery()
    kernel = ConversationKernel(agent, writer=writer, delivery=delivery)
    result = WorkResult(status="completed", summary="done")
    event = ConversationEvent(
        event_id="work:stable-result-id",
        session_id="s",
        kind="work_result",
        metadata={"work_capability": result.to_dict()},
    )

    first = kernel.handle_event(event)
    second = kernel.handle_event(event)

    assert first.delivery_id == second.delivery_id
    assert writer.calls == 1
    assert delivery.calls == 1


def test_capability_failure_does_not_create_fallback_speech():
    agent = _Agent(NoReply(reason="failed_capability_has_no_user_value"))
    writer = _Writer()
    delivery = _Delivery()
    kernel = ConversationKernel(agent, writer=writer, delivery=delivery)

    result = kernel.handle_event(ConversationEvent(
        event_id="research:failed:1",
        session_id="s",
        kind="research_result",
        metadata={"research_capability": {"status": "failed"}},
    ))

    assert result.status == "no_reply"
    assert writer.calls == 0
    assert delivery.calls == 0


def test_capability_modules_never_record_assistant_or_call_transport():
    root = Path(__file__).resolve().parents[2] / "runtime"
    paths = [*sorted((root / "capabilities").glob("*.py")), root / "tutor_research_runtime.py"]
    forbidden = {"record_assistant", "_send_decision_to_body", "_append_chat_history"}
    offenders = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden:
                offenders.append(f"{path.name}:{node.lineno}:{node.func.attr}")

    assert offenders == []
