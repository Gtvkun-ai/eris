# -*- coding: utf-8 -*-
"""Gate claim public dùng chung cho chat và autonomous.

Một câu public chỉ được phép claim tri giác/hành động khi SourceGroundingReport
có evidence tương ứng. Module này không viết lại câu, không sinh fallback và
không tự quyết nội dung. Nó chỉ trả verdict typed để cả hai lane dùng đúng cùng
một luật, thay vì chat nghiêm còn autonomous đi cửa sau như một quan chức nhỏ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GroundingSurfaceVerdict:
    allowed: bool
    annotations: tuple[Any, ...] = ()

    @property
    def violation_code(self) -> str:
        return "" if self.allowed else "UNGROUNDED_PERCEPTION_OR_ACTION_CLAIM"

    def retry_instruction(self) -> str:
        if self.allowed:
            return ""
        return (
            "The draft made a perception/action claim without current evidence. "
            "Rewrite it without claiming that ERIS is literally seeing, reading, opening, "
            "or completing anything. A hypothesis must name its evidence and leave room "
            "for the user to correct it."
        )


def evaluate_grounded_surface(engine: Any, text: str, *, report: Any = None) -> GroundingSurfaceVerdict:
    """Chạy đúng một luật annotation cho mọi public lane."""

    annotate = getattr(engine, "annotate_claims", None)
    if not callable(annotate) or not str(text or "").strip():
        return GroundingSurfaceVerdict(True, ())
    try:
        annotations = tuple(
            item
            for item in annotate(str(text or ""), report=report)
            if str(getattr(item, "claim_status", "grounded") or "grounded") != "grounded"
        )
    except Exception:
        # Gate không được tự bịa lỗi grounding khi chính annotator hỏng. Caller log
        # riêng, còn câu vẫn đi qua acceptance gate khác.
        return GroundingSurfaceVerdict(True, ())
    return GroundingSurfaceVerdict(not annotations, annotations)


__all__ = ["GroundingSurfaceVerdict", "evaluate_grounded_surface"]
