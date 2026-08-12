from __future__ import annotations

import asyncio

from cortex.subject.contracts import WorldObservation
from cortex.subject.needs import NeedSystem
from cortex.subject.relational import RelationalHomeostasis, RelationalState
from cortex.subject.service import SubjectService, SubjectServiceConfig
from runtime.relational_affordance import build_relational_affordance
from runtime.temporal_mind import TemporalMind, TemporalMindConfig, TemporalSignal


def test_relational_deficit_grows_without_external_event() -> None:
    home = RelationalHomeostasis()
    state = RelationalState(updated_at=100.0, last_meaningful_exchange_at=100.0)
    later = home.tick(
        state,
        now=1300.0,
        partner_available=0.8,
        interruption_cost=0.1,
        curiosity_signal=0.35,
        evidence_refs=("clock:quiet",),
    )
    assert later.affiliation_deficit > 0.60
    assert later.connection_pressure > 0.45
    assert later.outreach_drive > 0.35
    assert "clock:quiet" in later.evidence_refs


def test_user_reciprocity_reduces_deficit_and_learns_outreach_success() -> None:
    home = RelationalHomeostasis()
    state = RelationalState(
        updated_at=100.0,
        last_outreach_at=110.0,
        outreach_waiting=True,
        affiliation_deficit=0.82,
        outreach_confidence=0.45,
        reciprocity_expectation=0.45,
    )
    updated = home.note_user_turn(
        state,
        now=130.0,
        meaningful=True,
        engagement=0.9,
        evidence_ref="user-turn:1",
    )
    assert updated.successful_outreach == 1
    assert updated.outreach_waiting is False
    assert updated.affiliation_deficit < 0.30
    assert updated.outreach_confidence > state.outreach_confidence
    assert updated.reciprocity_expectation > state.reciprocity_expectation


def test_non_reply_bearing_startup_contact_satisfies_state_without_waiting() -> None:
    home = RelationalHomeostasis()
    state = RelationalState(
        updated_at=100.0,
        affiliation_deficit=0.90,
        interaction_satiety=0.02,
        unanswered_outreach=3,
    )
    updated = home.note_public_act(
        state,
        now=120.0,
        outreach=True,
        expect_response=False,
        evidence_ref="startup_greeting:test",
    )
    assert updated.last_outreach_at == 120.0
    assert updated.outreach_waiting is False
    assert updated.affiliation_deficit < state.affiliation_deficit
    assert updated.interaction_satiety >= 0.28

    # Crossing the ordinary response window must not turn a gentle startup
    # greeting into a failed outreach merely because the user stayed quiet.
    later = home.tick(updated, now=300.0)
    assert later.unanswered_outreach == 3


def test_relational_affordance_needs_no_external_factual_pretext() -> None:
    state = RelationalState(
        revision=7,
        updated_at=100.0,
        affiliation_deficit=0.75,
        interaction_satiety=0.05,
        partner_availability=0.85,
        interruption_cost=0.08,
        outreach_confidence=0.72,
        reciprocity_expectation=0.70,
        evidence_refs=("relational:history:7",),
    )
    affordance = build_relational_affordance(state.to_dict(), now=200.0)
    assert affordance is not None
    assert affordance.owner == "subject_relational_homeostasis"
    assert affordance.candidate.kind == "social_check_in"
    assert affordance.candidate.requires_grounding is False
    assert "relational-state:7" in affordance.candidate.evidence_refs
    assert "fabricate" in affordance.candidate.topic.lower() or "do not invent" in affordance.candidate.topic.lower()


def test_connection_need_can_activate_from_relational_homeostasis() -> None:
    service = SubjectService(config=SubjectServiceConfig(restore_projection=False))
    substrate = service.substrate
    system = NeedSystem()
    relational = RelationalState(
        revision=4,
        affiliation_deficit=0.82,
        partner_availability=0.9,
        interruption_cost=0.05,
        outreach_confidence=0.8,
        evidence_refs=("relational:test",),
    ).to_dict()
    activations = system.activate(substrate, (), relational=relational)
    connection = next(item for item in activations if item.need_id == "connection")
    assert connection.pressure >= 0.80
    assert connection.opportunity >= 0.65
    assert any(ref.startswith("relational-state:") for ref in connection.evidence_refs)


def test_need_effects_make_high_connection_pressure_penalize_silence() -> None:
    now = 2000.0
    service = SubjectService(
        config=SubjectServiceConfig(restore_projection=False),
        clock=lambda: now,
        id_factory=(lambda counter=iter(range(10000)): f"id-{next(counter)}"),
    )
    service.relational_state = RelationalState(
        revision=9,
        updated_at=now,
        last_meaningful_exchange_at=now - 2400.0,
        affiliation_deficit=0.92,
        interaction_satiety=0.02,
        partner_availability=0.92,
        interruption_cost=0.05,
        outreach_confidence=0.84,
        reciprocity_expectation=0.78,
        evidence_refs=("relational:history",),
    )
    observation = WorldObservation(
        observation_id="obs-relational",
        subject_id="eris",
        kind="autonomous_opportunity",
        created_at=now,
        context={
            "context_key": "autonomous",
            "affected_need_ids": ("connection",),
            "goal_relevance": 0.8,
            "novelty": 0.1,
            "controllability": 0.9,
            "relational_significance": 0.95,
            "future_consequence": 0.6,
            "uncertainty": 0.2,
            "action_proposals": (
                {
                    "proposal_id": "contact",
                    "action_kind": "speak",
                    "arguments": {"affordance_id": "relational:contact:9", "speech_act": "contact_bid"},
                    "supporting_need_ids": ("connection",),
                    "expected_need_relief": 0.48,
                    "expected_action_efficacy": 0.82,
                    "expected_epistemic_value": 0.12,
                    "value_congruence": 0.5,
                    "substrate_cost": 0.08,
                    "uncertainty": 0.18,
                    "commitment_conflict": 0.05,
                    "need_effects": {"connection": 0.75, "sovereignty": -0.08},
                    "evidence_refs": ("relational:history",),
                },
                {
                    "proposal_id": "silence",
                    "action_kind": "silence",
                    "arguments": {"reason_family": "wait"},
                    "supporting_need_ids": ("sovereignty", "coherence"),
                    "expected_need_relief": 0.44,
                    "expected_action_efficacy": 0.96,
                    "expected_epistemic_value": 0.24,
                    "value_congruence": 0.5,
                    "substrate_cost": 0.01,
                    "uncertainty": 0.10,
                    "commitment_conflict": 0.04,
                    "need_effects": {"sovereignty": 0.42, "coherence": 0.22, "connection": -0.72},
                    "evidence_refs": ("obs-relational",),
                },
            ),
            "runtime_context": {
                "partner_available": 0.92,
                "interruption_cost": 0.05,
                "relational_evidence_refs": ("relational:history",),
            },
        },
        evidence_refs=("obs-relational",),
    )
    frame = asyncio.run(service.prepare_deliberation(observation))
    assert frame.coalitions[0].action_kind == "speak"
    silence = next(item for item in frame.proposals if item.action_kind == "silence")
    contact = next(item for item in frame.proposals if item.action_kind == "speak")
    assert contact.expected_need_relief > silence.expected_need_relief
    assert contact.commitment_conflict < silence.commitment_conflict


def test_relational_pressure_can_wake_temporal_mind() -> None:
    mind = TemporalMind(config=TemporalMindConfig(wake_threshold=0.32), clock=lambda: 100.0)
    gate = mind.observe(
        (TemporalSignal("relational_pressure", 0.92, "subject_relational_homeostasis"),),
        now=100.0,
    )
    assert gate.wake is True
    assert gate.dominant_kind == "relational_pressure"


def test_relational_affordance_enters_subject_frame_and_beats_silence() -> None:
    from runtime.subject_ingress import SubjectIngress

    class Blackboard:
        reply_expected = False
        engagement_active = False
        user_busy = False

        @staticmethod
        def public_view():
            return {"reply_expected": False, "engagement_active": False, "novelty": 0.1}

    now = 3000.0
    service = SubjectService(
        config=SubjectServiceConfig(restore_projection=False),
        clock=lambda: now,
        id_factory=(lambda counter=iter(range(10000)): f"rid-{next(counter)}"),
    )
    service.relational_state = RelationalState(
        revision=12,
        updated_at=now,
        last_meaningful_exchange_at=now - 2200.0,
        affiliation_deficit=0.90,
        interaction_satiety=0.02,
        partner_availability=0.90,
        interruption_cost=0.06,
        outreach_confidence=0.80,
        reciprocity_expectation=0.76,
        evidence_refs=("relational:episode:12",),
    )
    affordance = build_relational_affordance(service.relational_view(), now=now)
    assert affordance is not None
    ingress = SubjectIngress(service)
    session = ingress.prepare_autonomous_session(
        Blackboard(),
        (affordance,),
        created_at=now,
        turn_id="autonomous:12",
        planning_context={"relational_state": service.relational_view()},
    )
    frame = session.frame
    assert any(item.action_kind == "speak" for item in frame.coalitions)
    assert frame.coalitions[0].action_kind == "speak"
    assert frame.coalitions[0].arguments.get("affordance_id") == affordance.affordance_id


def test_relational_pressure_is_owned_by_temporal_mind_not_executive_policy() -> None:
    # V30: relational pressure vẫn đánh thức cognition, nhưng đi qua TemporalMind
    # trực tiếp thay vì một ExecutiveState/reconsider policy song song.
    mind = TemporalMind(config=TemporalMindConfig(wake_threshold=0.25), clock=lambda: 100.0)
    decision = mind.observe(
        (TemporalSignal("relational_pressure", 0.80, "subject_relational_homeostasis"),),
        now=100.0,
    )
    assert decision.wake is True
    assert decision.dominant_kind == "relational_pressure"
