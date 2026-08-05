# -*- coding: utf-8 -*-
"""Coalition arbitration with pragmatic and epistemic value."""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from .contracts import ActionProposal, Belief, CommitmentLedger, MindDecision, OrganismicSubstrate, Value


@dataclass(frozen=True, slots=True)
class CoalitionScore:
    coalition_id: str
    proposals: tuple[ActionProposal, ...]
    score: float
    pragmatic_value: float
    epistemic_value: float
    uncertainty: float


class CoalitionArbiter:
    DEFAULT_WEIGHTS: Mapping[str, float] = {
        "expected_need_relief": 0.30,
        "expected_action_efficacy": 0.20,
        "expected_epistemic_value": 0.15,
        "value_congruence": 0.15,
        "project_contribution": 0.10,
        "historical_success": 0.10,
        "substrate_cost": -0.15,
        "uncertainty": -0.10,
        "commitment_conflict": -0.10,
    }

    def __init__(
        self,
        *,
        id_factory: Callable[[], str],
        clock: Callable[[], float],
        random_source: random.Random | None = None,
        weights: Mapping[str, float] | None = None,
        deterministic: bool = True,
    ) -> None:
        self._id_factory = id_factory
        self._clock = clock
        self._random = random_source or random.Random(0)
        self._weights = dict(weights or self.DEFAULT_WEIGHTS)
        self._deterministic = deterministic

    @staticmethod
    def _compatibility_key(proposal: ActionProposal) -> tuple[str, tuple[tuple[str, str], ...]]:
        stable_args = tuple(sorted((str(key), repr(value)) for key, value in proposal.arguments.items()))
        return proposal.action_kind, stable_args

    def build_compatible_coalitions(self, proposals: tuple[ActionProposal, ...]) -> tuple[tuple[ActionProposal, ...], ...]:
        grouped: dict[tuple[str, tuple[tuple[str, str], ...]], list[ActionProposal]] = {}
        for proposal in proposals:
            grouped.setdefault(self._compatibility_key(proposal), []).append(proposal)
        return tuple(tuple(grouped[key]) for key in sorted(grouped, key=repr))

    def _score(self, coalition: tuple[ActionProposal, ...]) -> CoalitionScore:
        if not coalition:
            raise ValueError("coalition must not be empty")
        def aggregate(name: str) -> float:
            values = [float(getattr(proposal, name)) for proposal in coalition]
            # Compatible supporters add evidence but do not multiply utility without bound.
            return min(1.0, max(values) + 0.15 * sum(sorted(values, reverse=True)[1:]))

        components = {name: aggregate(name) for name in self._weights}
        total = sum(self._weights[name] * components[name] for name in self._weights)
        digest = hashlib.sha256("|".join(sorted(p.proposal_id for p in coalition)).encode("utf-8")).hexdigest()[:16]
        return CoalitionScore(
            coalition_id=f"coalition:{digest}",
            proposals=coalition,
            score=total,
            pragmatic_value=max(0.0, min(1.0, (
                components["expected_need_relief"] + components["expected_action_efficacy"] + components["value_congruence"]
            ) / 3.0)),
            epistemic_value=components["expected_epistemic_value"],
            uncertainty=components["uncertainty"],
        )

    def choose(
        self,
        proposals: tuple[ActionProposal, ...],
        *,
        beliefs: tuple[Belief, ...] = (),
        values: tuple[Value, ...] = (),
        commitments: tuple[CommitmentLedger, ...] = (),
        substrate: OrganismicSubstrate | None = None,
        observation_ref: str = "",
        appraisal_refs: tuple[str, ...] = (),
        substrate_ref: str = "",
        temperature: float = 0.20,
    ) -> MindDecision:
        del commitments, substrate  # Các ràng buộc đã được projection vào proposal; refs vẫn được giữ dưới đây.
        if not proposals:
            raise ValueError("at least one proposal is required")
        scores = tuple(self._score(coalition) for coalition in self.build_compatible_coalitions(proposals))
        ordered = sorted(scores, key=lambda item: (-item.score, item.coalition_id))
        if self._deterministic or temperature <= 0 or len(ordered) == 1:
            winner = ordered[0]
        else:
            maximum = max(score.score for score in ordered)
            weights = [math.exp((score.score - maximum) / max(temperature, 1e-6)) for score in ordered]
            winner = self._random.choices(ordered, weights=weights, k=1)[0]

        primary = sorted(winner.proposals, key=lambda p: (-p.expected_need_relief, p.proposal_id))[0]
        supporting = tuple(dict.fromkeys(need for proposal in winner.proposals for need in proposal.supporting_need_ids))
        dissenting = tuple(dict.fromkeys(
            need
            for scored in ordered
            if scored.coalition_id != winner.coalition_id
            for proposal in scored.proposals
            for need in proposal.supporting_need_ids
            if need not in supporting
        ))

        # Không dump toàn bộ belief/value. Chỉ giữ refs đã thực sự liên quan tới
        # lựa chọn thắng, để decision có causal trace mà không trở thành dashboard toàn tri.
        value_refs: list[str] = []
        for proposal in winner.proposals:
            trace = proposal.arguments.get("inner_trace")
            if isinstance(trace, Mapping):
                value_refs.extend(str(item) for item in trace.get("value_refs", ()))
        if not value_refs and primary.arguments.get("principle"):
            principle = str(primary.arguments.get("principle")).casefold()
            value_refs.extend(
                value.value_id
                for value in values
                if principle in value.statement.casefold() or value.statement.casefold() in principle
            )
        belief_refs = tuple(
            belief.belief_id
            for belief in beliefs
            if belief.status == "active" and belief.confidence >= 0.55
        )[:8]

        return MindDecision(
            decision_id=self._id_factory(),
            coalition_id=winner.coalition_id,
            proposed_action=primary.action_kind,
            arguments=primary.arguments,
            expected_pragmatic_value=winner.pragmatic_value,
            expected_epistemic_value=winner.epistemic_value,
            uncertainty=winner.uncertainty,
            supporting_need_ids=supporting,
            dissenting_need_ids=dissenting,
            belief_refs=belief_refs,
            value_refs=tuple(dict.fromkeys(value_refs))[:8],
            observation_ref=observation_ref,
            appraisal_refs=appraisal_refs,
            substrate_ref=substrate_ref,
            proposal_refs=tuple(proposal.proposal_id for proposal in winner.proposals),
            created_at=self._clock(),
        )
