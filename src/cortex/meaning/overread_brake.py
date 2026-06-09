# -*- coding: utf-8 -*-
"""overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2).

Conclusion set → EvaluatedConclusion set.

``OverreadBrake`` là cơ chế phanh chuyên trách: nó nhận **mọi** kết luận xuôi
dòng (``MeaningHypothesis`` | ``PragmaticIntent`` | ``MentalStateInference``) và,
dựa trên ``overread_risk``, số lượng evidence, cùng danh sách
``forbidden_assumptions`` của frame, quyết định:

- **giảm** ``confidence`` (reduction band), hoặc
- **chặn** (``overread_suppressed=True``),

trước khi ``SurfaceMeaningPolicy`` quyết định surface/withhold. Brake KHÔNG vứt
bỏ kết luận nào — kể cả kết luận bị chặn vẫn nằm trong danh sách trả về kèm
``original_confidence`` và metric gốc (R8.5).

Hợp đồng hành vi (map requirement):

- **R8.1** — ``reduction_threshold ≤ overread_risk < suppression_threshold`` →
  giảm ``confidence`` xuống ``≤ reduced_conf_cap`` (mặc định 0.50), cụ thể
  ``min(confidence, reduced_conf_cap)``. ``original_confidence`` giữ giá trị
  trước khi giảm.
- **R8.2** — ``overread_risk ≥ suppression_threshold`` (mặc định 0.90) → đánh
  ``overread_suppressed=True``.
- **R8.3** — số evidence hỗ trợ ``< min_evidence_count`` (mặc định 2) → đánh
  ``overread_suppressed=True`` (reason ``insufficient_evidence``,
  ``metric_name="evidence_count"``, ``metric_value=count``).
- **R8.4** — mọi lần GIẢM hoặc CHẶN: ghi ``brake_reason``, ``metric_name``,
  ``metric_value`` lên ``EvaluatedConclusion`` (cho CẢ hai trường hợp).
- **R8.5** — kết luận bị chặn được GIỮ trong output (không drop), vẫn mang
  ``original_confidence`` và metric gốc; ``StageDebug.notes`` ghi nhận số lượng.
- **R8.6** — kết luận khẳng định một ``forbidden_assumption`` như fact → chặn,
  ghi forbidden assumption đã khớp làm ``brake_reason``.

### Diễn giải "khẳng định một forbidden assumption như fact" (R8.6)

Brake chỉ đọc văn bản tóm tắt của kết luận (``summary`` với ``MeaningHypothesis``
và ``MentalStateInference``; ``PragmaticIntent`` không có ``summary`` nên coi như
chuỗi rỗng). Một kết luận bị xem là "khẳng định forbidden assumption như fact"
khi **bất kỳ** chuỗi trong ``forbidden_assumptions`` xuất hiện dưới dạng
**substring không phân biệt hoa thường** trong văn bản tóm tắt đó. Đây là phép
khớp thận trọng (conservative): nghi ngờ thì chặn, đúng tinh thần no-over-read.
Chuỗi forbidden rỗng/space bị bỏ qua (không khớp mọi thứ).

### Thứ tự ưu tiên (precedence)

Một kết luận có thể chạm nhiều điều kiện cùng lúc. Quy ước: **chặn (suppression)
luôn thắng giảm (reduction)** (R8.2/R8.3/R8.6 > R8.1). Trong nhóm chặn, thứ tự
kiểm tra (lý do ghi nhận là lý do ĐẦU TIÊN khớp) là:

1. ``forbidden_assumption`` khớp (R8.6) — vi phạm ngữ nghĩa mạnh nhất.
2. ``overread_risk ≥ suppression_threshold`` (R8.2).
3. số evidence ``< min_evidence_count`` (R8.3).

Nếu không bị chặn, mới xét reduction band (R8.1). Nếu chẳng chạm gì →
``EvaluatedConclusion`` giữ nguyên confidence, không reason/metric.

Khi bị chặn, ``confidence`` được GIỮ NGUYÊN bằng ``original_confidence`` (không
bịa giá trị mới); việc một kết luận có surface hay không là quyết định của
``SurfaceMeaningPolicy`` dựa trên cờ ``overread_suppressed``.
"""

from __future__ import annotations

from typing import Sequence

from .config import Phase2Config
from .contracts import (
    Conclusion,
    EvaluatedConclusion,
    StageDebug,
    clamp01,
)


__all__ = ["OverreadBrake"]


class OverreadBrake:
    """Phanh phán bậy — giảm/chặn kết luận theo overread_risk & evidence (stage 8).

    Ngưỡng mặc định đọc từ ``Phase2Config`` (nguồn DUY NHẤT), nhưng cho phép
    override từng ngưỡng qua keyword args ở constructor.
    """

    __slots__ = (
        "reduction_threshold",
        "suppression_threshold",
        "reduced_conf_cap",
        "min_evidence_count",
    )

    def __init__(
        self,
        config: Phase2Config | None = None,
        *,
        reduction_threshold: float | None = None,
        suppression_threshold: float | None = None,
        reduced_conf_cap: float | None = None,
        min_evidence_count: int | None = None,
    ) -> None:
        """Khởi tạo brake.

        Lấy mặc định từ ``config`` (hoặc ``Phase2Config()`` nếu ``None``); mọi
        keyword arg được truyền tường minh sẽ **ghi đè** giá trị tương ứng.
        """

        cfg = config if config is not None else Phase2Config()

        self.reduction_threshold: float = (
            cfg.overread_reduction_threshold
            if reduction_threshold is None
            else reduction_threshold
        )
        self.suppression_threshold: float = (
            cfg.overread_suppression_threshold
            if suppression_threshold is None
            else suppression_threshold
        )
        self.reduced_conf_cap: float = (
            cfg.reduced_conf_cap if reduced_conf_cap is None else reduced_conf_cap
        )
        self.min_evidence_count: int = (
            cfg.min_evidence_count
            if min_evidence_count is None
            else min_evidence_count
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def evaluate(
        self,
        conclusions: list[Conclusion],
        *,
        forbidden_assumptions: list[str],
    ) -> tuple[list[EvaluatedConclusion], StageDebug]:
        """Đánh giá brake cho từng kết luận.

        Trả về một ``EvaluatedConclusion`` cho MỖI kết luận đầu vào (kể cả kết
        luận bị chặn — R8.5), kèm ``StageDebug`` tổng hợp. Xem docstring module
        cho hợp đồng đầy đủ (R8.1–R8.6) và quy ước precedence.
        """

        items = [c for c in (conclusions or []) if c is not None]
        forbidden = self._normalize_forbidden(forbidden_assumptions)

        evaluated: list[EvaluatedConclusion] = []
        for conclusion in items:
            evaluated.append(self._evaluate_one(conclusion, forbidden))

        debug = self._build_debug(evaluated)
        return evaluated, debug

    # ------------------------------------------------------------------
    # Per-conclusion evaluation
    # ------------------------------------------------------------------
    def _evaluate_one(
        self, conclusion: Conclusion, forbidden: Sequence[str]
    ) -> EvaluatedConclusion:
        """Áp luật brake cho một kết luận, theo đúng precedence đã ghi."""

        kind = self._kind(conclusion)
        original_confidence = clamp01(getattr(conclusion, "confidence", 0.0))
        overread_risk = clamp01(getattr(conclusion, "overread_risk", 0.0))
        evidence_ids = self._evidence_ids(conclusion)
        evidence_count = len(evidence_ids)
        summary = self._summary_text(conclusion)

        # === Nhóm CHẶN (suppression) — thắng reduction =====================
        # 1) R8.6 — khẳng định forbidden assumption như fact.
        matched = self._matched_forbidden(summary, forbidden)
        if matched is not None:
            return EvaluatedConclusion(
                conclusion=conclusion,
                kind=kind,
                confidence=original_confidence,  # giữ nguyên, không bịa (R8.5)
                original_confidence=original_confidence,
                overread_suppressed=True,
                brake_reason=f"forbidden_assumption:{matched}",
                metric_name="forbidden_assumption",
                metric_value=1.0,
            )

        # 2) R8.2 — overread_risk ≥ suppression_threshold.
        if overread_risk >= self.suppression_threshold:
            return EvaluatedConclusion(
                conclusion=conclusion,
                kind=kind,
                confidence=original_confidence,
                original_confidence=original_confidence,
                overread_suppressed=True,
                brake_reason="overread_risk_suppressed",
                metric_name="overread_risk",
                metric_value=overread_risk,
            )

        # 3) R8.3 — evidence không đủ.
        if evidence_count < self.min_evidence_count:
            return EvaluatedConclusion(
                conclusion=conclusion,
                kind=kind,
                confidence=original_confidence,
                original_confidence=original_confidence,
                overread_suppressed=True,
                brake_reason="insufficient_evidence",
                metric_name="evidence_count",
                metric_value=float(evidence_count),
            )

        # === Nhóm GIẢM (reduction) — R8.1 ==================================
        if self.reduction_threshold <= overread_risk < self.suppression_threshold:
            reduced = min(original_confidence, self.reduced_conf_cap)
            return EvaluatedConclusion(
                conclusion=conclusion,
                kind=kind,
                confidence=reduced,
                original_confidence=original_confidence,
                overread_suppressed=False,
                brake_reason="overread_risk_reduced",
                metric_name="overread_risk",
                metric_value=overread_risk,
            )

        # === Không chạm điều kiện nào — giữ nguyên =========================
        return EvaluatedConclusion(
            conclusion=conclusion,
            kind=kind,
            confidence=original_confidence,
            original_confidence=original_confidence,
            overread_suppressed=False,
            brake_reason="",
            metric_name="",
            metric_value=0.0,
        )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _evidence_ids(conclusion: Conclusion) -> list[str]:
        """Trích danh sách evidence một cách tổng quát.

        Ưu tiên ``evidence_ids`` (``MeaningHypothesis``); nếu không có thì dùng
        ``supporting_meaning_ids`` (``PragmaticIntent`` / ``MentalStateInference``);
        không có cả hai → ``[]``.
        """

        ids = getattr(conclusion, "evidence_ids", None)
        if ids is None:
            ids = getattr(conclusion, "supporting_meaning_ids", None)
        if ids is None:
            return []
        return [str(i) for i in ids]

    @staticmethod
    def _kind(conclusion: Conclusion) -> str:
        """Phân loại kết luận: ``meaning`` | ``intent`` | ``mental_state``."""

        if hasattr(conclusion, "hypothesis_id"):
            return "meaning"
        if hasattr(conclusion, "intent_id"):
            return "intent"
        if hasattr(conclusion, "inference_id"):
            return "mental_state"
        return "unknown"

    @staticmethod
    def _conclusion_id(conclusion: Conclusion) -> str:
        """Trích id ổn định: ``hypothesis_id`` / ``intent_id`` / ``inference_id``."""

        for attr in ("hypothesis_id", "intent_id", "inference_id"):
            value = getattr(conclusion, attr, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _summary_text(conclusion: Conclusion) -> str:
        """Văn bản tóm tắt để dò forbidden assumption.

        ``MeaningHypothesis`` và ``MentalStateInference`` có ``summary``;
        ``PragmaticIntent`` không có → trả chuỗi rỗng.
        """

        return str(getattr(conclusion, "summary", "") or "")

    # ------------------------------------------------------------------
    # Forbidden-assumption matching (R8.6)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_forbidden(forbidden_assumptions: list[str] | None) -> list[str]:
        """Chuẩn hóa danh sách forbidden: bỏ None/rỗng/space, giữ chuỗi gốc."""

        result: list[str] = []
        for item in forbidden_assumptions or []:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result

    @staticmethod
    def _matched_forbidden(summary: str, forbidden: Sequence[str]) -> str | None:
        """Trả forbidden assumption ĐẦU TIÊN xuất hiện (substring, case-insensitive).

        ``None`` nếu không khớp. Dùng phép khớp substring để thận trọng: chỉ cần
        văn bản kết luận chứa cụm forbidden là coi như đang khẳng định nó.
        """

        if not summary:
            return None
        haystack = summary.lower()
        for assumption in forbidden:
            if assumption.lower() in haystack:
                return assumption
        return None

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------
    @staticmethod
    def _build_debug(evaluated: Sequence[EvaluatedConclusion]) -> StageDebug:
        """Gom ``StageDebug`` cho stage brake (giữ thống kê, kể cả suppressed)."""

        total = len(evaluated)
        suppressed = sum(1 for e in evaluated if e.overread_suppressed)
        reduced = sum(
            1
            for e in evaluated
            if not e.overread_suppressed and e.brake_reason == "overread_risk_reduced"
        )
        untouched = total - suppressed - reduced

        max_overread: float | None
        if evaluated:
            max_overread = max(
                clamp01(getattr(e.conclusion, "overread_risk", 0.0)) for e in evaluated
            )
        else:
            max_overread = None

        notes = [
            f"evaluated {total} conclusion(s): "
            f"{suppressed} suppressed, {reduced} reduced, {untouched} untouched",
            "suppressed conclusions are preserved in the output list (R8.5)",
        ]
        return StageDebug(
            stage="OverreadBrake",
            confidence=None,
            ambiguity=None,
            overread_risk=max_overread,
            notes=notes,
        )
