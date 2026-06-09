# -*- coding: utf-8 -*-
"""surface_meaning_policy.py — ``SurfaceMeaningPolicy`` (phân vùng surfaced / withheld, stage 9).

EvaluatedConclusion set (đầu ra ``OverreadBrake``) → ``Phase2Result``.

``SurfaceMeaningPolicy`` là stage cuối quyết định kết luận nào được **đưa ra**
(surfaced) và kết luận nào bị **giữ lại** (withheld). Mỗi ``EvaluatedConclusion``
đầu vào được gán vào ĐÚNG MỘT trong hai tập ``{surfaced, withheld}`` và ghi
ĐÚNG MỘT ``SurfaceDecision`` (R10.1, R10.5). Phân vùng vì thế là **toàn phần**
(union = input) và **rời nhau** (intersection = rỗng).

### Thứ tự kiểm tra (precedence, trên xuống — design "Thứ tự kiểm tra")

Áp cho từng kết luận, dừng ở điều kiện ĐẦU TIÊN khớp:

1. **R10.7** — bị ``OverreadBrake`` chặn (``overread_suppressed=True``) →
   withheld, ghi lý do (giữ lại ``brake_reason`` của brake nếu có).
2. **R10.8** — không có ``evidence_id`` hỗ trợ → withheld. Đây cũng là bất biến
   "mọi phần tử trong surfaced đều có ≥1 evidence_id" (R10.8, R13.8): vì rule 2
   loại sạch các kết luận không evidence trước khi tới các nhánh surfaced.
3. **R10.4** — ``ambiguity == 1.0`` → withheld bất kể confidence.
4. **R10.2** — ``confidence < surface_conf_threshold`` → withheld, ghi lý do.
5. **R10.3** — ``confidence ≥ surface_conf_threshold`` và
   ``ambiguity_threshold ≤ ambiguity < 1.0`` → surfaced, status
   ``surfaced_tentative``.
6. **R10.6** — ``confidence ≥ surface_conf_threshold`` và
   ``ambiguity < ambiguity_threshold`` → surfaced, status ``surfaced_asserted``.

``confidence`` dùng để so ngưỡng là giá trị (có thể đã bị giảm) trên
``EvaluatedConclusion`` — phản ánh quyết định của ``OverreadBrake`` (R8.1).

### Đọc ``ambiguity`` và ``evidence`` một cách tổng quát

Đầu vào là ``EvaluatedConclusion`` bọc một ``Conclusion`` đa dạng
(``MeaningHypothesis`` | ``PragmaticIntent`` | ``MentalStateInference``). Không
phải kiểu nào cũng có cùng field:

- **ambiguity**: chỉ ``MeaningHypothesis`` mang ``ambiguity``;
  ``PragmaticIntent`` / ``MentalStateInference`` không có. Dùng
  ``getattr(conclusion, "ambiguity", 0.0)`` rồi ``clamp01`` → kết luận không có
  ambiguity được coi như ``0.0`` (không mơ hồ), nên không bao giờ rơi vào nhánh
  withheld vì mơ hồ hay tentative.
- **evidence**: ưu tiên ``evidence_ids`` (``MeaningHypothesis``); nếu không có
  thì dùng ``supporting_meaning_ids`` (``PragmaticIntent`` /
  ``MentalStateInference``); không có cả hai → ``[]``. Khớp đúng cách
  ``OverreadBrake`` đếm evidence, giữ pipeline nhất quán.
- **id**: id ổn định lấy theo thứ tự ``hypothesis_id`` → ``intent_id`` →
  ``inference_id`` để ghi vào ``SurfaceDecision.conclusion_id``.

Lưu ý: kết luận "insufficient evidence" của ``MeaningHypothesisEngine`` mang
sentinel ``evidence_ids=["insufficient_evidence"]`` nên có evidence count = 1 và
KHÔNG bị rule 2 loại; nhưng nó thường bị withheld bởi rule 1 (suppressed bởi
brake do thiếu evidence) hoặc rule 3/4 (ambiguity/confidence). Điều này chấp
nhận được theo thiết kế.
"""

from __future__ import annotations

from typing import Sequence

from .config import Phase2Config
from .contracts import (
    EvaluatedConclusion,
    Phase2Result,
    SurfaceDecision,
    clamp01,
)


__all__ = ["SurfaceMeaningPolicy"]


# Hằng status cho SurfaceDecision (design "SurfaceDecision.status").
_STATUS_ASSERTED = "surfaced_asserted"
_STATUS_TENTATIVE = "surfaced_tentative"
_STATUS_WITHHELD = "withheld"


class SurfaceMeaningPolicy:
    """Phân vùng surfaced / withheld theo precedence cố định (stage 9).

    Ngưỡng mặc định đọc từ ``Phase2Config`` (nguồn DUY NHẤT), nhưng cho phép
    override từng ngưỡng qua keyword args ở constructor.
    """

    __slots__ = (
        "surface_conf_threshold",
        "ambiguity_threshold",
    )

    def __init__(
        self,
        config: Phase2Config | None = None,
        *,
        surface_conf_threshold: float | None = None,
        ambiguity_threshold: float | None = None,
    ) -> None:
        """Khởi tạo policy.

        Lấy mặc định từ ``config`` (hoặc ``Phase2Config()`` nếu ``None`` —
        ``surface_conf_threshold=0.5``, ``ambiguity_threshold=0.6``); mọi keyword
        arg được truyền tường minh sẽ **ghi đè** giá trị tương ứng.
        """

        cfg = config if config is not None else Phase2Config()

        self.surface_conf_threshold: float = (
            cfg.surface_conf_threshold
            if surface_conf_threshold is None
            else surface_conf_threshold
        )
        self.ambiguity_threshold: float = (
            cfg.ambiguity_threshold
            if ambiguity_threshold is None
            else ambiguity_threshold
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def partition(
        self,
        evaluated: list[EvaluatedConclusion],
        *,
        frame_id: str,
    ) -> Phase2Result:
        """Phân từng ``EvaluatedConclusion`` vào surfaced HOẶC withheld.

        Trả ``Phase2Result`` ghi cả hai tập + đúng một ``SurfaceDecision`` cho
        mỗi kết luận đầu vào (R10.1, R10.5). Xem docstring module cho hợp đồng
        precedence đầy đủ (R10.2–R10.8).
        """

        items = [e for e in (evaluated or []) if e is not None]

        surfaced: list[EvaluatedConclusion] = []
        withheld: list[EvaluatedConclusion] = []
        decisions: list[SurfaceDecision] = []

        for item in items:
            status, reason = self._classify(item)
            decisions.append(
                SurfaceDecision(
                    conclusion_id=self._conclusion_id(item),
                    status=status,
                    reason=reason,
                )
            )
            if status == _STATUS_WITHHELD:
                withheld.append(item)
            else:
                surfaced.append(item)

        debug = self._build_debug(items, surfaced, withheld)
        return Phase2Result(
            frame_id=frame_id,
            surfaced=surfaced,
            withheld=withheld,
            decisions=decisions,
            debug=debug,
        )

    # ------------------------------------------------------------------
    # Per-conclusion classification (precedence)
    # ------------------------------------------------------------------
    def _classify(self, item: EvaluatedConclusion) -> tuple[str, str]:
        """Trả ``(status, reason)`` cho một kết luận theo precedence trên xuống."""

        confidence = clamp01(getattr(item, "confidence", 0.0))
        ambiguity = self._ambiguity(item)
        evidence_count = len(self._evidence_ids(item))

        # 1) R10.7 — bị OverreadBrake chặn.
        if getattr(item, "overread_suppressed", False):
            reason = item.brake_reason or "overread_suppressed"
            return _STATUS_WITHHELD, f"suppressed:{reason}"

        # 2) R10.8 — không có evidence hỗ trợ.
        if evidence_count < 1:
            return _STATUS_WITHHELD, "no_supporting_evidence"

        # 3) R10.4 — ambiguity tuyệt đối → withheld bất kể confidence.
        if ambiguity >= 1.0:
            return _STATUS_WITHHELD, "ambiguity_maximal"

        # 4) R10.2 — confidence dưới ngưỡng surface.
        if confidence < self.surface_conf_threshold:
            return (
                _STATUS_WITHHELD,
                f"confidence_below_threshold:{confidence:.4f}<{self.surface_conf_threshold:.4f}",
            )

        # 5) R10.3 — confidence đủ + mơ hồ ở dải [ambiguity_threshold, 1.0).
        if self.ambiguity_threshold <= ambiguity < 1.0:
            return _STATUS_TENTATIVE, f"ambiguity_tentative:{ambiguity:.4f}"

        # 6) R10.6 — confidence đủ + mơ hồ thấp.
        return _STATUS_ASSERTED, f"asserted:{ambiguity:.4f}"

    # ------------------------------------------------------------------
    # Extraction helpers (đọc generically từ Conclusion đa kiểu)
    # ------------------------------------------------------------------
    @staticmethod
    def _ambiguity(item: EvaluatedConclusion) -> float:
        """Đọc ``ambiguity`` của conclusion một cách tổng quát.

        Chỉ ``MeaningHypothesis`` có ``ambiguity``; các kiểu khác không có →
        coi như ``0.0`` (không mơ hồ).
        """

        conclusion = getattr(item, "conclusion", None)
        return clamp01(getattr(conclusion, "ambiguity", 0.0))

    @staticmethod
    def _evidence_ids(item: EvaluatedConclusion) -> list[str]:
        """Trích evidence một cách tổng quát (giống ``OverreadBrake``).

        Ưu tiên ``evidence_ids`` (``MeaningHypothesis``); nếu không có thì dùng
        ``supporting_meaning_ids`` (``PragmaticIntent`` / ``MentalStateInference``);
        không có cả hai → ``[]``.
        """

        conclusion = getattr(item, "conclusion", None)
        ids = getattr(conclusion, "evidence_ids", None)
        if ids is None:
            ids = getattr(conclusion, "supporting_meaning_ids", None)
        if ids is None:
            return []
        return [str(i) for i in ids]

    @staticmethod
    def _conclusion_id(item: EvaluatedConclusion) -> str:
        """Trích id ổn định: ``hypothesis_id`` / ``intent_id`` / ``inference_id``."""

        conclusion = getattr(item, "conclusion", None)
        for attr in ("hypothesis_id", "intent_id", "inference_id"):
            value = getattr(conclusion, attr, None)
            if value:
                return str(value)
        return ""

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------
    def _build_debug(
        self,
        items: Sequence[EvaluatedConclusion],
        surfaced: Sequence[EvaluatedConclusion],
        withheld: Sequence[EvaluatedConclusion],
    ) -> dict:
        """Gom thông tin debug stage (counts + ngưỡng + bất biến surfaced-có-evidence)."""

        # Xác nhận bất biến R10.8/R13.8 ngay trong debug để dễ truy vết.
        surfaced_all_have_evidence = all(
            len(self._evidence_ids(e)) >= 1 for e in surfaced
        )
        return {
            "stage": "SurfaceMeaningPolicy",
            "thresholds": {
                "surface_conf_threshold": self.surface_conf_threshold,
                "ambiguity_threshold": self.ambiguity_threshold,
            },
            "counts": {
                "total": len(items),
                "surfaced": len(surfaced),
                "withheld": len(withheld),
            },
            "surfaced_all_have_evidence": surfaced_all_have_evidence,
            "notes": [
                f"partitioned {len(items)} conclusion(s): "
                f"{len(surfaced)} surfaced, {len(withheld)} withheld",
                "partition is total and disjoint; one SurfaceDecision per input (R10.1, R10.5)",
            ],
        }
