from __future__ import annotations

"""
claim_consolidator.py
=====================

Công cụ merge/contradiction cho SemanticClaim.

Đây chưa phải dream-consolidation hoành tráng. Nó chỉ làm phần tối thiểu:
- cùng subject + predicate thì có thể merge;
- cùng predicate nhưng object khác thì đánh dấu contradiction nếu ontology nói mâu thuẫn;
- preference/location không merge sang hometown/current_location.

Một cái chổi nhỏ. Không phải thần kinh nhân tạo, nhưng ít nhất nó quét đúng phòng.
"""

from dataclasses import dataclass, field
from typing import Iterable

try:
    from .semantic_claim import SemanticClaim
    from .predicate_ontology import contradicts
except Exception:  # pragma: no cover
    from semantic_claim import SemanticClaim  # type: ignore
    from predicate_ontology import contradicts  # type: ignore


@dataclass(frozen=True, slots=True)
class ClaimMergeDecision:
    should_merge: bool
    contradiction: bool = False
    reason: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


class ClaimConsolidator:
    """Logic merge claim độc lập với store JSON."""

    def can_merge(self, old: SemanticClaim, new: SemanticClaim) -> ClaimMergeDecision:
        if old.subject != new.subject:
            return ClaimMergeDecision(False, reason="subject_mismatch")
        if old.predicate != new.predicate:
            return ClaimMergeDecision(False, reason="predicate_mismatch")
        if contradicts(old, new):
            return ClaimMergeDecision(False, contradiction=True, reason="same_predicate_value_conflict")
        if _norm(old.object_text) == _norm(new.object_text):
            return ClaimMergeDecision(True, reason="same_claim_value")
        # Cùng predicate nhưng object khác, không merge mù. Ví dụ user có thể thích nhiều nơi.
        if old.modality == "preference" and new.modality == "preference":
            return ClaimMergeDecision(False, reason="multi_value_preference_keep_separate")
        return ClaimMergeDecision(False, reason="different_value")

    def find_merge_target(self, items: Iterable[SemanticClaim], new: SemanticClaim) -> SemanticClaim | None:
        candidates: list[SemanticClaim] = []
        for old in items:
            decision = self.can_merge(old, new)
            if decision.should_merge:
                candidates.append(old)
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.confidence)


def _norm(text: str) -> str:
    try:
        from .query_intent import normalize_vi
    except Exception:  # pragma: no cover
        from query_intent import normalize_vi  # type: ignore
    return normalize_vi(text)


__all__ = ["ClaimMergeDecision", "ClaimConsolidator"]
