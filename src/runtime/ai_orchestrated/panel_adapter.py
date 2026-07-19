# -*- coding: utf-8 -*-
"""Chiếu RuntimeMindState mới sang payload panel/body.

``identity_runtime`` là contract panel chính của Architecture C v5. Các block
emotion_debug/depth_v2/private_mind vẫn được giữ để body cũ không gãy trong lúc
migrate, nhưng không còn là nguồn ý nghĩa chính.
"""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import AI_RUNTIME_VERSION, RuntimeMindState
from .views import build_cognitive_views


def _mood_label(pleasantness: float, irritation: float) -> str:
    valence = pleasantness * 2.0 - 1.0
    if irritation >= 0.45 or valence <= -0.22:
        return "kho_chiu"
    if valence >= 0.22:
        return "vui"
    return "trung_tinh"


def _view(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    fn = getattr(value, "panel_view", None)
    if callable(fn):
        try:
            result = fn()
            return dict(result) if isinstance(result, Mapping) else {}
        except Exception:
            return {}
    return {}


def _top_scores(mapping: Mapping[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    rows: list[tuple[str, float]] = []
    for key, value in mapping.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        rows.append((str(key), max(-1.0, min(1.0, number))))
    rows.sort(key=lambda item: item[1], reverse=True)
    return [{"key": key, "value": round(value, 4)} for key, value in rows[:limit]]


def build_ai_panel_payload(
    state: RuntimeMindState,
    discovery: Any | None = None,
    initiative: Any | None = None,
    consolidator: Any | None = None,
    expression: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    appraisal = state.appraisal
    relation = state.relationship
    personality = state.personality.panel_view()
    identity = state.identity.panel_view()
    observation = dict(state.latest_observation or {})
    intention = dict(state.latest_intention or {})
    views = build_cognitive_views(state)
    discovery_view = _view(discovery)
    initiative_view = _view(initiative)
    consolidator_view = _view(consolidator)
    expression_view = dict(expression or {})

    valence = max(-1.0, min(1.0, appraisal.pleasantness * 2.0 - 1.0))
    arousal = max(appraisal.pressure, appraisal.irritation, appraisal.novelty * 0.65)
    mood = _mood_label(appraisal.pleasantness, appraisal.irritation)

    primary_relationship = {}
    relationships = identity.get("relationships", {})
    if isinstance(relationships, Mapping):
        primary_relationship = dict(relationships.get("primary_user", {}) or {})

    identity_runtime = {
        "schema": "eris.identity_runtime.panel.v1",
        "architecture": AI_RUNTIME_VERSION,
        "state_version": state.version,
        "turn_seq": state.last_applied_turn_seq,
        "updated_at": state.updated_at,
        "learning": {
            "enabled": bool(state.identity_learning_enabled),
            "mode": "normal" if state.identity_learning_enabled else "observe_only",
        },
        "summary": {
            "mood": mood,
            "valence": round(valence, 4),
            "arousal": round(arousal, 4),
            "identity": state.identity_prompt_context(),
            "relationship": relation.prompt_summary(),
        },
        "expression": expression_view,
        "appraisal": appraisal.to_dict(),
        "relationship": primary_relationship or relation.to_dict(),
        "relationship_compat": relation.to_dict(),
        "values_top": _top_scores(identity.get("values", {}) if isinstance(identity.get("values"), Mapping) else {}),
        "motives_top": _top_scores(identity.get("motives", {}) if isinstance(identity.get("motives"), Mapping) else {}),
        "defenses_top": _top_scores(identity.get("defenses", {}) if isinstance(identity.get("defenses"), Mapping) else {}),
        "emergent_values_top": _top_scores(identity.get("emergent_values", {}) if isinstance(identity.get("emergent_values"), Mapping) else {}),
        "active_motives": list(identity.get("active_motives", []) or [])[:4],
        "active_defenses": list(identity.get("active_defenses", []) or [])[:4],
        "active_conflict": dict(identity.get("active_conflict", {}) or {}),
        "value_choice": dict(identity.get("latest_value_choice", {}) or {}),
        "derived_forms": dict(identity.get("emergent_forms", {}) or {}),
        "active_forms": list(identity.get("active_forms", []) or [])[:6],
        "beliefs": dict(identity.get("beliefs", {}) or {}),
        "strategies": dict(identity.get("strategies", {}) or {}),
        "pending_strategies": list(identity.get("pending_strategies", []) or [])[-4:],
        "imprints": list(identity.get("imprints", []) or [])[-8:],
        "recent_identity_ledger": list(identity.get("recent_ledger", []) or [])[-12:],
        "recent_personality_trajectory": list(personality.get("recent_trajectory", []) or [])[-10:],
        "latest_observation": observation,
        "latest_intention": intention,
        "open_loops": list(state.open_loops[-6:]),
        "discovery": discovery_view,
        "initiative": initiative_view,
        "consolidation": consolidator_view,
        "authority": views.get("authority", {}),
        "controls": {
            "freeze_learning": "identity freeze on|off",
            "snapshot": "identity snapshot",
            "reset_mood": "identity reset mood",
            "reset_relationship": "identity reset relationship",
            "reset_discovery": "identity reset discovery",
        },
    }

    # Body hiện vẫn có panel cảm xúc 4 thanh, nhưng parser của nó chỉ đọc
    # ``emotion_debug.items``. Contract mới vì thế chiếu state Architecture C
    # sang đúng các key cơ học mà panel cần, thay vì để UI trắng hoặc lén quay
    # lại đọc Ni/Fe legacy.
    personality_mood = personality.get("mood", {}) if isinstance(personality.get("mood"), Mapping) else {}
    temperament = personality.get("temperament", {}) if isinstance(personality.get("temperament"), Mapping) else {}

    def metric(label: str, value: Any, *, group: str, note: str = "") -> dict[str, Any]:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        if numeric != numeric:
            numeric = 0.0
        return {
            "label": label,
            "value": round(max(0.0, min(1.0, numeric)), 4),
            "group": group,
            "note": note,
        }

    emotional_stability = 1.0 - max(
        arousal,
        appraisal.irritation,
        appraisal.pressure,
        appraisal.embarrassment * 0.65,
    )
    mood_inertia = max(
        float(personality_mood.get("anxiety_tension", 0.0) or 0.0),
        float(personality_mood.get("separation_distress", 0.0) or 0.0),
        float(temperament.get("rumination", 0.0) or 0.0) * 0.58,
    )
    attachment = float(primary_relationship.get("attachment_intensity", relation.closeness) or 0.0)
    warmth = max(
        appraisal.tenderness,
        float(temperament.get("warmth_expression", 0.0) or 0.0),
    )
    distance = 1.0 - max(
        float(primary_relationship.get("closeness", relation.closeness) or 0.0),
        float(primary_relationship.get("familiarity", relation.familiarity) or 0.0) * 0.55,
    )
    intimacy = max(
        float(primary_relationship.get("closeness", relation.closeness) or 0.0),
        attachment * 0.72,
    )
    overload = max(appraisal.pressure, arousal * 0.55, appraisal.irritation * 0.60)
    thought_pressure = max(appraisal.curiosity, appraisal.novelty, appraisal.pressure * 0.65)

    emotion_items = {
        "calm_aroused": metric("bình tĩnh <-> kích thích", arousal, group="core"),
        "emotional_stability": metric("ổn định cảm xúc", emotional_stability, group="core"),
        "mood_inertia": metric("quán tính mood", mood_inertia, group="core"),
        "overload": metric("quá tải", overload, group="load"),
        "attachment": metric("mức quan tâm / gắn bó", attachment, group="bond"),
        "tenderness": metric("dịu dàng", appraisal.tenderness, group="bond"),
        "warmth": metric("độ ấm áp", warmth, group="tone"),
        "intimacy": metric("mức thân mật", intimacy, group="tone"),
        "distance": metric("giữ khoảng cách", distance, group="tone"),
        "irritation": metric("khó chịu", appraisal.irritation, group="friction"),
        "perceived_rejection": metric("cảm giác bị từ chối", relation.rupture, group="friction"),
        "curiosity": metric("tò mò", appraisal.curiosity, group="attention"),
        "thought_stream_pressure": metric("dòng suy nghĩ tăng", thought_pressure, group="attention"),
        "playfulness": metric(
            "mức đùa",
            float(primary_relationship.get("playful_safety", relation.playful_safety) or 0.0),
            group="tone",
        ),
        "restraint": metric(
            "tự kiềm chế",
            float(temperament.get("social_guardedness", 0.0) or 0.0),
            group="control",
        ),
    }
    if expression_view:
        emotion_items["expression_preset"] = {
            "label": "preset biểu hiện",
            "value": str(expression_view.get("preset", expression_view.get("name", "")) or ""),
            "group": "surface",
            "note": str(expression_view.get("reason", "") or ""),
        }

    emotion_debug = {
        "architecture": AI_RUNTIME_VERSION,
        "summary": {
            "label": "vui / kho_chiu / trung_tinh",
            "value": mood,
            "valence": round(valence, 3),
            "arousal": round(arousal, 3),
            "state": str(observation.get("relationship_meaning", "neutral") or "neutral"),
        },
        "items": emotion_items,
        "appraisal": appraisal.to_dict(),
        "relationship": relation.to_dict(),
        "personality": personality,
        "identity": identity,
        "cognitive_views": views,
        "discovery": discovery_view,
        "identity_expression": expression_view,
    }
    # depth_v2 giờ là compatibility alias của panel identity mới. Body v5 đọc
    # identity_runtime; body cũ vẫn có dữ liệu đủ để không trắng panel.
    depth_v2 = {
        "architecture": AI_RUNTIME_VERSION,
        "live": bool(observation or intention),
        "state_version": state.version,
        "turn_seq": state.last_applied_turn_seq,
        "relationship": relation.to_dict(),
        "appraisal": appraisal.to_dict(),
        "personality": personality,
        "identity": identity,
        "open_loops": list(state.open_loops),
        "latest_observation": observation,
        "latest_intention": intention,
        "authority": views["authority"],
        "discovery": discovery_view,
        "initiative": initiative_view,
        "expression": expression_view,
    }
    private_mind_digest = {
        "architecture": AI_RUNTIME_VERSION,
        "surface": False,
        "open_loops": list(state.open_loops[-5:]),
        "latest_intention": intention,
        "personality_direction_30d": personality.get("direction_30d", {}),
        "active_personality_forms": personality.get("active_forms", []),
        "active_identity_forms": identity.get("active_forms", []),
        "active_motives": identity.get("active_motives", []),
        "activated_defenses": identity.get("active_defenses", []),
        "active_conflict": identity.get("active_conflict", {}),
        "value_choice": identity.get("latest_value_choice", {}),
        "self_interpretation": observation.get("self_interpretation", {}),
        "expression": expression_view,
        "discovery": {
            "current_activity": discovery_view.get("current_activity", {}),
            "ready_to_share": discovery_view.get("ready_to_share", []),
        },
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
        "identity_summary": state.identity_prompt_context(),
        "personality_version": personality.get("version", 0),
        "identity_version": identity.get("version", 0),
        "identity_imprints": identity.get("imprints", [])[-6:],
        "pending_strategies": identity.get("pending_strategies", [])[-3:],
        "recent_trajectory": personality.get("recent_trajectory", [])[-6:],
        "last_event": relation.last_event,
        "memory_candidates": [dict(item) for item in state.memory_candidates[-4:]],
        "discovery_archive_count": int(discovery_view.get("archive_count", 0) or 0),
        "discovery_recent": list(discovery_view.get("recent", []) or [])[-4:],
        "initiative": initiative_view,
        "consolidation": consolidator_view,
    }
    return {
        "identity_runtime": identity_runtime,
        "emotion_debug": emotion_debug,
        "depth_v2": depth_v2,
        "private_mind_digest": private_mind_digest,
        "private_life_digest": private_life_digest,
        "cognitive_views": views,
    }


__all__ = ["build_ai_panel_payload"]
