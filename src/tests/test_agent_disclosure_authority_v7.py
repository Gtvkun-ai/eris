# -*- coding: utf-8 -*-
"""V7: root agent là authority duy nhất của semantic disclosure."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.agent_loop import TurnAgentRuntime, TurnDecision
from runtime.agent_loop.contracts import DialogueBeat, DiscoursePlan, DisclosureMode, ContinuationPlan
from runtime.agent_loop.director import ConversationDirector


class _Scripted:
    def __init__(self, payloads: list[Mapping[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0
        self.contexts: list[Mapping[str, Any]] = []

    def decide(self, *, user_text: str, recent_history: Sequence[Mapping[str, Any]], state: Mapping[str, Any], runtime_context: Mapping[str, Any]) -> TurnDecision:
        self.contexts.append(dict(runtime_context))
        idx = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        return TurnDecision.from_mapping(self.payloads[idx])


def _payload(*, beats: list[tuple[str, bool]], complete: bool = True, deferred: list[str] | None = None) -> dict[str, Any]:
    return {
        "situation_summary": "đang trò chuyện",
        "objective": "nói tự nhiên theo đúng disclosure decision của agent",
        "task_shape": "conversation",
        "active_roles": ["general"],
        "work_items": [],
        "completed_items": [],
        "remaining_items": [],
        "uncertainties": [],
        "next_action": "complete" if complete else "analyze",
        "progress": 1.0 if complete else 0.4,
        "uncertainty": 0.0,
        "completion_candidate": complete,
        "requires_user_response": False,
        "tutor_response_relation": "none",
        "response_mode": "progressive",
        "disclosure_mode": "conversational",
        "speech_budget": {"max_beats": 1, "target_words": 5, "hard_max_words": 8, "target_seconds": 2, "hard_max_seconds": 3},
        "continuation": {
            "active_thread": "thread",
            "deferred_threads": deferred or [],
            "continuation_anchor": "",
            "next_if_continue": "",
        },
        "dialogue_beats": [
            {
                "kind": "finding",
                "proposition": text,
                "communicative_goal": "public" if say else "hold",
                "relation_to_previous": "continue",
                "detail_level": "normal",
                "needs_example": False,
                "say_now": say,
            }
            for text, say in beats
        ],
        "style_notes": [],
        "decision_summary": "agent owns disclosure",
    }


def test_director_projects_exact_agent_say_now_flags_without_choosing_count() -> None:
    director = ConversationDirector()
    plan = DiscoursePlan(
        disclosure_mode=DisclosureMode.CONVERSATIONAL,
        beats=(
            DialogueBeat(proposition="A", say_now=True),
            DialogueBeat(proposition="B", say_now=True),
            DialogueBeat(proposition="C", say_now=False),
        ),
        continuation=ContinuationPlan(deferred_threads=("C",)),
    )
    projected = director.project_for_writer(plan)
    assert [b.proposition for b in projected.beats] == ["A", "B"]
    assert projected.continuation.deferred_threads == ("C",)


def test_runtime_ignores_legacy_max_beats_when_agent_selected_three_public_beats() -> None:
    reasoner = _Scripted([_payload(beats=[("A", True), ("B", True), ("C", True)])])
    runtime = TurnAgentRuntime(reasoner)
    result = runtime.prepare_turn(
        turn_id="v7-three",
        session_id="v7",
        user_text="nói ba ý này đi",
        runtime_context={"voice_mode": True, "tts_speed": 0.85},
    )
    assert [b.proposition for b in result.state.discourse.beats] == ["A", "B", "C"]


def test_runtime_does_not_auto_create_deferred_threads_from_hidden_beats() -> None:
    reasoner = _Scripted([_payload(beats=[("A", True), ("B", False)], deferred=[])])
    runtime = TurnAgentRuntime(reasoner)
    result = runtime.prepare_turn(turn_id="v7-hold", session_id="v7-hold", user_text="test")
    assert [b.proposition for b in result.state.discourse.beats] == ["A"]
    # Agent không ghi B vào deferred thì runtime cũng không tự nghĩ hộ.
    assert result.state.discourse.continuation.deferred_threads == ()


def test_invalid_complete_without_public_beat_is_sent_back_to_agent_for_replan() -> None:
    reasoner = _Scripted([
        _payload(beats=[("ý để sau", False)], complete=True, deferred=["ý để sau"]),
        _payload(beats=[("ý public sau replan", True)], complete=True),
    ])
    runtime = TurnAgentRuntime(reasoner)
    result = runtime.prepare_turn(turn_id="v7-replan", session_id="v7-replan", user_text="trả lời tôi")
    assert reasoner.calls == 2
    assert [b.proposition for b in result.state.discourse.beats] == ["ý public sau replan"]
    assert reasoner.contexts[1]["agent_disclosure_feedback"]["reason"] == "completion_requires_agent_selected_public_beat"
