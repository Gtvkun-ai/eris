# -*- coding: utf-8 -*-
"""Deterministic guardrail policy cho Tutor Executive.

Model được quyền linh hoạt về *cách dạy*, nhưng không được tự đổi phase của
learning loop. Ví dụ LearningService bảo đang `assess` thì reasoner không được
quay sang lecture 10 đoạn. Đây là lớp giữ agent tự nhiên nhưng không hỗn loạn.
"""
from __future__ import annotations

from dataclasses import replace

from runtime.learning_core.contracts import LearnerProfile
from runtime.learning_core.policy import TutorStep
from runtime.tutor.contracts import MoveEnvelope, TeachingMove, TutorDiagnosis


class TutorGuardrailPolicy:
    """Biến TutorStep deterministic thành một envelope cho semantic reasoner."""

    _RESPONSE_REQUIRED_KINDS = frozenset({
        "probe_question", "socratic_question", "guided_practice", "assessment", "review",
    })

    def envelope(
        self,
        step: TutorStep,
        diagnosis: TutorDiagnosis,
        learner: LearnerProfile,
    ) -> MoveEnvelope:
        pace = learner.preferred_pace
        teach_budget = 5 if pace == "slow" else (3 if pace == "fast" else 4)

        if step.kind == "probe":
            return MoveEnvelope(
                allowed_kinds=("probe_question", "socratic_question"),
                requires_user_response=True,
                max_sentences=2,
                interaction_type=step.interaction_type,
                reason="probe_before_teach",
            )

        if step.kind == "teach":
            has_misconception = any(
                item.status == "active"
                and item.kind == "misconception"
                and item.confidence >= 0.62
                for item in diagnosis.hypotheses
            )
            if has_misconception or diagnosis.primary_need == "misconception":
                return MoveEnvelope(
                    allowed_kinds=("counterexample", "socratic_question", "repair", "explain"),
                    requires_user_response=False,
                    max_sentences=min(teach_budget, 4),
                    interaction_type="short_answer",
                    reason="repair_misconception_before_more_content",
                )
            return MoveEnvelope(
                allowed_kinds=("explain", "analogy", "worked_example", "socratic_question"),
                requires_user_response=False,
                max_sentences=teach_budget,
                interaction_type="short_answer",
                reason="bounded_teaching_move",
            )

        if step.kind == "practice":
            return MoveEnvelope(
                allowed_kinds=("guided_practice", "socratic_question"),
                requires_user_response=True,
                max_sentences=3,
                interaction_type=step.interaction_type,
                reason="practice_requires_learner_action",
            )

        if step.kind == "assess":
            return MoveEnvelope(
                allowed_kinds=("assessment", "guided_practice"),
                requires_user_response=True,
                max_sentences=2,
                interaction_type=step.interaction_type,
                reason="assessment_must_collect_evidence",
            )

        if step.kind == "review":
            return MoveEnvelope(
                allowed_kinds=("review", "assessment", "socratic_question"),
                requires_user_response=True,
                max_sentences=2,
                interaction_type=step.interaction_type,
                reason="spaced_retrieval_before_reteaching",
            )

        if step.kind == "advance":
            return MoveEnvelope(
                allowed_kinds=("transition",),
                requires_user_response=False,
                max_sentences=2,
                interaction_type="short_answer",
                reason="mastery_gate_passed",
            )

        if step.kind == "complete":
            return MoveEnvelope(
                allowed_kinds=("complete",),
                requires_user_response=False,
                max_sentences=3,
                interaction_type="short_answer",
                reason="learning_path_complete",
            )

        return MoveEnvelope(
            allowed_kinds=("wait",),
            requires_user_response=False,
            max_sentences=1,
            interaction_type="short_answer",
            reason="policy_yields_floor",
        )

    def enforce(self, move: TeachingMove, envelope: MoveEnvelope, *, kp_id: str) -> TeachingMove:
        """Ép proposal của model về contract an toàn mà không làm mất intent chính."""
        kind = move.kind if move.kind in envelope.allowed_kinds else envelope.allowed_kinds[0]
        # Một số move (đặc biệt Socratic question) tự thân cần user trả lời,
        # kể cả khi phase cha là `teach`. Không được phát câu hỏi rồi tiếp tục
        # autonomous như thể đó chỉ là một câu giải thích.
        requires_response = (
            envelope.requires_user_response
            or kind in self._RESPONSE_REQUIRED_KINDS
        )
        return replace(
            move,
            kind=kind,
            kp_id=kp_id or move.kp_id,
            interaction_type=envelope.interaction_type,
            requires_user_response=requires_response,
            max_sentences=min(move.max_sentences, envelope.max_sentences),
        )


__all__ = ["TutorGuardrailPolicy"]
