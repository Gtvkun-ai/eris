# -*- coding: utf-8 -*-
"""Áp brief vào IntentionPlan mà không viết câu public."""

from __future__ import annotations

from core.cognition import PreResponseCognitiveBrief
from runtime.ai_orchestrated.contracts import IntentionPlan


_STRATEGY_BY_MOVE = {
    "self_elaborate": ("carry_own_thread", "continuity", "dry_tease"),
    "repair_previous_response": ("direct_repair", "accuracy", "repair"),
    "explain_relevance": ("explain_relevance", "coherence", "focused"),
    "clarify_literal_reference": ("literal_clarification", "accuracy", "focused"),
    "clarify_previous_phrase": ("literal_clarification", "accuracy", "focused"),
    "clarify_previous_statement": ("literal_clarification", "accuracy", "focused"),
    "repair_assumption": ("repair_assumption", "accuracy", "repair"),
    "acknowledge_close": ("respect_topic_close", "boundary", "neutral"),
}


def apply_cognitive_brief_to_plan(
    plan: IntentionPlan,
    brief: PreResponseCognitiveBrief,
) -> IntentionPlan:
    """Cortex được quyền khóa move, không được viết wording.

    Chỉ các discourse move confidence cao mới ghi đè planner. Các lượt trung tính
    giữ nguyên plan của model, tránh biến deterministic rules thành ông chủ mới.
    """

    if brief.confidence < 0.72:
        return plan
    if "discourse" in brief.degraded_modules:
        return plan
    if brief.needs_deep_inference and brief.ambiguity_owner != "assistant":
        return plan
    mapped = _STRATEGY_BY_MOVE.get(brief.response_move)
    if mapped is None:
        return plan
    strategy, value_focus, performance_hint = mapped
    data = plan.to_dict()
    data.update(
        {
            "speak": True,
            "motive": "resolve_current_discourse_move",
            "strategy": strategy,
            "value_focus": value_focus,
            "topic": brief.primary_goal,
            "importance": max(0.74, float(plan.importance or 0.0)),
            "intrusion_risk": 0.0,
            "confidence": max(0.82, float(plan.confidence or 0.0)),
            "performance_hint": performance_hint,
            "evidence_refs": list(dict.fromkeys((*plan.evidence_refs, *brief.evidence_ids)))[:5],
            "notes": f"cortex_v2:{brief.discourse_relation}:{brief.response_move}",
        }
    )
    # Repair/continuation là lời nói, không phải lý do để tool tự bật.
    if brief.response_move in _STRATEGY_BY_MOVE:
        data["tool_intent"] = ""
        data["tool_input"] = ""
    return IntentionPlan.from_mapping(data, channel=plan.channel)
