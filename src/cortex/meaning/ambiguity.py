# -*- coding: utf-8 -*-
"""ambiguity.py — AmbiguityModule (định lượng mơ hồ).

``AmbiguityModule`` lượng hoá **độ mơ hồ** của một tập giả thuyết đã chấm điểm
(``scored hypotheses``) thành một giá trị ``ambiguity ∈ [0.0, 1.0]``. Module này
được ``MeaningHypothesisEngine`` và ``SurfaceMeaningPolicy`` dùng chung (xem
design "AmbiguityModule").

Đầu vào là một ``list`` các object — mỗi object chỉ cần expose thuộc tính
``confidence`` kiểu ``float``. ``MeaningHypothesis`` thoả mãn hợp đồng này; design
gọi tên kiểu chung là ``ScoredHypothesis`` nên module chấp nhận **bất kỳ** object
nào có ``.confidence``.

Trạng thái: module **stateful** — giữ ``self._last_value`` là giá trị ambiguity
hợp lệ gần nhất, để tuân R9.5 ("giữ giá trị trước đó nếu input invalid").

Hợp đồng hành vi (map requirement):

- **R9.1 — ≥2 hypothesis**: tính ``ambiguity ∈ [0,1]`` cho cả tập, dựa trên độ
  sát của top-2 ``confidence``. Khoảng cách nhỏ → mơ hồ cao; khoảng cách lớn →
  mơ hồ thấp.
- **R9.2 — đúng 1 hypothesis, không đối thủ**: ``ambiguity ∈ [0.0, 0.1]`` (không
  có đối thủ thì gần như không mơ hồ → trả ``0.0``).
- **R9.3 — top-2 ``|Δconfidence| ≤ 0.05``**: ``ambiguity ∈ [0.9, 1.0]`` (gần hoà
  → rất mơ hồ).
- **R9.4 — 0 hypothesis**: ``ambiguity = 0.0`` + chỉ báo "no hypotheses
  available for comparison". Đây là một kết quả **hợp lệ** (``valid=True``); giá
  trị 0.0 ĐƯỢC ghi nhận vào ``_last_value`` (khác hẳn input invalid bên dưới).
- **R9.5 — có ``confidence`` ngoài [0,1]** (hoặc không phải số / NaN): **từ chối**
  cả tập, trả chỉ báo ``valid=False`` và **giữ nguyên** ``ambiguity`` hợp lệ
  trước đó (KHÔNG ghi đè ``_last_value``).

### Công thức ambiguity (≥2 hypothesis)

Sắp xếp ``confidence`` giảm dần, lấy hai giá trị đầu ``c1 ≥ c2`` và đặt
``gap = c1 - c2 ∈ [0, 1]``. Ánh xạ tuyến tính, đơn điệu-giảm theo ``gap``::

    ambiguity = clamp01(1.0 - 2.0 * gap)

Tính chất công thức (thoả mọi ràng buộc biên ở trên):

- ``gap = 0.0``    → ``1.0``  (hoà tuyệt đối → mơ hồ tối đa).
- ``gap = 0.05``   → ``0.9``  ⇒ với ``gap ≤ 0.05`` thì ``ambiguity ∈ [0.9, 1.0]`` (R9.3).
- ``gap = 0.5``    → ``0.0``  (cách biệt rõ → hết mơ hồ).
- ``gap > 0.5``    → kẹp về ``0.0`` qua ``clamp01`` (luôn ∈ [0,1], R9.1).

Hệ số dốc ``2.0`` được chọn để đúng điểm ``gap = 0.05`` rơi vào biên ``0.9`` của
R9.3 mà vẫn giữ ánh xạ đơn điệu trên toàn dải. ``clamp01`` chỉ áp cho **đầu ra**;
``confidence`` đầu vào KHÔNG bị clamp âm thầm mà được **kiểm tra** để phát hiện
vi phạm [0,1] (R9.5).

Logic thuần, không I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from .contracts import clamp01


__all__ = ["AmbiguityResult", "AmbiguityModule"]


# Slope của ánh xạ gap -> ambiguity; 2.0 đặt gap=0.05 đúng biên 0.9 (R9.3).
_GAP_SLOPE = 2.0

# Ngưỡng "near-tie" của top-2 confidence (R9.3).
_NEAR_TIE_GAP = 0.05

# Biên dưới của dải near-tie ambiguity (R9.3: near-tie -> [0.9, 1.0]).
_NEAR_TIE_FLOOR = 0.9

# Dung sai số học dấu phẩy động cho so sánh biên near-tie. Một gap "ý định"
# bằng 0.05 có thể tính ra 0.05000000000000004; epsilon nhỏ đảm bảo các input
# có |Δconf| ≤ 0.05 vẫn rơi đúng vào dải near-tie bất chấp sai số float.
_GAP_EPSILON = 1e-9


@dataclass(slots=True)
class AmbiguityResult:
    """Kết quả lượng hoá độ mơ hồ.

    - ``value``: ambiguity ∈ [0.0, 1.0]. Khi input invalid (R9.5), đây là giá trị
      hợp lệ gần nhất được giữ lại.
    - ``valid``: ``False`` khi input bị từ chối (có ``confidence`` ngoài [0,1]).
    - ``reason``: chú thích người-đọc-được (vd. "no hypotheses available for
      comparison", lý do reject...).
    """

    value: float
    valid: bool = True
    reason: str = ""


class AmbiguityModule:
    """Lượng hoá độ mơ hồ của một tập scored hypotheses (stateful)."""

    def __init__(self) -> None:
        # Giá trị ambiguity hợp lệ gần nhất; giữ lại khi input invalid (R9.5).
        self._last_value: float = 0.0

    @property
    def last_value(self) -> float:
        """Giá trị ambiguity hợp lệ gần nhất đã tính (chỉ-đọc, để debug)."""

        return self._last_value

    def compute(self, hypotheses: Sequence[Any]) -> AmbiguityResult:
        """Tính ``AmbiguityResult`` cho ``hypotheses``.

        ``hypotheses`` là chuỗi object có thuộc tính ``confidence``. Xem docstring
        module cho hợp đồng đầy đủ (R9.1–R9.5).
        """

        items = list(hypotheses) if hypotheses is not None else []

        # --- R9.4: 0 hypothesis -> ambiguity 0.0, kết quả hợp lệ --------------
        # Cập nhật _last_value về 0.0 (khác input invalid: đây là phép tính hợp lệ).
        if not items:
            self._last_value = 0.0
            return AmbiguityResult(
                value=0.0,
                valid=True,
                reason="no hypotheses available for comparison",
            )

        # --- R9.5: validate confidence trong [0,1] cho TOÀN BỘ tập -----------
        # Không clamp âm thầm; phát hiện vi phạm -> từ chối, giữ giá trị trước đó.
        confidences = self._extract_valid_confidences(items)
        if confidences is None:
            return AmbiguityResult(
                value=self._last_value,
                valid=False,
                reason=(
                    "invalid input: a hypothesis has confidence outside [0,1] "
                    "(or non-numeric); retaining previous ambiguity value"
                ),
            )

        # --- R9.2: đúng 1 hypothesis, không đối thủ -> ambiguity ∈ [0.0, 0.1] -
        if len(confidences) == 1:
            value = 0.0  # không có đối thủ => không mơ hồ
            self._last_value = value
            return AmbiguityResult(
                value=value,
                valid=True,
                reason="single hypothesis with no competitor",
            )

        # --- R9.1 / R9.3: ≥2 hypothesis -> dựa trên gap của top-2 ------------
        ordered = sorted(confidences, reverse=True)
        top1, top2 = ordered[0], ordered[1]
        gap = top1 - top2  # ∈ [0,1] vì confidences đã được kiểm trong [0,1]

        value = clamp01(1.0 - _GAP_SLOPE * gap)

        if gap <= _NEAR_TIE_GAP + _GAP_EPSILON:
            # Near-tie: cưỡng chế biên dưới 0.9 để R9.3 luôn đúng dù có sai số
            # float làm value rơi nhẹ dưới 0.9 (vd. gap=0.05 -> 0.8999...).
            value = clamp01(max(value, _NEAR_TIE_FLOOR))
            reason = (
                f"top-2 confidence near-tie (gap={gap:.4f} <= "
                f"{_NEAR_TIE_GAP}); high ambiguity"
            )
        else:
            reason = f"top-2 confidence gap={gap:.4f}; ambiguity={value:.4f}"

        self._last_value = value
        return AmbiguityResult(value=value, valid=True, reason=reason)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_valid_confidences(items: Sequence[Any]) -> list[float] | None:
        """Trích ``confidence`` từng item, kiểm phải là số thực ∈ [0,1].

        Trả ``list[float]`` nếu MỌI item hợp lệ; trả ``None`` nếu có bất kỳ item
        nào thiếu ``confidence``, không phải số, là NaN, hoặc nằm ngoài [0,1]
        (R9.5 — không clamp âm thầm, phát hiện để từ chối cả tập).
        """

        confidences: list[float] = []
        for item in items:
            raw = getattr(item, "confidence", None)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                # bool là subclass của int nhưng không phải confidence hợp lệ.
                return None
            value = float(raw)
            if math.isnan(value) or value < 0.0 or value > 1.0:
                return None
            confidences.append(value)
        return confidences
