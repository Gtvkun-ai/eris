# -*- coding: utf-8 -*-
"""Cổng đồng bộ từ runtime vào Subject Core.

Ingress chỉ biến sự kiện thành observation có provenance và dựng deliberation
frame. Nó không hard-code một cặp ``speak/investigate`` với điểm số cố định nữa;
việc đó từng khiến prior của tác giả giả làm động lực nội sinh, một trò thay tên
khá khéo nhưng vẫn là lái tay.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Coroutine, Mapping, Sequence

from cortex.subject.contracts import (
    MindDecision,
    SubjectDeliberationFrame,
    SubjectExecutiveCommit,
    WorldObservation,
)
from cortex.subject.service import SubjectService


def _run_coroutine(coro: Coroutine[Any, Any, Any]) -> Any:
    """Chạy coroutine từ runtime đồng bộ, kể cả khi thread hiện tại có event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    error: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # chuyển lỗi về caller thread
            error.append(exc)

    thread = threading.Thread(target=worker, name="eris-subject-ingress", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def _clamp01(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


class SubjectIngress:
    """Chuyển event công khai thành frame bounded cho Executive."""

    def __init__(self, service: SubjectService) -> None:
        self.service = service

    def prepare_user_turn(
        self,
        user_text: str,
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> SubjectDeliberationFrame:
        text = str(user_text or "").strip()
        context = dict(planning_context or {})
        uncertainty = 0.65 if "?" in text else 0.35
        observation = WorldObservation(
            observation_id=f"user-turn:{turn_id}:{uuid.uuid4()}",
            subject_id=self.service.config.subject_id,
            kind="user_turn",
            created_at=float(created_at),
            context={
                "context_key": "direct_chat",
                "user_text": text,
                "affected_need_ids": ("connection", "coherence", "continuity"),
                "goal_relevance": 0.92,
                "novelty": 0.45,
                "expectation_violation": 0.10,
                "controllability": 0.88,
                "relational_significance": 0.76,
                "identity_significance": 0.30,
                "future_consequence": 0.35,
                "uncertainty": uncertainty,
                "primary_interpretation": "người dùng chủ động mở một lượt hội thoại công khai",
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
        return _run_coroutine(self.service.prepare_deliberation(observation))

    @staticmethod
    def _affordance_proposal(affordance: Any, *, turn_id: str) -> dict[str, Any] | None:
        affordance_id = str(getattr(affordance, "affordance_id", "") or "").strip()
        candidate = getattr(affordance, "candidate", None)
        if not affordance_id or candidate is None:
            return None
        kind = str(getattr(candidate, "kind", "") or "autonomous_speech").strip()
        topic = str(getattr(candidate, "topic", "") or "").strip()
        owner = str(getattr(affordance, "owner", "") or getattr(candidate, "source", "") or "runtime")
        confidence = _clamp01(getattr(candidate, "confidence", 0.5))
        relevance = _clamp01(getattr(candidate, "relevance", confidence))
        urgency = _clamp01(getattr(candidate, "urgency", 0.2), 0.2)
        requires_grounding = bool(getattr(candidate, "requires_grounding", False))
        intrusion = _clamp01(getattr(candidate, "intrusion_risk", 1.0 - relevance), 1.0 - relevance)

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
        }

    def prepare_autonomous_turn(
        self,
        blackboard: Any,
        affordances: Sequence[Any],
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> SubjectDeliberationFrame:
        """Đưa mọi affordance về cùng nền Subject Core trước khi Executive chọn."""
        context = dict(planning_context or {})
        proposals = [
            item
            for item in (
                self._affordance_proposal(affordance, turn_id=turn_id)
                for affordance in affordances
            )
            if item is not None
        ]
        public_view = blackboard.public_view() if callable(getattr(blackboard, "public_view", None)) else {}
        reply_expected = bool(public_view.get("reply_expected", getattr(blackboard, "reply_expected", False)))
        engagement_active = bool(public_view.get("engagement_active", getattr(blackboard, "engagement_active", False)))

        # Silence và body-only là action thật, không phải absence bí ẩn. Chúng cũng
        # phải cạnh tranh bằng cost/need như mọi proposal khác để audit được.
        proposals.extend(
            (
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
                    "expected_action_efficacy": _clamp01(self.service.substrate.action_efficacy, 0.5),
                    "expected_epistemic_value": 0.78,
                    "value_congruence": 0.50,
                    "substrate_cost": max(0.08, 1.0 - self.service.substrate.processing_capacity),
                    "uncertainty": 0.48,
                    "project_contribution": self.service.substrate.project_viability * 0.35,
                    "historical_success": 0.50,
                    "commitment_conflict": 0.08 if not reply_expected else 0.28,
                    "evidence_refs": (turn_id,),
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
                },
            )
        )
        affected = tuple(
            dict.fromkeys(
                need
                for proposal in proposals
                for need in proposal.get("supporting_need_ids", ())
            )
        ) or ("coherence",)
        observation = WorldObservation(
            observation_id=f"autonomous-turn:{turn_id}:{uuid.uuid4()}",
            subject_id=self.service.config.subject_id,
            kind="autonomous_opportunity",
            created_at=float(created_at),
            context={
                "context_key": "autonomous",
                "affected_need_ids": affected,
                "goal_relevance": 0.48 if proposals else 0.10,
                "novelty": _clamp01(public_view.get("novelty", 0.30), 0.30),
                "expectation_violation": 0.15,
                "controllability": 0.90,
                "relational_significance": 0.54,
                "identity_significance": 0.28,
                "future_consequence": 0.22,
                "uncertainty": 0.42,
                "primary_interpretation": "runtime có các cơ hội hành động tự chủ cần Executive cân nhắc",
                "action_proposals": tuple(proposals),
                "runtime_context": {
                    "reply_expected": reply_expected,
                    "engagement_active": engagement_active,
                    "affordance_count": len(affordances),
                    "snapshot_revision": context.get("state_revision", 0),
                },
            },
            evidence_refs=(turn_id,),
            correlation_id=turn_id,
        )
        return _run_coroutine(self.service.prepare_deliberation(observation))

    def review(
        self,
        frame: SubjectDeliberationFrame,
        cognitive_requests: tuple[str, ...],
    ) -> SubjectDeliberationFrame:
        return _run_coroutine(
            self.service.review_deliberation(frame, cognitive_requests)
        )

    def finalize(
        self,
        frame: SubjectDeliberationFrame,
        commit: SubjectExecutiveCommit | None,
    ) -> MindDecision:
        return _run_coroutine(self.service.finalize_deliberation(frame, commit))

    def abandon(self, frame: SubjectDeliberationFrame, *, reason: str) -> None:
        _run_coroutine(self.service.abandon_deliberation(frame, reason=reason))

    def observe_user_turn(
        self,
        user_text: str,
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
        executive: Any | None = None,
    ) -> MindDecision:
        """API production: Subject chuẩn bị, Executive cam kết, Subject finalize."""
        frame = self.prepare_user_turn(
            user_text,
            created_at=created_at,
            turn_id=turn_id,
            planning_context=planning_context,
        )
        commit = None
        commit_method = getattr(executive, "commit_subject_frame", None)
        if callable(commit_method):
            commit = commit_method(
                frame,
                user_text=user_text,
                snapshot=planning_context or {},
                mode="interactive",
            )
            # Executive được phép yêu cầu đúng một vòng xem lại bounded. Không
            # cho vòng lặp vô hạn chỉ vì model vừa phát hiện thêm một phòng họp.
            if commit is not None and commit.cognitive_requests:
                revised = self.review(frame, commit.cognitive_requests)
                if revised.frame_id != frame.frame_id:
                    frame = revised
                    commit = commit_method(
                        frame,
                        user_text=user_text,
                        snapshot=planning_context or {},
                        mode="interactive_review",
                    )
        return self.finalize(frame, commit)


__all__ = ["SubjectIngress"]
