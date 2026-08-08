# -*- coding: utf-8 -*-
"""Cổng biến sự kiện runtime thành WorldObservation có provenance.

Ingress không điều phối deliberation. Nó chỉ chuẩn hóa input, còn toàn bộ vòng
prepare → cognitive review → Executive commit → finalize thuộc một MindLoop duy
nhất. Các method trả frame cũ vẫn được giữ như adapter migration cho test/module
chưa chuyển, nhưng đường production dùng session.
"""
from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from cortex.subject.contracts import MindDecision, SubjectDeliberationFrame, SubjectExecutiveCommit, WorldObservation
from cortex.subject.service import SubjectService
from runtime.mind_loop import DeliberationSession, DeliberationState, MindLoop, SubjectExecutivePort
from runtime.subject_proposals import AutonomousProposalSource



class SubjectIngress:
    """Tạo observation cho chat/autonomous và giao session cho MindLoop."""

    def __init__(
        self,
        service: SubjectService,
        *,
        mind_loop: MindLoop | None = None,
        autonomous_proposals: AutonomousProposalSource | None = None,
    ) -> None:
        self.service = service
        self.mind_loop = mind_loop or MindLoop(subject=service)
        self.autonomous_proposals = autonomous_proposals or AutonomousProposalSource(service)

    def user_observation(
        self,
        user_text: str,
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> WorldObservation:
        text = str(user_text or "").strip()
        context = dict(planning_context or {})
        uncertainty = 0.65 if "?" in text else 0.35
        return WorldObservation(
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

    def prepare_user_session(
        self,
        user_text: str,
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> DeliberationSession:
        self.service.note_relational_user_turn(
            now=created_at,
            meaningful=bool(str(user_text or "").strip()),
            engagement=0.82,
            evidence_ref=turn_id,
            persist=True,
        )
        observation = self.user_observation(
            user_text,
            created_at=created_at,
            turn_id=turn_id,
            planning_context=planning_context,
        )
        return self.mind_loop.prepare_sync(
            observation,
            mode="interactive",
            user_text=user_text,
            snapshot=planning_context or {},
        )

    def prepare_user_turn(self, *args: Any, **kwargs: Any) -> SubjectDeliberationFrame:
        """Adapter V17: caller cũ nhận frame, không tự sở hữu orchestration."""
        return self.prepare_user_session(*args, **kwargs).frame

    def autonomous_observation(
        self,
        blackboard: Any,
        affordances: Sequence[Any],
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> WorldObservation:
        context = dict(planning_context or {})
        proposals, proposal_context = self.autonomous_proposals.collect(
            blackboard,
            affordances,
            turn_id=turn_id,
        )
        reply_expected = bool(proposal_context["reply_expected"])
        engagement_active = bool(proposal_context["engagement_active"])
        relational = context.get("relational_state") if isinstance(context.get("relational_state"), Mapping) else {}
        relational_pressure = float(relational.get("connection_pressure", 0.0) or 0.0)
        relational_opportunity = float(relational.get("opportunity", 0.0) or 0.0)

        affected = tuple(dict.fromkeys(
            need for proposal in proposals for need in proposal.get("supporting_need_ids", ())
        )) or ("coherence",)
        return WorldObservation(
            observation_id=f"autonomous-turn:{turn_id}:{uuid.uuid4()}",
            subject_id=self.service.config.subject_id,
            kind="autonomous_opportunity",
            created_at=float(created_at),
            context={
                "context_key": "autonomous",
                "affected_need_ids": affected,
                "goal_relevance": max(0.48 if proposals else 0.10, min(0.90, relational_pressure)),
                "novelty": float(proposal_context["novelty"]),
                "expectation_violation": 0.15,
                "controllability": 0.90,
                "relational_significance": max(0.54, min(1.0, relational_pressure)),
                "identity_significance": 0.28,
                "future_consequence": max(0.22, min(0.72, relational_pressure * 0.68)),
                "uncertainty": 0.42,
                "primary_interpretation": "runtime có các cơ hội hành động tự chủ cần Executive cân nhắc",
                "action_proposals": tuple(proposals),
                "runtime_context": {
                    "reply_expected": reply_expected,
                    "engagement_active": engagement_active,
                    "affordance_count": len(affordances),
                    "snapshot_revision": context.get("state_revision", 0),
                    "partner_available": relational.get("partner_availability", relational_opportunity),
                    "interruption_cost": relational.get("interruption_cost", 0.25),
                    "sharing_signal": relational.get("sharing_pressure", 0.0),
                    "social_curiosity": relational.get("social_curiosity", 0.0),
                    "unresolved_relational": relational.get("affiliation_deficit", 0.0),
                    "relational_evidence_refs": tuple(relational.get("evidence_refs", ())),
                },
            },
            evidence_refs=(turn_id,),
            correlation_id=turn_id,
        )

    def prepare_autonomous_session(
        self,
        blackboard: Any,
        affordances: Sequence[Any],
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
    ) -> DeliberationSession:
        observation = self.autonomous_observation(
            blackboard,
            affordances,
            created_at=created_at,
            turn_id=turn_id,
            planning_context=planning_context,
        )
        return self.mind_loop.prepare_sync(
            observation,
            mode="autonomous",
            snapshot=planning_context or {},
        )

    def prepare_autonomous_turn(self, *args: Any, **kwargs: Any) -> SubjectDeliberationFrame:
        """Adapter V17 trả frame; production dùng prepare_autonomous_session."""
        return self.prepare_autonomous_session(*args, **kwargs).frame

    def observe_user_turn(
        self,
        user_text: str,
        *,
        created_at: float,
        turn_id: str,
        planning_context: Mapping[str, Any] | None = None,
        executive: SubjectExecutivePort | None = None,
    ) -> MindDecision:
        self.service.note_relational_user_turn(
            now=created_at,
            meaningful=bool(str(user_text or "").strip()),
            engagement=0.82,
            evidence_ref=turn_id,
            persist=True,
        )
        observation = self.user_observation(
            user_text,
            created_at=created_at,
            turn_id=turn_id,
            planning_context=planning_context,
        )
        return self.mind_loop.deliberate_sync(
            observation,
            mode="interactive",
            user_text=user_text,
            snapshot=planning_context or {},
            executive=executive,
        )

    def complete_autonomous_turn(
        self,
        session: DeliberationSession,
        executive_outcome: Any,
        *,
        executive: Any,
    ) -> MindDecision | None:
        commit_builder = getattr(executive, "subject_commit_from_outcome", None)
        if not callable(commit_builder):
            self.mind_loop.abandon_sync(
                session,
                reason="executive_has_no_subject_commit_adapter",
            )
            return None

        def provider(frame: SubjectDeliberationFrame, _mode: str) -> SubjectExecutiveCommit | None:
            # Sau cognitive review coalition ID có thể đổi. Rebuild commit từ cùng
            # executive outcome/affordance thay vì tái dùng ID cũ đã hết hạn.
            return commit_builder(frame, executive_outcome)

        commit = provider(session.frame, session.mode)
        if commit is None:
            self.mind_loop.abandon_sync(
                session,
                reason="executive_outcome_not_bound_to_subject_coalition",
            )
            return None
        return self.mind_loop.complete_sync(
            session,
            executive=executive,
            initial_commit=commit,
            commit_provider=provider,
        )

    # ------------------------------------------------------------------
    # Adapter migration cho caller V17
    # ------------------------------------------------------------------
    def finalize(self, frame: SubjectDeliberationFrame, commit: SubjectExecutiveCommit) -> MindDecision:
        session = DeliberationSession(
            session_id=f"legacy-frame:{uuid.uuid4()}",
            frame=frame,
            state=DeliberationState.PREPARED,
            mode="legacy_adapter",
            user_text=str(frame.observation.context.get("user_text") or ""),
            snapshot=dict(frame.observation.context),
            max_reviews=0,
        )
        return self.mind_loop.complete_sync(session, initial_commit=commit)

    def abandon(self, frame: SubjectDeliberationFrame, *, reason: str) -> None:
        session = DeliberationSession(
            session_id=f"legacy-frame:{uuid.uuid4()}",
            frame=frame,
            state=DeliberationState.PREPARED,
            mode="legacy_adapter",
            user_text="",
            snapshot={},
            max_reviews=0,
        )
        self.mind_loop.abandon_sync(session, reason=reason)


__all__ = ["SubjectIngress"]
