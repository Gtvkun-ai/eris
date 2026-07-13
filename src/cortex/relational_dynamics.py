# -*- coding: utf-8 -*-
"""Relational state engine with correction/rupture tracking."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import RelationalState


def _get(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        if obj is None:
            break
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class RelationalDynamicsEngine:
    module_name = "relational_dynamics"

    def evaluate(self, frame: Any, *, legacy_frame: Any = None) -> RelationalState:
        source = _get(legacy_frame, ("relationship_state", "relational_state", "relationship"), None)
        text = str(_get(frame, ("user_text",), "") or "").lower()
        correction = any(x in text for x in ("không phải", "ý tôi", "sai", "chưa", "vẫn thiếu", "làm tiếp"))
        temporal = getattr(frame, "temporal", None)
        meaning_debt = _clamp(getattr(temporal, "meaning_debt", 0.0), 0.0)
        trust = _clamp(_get(source, ("trust", "trust_score"), 0.55), 0.55)
        familiarity = _clamp(_get(source, ("familiarity", "closeness"), 0.55), 0.55)
        rupture = _clamp(_get(source, ("rupture", "rupture_score"), 0.0), 0.0)
        rupture = _clamp(rupture + (0.22 if correction else 0.0) + meaning_debt * 0.18)
        repair_need = _clamp(max(_get(source, ("repair_need",), 0.0), rupture * 0.82, 0.65 if correction else 0.0))
        privacy = _clamp(_get(source, ("privacy_sensitivity",), 0.48), 0.48)
        tease = _clamp(_get(source, ("teasing_permission", "tease_permission"), 0.35), 0.35)
        if correction or repair_need > 0.5:
            tease = min(tease, 0.08)
        rhythm = str(_get(source, ("user_specific_rhythm",), "") or "") or str(getattr(temporal, "rhythm", "unknown") or "unknown")
        return RelationalState(
            trust=trust,
            familiarity=familiarity,
            rupture=rupture,
            repair_need=repair_need,
            preferred_distance=_clamp(_get(source, ("preferred_distance",), 0.5), 0.5),
            attachment_visibility=_clamp(_get(source, ("attachment_visibility",), 0.2), 0.2),
            dignity_defense=_clamp(_get(source, ("dignity_defense",), 0.55), 0.55),
            teasing_permission=tease,
            privacy_sensitivity=privacy,
            overread_correction=_clamp(_get(source, ("overread_correction",), 0.5), 0.5),
            user_specific_rhythm=rhythm,
            cultural_boundary=_clamp(_get(source, ("cultural_boundary",), 0.5), 0.5),
        )


__all__ = ["RelationalDynamicsEngine"]
