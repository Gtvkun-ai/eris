from __future__ import annotations

"""
memory_activation.py
====================

Biến scored candidates thành MemoryActivation.

Activation không phải "hãy nói ký ức này ra".
Nó là áp lực có route:
- attention
- appraisal
- wording
- silence
- context

Surface policy quyết định có được đưa ra lời nói không.
Affective residue thường chỉ đi vào appraisal/silence, không được biến thành
claim công khai kiểu "tôi buồn". Cảm ơn, cuối cùng cũng có chút phẩm giá.
"""

from dataclasses import dataclass, field
from typing import Any

try:
    from .memory_record import compact_text, clamp01
    from .memory_candidate import MemoryCandidate
    from .memory_scoring import MemoryScore, LayerProfile, DEFAULT_LAYER_PROFILES
except Exception:  # pragma: no cover
    from memory_record import compact_text, clamp01
    from memory_candidate import MemoryCandidate
    from memory_scoring import MemoryScore, LayerProfile, DEFAULT_LAYER_PROFILES


@dataclass(slots=True)
class MemoryActivation:
    record_id: str
    layer: str
    text: str

    score: float
    relevance: float
    resonance: float

    surface_policy: str
    bias_routes: tuple[str, ...]
    matched_terms: tuple[str, ...] = ()
    matched_anchors: tuple[str, ...] = ()

    evidence_ids: tuple[str, ...] = ()
    score_breakdown: dict[str, Any] = field(default_factory=dict)

    may_surface: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "layer": self.layer,
            "text": self.text,
            "score": round(float(self.score), 3),
            "relevance": round(float(self.relevance), 3),
            "resonance": round(float(self.resonance), 3),
            "surface_policy": self.surface_policy,
            "bias_routes": list(self.bias_routes),
            "matched_terms": list(self.matched_terms),
            "matched_anchors": list(self.matched_anchors),
            "evidence_ids": list(self.evidence_ids),
            "score_breakdown": dict(self.score_breakdown),
            "may_surface": bool(self.may_surface),
            "reason": self.reason,
        }

    def to_attention_line(self) -> str:
        return compact_text(
            f"active_memory_resonance/{self.layer} score={self.score:.2f} "
            f"policy={self.surface_policy}: {self.text}",
            limit=280,
        )


@dataclass(slots=True)
class ScoredMemoryCandidate:
    candidate: MemoryCandidate
    score: MemoryScore


@dataclass(slots=True)
class MemoryRetrievalResult:
    activations: tuple[MemoryActivation, ...] = ()
    scored_candidates: tuple[ScoredMemoryCandidate, ...] = ()
    attention_bias: float = 0.0
    appraisal_bias: float = 0.0
    wording_bias: float = 0.0
    silence_bias: float = 0.0
    dominant_layer: str = ""
    score: float = 0.0
    debug_notes: tuple[str, ...] = ()


class MemoryActivationBuilder:
    def __init__(self, profiles: dict[str, LayerProfile] | None = None):
        self.profiles = profiles or DEFAULT_LAYER_PROFILES

    def build(self, scored: list[ScoredMemoryCandidate], *, max_activations: int = 10) -> MemoryRetrievalResult:
        usable = [item for item in scored if item.score.total > 0.0]
        usable.sort(key=lambda item: item.score.total, reverse=True)

        activations: list[MemoryActivation] = []
        debug_notes: list[str] = []

        for item in usable[:max_activations]:
            record = item.candidate.record
            score = item.score
            profile = self.profiles.get(record.layer)
            routes = profile.bias_routes if profile else ("context",)
            surface_policy = record.surface_policy or (profile.default_surface_policy if profile else "silent_bias")
            may_surface = bool(profile.can_surface if profile else False) and score.surfaceability >= 0.18 and score.permission >= 0.5

            activation = MemoryActivation(
                record_id=record.id,
                layer=record.layer,
                text=record.recall_line(limit=260),
                score=score.total,
                relevance=score.relevance,
                resonance=score.resonance,
                surface_policy=surface_policy,
                bias_routes=routes,
                matched_terms=score.matched_terms,
                matched_anchors=score.matched_anchors,
                evidence_ids=record.evidence_ids,
                score_breakdown=score.to_dict(),
                may_surface=may_surface,
                reason=score.reason,
            )
            activations.append(activation)

        attention_bias = self._route_bias(activations, "attention")
        appraisal_bias = self._route_bias(activations, "appraisal")
        wording_bias = self._route_bias(activations, "wording")
        silence_bias = clamp01(self._route_bias(activations, "silence") * 0.75)
        dominant_layer = activations[0].layer if activations else ""
        total_score = clamp01(sum(item.score for item in activations[:3]) / max(1, min(3, len(activations))) if activations else 0.0)

        return MemoryRetrievalResult(
            activations=tuple(activations),
            scored_candidates=tuple(usable[:max_activations]),
            attention_bias=attention_bias,
            appraisal_bias=appraisal_bias,
            wording_bias=wording_bias,
            silence_bias=silence_bias,
            dominant_layer=dominant_layer,
            score=total_score,
            debug_notes=tuple(debug_notes),
        )

    def _route_bias(self, activations: list[MemoryActivation], route: str) -> float:
        if not activations:
            return 0.0
        values = [item.score for item in activations if route in set(item.bias_routes)]
        return clamp01(max(values) if values else 0.0)
