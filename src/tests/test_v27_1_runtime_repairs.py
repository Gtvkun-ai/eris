# -*- coding: utf-8 -*-
"""Scenario regression từ log runtime 2026-08-08.

Không test từng helper rời rạc rồi tuyên bố chiến thắng. Các case dưới đây tái
hiện đúng ba failure đã thấy ngoài đời: startup surface bị legacy invariant chen
vào, Subject initiative đứng ngoài frame có seed, và intention đã nói bị phát lại.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from cortex.subject.initiative import IntentionStatus, MotiveKind
from cortex.subject.relational import RelationalState
from cortex.subject.service import SubjectService, SubjectServiceConfig
from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex
from runtime.subject_ingress import SubjectIngress
from runtime.subject_initiative_runtime import build_subject_initiative_affordances


class Determinism:
    def __init__(self) -> None:
        self.i = 0
        self.now = 10_000.0

    def id(self) -> str:
        self.i += 1
        return f"v27r-{self.i}"

    def clock(self) -> float:
        return self.now


def _service(d: Determinism) -> SubjectService:
    service = SubjectService(
        config=SubjectServiceConfig(restore_projection=False),
        clock=d.clock,
        id_factory=d.id,
    )
    service.relational_state = RelationalState(
        revision=4,
        updated_at=d.now,
        last_meaningful_exchange_at=d.now - 2400.0,
        affiliation_deficit=0.84,
        interaction_satiety=0.06,
        social_curiosity=0.72,
        partner_availability=0.92,
        interruption_cost=0.05,
        outreach_confidence=0.76,
        reciprocity_expectation=0.70,
        evidence_refs=("relational:runtime-repair",),
    )
    return service


def _blackboard():
    return SimpleNamespace(
        reply_expected=False,
        engagement_active=False,
        user_busy=False,
        public_view=lambda: {
            "reply_expected": False,
            "engagement_active": False,
            "novelty": 0.18,
        },
    )


def _seed_affordance():
    candidate = SimpleNamespace(
        kind="random_chat",
        topic="một seed cũ từ reservoir",
        speech_act="random_chat",
        tone="casual",
        source="random_chat_seed_reservoir",
        confidence=0.72,
        relevance=0.70,
        urgency=0.30,
        evidence_refs=("seed:old",),
        requires_grounding=False,
        intrusion_risk=0.12,
    )
    return SimpleNamespace(
        affordance_id="random-chat-seed:old",
        owner="random_chat_seed_reservoir",
        candidate=candidate,
        metadata={},
    )


def _force_ambiguous_non_social_frame(frame):
    coalitions = list(frame.coalitions)
    if len(coalitions) < 2:
        return frame
    coalitions[0] = replace(
        coalitions[0],
        score=0.60,
        uncertainty=0.72,
        action_kind="speak",
        arguments={**dict(coalitions[0].arguments), "speech_act": "random_chat"},
    )
    coalitions[1] = replace(
        coalitions[1],
        score=0.60,
        uncertainty=0.72,
        action_kind="speak",
        arguments={**dict(coalitions[1].arguments), "speech_act": "self_clarification"},
    )
    appraisals = tuple(
        replace(item, future_consequence=0.92, identity_significance=max(item.identity_significance, 0.82))
        for item in frame.appraisals
    )
    return replace(frame, coalitions=tuple(coalitions), appraisals=appraisals)


def test_current_subject_initiative_is_merged_into_same_frame_even_when_seed_exists() -> None:
    """Tái hiện lỗi log: có seed không được làm current intention đứng ngoài frame."""
    d = Determinism()
    service = _service(d)
    ingress = SubjectIngress(service)

    session = ingress.prepare_autonomous_session(
        _blackboard(),
        (_seed_affordance(),),
        created_at=d.now,
        turn_id="runtime-frame-merge",
        planning_context={
            "relational_state": service.relational_view(),
            "initiative_runtime_context": {
                "user_model_uncertainty": 0.96,
                "user_model_evidence_refs": ("user-model:thin",),
            },
        },
    )
    acts = {str(item.arguments.get("speech_act") or "") for item in session.frame.proposals}
    assert "random_chat" in acts
    assert "user_probe" in acts
    probe = next(item for item in session.frame.proposals if item.arguments.get("speech_act") == "user_probe")
    assert probe.arguments.get("intention_id")
    asyncio.run(service.abandon_deliberation(session.frame, reason="test_cleanup"))


def test_legacy_runtime_ids_from_model_cannot_steer_current_frame() -> None:
    """Payload kiểu V27 có ID runtime phải bị coi là invalid, không rebound."""
    d = Determinism()
    service = _service(d)
    ingress = SubjectIngress(service)
    session = ingress.prepare_autonomous_session(
        _blackboard(),
        (_seed_affordance(),),
        created_at=d.now,
        turn_id="runtime-stale-proposal",
        planning_context={
            "relational_state": service.relational_view(),
            "initiative_runtime_context": {"user_model_uncertainty": 0.96},
        },
    )
    calls = 0

    def fake_structured(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        # Cố tình giả lập output legacy: V30 không đọc hai ID này nữa.
        return {
            "selected_coalition_id": "coalition:stale-from-old-frame",
            "selected_proposal_ref": "proposal:stale-from-old-frame",
            "semantic_commitments": [],
            "cognitive_requests": [],
            "reason": "legacy shaped output",
            "confidence": 0.82,
            "review_conditions": [],
        }

    frame = _force_ambiguous_non_social_frame(session.frame)
    executive = ExecutiveCortex(
        SimpleNamespace(action_executor=None),
        object(),
        invoke_structured=fake_structured,
        clock=d.clock,
    )
    commit = executive.commit_subject_frame(frame, mode="autonomous")
    assert commit is not None
    assert calls == 1
    assert commit.source == "neuro_fast_gate_degraded"
    assert commit.reason == "neuro_deliberator_out_of_frame_use_fast_gate"
    fast = executive._neuro_selector.select(frame)
    assert commit.selected_coalition_id == fast.winner(frame).coalition_id
    assert commit.selected_coalition_id != "coalition:stale-from-old-frame"
    asyncio.run(service.abandon_deliberation(session.frame, reason="test_cleanup"))


def test_spoken_probe_enters_awaiting_outcome_and_cannot_repeat_on_next_ticks() -> None:
    """Một intention đã public không được phát lại trước khi có outcome/cooldown."""
    d = Determinism()
    service = _service(d)

    # Tick đầu tạo user_probe nội sinh, không seed.
    from cortex.subject.contracts import ObservationOrigin, WorldObservation
    obs = WorldObservation(
        observation_id="initiative:first",
        subject_id="eris",
        kind="subject_initiative_tick",
        created_at=d.now,
        origin=ObservationOrigin.INTERNAL,
        context={
            "context_key": "self_initiated",
            "affected_need_ids": ("connection", "coherence"),
            "goal_relevance": 0.72,
            "novelty": 0.08,
            "controllability": 0.90,
            "relational_significance": 0.84,
            "future_consequence": 0.35,
            "uncertainty": 0.88,
            "runtime_context": {
                "partner_available": 0.92,
                "interruption_cost": 0.05,
                "social_curiosity": 0.72,
                "user_model_uncertainty": 0.96,
                "user_model_evidence_refs": ("user-model:thin",),
            },
        },
        evidence_refs=("user-model:thin",),
    )
    frame = asyncio.run(service.prepare_deliberation(obs))
    intention = next(
        item for item in service.initiative_state.pending_intentions
        if item.motive_kind is MotiveKind.UNDERSTAND_USER and item.status is IntentionStatus.PENDING
    )
    asyncio.run(service.abandon_deliberation(frame, reason="prime"))

    service.note_initiative_public_act(
        intention.intention_id,
        now=d.now + 1.0,
        evidence_ref="public:probe:1",
        persist=False,
    )
    waiting = next(item for item in service.initiative_state.pending_intentions if item.intention_id == intention.intention_id)
    assert waiting.status is IntentionStatus.AWAITING_OUTCOME
    assert waiting.expression_count == 1

    affordances = build_subject_initiative_affordances(
        service,
        runtime_context={"user_model_uncertainty": 0.96},
        now=d.now + 5.0,
    )
    assert not any(item.candidate.speech_act == "user_probe" for item in affordances)

    # "ok" là outcome thật nhưng không cung cấp thông tin cho epistemic probe.
    service.note_initiative_user_outcome("ok", now=d.now + 8.0, evidence_ref="user:ok", persist=False)
    revised = next(item for item in service.initiative_state.pending_intentions if item.intention_id == intention.intention_id)
    assert revised.status is IntentionStatus.REVISED
    assert revised.outcome_count == 1

    d.now += 60.0
    frame2 = asyncio.run(service.prepare_deliberation(obs.__class__(
        **{**obs.to_dict(), "observation_id": "initiative:cooldown", "created_at": d.now,
           "origin": ObservationOrigin.INTERNAL}
    )))
    assert not any(item.arguments.get("speech_act") == "user_probe" for item in frame2.proposals)
    asyncio.run(service.abandon_deliberation(frame2, reason="cooldown"))


def test_runtime_consumes_intention_only_after_successful_public_text() -> None:
    """Guard wiring: lifecycle hook nằm sau `if not text` và trước tick kế tiếp."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py").read_text(encoding="utf-8")
    no_text_pos = source.index("if not text:")
    hook_pos = source.index("note_initiative_public_act")
    relational_pos = source.index("note_relational_public_act", hook_pos)
    assert no_text_pos < hook_pos < relational_pos


def test_startup_greeting_invariant_runs_after_main_cognition_without_erasing_context() -> None:
    """Greeting phải sống, nhưng writer chính vẫn là main cognition có vision/context."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "runtime" / "ai_orchestrated" / "orchestrator.py").read_text(encoding="utf-8")
    cognition_call = source.index("payload = generate_autonomous(")
    invariant_call = source.index("payload = ensure_startup_greeting_payload(", cognition_call)
    assert cognition_call < invariant_call
    assert "typed_surface_preserved=1" not in source
    assert "STARTUP_WORDING_CONTRACT" in source[cognition_call:invariant_call]


def test_invalid_deliberator_choice_degrades_without_second_llm_call() -> None:
    """The LLM no longer owns IDs; an invalid local choice degrades to the fast gate."""
    d = Determinism()
    service = _service(d)
    ingress = SubjectIngress(service)
    session = ingress.prepare_autonomous_session(
        _blackboard(),
        (_seed_affordance(),),
        created_at=d.now,
        turn_id="runtime-stale-coalition-fail-closed",
        planning_context={
            "relational_state": service.relational_view(),
            "initiative_runtime_context": {"user_model_uncertainty": 0.96},
        },
    )
    calls = 0

    def fake_structured(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "choice_index": 999,
            "semantic_commitments": [],
            "cognitive_requests": [],
            "reason": "invalid local choice",
            "confidence": 0.86,
            "review_conditions": [],
        }

    frame = _force_ambiguous_non_social_frame(session.frame)
    executive = ExecutiveCortex(
        SimpleNamespace(action_executor=None),
        object(),
        invoke_structured=fake_structured,
        clock=d.clock,
    )
    commit = executive.commit_subject_frame(frame, mode="autonomous")

    assert commit is not None
    assert calls == 1
    assert commit.source == "neuro_fast_gate_degraded"
    assert commit.reason == "neuro_deliberator_out_of_frame_use_fast_gate"
    fast = executive._neuro_selector.select(session.frame)
    assert commit.selected_coalition_id == fast.winner(session.frame).coalition_id
    asyncio.run(service.abandon_deliberation(session.frame, reason="test_cleanup"))


def test_startup_greeting_updates_relational_homeostasis_as_non_reply_bearing_contact() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "runtime" / "ai_orchestrated" / "orchestrator.py").read_text(encoding="utf-8")
    greeting_commit = source.index("host._startup_greeting_spoken_at = spoken_at")
    relational_hook = source.index("note_relational_public_act", greeting_commit)
    return_pos = source.index("return True", relational_hook)
    block = source[relational_hook:return_pos]
    assert greeting_commit < relational_hook < return_pos
    assert "outreach=True" in block
    assert "expect_response=False" in block
    assert "startup_greeting:" in block
