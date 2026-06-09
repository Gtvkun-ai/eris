# -*- coding: utf-8 -*-
"""counterfactual_corrector.py — CounterfactualCorrector (R7.4).

Stage cuối của nhóm ToM hậu kỳ: nhận một ``MentalStateInference`` đã được
``MentalStateRanker`` xếp hạng và một tập **giải thích phản thực**
(counterfactual) — các diễn giải thay thế khả dĩ cho cùng tín hiệu — rồi
**hạ độ tin cậy** của inference khi có một counterfactual đủ mạnh.

Hợp đồng R7.4:

    IF tồn tại một counterfactual có ``confidence`` ≥ ngưỡng cấu hình cho một
    mental-state inference THEN ``CounterfactualCorrector`` giảm ``confidence``
    của inference đó xuống một giá trị **không thấp hơn 0.0** và ghi lại
    counterfactual đã kích hoạt việc giảm.

Công thức giảm (xác định, không bao giờ < 0.0)::

    strongest = max(c.confidence for c in qualifying)   # >= threshold
    new_confidence = clamp01(inference.confidence * (1.0 - strongest))

Diễn giải: counterfactual càng đáng tin (``strongest`` càng gần 1.0) thì phần
confidence còn lại của inference càng nhỏ; ``strongest == 1.0`` triệt tiêu về
0.0. Hệ số ``(1 - strongest)`` luôn ∈ [0,1] nên tích không bao giờ âm và
``clamp01`` chốt bất biến [0,1]. ``counterfactual_reason`` được set bằng
``explanation`` của counterfactual mạnh nhất (cái kích hoạt việc giảm).

Nếu **không** có counterfactual nào đạt ngưỡng → inference trả về **nguyên
trạng** (``confidence`` không đổi, ``counterfactual_reason`` giữ "").

Phụ thuộc một chiều: ``cortex.tom.counterfactual_corrector`` →
``cortex.tom.contracts`` → ``cortex.meaning.contracts`` (dùng lại ``clamp01``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..meaning.contracts import clamp01
from .contracts import MentalStateInference


__all__ = [
    "Counterfactual",
    "CounterfactualCorrector",
]


# ---------------------------------------------------------------------------
# Counterfactual — giải thích thay thế cho một inference
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Counterfactual:
    """Một diễn giải phản thực (alternative) cho một mental-state inference.

    - ``explanation``: mô tả người-đọc-được về cách hiểu thay thế.
    - ``confidence`` ∈ [0,1]: độ khả dĩ của diễn giải thay thế này; được kẹp về
      [0,1] tại điểm khởi tạo để đồng bộ bất biến chỉ số của pipeline.
    """

    explanation: str
    confidence: float

    def __post_init__(self) -> None:
        self.confidence = clamp01(self.confidence)


# ---------------------------------------------------------------------------
# CounterfactualCorrector
# ---------------------------------------------------------------------------
class CounterfactualCorrector:
    """Hạ confidence của inference khi có counterfactual đủ mạnh (R7.4).

    Ngưỡng mặc định lấy theo tham số ``threshold`` của từng lần gọi; mặc định
    0.5. Có thể truyền giá trị từ ``Phase2Config`` xuống nếu muốn dùng một
    nguồn ngưỡng chung.
    """

    DEFAULT_THRESHOLD: float = 0.5

    def correct(
        self,
        inference: MentalStateInference,
        counterfactuals: list[Counterfactual],
        *,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> MentalStateInference:
        """Trả về inference đã hiệu chỉnh theo R7.4.

        - Nếu tồn tại counterfactual với ``confidence >= threshold``: chọn cái
          mạnh nhất, giảm ``confidence`` theo công thức ``conf * (1 - strongest)``
          (clamp về [0,1], không bao giờ < 0.0) và ghi ``counterfactual_reason``
          bằng ``explanation`` của counterfactual mạnh nhất.
        - Ngược lại: trả về inference **không đổi**.

        Trả về một ``MentalStateInference`` **mới** (không mutate đầu vào) để
        gọi hàm an toàn với caller giữ tham chiếu inference gốc.
        """

        qualifying = [c for c in counterfactuals if c.confidence >= threshold]
        if not qualifying:
            return inference

        # Counterfactual mạnh nhất là cái kích hoạt việc giảm; tie-break theo
        # thứ tự xuất hiện (max giữ phần tử đầu khi confidence bằng nhau).
        strongest = max(qualifying, key=lambda c: c.confidence)
        new_confidence = clamp01(inference.confidence * (1.0 - strongest.confidence))

        return replace(
            inference,
            confidence=new_confidence,
            counterfactual_reason=strongest.explanation,
        )

    def correct_all(
        self,
        inferences: list[MentalStateInference],
        counterfactuals_by_inference_id: dict[str, list[Counterfactual]],
        *,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> list[MentalStateInference]:
        """Batch helper: áp ``correct`` cho từng inference theo id của nó.

        Mỗi inference được hiệu chỉnh bằng danh sách counterfactual tra theo
        ``inference.inference_id`` trong ``counterfactuals_by_inference_id``;
        inference không có entry coi như không có counterfactual (giữ nguyên).
        Thứ tự của danh sách kết quả khớp với thứ tự đầu vào.
        """

        return [
            self.correct(
                inference,
                counterfactuals_by_inference_id.get(inference.inference_id, []),
                threshold=threshold,
            )
            for inference in inferences
        ]
