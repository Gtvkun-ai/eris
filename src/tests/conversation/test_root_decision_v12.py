# -*- coding: utf-8 -*-
from __future__ import annotations

from runtime.conversation import (
    ConversationEvent,
    NextConversationMove,
    NoReply,
    RuntimeModelRootAgent,
)


class _Router:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.executive_client = object()
        self.result = result
        self.error = error
        self.requests: list[dict] = []

    def invoke_structured_worker(self, _client, **kwargs):
        self.requests.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def _event(kind: str, *, text: str = "") -> ConversationEvent:
    return ConversationEvent(
        event_id=f"event:{kind}",
        session_id="s",
        kind=kind,
        text=text,
    )


def test_root_decision_parses_explicit_no_reply():
    router = _Router({"kind": "no_reply", "reason": "nothing_worth_saying"})

    decision = RuntimeModelRootAgent(router).decide(
        event=_event("autonomous_signal"),
        recent_history=(),
        note="",
        runtime_context={},
    )

    assert isinstance(decision, NoReply)
    assert decision.reason == "nothing_worth_saying"
    assert set(decision.to_dict()) == {"schema", "kind", "decision_id", "reason"}


def test_non_user_model_failure_fails_closed_to_no_reply():
    router = _Router(error=RuntimeError("provider unavailable"))

    decision = RuntimeModelRootAgent(router).decide(
        event=_event("opening_signal"),
        recent_history=(),
        note="",
        runtime_context={},
    )

    assert isinstance(decision, NoReply)
    assert decision.reason == "root_model_unavailable"
    payload = decision.to_dict()
    assert "say" not in payload
    assert "delivery" not in payload
    assert "after" not in payload


def test_user_model_failure_uses_root_owned_degraded_move():
    router = _Router(error=RuntimeError("provider unavailable"))

    decision = RuntimeModelRootAgent(router).decide(
        event=_event("user_turn", text="giúp tôi với"),
        recent_history=(),
        note="",
        runtime_context={},
    )

    assert isinstance(decision, NextConversationMove)
    assert "giúp tôi với" in decision.say
