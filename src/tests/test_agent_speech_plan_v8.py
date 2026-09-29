# -*- coding: utf-8 -*-
from __future__ import annotations

from runtime.agent_loop import (
    SpeechContinuationMode,
    TurnAgentRuntime,
    TurnDecision,
)


class ScriptedReasoner:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def decide(self, *, user_text, recent_history, state, runtime_context):
        self.calls.append({
            "user_text": user_text,
            "state": state,
            "runtime_context": runtime_context,
        })
        payload = self.payloads.pop(0)
        return TurnDecision.from_mapping(payload)


def payload(*, beat="Một ý public.", mode="yield_user", next_intent="", planned=()):
    return {
        "situation_summary": "đang nói chuyện",
        "objective": "giải thích chủ đề theo nhịp tự nhiên",
        "task_shape": "conversation",
        "active_roles": ["companion"],
        "work_items": ["giữ mạch"],
        "completed_items": ["chọn nhịp hiện tại"],
        "remaining_items": [],
        "uncertainties": [],
        "next_action": "complete",
        "progress": 1.0,
        "uncertainty": 0.1,
        "completion_candidate": True,
        "requires_user_response": False,
        "tutor_response_relation": "none",
        "response_mode": "normal",
        "disclosure_mode": "conversational",
        "speech_budget": {"max_beats": 1},
        "continuation": {
            "active_thread": "",
            "deferred_threads": [],
            "continuation_anchor": "",
            "next_if_continue": "",
        },
        "speech_plan": {
            "plan_id": "plan-1",
            "topic": "INTP 538",
            "conversation_goal": "phân tích cùng user thay vì dump",
            "current_thread": "khác stereotype",
            "discussed": ["tổng quan"],
            "planned_threads": list(planned),
            "next_intent": next_intent,
            "continuation_mode": mode,
            "resume_trigger": "auto_after_audio" if mode == "auto_continue" else "user_reply",
            "pause_seconds": 0.0,
        },
        "dialogue_beats": [{
            "kind": "finding",
            "proposition": beat,
            "communicative_goal": "nói đúng nhịp hiện tại",
            "relation_to_previous": "continue",
            "detail_level": "normal",
            "needs_example": False,
            "say_now": True,
        }],
        "style_notes": ["nói tự nhiên"],
        "decision_summary": "đã chọn nhịp nói",
    }


def test_runtime_persists_agent_authored_long_term_speech_plan_without_materializing_threads():
    reasoner = ScriptedReasoner([
        payload(beat="Chỉ nói ý mở đầu.", planned=("fix 3", "fix 8", "INTJ comparison"), next_intent="đào INTJ nếu user bắt nhánh đó"),
        payload(beat="Đi theo nhánh user vừa chọn.", planned=("fix 3", "fix 8"), next_intent="tiếp tục theo steering mới"),
    ])
    runtime = TurnAgentRuntime(reasoner)

    first = runtime.prepare_turn(turn_id="t1", session_id="s1", user_text="INTP 538 là gì")
    assert [b.proposition for b in first.state.discourse.beats] == ["Chỉ nói ý mở đầu."]
    snap = runtime.speech_plan_snapshot(session_id="s1")
    assert snap.plan.planned_threads == ("fix 3", "fix 8", "INTJ comparison")

    runtime.prepare_turn(turn_id="t2", session_id="s1", user_text="sao giống INTJ")
    prior = reasoner.calls[1]["runtime_context"]["conversation_speech_plan"]
    assert prior["plan"]["planned_threads"] == ["fix 3", "fix 8", "INTJ comparison"]
    # Runtime chỉ đưa plan lại cho agent; tuyệt đối không biến planned thread thành public beat.
    assert "fix 3" not in [b.proposition for b in first.state.discourse.beats]


def test_auto_continue_audio_receipt_only_schedules_wake_then_calls_agent_loop_again():
    reasoner = ScriptedReasoner([
        payload(beat="Phần một.", mode="auto_continue", planned=("phần hai",), next_intent="nói phần hai nếu vẫn hợp"),
        payload(beat="Phần hai do agent quyết lại.", mode="yield_user"),
    ])
    runtime = TurnAgentRuntime(reasoner)

    first = runtime.prepare_turn(turn_id="t1", session_id="s1", user_text="kể tiếp theo từng nhịp")
    assert first.state.speech_plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE
    runtime.commit_public_delivery(successful=True, public_text="Phần một.", turn_id="t1", session_id="s1")
    snap = runtime.note_audio_finished(session_id="s1")
    assert snap.status == "auto_continue_scheduled"

    second = runtime.prepare_continuation_turn(session_id="s1")
    assert second is not None
    assert reasoner.calls[1]["user_text"] == ""
    assert reasoner.calls[1]["runtime_context"]["continuation_wake"]["authorized"] is True
    assert [b.proposition for b in second.state.discourse.beats] == ["Phần hai do agent quyết lại."]


def test_real_user_turn_preempts_auto_continue_but_keeps_plan_for_replanning():
    reasoner = ScriptedReasoner([
        payload(beat="Phần một.", mode="auto_continue", planned=("phần hai",), next_intent="nói phần hai"),
        payload(beat="User chen vào nên đổi hướng.", mode="yield_user"),
    ])
    runtime = TurnAgentRuntime(reasoner)
    runtime.prepare_turn(turn_id="t1", session_id="s1", user_text="kể tiếp")
    runtime.commit_public_delivery(successful=True, public_text="Phần một.", turn_id="t1", session_id="s1")
    runtime.note_audio_finished(session_id="s1")

    runtime.prepare_turn(turn_id="t2", session_id="s1", user_text="khoan, nói fix 3 trước")
    prior = reasoner.calls[1]["runtime_context"]["conversation_speech_plan"]
    assert prior["plan"]["planned_threads"] == ["phần hai"]
    assert runtime.speech_plan_snapshot(session_id="s1").plan.continuation_mode == SpeechContinuationMode.YIELD_USER
