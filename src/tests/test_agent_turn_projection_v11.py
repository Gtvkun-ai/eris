# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from live2d_body.stage_state import Live2DStageState
from runtime.agent_loop import (
    ConversationSpeechPlan,
    DialogueBeat,
    DiscoursePlan,
    SpeechContinuationMode,
    SpeechPlanLedger,
    SpeechPlanValidator,
    TurnDecision,
    TurnFloor,
    TurnProjection,
)
from runtime.turn_projection_runtime import emit_turn_projection


def _decision(*, floor: str, mode: str, feel: str = "thinking") -> TurnDecision:
    return TurnDecision.from_mapping(
        {
            "situation_summary": "đang nói chuyện",
            "objective": "giữ nhịp tự nhiên",
            "task_shape": "conversation",
            "active_roles": ["companion"],
            "work_items": [],
            "completed_items": ["đã chốt lượt nói"],
            "remaining_items": [],
            "uncertainties": [],
            "next_action": "complete",
            "progress": 1.0,
            "uncertainty": 0.0,
            "completion_candidate": True,
            "requires_user_response": False,
            "tutor_response_relation": "none",
            "speech_plan": {
                "plan_id": "p",
                "topic": "INTP 538",
                "conversation_goal": "phân tích tự nhiên",
                "current_thread": "Ti",
                "discussed": [],
                "planned_threads": ["INTJ mistype"] if mode == "auto_continue" else [],
                "next_intent": "nói tiếp về INTJ" if mode == "auto_continue" else "",
                "desired_shape": "nói như đang hứng thú",
                "continuation_mode": mode,
                "resume_trigger": "auto_after_audio" if mode == "auto_continue" else "user_reply",
                "pause_seconds": 0.6,
            },
            "turn_projection": {
                "floor": floor,
                "continuation_feel": feel,
                "verbal_bridge_hint": "kết hơi mở vì còn một liên hệ muốn nói tiếp" if floor == "hold" else "",
            },
            "public_beats": [
                {
                    "kind": "finding",
                    "proposition": "538 làm Ti-dom trông cứng hơn stereotype.",
                    "communicative_goal": "mở nhánh phân tích",
                    "relation_to_previous": "continue",
                    "detail_level": "normal",
                    "needs_example": False,
                }
            ],
            "style_notes": ["nói tự nhiên"],
            "decision_summary": "đã chọn floor",
        }
    )


def test_turn_projection_is_separate_from_speech_plan() -> None:
    decision = _decision(floor="hold", mode="auto_continue", feel="eager")
    assert decision.turn_projection.floor is TurnFloor.HOLD
    assert decision.turn_projection.continuation_feel == "eager"
    assert decision.speech_plan.continuation_mode is SpeechContinuationMode.AUTO_CONTINUE
    assert "liên hệ" in decision.turn_projection.verbal_bridge_hint


def test_validator_rejects_projection_lifecycle_contradictions() -> None:
    validator = SpeechPlanValidator()
    discourse = DiscoursePlan(public_beats=(DialogueBeat(proposition="A"),))

    yield_plan = ConversationSpeechPlan(
        continuation_mode=SpeechContinuationMode.YIELD_USER,
        resume_trigger="user_reply",
    )
    bad_hold = validator.validate(
        discourse,
        speech_plan=yield_plan,
        completion_candidate=True,
        waiting_for_user=False,
        turn_projection=TurnProjection(floor=TurnFloor.HOLD),
    )
    assert bad_hold.valid is False
    assert bad_hold.reason == "hold_floor_requires_auto_continue"

    auto_plan = ConversationSpeechPlan(
        planned_threads=("B",),
        continuation_mode=SpeechContinuationMode.AUTO_CONTINUE,
        resume_trigger="auto_after_audio",
    )
    bad_yield = validator.validate(
        discourse,
        speech_plan=auto_plan,
        completion_candidate=True,
        waiting_for_user=False,
        turn_projection=TurnProjection(floor=TurnFloor.YIELD),
    )
    assert bad_yield.valid is False
    assert bad_yield.reason == "auto_continue_cannot_yield_floor"


def test_hold_floor_requires_real_auto_continue_lifecycle() -> None:
    validator = SpeechPlanValidator()
    discourse = DiscoursePlan(public_beats=(DialogueBeat(proposition="A"),))
    no_continue = ConversationSpeechPlan(continuation_mode=SpeechContinuationMode.NONE)
    verdict = validator.validate(
        discourse,
        speech_plan=no_continue,
        completion_candidate=True,
        waiting_for_user=False,
        turn_projection=TurnProjection(floor=TurnFloor.HOLD),
    )
    assert verdict.valid is False
    assert verdict.reason == "hold_floor_requires_auto_continue"


def test_speech_plan_ledger_persists_projection_until_user_takes_floor() -> None:
    ledger = SpeechPlanLedger()
    decision = _decision(floor="hold", mode="auto_continue", feel="soft")
    snap = ledger.commit_agent_plan(
        "s1",
        plan=decision.speech_plan,
        turn_projection=decision.turn_projection,
        turn_id="t1",
    )
    assert snap.turn_projection.floor is TurnFloor.HOLD
    assert snap.turn_projection.continuation_feel == "soft"

    after_user = ledger.note_user_turn("s1")
    assert after_user.turn_projection.floor is TurnFloor.OPEN
    # Semantic plan vẫn còn để root agent re-plan; chỉ presentation projection hết hạn.
    assert after_user.plan.plan_id == "p"


def test_turn_projection_stage_adapter_mirrors_exact_agent_choice() -> None:
    events = []

    class Owner:
        def _emit_stage_protocol_state(self, event_type, *, reason="", data=None):
            events.append((event_type, reason, dict(data or {})))

    projection = TurnProjection(
        floor=TurnFloor.HOLD,
        continuation_feel="playful",
        verbal_bridge_hint="để nhịp kết mở nhẹ",
    )
    assert emit_turn_projection(Owner(), projection, turn_id="t1", session_id="s1") is True
    assert events == [
        (
            "turn_projection",
            "agent_turn_projection",
            {
                "floor": "hold",
                "continuation_feel": "playful",
                "verbal_bridge_hint": "để nhịp kết mở nhẹ",
                "turn_id": "t1",
                "session_id": "s1",
                "owner": "turn_agent_loop",
            },
        )
    ]


def test_live2d_hold_projection_does_not_settle_after_audio() -> None:
    state = Live2DStageState()
    state.handle_payload({"protocol": "eris.stage", "type": "thinking_started"})
    state.handle_payload(
        {
            "protocol": "eris.stage",
            "type": "turn_projection",
            "data": {"floor": "hold", "continuation_feel": "eager"},
        }
    )
    state.handle_payload({"protocol": "eris.stage", "type": "audio_playback_started"})
    assert state.advance(1 / 60).speaking is True
    state.handle_payload({"protocol": "eris.stage", "type": "audio_playback_done"})
    snapshot = state.advance(1 / 60)
    assert snapshot.speaking is False
    assert snapshot.motion == "lean_in_small"
    assert snapshot.emotion == "curious"


def test_live2d_yield_projection_settles_after_audio() -> None:
    state = Live2DStageState()
    state.handle_payload({"protocol": "eris.stage", "type": "thinking_started"})
    state.handle_payload(
        {
            "protocol": "eris.stage",
            "type": "turn_projection",
            "data": {"floor": "yield", "continuation_feel": "neutral"},
        }
    )
    state.handle_payload({"protocol": "eris.stage", "type": "audio_playback_started"})
    state.handle_payload({"protocol": "eris.stage", "type": "audio_playback_done"})
    snapshot = state.advance(1 / 60)
    assert snapshot.speaking is False
    assert snapshot.motion == "stand"
