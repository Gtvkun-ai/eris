# -*- coding: utf-8 -*-
"""Neuro-inspired control layer for Subject Core.

This module deliberately does *less* than the old Executive LLM path.
It turns already-grounded coalition scores into fast action competition and only
asks for expensive deliberation when the competition itself is ambiguous.

The neuroscience analogy is intentionally modest:

* ``WorkspaceBroadcast`` ~= a tiny global-workspace broadcast: only the strongest
  current signals are exposed, never the whole private state dump.
* ``NeuroActionSelector`` ~= basal-ganglia-like gating: candidate action channels
  compete using salience/value/uncertainty and one channel is released.
* ``surprise`` / ``precision`` / ``resource`` are global modulators. They change
  selection gain; they are not new semantic flags or a fake neurotransmitter model.

Important engineering invariant: LLMs never need coalition IDs here. Runtime owns
identity; the model, when invited to deliberate, only receives ephemeral choice
indices local to the current frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import CoalitionCandidate, SubjectDeliberationFrame


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class WorkspaceSignal:
    """One bounded item allowed to win global broadcast for this decision cycle."""

    kind: str
    label: str
    salience: float
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "salience": self.salience,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceBroadcast:
    """Small public-safe projection of what currently matters most."""

    signals: tuple[WorkspaceSignal, ...]
    surprise: float
    precision: float
    resource: float
    social_drive: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "signals": [item.to_dict() for item in self.signals],
            "modulators": {
                "surprise": self.surprise,
                "precision": self.precision,
                "resource": self.resource,
                "social_drive": self.social_drive,
            },
        }


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Result of fast action competition.

    ``winner_index`` is ephemeral and only meaningful inside ``frame``.  This is
    the point: no model-owned runtime identity survives into a later frame.
    """

    winner_index: int
    scores: tuple[float, ...]
    probabilities: tuple[float, ...]
    margin: float
    entropy: float
    requires_deliberation: bool
    reason: str
    broadcast: WorkspaceBroadcast

    def winner(self, frame: SubjectDeliberationFrame) -> CoalitionCandidate:
        return frame.coalitions[self.winner_index]


@dataclass(frozen=True, slots=True)
class NeuroControlConfig:
    """A few continuous thresholds, not a forest of semantic booleans."""

    deliberation_margin: float = 0.075
    uncertainty_threshold: float = 0.52
    entropy_threshold: float = 0.82
    surprise_threshold: float = 0.74
    conflict_threshold: float = 0.60
    max_broadcast_signals: int = 3


class NeuroActionSelector:
    """Fast, deterministic action gate over Subject Core coalitions."""

    def __init__(self, config: NeuroControlConfig | None = None) -> None:
        self.config = config or NeuroControlConfig()

    def workspace(self, frame: SubjectDeliberationFrame) -> WorkspaceBroadcast:
        # Production receives a typed SubjectDeliberationFrame. ``getattr``
        # defaults keep the selector usable by degraded adapters/tests that only
        # expose ranked coalitions; absence of a signal means neutral modulation,
        # not invented cognition.
        appraisals = tuple(getattr(frame, "appraisals", ()) or ())
        activations = tuple(getattr(frame, "activations", ()) or ())

        surprise = max(
            (
                max(_clamp01(item.novelty), _clamp01(item.expectation_violation))
                for item in appraisals
            ),
            default=0.0,
        )
        appraisal_uncertainty = max((_clamp01(item.uncertainty) for item in appraisals), default=0.0)
        coalition_uncertainty = min(
            (_clamp01(item.uncertainty, 1.0) for item in frame.coalitions),
            default=1.0,
        )
        # Precision is confidence in the current action landscape, not certainty
        # that every belief in the system is true.
        precision = _clamp01(1.0 - max(appraisal_uncertainty, coalition_uncertainty))
        substrate = getattr(frame, "substrate", None)
        resource = _clamp01(getattr(substrate, "processing_capacity", 1.0), 1.0)
        social_drive = max(
            (
                _clamp01(item.pressure) * (0.55 + 0.45 * _clamp01(item.opportunity))
                for item in activations
                if str(item.need_id).lower() == "connection"
            ),
            default=0.0,
        )

        signals: list[WorkspaceSignal] = []
        for item in appraisals:
            label = str(item.primary_interpretation or "appraisal").strip()[:220]
            salience = max(
                _clamp01(item.goal_relevance),
                _clamp01(item.relational_significance),
                _clamp01(item.identity_significance),
                _clamp01(item.expectation_violation),
            )
            confidence = _clamp01(1.0 - item.uncertainty)
            signals.append(WorkspaceSignal("appraisal", label, salience, confidence))

        for item in activations:
            salience = _clamp01(
                0.50 * _clamp01(item.pressure)
                + 0.30 * _clamp01(item.urgency)
                + 0.20 * _clamp01(item.persistence)
            )
            signals.append(
                WorkspaceSignal(
                    "need",
                    str(item.need_id),
                    salience,
                    _clamp01(0.5 + 0.5 * item.opportunity),
                )
            )

        # Predictive-processing motif without a duplicate world model: Subject
        # Core already carries a learned competence prediction and historical
        # outcome prior inside each proposal's inner_trace. Their disagreement is
        # useful epistemic surprise. It can win workspace broadcast and lower the
        # confidence of routine gating, but it never manufactures an action.
        predictive_disagreement = 0.0
        for proposal in (getattr(frame, "proposals", ()) or ()):
            arguments = dict(getattr(proposal, "arguments", {}) or {})
            trace = dict(arguments.get("inner_trace", {}) or {})
            if "competence_prediction" not in trace or "historical_success" not in trace:
                continue
            learned = _clamp01(trace.get("competence_prediction"), 0.5)
            historical = _clamp01(trace.get("historical_success"), 0.5)
            disagreement = abs(learned - historical)
            predictive_disagreement = max(predictive_disagreement, disagreement)
            if disagreement >= 0.18:
                signals.append(WorkspaceSignal(
                    "prediction_error_prior",
                    str(getattr(proposal, "action_kind", "action") or "action"),
                    _clamp01(disagreement),
                    _clamp01(1.0 - getattr(proposal, "uncertainty", 0.5), 0.5),
                ))

        surprise = max(surprise, _clamp01(predictive_disagreement))
        precision = _clamp01(precision * (1.0 - 0.35 * predictive_disagreement))

        ordered = tuple(
            sorted(signals, key=lambda item: (-item.salience, -item.confidence, item.kind, item.label))[
                : max(1, int(self.config.max_broadcast_signals))
            ]
        )
        return WorkspaceBroadcast(
            signals=ordered,
            surprise=surprise,
            precision=precision,
            resource=resource,
            social_drive=social_drive,
        )

    @staticmethod
    def _commitment_conflict(frame: SubjectDeliberationFrame, candidate: CoalitionCandidate) -> float:
        proposals = {
            item.proposal_id: item
            for item in (getattr(frame, "proposals", ()) or ())
            if getattr(item, "proposal_id", "")
        }
        return max(
            (
                _clamp01(proposals[ref].commitment_conflict)
                for ref in (getattr(candidate, "proposal_refs", ()) or ())
                if ref in proposals
            ),
            default=0.0,
        )

    def _channel_score(
        self,
        frame: SubjectDeliberationFrame,
        candidate: CoalitionCandidate,
        broadcast: WorkspaceBroadcast,
    ) -> float:
        """Modulate existing causal score instead of replacing Subject Core.

        The arbiter already did the structured work.  These small terms only
        change gain according to global state: when precision falls, epistemic
        actions matter more; when resources fall, uncertain/costly channels lose
        ground.  Keeping the modulation weak prevents a pretty neuroscience name
        from silently becoming a second policy engine.
        """

        # Some degraded adapters expose only the already-ranked order and a
        # pragmatic/uncertainty summary. In that case pragmatic value is a safe
        # neutral base; equal channels retain tuple order as the tie-breaker.
        score = float(
            getattr(
                candidate,
                "score",
                getattr(candidate, "expected_pragmatic_value", 0.0),
            )
            or 0.0
        )
        pragmatic = _clamp01(getattr(candidate, "expected_pragmatic_value", 0.0))
        epistemic = _clamp01(getattr(candidate, "expected_epistemic_value", 0.0))
        uncertainty = _clamp01(getattr(candidate, "uncertainty", 0.5), 0.5)
        score += 0.08 * broadcast.precision * pragmatic
        score += 0.10 * (1.0 - broadcast.precision) * epistemic
        score -= 0.08 * (1.0 - broadcast.resource) * uncertainty

        # Outcome-adaptive prior without trainable selector state. Subject Core's
        # competence/history estimators are already updated by real outcomes; the
        # gate reads that learned prior from the proposal it is evaluating. This
        # keeps one learning authority instead of teaching a second policy model
        # behind the arbiter's back.
        proposals = {
            item.proposal_id: item
            for item in (getattr(frame, "proposals", ()) or ())
            if getattr(item, "proposal_id", "")
        }
        learned_values: list[float] = []
        for ref in (getattr(candidate, "proposal_refs", ()) or ()):
            proposal = proposals.get(ref)
            if proposal is None:
                continue
            trace = dict(dict(getattr(proposal, "arguments", {}) or {}).get("inner_trace", {}) or {})
            if "competence_prediction" in trace:
                learned_values.append(_clamp01(trace.get("competence_prediction"), 0.5))
            if "historical_success" in trace:
                learned_values.append(_clamp01(trace.get("historical_success"), 0.5))
        if learned_values:
            learned_prior = sum(learned_values) / len(learned_values)
            score += 0.06 * (learned_prior - 0.5)

        action = str(candidate.action_kind or "").lower()
        if action == "speak":
            score += 0.035 * broadcast.social_drive
        elif action == "silence":
            score += 0.025 * (1.0 - broadcast.social_drive)
        return score

    @staticmethod
    def _softmax(scores: Sequence[float], beta: float) -> tuple[float, ...]:
        if not scores:
            return ()
        peak = max(scores)
        exps = [math.exp(max(-60.0, min(60.0, beta * (score - peak)))) for score in scores]
        total = sum(exps) or 1.0
        return tuple(value / total for value in exps)

    @staticmethod
    def _normalized_entropy(probabilities: Sequence[float]) -> float:
        if len(probabilities) <= 1:
            return 0.0
        entropy = -sum(p * math.log(max(p, 1e-12)) for p in probabilities)
        return _clamp01(entropy / math.log(len(probabilities)))

    def select(self, frame: SubjectDeliberationFrame) -> SelectionResult:
        if not frame.coalitions:
            raise ValueError("neuro selector requires at least one coalition")

        broadcast = self.workspace(frame)

        # Compatibility/degraded adapters may expose only a ranked tuple instead
        # of the full typed frame. In that case the ranking *is* the available
        # evidence. Do not invent uncertainty and do not wake a deliberator merely
        # because diagnostic detail is absent.
        rank_only = (
            not hasattr(frame, "appraisals")
            or not all(hasattr(item, "score") for item in frame.coalitions)
        )
        if rank_only:
            scores = tuple(1.0 - 0.01 * index for index, _item in enumerate(frame.coalitions))
            probabilities = self._softmax(scores, beta=10.0)
            return SelectionResult(
                winner_index=0,
                scores=scores,
                probabilities=probabilities,
                margin=(scores[0] - scores[1] if len(scores) > 1 else 1.0),
                entropy=self._normalized_entropy(probabilities),
                requires_deliberation=False,
                reason="fast_gate:ranked_adapter",
                broadcast=broadcast,
            )

        scores = tuple(self._channel_score(frame, item, broadcast) for item in frame.coalitions)
        order = sorted(range(len(scores)), key=lambda idx: (-scores[idx], idx))
        winner_index = order[0]
        runner_index = order[1] if len(order) > 1 else winner_index
        margin = scores[winner_index] - scores[runner_index] if len(order) > 1 else 1.0

        # Precision controls the sharpness of competition. High uncertainty makes
        # the distribution flatter, which naturally increases deliberation chance.
        beta = 3.0 + 7.0 * broadcast.precision
        probabilities = self._softmax(scores, beta)
        entropy = self._normalized_entropy(probabilities)
        winner = frame.coalitions[winner_index]
        conflict = self._commitment_conflict(frame, winner)

        reasons: list[str] = []
        if len(frame.coalitions) > 1 and margin < self.config.deliberation_margin:
            reasons.append("low_margin")
        if _clamp01(getattr(winner, "uncertainty", 0.5), 0.5) >= self.config.uncertainty_threshold:
            reasons.append("winner_uncertain")
        if entropy >= self.config.entropy_threshold:
            reasons.append("high_entropy")
        if broadcast.surprise >= self.config.surprise_threshold and broadcast.precision < 0.62:
            reasons.append("surprising_low_precision")
        if conflict >= self.config.conflict_threshold:
            reasons.append("commitment_conflict")

        requires = bool(reasons)
        return SelectionResult(
            winner_index=winner_index,
            scores=scores,
            probabilities=probabilities,
            margin=margin,
            entropy=entropy,
            requires_deliberation=requires,
            reason=("deliberate:" + ",".join(reasons)) if requires else "fast_gate:clear_winner",
            broadcast=broadcast,
        )


__all__ = [
    "NeuroActionSelector",
    "NeuroControlConfig",
    "SelectionResult",
    "WorkspaceBroadcast",
    "WorkspaceSignal",
]
