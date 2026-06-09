# -*- coding: utf-8 -*-
"""cortex.tom — Phase 2 Theory of Mind package.

Tầng lý thuyết tâm trí (Theory of Mind) của Phase 2. Cưỡng chế ràng buộc
ToM-after-Meaning (R7): ``TheoryOfMindCore`` chỉ suy luận từ đầu ra của
``MeaningHypothesisEngine`` và ``PragmaticIntentEngine``, không bao giờ từ
câu thô của người dùng.

Module này export API công khai của tầng ToM để downstream import gọn:

- Stage chính: ``TheoryOfMindCore``.
- Cộng sự hậu kỳ: ``MentalStateRanker``, ``CounterfactualCorrector``,
  ``Counterfactual``, ``ToMHistoryAdapter``.
- Data models / lỗi contract: ``MentalStateInference``, ``ToMHistory``,
  ``ToMOrderingViolation``.

Mọi import ở mức module là một chiều (``tom`` → ``meaning``), không tạo vòng:
``cortex.meaning.*`` KHÔNG import runtime bất kỳ symbol nào của ``cortex.tom``.
"""

from __future__ import annotations

from .contracts import (
    MentalStateInference,
    ToMHistory,
    ToMOrderingViolation,
)
from .counterfactual_corrector import Counterfactual, CounterfactualCorrector
from .mental_state_ranker import MentalStateRanker
from .theory_of_mind import TheoryOfMindCore
from .tom_history_adapter import ToMHistoryAdapter


__all__ = [
    "TheoryOfMindCore",
    "MentalStateRanker",
    "CounterfactualCorrector",
    "Counterfactual",
    "ToMHistoryAdapter",
    "MentalStateInference",
    "ToMHistory",
    "ToMOrderingViolation",
]
