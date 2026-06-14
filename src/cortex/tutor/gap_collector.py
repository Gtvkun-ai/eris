# -*- coding: utf-8 -*-
"""
cortex/tutor/gap_collector.py
=============================

Dẫn xuất Knowledge_Gap từ vi phạm kỳ vọng (SituationModel) và observer 'unknown',
dedupe theo ngữ nghĩa, giới hạn hàng đợi.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .config import TutorConfig
from .contracts import KnowledgeGap


# Import mềm hạ tầng tương đồng — fallback token-overlap nếu thiếu.
try:  # pragma: no cover
    from cortex.event_semantics import _cosine_similarity, _normalize_vector  # type: ignore
except Exception:  # pragma: no cover
    def _normalize_vector(vector):  # type: ignore
        return tuple(vector or ())

    def _cosine_similarity(left, right):  # type: ignore
        return -1.0

try:  # pragma: no cover
    from cortex.attention_salience import tokenize  # type: ignore
except Exception:  # pragma: no cover
    def tokenize(text: Any):  # type: ignore
        return set(str(text or "").lower().split())


EmbedFn = Callable[[str], "tuple[float, ...]"]


class GapCollector:
    """Thu thập, dedupe và giới hạn hàng đợi Knowledge_Gap."""

    def __init__(self, config: Optional[TutorConfig] = None, *, embed_fn: Optional[EmbedFn] = None) -> None:
        self.config = (config or TutorConfig()).normalized()
        self._embed_fn = embed_fn
        self._gaps: list[KnowledgeGap] = []

    # ------------------------------------------------------------------
    # Dẫn xuất
    # ------------------------------------------------------------------

    def collect_from_violation(self, violation: Any, *, stake_relevance: float, now: float) -> Optional[KnowledgeGap]:
        """Từ một ExpectationViolation của SituationModel."""

        expected = str(getattr(violation, "expected", "") or "").strip()
        observed = str(getattr(violation, "observed", "") or "").strip()
        pe = float(getattr(violation, "prediction_error", 0.0) or 0.0)
        if not expected and not observed:
            return None
        description = f"Tôi tưởng: {expected or '(không rõ)'} — nhưng thực tế: {observed or '(không rõ)'}"
        context = f"expected={expected} | observed={observed}"
        gap = KnowledgeGap(
            description=description,
            context=context,
            source="expectation_violation",
            stake_relevance=stake_relevance,
            prediction_error=pe,
            created_ts=now,
            updated_ts=now,
            embedding=self._embed(description),
        )
        return gap

    def collect_from_observer(self, frame: Any, *, now: float) -> Optional[KnowledgeGap]:
        """Từ một ObserverFrame có focus/activity 'unknown' và ambiguity cao."""

        focus = str(getattr(frame, "focus_kind", "") or "")
        activity = str(getattr(frame, "activity_intent", "") or "")
        ambiguity = float(getattr(frame, "ambiguity", 0.0) or 0.0)
        if focus != "unknown" and activity != "unknown":
            return None
        if ambiguity < self.config.observer_ambiguity_threshold:
            return None
        description = "Tôi không phân loại được Ngài đang làm gì trên màn hình"
        evidence = list(getattr(frame, "evidence", None) or [])
        context = f"focus={focus} | activity={activity} | ambiguity={ambiguity:.2f} | evidence={evidence[:4]}"
        gap = KnowledgeGap(
            description=description,
            context=context,
            source="observer_unknown",
            stake_relevance=clamp01_local(getattr(frame, "salience", 0.0)),
            prediction_error=clamp01_local(ambiguity),
            created_ts=now,
            updated_ts=now,
            embedding=self._embed(description + " " + context),
        )
        return gap

    # ------------------------------------------------------------------
    # Hàng đợi
    # ------------------------------------------------------------------

    def push(self, gap: Optional[KnowledgeGap]) -> bool:
        """Thêm gap với dedupe ngữ nghĩa + giới hạn queue. Trả True nếu thêm mới."""

        if gap is None:
            return False
        existing = self._find_duplicate(gap)
        if existing is not None:
            existing.updated_ts = max(existing.updated_ts, gap.updated_ts)
            existing.stake_relevance = max(existing.stake_relevance, gap.stake_relevance)
            existing.prediction_error = max(existing.prediction_error, gap.prediction_error)
            return False
        self._gaps.append(gap)
        self._enforce_cap()
        return True

    def drain_candidates(self) -> list[KnowledgeGap]:
        """Các gap chưa giải quyết, cho gate đọc."""

        return [g for g in self._gaps if not g.resolved]

    def resolve(self, gap: KnowledgeGap) -> None:
        for g in self._gaps:
            if g.gap_id == gap.gap_id:
                g.resolved = True
        self._gaps = [g for g in self._gaps if not g.resolved]

    def serialize(self) -> dict[str, Any]:
        return {
            "queue_size": len(self._gaps),
            "unresolved": len(self.drain_candidates()),
            "gaps": [g.to_dict() for g in self._gaps[-20:]],
        }

    @property
    def size(self) -> int:
        return len(self._gaps)

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> tuple[float, ...]:
        if self._embed_fn is None:
            return ()
        try:
            vec = self._embed_fn(text)
            return tuple(vec or ())
        except Exception:
            return ()

    def _find_duplicate(self, gap: KnowledgeGap) -> Optional[KnowledgeGap]:
        for existing in self._gaps:
            if existing.resolved:
                continue
            if existing.gap_id == gap.gap_id:
                return existing
            if self._similar(existing, gap):
                return existing
        return None

    def _similar(self, a: KnowledgeGap, b: KnowledgeGap) -> bool:
        if a.embedding and b.embedding:
            va = _normalize_vector(tuple(a.embedding))
            vb = _normalize_vector(tuple(b.embedding))
            if va and vb and len(va) == len(vb):
                sim = _cosine_similarity(va, vb)
                if sim >= self.config.dedupe_similarity:
                    return True
                return False
        # Fallback token-overlap
        ta = tokenize(a.description)
        tb = tokenize(b.description)
        if not ta or not tb:
            return False
        overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
        return overlap >= self.config.dedupe_similarity

    def _enforce_cap(self) -> None:
        cap = self.config.max_gap_queue
        if len(self._gaps) <= cap:
            return
        # Bỏ phần tử cũ nhất có stake_relevance thấp nhất cho tới khi vừa cap.
        while len(self._gaps) > cap:
            victim_idx = min(
                range(len(self._gaps)),
                key=lambda i: (self._gaps[i].stake_relevance, self._gaps[i].updated_ts),
            )
            self._gaps.pop(victim_idx)


def clamp01_local(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if n != n:
        return 0.0
    return max(0.0, min(1.0, n))


__all__ = ["GapCollector"]
