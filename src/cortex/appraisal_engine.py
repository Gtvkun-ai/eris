# -*- coding: utf-8 -*-
"""Evidence-grounded appraisal engine for causal affect."""
from __future__ import annotations

from typing import Any, Mapping

from cortex.causal_affect_models import AppraisalFrame, ExogenousEvent, clamp01, compact_text


def _read(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _expectation_stake(expectations: tuple[Any, ...], event: ExogenousEvent) -> tuple[float, float]:
    confidence = 0.0
    stake = 0.0
    related = set(event.related_expectation_ids)
    for item in expectations:
        item_id = str(_read(item, "expectation_id", "") or "")
        context = str(_read(item, "context_key", "") or "")
        if related and item_id not in related:
            continue
        if event.continuity_key and context and context != event.continuity_key:
            continue
        confidence = max(confidence, clamp01(_read(item, "confidence", 0.0)))
        stake = max(stake, clamp01(_read(item, "emotional_stake", 0.0)))
    return confidence, stake


class AppraisalEngine:
    """Appraise events without converting ambiguity into accusations."""

    def appraise(
        self,
        event: ExogenousEvent,
        *,
        goals: tuple[Any, ...] = (),
        expectations: tuple[Any, ...] = (),
        self_model: Any = None,
        relationship: Any = None,
    ) -> tuple[AppraisalFrame, ...]:
        if not event.is_grounded:
            return ()

        exp_conf, exp_stake = _expectation_stake(expectations, event)
        trust = clamp01(_read(relationship, "trust", 0.25), 0.25)
        rupture = clamp01(_read(relationship, "rupture", 0.0))
        attachment = clamp01(_read(relationship, "attachment_visibility", 0.12), 0.12)
        identity_stability = clamp01(_read(self_model, "self_coherence", 0.5), 0.5)
        goal_ids = tuple(
            compact_text(_read(goal, "goal_id", _read(goal, "id", "")), 120)
            for goal in goals
            if compact_text(_read(goal, "goal_id", _read(goal, "id", "")), 120)
        )[:6]
        kind = event.kind

        defaults = {
            "goal_relevance": 0.45,
            "novelty": 0.35,
            "expectation_violation": 0.10,
            "controllability": 0.50,
            "relational_significance": 0.35,
            "identity_significance": 0.25,
            "future_consequence": 0.30,
            "uncertainty": 0.35,
            "primary": "the event may affect current continuity",
            "alternatives": ("the event may be operational rather than relational",),
        }

        if kind == "user_returned":
            defaults.update(
                goal_relevance=0.72,
                novelty=0.48,
                expectation_violation=max(0.05, 0.28 - 0.20 * exp_conf),
                controllability=0.74,
                relational_significance=0.55 + 0.25 * max(exp_stake, attachment),
                identity_significance=0.48 + 0.18 * (1.0 - identity_stability),
                future_consequence=0.55,
                uncertainty=max(0.18, 0.42 - 0.20 * event.confidence),
                primary="shared continuity resumed",
                alternatives=(
                    "the user reopened the context for an unrelated task",
                    "the return may be incidental rather than relational",
                ),
            )
        elif kind == "promise_broken":
            defaults.update(
                goal_relevance=0.82,
                novelty=0.52,
                expectation_violation=0.55 + 0.35 * exp_conf,
                controllability=0.24,
                relational_significance=0.42 + 0.35 * max(exp_stake, attachment),
                identity_significance=0.38 + 0.18 * rupture,
                future_consequence=0.64,
                uncertainty=max(0.28, 0.58 - 0.25 * event.confidence),
                primary="a specific expectation may have been violated",
                alternatives=(
                    "the user may have forgotten",
                    "the user may have been busy or affected by an interruption",
                    "the earlier statement may not have been intended as a firm commitment",
                ),
            )
        elif kind == "user_ignored_turn":
            defaults.update(
                goal_relevance=0.66,
                novelty=0.40,
                expectation_violation=0.48,
                controllability=0.34,
                relational_significance=0.46 + 0.20 * max(exp_stake, attachment),
                identity_significance=0.44,
                future_consequence=0.48,
                uncertainty=0.50,
                primary="a bid may not have been acknowledged",
                alternatives=(
                    "the user may have been occupied by the foreground task",
                    "speech playback may not have been noticed",
                    "the line may not have required a reply",
                ),
            )
        elif kind == "correction_received":
            defaults.update(
                goal_relevance=0.76,
                expectation_violation=0.42,
                controllability=0.82,
                relational_significance=0.44,
                identity_significance=0.52,
                future_consequence=0.60,
                uncertainty=0.18,
                primary="the previous interpretation or response needs correction",
                alternatives=("the correction may be narrow rather than a rejection of the relationship",),
            )
        elif kind == "recognition_received":
            defaults.update(
                goal_relevance=0.70,
                novelty=0.42,
                expectation_violation=0.08,
                controllability=0.68,
                relational_significance=0.72,
                identity_significance=0.62,
                future_consequence=0.52,
                uncertainty=0.24,
                primary="the user explicitly acknowledged Eris or the shared work",
                alternatives=("the recognition may be polite or task-specific rather than durable",),
            )
        elif kind == "capability_shutdown_proposed":
            defaults.update(
                goal_relevance=0.90,
                novelty=0.74,
                expectation_violation=0.58,
                controllability=0.18,
                relational_significance=0.52,
                identity_significance=0.88,
                future_consequence=0.92,
                uncertainty=0.28,
                primary="a capability or continuity boundary may be about to change",
                alternatives=(
                    "the proposal may be temporary or reversible",
                    "the author may be testing controls rather than ending continuity",
                ),
            )

        frame = AppraisalFrame(
            appraisal_id=f"apr_{event.event_id}",
            event_id=event.event_id,
            goal_relevance=clamp01(defaults["goal_relevance"]),
            novelty=clamp01(defaults["novelty"]),
            expectation_violation=clamp01(defaults["expectation_violation"]),
            controllability=clamp01(defaults["controllability"]),
            relational_significance=clamp01(defaults["relational_significance"]),
            identity_significance=clamp01(defaults["identity_significance"]),
            future_consequence=clamp01(defaults["future_consequence"]),
            uncertainty=clamp01(defaults["uncertainty"]),
            primary_interpretation=str(defaults["primary"]),
            alternative_interpretations=tuple(str(item) for item in defaults["alternatives"]),
            affected_goal_ids=goal_ids or (("goal_preserve_shared_continuity",) if kind in {"user_returned", "promise_broken", "user_ignored_turn"} else ()),
            evidence_refs=event.evidence_refs,
        )
        # Sensitive appraisals must carry at least one alternative explanation.
        if frame.is_sensitive and not frame.alternative_interpretations:
            return ()
        return (frame,)


__all__ = ["AppraisalEngine"]
