# -*- coding: utf-8 -*-
"""Volitional commitment layer for canonical V3."""
from __future__ import annotations
from runtime.canonical_cognition import ActionCommitment, ArbitrationResult, InquiryPlan


class AgencyEngine:
    module_name = "agency_engine"

    def commit(self, arbitration: ArbitrationResult, inquiry: InquiryPlan) -> ActionCommitment:
        mapping = {
            "practical_help": "speak",
            "repair": "repair",
            "curiosity": "ask",
            "knowledge_acquisition": "search",
            "restraint": "stay_silent",
            "presence": "body_only",
            "playfulness": "speak",
        }
        intent = mapping.get(arbitration.winning_drive, "speak")
        goal = {
            "repair": "repair the failed interpretation/action without defending it",
            "search": "ground the answer with an allowed knowledge action",
            "ask": "reduce decisive ambiguity with minimum intrusion",
            "stay_silent": "preserve user focus and avoid low-value speech",
            "body_only": "maintain presence without unnecessary speech",
        }.get(intent, "resolve the current request without overread")
        return ActionCommitment(
            intent=intent,  # type: ignore[arg-type]
            goal_preserved=goal,
            commitment_strength=arbitration.confidence,
            reversibility=0.95 if intent in {"ask", "stay_silent", "body_only"} else 0.74,
            reason=arbitration.reason,
        )


__all__ = ["AgencyEngine"]
