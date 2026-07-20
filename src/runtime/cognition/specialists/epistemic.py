# -*- coding: utf-8 -*-
from __future__ import annotations

from core.cognition import CognitiveFrame, DiscourseProjection, EpistemicProjection, SemanticProjection


class EpistemicCortex:
    """Giữ claim trong phạm vi evidence; không quyết định giọng."""

    def project(
        self,
        frame: CognitiveFrame,
        discourse: DiscourseProjection,
        semantic: SemanticProjection,
    ) -> EpistemicProjection:
        scope = ["user_text", "public_history"]
        refs = list(dict.fromkeys((*discourse.evidence_ids, *semantic.evidence_ids)))
        if frame.grounding_context:
            scope.append("runtime_grounding")
            refs.append("runtime:grounding")
        if frame.memory_available:
            scope.append("memory_as_continuity_only")
        missing: list[str] = []
        tool_eligible = semantic.action_requested
        uncertainty = max(discourse.ambiguity, semantic.ambiguity) * 0.65
        overread = 0.22
        if discourse.ambiguity_owner == "assistant":
            overread = 0.10
        elif semantic.user_act == "statement_or_social_bid":
            overread = 0.42
        if semantic.action_requested and not frame.grounding_context:
            missing.append("mechanical_action_result")
        return EpistemicProjection(
            grounding_scope=tuple(scope),
            missing_evidence=tuple(missing),
            uncertainty=min(1.0, uncertainty),
            overread_risk=overread,
            tool_eligible=tool_eligible,
            confidence=0.84 if refs else 0.58,
            evidence_ids=tuple(dict.fromkeys(refs)),
        )
