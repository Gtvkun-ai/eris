# -*- coding: utf-8 -*-
"""Evidence-traceable belief projection."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping

from .contracts import Belief, BeliefProposal, BeliefRevision, BeliefSourceKind, VisibilityScope


class BeliefService:
    def __init__(self, id_factory: Callable[[], str], clock: Callable[[], float]) -> None:
        self._id_factory = id_factory
        self._clock = clock
        self._beliefs: dict[str, Belief] = {}

    def all(self) -> tuple[Belief, ...]:
        return tuple(sorted(self._beliefs.values(), key=lambda belief: (belief.updated_at, belief.belief_id)))

    def get(self, belief_id: str) -> Belief | None:
        return self._beliefs.get(belief_id)


    def restore(self, records: Iterable[Belief | Mapping[str, Any]]) -> None:
        """Khôi phục belief projection từ snapshot đã kiểm tra.

        Raw event vẫn là nguồn forensic; hàm này chỉ dựng projection để Eris không
        mất toàn bộ điều đã học sau mỗi lần khởi động lại.
        """
        restored: dict[str, Belief] = {}
        for record in records:
            if isinstance(record, Belief):
                belief = record
            else:
                belief = Belief(
                    belief_id=str(record["belief_id"]),
                    subject=str(record["subject"]),
                    predicate=str(record["predicate"]),
                    object_json=record.get("object_json"),
                    confidence=float(record.get("confidence", 0.5)),
                    source_kind=BeliefSourceKind(str(record.get("source_kind", BeliefSourceKind.INFERENCE.value))),
                    evidence_refs=tuple(str(item) for item in record.get("evidence_refs", ())),
                    counter_evidence_refs=tuple(str(item) for item in record.get("counter_evidence_refs", ())),
                    accessibility=float(record.get("accessibility", 1.0)),
                    salience=float(record.get("salience", 0.5)),
                    retrieval_salience=float(record.get("retrieval_salience", 0.5)),
                    visibility_scope=VisibilityScope(str(record.get("visibility_scope", VisibilityScope.PRIVATE.value))),
                    ownership=str(record.get("ownership", "self")),
                    status=str(record.get("status", "active")),
                    created_at=float(record.get("created_at", 0.0)),
                    updated_at=float(record.get("updated_at", 0.0)),
                    supersedes_id=(str(record["supersedes_id"]) if record.get("supersedes_id") else None),
                    predictive_commitments=tuple(str(item) for item in record.get("predictive_commitments", ())),
                )
            restored[belief.belief_id] = belief
        self._beliefs = restored

    def to_projection(self) -> list[dict[str, Any]]:
        return [
            {
                "belief_id": belief.belief_id,
                "subject": belief.subject,
                "predicate": belief.predicate,
                "object_json": belief.object_json,
                "confidence": belief.confidence,
                "source_kind": belief.source_kind.value,
                "evidence_refs": list(belief.evidence_refs),
                "counter_evidence_refs": list(belief.counter_evidence_refs),
                "accessibility": belief.accessibility,
                "salience": belief.salience,
                "retrieval_salience": belief.retrieval_salience,
                "visibility_scope": belief.visibility_scope.value,
                "ownership": belief.ownership,
                "status": belief.status,
                "created_at": belief.created_at,
                "updated_at": belief.updated_at,
                "supersedes_id": belief.supersedes_id,
                "predictive_commitments": list(belief.predictive_commitments),
            }
            for belief in self.all()
        ]

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
