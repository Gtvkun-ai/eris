# -*- coding: utf-8 -*-
"""Proposal sources chuyển cơ hội runtime thành ActionProposal input có provenance.

Affordance, silence và body-only đều đi qua cùng một adapter. Ingress không còn
biết cách chấm từng nguồn, còn Subject Core vẫn là nơi enrich/rank theo history,
need, value và competence.
"""
from __future__ import annotations

from typing import Any, Sequence

from cortex.subject.service import SubjectService


def clamp01(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


class AutonomousProposalSource:
    """Hợp nhất các affordance runtime thành proposal schema của Subject Core."""

    def __init__(self, subject: SubjectService) -> None:
        self._subject = subject

    @staticmethod
    def from_affordance(affordance: Any, *, turn_id: str) -> dict[str, Any] | None:
        affordance_id = str(getattr(affordance, "affordance_id", "") or "").strip()
        candidate = getattr(affordance, "candidate", None)
        if not affordance_id or candidate is None:
            return None
        kind = str(getattr(candidate, "kind", "") or "autonomous_speech").strip()
        topic = str(getattr(candidate, "topic", "") or "").strip()
        owner = str(getattr(affordance, "owner", "") or getattr(candidate, "source", "") or "runtime")
        confidence = clamp01(getattr(candidate, "confidence", 0.5))
        relevance = clamp01(getattr(candidate, "relevance", confidence))
        urgency = clamp01(getattr(candidate, "urgency", 0.2), 0.2)
        requires_grounding = bool(getattr(candidate, "requires_grounding", False))
        intrusion = clamp01(getattr(candidate, "intrusion_risk", 1.0 - relevance), 1.0 - relevance)

        need_ids: list[str] = []
        lowered = f"{owner} {kind}".casefold()
        if any(token in lowered for token in ("followup", "continuation", "arc", "memory")):
            need_ids.append("continuity")
        if any(token in lowered for token in ("social", "chat", "seed", "conversation", "relationship")):
            need_ids.append("connection")
        if any(token in lowered for token in ("project", "task", "practice", "competence")):
            need_ids.append("competence")
        if requires_grounding or any(token in lowered for token in ("observe", "ground", "inspect")):
            need_ids.append("coherence")
        if not need_ids:
            need_ids.append("connection")

        evidence_refs = tuple(
            str(item)
            for item in (getattr(candidate, "evidence_refs", ()) or ())
            if str(item or "").strip()
        ) or (turn_id, affordance_id)
        return {
            "proposal_id": f"proposal:{affordance_id}",
            "action_kind": "speak",
            "arguments": {
                "affordance_id": affordance_id,
                "semantic_target": topic,
                "speech_act": str(getattr(candidate, "speech_act", "") or ""),
                "tone": str(getattr(candidate, "tone", "") or ""),
                "source_owner": owner,
                "candidate_kind": kind,
                "context": "autonomous",
                "skill_id": "dialogue",
            },
            "supporting_need_ids": tuple(dict.fromkeys(need_ids)),
            "expected_need_relief": max(0.05, relevance),
            "expected_action_efficacy": confidence,
            "expected_epistemic_value": 0.62 if requires_grounding else 0.16,
            "value_congruence": 0.50,
            "substrate_cost": min(1.0, 0.12 + 0.45 * intrusion),
            "uncertainty": 1.0 - confidence,
            "project_contribution": 0.55 if "competence" in need_ids else 0.0,
            "historical_success": 0.50,
            "commitment_conflict": max(0.0, intrusion - urgency * 0.25),
            "evidence_refs": evidence_refs,
            "need_effects": {
                **({"connection": 0.72, "sovereignty": -min(0.30, intrusion * 0.35)} if "connection" in need_ids else {}),
                **({"coherence": 0.62} if "coherence" in need_ids else {}),
                **({"competence": 0.54} if "competence" in need_ids else {}),
                **({"continuity": 0.58} if "continuity" in need_ids else {}),
            },
        }

    def collect(
        self,
        blackboard: Any,
        affordances: Sequence[Any],
        *,
        turn_id: str,
    ) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        proposals = [
            item
            for item in (self.from_affordance(affordance, turn_id=turn_id) for affordance in affordances)
            if item is not None
        ]
        public_view = blackboard.public_view() if callable(getattr(blackboard, "public_view", None)) else {}
        reply_expected = bool(public_view.get("reply_expected", getattr(blackboard, "reply_expected", False)))
        engagement_active = bool(public_view.get("engagement_active", getattr(blackboard, "engagement_active", False)))

        proposals.extend((
            {
                "proposal_id": f"proposal:capability-grounded-speech:{turn_id}",
                "action_kind": "speak",
                "arguments": {
                    "context": "autonomous",
                    "capability_route": True,
                    "reason_family": "ground_before_public_claim",
                    "skill_id": "investigation",
                },
                "supporting_need_ids": ("coherence", "competence"),
                "expected_need_relief": 0.38,
                "expected_action_efficacy": clamp01(self._subject.substrate.action_efficacy, 0.5),
                "expected_epistemic_value": 0.78,
                "value_congruence": 0.50,
                "substrate_cost": max(0.08, 1.0 - self._subject.substrate.processing_capacity),
                "uncertainty": 0.48,
                "project_contribution": self._subject.substrate.project_viability * 0.35,
                "historical_success": 0.50,
                "commitment_conflict": 0.08 if not reply_expected else 0.28,
                "evidence_refs": (turn_id,),
                "need_effects": {"coherence": 0.70, "competence": 0.48, "connection": -0.08},
            },
            {
                "proposal_id": f"proposal:silence:{turn_id}",
                "action_kind": "silence",
                "arguments": {"context": "autonomous", "reason_family": "low_pressure_wait"},
                "supporting_need_ids": ("sovereignty", "coherence"),
                "expected_need_relief": 0.44 if not reply_expected else 0.18,
                "expected_action_efficacy": 0.96,
                "expected_epistemic_value": 0.24,
                "value_congruence": 0.50,
                "substrate_cost": 0.01,
                "uncertainty": 0.10,
                "historical_success": 0.50,
                "commitment_conflict": 0.62 if reply_expected else 0.04,
                "evidence_refs": (turn_id,),
                "need_effects": {"sovereignty": 0.42, "coherence": 0.22, "connection": -0.72},
            },
            {
                "proposal_id": f"proposal:body-only:{turn_id}",
                "action_kind": "body_only",
                "arguments": {"context": "autonomous", "reason_family": "nonverbal_presence"},
                "supporting_need_ids": ("connection", "sovereignty"),
                "expected_need_relief": 0.32 if not engagement_active else 0.16,
                "expected_action_efficacy": 0.80,
                "expected_epistemic_value": 0.08,
                "value_congruence": 0.50,
                "substrate_cost": 0.04,
                "uncertainty": 0.18,
                "historical_success": 0.50,
                "commitment_conflict": 0.18 if reply_expected else 0.02,
                "evidence_refs": (turn_id,),
                "need_effects": {"connection": 0.24, "sovereignty": 0.30},
            },
        ))
        return tuple(proposals), {
            "reply_expected": reply_expected,
            "engagement_active": engagement_active,
            "novelty": clamp01(public_view.get("novelty", 0.30), 0.30),
        }


__all__ = ["AutonomousProposalSource", "clamp01"]
