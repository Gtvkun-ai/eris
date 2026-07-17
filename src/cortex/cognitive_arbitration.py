# -*- coding: utf-8 -*-
"""Cognitive arbitration over explicit simulated action outcomes."""
from __future__ import annotations
from runtime.canonical_cognition import ArbitrationResult, SimulatedActionOutcome, InquiryPlan, PermissionReport


class CognitiveArbitrationEngine:
    module_name = "cognitive_arbitration"

    @staticmethod
    def utility(item: SimulatedActionOutcome) -> float:
        return (
            item.usefulness
            + item.continuity_gain * 0.48
            - item.social_risk * 0.58
            - item.privacy_risk * 0.86
            - item.relationship_cost * 0.55
        )

    def resolve(self, simulations: list[SimulatedActionOutcome], inquiry: InquiryPlan, permission: PermissionReport) -> ArbitrationResult:
        allowed = [x for x in simulations if not (x.action_type == "search" and not permission.allowed_search)]
        constrained = None
        if inquiry.action == "ask_user":
            constrained = "ask"
        elif inquiry.action == "suppress_inquiry":
            constrained = None
        winner = next((x for x in allowed if x.action_type == constrained), None) if constrained else None
        if winner is None:
            winner = max(allowed, key=self.utility, default=None)
        action = winner.action_type if winner else "stay_silent"
        drive_map = {
            "practical_help": "practical_help",
            "repair": "repair",
            "ask": "curiosity",
            "search": "knowledge_acquisition",
            "stay_silent": "restraint",
            "body_only": "presence",
            "tease": "playfulness",
        }
        winning_drive = drive_map.get(action, action)
        compromise = action
        if action == "practical_help" and inquiry.privacy_cost > 0.35:
            compromise = "answer_directly_without_intrusive_probe"
        elif action == "repair":
            compromise = "acknowledge_then_fix"
        return ArbitrationResult(
            competing_drives=[drive_map.get(x.action_type, x.action_type) for x in allowed],
            winning_drive=winning_drive,
            suppressed_drives=[drive_map.get(x.action_type, x.action_type) for x in allowed if x is not winner],
            compromise_action=compromise,
            reason=f"Winner={action}; utility={self.utility(winner):.3f}" if winner else "No allowed candidate; restraint wins.",
            confidence=max(0.0, min(1.0, winner.confidence if winner else 0.30)),
        )


__all__ = ["CognitiveArbitrationEngine"]
