# -*- coding: utf-8 -*-
"""
cortex/private_mind/mini_evaluators.py

4 mini-evaluator gọi API. Không có rule fallback — nếu API fail thì tick đó
không có fragment từ evaluator đó. Pool API dự phòng lo việc resilience.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol
from concurrent.futures import ThreadPoolExecutor, as_completed

from .contracts import (
    EvidenceDossier,
    ThoughtFragment,
    clamp01,
    compact_text,
)


class MiniEvaluatorModelAdapter(Protocol):
    def evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier) -> Mapping[str, Any] | None:
        ...


def _evidence_ids(dossier: EvidenceDossier, *extra: str) -> tuple[str, ...]:
    ids = list(dossier.evidence_ids[:16])
    for e in extra:
        if e and e not in ids:
            ids.append(e)
    return tuple(ids[:20])


def _from_model(adapter: Any, evaluator_name: str, dossier: EvidenceDossier) -> ThoughtFragment | None:
    """Gọi model adapter, trả None nếu fail hoặc result yếu."""
    fn = getattr(adapter, "evaluate_fragment", None)
    if not callable(fn):
        return None
    try:
        raw = fn(evaluator_name, dossier)
    except Exception:
        return None
    if not isinstance(raw, Mapping):
        return None
    claim = compact_text(str(raw.get("claim") or ""), 480)
    if not claim:
        return None
    confidence = clamp01(raw.get("confidence", 0.0))
    pressure = clamp01(raw.get("pressure", 0.0))
    if confidence < 0.15 and pressure < 0.15:
        return None
    from .contracts import RankedHypothesis, ThoughtFragment
    hypotheses = tuple(
        RankedHypothesis.from_mapping(h)
        for h in (raw.get("hypotheses") or [])
        if isinstance(h, Mapping)
    )
    theme = str(raw.get("theme") or raw.get("metadata", {}).get("theme") or "")
    return ThoughtFragment(
        source=evaluator_name,
        claim=claim,
        confidence=confidence,
        pressure=pressure,
        evidence_ids=_evidence_ids(dossier),
        suggested_question=compact_text(str(raw.get("suggested_question") or ""), 200),
        hypotheses=hypotheses,
        metadata={"theme": theme} if theme else {},
    )


class BaseMiniEvaluator:
    def __init__(self, name: str, *, model_adapter: Any = None) -> None:
        self.name = name
        self.model_adapter = model_adapter

    def evaluate(self, dossier: EvidenceDossier) -> ThoughtFragment | None:
        return _from_model(self.model_adapter, self.name, dossier)


class IntentEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("intent_evaluator", model_adapter=model_adapter)


class MemoryResonanceEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("memory_resonance_evaluator", model_adapter=model_adapter)


class RiskAndPermissionEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("risk_and_permission_evaluator", model_adapter=model_adapter)


class FutureBiasEvaluator(BaseMiniEvaluator):
    def __init__(self, *, model_adapter: Any = None) -> None:
        super().__init__("future_bias_evaluator", model_adapter=model_adapter)


class MiniEvaluatorPipeline:
    def __init__(self, *, model_adapter: Any = None, evaluators: Iterable[BaseMiniEvaluator] | None = None) -> None:
        self.model_adapter = model_adapter
        self.evaluators = tuple(
            evaluators
            if evaluators is not None
            else (
                IntentEvaluator(model_adapter=model_adapter),
                MemoryResonanceEvaluator(model_adapter=model_adapter),
                RiskAndPermissionEvaluator(model_adapter=model_adapter),
                FutureBiasEvaluator(model_adapter=model_adapter),
            )
        )

    def evaluate(self, dossier: EvidenceDossier) -> tuple[ThoughtFragment, ...]:
        def _run(evaluator: BaseMiniEvaluator) -> ThoughtFragment | None:
            try:
                return evaluator.evaluate(dossier)
            except Exception:
                return None

        fragments: list[ThoughtFragment] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_run, ev): ev for ev in self.evaluators}
            for future in as_completed(futures):
                result = future.result()
                if result is not None and result.claim and result.score >= 0.24:
                    fragments.append(result)

        return tuple(sorted(fragments, key=lambda f: f.score, reverse=True)[:8])
