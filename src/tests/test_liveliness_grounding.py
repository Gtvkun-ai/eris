from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.surface_seed_compiler import SurfaceSeedCompiler


def _private_life_digest(note: str = "một mảnh đời sống riêng nhỏ") -> dict:
    return {
        "current": {
            "projects": [
                {
                    "id": "proj-1",
                    "last_note": note,
                    "surface_permission": 0.9,
                    "interest": 0.9,
                    "frustration": 0.5,
                }
            ]
        }
    }


def test_fresh_specific_vision_fact_beats_generic_private_life() -> None:
    snapshot = SimpleNamespace(
        vision_facts=("Execution Changes (5 files) - eris - Kiro",),
        recent_events=(),
    )
    cue = SimpleNamespace(confidence=0.5)

    compiled = SurfaceSeedCompiler().compile(
        snapshot=snapshot,
        presence_cue=cue,
        surface_kind="re_engagement",
        private_life_digest=_private_life_digest(),
    )

    assert compiled.selected is True
    assert compiled.root_source == "vision_fact"
    assert compiled.debug["selected_source"] == "vision_fact"


def test_vision_rank_at_least_private_life_rank() -> None:
    compiler = SurfaceSeedCompiler()
    snapshot = SimpleNamespace(
        vision_facts=("Execution Changes (5 files) - eris - Kiro",),
        recent_events=(),
    )
    vision = compiler._from_vision(snapshot=snapshot, presence_cue=SimpleNamespace(confidence=0.5))
    private = compiler._from_private_life_digest(_private_life_digest())
    assert vision and private
    assert compiler._rank_key(vision[0]) >= compiler._rank_key(private[0])


def test_vision_confidence_is_bounded() -> None:
    compiler = SurfaceSeedCompiler()
    snapshot = SimpleNamespace(
        vision_facts=("Execution Changes (5 files) - eris - Kiro",),
        recent_events=(),
    )
    cand = compiler._from_vision(snapshot=snapshot, presence_cue=SimpleNamespace(confidence=0.5))[0]
    assert 0.0 <= cand.confidence <= 1.0
    assert cand.confidence >= 0.74  # can compete with generic private_life


def test_short_public_safe_memory_seed_retained() -> None:
    activation = SimpleNamespace(
        may_surface=True,
        text="vision đói lại nữa",  # short, but concrete and public-safe
        evidence_ids=("memory.ev.short",),
        record_id="mem-short",
        layer="semantic",
    )
    resonance = SimpleNamespace(
        score=0.62,
        attention_bias=0.40,
        wording_bias=0.55,
        dominant_layer="semantic",
        activations=(activation,),
    )
    compiled = SurfaceSeedCompiler().compile(
        active_memory_resonance=resonance, surface_kind="re_engagement"
    )
    assert compiled.selected is True
    assert compiled.root_source == "memory_resonance"


def test_non_public_safe_memory_seed_excluded() -> None:
    activation = SimpleNamespace(
        may_surface=True,
        text="ThoughtFragment raw judgment leaking private mind json",
        evidence_ids=("memory.ev.private",),
        record_id="mem-private",
        layer="semantic",
    )
    resonance = SimpleNamespace(
        score=0.72,
        attention_bias=0.66,
        wording_bias=0.64,
        dominant_layer="semantic",
        activations=(activation,),
    )
    compiled = SurfaceSeedCompiler().compile(
        active_memory_resonance=resonance, surface_kind="re_engagement"
    )
    assert compiled.selected is False


def test_no_specific_vision_fact_yields_no_vision_candidate() -> None:
    compiler = SurfaceSeedCompiler()
    snapshot = SimpleNamespace(
        vision_facts=("focus=unknown intent=unknown",),
        recent_events=(),
    )
    assert compiler._from_vision(snapshot=snapshot, presence_cue=SimpleNamespace(confidence=0.5)) == ()


def test_alternative_impulses_exposed_for_retry() -> None:
    snapshot = SimpleNamespace(
        vision_facts=("Execution Changes (5 files) - eris - Kiro",),
        recent_events=(),
    )
    compiled = SurfaceSeedCompiler().compile(
        snapshot=snapshot,
        presence_cue=SimpleNamespace(confidence=0.5),
        surface_kind="re_engagement",
        private_life_digest=_private_life_digest(),
    )
    # vision selected; private_life should remain as an alternative impulse.
    assert compiled.selected is True
    alt_sources = {imp.root_source for imp in compiled.alternative_impulses}
    assert "private_life" in alt_sources
