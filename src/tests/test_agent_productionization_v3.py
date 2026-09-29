# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runtime.agent_loop import (
    DialogueBeat,
    DisclosureMode,
    DiscoursePlan,
    TurnSpeechBudget,
)
from runtime.agent_loop.director import ConversationDirector
from runtime.agent_loop.speech import enforce_public_speech_budget
from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
from runtime.ai_orchestrated.planner import IntentionPlanner
from runtime.learning_core import KnowledgePoint, LearningPath, LearningService, LearningStore
from runtime.tutor.contracts import TeachingMove, TutorState
from runtime.tutor.session_store import TutorSessionLedger


def test_learning_service_restores_active_path_and_kp_after_restart(tmp_path: Path) -> None:
    db = tmp_path / "learning.sqlite3"
    store1 = LearningStore(db)
    service1 = LearningService(store1)
    path = LearningPath(
        path_id="p1",
        title="Transaction",
        goal="Hiểu transaction boundary",
        knowledge_points=(
            KnowledgePoint(kp_id="kp1", title="DB transaction", description="db"),
            KnowledgePoint(kp_id="kp2", title="Kafka boundary", description="kafka"),
        ),
    )
    service1.register_path(path)
    assert service1.activate_path("p1") is True
    service1.advance_kp("kp2")
    store1.close()

    store2 = LearningStore(db)
    service2 = LearningService(store2)
    assert service2.active_path() is not None
    snapshot = service2.snapshot()
    assert snapshot["active_path_id"] == "p1"
    assert snapshot["active_kp_id"] == "kp2"
    store2.close()


def test_tutor_session_ledger_restores_exact_delivered_move(tmp_path: Path) -> None:
    atomic = SQLiteAtomicStateStore(tmp_path / "runtime.sqlite3")
    ledger1 = TutorSessionLedger(atomic_store=atomic)
    move = TeachingMove(
        move_id="m1",
        kind="socratic_question",
        kp_id="kp1",
        objective="phân biệt Ti và Te",
        instruction_vi="Hỏi đúng một câu.",
        requires_user_response=True,
        max_sentences=1,
    )
    state = TutorState(
        session_id="tutor:s1",
        path_id="p1",
        kp_id="kp1",
        session_goal="understand",
        last_move=move,
        last_delivery_text="Theo bạn Ti muốn hiểu đúng hay tối ưu hiệu quả trước?",
        turn_count=3,
    )
    ledger1.commit(state, committed_move_ids=("m0",), assessed_response_keys=("m0|t0",))

    ledger2 = TutorSessionLedger(atomic_store=atomic)
    restored = ledger2.load()
    assert restored.state.last_move is not None
    assert restored.state.last_move.move_id == "m1"
    assert "Ti muốn hiểu đúng" in restored.state.last_delivery_text
    assert restored.committed_move_ids == ("m0",)


def test_voice_speech_observer_never_mutates_writer_text() -> None:
    budget = TurnSpeechBudget(
        target_words=35,
        hard_max_words=55,
        max_beats=1,
        target_seconds=12.0,
        hard_max_seconds=18.0,
    )
    text = " ".join(["Đây là một câu giải thích khá dài về kiến trúc agent."] * 35)
    result = enforce_public_speech_budget(text, budget, speed=1.0)
    assert result.clipped is False
    assert result.text == text
    assert result.reason == "observe_only_no_runtime_mutation"
    assert result.estimate.seconds > 0


def test_director_voice_guidance_does_not_change_with_tts_speed() -> None:
    director = ConversationDirector()
    plan = DiscoursePlan(
        disclosure_mode=DisclosureMode.CONVERSATIONAL,
        beats=(DialogueBeat(proposition="Một ý ngắn để nói tự nhiên."),),
        speech_budget=TurnSpeechBudget(
            target_words=500,
            hard_max_words=900,
            max_beats=4,
            target_seconds=20,
            hard_max_seconds=30,
        ),
    )
    slow = director.apply_turn_pacing(plan, voice_mode=True, tts_speed=0.85)
    fast = director.apply_turn_pacing(plan, voice_mode=True, tts_speed=1.15)
    # TTS speed chỉ còn là telemetry; runtime không biến nó thành word/time cap.
    assert slow.speech_budget == fast.speech_budget


class _Router:
    def __init__(self) -> None:
        self.calls = 0

    def plan_chat(self, snapshot):  # pragma: no cover - phải không được gọi
        self.calls += 1
        raise AssertionError("legacy planner must not own foreground semantic planning")


class _Reducer:
    def __init__(self) -> None:
        self.events = []

    def snapshot(self):
        return SimpleNamespace(version=7)

    def submit(self, event):
        self.events.append(event)


def test_intention_planner_is_only_compat_projection_when_agent_turn_exists() -> None:
    router = _Router()
    planner = IntentionPlanner(router, _Reducer())
    plan = planner.plan_chat(
        {
            "agent_turn": {
                "cognitive_plan": {"objective": "Phân tích INTP 538 theo nhịp hội thoại."},
                "discourse_plan": {
                    "response_mode": "progressive",
                    "continuation": {"active_thread": "INTJ mistype"},
                },
            }
        },
        turn_seq=3,
    )
    assert router.calls == 0
    assert plan.strategy == "agent_turn_owned"
    assert "INTP 538" in plan.topic
