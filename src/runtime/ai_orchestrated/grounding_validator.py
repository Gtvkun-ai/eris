# -*- coding: utf-8 -*-
"""Grounding boundary riêng cho autonomous speech.

Validator chạy hai lần:

1. preflight: trước khi gọi Surface Worker, kiểm tra SpeechIntent có quyền dùng
   anchor/evidence đó hay không;
2. postflight: sau khi có text, dùng grounding gate chung để chặn claim vượt
   quá evidence.

Surface Worker có quyền viết câu. Nó không có quyền tự cấp giác quan cho mình.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.grounding_surface_gate import evaluate_grounded_surface

from .cognitive_blackboard import TypedCognitiveBlackboard
from .initiative import SpeechIntent


@dataclass(frozen=True, slots=True)
class GroundingDecision:
    allowed: bool
    reason: str
    violation_code: str = ""


class AutonomousGroundingValidator:
    """Kiểm tra provenance trước và sau model call."""

    def __init__(self, *, logger: Any | None = None) -> None:
        self.logger = logger

    def validate_intent(
        self,
        intent: SpeechIntent,
        blackboard: TypedCognitiveBlackboard,
    ) -> GroundingDecision:
        scope = str(intent.plan.semantics.evidence_scope or "").strip().lower()
        if blackboard.privacy_blocked and scope.startswith("screen"):
            return GroundingDecision(False, "screen_privacy_blocked", "screen_privacy_blocked")
        if intent.anchor_type in {"screen", "activity"}:
            if not (blackboard.screen_fresh or blackboard.screen_title):
                return GroundingDecision(False, "screen_anchor_not_fresh", "missing_screen_anchor")
            available = set(blackboard.screen_evidence_refs)
            unknown = [ref for ref in intent.evidence_refs if ref not in available]
            if unknown:
                return GroundingDecision(False, "unknown_screen_evidence_ref", "unknown_evidence_ref")
        if intent.anchor_type == "conversation" and blackboard.reply_expected:
            return GroundingDecision(False, "waiting_for_user_reply", "conversation_baton_owned_by_user")
        if intent.anchor_type == "self" and not blackboard.public_seed_ready:
            return GroundingDecision(False, "private_seed_not_public", "private_cognition_boundary")
        if intent.anchor_type == "memory":
            if not blackboard.memory_available:
                return GroundingDecision(False, "memory_not_available", "missing_memory_provenance")
            if not intent.evidence_refs:
                return GroundingDecision(False, "memory_without_evidence", "missing_memory_provenance")
        if intent.anchor_type == "discovery" and not blackboard.discovery_ready:
            return GroundingDecision(False, "discovery_not_ready", "missing_discovery_artifact")
        if intent.anchor_type == "task" and not blackboard.engagement_active:
            return GroundingDecision(False, "engagement_not_active", "missing_engagement")
        return GroundingDecision(True, "intent_grounded")

    def validate_surface(
        self,
        text: str,
        *,
        report: Any,
        engine: Any,
    ) -> GroundingDecision:
        verdict = evaluate_grounded_surface(engine, str(text or ""), report=report)
        if bool(getattr(verdict, "allowed", False)):
            return GroundingDecision(True, "surface_grounded")
        code = str(getattr(verdict, "violation_code", "") or "grounding_blocked")
        return GroundingDecision(False, code, code)


__all__ = ["AutonomousGroundingValidator", "GroundingDecision"]
