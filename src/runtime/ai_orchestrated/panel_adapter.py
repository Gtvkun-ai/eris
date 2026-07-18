# -*- coding: utf-8 -*-
"""Chiếu RuntimeMindState mới sang payload panel/body tương thích.

Không đọc legacy internal_state, không gọi cognition engine và không sửa Decision.
Mục đích là giữ panel sống sau khi Ni/Ti/Fe cũ rời production path.
"""

from __future__ import annotations

from typing import Any

from .contracts import AI_RUNTIME_VERSION, RuntimeMindState
from .views import build_cognitive_views


def _mood_label(pleasantness: float, irritation: float) -> str:
    valence = pleasantness * 2.0 - 1.0
    if irritation >= 0.45 or valence <= -0.22:
        return "kho_chiu"
    if valence >= 0.22:
        return "vui"
    return "trung_tinh"


def build_ai_panel_payload(state: RuntimeMindState) -> dict[str, Any]:
    appraisal = state.appraisal
    relation = state.relationship
    personality = state.personality.panel_view()
    observation = dict(state.latest_observation or {})
    intention = dict(state.latest_intention or {})
    views = build_cognitive_views(state)
    valence = max(-1.0, min(1.0, appraisal.pleasantness * 2.0 - 1.0))
    arousal = max(appraisal.pressure, appraisal.irritation, appraisal.novelty * 0.65)
    mood = _mood_label(appraisal.pleasantness, appraisal.irritation)

    emotion_debug = {
        "architecture": AI_RUNTIME_VERSION,
        "summary": {
            "label": "vui / kho_chiu / trung_tinh",
            "value": mood,
            "valence": round(valence, 3),
            "arousal": round(arousal, 3),
            "state": str(observation.get("relationship_meaning", "neutral") or "neutral"),
        },
        "appraisal": appraisal.to_dict(),
        "relationship": relation.to_dict(),
        "personality": personality,
        "cognitive_views": views,
    }
    depth_v2 = {
        "architecture": AI_RUNTIME_VERSION,
        "live": bool(observation or intention),
        "state_version": state.version,
        "turn_seq": state.last_applied_turn_seq,
        "relationship": relation.to_dict(),
        "appraisal": appraisal.to_dict(),
        "personality": personality,
        "open_loops": list(state.open_loops),
        "latest_observation": observation,
        "latest_intention": intention,
        "authority": views["authority"],
    }
    private_mind_digest = {
        "architecture": AI_RUNTIME_VERSION,
        "surface": False,
        "open_loops": list(state.open_loops[-5:]),
        "latest_intention": intention,
        "personality_direction_30d": personality.get("direction_30d", {}),
        "active_personality_forms": personality.get("active_forms", []),
        "self_interpretation": observation.get("self_interpretation", {}),
        "latest_observation": {
            key: observation.get(key)
            for key in (
                "user_act",
                "relationship_meaning",
                "continuity",
                "repair_needed",
                "confidence",
                "notes",
            )
            if key in observation
        },
    }
    private_life_digest = {
        "architecture": AI_RUNTIME_VERSION,
        "relationship_summary": relation.prompt_summary(),
        "personality_summary": personality.get("prompt_summary", ""),
        "personality_version": personality.get("version", 0),
        "recent_trajectory": personality.get("recent_trajectory", [])[-6:],
        "last_event": relation.last_event,
        "memory_candidates": [dict(item) for item in state.memory_candidates[-4:]],
    }
    return {
        "emotion_debug": emotion_debug,
        "depth_v2": depth_v2,
        "private_mind_digest": private_mind_digest,
        "private_life_digest": private_life_digest,
        "cognitive_views": views,
    }


__all__ = ["build_ai_panel_payload"]
