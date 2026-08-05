# -*- coding: utf-8 -*-
"""Synchronous ingress from the production chat loop into Subject Core."""
from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Coroutine, Mapping

from cortex.subject.contracts import MindDecision, WorldObservation
from cortex.subject.service import SubjectService


def _run_coroutine(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine from synchronous runtime code, even when a loop exists."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    error: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # re-raised in caller thread
            error.append(exc)

    thread = threading.Thread(target=worker, name="eris-subject-ingress", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


class SubjectIngress:
    """Convert public runtime events into bounded, evidence-carrying observations."""

    def __init__(self, service: SubjectService) -> None:
        self.service = service

    def observe_user_turn(
        self,
        user_text: str,
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> MindDecision:
        text = str(user_text or "").strip()
        context = dict(planning_context or {})
        uncertainty = 0.65 if "?" in text else 0.35
        action_proposals = [
            {
                "action_kind": "speak",
                "arguments": {
                    "user_turn_id": turn_id,
                    "semantic_content": text,
                    "context": "direct_chat",
                    "principle": "duy trì kết nối trung thực",
                    "value_tags": ("kết nối", "trung thực"),
                    "cost_paid": 0.05,
                    "skill_id": "dialogue",
                },
                "supporting_need_ids": ("connection", "coherence"),
                "expected_need_relief": 0.72,
                "expected_action_efficacy": 0.88,
                "expected_epistemic_value": 0.18,
                "value_congruence": 0.72,
                "substrate_cost": 0.08,
                "uncertainty": uncertainty,
                "historical_success": 0.72,
                "evidence_refs": (turn_id,),
            },
            {
                "action_kind": "investigate",
                "arguments": {
                    "user_turn_id": turn_id,
                    "query": text,
                    "context": "direct_chat",
                    "principle": "kiểm chứng trước khi khẳng định",
                    "value_tags": ("kiểm chứng", "nhất quán"),
                    "cost_paid": 0.12,
                    "skill_id": "investigation",
                },
                "supporting_need_ids": ("coherence", "competence"),
                "expected_need_relief": 0.44,
                "expected_action_efficacy": 0.66,
                "expected_epistemic_value": 0.82,
                "value_congruence": 0.64,
                "substrate_cost": 0.20,
                "uncertainty": uncertainty,
                "historical_success": 0.62,
                "evidence_refs": (turn_id,),
            },
        ]
        observation = WorldObservation(
            observation_id=f"user-turn:{turn_id}:{uuid.uuid4()}",
            subject_id=self.service.config.subject_id,
            kind="user_turn",
            created_at=float(created_at),
            context={
                "context_key": "direct_chat",
                "affected_need_ids": ("connection", "coherence", "continuity"),
                "goal_relevance": 0.92,
                "novelty": 0.45,
                "expectation_violation": 0.10,
                "controllability": 0.88,
                "relational_significance": 0.76,
                "identity_significance": 0.30,
                "future_consequence": 0.35,
                "uncertainty": uncertainty,
                "primary_interpretation": "the user initiated a direct public turn",
                "action_proposals": action_proposals,
                "runtime_context": {
                    "memory_available": bool(context.get("memory_available")),
                    "engagement_active": bool((context.get("engagement_context") or {}).get("active", False))
                    if isinstance(context.get("engagement_context"), Mapping)
                    else False,
                },
            },
            evidence_refs=(turn_id,),
            causal_refs=(),
            correlation_id=turn_id,
        )
        return _run_coroutine(self.service.deliberate(observation))


__all__ = ["SubjectIngress"]
