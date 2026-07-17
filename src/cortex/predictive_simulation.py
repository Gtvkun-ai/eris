# -*- coding: utf-8 -*-
"""Small explicit action-outcome simulator for V3 arbitration."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import SimulatedActionOutcome, InquiryPlan, PermissionReport, RelationalState


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class PredictiveSimulationEngine:
    module_name = "predictive_simulation"

    def simulate(self, frame: Any, inquiry: InquiryPlan, permission: PermissionReport, relation: RelationalState) -> list[SimulatedActionOutcome]:
        channel = str(getattr(frame, "channel", "") or "")
        chat = channel == "chat"
        homeostasis = getattr(frame, "homeostasis", None)
        speech_cost = float(getattr(homeostasis, "speech_cost", 0.2) or 0.2)
        silence_need = float(getattr(homeostasis, "silence_recovery_need", 0.1) or 0.1)
        meaning = getattr(frame, "meaning", None)
        ambiguity = float(getattr(meaning, "ambiguity", 0.3) or 0.3)

        actions = ["practical_help", "ask", "stay_silent", "body_only", "repair"]
        if permission.allowed_tease:
            actions.append("tease")

        out: list[SimulatedActionOutcome] = []
        for action in actions:
            usefulness = {
                "practical_help": 0.93 if chat else 0.48,
                "ask": 0.80 if inquiry.action == "ask_user" else 0.36,
                "repair": 0.94 if relation.repair_need > 0.4 else 0.48,
                "stay_silent": 0.12 if chat else 0.70,
                "body_only": 0.10 if chat else 0.58,
                "tease": 0.48,
            }.get(action, 0.4)
            social_risk = {
                "practical_help": 0.10,
                "ask": 0.22 + ambiguity * 0.12,
                "repair": 0.08,
                "stay_silent": 0.06,
                "body_only": 0.06,
                "tease": 0.22 + relation.rupture * 0.55,
            }.get(action, 0.2)
            privacy_risk = inquiry.privacy_cost if action == "ask" else 0.02
            relation_cost = 0.62 if chat and action in {"stay_silent", "body_only"} else social_risk * 0.42
            if action == "tease" and relation.repair_need > 0.25:
                relation_cost += 0.48
            continuity = {
                "practical_help": 0.74,
                "repair": 0.82,
                "ask": 0.52,
                "stay_silent": 0.50,
                "body_only": 0.46,
                "tease": 0.44,
            }.get(action, 0.4)
            if action in {"practical_help", "repair", "ask", "tease"}:
                usefulness -= speech_cost * 0.15
            if action in {"stay_silent", "body_only"}:
                usefulness += silence_need * 0.35
            expected = {
                "practical_help": "User receives concrete progress.",
                "repair": "Correction is acknowledged and the failed action is replaced.",
                "ask": "Ambiguity is reduced at interruption cost.",
                "stay_silent": "No interruption; may feel unresponsive in direct chat.",
                "body_only": "Presence is preserved without speech.",
                "tease": "Warmth may increase if relational timing is safe.",
            }.get(action, "Context-dependent result.")
            out.append(SimulatedActionOutcome(
                action_type=action,
                expected_user_reaction=expected,
                usefulness=_clamp(usefulness),
                social_risk=_clamp(social_risk),
                privacy_risk=_clamp(privacy_risk),
                relationship_cost=_clamp(relation_cost),
                continuity_gain=_clamp(continuity),
                confidence=0.76 if action in {"practical_help", "repair"} else 0.68,
            ))
        return out


__all__ = ["PredictiveSimulationEngine"]
