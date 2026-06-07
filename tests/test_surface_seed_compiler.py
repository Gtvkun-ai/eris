from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.surface_arbiter import SurfaceImpulse
from cortex.surface_seed_compiler import SurfaceSeedCompiler


def test_memory_resonance_public_safe_compiles_to_impulse() -> None:
    activation = SimpleNamespace(
        may_surface=True,
        text="A remembered pattern about debugging vision starvation.",
        evidence_ids=("memory.ev.1",),
        record_id="mem-1",
        layer="semantic",
    )
    resonance = SimpleNamespace(
        score=0.62,
        attention_bias=0.40,
        wording_bias=0.55,
        dominant_layer="semantic",
        activations=(activation,),
    )

    compiled = SurfaceSeedCompiler().compile(active_memory_resonance=resonance, surface_kind="re_engagement")

    assert compiled.selected is True
    assert compiled.impulse is not None
    assert compiled.impulse.kind == "memory_resonance"
    assert compiled.impulse.source == "surface_seed_compiler"
    assert compiled.root_source == "memory_resonance"
    assert "memory.ev.1" in compiled.evidence


def test_vague_memory_resonance_does_not_compile_to_placeholder_speech() -> None:
    activation = SimpleNamespace(
        may_surface=True,
        text="memory resonance",
        evidence_ids=("memory.ev.vague",),
        record_id="mem-vague",
        layer="semantic",
    )
    resonance = SimpleNamespace(
        score=0.72,
        attention_bias=0.66,
        wording_bias=0.64,
        dominant_layer="semantic",
        activations=(activation,),
    )

    compiled = SurfaceSeedCompiler().compile(active_memory_resonance=resonance, surface_kind="re_engagement")

    assert compiled.selected is False
    assert compiled.impulse is None


def test_thought_surface_public_seed_compiles_as_thought_stream_seed() -> None:
    frame = SimpleNamespace(
        thought_stream_report=SimpleNamespace(
            latest_seed=SimpleNamespace(
                public_seed="a small public-safe thought about the mouth gate",
                topic_seed="private raw topic should not win",
                pressure=0.55,
                momentum_score=0.48,
                evidence=("anchor=recent_silence",),
                recommended_route="surface_candidate",
                impulse_kind="inner_whim",
                root_source="thought_stream",
                action_opportunity="surface one rooted aside",
            )
        )
    )

    compiled = SurfaceSeedCompiler().compile(frame=frame, surface_kind="presence_maintenance")

    assert compiled.selected is True
    assert compiled.public_seed == "a small public-safe thought about the mouth gate"
    assert compiled.root_source == "thought_stream"
    assert compiled.impulse is not None
    assert compiled.impulse.kind == "inner_whim"


def test_private_mind_raw_judgment_is_not_compiled() -> None:
    digest = {
        "menu": {
            "inner_judgment": {"dominant_judgment": "raw private judgment"},
            "temporary_thoughts": [{"claim": "ThoughtFragment should stay private"}],
        }
    }

    compiled = SurfaceSeedCompiler().compile(private_mind_digest=digest, private_mind_thought_pressure=0.90)

    assert compiled.selected is False
    assert compiled.impulse is None


def test_surface_valve_approved_private_impulse_can_be_compiled() -> None:
    private_impulse = SurfaceImpulse(
        kind="private_mind_surface",
        source="private_mind",
        confidence=0.72,
        pressure=0.70,
        score=0.71,
        topic_seed="public-safe architecture concern",
        evidence=("dossier.user.current",),
        missing_evidence_ids=False,
        needs_external_evidence=False,
        should_surface=True,
        raw={"metadata": {"public_anchor_count": 1, "has_public_anchor": True}},
    )

    compiled = SurfaceSeedCompiler().compile(extra_impulses=(private_impulse,))

    assert compiled.selected is True
    assert compiled.root_source == "private_mind_surface"
    assert compiled.impulse is not None
    assert compiled.impulse.topic_seed == "public-safe architecture concern"


def test_api_invalid_json_private_bias_does_not_compile() -> None:
    bias = {"direct": {"confidence": 0.90, "value": {"preference": "say the quiet concern"}}}
    digest = {"menu": {"debug_api": {"last_error": "invalid_json"}}}

    compiled = SurfaceSeedCompiler().compile(
        private_mind_digest=digest,
        private_mind_speech_bias=bias,
        private_mind_thought_pressure=0.80,
    )

    assert compiled.selected is False


def test_timer_only_reengagement_does_not_create_speech_seed() -> None:
    cue = SimpleNamespace(confidence=0.50, evidence=("idle_seconds=120.0",))
    snapshot = SimpleNamespace(vision_facts=(), recent_events=())
    timer_impulse = {"kind": "re_engagement", "topic_seed": "idle=120s"}

    compiled = SurfaceSeedCompiler().compile(
        snapshot=snapshot,
        presence_cue=cue,
        surface_kind="re_engagement",
        extra_impulses=(timer_impulse,),
    )

    assert compiled.selected is False
    assert compiled.debug["reason"] in {"no_public_anchor", "timer_only"}
