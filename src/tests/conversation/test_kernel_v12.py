# -*- coding: utf-8 -*-
from __future__ import annotations

from runtime.conversation import (
    ConversationAfter,
    ConversationKernel,
    DeterministicRootAgent,
    NextConversationMove,
    RunPhase,
)


class _Agent:
    def __init__(self, moves):
        self.moves = list(moves)
        self.calls = []

    def decide(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.moves.pop(0)


def test_user_turn_has_one_root_move_and_no_semantic_runtime_state():
    agent = _Agent([
        NextConversationMove(
            intent="bắt lại nhịp đùa",
            say="trêu lại nhẹ, không giải thích",
            delivery="hơi ngơ rồi bật cười",
            after=ConversationAfter.WAIT_USER,
        )
    ])
    kernel = ConversationKernel(agent)
    turn = kernel.begin_user_turn(session_id="s", user_text="hen hen")

    assert len(agent.calls) == 1
    assert turn.move.say == "trêu lại nhẹ, không giải thích"
    state = kernel.snapshot("s")
    assert state.phase == RunPhase.WRITING
    payload = state.to_dict()
    # Mechanical state không được tái sinh semantic scheduler V8-V11.
    for forbidden in ("planned_threads", "desired_shape", "floor", "next_intent", "public_beats"):
        assert forbidden not in payload


def test_delivery_receipt_is_idempotent_and_schedules_single_lease():
    agent = _Agent([
        NextConversationMove(
            intent="nói tiếp một nhịp",
            say="ý hiện tại",
            after=ConversationAfter.CONTINUE_SELF,
        )
    ])
    kernel = ConversationKernel(agent)
    turn = kernel.begin_user_turn(session_id="s", user_text="x")
    assert kernel.mark_delivery_started(turn, delivery_id="d1")
    assert kernel.settle_delivery(turn, delivery_id="d1", successful=True)
    assert not kernel.settle_delivery(turn, delivery_id="d1", successful=True)
    lease = kernel.continuation.peek("s")
    assert lease is not None
    assert lease.source_move_id == turn.move.move_id
    assert kernel.snapshot("s").phase == RunPhase.CONTINUATION_PENDING


def test_new_user_generation_preempts_old_continuation():
    agent = _Agent([
        NextConversationMove(intent="a", say="a", after=ConversationAfter.CONTINUE_SELF),
        NextConversationMove(intent="b", say="b", after=ConversationAfter.WAIT_USER),
    ])
    kernel = ConversationKernel(agent)
    first = kernel.begin_user_turn(session_id="s", user_text="one")
    kernel.mark_delivery_started(first, delivery_id="d1")
    kernel.settle_delivery(first, delivery_id="d1", successful=True)
    assert kernel.continuation.peek("s") is not None

    second = kernel.begin_user_turn(session_id="s", user_text="two")
    assert second.generation > first.generation
    assert kernel.continuation.peek("s") is None


def test_stale_delivery_cannot_schedule_after_user_steers():
    agent = _Agent([
        NextConversationMove(intent="a", say="a", after=ConversationAfter.CONTINUE_SELF),
        NextConversationMove(intent="b", say="b", after=ConversationAfter.WAIT_USER),
    ])
    kernel = ConversationKernel(agent)
    old = kernel.begin_user_turn(session_id="s", user_text="old")
    kernel.mark_delivery_started(old, delivery_id="old-d")
    new = kernel.begin_user_turn(session_id="s", user_text="new")

    assert not kernel.settle_delivery(old, delivery_id="old-d", successful=True)
    assert kernel.continuation.peek("s") is None
    assert kernel.snapshot("s").active_move_id == new.move.move_id


def test_crash_state_never_contains_public_text_for_replay():
    kernel = ConversationKernel(DeterministicRootAgent())
    turn = kernel.begin_user_turn(session_id="s", user_text="hello")
    kernel.mark_delivery_started(turn, delivery_id="d")
    state = kernel.snapshot("s").to_dict()
    assert "public_text" not in state
    assert "last_public_text" not in state
    assert "speech_text" not in state
