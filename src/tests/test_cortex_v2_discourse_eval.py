# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cognition import (
    CognitiveFrame,
    DiscourseProjection,
    EpistemicProjection,
    ProjectionFailure,
    SemanticProjection,
    SocialProjection,
    StyleProjection,
)
from runtime.cognition import PreResponseCognition
from runtime.cognition.frame_builder import CognitiveFrameBuilder
from runtime.cognition.workspace import CognitiveWorkspace
from tools.audit_cortex_reachability import audit
from tools.audit_cognition_architecture import audit as audit_architecture


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "tests" / "fixtures" / "discourse_cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_discourse_eval_corpus(case: dict[str, object]) -> None:
    previous = str(case.get("previous", ""))
    history = ({"role": "assistant", "content": previous},) if previous else ()
    brief = PreResponseCognition().analyze(
        user_text=str(case["user"]),
        recent_history=history,
        turn_id=f"eval:{case['id']}",
        turn_seq=1,
    )
    assert brief.discourse_relation == case["relation"]
    assert brief.ambiguity_owner == case["owner"]
    assert brief.response_move == case["move"]


def test_workspace_uses_real_evidence_ids_only() -> None:
    builder = CognitiveFrameBuilder()
    frame = builder.build(
        user_text="rồi sao?",
        recent_history=({"role": "assistant", "content": "Tôi còn một ý."},),
        turn_id="evidence",
        turn_seq=2,
    )
    brief = PreResponseCognition(frame_builder=builder).analyze(
        user_text="rồi sao?",
        recent_history=({"role": "assistant", "content": "Tôi còn một ý."},),
        turn_id="evidence",
        turn_seq=2,
    )
    valid = set(frame.evidence_by_id())
    assert brief.evidence_ids
    assert set(brief.evidence_ids) <= valid
    assert "history:last_assistant" not in brief.evidence_ids


class _BrokenStyle:
    def project(self, *_args, **_kwargs):
        raise RuntimeError("style exploded")


class _BrokenDiscourse:
    def project(self, *_args, **_kwargs):
        raise RuntimeError("discourse exploded")


def test_specialist_failure_isolated_instead_of_neutralizing_entire_brief() -> None:
    brief = PreResponseCognition(style=_BrokenStyle()).analyze(
        user_text="rồi sao?",
        recent_history=({"role": "assistant", "content": "Tôi còn một ý."},),
        turn_id="degraded-style",
        turn_seq=3,
    )
    assert brief.discourse_relation == "continue_assistant_move"
    assert brief.response_move == "self_elaborate"
    assert brief.ambiguity_owner == "assistant"
    assert brief.degraded_modules == ("style",)
    assert brief.confidence > 0.55


def test_critical_specialist_failure_marks_inference_tentative() -> None:
    brief = PreResponseCognition(discourse=_BrokenDiscourse()).analyze(
        user_text="rồi sao?",
        recent_history=({"role": "assistant", "content": "Tôi còn một ý."},),
        turn_id="degraded-discourse",
        turn_seq=4,
    )
    assert "discourse" in brief.degraded_modules
    assert brief.needs_deep_inference is True
    assert brief.ambiguity_owner != "assistant"


def _frame() -> CognitiveFrame:
    return CognitiveFrameBuilder().build(
        user_text="rồi sao?",
        recent_history=({"role": "assistant", "content": "Tôi còn một ý."},),
        turn_id="workspace",
        turn_seq=5,
    )


def test_workspace_arbitrates_conflicting_response_moves_by_evidence_and_authority() -> None:
    frame = _frame()
    discourse = DiscourseProjection(
        relation="continue_assistant_move",
        ambiguity_owner="assistant",
        expected_next_move="self_elaborate",
        confidence=0.94,
        ambiguity=0.05,
        evidence_ids=("turn:user_text", frame.last_assistant_evidence_id),
    )
    semantic = SemanticProjection(
        user_act="question",
        task_goal="answer_current_question",
        literal_question=True,
        confidence=0.78,
        ambiguity=0.22,
        evidence_ids=("turn:user_text",),
    )
    brief = CognitiveWorkspace().compile(
        frame=frame,
        discourse=discourse,
        semantic=semantic,
        epistemic=EpistemicProjection(evidence_ids=("turn:user_text",)),
        social=SocialProjection(evidence_ids=("turn:user_text",)),
        style=StyleProjection(delivery="dry_soft_follow_through", evidence_ids=("turn:user_text",)),
    )
    assert brief.response_move == "self_elaborate"
    assert any(item.startswith("response_move:") for item in brief.conflicts)
    assert brief.decision_margin > 0.0


def test_workspace_does_not_double_count_fake_evidence() -> None:
    frame = _frame()
    brief = CognitiveWorkspace().compile(
        frame=frame,
        discourse=DiscourseProjection(
            relation="continue_assistant_move",
            ambiguity_owner="assistant",
            expected_next_move="self_elaborate",
            confidence=0.92,
            ambiguity=0.08,
            evidence_ids=("missing:a", "missing:b"),
        ),
        semantic=SemanticProjection(
            user_act="continuation_bid",
            task_goal="complete_previous_assistant_implication",
            confidence=0.90,
            ambiguity=0.08,
            evidence_ids=("missing:a",),
        ),
        epistemic=EpistemicProjection(evidence_ids=("missing:a",)),
        social=SocialProjection(evidence_ids=("missing:a",)),
        style=StyleProjection(evidence_ids=("missing:a",)),
    )
    assert brief.evidence_ids == ()
    assert brief.evidence_coverage == 0.0
    assert brief.confidence < 0.75


def test_workspace_reports_degraded_module_without_erasing_other_lanes() -> None:
    frame = _frame()
    brief = CognitiveWorkspace().compile(
        frame=frame,
        discourse=DiscourseProjection(
            relation="continue_assistant_move",
            ambiguity_owner="assistant",
            expected_next_move="self_elaborate",
            confidence=0.94,
            ambiguity=0.06,
            evidence_ids=("turn:user_text", frame.last_assistant_evidence_id),
        ),
        semantic=SemanticProjection(
            user_act="continuation_bid",
            task_goal="complete_previous_assistant_implication",
            confidence=0.92,
            ambiguity=0.06,
            evidence_ids=("turn:user_text", frame.last_assistant_evidence_id),
        ),
        epistemic=EpistemicProjection(evidence_ids=("turn:user_text",)),
        social=SocialProjection(evidence_ids=("turn:user_text",)),
        style=StyleProjection(evidence_ids=("turn:user_text",)),
        failures=(ProjectionFailure("style", "RuntimeError", "broken"),),
    )
    assert brief.response_move == "self_elaborate"
    assert brief.degraded_modules == ("style",)
    assert brief.needs_deep_inference is False


def test_cortex_package_has_no_statically_unreachable_modules() -> None:
    result = audit(ROOT)
    assert result.unreachable_modules == ()


def test_cognition_hot_path_has_no_cycles_or_legacy_imports() -> None:
    result = audit_architecture(ROOT)
    assert result.clean is True
    assert result.cycles == ()
    assert result.forbidden_imports == ()
    assert result.package_root_reexports == ()
