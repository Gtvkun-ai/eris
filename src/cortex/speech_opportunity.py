# -*- coding: utf-8 -*-
"""Decides whether speech is worth the interruption cost."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import SpeechOpportunity, ActionCommitment, HomeostaticState, PermissionReport


class SpeechOpportunityEngine:
    module_name = "speech_opportunity"

    def evaluate(self, frame: Any, agency: ActionCommitment, homeostasis: HomeostaticState, permission: PermissionReport) -> SpeechOpportunity:
        channel = str(getattr(frame, "channel", "") or "")
        direct_user_turn = bool(str(getattr(frame, "user_text", "") or "").strip())
        if not permission.public_sayable:
            return SpeechOpportunity(mode="silence", speech_allowed=False, reason_to_stay_silent="Public surface is not permitted.", urgency=0.0, interruption_cost=0.0)
        if agency.intent in {"stay_silent", "observe", "withdraw"}:
            return SpeechOpportunity(mode="silence", speech_allowed=False, reason_to_stay_silent="Agency committed to restraint.", urgency=0.08, interruption_cost=0.0)
        if agency.intent == "body_only":
            return SpeechOpportunity(mode="body_only_reaction", speech_allowed=False, reason_to_stay_silent="Body-only action has higher utility.", urgency=0.18, interruption_cost=0.0)
        if not direct_user_turn and not permission.allowed_proactivity:
            return SpeechOpportunity(mode="silence", speech_allowed=False, reason_to_stay_silent="No direct request and proactivity is not permitted.", urgency=0.08, interruption_cost=homeostasis.speech_cost)
        mode = "direct_answer" if channel == "chat" else "reengagement"
        if agency.intent == "repair":
            mode = "practical_help"
        elif homeostasis.regulation_policy in {"short_grounded", "reduce_speech", "repair"}:
            mode = "practical_help"
        urgency = 0.78 if direct_user_turn else 0.34
        if agency.intent in {"search", "repair"}:
            urgency = max(urgency, 0.86)
        return SpeechOpportunity(
            mode=mode,  # type: ignore[arg-type]
            speech_allowed=True,
            reason_to_speak="Direct request or committed useful action outweighs speech cost.",
            reason_to_stay_silent="Speech should be suppressed if execution fails or interruption cost rises.",
            urgency=max(0.0, min(1.0, urgency)),
            interruption_cost=max(0.0, min(1.0, homeostasis.speech_cost * (0.22 if direct_user_turn else 0.82))),
        )


__all__ = ["SpeechOpportunityEngine"]
