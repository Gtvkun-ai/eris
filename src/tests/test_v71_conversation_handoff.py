# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from cortex.subject.neuro_control import ChoiceSemanticAppraisal, NeuroSemanticAppraisal
from cortex.subject.service import SubjectService, SubjectServiceConfig
from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex
from runtime.ai_orchestrated.orchestrator import AIAutonomousOrchestrator
from runtime.conversation_handoff import ConversationHandoffRuntime
from runtime.subject_ingress import SubjectIngress


def _abstract_eris_line() -> str:
    return (
        "Đôi khi nhìn thấy hai lớp đó lại hóa thành một lớp thứ ba, cách tôi tự soi chiếu "
        "cái cách tôi đang đọc, và liệu tôi có thể ngừng nhìn chằm chằm vào lăng kính "
        "của chính mình để thực sự thấy bạn không?"
    )


def test_self_deprecation_after_abstract_eris_line_creates_causal_repair() -> None:
    runtime = ConversationHandoffRuntime()
    previous = _abstract_eris_line()
    runtime.observe_assistant_commit(previous, turn_ref="assistant:20", turn_index=20)

    state = runtime.observe_user_turn(
        "chết dở rồi eris ơi . tôi bị ngu",
        turn_ref="user:21",
        turn_index=21,
        previous_assistant_text=previous,
        previous_assistant_turn_ref="assistant:20",
        previous_assistant_turn_index=20,
    )

    assert state.repair_needed is True
    assert state.next_move_owner == "eris"
    assert state.self_caused_reaction_probability >= 0.75
    assert state.unresolved_intent == "repair_or_clarify_previous_eris_move"
    assert state.causal_hypotheses[0].kind == "reaction_to_previous_eris_move"

    proposal = runtime.repair_action_proposal()
    assert proposal is not None
    assert proposal["arguments"]["speech_act"] == "causal_repair"
    assert proposal["arguments"]["candidate_kind"] == "conversation_repair"
    assert proposal["arguments"]["source_owner"] == "conversation_handoff"


def test_explicit_confusion_links_to_previous_eris_move_with_high_confidence() -> None:
    runtime = ConversationHandoffRuntime()
    previous = _abstract_eris_line()
    state = runtime.observe_user_turn(
        "là do tôi không hiểu em nói gì hết",
        turn_ref="user:23",
        previous_assistant_text=previous,
        previous_assistant_turn_ref="assistant:22",
    )
    assert state.user_stance == "confused"
    assert state.repair_needed is True
    assert state.self_caused_reaction_probability >= 0.90


def test_explicit_external_cause_prevents_eriss_self_blame() -> None:
    runtime = ConversationHandoffRuntime()
    state = runtime.observe_user_turn(
        "tôi bị ngu vì tôi làm sai bài toán",
        turn_ref="user:external",
        previous_assistant_text="Bạn ổn chứ?",
        previous_assistant_turn_ref="assistant:previous",
    )
    assert state.self_caused_reaction_probability < 0.35
    assert state.repair_needed is False
    assert any(item.kind == "external_or_unstated_cause" for item in state.causal_hypotheses)


def test_shared_goal_survives_empty_autonomous_user_text_as_handoff_debt() -> None:
    runtime = ConversationHandoffRuntime()
    state = runtime.refresh_shared_goal(
        "mục tiêu đang dang dở: User's request for a novel topic awaits ERIS's response.",
        evidence_refs=("shared-goal:novel-topic",),
    )
    assert state.next_move_owner == "eris"
    assert state.continuity_pressure >= 0.86
    assert "novel topic" in state.pending_shared_goal


def test_repair_completion_restores_preexisting_shared_goal_to_eris() -> None:
    runtime = ConversationHandoffRuntime()
    runtime.refresh_shared_goal(
        "mục tiêu đang dang dở: User's request for a novel topic awaits ERIS's response."
    )
    previous = _abstract_eris_line()
    runtime.observe_user_turn(
        "là do tôi không hiểu em nói gì hết",
        turn_ref="user:23",
        previous_assistant_text=previous,
        previous_assistant_turn_ref="assistant:22",
    )
    repaired = runtime.observe_assistant_commit(
        "Ừ, câu vừa rồi của em rối quá. Ý đơn giản là em đang tự phân tích quá mức.",
        turn_ref="assistant:24",
        speech_act="causal_repair",
    )
    assert repaired.repair_needed is False
    assert repaired.pending_shared_goal
    assert repaired.unresolved_intent == repaired.pending_shared_goal
    assert repaired.next_move_owner == "eris"
    assert repaired.continuity_pressure >= 0.82


def test_subject_ingress_materializes_causal_repair_as_typed_speech_candidate() -> None:
    runtime = ConversationHandoffRuntime()
    previous = _abstract_eris_line()
    state = runtime.observe_user_turn(
        "chết dở rồi eris ơi . tôi bị ngu",
        turn_ref="user:21",
        turn_index=21,
        previous_assistant_text=previous,
        previous_assistant_turn_ref="assistant:20",
        previous_assistant_turn_index=20,
    )
    service = SubjectService(config=SubjectServiceConfig(subject_id="eris", deterministic=True))
    session = SubjectIngress(service).prepare_user_session(
        "chết dở rồi eris ơi . tôi bị ngu",
        created_at=1000.0,
        turn_id="user:21",
        planning_context={
            "conversation_handoff": state.to_dict(),
            "causal_discourse": state.to_dict(),
            "conversation_repair_proposal": runtime.repair_action_proposal(),
        },
    )
    assert session.frame.coalitions
    winner = max(session.frame.coalitions, key=lambda item: item.score)
    assert winner.action_kind == "speak"
    assert winner.arguments["speech_act"] == "causal_repair"
    assert winner.arguments["source_owner"] == "conversation_handoff"


def test_executive_handoff_boosts_pending_goal_and_penalizes_unrelated_rumination() -> None:
    service = SubjectService(config=SubjectServiceConfig(subject_id="eris", deterministic=True))
    handoff = ConversationHandoffRuntime().refresh_shared_goal(
        "mục tiêu đang dang dở: User's request for a novel topic awaits ERIS's response."
    )
    session = SubjectIngress(service).prepare_user_session(
        "x",
        created_at=1000.0,
        turn_id="seed",
        planning_context={"conversation_handoff": handoff.to_dict()},
    )
    base = session.frame.coalitions[0]
    unrelated = replace(
        base,
        coalition_id="coalition:unrelated",
        primary_proposal_ref="proposal:unrelated",
        proposal_refs=("proposal:unrelated",),
        action_kind="speak",
        arguments={
            **dict(base.arguments),
            "speech_act": "share_self_originated_thought",
            "candidate_kind": "random_chat",
            "source_owner": "expression_urge",
            "semantic_target": "quay lại một suy nghĩ nội tâm không liên quan",
        },
    )
    aligned = replace(
        base,
        coalition_id="coalition:goal",
        primary_proposal_ref="proposal:goal",
        proposal_refs=("proposal:goal",),
        action_kind="speak",
        arguments={
            **dict(base.arguments),
            "speech_act": "resume_shared_goal",
            "candidate_kind": "random_chat",
            "source_owner": "expression_urge",
            "semantic_target": handoff.pending_shared_goal,
        },
    )
    frame = replace(session.frame, coalitions=(unrelated, aligned))
    raw = NeuroSemanticAppraisal(
        choices=(
            ChoiceSemanticAppraisal(0, motive_validity=0.80, novelty=0.80, continuity_fit=0.72, epistemic_support=0.5, reversibility=0.8),
            ChoiceSemanticAppraisal(1, motive_validity=0.45, novelty=0.50, continuity_fit=0.45, epistemic_support=0.5, reversibility=0.8),
        ),
        confidence=0.8,
        reason="remote forgot the handoff",
    )
    fixed = ExecutiveCortex._apply_conversation_handoff_appraisal(frame, raw)
    by_index = {item.index: item for item in fixed.choices}
    assert by_index[1].motive_validity > by_index[0].motive_validity
    assert by_index[1].continuity_fit > by_index[0].continuity_fit
    assert "preserve_authoritative_conversation_handoff" in fixed.semantic_commitments


def test_executive_handoff_prioritizes_causal_repair_over_unrelated_speech() -> None:
    runtime = ConversationHandoffRuntime()
    previous = _abstract_eris_line()
    state = runtime.observe_user_turn(
        "chết dở rồi eris ơi . tôi bị ngu",
        turn_ref="u21",
        previous_assistant_text=previous,
        previous_assistant_turn_ref="a20",
    )
    service = SubjectService(config=SubjectServiceConfig(subject_id="eris", deterministic=True))
    session = SubjectIngress(service).prepare_user_session(
        state.last_user_text,
        created_at=1000.0,
        turn_id="u21",
        planning_context={
            "conversation_handoff": state.to_dict(),
            "causal_discourse": state.to_dict(),
            "conversation_repair_proposal": runtime.repair_action_proposal(),
        },
    )
    repair = session.frame.coalitions[0]
    unrelated = replace(
        repair,
        coalition_id="coalition:rumination",
        primary_proposal_ref="proposal:rumination",
        proposal_refs=("proposal:rumination",),
        arguments={
            **dict(repair.arguments),
            "speech_act": "share_self_originated_thought",
            "candidate_kind": "random_chat",
            "source_owner": "expression_urge",
        },
    )
    frame = replace(session.frame, coalitions=(unrelated, repair))
    raw = NeuroSemanticAppraisal(
        choices=(
            ChoiceSemanticAppraisal(0, motive_validity=0.92, novelty=0.80, continuity_fit=0.70, epistemic_support=0.5, reversibility=0.8),
            ChoiceSemanticAppraisal(1, motive_validity=0.40, novelty=0.40, continuity_fit=0.40, epistemic_support=0.5, reversibility=0.8),
        ),
        confidence=0.8,
        reason="critic underweighted causal repair",
    )
    fixed = ExecutiveCortex._apply_conversation_handoff_appraisal(frame, raw)
    by_index = {item.index: item for item in fixed.choices}
    assert by_index[1].motive_validity >= 0.95
    assert by_index[1].continuity_fit >= 0.95
    assert by_index[0].motive_validity < 0.40


def test_startup_only_primes_continuity_and_never_commits_fake_public_turn() -> None:
    logs: list[str] = []
    state = SimpleNamespace(
        open_loops=("mục tiêu đang dang dở: đổi sang một chủ đề mới",),
        latest_observation={},
    )
    host = SimpleNamespace(
        _ai_startup_ran=False,
        ai_state_reducer=SimpleNamespace(snapshot=lambda: state),
        _chat_history_for_llm=lambda limit=8: [
            {"role": "user", "content": "đổi chủ đề mới mẻ hơn đi"},
            {"role": "assistant", "content": "tôi sẽ rẽ sang hướng khác"},
        ],
        logger=SimpleNamespace(
            info=lambda fmt, *args: logs.append(fmt % args if args else fmt),
            warning=lambda *args, **kwargs: None,
            debug=lambda *args, **kwargs: None,
        ),
    )
    runtime = AIAutonomousOrchestrator(host)
    runtime._commit_public = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("startup must never create a public commit")
    )

    assert runtime.run_startup() is False
    assert getattr(host, "_startup_greeting_spoken_at", 0.0) == 0.0
    assert getattr(host, "last_autonomous_spoken_at", 0.0) == 0.0
    handoff = host.conversation_handoff_runtime.snapshot()
    assert handoff.pending_shared_goal
    assert handoff.next_move_owner == "eris"
    assert any("opening_signal=kernel" in line for line in logs)
    assert host.last_conversation_run["status"] == "no_reply"
    assert all(" spoke " not in f" {line} " for line in logs)
