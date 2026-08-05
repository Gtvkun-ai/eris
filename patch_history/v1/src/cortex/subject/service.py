# -*- coding: utf-8 -*-
"""Single orchestrator for the Eris Subject Core."""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Protocol

from .authorship import AuthorshipService
from .beliefs import BeliefService
from .coalitions import CoalitionArbiter
from .competence import CompetenceService
from .contracts import (
    ActionProposal,
    ActionRequest,
    AttributionDistribution,
    AttributionTarget,
    BeliefSourceKind,
    LearningReceipt,
    MindDecision,
    NeedActivation,
    OrganismicSubstrate,
    SubjectAppraisal,
    WorldObservation,
    WorldOutcome,
)
from .episodes import NeedEpisodeRecorder
from .narrative import NarrativeBeliefGenerator, NarrativeView
from .needs import NeedSystem
from .substrate import SubstrateMonitor


class SubjectRepositoryPort(Protocol):
    def append_subject_event(self, *, subject_id: str, event_type: str, payload: Mapping[str, Any], causal_refs: tuple[str, ...] = (), correlation_id: str = "", event_id: str | None = None, created_at: float | None = None) -> Any: ...
    def save_projection(self, *, subject_id: str, projection_type: str, projection_key: str, payload: Mapping[str, Any], expected_revision: int | None = None) -> int: ...


class AuditPort(Protocol):
    def append(self, event: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class SubjectServiceConfig:
    subject_id: str = "eris"
    deterministic: bool = True
    random_seed: int = 0
    min_episode_pressure: float = 0.08
    default_temperature: float = 0.20
    algorithm_version: str = "subject-service-v1"


class SubjectService:
    """Observation → appraisal → need episode → coalition → decision.

    The service never calls shell, filesystem, network, TTS or body adapters.
    Those capabilities live behind the actuator and sandbox boundaries.
    """

    def __init__(
        self,
        *,
        config: SubjectServiceConfig | None = None,
        repository: SubjectRepositoryPort | None = None,
        audit: AuditPort | None = None,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        random_source: random.Random | None = None,
    ) -> None:
        self.config = config or SubjectServiceConfig()
        self._repository = repository
        self._audit = audit
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._random = random_source or random.Random(self.config.random_seed)

        self.substrate_monitor = SubstrateMonitor()
        self.need_system = NeedSystem()
        self.episodes = NeedEpisodeRecorder(self._id_factory, self._clock)
        self.beliefs = BeliefService(self._id_factory, self._clock)
        self.authorship = AuthorshipService(self._id_factory, self._clock)
        self.competence = CompetenceService(self._id_factory, self._clock)
        self.narrative = NarrativeBeliefGenerator(self._id_factory, self._clock)
        self.arbiter = CoalitionArbiter(
            id_factory=self._id_factory,
            clock=self._clock,
            random_source=self._random,
            deterministic=self.config.deterministic,
        )
        self.substrate = self.substrate_monitor.initial(subject_id=self.config.subject_id, captured_at=self._clock())
        self._last_appraisals: tuple[SubjectAppraisal, ...] = ()
        self._last_activations: tuple[NeedActivation, ...] = ()
        self._decisions: dict[str, MindDecision] = {}
        self._authorship_by_decision: dict[str, str] = {}
        self._outcomes: list[WorldOutcome] = []

    @staticmethod
    def _as_payload(value: Any) -> dict[str, Any]:
        if hasattr(value, "to_dict"):
            return dict(value.to_dict())
        if hasattr(value, "__dataclass_fields__"):
            return SubjectService._normalize({
                name: getattr(value, name) for name in value.__dataclass_fields__
            })
        if isinstance(value, Mapping):
            return SubjectService._normalize(dict(value))
        return {"value": str(value)}

    @staticmethod
    def _normalize(value: Any) -> Any:
        if hasattr(value, "__dataclass_fields__"):
            return {
                name: SubjectService._normalize(getattr(value, name))
                for name in value.__dataclass_fields__
            }
        if isinstance(value, Mapping):
            return {str(key): SubjectService._normalize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [SubjectService._normalize(item) for item in value]
        if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
            return value.value
        return value

    def _append_event(self, event_type: str, payload: Mapping[str, Any], *, causal_refs: tuple[str, ...] = (), correlation_id: str = "", event_id: str | None = None, created_at: float | None = None) -> None:
        stored_event_id = event_id or self._id_factory()
        event_time = self._clock() if created_at is None else created_at
        if self._repository is not None:
            self._repository.append_subject_event(
                subject_id=self.config.subject_id,
                event_type=event_type,
                payload=payload,
                causal_refs=causal_refs,
                correlation_id=correlation_id,
                event_id=stored_event_id,
                created_at=event_time,
            )
        if self._audit is not None:
            append_audit = getattr(self._audit, "append", None)
            if callable(append_audit):
                append_audit({
                    "event_id": f"audit:{stored_event_id}",
                    "subject_id": self.config.subject_id,
                    "kind": event_type,
                    "entity_id": stored_event_id,
                    "created_at": event_time,
                    "payload": dict(payload),
                    "causal_refs": causal_refs,
                    "correlation_id": correlation_id,
                    "algorithm_version": self.config.algorithm_version,
                })

    def _appraise(self, observation: WorldObservation, before: OrganismicSubstrate, after: OrganismicSubstrate) -> tuple[SubjectAppraisal, ...]:
        context = observation.context
        affected = tuple(str(item) for item in context.get("affected_need_ids", ()))
        if not affected:
            kind = observation.kind.lower()
            guessed: list[str] = []
            if any(token in kind for token in ("error", "failure", "task", "correction")):
                guessed.extend(("competence", "coherence"))
            if any(token in kind for token in ("promise", "return", "leave", "relation", "user")):
                guessed.extend(("connection", "continuity"))
            if any(token in kind for token in ("denied", "boundary", "capability", "constraint")):
                guessed.append("sovereignty")
            affected = tuple(dict.fromkeys(guessed or ("coherence",)))

        attribution_raw = context.get("attribution")
        if isinstance(attribution_raw, Mapping) and attribution_raw:
            distribution = AttributionDistribution({AttributionTarget(str(key)): float(value) for key, value in attribution_raw.items()})
        else:
            distribution = AttributionDistribution.unknown()
        refs = observation.evidence_refs or (observation.observation_id,)
        substrate_delta = self.substrate_monitor.delta(before, after)
        novelty = float(context.get("novelty", 0.5))
        violation = float(context.get("expectation_violation", 0.0))
        relevance = float(context.get("goal_relevance", 0.5))
        future = float(context.get("future_consequence", 0.3))
        controllability = float(context.get("controllability", after.action_efficacy))
        uncertainty = float(context.get("uncertainty", 0.5))
        relational = float(context.get("relational_significance", 0.6 if "connection" in affected else 0.0))
        identity = float(context.get("identity_significance", 0.6 if any(n in affected for n in ("continuity", "sovereignty")) else 0.0))
        clamp = lambda x: max(0.0, min(1.0, x))
        appraisal = SubjectAppraisal(
            appraisal_id=self._id_factory(),
            observation_id=observation.observation_id,
            goal_relevance=clamp(relevance),
            novelty=clamp(novelty),
            expectation_violation=clamp(violation),
            controllability=clamp(controllability),
            relational_significance=clamp(relational),
            identity_significance=clamp(identity),
            future_consequence=clamp(future),
            uncertainty=clamp(uncertainty),
            affected_need_ids=affected,
            attribution=distribution,
            evidence_refs=tuple(refs),
            substrate_delta=substrate_delta,
            primary_interpretation=str(context.get("primary_interpretation") or observation.kind),
            alternatives=tuple(str(item) for item in context.get("alternative_interpretations", ())),
        )
        return (appraisal,)

    def _proposals_from_context(self, observation: WorldObservation, activations: tuple[NeedActivation, ...]) -> tuple[ActionProposal, ...]:
        raw = observation.context.get("action_proposals")
        proposals: list[ActionProposal] = []
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                supporting = tuple(str(value) for value in item.get("supporting_need_ids", ()))
                proposals.append(ActionProposal(
                    proposal_id=str(item.get("proposal_id") or self._id_factory()),
                    action_kind=str(item.get("action_kind") or "observe"),
                    arguments=dict(item.get("arguments") or {}),
                    supporting_need_ids=supporting,
                    expected_need_relief=float(item.get("expected_need_relief", 0.5)),
                    expected_action_efficacy=float(item.get("expected_action_efficacy", self.substrate.action_efficacy)),
                    expected_epistemic_value=float(item.get("expected_epistemic_value", 0.2)),
                    value_congruence=float(item.get("value_congruence", 0.5)),
                    substrate_cost=float(item.get("substrate_cost", 0.1)),
                    uncertainty=float(item.get("uncertainty", 0.5)),
                    project_contribution=float(item.get("project_contribution", 0.0)),
                    historical_success=float(item.get("historical_success", 0.5)),
                    commitment_conflict=float(item.get("commitment_conflict", 0.0)),
                    evidence_refs=tuple(str(ref) for ref in item.get("evidence_refs", observation.evidence_refs or (observation.observation_id,))),
                ))
        if proposals:
            return tuple(proposals)

        for activation in activations:
            if activation.need_id == "competence":
                action_kind, epistemic = "practice", 0.25
            elif activation.need_id == "connection":
                action_kind, epistemic = "speak", 0.15
            elif activation.need_id == "sovereignty":
                action_kind, epistemic = "request_capability", 0.20
            elif activation.need_id == "continuity":
                action_kind, epistemic = "preserve_commitment", 0.10
            else:
                action_kind, epistemic = "investigate", 0.65
            proposals.append(ActionProposal(
                proposal_id=self._id_factory(),
                action_kind=action_kind,
                arguments={
                    "observation_id": observation.observation_id,
                    "context": str(observation.context.get("context_key") or "general"),
                },
                supporting_need_ids=(activation.need_id,),
                expected_need_relief=activation.pressure,
                expected_action_efficacy=self.substrate.action_efficacy,
                expected_epistemic_value=epistemic,
                value_congruence=0.5,
                substrate_cost=max(0.0, 1.0 - self.substrate.processing_capacity),
                uncertainty=self._last_appraisals[0].uncertainty if self._last_appraisals else 0.5,
                project_contribution=self.substrate.project_viability * 0.5,
                historical_success=0.5,
                commitment_conflict=0.0,
                evidence_refs=activation.evidence_refs or (observation.observation_id,),
            ))
        if not proposals:
            proposals.append(ActionProposal(
                proposal_id=self._id_factory(),
                action_kind="observe",
                arguments={"observation_id": observation.observation_id},
                supporting_need_ids=("coherence",),
                expected_need_relief=0.1,
                expected_action_efficacy=1.0,
                expected_epistemic_value=0.8,
                value_congruence=0.5,
                substrate_cost=0.0,
                uncertainty=0.5,
                evidence_refs=observation.evidence_refs or (observation.observation_id,),
            ))
        return tuple(proposals)

    async def deliberate(self, observation: WorldObservation) -> MindDecision:
        if observation.subject_id != self.config.subject_id:
            raise ValueError("observation subject does not match SubjectService")
        self._append_event(
            "raw_observation",
            observation.to_dict(),
            causal_refs=observation.causal_refs,
            correlation_id=observation.correlation_id,
            event_id=observation.observation_id,
            created_at=observation.created_at,
        )
        before = self.substrate
        self.substrate = self.substrate_monitor.measure(observation, before)
        substrate_ref = f"substrate:{self.substrate.subject_id}:{self.substrate.revision}"
        self._last_appraisals = self._appraise(observation, before, self.substrate)
        self._last_activations = self.need_system.activate(
            self.substrate,
            self._last_appraisals,
            self.episodes.closed_episodes(),
        )
        for activation in self._last_activations:
            if activation.pressure < self.config.min_episode_pressure or not activation.evidence_refs:
                continue
            appraisal = next((a for a in self._last_appraisals if activation.need_id in a.affected_need_ids), self._last_appraisals[0])
            self.episodes.open(
                activation,
                controllability=appraisal.controllability,
                predictability=1.0 - appraisal.uncertainty,
                attribution=appraisal.attribution,
                substrate_before_ref=substrate_ref,
                social_context_ids=(str(observation.context.get("context_key") or "general"),),
            )

        proposals = self._proposals_from_context(observation, self._last_activations)
        decision = self.arbiter.choose(
            proposals,
            substrate=self.substrate,
            observation_ref=observation.observation_id,
            appraisal_refs=tuple(appraisal.appraisal_id for appraisal in self._last_appraisals),
            substrate_ref=substrate_ref,
            temperature=self.config.default_temperature,
        )
        draft = self.authorship.draft(decision)
        self._authorship_by_decision[decision.decision_id] = draft.authorship_id
        self._decisions[decision.decision_id] = decision
        for need_id in decision.supporting_need_ids:
            self.episodes.attach_action(need_id, draft.action_id)

        self._append_event("substrate_projection", self.substrate.to_dict(), causal_refs=(observation.observation_id,))
        for appraisal in self._last_appraisals:
            self._append_event("appraisal_projection", self._as_payload(appraisal), causal_refs=(observation.observation_id,))
        for activation in self._last_activations:
            self._append_event("need_activation", self._as_payload(activation), causal_refs=(observation.observation_id,))
        self._append_event("mind_decision", decision.to_dict(), causal_refs=(observation.observation_id, *decision.appraisal_refs))
        self._append_event("authorship_draft", self._as_payload(draft), causal_refs=(decision.decision_id,))
        if self._repository is not None:
            append_authorship = getattr(self._repository, "append_authorship_event", None)
            if callable(append_authorship):
                append_authorship(
                    authorship_id=draft.authorship_id,
                    action_id=draft.action_id,
                    decision_id=draft.decision_id,
                    stage="draft",
                    payload=self._as_payload(draft),
                )
            self._repository.save_projection(
                subject_id=self.config.subject_id,
                projection_type="subject_state",
                projection_key="current",
                payload=self.snapshot(),
                expected_revision=None,
            )
        return decision

    def to_action_request(
        self,
        decision: MindDecision,
        *,
        requested_capabilities: tuple[str, ...] = (),
        expected_outcomes: tuple[str, ...] = (),
        idempotency_key: str | None = None,
    ) -> ActionRequest:
        authorship_id = self._authorship_by_decision.get(decision.decision_id)
        if not authorship_id:
            raise KeyError("decision has no authorship draft")
        draft = self.authorship.get(authorship_id)
        if draft is None:
            raise KeyError("authorship draft not found")
        return ActionRequest(
            action_id=draft.action_id,
            decision_id=decision.decision_id,
            kind=decision.proposed_action,
            arguments=decision.arguments,
            expected_outcomes=expected_outcomes,
            requested_capabilities=requested_capabilities,
            idempotency_key=idempotency_key or f"{decision.decision_id}:{draft.action_id}",
            authorship_draft_id=draft.authorship_id,
            created_at=self._clock(),
        )

    async def observe_outcome(self, outcome: WorldOutcome) -> LearningReceipt:
        decision = self._decisions.get(outcome.decision_id)
        if decision is None:
            raise KeyError(f"unknown decision {outcome.decision_id}")
        authorship_id = self._authorship_by_decision[decision.decision_id]
        finalized = self.authorship.finalize(
            outcome,
            {
                "retrospective_endorsement": outcome.success_score,
                "claimed_as_self": outcome.status.value in {"succeeded", "partial", "simulated"},
                "externally_constrained": outcome.status.value == "denied",
                "disclaimed_reason": outcome.denial_reason if outcome.status.value == "denied" else None,
            },
            authorship_id=authorship_id,
        )
        substrate_ref = f"substrate:{self.substrate.subject_id}:{self.substrate.revision}"
        closed = self.episodes.close_all_for_action(outcome.action_id, outcome=outcome, substrate_after_ref=substrate_ref)
        self._outcomes.append(outcome)

        visible_refs = tuple(dict.fromkeys((*outcome.evidence_refs, outcome.outcome_id, decision.observation_ref)))
        proposals = self.narrative.interpret(NarrativeView(
            action_id=outcome.action_id,
            action_kind=decision.proposed_action,
            visible_evidence_refs=visible_refs,
            accessible_belief_summaries=tuple(
                f"{belief.subject}:{belief.predicate}" for belief in self.beliefs.accessible(minimum_accessibility=0.6)
            ),
            outcome_summary=outcome.status.value,
            current_value_statements=(),
            public_context={"decision_id": decision.decision_id},
        ))
        belief_revision_ids: list[str] = []
        if proposals:
            revision = self.beliefs.revise(proposals[0], visible_refs)
            belief_revision_ids.append(revision.belief.belief_id)
            self._append_event("narrative_belief", self._as_payload(revision.belief), causal_refs=(outcome.outcome_id, outcome.action_id))

        self._append_event("world_outcome", outcome.to_dict(), causal_refs=(outcome.action_id, outcome.decision_id))
        self._append_event("authorship_finalized", self._as_payload(finalized), causal_refs=(outcome.outcome_id, outcome.action_id))
        if self._repository is not None:
            append_outcome = getattr(self._repository, "append_world_outcome", None)
            if callable(append_outcome):
                append_outcome(
                    outcome_id=outcome.outcome_id,
                    action_id=outcome.action_id,
                    decision_id=outcome.decision_id,
                    status=outcome.status.value,
                    payload=outcome.to_dict(),
                )
            append_authorship = getattr(self._repository, "append_authorship_event", None)
            if callable(append_authorship):
                append_authorship(
                    authorship_id=finalized.authorship_id,
                    action_id=finalized.action_id,
                    decision_id=finalized.decision_id,
                    stage="finalized",
                    payload=self._as_payload(finalized),
                )
        for episode in closed:
            self._append_event("need_episode_closed", self._as_payload(episode), causal_refs=(outcome.outcome_id,))
        receipt = LearningReceipt(
            receipt_id=self._id_factory(),
            outcome_id=outcome.outcome_id,
            closed_episode_ids=tuple(episode.episode_id for episode in closed),
            belief_revision_ids=tuple(belief_revision_ids),
            competence_estimate_ids=(),
            authorship_id=finalized.authorship_id,
            created_at=self._clock(),
        )
        self._append_event("learning_receipt", self._as_payload(receipt), causal_refs=(outcome.outcome_id,))
        return receipt

    def snapshot(self) -> dict[str, Any]:
        return {
            "algorithm_version": self.config.algorithm_version,
            "subject_id": self.config.subject_id,
            "substrate": self.substrate.to_dict(),
            "active_appraisal_ids": [item.appraisal_id for item in self._last_appraisals],
            "active_needs": [self._as_payload(item) for item in self._last_activations],
            "open_episode_ids": [item.episode_id for item in self.episodes.open_episodes()],
            "belief_ids": [item.belief_id for item in self.beliefs.all() if item.status == "active"],
            "decision_ids": list(self._decisions),
            "outcome_ids": [item.outcome_id for item in self._outcomes],
        }


__all__ = ["SubjectService", "SubjectServiceConfig"]
