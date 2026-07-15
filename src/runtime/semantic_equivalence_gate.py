# -*- coding: utf-8 -*-
"""Cổng tương đương ngữ nghĩa cho Director.

Director được quyền làm câu mượt hơn, không được quyền thay sự thật. Module này
không giả vờ là một mô hình entailment đầy đủ. Nó dùng các ràng buộc cứng
(negation, số liệu, trạng thái action, chủ thể) và một điểm tương đồng nhẹ. Khi
runtime có embedding/entailment backend, caller có thể inject callback để nâng
độ chính xác mà không đổi contract.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable


SimilarityFn = Callable[[str, str], float]


@dataclass(frozen=True, slots=True)
class SemanticGateResult:
    accepted: bool
    score: float
    threshold: float
    reason: str = ""


_NEGATION = {"khong", "chua", "chang", "chẳng", "not", "never", "no"}
_DISPATCH_MARKERS = (
    "da gui yeu cau", "da gui lenh", "da yeu cau", "requested", "dispatched",
)
_OBSERVED_SUCCESS_MARKERS = (
    "da tang", "da giam", "da mo", "da chuyen", "da dua", "da xong",
    "hien da", "thanh cong", "completed", "opened", "changed",
)
_FACTUAL_INTENTS = {
    "factual", "world_knowledge", "memory_answer", "repair", "conversation_repair",
    "capability", "capability_answer", "system_action", "direct_action",
}


def _enabled() -> bool:
    return os.environ.get("ERIS_DIRECTOR_SEMANTIC_GATE", "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _fold(text: str) -> str:
    raw = str(text or "").lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", raw)
    return " ".join(normalized.encode("ascii", "ignore").decode("ascii", "ignore").split())


def _tokens(text: str) -> set[str]:
    stop = {"toi", "ban", "em", "la", "va", "thi", "mot", "cua", "co", "the", "duoc", "cho"}
    return {tok for tok in re.findall(r"[a-z0-9_]{2,}", _fold(text)) if tok not in stop}


def _numbers(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"(?<!\w)-?\d+(?:[.,]\d+)?%?", str(text or "")))


def _has_negation(text: str) -> bool:
    return bool(_NEGATION & set(re.findall(r"[a-z0-9_]+", _fold(text))))


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    folded = _fold(text)
    return any(marker in folded for marker in markers)


class SemanticEquivalenceGate:
    """Kiểm tra candidate có còn cùng nghĩa với draft nguồn hay không."""

    def __init__(self, *, similarity_fn: SimilarityFn | None = None) -> None:
        self.similarity_fn = similarity_fn

    def evaluate(
        self,
        baseline: str,
        candidate: str,
        *,
        intent: str = "",
        user_text: str = "",
    ) -> SemanticGateResult:
        if not _enabled():
            return SemanticGateResult(True, 1.0, 0.0, "gate_disabled")

        base = str(baseline or "").strip()
        cand = str(candidate or "").strip()
        intent_key = str(intent or "").strip().lower()
        strict = intent_key in _FACTUAL_INTENTS or any(
            key in _fold(user_text) for key in ("sua lai", "khong dung", "co lam duoc", "da lam chua")
        )
        threshold = 0.84 if self.similarity_fn is not None and strict else 0.72 if strict else 0.58

        if base == cand:
            return SemanticGateResult(True, 1.0, threshold, "exact")
        if not base or not cand:
            return SemanticGateResult(False, 0.0, threshold, "empty_mismatch")

        # Không cho hậu kỳ đổi "chưa/không" thành khẳng định hoặc ngược lại.
        if _has_negation(base) != _has_negation(cand):
            return SemanticGateResult(False, 0.0, threshold, "negation_flip")

        # Số liệu là bằng chứng, không phải đồ trang trí cho Director thay tùy hứng.
        base_numbers = _numbers(base)
        cand_numbers = _numbers(cand)
        if strict and base_numbers and cand_numbers != base_numbers:
            return SemanticGateResult(False, 0.0, threshold, "numeric_claim_changed")

        # dispatched chỉ chứng minh lệnh đã gửi. Candidate không được tự phong nó
        # thành observed_success, dù câu nghe tự tin hơn hẳn. Con người đã làm đủ trò đó rồi.
        if _contains_any(base, _DISPATCH_MARKERS) and _contains_any(cand, _OBSERVED_SUCCESS_MARKERS):
            return SemanticGateResult(False, 0.0, threshold, "dispatch_escalated_to_success")

        base_tokens = _tokens(base)
        cand_tokens = _tokens(cand)
        containment = len(base_tokens & cand_tokens) / max(1, min(len(base_tokens), len(cand_tokens)))
        sequence = SequenceMatcher(None, _fold(base), _fold(cand)).ratio()
        lexical_score = 0.62 * containment + 0.38 * sequence

        if self.similarity_fn is not None:
            try:
                semantic_score = max(0.0, min(1.0, float(self.similarity_fn(base, cand))))
            except Exception:
                semantic_score = lexical_score
            score = 0.72 * semantic_score + 0.28 * lexical_score
        else:
            score = lexical_score

        if score < threshold:
            return SemanticGateResult(False, score, threshold, "semantic_similarity_below_threshold")
        return SemanticGateResult(True, score, threshold, "equivalent")


__all__ = ["SemanticEquivalenceGate", "SemanticGateResult"]
