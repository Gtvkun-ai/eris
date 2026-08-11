from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cortex.subject.neuro_control import (
    ChoiceSemanticAppraisal,
    NeuroActionSelector,
    NeuroSemanticAppraisal,
    SelectionResult,
    WorkspaceBroadcast,
)
from runtime.ai_orchestrated.random_chat_seed import RandomChatSeed, assess_seed_quality
from runtime.ai_orchestrated.random_chat_seed_service import (
    RandomChatSeedGenerator,
    RandomChatSeedReservoir,
    build_seed_temporal_context,
)
from runtime.ai_orchestrated.social_initiative import SocialInitiativeEngine


def _rich_seed(**overrides):
    payload = dict(
        decision="seed",
        seed_id="rseed_v32",
        mode="shared",
        premise=(
            "Tôi vừa nhận ra việc cố làm lời chào tự nhiên lại khiến kiến trúc mọc thêm một tầng; "
            "nghịch lý giữa autonomy và restraint đó khá buồn cười và đáng chia sẻ."
        ),
        source_kind="recent_shared_context",
        source_refs=("turn:test",),
        topic_tags=("autonomy", "restraint"),
        event_kind="thought",
        epistemic_mode="opinion",
        opening_move="share_observation",
        desired_response=("optional_reaction",),
        eris_motive_kind="want_to_share",
        eris_motive_why_now="Vừa có một chuỗi test về autonomous initiation nên liên hệ này còn mới và cụ thể.",
        personal_stake=0.72,
        authenticity=0.86,
        daring=0.24,
        uncertainty=0.18,
        intrusion_risk=0.16,
        face_risk=0.08,
        recovery_available=True,
        estimated_fit=0.78,
        confidence=0.84,
        tone="casual_warm",
        ttl_seconds=600.0,
    )
    payload.update(overrides)
    return RandomChatSeed(**payload)


def test_seed_quality_rejects_thin_fortune_cookie_even_with_high_declared_stake():
    seed = _rich_seed(
        premise="Thời gian trôi nhanh thật.",
        source_refs=(),
        eris_motive_why_now="",
        personal_stake=0.80,
        authenticity=0.80,
    )
    quality = assess_seed_quality(seed)
    assert quality.score < 0.46
    assert "thin_premise" in quality.reasons


def test_seed_quality_rewards_concrete_premise_and_real_why_now():
    quality = assess_seed_quality(_rich_seed())
    assert quality.score > 0.75
    assert quality.specificity > 0.70
    assert quality.motive_strength > 0.60


def test_seed_reservoir_quality_gate_rejects_thin_seed_before_stocking():
    generator = RandomChatSeedGenerator(object(), invoke_structured=lambda *_a, **_k: {})
    reservoir = RandomChatSeedReservoir(generator)
    thin = _rich_seed(
        premise="Thời gian trôi nhanh thật.",
        source_refs=(),
        eris_motive_why_now="",
    )
    allowed, reason = reservoir._validate_generated_locked(thin, 1_000.0)
    assert not allowed
    assert reason.startswith("seed_quality_low:")


def test_user_clock_context_is_vietnam_local_time_and_has_narrow_evidence_scope():
    epoch = datetime(2026, 8, 11, 16, 20, tzinfo=timezone(timedelta(hours=7))).timestamp()
    context = build_seed_temporal_context(epoch)
    assert context["timezone"] == "Asia/Ho_Chi_Minh"
    assert context["local_date"] == "2026-08-11"
    assert context["local_time"].startswith("16:20")
    assert context["local_hour"] == 16
    assert context["daypart"] == "afternoon"
    assert context["environment_evidence"] is False
    assert "ambient_sound" in context["does_not_support"]
    assert "room_lighting" in context["does_not_support"]


def test_seed_materialization_late_binds_time_instead_of_reusing_generation_time():
    generated = datetime(2026, 8, 11, 14, 20, tzinfo=timezone(timedelta(hours=7))).timestamp()
    used = datetime(2026, 8, 11, 18, 40, tzinfo=timezone(timedelta(hours=7))).timestamp()
    candidate = SocialInitiativeEngine._candidate_from_seed(
        _rich_seed(), generated_at=generated, expires_at=used + 600.0, now=used
    )
    temporal = candidate.random_chat_seed["temporal_context"]
    assert temporal["local_time"].startswith("18:40")
    assert temporal["daypart"] == "evening"
    assert candidate.random_chat_seed["claim_contract"]["current_environment_requires_direct_evidence"] is True
    assert candidate.seed_quality_score > 0.75


def test_seed_generation_request_receives_clock_without_making_clock_part_of_context_fingerprint():
    epoch = datetime(2026, 8, 11, 16, 20, tzinfo=timezone(timedelta(hours=7))).timestamp()
    generator = RandomChatSeedGenerator(object(), invoke_structured=lambda *_a, **_k: {})
    reservoir = RandomChatSeedReservoir(generator, clock=lambda: epoch)
    reservoir._context_request = {"user_memory": "", "recent_public_history": []}
    request = reservoir._generation_request_locked()
    assert request["generation_temporal_context"]["local_time"].startswith("16:20")
    projection = reservoir._fingerprint_projection(request)
    assert "generation_temporal_context" not in projection


def test_parallel_semantic_appraisal_can_make_silence_win_without_remote_winner_vote():
    speak = SimpleNamespace(action_kind="speak", arguments={"seed_id": "rseed"})
    silence = SimpleNamespace(action_kind="silence", arguments={})
    frame = SimpleNamespace(coalitions=(speak, silence))
    broadcast = WorkspaceBroadcast(signals=(), surprise=0.0, precision=0.7, resource=1.0, social_drive=0.5)
    baseline = SelectionResult(
        winner_index=0,
        scores=(0.56, 0.52),
        probabilities=(0.55, 0.45),
        margin=0.04,
        entropy=0.99,
        requires_deliberation=False,
        parallel_review_recommended=False,
        reason="fast_gate:test",
        broadcast=broadcast,
    )
    appraisal = NeuroSemanticAppraisal(
        choices=(
            ChoiceSemanticAppraisal(
                index=0,
                motive_validity=0.18,
                novelty=0.12,
                continuity_fit=0.18,
                epistemic_support=0.0,
                reversibility=0.55,
            ),
            ChoiceSemanticAppraisal(
                index=1,
                motive_validity=0.5,
                novelty=0.5,
                continuity_fit=0.8,
                epistemic_support=1.0,
                reversibility=1.0,
            ),
        ),
        boundary_pressure=0.94,
        interruption_cost=0.88,
        confidence=0.92,
        reason="explicit_quiet_boundary_and_unsupported_world_claim",
    )
    merged = NeuroActionSelector().merge_semantic_appraisal(frame, baseline, appraisal)
    assert merged.winner_index == 1
    assert merged.winner(frame).action_kind == "silence"
    assert merged.reason.startswith("semantic_merge:")


def test_recent_unanswered_autonomous_speech_increases_silence_utility():
    observation = SimpleNamespace(context={"runtime_context": {
        "recent_unsolicited_speech": 1.0,
        "user_response_rate": 0.0,
        "social_refractory_cost": 0.22,
    }})
    speak = SimpleNamespace(
        action_kind="speak",
        arguments={},
        score=0.60,
        expected_pragmatic_value=0.50,
        expected_epistemic_value=0.30,
        uncertainty=0.20,
        proposal_refs=(),
    )
    silence = SimpleNamespace(
        action_kind="silence",
        arguments={},
        score=0.59,
        expected_pragmatic_value=0.20,
        expected_epistemic_value=0.10,
        uncertainty=0.10,
        proposal_refs=(),
    )
    frame = SimpleNamespace(
        observation=observation,
        coalitions=(speak, silence),
        appraisals=(),
        activations=(),
        proposals=(),
        substrate=SimpleNamespace(processing_capacity=1.0),
    )
    selection = NeuroActionSelector().select(frame)
    assert selection.winner(frame).action_kind == "silence"
