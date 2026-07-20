# -*- coding: utf-8 -*-
"""Bounded Cognitive Workspace.

Workspace không giữ state lâu dài. Nó chỉ hợp nhất projection của một lượt, giới
hạn evidence và giải quyết xung đột theo ownership/confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.cognition import (
    DiscourseProjection,
    EpistemicProjection,
    PreResponseCognitiveBrief,
    SemanticProjection,
    SocialProjection,
    StyleProjection,
)


@dataclass(frozen=True, slots=True)
class WorkspaceBudget:
    max_evidence_refs: int = 10
    max_avoid_moves: int = 8
    max_notes: int = 5


class CognitiveWorkspace:
    def __init__(self, budget: WorkspaceBudget | None = None) -> None:
        self.budget = budget or WorkspaceBudget()

    @staticmethod
    def _unique(values: Iterable[str], limit: int) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return tuple(result)

    def compile(
        self,
        *,
        trace_id: str,
        discourse: DiscourseProjection,
        semantic: SemanticProjection,
        epistemic: EpistemicProjection,
        social: SocialProjection,
        style: StyleProjection,
    ) -> PreResponseCognitiveBrief:
        # Discourse sở hữu move. Semantic chỉ bổ sung goal; không được lật ownership.
        response_move = discourse.expected_next_move or "answer"
        primary_goal = semantic.task_goal or "respond_to_current_turn"
        confidence = (
            discourse.confidence * 0.34
            + semantic.confidence * 0.20
            + epistemic.confidence * 0.16
            + social.confidence * 0.16
            + style.confidence * 0.14
        )
        ambiguity = max(
            discourse.ambiguity * 0.55,
            semantic.ambiguity * 0.30,
            social.ambiguity * 0.20,
            epistemic.uncertainty * 0.35,
        )
        notes: list[str] = []
        if discourse.ambiguity_owner == "assistant":
            notes.append("ERIS must resolve ambiguity created by her own previous wording before asking the user anything broad.")
        if epistemic.overread_risk >= 0.40:
            notes.append("Keep social inference tentative; do not turn posture into a fact about the user.")
        if epistemic.missing_evidence:
            notes.append("Do not claim missing mechanical or external evidence as completed fact.")
        if discourse.open_loop:
            notes.append("Use the immediately previous ERIS turn as the active open loop.")

        evidence_ids = self._unique(
            (
                *discourse.evidence_ids,
                *semantic.evidence_ids,
                *epistemic.evidence_ids,
                *social.evidence_ids,
                *style.evidence_ids,
            ),
            self.budget.max_evidence_refs,
        )
        return PreResponseCognitiveBrief(
            trace_id=trace_id,
            primary_goal=primary_goal,
            discourse_relation=discourse.relation,
            ambiguity_owner=discourse.ambiguity_owner,
            response_move=response_move,
            user_act=semantic.user_act,
            user_posture=social.user_posture,
            assistant_fault_probability=discourse.assistant_fault_probability,
            grounding_scope=epistemic.grounding_scope,
            missing_evidence=epistemic.missing_evidence,
            delivery=style.delivery,
            avoid_moves=self._unique(style.avoid_moves, self.budget.max_avoid_moves),
            confidence=max(0.0, min(1.0, confidence)),
            ambiguity=max(0.0, min(1.0, ambiguity)),
            evidence_ids=evidence_ids,
            notes=self._unique(notes, self.budget.max_notes),
        )
