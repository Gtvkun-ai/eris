from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.surface_arbiter import SurfaceArbiter, SurfaceImpulse


def _policy() -> LowLevelSpeechPolicy:
    return LowLevelSpeechPolicy(
        LowLevelSpeechPolicyConfig(
            min_surface_confidence=0.30,
            body_only_min_confidence=0.20,
            force_llm_after_silent=99,
            always_llm_kinds=("technical_help", "memory_resonance"),
        )
    )


def test_surface_line_without_specific_anchor_token_becomes_body_only() -> None:
    calls = []

    def generator(**kwargs):
        calls.append(kwargs)
        return "Mạch này vẫn giữ chỗ.", "should_not_run"

    arbiter = SurfaceArbiter(policy=_policy(), llm_micro_gen=generator)
    impulse = SurfaceImpulse(
        kind="technical_help",
        source="surface_seed_compiler",
        confidence=0.82,
        pressure=0.82,
        score=0.82,
        topic_seed="VS Code looks paused",
        evidence=("surface_seed_compiler:vision_fact", "screen-ish summary"),
        should_surface=True,
    )

    decision = arbiter.arbitrate(extra_impulses=(impulse,), force_llm=True)

    assert decision.should_speak is False
    assert decision.body_only is True
    assert decision.reason == "forced_body_only:persona_anchor_missing"
    assert calls == []


def test_surface_line_with_specific_anchor_token_can_call_generator() -> None:
    calls = []

    def generator(**kwargs):
        calls.append(kwargs)
        return "Có một traceback đang làm mạch debug đứng lại.", "ok"

    arbiter = SurfaceArbiter(policy=_policy(), llm_micro_gen=generator)
    impulse = SurfaceImpulse(
        kind="technical_help",
        source="surface_seed_compiler",
        confidence=0.82,
        pressure=0.82,
        score=0.82,
        topic_seed="terminal shows traceback",
        evidence=("vision_fact_id=terminal_traceback_01", "terminal shows traceback"),
        should_surface=True,
    )

    decision = arbiter.arbitrate(extra_impulses=(impulse,), force_llm=True)

    assert decision.should_speak is True
    assert decision.body_only is False
    assert decision.source == "surface_arbiter_llm"
    assert len(calls) == 1


def test_surface_decision_ledger_records_gate_that_blocked_impulse() -> None:
    arbiter = SurfaceArbiter(policy=_policy(), llm_micro_gen=lambda **_: ("", "unused"))
    impulse = SurfaceImpulse(
        kind="technical_help",
        source="surface_seed_compiler",
        confidence=0.45,
        pressure=0.45,
        score=0.45,
        topic_seed="terminal shows traceback",
        family="debug_traceback",
        evidence=("vision_fact_id=terminal_traceback_01", "terminal shows traceback"),
        should_surface=True,
    )
    now = time.time()
    arbiter.last_surface_time = now
    arbiter._last_family_at[arbiter._family_id(impulse)] = now

    decision = arbiter.arbitrate(extra_impulses=(impulse,), silent_cycles=0)

    assert decision.should_speak is False
    assert decision.reason.startswith("soft_gate_block:")
    assert "[surface_decision_ledger]" in decision.debug_trace
    assert "family_cooldown" in decision.debug_trace
    assert "technical_help/surface_seed_compiler" in decision.debug_trace


def test_strong_anchored_impulse_can_override_soft_rate_gate() -> None:
    calls = []

    def generator(**kwargs):
        calls.append(kwargs)
        return "Traceback kia đủ rõ để bám vào.", "ok"

    arbiter = SurfaceArbiter(policy=_policy(), llm_micro_gen=generator)
    impulse = SurfaceImpulse(
        kind="technical_help",
        source="surface_seed_compiler",
        confidence=0.90,
        pressure=0.90,
        score=0.90,
        topic_seed="terminal shows traceback",
        family="debug_traceback",
        evidence=("vision_fact_id=terminal_traceback_01", "terminal shows traceback"),
        should_surface=True,
        vital_pressure=0.65,
    )
    now = time.time()
    arbiter.last_surface_time = now
    arbiter._last_family_at[arbiter._family_id(impulse)] = now

    decision = arbiter.arbitrate(extra_impulses=(impulse,), silent_cycles=0)

    assert decision.should_speak is True
    assert calls
    assert "family_cooldown" in decision.debug_trace
    assert "soft_gate_override=true" in decision.debug_trace
    assert "[surface_decision_ledger]" in decision.debug_trace
