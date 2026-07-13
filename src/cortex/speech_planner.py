# -*- coding: utf-8 -*-
"""Canonical speech-act planner. It plans intent, not prose."""
from __future__ import annotations

from typing import Any

from runtime.canonical_cognition import (
    CanonicalMeaningReport,
    PermissionReport,
    RelationalState,
    SpeechOpportunity,
    SpeechPlan,
)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


class SpeechPlannerEngine:
    module_name = "speech_core"

    def plan(
        self,
        frame: Any,
        opportunity: SpeechOpportunity,
        meaning: CanonicalMeaningReport,
        relation: RelationalState,
        permission: PermissionReport,
    ) -> SpeechPlan:
        text = str(getattr(frame, "user_text", "") or "").strip().lower()
        technical = any(x in text for x in ("code", "file", "fix", "lỗi", "bug", "repo", "src", "pipeline", "kiến trúc", "json", "python"))
        correction = any(x in text for x in ("không phải", "chưa", "sai", "tôi nhớ là", "ý tôi"))
        if not opportunity.speech_allowed:
            act = "compress"
        elif correction or relation.repair_need > 0.48:
            act = "repair"
        elif meaning.needs_clarification:
            act = "clarify"
        elif technical:
            act = "technical_diagnosis"
        else:
            act = "answer"
        return SpeechPlan(
            speech_act=act,  # type: ignore[arg-type]
            tone="cold_soft" if relation.rupture < 0.4 else "restrained_repair",
            warmth=_clamp(0.20 + relation.trust * 0.32),
            restraint=_clamp(0.35 + (1.0 - permission.max_intensity) * 0.55),
            directness=0.90 if technical or correction else 0.72,
            tease_level=0.18 if permission.allowed_tease and not technical and not correction else 0.0,
            technical_depth=0.88 if technical else 0.35,
            emotional_visibility=_clamp(relation.attachment_visibility * 0.55),
            must_include=["answer-first", "state uncertainty where needed"] + (["acknowledge correction"] if correction else []),
            must_avoid=list(getattr(getattr(frame, "tom", None), "forbidden_assumptions", []) or []) + ["unsupported current-state claims"],
        )


__all__ = ["SpeechPlannerEngine"]
