# -*- coding: utf-8 -*-
"""Regression tests cho AgentLoop + TutorRole + conversation pacing V2."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.agent_loop import LoopBudget, TurnAgentRuntime, TurnDecision
from runtime.agent_loop.tutor_role import TutorRoleCoordinator


class ScriptedReasoner:
    def __init__(self, decisions: list[Mapping[str, Any]]) -> None:
        self.decisions = decisions
        self.calls = 0
        self.contexts: list[Mapping[str, Any]] = []

    def decide(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any]],
        state: Mapping[str, Any],
        runtime_context: Mapping[str, Any],
    ) -> TurnDecision:
        self.contexts.append(dict(runtime_context))
        index = min(self.calls, len(self.decisions) - 1)
        self.calls += 1
        return TurnDecision.from_mapping(self.decisions[index])


def d(
    *,
    beats: list[str],
    disclosure: str = "conversational",
    relation: str = "none",
    continuation: Mapping[str, Any] | None = None,
    max_beats: int = 6,
    complete: bool = True,
) -> dict[str, Any]:
    return {
        "situation_summary": "Đang cùng user phân tích một chủ đề.",
        "objective": "Phân tích INTP 538 theo mạch hội thoại.",
        "task_shape": "analysis",
        "active_roles": ["general", "tutor"],
        "work_items": ["core 5", "fix 3", "fix 8", "INTJ mistype"],
        "completed_items": ["đã có analysis map"],
        "remaining_items": [],
        "uncertainties": [],
        "next_action": "complete" if complete else "analyze",
        "progress": 1.0 if complete else 0.5,
        "uncertainty": 0.1,
        "completion_candidate": complete,
        "requires_user_response": False,
        "tutor_response_relation": relation,
        "response_mode": "progressive",
        "disclosure_mode": disclosure,
        "speech_budget": {
            "target_words": 400,
            "hard_max_words": 800,
            "max_beats": max_beats,
            "target_seconds": 120.0,
        },
        "continuation": continuation or {
            "active_thread": "INTP 538 khác stereotype ở đâu",
            "deferred_threads": ["fix 3", "fix 8", "vì sao dễ nhầm INTJ"],
            "continuation_anchor": "Điểm thú vị là 538 làm Ti-dom trông cứng hơn bình thường.",
            "next_if_continue": "giải thích vì sao bề ngoài dễ giống INTJ",
        },
        "dialogue_beats": [
            {
                "kind": "finding",
                "proposition": text,
                "communicative_goal": "nói một ý rồi để user có nhịp phản ứng",
                "relation_to_previous": "deepen",
                "detail_level": "normal",
                "needs_example": False,
                "say_now": True,
            }
            for text in beats
        ],
        "style_notes": ["nói như hội thoại, không dump encyclopedia"],
        "decision_summary": "đã phân tích đủ; public chỉ tiết lộ theo nhịp",
    }


def test_voice_conversational_says_one_beat_and_defers_rest() -> None:
    reasoner = ScriptedReasoner([
        d(beats=["Tổng quan 538.", "Core 5.", "Fix 3 và 8."])
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(
        turn_id="t1",
        session_id="s1",
        user_text="INTP 538 là gì?",
        runtime_context={"voice_mode": True},
    )

    assert [b.proposition for b in result.state.discourse.beats] == ["Tổng quan 538."]
    assert result.state.discourse.speech_budget.max_beats == 1
    assert "Core 5." in result.state.discourse.continuation.deferred_threads
    assert "Fix 3 và 8." in result.state.discourse.continuation.deferred_threads


def test_deep_dialogue_voice_allows_two_beats_not_full_dump() -> None:
    reasoner = ScriptedReasoner([
        d(
            beats=["Root issue.", "Giải thích root issue.", "Ví dụ.", "Kết luận."],
            disclosure="deep_dialogue",
        )
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(
        turn_id="t2",
        session_id="s2",
        user_text="phân tích sâu với tôi",
        runtime_context={"voice_mode": True},
    )

    assert len(result.state.discourse.beats) == 2
    assert result.state.discourse.continuation.next_if_continue


def test_report_text_can_reveal_more_when_user_explicitly_wants_full_answer() -> None:
    reasoner = ScriptedReasoner([
        d(
            beats=["A", "B", "C", "D", "E"],
            disclosure="report",
            max_beats=6,
        )
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(
        turn_id="t3",
        session_id="s3",
        user_text="viết profile đầy đủ cho tôi",
        runtime_context={"voice_mode": False},
    )

    assert [b.proposition for b in result.state.discourse.beats] == ["A", "B", "C", "D", "E"]


def test_next_turn_receives_prior_disclosure_arc_in_context() -> None:
    reasoner = ScriptedReasoner([
        d(beats=["Ý đầu."], continuation={
            "active_thread": "INTP 538",
            "deferred_threads": ["INTJ mistype"],
            "continuation_anchor": "Bề ngoài có thể giống INTJ.",
            "next_if_continue": "INTJ mistype",
        }),
        d(beats=["Tiếp đúng nhánh INTJ mistype."], continuation={
            "active_thread": "INTJ mistype",
            "deferred_threads": [],
            "continuation_anchor": "",
            "next_if_continue": "",
        }),
    ])
    runtime = TurnAgentRuntime(reasoner)

    runtime.prepare_turn(turn_id="a", session_id="same", user_text="INTP 538 là gì?")
    runtime.prepare_turn(turn_id="b", session_id="same", user_text="sao giống INTJ?")

    second_context = reasoner.contexts[1]
    arc = second_context["disclosure_arc"]
    assert arc["active_thread"] == "INTP 538"
    assert "INTJ mistype" in arc["deferred_threads"]


class FakeAssessment:
    def to_dict(self) -> dict[str, Any]:
        return {"verdict": "partial", "summary": "user đã trả lời một phần"}


class FakeTutorDecision:
    def __init__(self, *, requires_response: bool = True) -> None:
        self.requires_response = requires_response

    def to_writer_context(self) -> dict[str, Any]:
        return {
            "schema": "eris.tutor.directive.v1",
            "move": {
                "kind": "socratic_question",
                "objective": "phân biệt Ti và Te",
                "instruction_vi": "Hỏi đúng một câu Socratic rồi dừng.",
                "requires_user_response": self.requires_response,
                "max_sentences": 1,
            },
            "delivery_constraints": {
                "requires_user_response": self.requires_response,
                "max_sentences": 1,
            },
        }


class FakeTutorExecutive:
    def __init__(self) -> None:
        self.assess_calls = 0
        self.plan_calls = 0
        self.commit_calls = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": {
                "last_move": {
                    "kind": "probe_question",
                    "objective": "kiểm tra mental model",
                    "requires_user_response": True,
                    "max_sentences": 1,
                }
            },
            "learning": {"active_path_id": "path-1"},
        }

    def observe_response(self, *args: Any, **kwargs: Any) -> FakeAssessment:
        self.assess_calls += 1
        return FakeAssessment()

    def plan_next_move(self, *args: Any, **kwargs: Any) -> FakeTutorDecision:
        self.plan_calls += 1
        return FakeTutorDecision(requires_response=True)

    def commit_delivery(self, *args: Any, **kwargs: Any) -> None:
        self.commit_calls += 1


def test_tutor_answer_is_assessed_then_root_replans_and_hard_waits() -> None:
    tutor = FakeTutorExecutive()
    reasoner = ScriptedReasoner([
        d(beats=["Nhận câu trả lời user."], relation="answer"),
        d(beats=["Hỏi một câu Socratic tiếp theo rồi dừng."], relation="none"),
    ])
    runtime = TurnAgentRuntime(
        reasoner,
        tutor_role=TutorRoleCoordinator(tutor),
        budget=LoopBudget(soft_iterations=2, hard_iterations=4),
    )

    result = runtime.prepare_turn(
        turn_id="tutor-turn",
        session_id="lesson",
        user_text="tôi nghĩ là vì Ti muốn hiểu đúng",
        runtime_context={"voice_mode": True},
    )

    assert tutor.assess_calls == 1
    assert tutor.plan_calls == 1
    assert reasoner.calls == 2  # iteration 2 phải nhìn TeachingMove mới
    assert result.state.status == "waiting_user"
    assert len(result.state.discourse.beats) == 1

    runtime.commit_public_delivery(successful=True)
    assert tutor.commit_calls == 1


def test_tutor_interrupt_is_not_misgraded_as_learning_evidence() -> None:
    tutor = FakeTutorExecutive()
    reasoner = ScriptedReasoner([
        d(beats=["Chuyển theo chủ đề mới của user."], relation="interrupt")
    ])
    runtime = TurnAgentRuntime(reasoner, tutor_role=TutorRoleCoordinator(tutor))

    runtime.prepare_turn(
        turn_id="interrupt",
        session_id="lesson",
        user_text="thôi nói chuyện khác đi",
    )

    assert tutor.assess_calls == 0
    assert tutor.plan_calls == 0


def test_progressive_deferred_turn_reserves_user_floor_from_autonomous_afterbeat() -> None:
    reasoner = ScriptedReasoner([
        d(beats=["Nói một ý trước.", "Ý còn lại để sau."])
    ])
    runtime = TurnAgentRuntime(reasoner)
    result = runtime.prepare_turn(
        turn_id="floor",
        session_id="floor-session",
        user_text="phân tích với tôi",
        runtime_context={"voice_mode": True},
    )

    assert result.reserves_user_floor is True
