# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate
from runtime.expression_commitment_transition_v102 import ExpressionCommitmentTransitionV102
from runtime.expression_urge_runtime import ExpressionUrgeRuntime


class _Logger:
    def debug(self, *args, **kwargs):
        pass
    def info(self, *args, **kwargs):
        pass
    def warning(self, *args, **kwargs):
        pass


class _Host:
    def __init__(self):
        self.logger = _Logger()
        self.expression_consummation_runtime = None
        self.expression_commitment_transition_v102 = ExpressionCommitmentTransitionV102(
            self, logger=self.logger
        )


def _urge(
    *,
    urge_id: str = "urge:v102",
    content: str = "Cái transition commitment hiện vẫn còn quá tức thời và nên có state riêng.",
    pressure: float = 0.82,
    freshness: float = 0.96,
    satisfaction: float = 0.0,
):
    return SimpleNamespace(
        urge_id=urge_id,
        content=content,
        motive="share",
        satisfaction=satisfaction,
        confidence=0.82,
        relevance=0.78,
        _pressure=pressure,
        _freshness=freshness,
    )


def _private_intention_affordance(topic: str = "Transition này nên sống qua thời gian trước khi commit public."):
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="random_chat",
        topic=topic,
        speech_act="share_self_originated_thought",
        anchor_type="internal",
        anchor_id="private-intent:v102",
        evidence_refs=("focus:v102", "material:v102"),
        confidence=0.82,
        relevance=0.78,
        urgency=0.42,
        tone="natural",
        reason="private_intention_v101:ready",
        source="private_intention_v101",
        seed_id="material:v102",
        seed_mode="eris_led",
        source_kind="private_intention",
        eris_motive_kind="want_to_share",
        eris_motive_why_now="sustained private intention",
        personal_stake=0.78,
        authenticity=0.82,
        uncertainty=0.18,
        seed_quality_score=0.82,
        seed_specificity=0.86,
        seed_motive_strength=0.82,
        seed_semantic_completeness=0.84,
    )
    return ExecutiveAffordance(
        affordance_id="private-intention:private-intent:v102",
        owner="private_intention_v101",
        revision=1,
        candidate=candidate,
        claim_required=False,
        expires_at=180.0,
        metadata={
            "private_intention_v101": True,
            "intent_id": "private-intent:v102",
            "object_key": "focus:v102",
            "material_id": "material:v102",
            "state": "ready",
        },
    )


def test_single_urge_observation_cannot_instantly_create_commitment():
    host = _Host()
    transition = host.expression_commitment_transition_v102
    urge = _urge()

    commitment = transition.consider_urge(
        urge,
        pressure=urge._pressure,
        freshness=urge._freshness,
        runtime_context={},
        now=100.0,
    )

    assert commitment is None
    row = transition.snapshot(now=100.0)[0]
    assert row["state"] in {"forming", "holding"}
    assert row["observations"] == 1
    assert row["charge"] < transition.OPEN_CHARGE


def test_sustained_urge_commits_on_later_tick_not_same_tick():
    host = _Host()
    transition = host.expression_commitment_transition_v102
    urge = _urge()

    assert transition.consider_urge(
        urge, pressure=0.82, freshness=0.96, runtime_context={}, now=100.0
    ) is None
    commitment = transition.consider_urge(
        urge, pressure=0.82, freshness=0.94, runtime_context={}, now=104.0
    )

    assert commitment
    assert commitment["origin"] == "expression_urge"
    assert commitment["source_id"] == urge.urge_id
    assert commitment["semantic_target"] == urge.content
    assert transition.snapshot(now=104.0)[0]["state"] == "committed"


def test_hard_boundary_defers_projection_without_erasing_maturity():
    host = _Host()
    transition = host.expression_commitment_transition_v102
    urge = _urge()

    assert transition.consider_urge(
        urge, pressure=0.82, freshness=0.96, runtime_context={}, now=100.0
    ) is None
    assert transition.consider_urge(
        urge,
        pressure=0.82,
        freshness=0.94,
        runtime_context={"awaiting_user_answer": True},
        now=104.0,
    ) is None
    deferred = transition.snapshot(now=104.0)[0]
    assert deferred["state"] == "holding"
    assert deferred["last_boundary_reason"] == "awaiting_user_answer"
    charge_during_hold = deferred["charge"]

    commitment = transition.consider_urge(
        urge, pressure=0.80, freshness=0.92, runtime_context={}, now=108.0
    )
    assert commitment
    reopened = transition.snapshot(now=108.0)[0]
    assert reopened["state"] == "committed"
    assert reopened["charge"] >= charge_during_hold


def test_committed_state_uses_hysteresis_instead_of_reranking_every_tick():
    host = _Host()
    transition = host.expression_commitment_transition_v102
    urge = _urge()
    transition.consider_urge(urge, pressure=0.82, freshness=0.96, runtime_context={}, now=100.0)
    assert transition.consider_urge(
        urge, pressure=0.82, freshness=0.94, runtime_context={}, now=104.0
    )

    # Một nhịp pressure thấp không đủ làm commitment rung OFF vì release band thấp hơn.
    still = transition.consider_urge(
        urge, pressure=0.25, freshness=0.55, runtime_context={}, now=108.0
    )
    assert still
    row = transition.snapshot(now=108.0)[0]
    assert row["state"] == "committed"
    assert row["charge"] >= transition.RELEASE_CHARGE


def test_semantic_shift_resets_commitment_maturity():
    host = _Host()
    transition = host.expression_commitment_transition_v102
    urge = _urge()
    transition.consider_urge(urge, pressure=0.82, freshness=0.96, runtime_context={}, now=100.0)
    assert transition.consider_urge(
        urge, pressure=0.82, freshness=0.94, runtime_context={}, now=104.0
    )

    shifted = _urge(
        content="Ngày mai có mưa nên nhớ mang dép chống nước.",
        pressure=0.86,
        freshness=1.0,
    )
    assert transition.consider_urge(
        shifted, pressure=0.86, freshness=1.0, runtime_context={}, now=108.0
    ) is None
    row = transition.snapshot(now=108.0)[0]
    assert row["semantic_shifts"] == 1
    assert row["state"] != "committed"
    assert row["observations"] == 1


def test_public_receipt_cools_transition_without_feeding_public_text_back():
    host = _Host()
    transition = host.expression_commitment_transition_v102
    urge = _urge()
    transition.consider_urge(urge, pressure=0.82, freshness=0.96, runtime_context={}, now=100.0)
    assert transition.consider_urge(
        urge, pressure=0.82, freshness=0.94, runtime_context={}, now=104.0
    )

    assert transition.note_expressed(urge.urge_id, now=108.0)
    row = transition.snapshot(now=108.0)[0]
    assert row["state"] == "cooling"
    assert row["satisfaction"] == 1.0
    assert row["committed_age_seconds"] == 0.0


def test_expression_urge_runtime_production_path_waits_for_v102_commitment():
    host = _Host()
    runtime = ExpressionUrgeRuntime(host)
    affordance = _private_intention_affordance()

    first = runtime.shape_affordances(
        (affordance,),
        relational={},
        affect={},
        runtime_context={},
        now=100.0,
        limit=3,
    )
    assert not any(
        bool(getattr(item.candidate, "expression_commitment", {}))
        for item in first
        if getattr(item, "owner", "") == "expression_urge"
    )
    assert runtime.snapshot(now=100.0)

    second = runtime.shape_affordances(
        (affordance,),
        relational={},
        affect={},
        runtime_context={},
        now=104.0,
        limit=3,
    )
    committed = [item for item in second if getattr(item, "owner", "") == "expression_urge"]
    assert committed
    assert committed[0].candidate.expression_commitment


def test_production_wiring_routes_expression_urge_through_v102_transition():
    root = Path(__file__).resolve().parents[1]
    urge_source = (root / "runtime" / "expression_urge_runtime.py").read_text(encoding="utf-8")
    pipeline = (root / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py").read_text(encoding="utf-8")
    bootstrap = (root / "runtime" / "coordinator_bootstrap.py").read_text(encoding="utf-8")

    assert 'expression_commitment_transition_v102' in bootstrap
    assert 'consider = getattr(transition, "consider_urge", None)' in urge_source
    assert 'runtime_context=commitment_context_v102' in pipeline
    assert 'planner_snapshot["v102_expression_urge_direct_commitment"] = False' in pipeline
