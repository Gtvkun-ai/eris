# -*- coding: utf-8 -*-
"""Các view debug thuần từ một RuntimeMindState duy nhất.

Ni/Ti/Fe/Appraisal và Personality không còn là engine tự đọc raw text. Chúng là
các cửa sổ nhìn vào cùng observation/profile đã được reducer chấp nhận. View
không ghi state, không sửa lời và không gọi model.
"""

from __future__ import annotations

from typing import Any

from .contracts import RuntimeMindState


def build_cognitive_views(state: RuntimeMindState) -> dict[str, Any]:
    observation = dict(state.latest_observation or {})
    relationship = state.relationship
    appraisal = state.appraisal
    personality = state.personality
    personality_view = personality.panel_view()
    interpretation = observation.get("self_interpretation", {})
    consequence = observation.get("consequence", {})
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
        "personality": personality_view,
        "development": {
            "self_interpretation": dict(interpretation) if isinstance(interpretation, dict) else {},
            "consequence": dict(consequence) if isinstance(consequence, dict) else {},
            "trait_signals": list(observation.get("trait_signals", []) or []),
            "direction_30d": personality_view.get("direction_30d", {}),
            "active_forms": personality_view.get("active_forms", []),
            "no_maturity_target": True,
        },
        "authority": {
            "source": str(observation.get("source", "none") or "none"),
            "confidence": float(observation.get("confidence", 0.0) or 0.0),
            "state_version": state.version,
            "personality_version": personality.version,
            "last_applied_turn_seq": state.last_applied_turn_seq,
            "text_mutation_authority": False,
            "state_write_authority": "StateReducer",
            "personality_write_authority": "StateReducer",
            "type_labels_in_prompt": False,
        },
    }


__all__ = ["build_cognitive_views"]
