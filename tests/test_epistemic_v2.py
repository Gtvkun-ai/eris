from __future__ import annotations

from types import SimpleNamespace

from cortex.epistemic import (
    ActionCandidate,
    BeliefHorizon,
    EpisodeFeedback,
    EpistemicKernel,
    EpistemicStore,
    EvidenceRef,
    Hypothesis,
    EpistemicUserModelProjection,
)
from runtime.epistemic_bridge import feedback_from_outcome, prepare_authoritative_action, update_relationship_projection


def kernel() -> EpistemicKernel:
    return EpistemicKernel(EpistemicStore(path=":memory:"))


def direct_ref(key: str, *, episode: str = "e1") -> EvidenceRef:
    return EvidenceRef(
        id=f"ev:{key}",
        source="user",
        independence_key=key,
        source_kind="user_direct",
        directness=1.0,
        reliability=0.95,
        episode_id=episode,
    )


def test_low_signal_messages_do_not_create_persistent_user_belief():
    core = kernel()
    for index, text in enumerate(("Chào", "ừ", "ok", "")):
        observation = core.observe(
            kind="user_message",
            content=text,
            source="user",
            directness=1.0,
            reliability=1.0,
            independence_key=f"turn:{index}",
            source_kind="user_direct",
            episode_id=f"episode:{index}",
        )
        hypotheses = core.infer([observation])
        assert hypotheses.hypotheses
        assert all(item.horizon_hint == BeliefHorizon.TURN_STATE for item in hypotheses.hypotheses)
        assert core.commit_hypothesis(hypotheses.selected) is None
    assert core.recall(scope="user") == ()


def test_repeated_modules_share_one_provenance_group():
    core = kernel()
    refs = tuple(
        EvidenceRef(
            id=f"module:{index}",
            source=f"module_{index}",
            independence_key="same-user-turn",
            source_kind="runtime",
            directness=0.5,
            reliability=0.7,
            episode_id="episode:1",
        )
        for index in range(10)
    )
    hypothesis = Hypothesis(
        id="",
        claim="The user may be testing Eris.",
        subject="user",
        facet="interaction_style",
        confidence=0.88,
        uncertainty=0.4,
        overread_risk=0.7,
        evidence_refs=refs,
        origin="private_modules",
        horizon_hint=BeliefHorizon.PERSISTENT_BELIEF,
    )
    assert core.commit_hypothesis(hypothesis) is None


def test_diary_cannot_promote_or_reinforce_belief():
    core = kernel()
    diary = EvidenceRef(
        id="diary:1",
        source="inner_diary",
        independence_key="diary:1",
        source_kind="diary",
        directness=0.0,
        reliability=0.2,
        episode_id="episode:1",
    )
    hypothesis = Hypothesis(
        id="",
        claim="The user is deliberately testing Eris.",
        subject="user",
        facet="interaction_style",
        confidence=0.9,
        uncertainty=0.2,
        evidence_refs=(diary,),
        origin="inner_diary",
        horizon_hint=BeliefHorizon.PERSISTENT_BELIEF,
    )
    assert core.commit_hypothesis(hypothesis) is None
    assert core.store.beliefs == {}


def test_explicit_user_fact_promotes_with_provenance_and_inferred_cap():
    core = kernel()
    observation = core.observe(
        kind="user_message",
        content="Tôi thích câu trả lời kỹ thuật trực tiếp",
        source="user",
        directness=1.0,
        reliability=0.98,
        independence_key="turn:fact",
        source_kind="user_direct",
        episode_id="episode:fact",
    )
    selected = core.infer([observation]).selected
    belief = core.commit_hypothesis(selected)
    assert belief is not None
    assert belief.horizon == BeliefHorizon.PERSISTENT_BELIEF
    assert belief.positive_evidence[0].independence_key == "turn:fact"

    inferred = Hypothesis(
        id="",
        claim="The user prefers silence.",
        subject="user",
        facet="interaction_style",
        confidence=1.0,
        uncertainty=0.1,
        evidence_refs=(direct_ref("a", episode="a"), direct_ref("b", episode="b"), direct_ref("c", episode="c")),
        origin="model",
        horizon_hint=BeliefHorizon.PERSISTENT_BELIEF,
    )
    inferred_belief = core.commit_hypothesis(inferred)
    assert inferred_belief is not None
    assert inferred_belief.confidence == 0.9


def test_correction_closes_episode_and_weakens_exact_belief():
    core = kernel()
    hypothesis = Hypothesis(
        id="",
        claim="User explicitly stated: Tôi thích câu ngắn",
        subject="user",
        facet="explicit_fact",
        confidence=0.9,
        uncertainty=0.1,
        evidence_refs=(direct_ref("fact"),),
        origin="explicit_user_statement",
        horizon_hint=BeliefHorizon.PERSISTENT_BELIEF,
        direct_assertion=True,
    )
    belief = core.commit_hypothesis(hypothesis)
    episode = core.start_episode(
        channel="chat",
        observations=(),
        hypothesis_set=SimpleNamespace(selected=hypothesis, selected_id=hypothesis.id, hypotheses=(hypothesis,), uncertainty=0.1, to_dict=lambda: {}),
        action=ActionCandidate(id="actual", action_type="answer"),
    )
    updates = core.close_episode(EpisodeFeedback(kind="correction", corrected=True, text="không phải", evidence=("user_feedback",), confidence=1.0), episode_id=episode.id)
    assert len(updates) == 1
    assert updates[0].target_id == belief.id
    assert core.store.beliefs[belief.id].confidence < belief.confidence + 0.001
    assert core.store.beliefs[belief.id].contradictory_evidence


def test_tone_feedback_updates_policy_not_user_identity():
    core = kernel()
    hypothesis = Hypothesis(id="", claim="Current tone may be too cold.", confidence=0.6)
    episode = core.start_episode(
        channel="chat",
        observations=(),
        hypothesis_set=SimpleNamespace(selected=hypothesis, selected_id=hypothesis.id, hypotheses=(hypothesis,), uncertainty=0.4, to_dict=lambda: {}),
        action=ActionCandidate(id="actual", action_type="answer"),
    )
    outcome = SimpleNamespace(
        user_accepted=None,
        user_corrected=False,
        user_confused=False,
        user_felt_intruded=False,
        relation_improved=False,
        relation_ruptured=True,
        feedback_text="lạnh lùng quá",
        evidence=["tone"],
        tags=["relation_ruptured"],
        confidence=0.9,
    )
    updates = core.close_episode(feedback_from_outcome(outcome), episode_id=episode.id)
    assert updates[0].target_kind == "procedural_policy"
    assert core.recall(scope="user") == ()
    answer = ActionCandidate(id="answer", action_type="answer", task_fit=0.8, expected_helpfulness=0.8)
    neutral = ActionCandidate(id="neutral", action_type="neutral_reply", task_fit=0.7, expected_helpfulness=0.7)
    selected = core.select_action((answer, neutral), hypothesis_set=SimpleNamespace(uncertainty=0.2))
    assert selected.id == "neutral"


def test_high_uncertainty_high_risk_prefers_clarification():
    core = kernel()
    risky = ActionCandidate(
        id="risky",
        action_type="interpret",
        task_fit=1.0,
        relational_fit=0.8,
        expected_helpfulness=0.8,
        epistemic_value=0.1,
        intrusion_risk=0.55,
        high_consequence=True,
    )
    clarify = ActionCandidate(
        id="clarify",
        action_type="clarify",
        task_fit=0.5,
        relational_fit=0.6,
        expected_helpfulness=0.5,
        epistemic_value=0.9,
        intrusion_risk=0.05,
    )
    hypotheses = SimpleNamespace(uncertainty=0.8)
    assert core.select_action((risky, clarify), hypothesis_set=hypotheses).id == "clarify"


def test_contradiction_never_increases_confidence():
    core = kernel()
    hypothesis = Hypothesis(
        id="",
        claim="User explicitly stated: Tôi thích câu ngắn",
        subject="user",
        facet="explicit_fact",
        confidence=0.88,
        uncertainty=0.12,
        evidence_refs=(direct_ref("fact"),),
        origin="explicit_user_statement",
        horizon_hint=BeliefHorizon.PERSISTENT_BELIEF,
        direct_assertion=True,
    )
    belief = core.commit_hypothesis(hypothesis)
    before = belief.confidence
    episode = core.start_episode(
        channel="chat",
        observations=(),
        hypothesis_set=SimpleNamespace(selected=hypothesis, selected_id=hypothesis.id, hypotheses=(hypothesis,), uncertainty=0.1, to_dict=lambda: {}),
        action=None,
    )
    core.close_episode(EpisodeFeedback(corrected=True, confidence=0.8, evidence=("correction",)), episode_id=episode.id)
    assert core.store.beliefs[belief.id].confidence <= before
    assert core.store.beliefs[belief.id].uncertainty >= belief.uncertainty


def test_authoritative_action_overrides_risky_chat_read_with_clarification():
    core = kernel()
    plan = SimpleNamespace(
        speech_act="interpret",
        speech_intent="answer",
        should_speak=True,
        risk_flags=("overread_risk",),
        selected_utility=0.8,
        notes=(),
        reason="",
        reason_to_speak="",
    )
    frame = SimpleNamespace(
        cycle_id="frame:1",
        channel="chat",
        started_at=1.0,
        percepts=(SimpleNamespace(kind="user_message", content="hi", source="user", confidence=1.0, timestamp=1.0, privacy_level="private"),),
        meaning_layer=SimpleNamespace(meaning="The user may be testing Eris.", semantic_family="relational", confidence=0.7),
        appraisal=SimpleNamespace(stance="ungrounded_interpretation"),
        action_plan=plan,
        final_decision={},
        epistemic_episode=None,
        debug_notes=[],
    )
    selected = prepare_authoritative_action(core, frame)
    assert selected.action_type == "clarify"
    assert frame.action_plan.speech_act == "clarifying_question"
    assert frame.action_plan.speech_intent == "user_requested"


def test_non_chat_action_is_not_replaced_by_clarification():
    core = kernel()
    plan = SimpleNamespace(
        speech_act="telemetry_comment",
        speech_intent="micro_presence",
        should_speak=True,
        risk_flags=("overread_risk",),
        selected_utility=0.5,
        notes=(),
        reason="",
        reason_to_speak="",
    )
    frame = SimpleNamespace(
        cycle_id="frame:2",
        channel="force_speak",
        started_at=1.0,
        percepts=(),
        meaning_layer=SimpleNamespace(meaning="A possible screen pattern.", semantic_family="scene", confidence=0.4),
        appraisal=SimpleNamespace(stance="ungrounded_interpretation"),
        action_plan=plan,
        final_decision={},
        epistemic_episode=None,
        debug_notes=[],
    )
    prepare_authoritative_action(core, frame)
    assert frame.action_plan.speech_act == "telemetry_comment"
    assert frame.action_plan.speech_intent == "micro_presence"


def test_relationship_projection_uses_v2_as_previous_state():
    from cortex.relationship_dynamics import RelationshipDynamicsEngine, RelationshipDynamicsState, RelationshipTurnEvent

    core = kernel()
    core.set_projection("relationship", {"state": RelationshipDynamicsState(trust=0.72).to_dict()})
    report = update_relationship_projection(
        core,
        RelationshipDynamicsEngine(),
        RelationshipTurnEvent(turn_index=2),
        fallback_state=RelationshipDynamicsState(trust=0.05),
    )
    assert report.state.trust > 0.5
    assert core.get_projection("relationship")["state"]["trust"] == report.state.trust


def test_user_model_projection_reads_and_resets_v2_beliefs():
    core = kernel()
    hypothesis = Hypothesis(
        id="",
        claim="User explicitly stated: I prefer direct technical answers",
        subject="user",
        facet="interaction_style",
        confidence=0.92,
        uncertainty=0.08,
        evidence_refs=(direct_ref("preference"),),
        origin="explicit_user_statement",
        horizon_hint=BeliefHorizon.PERSISTENT_BELIEF,
        direct_assertion=True,
    )
    core.commit_hypothesis(hypothesis)
    projection = EpistemicUserModelProjection(core)
    assert projection.by_facet("interaction_style")[0].claim == hypothesis.claim
    assert projection.model_thickness() > 0.0
    projection.reset_to_baseline()
    assert projection.all() == ()


def test_store_roundtrips_authoritative_projections(tmp_path):
    path = tmp_path / "epistemic.json"
    first = EpistemicStore(path=path, mode="authoritative")
    first.projections["self_current"] = {"stance": "steady"}
    first.save()
    second = EpistemicStore(path=path)
    assert second.mode == "authoritative"
    assert second.projections["self_current"]["stance"] == "steady"
