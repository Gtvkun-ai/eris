# -*- coding: utf-8 -*-
"""tom_debug.py — ``ToMDebug`` (bản ghi debug Theory of Mind, R12.3).

Sinh **bản ghi người-đọc-được** cho tập ``MentalStateInference`` mà
``TheoryOfMindCore`` suy ra. Với mỗi inference, in:

- ``supporting_meaning_ids`` — các tham chiếu ``MeaningHypothesis`` đã chống đỡ
  cho inference (R7.6, R12.3).
- ``confidence`` và ``overread_risk`` (mỗi giá trị ∈ [0,1]).
- ``unsupported`` — cờ inference không gắn được tham chiếu hỗ trợ (R7.7).
- ``counterfactual_reason`` — lý do phản thực đã kích hoạt làm giảm confidence
  (R7.4), nếu có.

Module thuần trình bày: không đọc Raw_World, không suy luận thêm.
"""

from __future__ import annotations

from ..meaning.contracts import clamp01  # noqa: F401  (giữ một nguồn kẹp [0,1])
from .contracts import MentalStateInference


__all__ = ["ToMDebug"]


def _render_metric(value: float | None) -> str:
    """Render một chỉ số: ``f"{value:.3f}"`` khi có giá trị, else ``"unavailable"`` (R12.5)."""

    if value is None:
        return "unavailable"
    return f"{value:.3f}"


class ToMDebug:
    """Render danh sách ``MentalStateInference`` thành chuỗi người-đọc-được (R12.3)."""

    __slots__ = ()

    def render(self, inferences: list[MentalStateInference]) -> str:
        """Trả bản ghi nhiều dòng cho từng mental-state inference (R12.3)."""

        lines: list[str] = ["=== Theory of Mind inferences ==="]

        items = [i for i in (inferences or []) if i is not None]
        if not items:
            lines.append("(no mental-state inferences)")
            return "\n".join(lines)

        for inf in items:
            lines.extend(self._render_inference(inf))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Per-inference rendering
    # ------------------------------------------------------------------
    @staticmethod
    def _render_inference(inf: MentalStateInference) -> list[str]:
        """Render một inference + các tham chiếu MeaningHypothesis hỗ trợ."""

        inference_id = getattr(inf, "inference_id", "") or "<unknown>"
        category = getattr(inf, "category", "") or "<uncategorized>"
        summary = getattr(inf, "summary", "") or ""

        supporting = getattr(inf, "supporting_meaning_ids", None) or []
        if supporting:
            supporting_str = ", ".join(str(s) for s in supporting)
        else:
            supporting_str = "(none)"

        out: list[str] = [f"- {inference_id} [{category}]: {summary}"]
        out.append(f"    confidence:    {_render_metric(getattr(inf, 'confidence', None))}")
        out.append(f"    overread_risk: {_render_metric(getattr(inf, 'overread_risk', None))}")
        out.append(f"    supporting_meaning_ids: {supporting_str}")
        out.append(f"    unsupported: {getattr(inf, 'unsupported', False)}")

        counterfactual = getattr(inf, "counterfactual_reason", "") or ""
        if counterfactual:
            out.append(f"    counterfactual_reason: {counterfactual}")
        return out
