# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from runtime.conversation import (
    ConversationAfter,
    ConversationEvent,
    ConversationKernel,
    ContinuationLeaseScheduler,
    NextConversationMove,
    NoReply,
    RenderedConversationMove,
    SurfaceEnvelope,
)


ROOT = Path(__file__).resolve().parents[2]


class _Agent:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls: list[dict] = []

    def decide(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.decisions.pop(0)


class _Writer:
    def __init__(self):
        self.calls: list[dict] = []

    def realize(self, **kwargs):
        self.calls.append(dict(kwargs))
        return RenderedConversationMove(
            surface=SurfaceEnvelope(display_text="continued"),
            decision_payload=kwargs["turn"].move.to_dict(),
        )


class _Delivery:
    def __init__(self):
        self.calls: list[dict] = []

    def deliver(self, **kwargs):
        self.calls.append(dict(kwargs))


def _due_kernel(decision):
    scheduler = ContinuationLeaseScheduler()
    agent = _Agent([decision])
    writer = _Writer()
    delivery = _Delivery()
    kernel = ConversationKernel(
        agent,
        continuation=scheduler,
        writer=writer,
        delivery=delivery,
    )
    generation = kernel.preempt_for_user("s").generation
    scheduler.schedule(
        session_id="s",
        generation=generation,
        move_id="move:source",
        after=ConversationAfter.CONTINUE_SELF,
        now=10.0,
        continue_self_delay=0.0,
    )
    return kernel, agent, writer, delivery


def test_due_lease_reenters_kernel_and_root_can_choose_no_reply():
    kernel, agent, writer, delivery = _due_kernel(NoReply(reason="thread_complete"))

    result = kernel.handle_due_continuation(session_id="s", now=11.0)

    assert result is not None and result.status == "no_reply"
    assert agent.calls[0]["event"].kind == "continuation_due"
    assert writer.calls == []
    assert delivery.calls == []
    assert kernel.continuation.peek("s") is None


def test_user_generation_beats_claimed_continuation_before_writer():
    writer = _Writer()
    delivery = _Delivery()

    class _RacingAgent:
        kernel = None

        def decide(self, **_kwargs):
            self.kernel.preempt_for_user("s")
            return NextConversationMove(intent="stale", say="must not render")

    agent = _RacingAgent()
    scheduler = ContinuationLeaseScheduler()
    kernel = ConversationKernel(agent, continuation=scheduler, writer=writer, delivery=delivery)
    agent.kernel = kernel
    generation = kernel.preempt_for_user("s").generation
    scheduler.schedule(
        session_id="s", generation=generation, move_id="source",
        after=ConversationAfter.CONTINUE_SELF, now=10.0, continue_self_delay=0.0,
    )

    result = kernel.handle_due_continuation(session_id="s", now=11.0)

    assert result is not None and result.status == "stale"
    assert writer.calls == []
    assert delivery.calls == []
    assert kernel.continuation.peek("s") is None


def test_duplicate_due_wakes_claim_only_one_lease():
    kernel, agent, _writer, _delivery = _due_kernel(NoReply(reason="done"))

    first = kernel.handle_due_continuation(session_id="s", now=11.0)
    second = kernel.handle_due_continuation(session_id="s", now=11.0)

    assert first is not None
    assert second is None
    assert len(agent.calls) == 1


def test_lease_schema_contains_no_semantic_content():
    kernel, _agent, _writer, _delivery = _due_kernel(NoReply(reason="done"))
    payload = kernel.continuation.peek("s").to_dict()

    for forbidden in (
        "topic", "objective", "say", "speech_act", "public_text",
        "teaching_chunk", "planned_thread", "next_intent",
    ):
        assert forbidden not in payload


def test_only_continuation_lease_scheduler_is_bootstrapped_for_public_continuation():
    bootstrap = (ROOT / "runtime/ai_orchestrated/bootstrap.py").read_text(encoding="utf-8")
    orchestrator = (ROOT / "runtime/ai_orchestrated/orchestrator.py").read_text(encoding="utf-8")
    signal_handler = orchestrator.split("    def _run_v12_signal(", 1)[1].split(
        "    def run_social_signal(", 1
    )[0]

    assert "SocialContinuationRuntime(" not in bootstrap
    assert "ConversationArcRuntime(" not in bootstrap
    assert "runtime.agent_loop" not in signal_handler
    assert "handle_due_continuation" in signal_handler
