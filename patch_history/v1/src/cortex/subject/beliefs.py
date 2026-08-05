# -*- coding: utf-8 -*-
"""Evidence-traceable belief projection."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Iterable

from .contracts import Belief, BeliefProposal, BeliefRevision, BeliefSourceKind


class BeliefService:
    def __init__(self, id_factory: Callable[[], str], clock: Callable[[], float]) -> None:
        self._id_factory = id_factory
        self._clock = clock
        self._beliefs: dict[str, Belief] = {}

    def all(self) -> tuple[Belief, ...]:
        return tuple(sorted(self._beliefs.values(), key=lambda belief: (belief.updated_at, belief.belief_id)))

    def get(self, belief_id: str) -> Belief | None:
        return self._beliefs.get(belief_id)

    def revise(self, proposal: BeliefProposal, evidence: Iterable[str] = ()) -> BeliefRevision:
        evidence_refs = tuple(dict.fromkeys((*proposal.evidence_refs, *tuple(evidence))))
        if proposal.source_kind is not BeliefSourceKind.CONFABULATION_CANDIDATE and not evidence_refs:
            raise ValueError("belief revision requires evidence")

        prior = self._beliefs.get(proposal.supersedes_id or "")
        contradiction = bool(prior and (
            prior.subject != proposal.subject
            or prior.predicate != proposal.predicate
            or prior.object_json != proposal.object_json
        ))
        confidence = proposal.confidence
        if prior and not contradiction:
            confidence = min(1.0, 0.65 * prior.confidence + 0.35 * proposal.confidence + min(0.05, len(evidence_refs) * 0.01))
        elif prior and contradiction:
            confidence = max(0.05, proposal.confidence - min(0.20, prior.confidence * 0.20))

        belief = Belief(
            belief_id=self._id_factory(),
            subject=proposal.subject,
            predicate=proposal.predicate,
            object_json=proposal.object_json,
            confidence=confidence,
            source_kind=proposal.source_kind,
            evidence_refs=evidence_refs,
            counter_evidence_refs=proposal.counter_evidence_refs,
            visibility_scope=proposal.visibility_scope,
            created_at=self._clock(),
            updated_at=self._clock(),
            supersedes_id=prior.belief_id if prior else proposal.supersedes_id,
            predictive_commitments=proposal.predictive_commitments,
        )
        if prior:
            self._beliefs[prior.belief_id] = replace(prior, status="superseded", updated_at=self._clock())
        self._beliefs[belief.belief_id] = belief
        return BeliefRevision(
            prior_belief_id=prior.belief_id if prior else None,
            belief=belief,
            confidence_delta=belief.confidence - (prior.confidence if prior else 0.0),
            contradiction_detected=contradiction,
        )

    def accessible(self, *, minimum_accessibility: float = 0.5, public_only: bool = False) -> tuple[Belief, ...]:
        output = []
        for belief in self._beliefs.values():
            if belief.status != "active" or belief.accessibility < minimum_accessibility:
                continue
            if public_only and belief.visibility_scope.value != "public":
                continue
            output.append(belief)
        return tuple(sorted(output, key=lambda belief: (-belief.retrieval_salience, -belief.confidence, belief.belief_id)))
