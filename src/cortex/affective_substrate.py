# -*- coding: utf-8 -*-
"""Affective substrate. Affect remains pressure, never an automatic claim."""
from __future__ import annotations

from typing import Any
from runtime.canonical_cognition import AffectiveState, HomeostaticState


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


class AffectiveSubstrateEngine:
    module_name = "affective_substrate"

    def evaluate(self, frame: Any, homeostasis: HomeostaticState, *, legacy_frame: Any = None) -> AffectiveState:
        state = _get(legacy_frame, ("internal_state_before", "internal_state_after", "internal_state"), None)
        temporal = getattr(frame, "temporal", None)
        relation = getattr(frame, "relation", None)
        arousal = _clamp(_get(state, ("arousal",), 0.30), 0.30)
        tension = _clamp(_get(state, ("tension", "cognitive_tension"), homeostasis.cognitive_load), homeostasis.cognitive_load)
        restraint = _clamp(_get(state, ("restraint", "restraint_pressure"), 0.46), 0.46)
        continuity = _clamp(_get(state, ("continuity_anxiety", "continuity_pressure"), 0.10), 0.10)
        repair_pressure = _clamp(getattr(temporal, "meaning_debt", 0.0), 0.0)
        rupture = _clamp(getattr(relation, "rupture", 0.0), 0.0)
        tension = _clamp(tension + repair_pressure * 0.18 + rupture * 0.20)
        restraint = _clamp(restraint + repair_pressure * 0.12 + homeostasis.exposure_load * 0.18)
        residue = {
            "tension": tension,
            "irritation": homeostasis.irritation_pressure,
            "tenderness": homeostasis.tenderness_pressure,
            "repair_pressure": repair_pressure,
            "repetition_fatigue": _clamp(getattr(temporal, "repetition_fatigue", 0.0), 0.0),
        }
        return AffectiveState(
            energy=homeostasis.energy_budget,
            fatigue=_clamp(1.0 - homeostasis.energy_budget),
            arousal=arousal,
            tension=tension,
            curiosity=homeostasis.curiosity_pressure,
            restraint=restraint,
            attachment_pressure=homeostasis.attachment_pressure,
            irritation=homeostasis.irritation_pressure,
            tenderness=homeostasis.tenderness_pressure,
            exposure_recoil=homeostasis.exposure_load,
            continuity_anxiety=continuity,
            affective_residue=residue,
        )


__all__ = ["AffectiveSubstrateEngine"]
