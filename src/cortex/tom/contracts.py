# -*- coding: utf-8 -*-
"""contracts.py — MentalStateInference, ToM dataclasses, lỗi contract ToM.

Các kiểu dữ liệu riêng của tầng Theory of Mind (Phase 2). Phụ thuộc một chiều
``cortex.tom.contracts`` → ``cortex.meaning.contracts`` để dùng lại helper
``clamp01`` (nguồn DUY NHẤT) thay vì tự định nghĩa — giữ một nguồn kẹp [0,1].

``ToMOrderingViolation`` đặt tại đây (không ở ``cortex.meaning.contracts``) để
ràng buộc ToM-after-Meaning (R7) sống đúng trong package ``tom``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..meaning.contracts import clamp01


__all__ = [
    "ToMOrderingViolation",
    "MentalStateInference",
    "ToMHistory",
]


# ---------------------------------------------------------------------------
# Lỗi contract ToM
# ---------------------------------------------------------------------------
class ToMOrderingViolation(RuntimeError):
    """R7.2, R13.3 — ToM chạy trước khi Meaning/Pragmatic sinh output cho frame.

    Mang theo ``missing_stage`` (stage tiền đề còn thiếu) và ``frame_id`` hiện
    tại để debug ghi rõ vi phạm thứ tự pipeline.
    """

    def __init__(self, missing_stage: str, frame_id: str | None) -> None:
        self.missing_stage = missing_stage
        self.frame_id = frame_id
        super().__init__(
            f"Theory of Mind cannot run for frame '{frame_id}': "
            f"required stage '{missing_stage}' has not produced output yet"
        )


# ---------------------------------------------------------------------------
# Theory of Mind dataclasses
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class MentalStateInference:
    inference_id: str
    category: str                   # Taxonomy.MENTAL_STATE
    summary: str
    confidence: float
    overread_risk: float
    supporting_meaning_ids: list[str]   # R7.6
    unsupported: bool = False           # R7.7
    counterfactual_reason: str = ""     # R7.4

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)
        self.overread_risk = clamp01(self.overread_risk)


@dataclass(slots=True)
class ToMHistory:
    items: list[str]
    available: bool = True              # R7.8
