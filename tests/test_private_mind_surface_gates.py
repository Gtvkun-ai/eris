from __future__ import annotations

from types import SimpleNamespace

from cortex.private_mind.contracts import InternalJudgment, SurfaceCandidate, ThoughtFragment
from cortex.private_mind.evidence_dossier import EvidenceDossierBuilder
from cortex.private_mind.inner_synthesizer import GemmaInnerSynthesizer
from cortex.private_mind.surface_valve import SurfaceValve
from cortex.surface_arbiter import SurfaceArbiter


def test_evidence_dossier_carries_novelty_repetition_and_strength():
    observer = SimpleNamespace(
        novelty=0.10,
        repetition=0.90,
        possible_error=0.0,
        user_presence=0.0,
        focus_kind="idle",
        recommended_action="observe_only",
    )

    dossier = EvidenceDossierBuilder().build(observer_frame=observer)

    assert dossier.metadata["novelty"] == 0.10
    assert dossier.metadata["repetition"] == 0.90
    assert dossier.metadata["has_recent_user_turn"] is False
    assert dossier.metadata["evidence_strength"] < 0.10


def test_fallback_private_mind_candidate_defaults_to_body_only_without_anchor():
    candidate = SurfaceCandidate(
        kind="private_mind_surface",
        topic_seed="No clear external evidence; keep private concern alive.",
        usefulness=0.70,
        confidence=0.72,
        interrupt_cost=0.20,
        evidence_ids=("dossier.runtime.state",),
        metadata={
            "source": "fallback",
            "novelty": 0.10,
            "repetition": 0.20,
            "public_anchor_count": 0,
            "evidence_strength": 0.08,
            "semantic_family": "private_mind_continuity_filler",
        },
    )
    judgment = InternalJudgment(
        dominant_judgment="private concern should persist",
        surface_candidate=candidate,
        confidence=0.72,
        pressure=0.70,
        source="deterministic_inner_synthesizer",
    )

    filtered = SurfaceValve().filter(judgment)
    impulse = SurfaceValve().to_surface_impulse(filtered)

    assert filtered is not None
    assert filtered.channel == "body_only"
    assert impulse is not None
    assert impulse.missing_evidence_ids is True
    assert impulse.needs_external_evidence is True
    assert impulse.family == "private_mind_continuity_filler"


def test_api_invalid_json_blocks_private_mind_surface():
    candidate = SurfaceCandidate(
        kind="private_mind_surface",
        topic_seed="Mạch này vẫn giữ chỗ.",
        usefulness=0.80,
        confidence=0.80,
        interrupt_cost=0.20,
        evidence_ids=("dossier.user.current",),
        metadata={
            "source": "fallback",
            "api_invalid_json": True,
            "public_anchor_count": 1,
            "evidence_strength": 0.80,
            "novelty": 0.80,
            "repetition": 0.0,
        },
    )
    judgment = InternalJudgment(
        dominant_judgment="api degraded",
        surface_candidate=candidate,
        confidence=0.80,
        pressure=0.80,
    )

    assert SurfaceValve().filter(judgment) is None


def test_private_mind_surface_without_anchor_loses_speech_slot_to_body_only():
    arbiter = SurfaceArbiter(llm_micro_gen=lambda **_: ("Mạch này vẫn giữ chỗ.", "mock"))
    candidate = SurfaceCandidate(
        kind="private_mind_surface",
        topic_seed="No clear external evidence; keep private concern alive.",
        usefulness=0.70,
        confidence=0.72,
        interrupt_cost=0.20,
        evidence_ids=("dossier.runtime.state",),
        metadata={"source": "fallback", "public_anchor_count": 0, "semantic_family": "private_mind_continuity_filler"},
    )
    impulse = SurfaceValve().to_surface_impulse(candidate)

    decision = arbiter.arbitrate(extra_impulses=(impulse,), silent_cycles=0)

    assert decision.should_speak is False
    assert decision.body_only is True
    assert decision.reason in {"forced_body_only:needs_external_evidence_missing", "private_mind_missing_public_anchor"}


def test_deterministic_synthesizer_marks_fallback_candidate_with_metrics():
    observer = SimpleNamespace(novelty=0.12, repetition=0.88, possible_error=0.0, focus_kind="idle")
    dossier = EvidenceDossierBuilder().build(observer_frame=observer)
    fragment = ThoughtFragment(
        source="risk_and_permission_evaluator",
        claim="No clear external evidence; keep private concern alive.",
        confidence=0.72,
        pressure=0.80,
        evidence_ids=("dossier.runtime.state",),
    )

    judgment = GemmaInnerSynthesizer().synthesize(dossier=dossier, fragments=(fragment,))

    assert judgment is not None
    assert judgment.surface_candidate is not None
    assert judgment.surface_candidate.metadata["source"] == "fallback"
    assert judgment.surface_candidate.metadata["repetition"] == 0.88
