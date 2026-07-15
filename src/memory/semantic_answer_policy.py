from __future__ import annotations

"""
semantic_answer_policy.py
=========================

Policy surface câu trả lời từ SemanticClaim.

Nó không search text. Nó nhận query intent + claim đã entail đúng rồi mới viết câu.
Nếu không có claim exact, nó phải nói không có bằng chứng, thay vì lôi claim liên quan ra đóng thế.
Đóng thế ký ức là trò rất tiện, cũng là cách memory trở thành máy bịa có archive.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable

try:
    from .claim_entailment import ClaimEntailmentEngine, semantic_claim_from_memory_item
    from .query_intent import SemanticQueryIntent, compile_semantic_query
    from .semantic_claim import SemanticClaim
except Exception:  # pragma: no cover
    from claim_entailment import ClaimEntailmentEngine, semantic_claim_from_memory_item  # type: ignore
    from query_intent import SemanticQueryIntent, compile_semantic_query  # type: ignore
    from semantic_claim import SemanticClaim  # type: ignore


@dataclass(frozen=True, slots=True)
class SemanticAnswer:
    found: bool
    text: str
    confidence: float = 0.0
    source: str = "semantic_claim_entailment"
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    used_claim_id: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


class SemanticAnswerPolicy:
    """Chọn claim exact và format câu trả lời ngắn, grounded."""

    def __init__(self) -> None:
        self.entailment = ClaimEntailmentEngine()

    def answer(self, query: str | SemanticQueryIntent, memory_items: Iterable[Any]) -> SemanticAnswer:
        intent = compile_semantic_query(query, allow_fallback=True) if isinstance(query, str) else query
        if not intent.is_known:
            return SemanticAnswer(False, "Tôi chưa xác định được bạn đang hỏi loại ký ức nào.", 0.0, warnings=("unknown_query_intent",))

        claims: list[SemanticClaim] = []
        for item in memory_items:
            claim = semantic_claim_from_memory_item(item)
            if claim is not None:
                claims.append(claim)

        ranked = self.entailment.rank(claims, intent)
        exact = [(claim, decision) for claim, decision in ranked if decision.can_answer]
        if not exact:
            return SemanticAnswer(
                False,
                self._missing_text(intent),
                0.0,
                evidence_ids=(),
                warnings=("no_exact_entailing_claim",),
            )

        claim, decision = exact[0]
        return SemanticAnswer(
            True,
            self._format(intent, claim),
            confidence=decision.score,
            evidence_ids=claim.evidence_ids,
            used_claim_id=claim.claim_id,
            warnings=decision.warnings,
        )

    def _missing_text(self, intent: SemanticQueryIntent) -> str:
        if intent.requires_freshness:
            return "Tôi không có bằng chứng hiện tại đủ mới để trả lời câu đó."
        if intent.answer_target == "user_nickname":
            return "Tôi chưa có claim nào nói rõ biệt danh của bạn."
        if intent.answer_target == "user_hometown":
            return "Tôi chưa có claim nào nói rõ quê của bạn."
        if intent.answer_target == "user_living_location":
            return "Tôi chưa có claim nào nói rõ nơi bạn đang sống."
        if intent.answer_target == "user_location_preference":
            return "Tôi chưa có claim nào nói rõ địa điểm bạn thích."
        return "Tôi chưa có ký ức đủ chắc để trả lời câu đó."

    def _format(self, intent: SemanticQueryIntent, claim: SemanticClaim) -> str:
        obj = claim.object_text
        if intent.answer_target == "user_name":
            return f"Tên bạn là {obj}."
        if intent.answer_target == "user_nickname":
            return f"Biệt danh của bạn là {obj}."
        if intent.answer_target == "user_birth_month":
            return f"bạn sinh vào tháng {obj}."
        if intent.answer_target == "user_birth_year":
            return f"bạn sinh năm {obj}."
        if intent.answer_target == "user_current_location":
            return f"Theo ký ức hiện tại tôi có, bạn đang ở {obj}."
        if intent.answer_target == "user_living_location":
            return f"Theo những gì bạn đã nói, bạn đang sống ở {obj}."
        if intent.answer_target == "user_hometown":
            return f"Quê của bạn là {obj}."
        if intent.answer_target == "user_location_preference":
            if claim.assertion == "denied":
                return f"bạn từng nói không thích {obj}."
            return f"bạn từng nói thích {obj}."
        if intent.answer_target == "user_response_style":
            return f"bạn có preference về cách tôi trả lời: {obj}"
        return f"Tôi nhớ: {obj}"


__all__ = ["SemanticAnswer", "SemanticAnswerPolicy"]
