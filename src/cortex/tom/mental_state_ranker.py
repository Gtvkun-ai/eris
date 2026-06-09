# -*- coding: utf-8 -*-
"""mental_state_ranker.py — MentalStateRanker.

Xếp hạng các ``MentalStateInference`` theo độ hợp lý giảm dần (R7.3):

- ``confidence`` cao xếp trước.
- Khi ``confidence`` bằng nhau, ``overread_risk`` thấp hơn xếp trên (ưu tiên kết
  luận ít rủi ro suy diễn vượt bằng chứng).

Sắp xếp ổn định (stable) và tất định (deterministic): với cùng đầu vào luôn cho
cùng thứ tự, và các phần tử có cùng khóa giữ nguyên thứ tự tương đối ban đầu.
Hàm ``rank`` trả về một danh sách MỚI, không mutate danh sách đầu vào.
"""

from __future__ import annotations

from .contracts import MentalStateInference


__all__ = ["MentalStateRanker"]


class MentalStateRanker:
    """Xếp hạng mental-state inference theo plausibility giảm dần (R7.3)."""

    def rank(
        self, inferences: list[MentalStateInference]
    ) -> list[MentalStateInference]:
        """Trả danh sách mới đã sắp xếp giảm dần theo plausibility.

        Khóa sắp xếp ``(-confidence, overread_risk)``:
        - ``-confidence`` → confidence cao đứng trước.
        - ``overread_risk`` tăng dần → khi confidence bằng nhau, rủi ro thấp đứng trước.

        ``sorted`` của Python là stable nên các phần tử cùng khóa giữ nguyên thứ
        tự tương đối; ``confidence``/``overread_risk`` đã được clamp về [0,1] tại
        ``MentalStateInference.__post_init__``.
        """
        return sorted(
            inferences,
            key=lambda inf: (-inf.confidence, inf.overread_risk),
        )
