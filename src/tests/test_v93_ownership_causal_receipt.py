# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from runtime.ai_orchestrated.contracts import CognitiveObservation, RuntimeMindState, StateEvent
from runtime.ai_orchestrated.state_reducer import StateReducer
from runtime.conversation_handoff import ConversationHandoffRuntime
from runtime.public_causal_receipt import (
    PublicCausalReceipt,
    build_public_causal_receipt,
    normalize_semantic_owner,
)


def test_owner_normalization_fails_closed_instead_of_guessing_user() -> None:
    assert normalize_semantic_owner("ERIS") == "eris"
    assert normalize_semantic_owner("shared") == "shared"
    assert normalize_semantic_owner("mystery-person") == "unknown"


def test_autonomous_observer_open_loop_is_owned_by_eris_and_not_promoted_to_shared_goal() -> None:
    observation = CognitiveObservation.from_mapping(
        {
            "event_kind": "autonomous",
            "user_act": "none",
            "relationship_meaning": "neutral",
            "confidence": 0.92,
            "open_loop": "ERIS tự hỏi vì sao mình cứ đẩy ranh giới ra xa.",
        },
        turn_id="auto:1",
        turn_seq=1,
        source="observer",
    )
    assert observation.open_loop_owner == "eris"

    reducer = StateReducer()
    reducer.apply_now(StateEvent.from_observation(observation, base_version=reducer.snapshot().version))
    state = reducer.snapshot()
    assert "ERIS tự hỏi" not in " ".join(state.open_loops)


def test_chat_observer_open_loop_remains_shared_continuity() -> None:
    observation = CognitiveObservation.from_mapping(
        {
            "event_kind": "chat",
            "user_act": "request",
            "relationship_meaning": "neutral",
            "confidence": 0.92,
            "open_loop": "User đang chờ ERIS trả lời phần kiểm tra repo.",
        },
        turn_id="chat:2",
        turn_seq=2,
        source="observer",
    )
    assert observation.open_loop_owner == "shared"

    reducer = StateReducer()
    reducer.apply_now(StateEvent.from_observation(observation, base_version=reducer.snapshot().version))
    assert reducer.snapshot().open_loops == ("User đang chờ ERIS trả lời phần kiểm tra repo.",)


def test_refresh_shared_goal_rejects_eris_owned_material() -> None:
    runtime = ConversationHandoffRuntime()
    state = runtime.refresh_shared_goal(
        "ERIS tự nhận cơ chế đẩy ranh giới.",
        semantic_owner="eris",
        evidence_refs=("observer:auto:9",),
    )
    assert state.pending_shared_goal == ""
    assert state.pending_shared_goal_owner == "unknown"
    assert state.next_move_owner == "none"


def test_public_causal_receipt_keeps_self_generated_autonomous_origin() -> None:
    receipt = build_public_causal_receipt(
        channel="autonomous",
        speech_act="share_self_originated_thought",
        semantic_owner="eris",
        trigger_owner="eris",
        source_kind="expression_urge",
        source_ref="urge:boundary",
        motive="revisit",
        why_now="active concern resurfaced with enough pressure",
        user_triggered=False,
        confidence=0.78,
        evidence_refs=("concern:boundary",),
    )
    payload = receipt.to_dict()
    assert payload["semantic_owner"] == "eris"
    assert payload["trigger_owner"] == "eris"
    assert payload["user_triggered"] is False
    assert payload["source_kind"] == "expression_urge"


def test_handoff_keeps_last_public_causal_receipt_for_self_explanation() -> None:
    runtime = ConversationHandoffRuntime()
    receipt = PublicCausalReceipt(
        channel="autonomous",
        semantic_owner="eris",
        trigger_owner="eris",
        source_kind="expression_urge",
        source_ref="urge:boundary",
        motive="revisit",
        why_now="một concern cũ vừa trồi lại",
        user_triggered=False,
        confidence=0.82,
        speech_act="share_self_originated_thought",
        evidence_refs=("concern:boundary",),
        created_at=100.0,
    )
    state = runtime.observe_assistant_commit(
        "Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        turn_ref="assistant:9",
        turn_index=9,
        speech_act="share_self_originated_thought",
        causal_receipt=receipt,
        now=100.0,
    )
    assert state.last_public_semantic_owner == "eris"
    assert state.last_public_causal_receipt["motive"] == "revisit"

    prompt = runtime.prompt_context()
    assert "PUBLIC_CAUSAL_RECEIPT_V93" in prompt
    assert '"semantic_owner":"eris"' in prompt
    assert "không được đảo chủ thể" in prompt.lower()


def test_user_why_question_marks_self_explanation_request_without_reassigning_owner() -> None:
    runtime = ConversationHandoffRuntime()
    receipt = build_public_causal_receipt(
        channel="autonomous",
        speech_act="share_self_originated_thought",
        semantic_owner="eris",
        trigger_owner="eris",
        source_kind="expression_urge",
        source_ref="urge:boundary",
        motive="revisit",
        why_now="active concern resurfaced",
        user_triggered=False,
        confidence=0.8,
    )
    runtime.observe_assistant_commit(
        "Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        turn_ref="assistant:9",
        causal_receipt=receipt,
    )
    state = runtime.observe_user_turn(
        "ý là sao em lại nghĩ về đặt ranh giới, em đang muốn nói gì vậy?",
        turn_ref="user:10",
        previous_assistant_text="Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        previous_assistant_turn_ref="assistant:9",
    )
    assert state.self_explanation_requested is True
    assert state.unresolved_intent == "explain_previous_eris_public_motive_from_receipt"
    assert state.last_public_semantic_owner == "eris"


def test_chat_intention_plan_defaults_to_shared_semantics_triggered_by_user() -> None:
    from runtime.ai_orchestrated.contracts import IntentionPlan

    plan = IntentionPlan.from_mapping(
        {
            "speak": True,
            "motive": "respond_to_user",
            "semantics": {"speech_act": "answer", "subject_key": "current_user_turn"},
        },
        channel="chat",
    )
    assert plan.semantic_owner == "shared"
    assert plan.trigger_owner == "user"
    assert plan.user_triggered is True


def test_expression_urge_candidate_plan_carries_eris_ownership() -> None:
    from runtime.ai_orchestrated.initiative import InitiativeController
    from runtime.ai_orchestrated.social_candidate import SocialSpeechCandidate

    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="random_chat",
        topic="Tôi lại nghĩ tới một chuyện cũ.",
        speech_act="share_self_originated_thought",
        anchor_type="internal",
        anchor_id="concern:self:1",
        evidence_refs=("concern:self:1",),
        confidence=0.8,
        relevance=0.7,
        urgency=0.5,
        source="expression_urge",
        eris_motive_kind="want_to_revisit",
        eris_motive_why_now="một concern cũ vừa trồi lại",
    )
    plan, *_ = InitiativeController._plan_for_candidate(candidate, SimpleNamespace(now=100.0))
    assert plan.semantic_owner == "eris"
    assert plan.trigger_owner == "eris"
    assert plan.source_kind == "expression_urge"
    assert plan.source_ref == "concern:self:1"


def test_self_explanation_request_materializes_receipt_grounded_proposal() -> None:
    runtime = ConversationHandoffRuntime()
    receipt = build_public_causal_receipt(
        channel="autonomous",
        speech_act="share_self_originated_thought",
        semantic_owner="eris",
        trigger_owner="eris",
        source_kind="expression_urge",
        source_ref="urge:self:1",
        motive="revisit",
        why_now="một concern cũ vừa trồi lại",
        confidence=0.83,
    )
    runtime.observe_assistant_commit(
        "Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        turn_ref="assistant:9",
        causal_receipt=receipt,
    )
    runtime.observe_user_turn(
        "sao em lại nói cái đó vậy?",
        turn_ref="user:10",
        previous_assistant_text="Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        previous_assistant_turn_ref="assistant:9",
    )
    proposal = runtime.repair_action_proposal()
    assert proposal is not None
    assert proposal["arguments"]["speech_act"] == "self_explanation"
    assert '"semantic_owner":"eris"' in proposal["arguments"]["semantic_content"]


def test_subject_core_receives_typed_self_explanation_from_receipt() -> None:
    from cortex.subject.service import SubjectService, SubjectServiceConfig
    from runtime.subject_ingress import SubjectIngress

    runtime = ConversationHandoffRuntime()
    receipt = build_public_causal_receipt(
        channel="autonomous",
        speech_act="share_self_originated_thought",
        semantic_owner="eris",
        trigger_owner="eris",
        source_kind="expression_urge",
        source_ref="urge:self:1",
        motive="revisit",
        why_now="một concern cũ vừa trồi lại",
        confidence=0.83,
    )
    runtime.observe_assistant_commit(
        "Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        turn_ref="assistant:9",
        causal_receipt=receipt,
    )
    state = runtime.observe_user_turn(
        "sao em lại nói cái đó vậy?",
        turn_ref="user:10",
        previous_assistant_text="Tôi lại nhớ ra chuyện mình cứ đẩy ranh giới ra xa.",
        previous_assistant_turn_ref="assistant:9",
    )
    service = SubjectService(config=SubjectServiceConfig(subject_id="eris", deterministic=True))
    session = SubjectIngress(service).prepare_user_session(
        state.last_user_text,
        created_at=1000.0,
        turn_id="user:10",
        planning_context={
            "conversation_handoff": state.to_dict(),
            "causal_discourse": state.to_dict(),
            "conversation_repair_proposal": runtime.repair_action_proposal(),
        },
    )
    assert session.frame.coalitions
    winner = max(session.frame.coalitions, key=lambda item: item.score)
    assert winner.action_kind == "speak"
    assert winner.arguments["speech_act"] == "self_explanation"
    assert winner.arguments["source_owner"] == "conversation_handoff"


def test_autonomous_open_loop_never_becomes_subject_shared_goal_context() -> None:
    from runtime.subject_initiative_runtime import build_initiative_runtime_context

    observation = CognitiveObservation.from_mapping(
        {
            "event_kind": "autonomous",
            "user_act": "none",
            "confidence": 0.95,
            "open_loop": "ERIS tự nhận cơ chế đẩy ranh giới.",
        },
        turn_id="auto:9",
        turn_seq=9,
        source="observer",
    )
    reducer = StateReducer()
    try:
        reducer.apply_now(StateEvent.from_observation(observation, base_version=reducer.snapshot().version))
        context = __import__("runtime.subject_initiative_runtime", fromlist=["build_initiative_runtime_context"]).build_initiative_runtime_context(
            SimpleNamespace(ai_state_reducer=reducer)
        )
        assert context["active_goal_text"] == ""
        assert context["active_goal_owner"] == "unknown"
    finally:
        reducer.close()
