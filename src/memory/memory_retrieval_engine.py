from __future__ import annotations

"""
memory_retrieval_engine.py
==========================

Orchestrator cho memory retrieval v2.

Nó không ghi memory.
Nó không render prompt.
Nó chỉ:
1. Nhận MemoryCue.
2. Hỏi từng layer adapter lấy MemoryCandidate.
3. Chấm bằng MemoryScorer.
4. Biến thành MemoryActivation.

MemoryCognitionCore gọi engine này thay cho _with_resonance_fields().
Cuối cùng cũng thôi đo resonance bằng token overlap như Ctrl+F có ego.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

try:
    from .memory_cue import MemoryCue
    from .memory_candidate import LegacyLayerAdapter, MemoryCandidate
    from .memory_scoring import MemoryScorer, DEFAULT_LAYER_PROFILES
    from .memory_activation import MemoryActivationBuilder, MemoryRetrievalResult, ScoredMemoryCandidate
except Exception:  # pragma: no cover
    from memory_cue import MemoryCue
    from memory_candidate import LegacyLayerAdapter, MemoryCandidate
    from memory_scoring import MemoryScorer, DEFAULT_LAYER_PROFILES
    from memory_activation import MemoryActivationBuilder, MemoryRetrievalResult, ScoredMemoryCandidate


@dataclass(slots=True)
class MemoryStores:
    semantic: Any = None
    relational: Any = None
    episodic: Any = None
    procedural: Any = None
    affective_residue: Any = None
    repair: Any = None

    def as_layer_map(self) -> dict[str, Any]:
        return {
            "semantic": self.semantic,
            "relational": self.relational,
            "episodic": self.episodic,
            "procedural": self.procedural,
            "affective_residue": self.affective_residue,
            "repair": self.repair,
        }


class MemoryRetrievalEngine:
    def __init__(self, stores: MemoryStores, *, scorer: MemoryScorer | None = None, activation_builder: MemoryActivationBuilder | None = None):
        self.stores = stores
        self.scorer = scorer or MemoryScorer()
        self.activation_builder = activation_builder or MemoryActivationBuilder()
        self.adapters = {
            layer: LegacyLayerAdapter(layer=layer, store=store)
            for layer, store in stores.as_layer_map().items()
            if store is not None
        }

    def retrieve(self, cue: MemoryCue, *, quotas: Mapping[str, int] | None = None, max_activations: int = 10) -> MemoryRetrievalResult:
        quotas = dict(quotas or {})
        scored: list[ScoredMemoryCandidate] = []
        debug_notes: list[str] = []

        for layer, adapter in self.adapters.items():
            if not cue.layer_allowed(layer):
                debug_notes.append(f"layer_forbidden:{layer}")
                continue

            limit = max(1, int(quotas.get(layer, 4) or 4)) * 4
            try:
                candidates = adapter.retrieve_candidates(cue, limit=limit)
            except Exception as exc:
                debug_notes.append(f"adapter_error:{layer}:{type(exc).__name__}")
                continue

            for candidate in candidates:
                score = self.scorer.score(cue, candidate)
                if score.total > 0.0:
                    scored.append(ScoredMemoryCandidate(candidate=candidate, score=score))

        result = self.activation_builder.build(scored, max_activations=max_activations)
        if debug_notes:
            result.debug_notes = tuple((*result.debug_notes, *debug_notes))
        return result
