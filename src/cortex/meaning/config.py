# -*- coding: utf-8 -*-
"""config.py — ``Phase2Config`` (nguồn duy nhất của mọi threshold) và ``StageLedger``.

Module này giữ phần "điều khiển" của tầng meaning (Phase 2) tách khỏi
``contracts.py`` (chỉ chứa data models thuần):

- ``Phase2Config``: **nguồn sự thật DUY NHẤT** của mọi ngưỡng dùng xuyên suốt
  pipeline. Mọi stage và mọi test phải đọc giá trị từ đây thay vì hard-code,
  để runtime và test luôn đồng bộ (design "Configuration defaults (single
  source)").
- ``StageLedger``: substrate cho ràng buộc **ToM-after-Meaning** (R7.2). Ghi
  nhận stage nào đã sinh đầu ra cho ``frame_id`` nào; ``TheoryOfMindCore`` tra
  ledger trước khi chạy.

Module KHÔNG import bất kỳ symbol nào của ``cortex.tom`` hay kênh Raw_World.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Phase2Config",
    "StageLedger",
]


# ---------------------------------------------------------------------------
# Phase2Config — nguồn DUY NHẤT của mọi threshold
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Phase2Config:
    """Tập trung mọi ngưỡng của pipeline Phase 2 vào một nơi.

    Giá trị mặc định lấy từ design "Configuration defaults (single source)".
    Truyền instance này xuống từng stage để runtime và property tests dùng
    chung một bộ ngưỡng (tránh lệch hằng số rải rác).
    """

    # MeaningHypothesisEngine
    max_hypotheses: int = 4
    ambiguity_margin: float = 0.08
    meaning_low_conf: float = 0.2

    # WorldInterpreter
    interpreter_low_conf: float = 0.5

    # OverreadBrake
    overread_reduction_threshold: float = 0.70
    overread_suppression_threshold: float = 0.90
    reduced_conf_cap: float = 0.50
    min_evidence_count: int = 2

    # SurfaceMeaningPolicy
    surface_conf_threshold: float = 0.5
    ambiguity_threshold: float = 0.6


# ---------------------------------------------------------------------------
# StageLedger — substrate cho ToM-after-Meaning guard (R7.2)
# ---------------------------------------------------------------------------
class StageLedger:
    """Ghi nhận stage nào đã sinh đầu ra cho ``frame_id`` nào.

    Mỗi lần chạy pipeline dùng một ledger riêng. ``TheoryOfMindCore.infer``
    tra ledger để cưỡng chế thứ tự: ToM chỉ chạy khi
    ``MeaningHypothesisEngine`` và ``PragmaticIntentEngine`` đã có entry cho
    ``frame_id`` hiện tại (R7.2).

    Khóa nội bộ là cặp ``(stage, frame_id)`` nên ledger phân biệt theo từng
    frame: một stage đã chạy cho frame A không tự động được coi là đã chạy
    cho frame B.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: set[tuple[str, str]] = set()

    def record(self, stage: str, frame_id: str) -> None:
        """Đánh dấu ``stage`` đã sinh đầu ra cho ``frame_id``.

        Idempotent: ghi lại cùng cặp ``(stage, frame_id)`` không gây lỗi.
        """

        self._entries.add((stage, frame_id))

    def has(self, stage: str, frame_id: str) -> bool:
        """True nếu ``stage`` đã được ghi nhận cho đúng ``frame_id`` này."""

        return (stage, frame_id) in self._entries
