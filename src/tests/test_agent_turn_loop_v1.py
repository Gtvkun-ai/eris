# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.agent_loop import LoopBudget, TurnAgentRuntime, TurnDecision


class ScriptedReasoner:
    def __init__(self, decisions: list[Mapping[str, Any]]) -> None:
        self.decisions = list(decisions)
        self.calls = 0

    def decide(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any]],
        state: Mapping[str, Any],
        runtime_context: Mapping[str, Any],
    ) -> TurnDecision:
        index = min(self.calls, len(self.decisions) - 1)
        self.calls += 1
        return TurnDecision.from_mapping(self.decisions[index])


def decision(
    *,
    action: str,
    remaining: list[str] | None = None,
    completed: list[str] | None = None,
    beats: list[str] | None = None,
    mode: str = "normal",
    completion: bool = False,
    wait: bool = False,
    progress: float = 0.5,
) -> dict[str, Any]:
    return {
        "situation_summary": "Đang xử lý yêu cầu hiện tại.",
        "objective": "Trả lời đủ và tự nhiên.",
        "task_shape": "analysis" if mode in {"deep", "progressive"} else "conversation",
        "active_roles": ["general", "critic"] if mode in {"deep", "progressive"} else ["general"],
        "work_items": ["phân tích", "kiểm tra", "trình bày"],
        "completed_items": completed or [],
        "remaining_items": remaining or [],
        "uncertainties": [],
        "next_action": action,
        "progress": progress,
        "uncertainty": max(0.0, 1.0 - progress),
        "completion_candidate": completion,
        "requires_user_response": wait,
        "response_mode": mode,
        "dialogue_beats": [
            {
                "kind": "finding",
                "proposition": text,
                "communicative_goal": "nói một phát hiện hữu ích",
                "relation_to_previous": "deepen",
                "detail_level": "deep" if mode in {"deep", "progressive"} else "normal",
                "needs_example": False,
                "say_now": True,
            }
            for text in (beats or ["Nói ý quan trọng trước."])
        ],
        "style_notes": ["nói tự nhiên", "không lặp ý"],
        "decision_summary": f"{action}: còn {len(remaining or [])} mục",
    }


def test_simple_turn_completes_in_one_iteration() -> None:
    reasoner = ScriptedReasoner([
        decision(action="complete", completion=True, progress=1.0, beats=["Trả lời trực tiếp."])
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(turn_id="t1", user_text="hello")

    assert result.state.status == "complete"
    assert result.model_iterations == 1
    assert reasoner.calls == 1
    assert result.completion_reason == "coverage_complete"


def test_deep_analysis_can_decompose_verify_then_complete() -> None:
    reasoner = ScriptedReasoner([
        decision(
            action="decompose",
            remaining=["state ownership", "failure modes"],
            completed=["root issue"],
            beats=["Vấn đề gốc nằm ở lifecycle."],
            mode="progressive",
            progress=0.3,
        ),
        decision(
            action="verify",
            remaining=["failure modes"],
            completed=["root issue", "state ownership"],
            beats=["State ownership đang bị chia đôi."],
            mode="progressive",
            progress=0.72,
        ),
        decision(
            action="complete",
            remaining=[],
            completed=["root issue", "state ownership", "failure modes"],
            beats=["Từ đó kiến trúc nên dùng một TurnAgentLoop thống nhất."],
            mode="deep",
            completion=True,
            progress=1.0,
        ),
    ])
    runtime = TurnAgentRuntime(reasoner, budget=LoopBudget(soft_iterations=2, hard_iterations=5))

    result = runtime.prepare_turn(turn_id="t2", user_text="phân tích sâu kiến trúc này")

    assert result.state.status == "complete"
    assert result.model_iterations == 3
    assert [b.proposition for b in result.state.discourse.beats] == [
        "Vấn đề gốc nằm ở lifecycle.",
        "State ownership đang bị chia đôi.",
        "Từ đó kiến trúc nên dùng một TurnAgentLoop thống nhất.",
    ]


def test_runtime_rejects_premature_complete_when_work_remains() -> None:
    reasoner = ScriptedReasoner([
        decision(
            action="complete",
            completion=True,
            remaining=["kiểm tra mâu thuẫn"],
            beats=["Có kết luận sơ bộ."],
            mode="deep",
            progress=0.7,
        ),
        decision(
            action="complete",
            completion=True,
            remaining=[],
            completed=["kiểm tra mâu thuẫn"],
            beats=["Đã kiểm tra xong mâu thuẫn."],
            mode="deep",
            progress=1.0,
        ),
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(turn_id="t3", user_text="phân tích")

    assert reasoner.calls == 2
    assert result.completion_reason == "coverage_complete"


def test_wait_user_is_a_hard_stop() -> None:
    reasoner = ScriptedReasoner([
        decision(
            action="wait_user",
            completion=False,
            wait=True,
            remaining=["câu trả lời của user"],
            beats=["Hỏi đúng một câu cần thiết rồi dừng."],
            progress=0.5,
        ),
        decision(action="complete", completion=True, progress=1.0),
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(turn_id="t4", user_text="giúp tôi chọn nhưng thiếu dữ kiện")

    assert result.state.status == "waiting_user"
    assert result.should_wait_user is True
    assert reasoner.calls == 1


def test_duplicate_dialogue_beats_are_not_repeated() -> None:
    same = "Root cause nằm ở foreground lifecycle."
    reasoner = ScriptedReasoner([
        decision(action="analyze", remaining=["verify"], beats=[same], mode="deep", progress=0.4),
        decision(action="complete", completion=True, beats=[same, "Giải pháp là unified turn loop."], mode="deep", progress=1.0),
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(turn_id="t5", user_text="phân tích")

    propositions = [beat.proposition for beat in result.state.discourse.beats]
    assert propositions.count(same) == 1
    assert "Giải pháp là unified turn loop." in propositions


def test_stall_guard_prevents_infinite_loop() -> None:
    repeated = decision(
        action="analyze",
        remaining=["chưa rõ"],
        beats=["Đang kiểm tra cùng một điểm."],
        mode="deep",
        progress=0.2,
    )
    reasoner = ScriptedReasoner([repeated, repeated, repeated, repeated])
    runtime = TurnAgentRuntime(
        reasoner,
        budget=LoopBudget(soft_iterations=2, hard_iterations=8, stall_limit=2),
    )

    result = runtime.prepare_turn(turn_id="t6", user_text="bài khó")

    assert result.completion_reason == "stall_guard"
    assert reasoner.calls == 3
    assert result.state.status == "complete"


def test_external_agent_route_is_projected_not_reowned() -> None:
    reasoner = ScriptedReasoner([
        decision(action="complete", completion=True, progress=1.0)
    ])
    runtime = TurnAgentRuntime(reasoner)

    result = runtime.prepare_turn(
        turn_id="t7",
        user_text="fix repo",
        runtime_context={
            "agent_execution_route": {"action": "execute", "start_status": "started", "task_id": "a1"}
        },
    )

    assert result.state.execution.external_action_needed is True
    assert result.state.execution.external_action_status == "started"
