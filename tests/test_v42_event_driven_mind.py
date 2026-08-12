from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from cortex.active_concern import private_concern_view
from cortex.private_mind.concern_store import ConcernStore
from cortex.private_mind.contracts import ThoughtFragment
from runtime.active_concern_runtime import ActiveConcernRuntime
from runtime.claim_domain_contract import validate_claim_manifest
from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.random_chat_seed_service import RandomChatSeedReservoir
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate
from runtime.subject_proposals import AutonomousProposalSource


def _seed_candidate(seed_id: str, topic: str, *, evidence_refs=("seed-source",)):
    return SimpleNamespace(
        available=True,
        kind="random_chat",
        topic=topic,
        source="random_chat_seed",
        confidence=0.84,
        relevance=0.80,
        urgency=0.18,
        requires_grounding=False,
        seed_intrusion_risk=0.16,
        intrusion_risk=0.16,
        seed_quality_score=0.90,
        seed_specificity=0.82,
        seed_motive_strength=0.72,
        seed_semantic_completeness=0.88,
        seed_id=seed_id,
        seed_epistemic_mode="opinion",
        seed_temporal_context={},
        evidence_refs=evidence_refs,
        speech_act="share_self_originated_thought",
        tone="natural",
        uncertainty=0.24,
        source_kind="recent_shared_context",
        seed_event_kind="thought",
    )


def _aff(seed_id: str, topic: str, *, evidence_refs=("seed-source",)):
    return SimpleNamespace(
        affordance_id=f"aff:{seed_id}",
        owner="random_chat_seed",
        candidate=_seed_candidate(seed_id, topic, evidence_refs=evidence_refs),
        metadata={},
    )


def _runtime(store: ConcernStore) -> ActiveConcernRuntime:
    host = SimpleNamespace(
        private_mind_daemon=SimpleNamespace(concern_store=store),
        last_cortex_attention=SimpleNamespace(interrupt_cost=0.0),
        logger=None,
    )
    return ActiveConcernRuntime(host)


def test_same_seed_is_a_cognitive_event_only_once():
    store = ConcernStore()
    runtime = _runtime(store)
    now = time.time()
    affordance = _aff("seed.v42.once", "autonomy cần restraint để không làm phiền")

    first = runtime.ingest_affordances((affordance,), now=now)
    concern = store.get(first[0])
    before = (concern.recurrence, concern.updated_at, dict(concern.metadata))
    second = runtime.ingest_affordances((affordance,), now=now + 30)
    concern_after = store.get(first[0])

    assert first
    assert second == ()
    assert concern_after.recurrence == before[0]
    assert concern_after.updated_at == before[1]
    assert concern_after.metadata["event_count"] == before[2]["event_count"] == 1


def test_scheduler_projection_does_not_reactivate_concern():
    store = ConcernStore()
    runtime = _runtime(store)
    now = time.time()
    cid = runtime.ingest_affordances((_aff("seed.v42.tick", "một câu hỏi cụ thể về autonomy"),), now=now)[0]
    concern = store.get(cid)
    baseline = (concern.recurrence, concern.metadata.get("reactivation_count", 0))

    for offset in (3, 8, 21, 55):
        runtime.snapshot(now=now + offset)

    concern = store.get(cid)
    assert (concern.recurrence, concern.metadata.get("reactivation_count", 0)) == baseline


def test_no_mutation_does_not_get_fake_mutation_freshness():
    store = ConcernStore()
    runtime = _runtime(store)
    now = time.time()
    cid = runtime.ingest_affordances((_aff("seed.v42.novelty", "một suy nghĩ cụ thể chưa được nói"),), now=now)[0]
    concern = store.get(cid)
    assert int(concern.metadata.get("mutation_count", 0)) == 0
    view = private_concern_view(concern, now=now + 90)
    # V40 từng vô tình cho mutation_count=0 vẫn freshness ~= 1.0.
    assert view.novelty < 0.60


def test_related_topics_do_not_become_one_mega_concern():
    store = ConcernStore()
    runtime = _runtime(store)
    now = time.time()
    runtime.ingest_affordances((_aff("seed.v42.a", "im lặng có thể là một lựa chọn xã hội"),), now=now)
    runtime.ingest_affordances((_aff("seed.v42.b", "sự hiện diện có thể trở thành một màn trình diễn"),), now=now + 1)
    opened = store.open_concerns(limit=10)
    assert len(opened) == 2


def test_new_event_echo_habituates_instead_of_pumping_pressure():
    store = ConcernStore()
    runtime = _runtime(store)
    now = time.time()
    first = _aff("seed.v42.echo1", "autonomy cần restraint để không làm phiền", evidence_refs=("same-source",))
    second = _aff("seed.v42.echo2", "restraint giúp autonomy không trở thành làm phiền", evidence_refs=("same-source",))
    cid = runtime.ingest_affordances((first,), now=now)[0]
    before = store.get(cid).pressure
    runtime.ingest_affordances((second,), now=now + 5)
    after = store.get(cid)
    assert int(after.metadata.get("echo_streak", 0)) >= 1
    assert after.pressure < before
    view = private_concern_view(after, now=now + 6)
    assert view.habituation > 0.0


def test_new_independent_evidence_can_mutate_and_reset_echo():
    store = ConcernStore()
    runtime = _runtime(store)
    now = time.time()
    first = _aff("seed.v42.m1", "autonomy cần restraint để không làm phiền", evidence_refs=("turn:1",))
    echo = _aff("seed.v42.m2", "restraint giúp autonomy không trở thành làm phiền", evidence_refs=("turn:1",))
    mutation = _aff("seed.v42.m3", "autonomy cần restraint để không làm phiền", evidence_refs=("turn:2",))
    cid = runtime.ingest_affordances((first,), now=now)[0]
    runtime.ingest_affordances((echo,), now=now + 1)
    runtime.ingest_affordances((mutation,), now=now + 2)
    concern = store.get(cid)
    assert int(concern.metadata.get("mutation_count", 0)) >= 1
    assert int(concern.metadata.get("echo_streak", 0)) == 0


def test_seed_context_excludes_assistant_surface_text():
    generator = SimpleNamespace(enabled=True)
    reservoir = RandomChatSeedReservoir(generator)
    request = reservoir._context_from_snapshot({
        "recent_public_history": [
            {"role": "user", "content": "user event thật"},
            {"role": "assistant", "content": "một chỗ đứng nhẹ trong bóng tối"},
        ],
        "personality_summary": "",
        "identity_summary": "",
        "relationship_summary": "",
        "memory_context": "",
        "self_context": {},
    })
    rendered = str(request.get("recent_user_events", ""))
    assert "user event thật" in rendered
    assert "một chỗ đứng nhẹ trong bóng tối" not in rendered
    assert "recent_public_history" not in request


def test_background_seed_status_never_reaches_public_callback():
    calls = []
    reservoir = RandomChatSeedReservoir(SimpleNamespace(enabled=True), status_callback=lambda **kw: calls.append(kw))
    reservoir._status(activity="random_chat_seed", phase="generating", label="internal", active=True)
    assert calls == []


def test_no_persistent_preparing_to_speak_status_in_background_runtime():
    root = Path(__file__).resolve().parents[1] / "runtime" / "ai_orchestrated"
    text = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("self_turn_pipeline.py", "random_chat_seed_service.py", "orchestrator.py")
    )
    assert "Đang chuẩn bị nói" not in text
    assert "Đang nghĩ xem có nên nói" not in text
    assert "Đang chuẩn bị chuyện để nói" not in text


def _board(*, reply_expected: bool) -> TypedCognitiveBlackboard:
    return TypedCognitiveBlackboard.from_snapshot({
        "telemetry": {},
        "screen_context": {"fresh": False, "privacy_blocked": False, "evidence_refs": [], "visible_text": [], "changed_text": []},
        "vision_facts": [],
        "conversation_baton": {
            "reply_expected": reply_expected,
            "assistant_may_continue": False,
            "thread_fresh": reply_expected,
            "thread_key": "t1",
        },
        "self_context": {},
        "engagement_context": {"active": False},
        "commentary_expectation": {},
        "seconds_since_user": 2.0,
        "seconds_since_assistant": 40.0,
    }, now=1000.0)


def _social_candidate() -> SocialSpeechCandidate:
    return SocialSpeechCandidate(
        decision="candidate",
        kind="random_chat",
        topic="chia sẻ một ý mới có nội dung",
        speech_act="share_self_originated_thought",
        anchor_type="idle",
        anchor_id="shared_quiet",
        evidence_refs=("turn:1",),
        confidence=0.82,
        relevance=0.75,
        urgency=0.20,
        source="random_chat_seed",
    )


def test_waiting_for_user_is_feature_before_neuro_not_downstream_veto(tmp_path: Path):
    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = _board(reply_expected=True)
    candidate = _social_candidate()
    aff = SimpleNamespace(affordance_id="aff:wait", candidate=candidate)
    signals = controller.policy_signals(board, (aff,))
    assert signals["aff:wait"]["reply_cost"] >= 0.9

    # Legacy callers still get the old guard, but production path after Neuro does not.
    assert controller.decide(board, candidate).action is not InitiativeAction.SPEECH
    committed = controller.decide(board, candidate, committed_by_neuro=True)
    assert committed.action is InitiativeAction.SPEECH
    assert committed.reason == "neuro_committed"


def test_policy_cost_is_attached_to_speech_proposal_before_neuro():
    proposal = AutonomousProposalSource.from_affordance(
        _aff("seed.v42.policy", "một ý đủ cụ thể để chia sẻ"),
        turn_id="autonomous:42",
        policy_signal={"total_cost": 0.92, "reply_expected": True, "reply_cost": 0.92},
    )
    assert proposal is not None
    assert proposal["arguments"]["initiative_policy_cost"] == 0.92
    assert proposal["substrate_cost"] > 0.4
    assert proposal["commitment_conflict"] > 0.4


def test_claim_domain_contract_rejects_sensor_claim_without_authority():
    verdict = validate_claim_manifest(
        [{"domain": "grounded_environment", "claim": "nghe tiếng quạt", "evidence_refs": []}],
        allowed_domains=("internal_state", "opinion", "hypothetical"),
        allowed_evidence_refs=(),
    )
    assert verdict.allowed is False
    assert verdict.reason == "claim_domain_not_allowed"


def test_claim_domain_contract_accepts_grounded_environment_with_exact_ref():
    verdict = validate_claim_manifest(
        [{"domain": "grounded_environment", "claim": "màn hình đang hiện X", "evidence_refs": ["vision:42"]}],
        allowed_domains=("grounded_environment",),
        allowed_evidence_refs=("vision:42",),
    )
    assert verdict.allowed is True
    assert verdict.added_claim_count == 1


def test_autonomous_semantic_timeout_uses_local_merge_not_fast_speak_fail_open():
    source = (Path(__file__).resolve().parents[1] / "runtime" / "ai_orchestrated" / "executive_cortex.py").read_text(encoding="utf-8")
    assert "semantic_appraisal_unavailable_use_fast_gate" not in source
    assert "neuro_local_semantic_merge" in source
    assert "local_typed_semantic_fallback" in source


def test_surface_wording_schema_requires_typed_claim_manifest():
    from runtime.ai_orchestrated.model_router import PUBLIC_REPLY_CORE_SCHEMA, SURFACE_REALIZATION_SCHEMA

    assert "claim_manifest" in PUBLIC_REPLY_CORE_SCHEMA["required"]
    assert "claim_manifest" in SURFACE_REALIZATION_SCHEMA["required"]


def test_grounding_validator_does_not_re_veto_reply_baton_after_neuro(tmp_path: Path):
    from runtime.ai_orchestrated.grounding_validator import AutonomousGroundingValidator

    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    board = _board(reply_expected=True)
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="continuation",
        topic="tiếp đúng thread đã được Neuro commit",
        speech_act="continuation",
        anchor_type="conversation",
        anchor_id="t1",
        evidence_refs=("turn:1",),
        confidence=0.8,
        relevance=0.8,
    )
    decision = controller.decide(board, candidate, committed_by_neuro=True)
    assert decision.speech_intent is not None
    assert AutonomousGroundingValidator().validate_intent(decision.speech_intent, board).allowed is True


def test_seed_worker_does_not_feed_its_own_private_life_events_back_into_seed_context():
    reservoir = RandomChatSeedReservoir(SimpleNamespace(enabled=True))
    request = reservoir._context_from_snapshot({
        "recent_public_history": [],
        "personality_summary": "",
        "identity_summary": "",
        "memory_context": "",
        "self_context": {
            "private_life_workspace": [
                {
                    "id": "mental.seed.self",
                    "kind": "thought",
                    "content": "seed worker tự sinh ý về khoảng trống",
                    "origin_source": "seed_worker",
                    "open_loop": True,
                },
                {
                    "id": "mental.memory.real",
                    "kind": "memory_callback",
                    "content": "một ký ức thực sự nổi lên từ memory resonance",
                    "origin_source": "memory_resonance",
                    "open_loop": True,
                },
            ],
        },
    })
    workspace = request["eris_self_memory"]["private_life_workspace"]
    rendered = str(workspace)
    assert "seed worker tự sinh" not in rendered
    assert "một ký ức thực sự" in rendered


def test_same_private_mind_fragment_is_not_a_new_event_on_next_tick():
    store = ConcernStore()
    fragment = ThoughtFragment(
        source="intent_evaluator",
        claim="Eris đang cân nhắc một ranh giới cụ thể",
        confidence=0.82,
        pressure=0.55,
        evidence_ids=("turn:42",),
    )
    first = store.update_from_fragments((fragment,))
    assert first
    concern = first[0]
    before = (concern.recurrence, concern.pressure, concern.updated_at, concern.metadata.get("event_count"))
    second = store.update_from_fragments((fragment,))
    after = store.get(concern.id)
    assert second == ()
    assert (after.recurrence, after.pressure, after.updated_at, after.metadata.get("event_count")) == before


def test_public_text_without_claim_manifest_fails_closed():
    verdict = validate_claim_manifest(
        None,
        allowed_domains=("internal_state", "opinion"),
        allowed_evidence_refs=(),
        text_present=True,
    )
    assert verdict.allowed is False
    assert verdict.reason == "claim_manifest_missing"
