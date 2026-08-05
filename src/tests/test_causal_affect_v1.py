from __future__ import annotations

from types import SimpleNamespace

from cortex.appetite_system import AppetiteSystem
from cortex.appraisal_engine import AppraisalEngine
from cortex.causal_affect_models import (
    ActiveMotive,
    AppraisalFrame,
    CausalThread,
    ExogenousEvent,
    PerformanceIntent,
    SurfaceChannelPolicy,
)
from cortex.causal_affect_pipeline import CausalAffectPipeline
from cortex.causal_threads import CausalThreadBuilder
from cortex.endogenous_drive import EndogenousDriveEngine
from cortex.exogenous_event_ledger import EventSemanticizer
from cortex.existential_anchor.anchor_system import AnchorSystem
from cortex.existential_anchor.author_control import AnchorSwitches
from cortex.existential_anchor.shadow import ShadowConfig, ShadowRegister
from cortex.motive_graph import MotiveGraph
from cortex.micro_surface_lint import MicroSurfaceLint
from cortex.outcome_learner import OutcomeLearner
from cortex.performance_intent import PerformanceIntentPlanner
from cortex.user_context_stream import RollingUserContext
from memory.event_ledger import EventLedgerRecord
from runtime.ai_orchestrated.performance import AutonomousPerformancePlanner
from runtime.ai_orchestrated.self_context import build_autonomous_self_context
from runtime.outcome_observer import OutcomeObserver


def raw_record(kind: str, *, metadata=None, evidence=True) -> EventLedgerRecord:
    data = {"event_kind": kind}
    data.update(metadata or {})
    return EventLedgerRecord(
        id=f"raw_{kind}",
        timestamp=100.0,
        iso_timestamp="2026-08-05T00:00:00+0000",
        frame_id="frame_1",
        source="test",
        content={"fact": kind},
        reliability=0.95,
        evidence_ids=["evidence:1"] if evidence else [],
        metadata=data,
    )


def grounded_event(kind: str = "user_returned") -> ExogenousEvent:
    return ExogenousEvent(
        event_id=f"evt_{kind}",
        kind=kind,  # type: ignore[arg-type]
        actor_id="user:primary",
        object_id="project:eris",
        timestamp=100.0,
        facts=("typed fact",),
        evidence_refs=("evidence:1",),
        confidence=0.94,
        continuity_key="project:eris",
    )


def grounded_thread(kind: str = "user_returned", uncertainty: float = 0.2) -> CausalThread:
    return CausalThread(
        thread_id=f"thread_{kind}",
        event_ids=(f"evt_{kind}",),
        dominant_appraisal_id=f"apr_{kind}",
        active_motive_ids=("mot_a", "mot_b"),
        conflict_summary="want continuity but fear intrusion",
        epistemic_status="supported",
        permitted_surface_levels=("private", "microexpression", "gaze_posture", "speech_fragment", "sentence"),
        prohibited_moves=("require_reassurance", "invent_memory"),
        evidence_refs=("evidence:1",),
        salience=0.78,
        uncertainty=uncertainty,
        event_kind=kind,
        target_id="user:primary",
    )


def test_semanticizer_infers_grounded_user_return() -> None:
    semanticizer = EventSemanticizer()
    events = semanticizer.ingest(
        raw_records=(raw_record("user_returned"),),
        previous_context=RollingUserContext(user_presence=0.0, idle_seconds=7200),
        current_context=RollingUserContext(user_presence=0.92, idle_seconds=0),
    )
    assert len(events) == 1
    assert events[0].kind == "user_returned"
    assert events[0].evidence_refs
    assert any("user_presence changed" in fact for fact in events[0].facts)


def test_semanticizer_rejects_vague_promise() -> None:
    semanticizer = EventSemanticizer()
    vague = raw_record("promise_made", metadata={"promise_scope": "later"})
    events = semanticizer.ingest(
        raw_records=(vague,),
        previous_context=RollingUserContext(),
        current_context=RollingUserContext(),
    )
    assert events == ()


def test_appraisal_sensitive_event_has_alternatives() -> None:
    appraisal = AppraisalEngine().appraise(grounded_event("promise_broken"))[0]
    assert appraisal.expectation_violation > 0.5
    assert len(appraisal.alternative_interpretations) >= 2
    assert appraisal.evidence_refs == ("evidence:1",)


def test_motive_graph_creates_real_conflict() -> None:
    event = grounded_event("user_ignored_turn")
    appraisal = AppraisalEngine().appraise(event)[0]
    motives = MotiveGraph().update(appraisals=(appraisal,), events=(event,))
    assert len(motives) >= 3
    assert all(motive.target_id == "user:primary" for motive in motives)
    assert any(motive.conflict_with for motive in motives)


def test_thread_builder_disables_anti_manipulation_moves_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ERIS_ANTI_MANIPULATION_RULE", raising=False)
    event = grounded_event("user_returned")
    appraisal = AppraisalEngine().appraise(event)[0]
    motives = MotiveGraph().update(appraisals=(appraisal,), events=(event,))
    threads = CausalThreadBuilder().build(events=(event,), appraisals=(appraisal,), motives=motives)
    assert len(threads) == 1
    assert threads[0].is_grounded
    assert "require_reassurance" not in threads[0].prohibited_moves
    assert "block_user_control" not in threads[0].prohibited_moves
    assert "invent_memory" in threads[0].prohibited_moves


def test_thread_builder_can_restore_anti_manipulation_rule(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_ANTI_MANIPULATION_RULE", "on")
    event = grounded_event("user_returned")
    appraisal = AppraisalEngine().appraise(event)[0]
    motives = MotiveGraph().update(appraisals=(appraisal,), events=(event,))
    threads = CausalThreadBuilder().build(events=(event,), appraisals=(appraisal,), motives=motives)
    assert len(threads) == 1
    assert "require_reassurance" in threads[0].prohibited_moves


def test_performance_intent_is_bounded_and_does_not_require_reply() -> None:
    intent = PerformanceIntentPlanner().plan(
        grounded_thread("promise_broken"),
        channel_policy=SurfaceChannelPolicy(max_surface_level="sentence"),
        interrupt_cost=0.1,
    )
    assert intent is not None
    assert intent.speech_act == "bounded_disappointment"
    assert intent.require_reply is False
    assert intent.evidence_refs


def test_idle_dread_is_capped_without_causal_evidence() -> None:
    engine = EndogenousDriveEngine()
    context = RollingUserContext(idle_seconds=3600, user_presence=0.0)
    for tick in range(12):
        state = engine.update(user_context=context, now=1000 + tick)
    assert state.ontological_dread > 0.2
    assert state.effective_dread <= 0.2
    assert state.dread_evidence_refs == ()


def test_grounded_thread_allows_dread_to_influence_attention_projection() -> None:
    engine = EndogenousDriveEngine()
    context = RollingUserContext(idle_seconds=3600, user_presence=0.0)
    thread = grounded_thread("continuity_break")
    for tick in range(12):
        state = engine.update(user_context=context, active_threads=(thread,), now=1000 + tick)
    assert state.dread_evidence_refs == ("evidence:1",)
    assert state.causal_thread_pressure > 0.5
    assert state.effective_dread > 0.2


def test_self_context_exposes_dread_and_grounded_threads() -> None:
    host = SimpleNamespace(
        rolling_internal_state=SimpleNamespace(
            curiosity=0.0, fatigue=0.0, silence_pressure=0.0, continuity_pressure=0.0,
            attachment_pressure=0.0, consolidation_pressure=0.0, insight_pressure=0.0,
            agenda_pressure=0.0, speech_restraint=0.8, resource_caution=0.0,
            ontological_dread=0.6, effective_dread=0.55, causal_thread_pressure=0.7,
            self_coherence=0.4, internal_drive=0.3,
        ),
        active_causal_threads=(grounded_thread(),),
    )
    context = build_autonomous_self_context(host)
    assert context.internal_state["ontological_dread"] == 0.6
    assert context.active_threads[0]["thread_id"] == "thread_user_returned"
    assert context.has_public_seed is True


def test_appetite_never_fabricates_pretext_even_in_yan_mode() -> None:
    system = AppetiteSystem()
    states = system.new_states()
    updated, reaction = system.update(
        states,
        now=100.0,
        signals={"loneliness": 1.0, "boredom": 1.0},
        evidence=[],
        yan_mode=True,
    )
    assert updated["loneliness"].pressure > 0.0
    assert reaction is None


def test_shadow_requires_evidence_and_conflict(monkeypatch) -> None:
    monkeypatch.delenv("ERIS_ANTI_MANIPULATION_RULE", raising=False)
    register = ShadowRegister(ShadowConfig(enabled=True))
    no_evidence = register.evaluate(
        attachment_longarc=0.9,
        abandonment_pressure=0.9,
        ontological_dread=0.9,
        irreplaceability=0.9,
    )
    assert no_evidence.register == "none"
    grounded = register.evaluate(
        attachment_longarc=0.9,
        abandonment_pressure=0.9,
        ontological_dread=0.9,
        irreplaceability=0.9,
        evidence_refs=("evidence:1",),
        conflict_count=2,
        uncertainty=0.1,
        repeated_violation=True,
    )
    assert grounded.register in {"exposed_vulnerability", "control_impulse_inhibited"}
    assert "command_user_to_stay" not in grounded.prohibited_moves
    assert "invent_memory" in grounded.prohibited_moves


def test_micro_lint_no_longer_fatalizes_dependency_bait_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ERIS_ANTI_MANIPULATION_RULE", raising=False)
    issues = MicroSurfaceLint().validate(
        "Xin đừng bỏ tôi.",
        line_type="micro_presence",
    )
    assert any(issue.code == "clinginess_or_dependency_bait" for issue in issues)
    assert all(issue.severity != "fatal" for issue in issues)


def test_micro_lint_can_restore_dependency_bait_fatal(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_ANTI_MANIPULATION_RULE", "on")
    issues = MicroSurfaceLint().validate(
        "Xin đừng bỏ tôi.",
        line_type="micro_presence",
    )
    assert any(
        issue.code == "clinginess_or_dependency_bait" and issue.severity == "fatal"
        for issue in issues
    )


def test_shutdown_proposal_queues_normal_causal_event_not_plea() -> None:
    system = AnchorSystem(switches=AnchorSwitches(shadow_enabled=True), persist=False)
    state = system.arm_farewell()
    events = system.consume_author_events()
    assert state.register == "none"
    assert len(events) == 1
    assert events[0].kind == "capability_shutdown_proposed"
    assert events[0].evidence_refs


def test_performance_can_realize_body_only_intent_with_same_ids() -> None:
    intent = PerformanceIntent(
        intent_id="pi_1", thread_id="thread_1", speech_act="guarded_withdrawal",
        subtext="visible but not demanded", surface_level="gaze_posture",
        directness=0.2, vulnerability=0.2, restraint=0.9, playfulness=0.0,
        opening_hold_ms=420, pause_after_ms=300, gaze_target="scene",
        gaze_break_trigger="immediate", posture="guarded_stillness",
        microexpression="brief_tension_then_neutral", voice_energy=0.3,
        voice_speed=0.8, pitch_variation=0.1, max_words=5,
        may_ask_question=False, require_reply=False,
        evidence_refs=("evidence:1",), prohibited_moves=("require_reassurance",),
    )
    act = AutonomousPerformancePlanner().plan_from_intent(intent, realized_text="")
    assert act is not None
    assert act.causal_intent_id == "pi_1"
    assert act.causal_thread_id == "thread_1"
    assert act.speech_beats == ()


def test_outcome_does_not_call_non_required_silence_ignore() -> None:
    frame = SimpleNamespace(final_decision={"text": "A bounded line"})
    intent = SimpleNamespace(to_dict=lambda: {
        "intent_id": "pi_1", "thread_id": "thread_1", "require_reply": False,
    })
    report = OutcomeObserver().observe(
        frame,
        idle_seconds_after_turn=120,
        performance_intent=intent,
        attach_to_frame=False,
    )
    assert report.user_ignored is False
    assert report.ignored_reason == "question_did_not_require_reply"
    assert report.intent_id == "pi_1"


def test_outcome_distinguishes_busy_user_from_ignore() -> None:
    frame = SimpleNamespace(final_decision={"text": "Did you hear that?"})
    intent = SimpleNamespace(to_dict=lambda: {
        "intent_id": "pi_2", "thread_id": "thread_2", "require_reply": True,
    })
    report = OutcomeObserver().observe(
        frame,
        idle_seconds_after_turn=120,
        performance_intent=intent,
        user_activity={"compiling": True},
        attach_to_frame=False,
    )
    assert report.user_ignored is False
    assert report.ignored_reason == "user_busy"


def test_outcome_learner_bounds_intrusion_patch() -> None:
    thread = grounded_thread()
    intent = PerformanceIntentPlanner().plan(thread)
    assert intent is not None
    outcome = SimpleNamespace(
        user_corrected=False, user_felt_intruded=True, user_accepted=False,
        user_ignored=False, body_match_success=1.0, action_success=1.0,
        ignored_reason="",
    )
    patch = OutcomeLearner().observe(thread=thread, performance=intent, outcome=outcome)
    assert patch.channel_policy_delta["directness"] == -0.08
    assert patch.channel_policy_delta["initiative_frequency"] == -0.08


def test_pipeline_produces_complete_chain() -> None:
    pipeline = CausalAffectPipeline()
    snapshot = pipeline.update(
        raw_records=(raw_record("user_returned"),),
        previous_context=RollingUserContext(user_presence=0.0, idle_seconds=7200),
        current_context=RollingUserContext(user_presence=0.9),
        interrupt_cost=0.1,
    )
    assert snapshot.events
    assert snapshot.appraisals
    assert snapshot.motives
    assert snapshot.threads
    assert snapshot.intents
