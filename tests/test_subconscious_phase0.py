from __future__ import annotations

from types import SimpleNamespace

from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.subconscious import (
    ConsciousSynthesizer,
    SynthesisPolicy,
    SubconsciousBlackboard,
    ThoughtFragment,
)
from cortex.surface_arbiter import SurfaceArbiter
from runtime.subconscious_loop import SubconsciousLoop


def test_thought_fragment_factory_clamps_and_serializes() -> None:
    fragment = ThoughtFragment.create(
        source_agent="memory_resonator",
        kind="memory_echo_fragment",
        content="  ERIS nhớ bug micro-presence bị body-only kéo dài.  ",
        evidence_ids=["ev.memory.1", "ev.memory.1"],
        confidence=1.5,
        urgency=-3,
        affect_charge=0.42,
        privacy_level="normal",
        surface_allowed=True,
        tags=["micro_presence", "micro_presence"],
        now=1000.0,
    )

    assert fragment.confidence == 1.0
    assert fragment.urgency == 0.0
    assert fragment.affect_charge == 0.42
    assert fragment.evidence_ids == ("ev.memory.1",)
    assert fragment.tags == ("micro_presence",)
    assert fragment.to_dict()["source_agent"] == "memory_resonator"


def test_blackboard_dedupes_refreshes_and_decays() -> None:
    board = SubconsciousBlackboard(max_fragments=8)
    first = ThoughtFragment.create(
        source_agent="goal_simulator",
        kind="bottleneck_prediction",
        content="SurfaceArbiter đang thiếu seed nội sinh có evidence.",
        evidence_ids=["ev.goal.1"],
        confidence=0.55,
        urgency=0.45,
        tags=["surface_arbiter"],
        ttl_seconds=10,
        now=1000.0,
    )
    second = ThoughtFragment.create(
        source_agent="goal_simulator",
        kind="bottleneck_prediction",
        content="SurfaceArbiter đang thiếu seed nội sinh có evidence.",
        evidence_ids=["ev.goal.2"],
        confidence=0.75,
        urgency=0.60,
        tags=["surface_arbiter"],
        ttl_seconds=10,
        now=1001.0,
    )

    stored_first = board.submit(first)
    stored_second = board.submit(second)

    assert stored_first.id == stored_second.id
    assert len(board) == 1
    assert stored_second.confidence == 0.75
    assert stored_second.evidence_ids == ("ev.goal.1", "ev.goal.2")

    expired = board.decay(now=1012.0)
    assert expired == (stored_second.id,)
    assert len(board) == 0


def test_synthesizer_creates_surface_candidate_when_grounded() -> None:
    board = SubconsciousBlackboard()
    board.submit(
        ThoughtFragment.create(
            source_agent="memory_resonator",
            kind="memory_echo_fragment",
            content="User vừa hỏi vá Phase 0 nên cần seed subconscious có contract rõ.",
            evidence_ids=["ev.user.phase0"],
            confidence=0.82,
            urgency=0.68,
            affect_charge=0.31,
            privacy_level="normal",
            surface_allowed=True,
            tags=["phase0_subconscious"],
            now=1000.0,
        )
    )
    board.submit(
        ThoughtFragment.create(
            source_agent="goal_simulator",
            kind="possible_next_step",
            content="Tạo ThoughtFragment, Blackboard, Synthesizer trước khi thêm worker.",
            evidence_ids=["ev.arch.phase0"],
            confidence=0.78,
            urgency=0.62,
            affect_charge=0.20,
            privacy_level="normal",
            surface_allowed=True,
            tags=["phase0_subconscious"],
            now=1001.0,
        )
    )

    synthesizer = ConsciousSynthesizer()
    thought = synthesizer.synthesize_from_blackboard(board, now=1002.0)

    assert thought is not None
    assert thought.dominant_theme == "phase0 subconscious"
    assert thought.recommended_route == "surface_candidate"
    assert thought.surface_pressure >= 0.55
    assert set(thought.evidence_ids) == {"ev.user.phase0", "ev.arch.phase0"}
    assert thought.to_surface_seed()["public_seed"]


def test_synthesizer_keeps_private_fragment_out_of_surface() -> None:
    fragment = ThoughtFragment.create(
        source_agent="self_regulator",
        kind="restraint_drive",
        content="Một áp lực riêng tư không nên thành câu public ngay.",
        evidence_ids=["ev.private.1"],
        confidence=0.88,
        urgency=0.90,
        affect_charge=0.92,
        privacy_level="private",
        surface_allowed=True,
        tags=["restraint"],
        now=1000.0,
    )
    synthesizer = ConsciousSynthesizer(policy=SynthesisPolicy(rehearsal_band=0.70))
    thought = synthesizer.synthesize((fragment,))

    assert thought is not None
    assert thought.recommended_route == "rehearse"
    assert thought.public_seed == ""
    assert thought.suppressed_pressure >= 0.70


def test_runtime_loop_exposes_surface_seed_only_for_surface_candidate() -> None:
    loop = SubconsciousLoop()
    loop.submit(
        ThoughtFragment.create(
            source_agent="memory_resonator",
            kind="memory_echo_fragment",
            content="Có một seed đủ rõ để đưa qua SurfaceArbiter.",
            evidence_ids=["ev.seed.1"],
            confidence=0.9,
            urgency=0.8,
            affect_charge=0.2,
            privacy_level="normal",
            surface_allowed=True,
            tags=["seed_test"],
            now=1000.0,
        )
    )

    result = loop.tick(now=1001.0)

    assert result.thought_object is not None
    assert result.surface_seed is not None
    assert loop.subconscious_seed == result.surface_seed
    assert loop.subconscious_report is not None


def test_surface_arbiter_can_read_phase0_subconscious_report() -> None:
    loop = SubconsciousLoop()
    loop.submit(
        ThoughtFragment.create(
            source_agent="memory_resonator",
            kind="memory_echo_fragment",
            content="Seed đã qua Synthesizer, có thể thành một dòng rất nhỏ.",
            evidence_ids=["ev.surface.1"],
            confidence=0.92,
            urgency=0.82,
            affect_charge=0.30,
            privacy_level="normal",
            surface_allowed=True,
            tags=["memory"],
            now=1000.0,
        )
    )
    result = loop.tick(now=1001.0)
    frame = SimpleNamespace(subconscious_report=loop.subconscious_report, subconscious_seed=result.surface_seed)

    policy = LowLevelSpeechPolicy(
        LowLevelSpeechPolicyConfig(
            min_surface_interval_seconds=0.0,
            family_cooldown_seconds=0.0,
            high_conf_threshold=0.50,
            min_surface_confidence=0.30,
            body_only_min_confidence=0.20,
        )
    )
    arbiter = SurfaceArbiter(
        policy=policy,
        llm_micro_gen=lambda **kwargs: ("Tôi giữ lại mảnh này đã.", "test_llm"),
    )

    decision = arbiter.arbitrate(cognitive_frame=frame, silent_cycles=0)

    assert decision.should_speak is True
    assert decision.kind in {"thought_stream_surface", "memory_resonance"}
    assert decision.text == "Tôi giữ lại mảnh này đã."
