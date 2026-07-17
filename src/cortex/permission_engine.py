# -*- coding: utf-8 -*-
"""Permission engine. It constrains action space and never rewrites prose."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import PermissionReport, CanonicalTheoryOfMindReport, RelationalState, InquiryPlan


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class PermissionEngine:
    module_name = "permission_engine"

    def evaluate(self, frame: Any, tom: CanonicalTheoryOfMindReport, relation: RelationalState, inquiry: InquiryPlan, *, knowledge: Any = None) -> PermissionReport:
        evidence = list(_get(frame, "evidence", []) or [])
        privacy_levels = {str(_get(ev, "privacy_level", "normal") or "normal").lower() for ev in evidence}
        has_sensitive = bool(privacy_levels & {"private", "sensitive"})
        explicit_user_chat = bool(str(_get(frame, "user_text", "") or "").strip())
        public_sayable = not (has_sensitive and str(_get(frame, "channel", "")) not in {"chat", "test"})
        overread_brake = tom.global_overread_risk > 0.62 or tom.global_confidence < 0.42
        memory_storable = not has_sensitive and explicit_user_chat
        raw_storable = False
        # Direct web search đã bị gỡ. Tutor/research là lane riêng và không được
        # chiếm ``system_action`` của chat.
        allowed_search = False
        tease = relation.teasing_permission > 0.48 and relation.repair_need < 0.25 and not overread_brake
        proactivity = str(_get(frame, "channel", "")) != "chat" and relation.trust > 0.45 and relation.repair_need < 0.35
        max_intensity = _clamp(0.68 - relation.privacy_sensitivity * 0.22 - relation.repair_need * 0.35 - (0.18 if overread_brake else 0.0), 0.42)
        body_actions = ["none", "stillness", "face_user", "look_at_focus", "idle_shift", "turn_away_softly"]
        spatial = _get(frame, "spatial", None)
        if _clamp(_get(spatial, "obstruction_risk", 0.0), 0.0) < 0.35:
            body_actions.extend(["step_closer", "step_back", "approach_focus", "withdraw"])
        reactions = ["direct_answer", "practical_help", "clarify", "repair", "silence", "body_only"]
        if allowed_search:
            reactions.append("search")
        if tease:
            reactions.append("micro_tease")
        reason_bits = []
        if has_sensitive:
            reason_bits.append("sensitive evidence")
        if overread_brake:
            reason_bits.append("overread brake")
        if relation.repair_need > 0.35:
            reason_bits.append("repair priority")
        return PermissionReport(
            public_sayable=public_sayable,
            prompt_sayable=public_sayable,
            memory_storable=memory_storable,
            raw_evidence_storable=raw_storable,
            allowed_reaction=reactions,
            allowed_body_action=list(dict.fromkeys(body_actions)),
            allowed_search=allowed_search,
            allowed_tease=tease,
            allowed_proactivity=proactivity,
            max_intensity=max_intensity,
            reason="; ".join(reason_bits) or "Normal grounded action space.",
        )


__all__ = ["PermissionEngine"]
