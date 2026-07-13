# -*- coding: utf-8 -*-
"""Homeostatic regulation engine for ERIS V3."""
from __future__ import annotations

from typing import Any
from runtime.canonical_cognition import HomeostaticState


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


class HomeostasisEngine:
    module_name = "homeostasis"

    def evaluate(self, frame: Any, *, legacy_frame: Any = None) -> HomeostaticState:
        state = _get(legacy_frame, ("internal_state_before", "internal_state_after", "internal_state"), None)
        temporal = getattr(frame, "temporal", None)
        salience = getattr(frame, "salience", None)
        budget = str(getattr(frame, "budget_mode", "normal") or "normal")

        energy = _clamp(_get(state, ("energy", "energy_budget", "vitality"), 0.68), 0.68)
        base_cognitive = _clamp(_get(state, ("cognitive_load", "cognitive_tension", "load"), 0.24), 0.24)
        deep_cost = 0.18 if budget == "deep" else (0.08 if budget == "reflection" else 0.0)
        salience_pressure = _clamp(_get(salience, ("broadcast_priority", "urgency"), 0.0), 0.0) * 0.18
        repetition = _clamp(getattr(temporal, "repetition_fatigue", 0.0), 0.0)
        cognitive_load = _clamp(base_cognitive + deep_cost + salience_pressure + repetition * 0.25)
        social_load = _clamp(_get(state, ("social_load", "social_pressure"), 0.18), 0.18)
        exposure = _clamp(_get(state, ("exposure_load", "exposure_recoil"), 0.10), 0.10)
        curiosity = _clamp(_get(state, ("curiosity_pressure", "curiosity"), 0.28), 0.28)
        attachment = _clamp(_get(state, ("attachment_pressure", "attachment"), 0.15), 0.15)
        irritation = _clamp(_get(state, ("irritation_pressure", "irritation"), 0.05), 0.05)
        tenderness = _clamp(_get(state, ("tenderness_pressure", "tenderness"), 0.10), 0.10)
        correction_pressure = _clamp(getattr(temporal, "meaning_debt", 0.0), 0.0)
        irritation = _clamp(irritation + correction_pressure * 0.10)
        silence_need = _clamp(max(0.0, cognitive_load - 0.55) * 1.2 + max(0.0, social_load - 0.60) + repetition * 0.20)
        speech_cost = _clamp(0.12 + cognitive_load * 0.48 + social_load * 0.24 + exposure * 0.12)
        readiness = _clamp(energy * (1.0 - cognitive_load * 0.52) * (1.0 - exposure * 0.18))

        channel = str(getattr(frame, "channel", "") or "")
        if correction_pressure > 0.55:
            policy = "repair"
        elif exposure > 0.80:
            policy = "withdraw"
        elif cognitive_load > 0.80 or irritation > 0.78:
            policy = "short_grounded"
        elif social_load > 0.76 or silence_need > 0.72:
            policy = "reduce_speech"
        elif channel == "chat":
            policy = "act_practically"
        elif readiness < 0.24:
            policy = "observe_only"
        else:
            policy = "normal"

        return HomeostaticState(
            energy_budget=energy,
            cognitive_load=cognitive_load,
            social_load=social_load,
            exposure_load=exposure,
            curiosity_pressure=curiosity,
            attachment_pressure=attachment,
            irritation_pressure=irritation,
            tenderness_pressure=tenderness,
            silence_recovery_need=silence_need,
            speech_cost=speech_cost,
            action_readiness=readiness,
            regulation_policy=policy,  # type: ignore[arg-type]
        )


__all__ = ["HomeostasisEngine"]
