from __future__ import annotations

from pathlib import Path

from memory.living_user.service import LivingUserMemoryConfig, LivingUserMemoryService
from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.random_chat_seed import RandomChatSeed, RandomChatSeedAffinityStore
from runtime.ai_orchestrated.random_chat_seed_service import SeedReservoirLease
from runtime.ai_orchestrated.social_initiative import SocialInitiativeEngine


def _snapshot(*, seconds: float = 400.0) -> dict:
    return {
        "time": 1000.0,
        "telemetry": {},
        "screen_context": {
            "fresh": True,
            "privacy_blocked": False,
            "meaningful_delta": False,
            "window_changed": False,
            "window_title": "",
            "evidence_refs": [],
        },
        "vision_grounding": {"recommendation": "silence", "evidence_strength": 0.0, "claims": []},
        "conversation_baton": {
            "reply_expected": False,
            "assistant_may_continue": False,
            "thread_fresh": False,
            "thread_key": "none",
        },
        "activity_session": {"has_new_event": False, "new_event_keys": []},
        "self_context": {
            "has_public_seed": True,
            "attention": {"internal_drive": 0.66},
            "public_fragments": ["ERIS finds over-engineered social systems funny."],
        },
        "memory_context": "User enjoys discussing ERIS architecture and dry technical teasing.",
        "personality_summary": "Warm, private, dryly playful.",
        "identity_summary": "ERIS likes sharing observations that feel personally meaningful.",
        "relationship": {"familiarity": 0.7, "playful_safety": 0.72},
        "discovery": {},
        "commentary_expectation": {"due": True, "required": False},
        "engagement_context": {"active": False},
        "engagement_interaction": {},
        "latest_observation": {},
        "seconds_since_user": seconds,
        "seconds_since_assistant": seconds,
        "open_loops": [],
        "recent_public_history": [
            {"role": "user", "text": "Fix gốc cho random chat đi."},
            {"role": "assistant", "text": "Cần một semantic seed trước Surface."},
        ],
    }


def _seed_payload(*, seed_id: str = "rseed_arch", mode: str = "eris_led") -> dict:
    return {
        "decision": "seed",
        "seed_id": seed_id,
        "mode": mode,
        "premise": "ERIS thinks every attempt to make conversation natural grows one more architecture layer, which is funny and worth sharing.",
        "source_kind": "eris_self_memory",
        "source_refs": ["self:architecture_irony", "memory:user_eris_design"],
        "topic_tags": ["eris_architecture", "dry_tease"],
        "opening_move": "share_opinion_with_tease",
        "desired_response": ["counter_tease", "agreement", "explain_reasoning"],
        "eris_motive": {
            "kind": "want_to_share",
            "why_now": "The current design discussion made the thought salient.",
            "personal_stake": 0.72,
            "authenticity": 0.88,
        },
        "risk": {
            "daring": 0.49,
            "uncertainty": 0.42,
            "intrusion_risk": 0.08,
            "face_risk": 0.28,
            "recovery_available": True,
        },
        "estimated_fit": 0.76,
        "confidence": 0.82,
        "tone": "dry_warm",
        "ttl_seconds": 90,
    }


def test_seed_contract_keeps_eris_ego_and_bounded_daring() -> None:
    seed = RandomChatSeed.from_mapping(_seed_payload())
    store = RandomChatSeedAffinityStore(clock=lambda: 1000.0)

    allowed, reason = store.validate_seed(seed, now=1000.0)

    assert allowed is True
    assert reason == "allowed"
    assert seed.mode == "eris_led"
    assert seed.eris_motive_kind == "want_to_share"
    assert seed.personal_stake == 0.72
    assert seed.daring == 0.49


def test_generic_presence_seed_is_rejected() -> None:
    payload = _seed_payload()
    payload["premise"] = "Mình vẫn ở đây đấy."
    seed = RandomChatSeed.from_mapping(payload)

    allowed, reason = RandomChatSeedAffinityStore(clock=lambda: 1000.0).validate_seed(seed, now=1000.0)

    assert allowed is False
    assert reason == "seed_generic_presence"


def test_negative_feedback_does_not_erase_eris_interest() -> None:
    store = RandomChatSeedAffinityStore(clock=lambda: 1000.0)
    seed = RandomChatSeed.from_mapping(_seed_payload())
    store.note_spoken(seed, assistant_turn_id="a1", text="Một câu chia sẻ.", now=1000.0)
    before = store.snapshot()["eris_interests"]["tag:eris_architecture"].copy()

    outcome = store.observe_user_turn("Đừng nói kiểu đó nữa.", user_turn_id="u1", now=1010.0)
    after = store.snapshot()["eris_interests"]["tag:eris_architecture"]

    assert outcome is not None and outcome.classification == "negative"
    assert store.snapshot()["affinities"]["tag:eris_architecture"]["score"] < 0
    assert after == before


def test_three_positive_outcomes_promote_user_preference() -> None:
    promotions: list[dict] = []

    def promote(**kwargs):
        promotions.append(kwargs)
        return kwargs["path"]

    store = RandomChatSeedAffinityStore(preference_callback=promote, clock=lambda: 1000.0)
    for index in range(3):
        payload = _seed_payload(seed_id=f"rseed_{index}", mode="shared")
        payload["premise"] += f" Variation {index}."
        seed = RandomChatSeed.from_mapping(payload)
        now = 1000.0 + index * 30.0
        store.note_spoken(seed, assistant_turn_id=f"a{index}", text="Một câu chia sẻ.", now=now)
        outcome = store.observe_user_turn(
            "Cái này nghe thú vị, kể thêm coi?",
            user_turn_id=f"u{index}",
            now=now + 5.0,
        )
        assert outcome is not None and outcome.classification == "positive"

    assert {item["path"] for item in promotions} == {
        "preferences.autonomous_chat.eris_architecture",
        "preferences.autonomous_chat.dry_tease",
    }
    assert all(item["explicitness"] == "observed" for item in promotions)


class _SeedRouter:
    surface_client = object()

    def __init__(self) -> None:
        self.generic_calls = 0

    def propose_social_initiative(self, request):
        self.generic_calls += 1
        return {"decision": "none"}


class _ReadyReservoir:
    enabled = True

    def __init__(self, payload: dict | None) -> None:
        self.seed = RandomChatSeed.from_mapping(payload) if payload else RandomChatSeed()
        self.claims = 0
        self.released: list[tuple[str, str]] = []
        self.committed: list[str] = []

    def claim(self, *, now=None):
        self.claims += 1
        if not self.seed.available:
            return None
        seed = self.seed
        self.seed = RandomChatSeed()
        return SeedReservoirLease(
            token="lease_arch",
            seed=seed,
            generated_at=900.0,
            expires_at=1500.0,
            context_revision=3,
        )

    def release(self, token, *, reason="", now=None):
        self.released.append((token, reason))
        return True

    def commit(self, token):
        self.committed.append(token)
        return True


def test_idle_random_chat_leases_precomputed_seed_without_model_call() -> None:
    router = _SeedRouter()
    reservoir = _ReadyReservoir(_seed_payload())
    snapshot = _snapshot()
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)
    engine = SocialInitiativeEngine(router, seed_reservoir=reservoir)

    candidate = engine.propose(board, snapshot=snapshot)

    assert candidate is not None and candidate.kind == "random_chat"
    assert candidate.seed_id == "rseed_arch"
    assert candidate.seed_lease_token == "lease_arch"
    assert candidate.eris_motive_kind == "want_to_share"
    assert candidate.daring == 0.49
    assert reservoir.claims == 1
    assert router.generic_calls == 0


def test_candidate_seed_payload_can_be_recorded_after_public_commit() -> None:
    router = _SeedRouter()
    reservoir = _ReadyReservoir(_seed_payload())
    snapshot = _snapshot()
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)
    store = RandomChatSeedAffinityStore(clock=lambda: 1000.0)
    candidate = SocialInitiativeEngine(router, seed_reservoir=reservoir).propose(board, snapshot=snapshot)
    assert candidate is not None

    store.note_spoken(
        candidate.random_chat_seed,
        assistant_turn_id="autonomous:1",
        text="Một nhận xét kiến trúc hơi khô.",
        now=1000.0,
    )

    state = store.snapshot()
    assert state["pending"]["seed_id"] == "rseed_arch"
    assert state["eris_interests"]["tag:eris_architecture"]["shares"] == 1


def test_empty_reservoir_is_real_silence_not_generic_fallback() -> None:
    router = _SeedRouter()
    reservoir = _ReadyReservoir(None)
    snapshot = _snapshot()
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)

    candidate = SocialInitiativeEngine(router, seed_reservoir=reservoir).propose(board, snapshot=snapshot)

    assert candidate is None
    assert reservoir.claims == 1
    assert router.generic_calls == 0


def test_governor_preserves_seed_in_surface_intent_and_plan(tmp_path: Path) -> None:
    router = _SeedRouter()
    reservoir = _ReadyReservoir(_seed_payload())
    snapshot = _snapshot()
    board = TypedCognitiveBlackboard.from_snapshot(snapshot, now=1000.0)
    candidate = SocialInitiativeEngine(router, seed_reservoir=reservoir).propose(board, snapshot=snapshot)
    assert candidate is not None

    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(board, candidate)

    assert decision.action is InitiativeAction.SPEECH
    assert decision.speech_intent is not None
    assert decision.speech_intent.random_chat_seed["seed_id"] == "rseed_arch"
    assert decision.plan.motive == "want_to_share"
    assert decision.plan.value_focus == "self_expression"
    assert decision.plan.semantics.subject_key == "rseed_arch"
    assert decision.plan.intrusion_risk >= 0.08


def test_living_user_preference_recording_keeps_evidence(tmp_path: Path) -> None:
    service = LivingUserMemoryService(
        tmp_path / "living_user",
        config=LivingUserMemoryConfig(auto_observe_turns=False, auto_sync_semantic=False),
    )

    result = service.record_interaction_preference(
        "preferences.autonomous_chat.eris_architecture",
        {"topic_tag": "eris_architecture", "preference": "welcomes_eris_sharing"},
        explicitness="observed",
        confidence=0.8,
        evidence_ids=("a1", "u1"),
        metadata={"seed_id": "rseed_arch"},
    )

    assert result.changed is True
    records = tuple(
        record for record in service.profile_store.all()
        if record.path.startswith("preferences.autonomous_chat")
    )
    assert len(records) == 1
    assert records[0].evidence_ids == ("a1", "u1")
    assert records[0].source == "random_chat_seed_outcome"
