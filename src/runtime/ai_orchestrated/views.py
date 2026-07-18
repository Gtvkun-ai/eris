# -*- coding: utf-8 -*-
"""Các view debug thuần từ một RuntimeMindState duy nhất.

Ni/Ti/Fe/Appraisal không còn là bốn engine tự đọc lại raw text. Chúng là bốn
cửa sổ nhìn vào cùng một CognitiveObservation đã được observer tạo và reducer
chấp nhận. View không ghi state, không sửa lời, không gọi model.
"""

from __future__ import annotations

from typing import Any

from .contracts import RuntimeMindState


def build_cognitive_views(state: RuntimeMindState) -> dict[str, Any]:
    observation = dict(state.latest_observation or {})
    relationship = state.relationship
    appraisal = state.appraisal
    return {
        "ni": {
            "continuity": str(observation.get("continuity", "new_or_neutral") or "new_or_neutral"),
            "open_loops": list(state.open_loops),
            "novelty": appraisal.novelty,
            "source_turn_seq": int(observation.get("turn_seq", 0) or 0),
        },
        "fe": {
            "user_act": str(observation.get("user_act", "unknown") or "unknown"),
            "relationship_meaning": str(observation.get("relationship_meaning", "neutral") or "neutral"),
            "relational_trust": relationship.relational_trust,
            "closeness": relationship.closeness,
            "playful_safety": relationship.playful_safety,
            "rupture": relationship.rupture,
        },
        "ti": {
            "assistant_fault_probability": float(observation.get("assistant_fault_probability", 0.0) or 0.0),
            "competence_trust": relationship.competence_trust,
            "factual_reliability": relationship.factual_reliability,
            "boundary_safety": relationship.boundary_safety,
            "repair_needed": bool(observation.get("repair_needed", False)),
        },
        "appraisal": appraisal.to_dict(),
        "authority": {
            "source": str(observation.get("source", "none") or "none"),
            "confidence": float(observation.get("confidence", 0.0) or 0.0),
            "state_version": state.version,
            "last_applied_turn_seq": state.last_applied_turn_seq,
            "text_mutation_authority": False,
            "state_write_authority": "StateReducer",
        },
    }


__all__ = ["build_cognitive_views"]
