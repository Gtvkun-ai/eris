from __future__ import annotations

import asyncio
from types import SimpleNamespace

from cortex.subject.contracts import ObservationOrigin, SubjectExecutiveCommit, WorldObservation
from cortex.subject.initiative import MotiveKind
from cortex.subject.relational import RelationalState
from cortex.subject.service import SubjectService, SubjectServiceConfig
from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex
from runtime.subject_ingress import SubjectIngress
from runtime.subject_initiative_runtime import (
    build_initiative_runtime_context,
    build_subject_initiative_affordances,
    coalesce_contact_probe_affordances,
)


class Determinism:
    def __init__(self) -> None:
        self.i = 0
        self.now = 1000.0

    def id(self) -> str:
        self.i += 1
        return f"v26-{self.i}"

    def clock(self) -> float:
        return self.now


def _service(d: Determinism) -> SubjectService:
    service = SubjectService(
        config=SubjectServiceConfig(restore_projection=False),
        clock=d.clock,
        id_factory=d.id,
    )
    service.relational_state = RelationalState(
        revision=8,
        updated_at=d.now,
        last_meaningful_exchange_at=d.now - 1800.0,
        affiliation_deficit=0.82,
        interaction_satiety=0.05,
        social_curiosity=0.62,
        partner_availability=0.90,
        interruption_cost=0.06,
        outreach_confidence=0.78,
        reciprocity_expectation=0.72,
        evidence_refs=("relational:v26",),
    )
    return service


def _internal_observation(d: Determinism) -> WorldObservation:
    return WorldObservation(
        observation_id="internal:v26",
        subject_id="eris",
        kind="subject_initiative_tick",
        created_at=d.now,
        origin=ObservationOrigin.INTERNAL,
        context={
            "context_key": "self_initiated",
            "affected_need_ids": ("connection", "coherence"),
            "goal_relevance": 0.62,
            "novelty": 0.05,
            "controllability": 0.90,
            "relational_significance": 0.80,
            "future_consequence": 0.35,
            "uncertainty": 0.72,
            "runtime_context": {
                "partner_available": 0.90,
                "interruption_cost": 0.06,
                "social_curiosity": 0.62,
                "user_model_uncertainty": 0.92,
                "user_model_evidence_refs": ("user-model:thin",),
            },
        },
        evidence_refs=("user-model:thin", "relational:v26"),
    )


def test_understand_user_motive_is_generated_without_random_seed() -> None:
    d = Determinism()
    service = _service(d)
    frame = asyncio.run(service.prepare_deliberation(_internal_observation(d)))

    motives = service.initiative_state.active_motives
    understand = next(item for item in motives if item.kind is MotiveKind.UNDERSTAND_USER)
    assert understand.pressure >= 0.40
    assert "user-model:thin" in understand.evidence_refs
    assert "seed" not in understand.reason.lower()
    assert any(
        item.action_kind == "speak"
        and item.arguments.get("speech_act") == "user_probe"
        and item.arguments.get("initiative_motive") == "understand_user"
        for item in frame.proposals
    )
    asyncio.run(service.abandon_deliberation(frame, reason="test_cleanup"))


def test_pending_intention_survives_origin_change_from_internal_to_user() -> None:
    d = Determinism()
    service = _service(d)
    first = asyncio.run(service.prepare_deliberation(_internal_observation(d)))
    intention = next(
        item for item in service.initiative_state.pending_intentions
        if item.motive_kind is MotiveKind.UNDERSTAND_USER
    )
    asyncio.run(service.abandon_deliberation(first, reason="test_cleanup"))

    d.now += 5.0
    user = WorldObservation(
        observation_id="user:v26",
        subject_id="eris",
        kind="user_turn",
        created_at=d.now,
        origin=ObservationOrigin.USER,
        context={
            "context_key": "direct_chat",
            "user_text": "ừ",
            "affected_need_ids": ("connection", "coherence"),
            "goal_relevance": 0.8,
            "novelty": 0.2,
            "controllability": 0.9,
            "relational_significance": 0.7,
            "future_consequence": 0.2,
            "uncertainty": 0.5,
            "runtime_context": {
                "user_model_uncertainty": 0.88,
                "user_model_evidence_refs": ("user-model:thin",),
            },
        },
        evidence_refs=("user:v26",),
    )
    second = asyncio.run(service.prepare_deliberation(user))
    after = next(
        item for item in service.initiative_state.pending_intentions
        if item.motive_kind is MotiveKind.UNDERSTAND_USER
    )
    assert after.intention_id == intention.intention_id
    assert after.source_origin is ObservationOrigin.INTERNAL
    assert any(item.arguments.get("intention_id") == intention.intention_id for item in second.proposals)
    asyncio.run(service.abandon_deliberation(second, reason="test_cleanup"))


def test_subject_initiative_builds_user_probe_affordance_without_seed() -> None:
    d = Determinism()
    service = _service(d)
    frame = asyncio.run(service.prepare_deliberation(_internal_observation(d)))
    asyncio.run(service.abandon_deliberation(frame, reason="test_cleanup"))

    affordances = build_subject_initiative_affordances(
        service,
        runtime_context={
            "user_model_uncertainty": 0.92,
            "user_model_evidence_refs": ("user-model:thin",),
        },
        now=d.now + 1.0,
    )
    probe = next(item for item in affordances if item.candidate.speech_act == "user_probe")
    assert probe.owner == "subject_initiative"
    assert probe.candidate.requires_grounding is False
    assert "assume" in probe.candidate.topic.lower()




def test_contact_and_user_probe_are_coalesced_before_competition() -> None:
    contact = SimpleNamespace(
        affordance_id="relational:contact:1",
        candidate=SimpleNamespace(
            speech_act="contact_bid", relevance=0.90, confidence=0.90, urgency=0.80
        ),
    )
    probe = SimpleNamespace(
        affordance_id="subject-intention:probe:1",
        candidate=SimpleNamespace(
            speech_act="user_probe", relevance=0.70, confidence=0.72, urgency=0.60
        ),
    )
    task = SimpleNamespace(
        affordance_id="task:1",
        candidate=SimpleNamespace(
            speech_act="share_grounded_runtime_finding", relevance=0.80, confidence=0.90, urgency=0.50
        ),
    )

    thin_model = coalesce_contact_probe_affordances(
        (contact, probe, task),
        runtime_context={"user_model_uncertainty": 0.92},
    )
    assert [item.affordance_id for item in thin_model] == ["subject-intention:probe:1", "task:1"]

    thick_model = coalesce_contact_probe_affordances(
        (contact, probe, task),
        runtime_context={"user_model_uncertainty": 0.25},
    )
    assert [item.affordance_id for item in thick_model] == ["relational:contact:1", "task:1"]


def test_startup_social_cooldown_blocks_immediate_check_in() -> None:
    import time

    host = SimpleNamespace(
        _startup_greeting_spoken_at=time.time() - 20.0,
        private_mind_daemon=None,
        private_mind_system=None,
        private_mind_loop=None,
    )
    runtime_context = build_initiative_runtime_context(host)
    assert runtime_context["startup_social_cooldown_active"] is True

    d = Determinism()
    service = _service(d)
    frame = asyncio.run(service.prepare_deliberation(_internal_observation(d)))
    asyncio.run(service.abandon_deliberation(frame, reason="test_cleanup"))

    affordances = build_subject_initiative_affordances(
        service,
        runtime_context={
            **runtime_context,
            "user_model_uncertainty": 0.92,
            "user_model_evidence_refs": ("user-model:thin",),
        },
        now=d.now + 1.0,
    )
    assert not any(
        item.candidate.speech_act in {"contact_bid", "user_probe", "curiosity_bid"}
        for item in affordances
    )


def test_chat_and_self_turn_commit_through_same_mindloop_port() -> None:
    d = Determinism()
    service = _service(d)
    ingress = SubjectIngress(service)

    class Executive:
        enabled = True

        def __init__(self) -> None:
            self.modes: list[str] = []

        def commit_subject_frame(self, frame, *, mode="runtime", **_kwargs):
            self.modes.append(mode)
            selected = frame.coalitions[0]
            return SubjectExecutiveCommit(
                commit_id=f"commit:{mode}:{len(self.modes)}",
                frame_id=frame.frame_id,
                selected_coalition_id=selected.coalition_id,
                selected_proposal_ref=selected.primary_proposal_ref,
                semantic_commitments=(),
                cognitive_requests=(),
                reason="same executive port for every origin",
                confidence=0.8,
                review_conditions=(),
                created_at=d.now,
            )

    executive = Executive()
    user_session = ingress.prepare_user_session("chào", created_at=d.now, turn_id="u-v26")
    ingress.complete_session(user_session, committer=executive)

    candidate = SimpleNamespace(
        kind="social_check_in", topic="ask one open question", speech_act="user_probe",
        tone="curious", source="subject_initiative", confidence=0.8, relevance=0.8,
        urgency=0.4, evidence_refs=("user-model:thin",), requires_grounding=False,
    )
    affordance = SimpleNamespace(
        affordance_id="subject-intention:test", owner="subject_initiative", candidate=candidate,
    )
    blackboard = SimpleNamespace(
        reply_expected=False, engagement_active=False, user_busy=False,
        public_view=lambda: {"reply_expected": False, "engagement_active": False, "novelty": 0.1},
    )
    auto_session = ingress.prepare_autonomous_session(
        blackboard, (affordance,), created_at=d.now, turn_id="a-v26",
        planning_context={
            "relational_state": service.relational_view(),
            "initiative_runtime_context": {"user_model_uncertainty": 0.9},
        },
    )
    ingress.complete_session(auto_session, committer=executive)

    assert executive.modes == ["interactive", "autonomous"]


def test_committed_subject_probe_materializes_without_second_executive_decision() -> None:
    d = Determinism()
    service = _service(d)
    ingress = SubjectIngress(service)
    # Prime initiative state first.
    frame = asyncio.run(service.prepare_deliberation(_internal_observation(d)))
    asyncio.run(service.abandon_deliberation(frame, reason="prime"))
    affordances = build_subject_initiative_affordances(
        service,
        runtime_context={"user_model_uncertainty": 0.92},
        now=d.now + 1.0,
    )
    blackboard = SimpleNamespace(
        reply_expected=False, engagement_active=False, user_busy=False,
        public_view=lambda: {"reply_expected": False, "engagement_active": False, "novelty": 0.1},
    )
    session = ingress.prepare_autonomous_session(
        blackboard, affordances, created_at=d.now + 1.0, turn_id="materialize-v26",
        planning_context={
            "relational_state": service.relational_view(),
            "initiative_runtime_context": {"user_model_uncertainty": 0.92},
        },
    )

    class Committer:
        enabled = True

        def commit_subject_frame(self, frame, **_kwargs):
            selected = next(
                item for item in frame.coalitions
                if item.arguments.get("speech_act") == "user_probe"
            )
            return SubjectExecutiveCommit(
                commit_id="probe-commit", frame_id=frame.frame_id,
                selected_coalition_id=selected.coalition_id,
                selected_proposal_ref=selected.primary_proposal_ref,
                semantic_commitments=("ask one open probe",), cognitive_requests=(),
                reason="understand user", confidence=0.8, review_conditions=(), created_at=d.now,
            )

    decision = ingress.complete_session(session, committer=Committer())
    invoked: list[object] = []
    cortex = ExecutiveCortex(
        SimpleNamespace(action_executor=None),
        None,
        invoke_structured=lambda *_a, **_k: invoked.append(object()),
        clock=lambda: d.now,
    )
    outcome = cortex.materialize_subject_decision(decision, affordances, subject_frame=session.frame)
    assert outcome is not None
    assert outcome.action == "use_candidate"
    assert outcome.candidate is not None
    assert outcome.candidate.speech_act == "user_probe"
    assert invoked == []


def test_production_self_turn_uses_unified_subject_commit_path() -> None:
    """Guard kiến trúc: self-turn không quay lại semantic Executive path cũ."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py").read_text(encoding="utf-8")
    assert "subject_ingress.complete_session(" in source
    assert "complete_autonomous_turn(" not in source
    # ``executive.deliberate`` chỉ còn ở nhánh capability_route sau Subject commit.
    commit_pos = source.index("subject_ingress.complete_session(")
    capability_pos = source.index('subject_decision.arguments.get("capability_route", False)')
    legacy_exec_pos = source.index("executive.deliberate(", capability_pos)
    assert commit_pos < capability_pos < legacy_exec_pos


def test_seed_is_not_required_for_initiative_wake_source() -> None:
    """Guard tĩnh nhỏ: initiative_pressure tồn tại độc lập seed_available."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime" / "ai_orchestrated" / "self_turn_pipeline.py").read_text(encoding="utf-8")
    assert 'emit(\n                "initiative_pressure"' in source
    assert "preview_understand" in source
    assert "user_model_uncertainty" in source
