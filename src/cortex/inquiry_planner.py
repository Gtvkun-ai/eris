# -*- coding: utf-8 -*-
"""Inquiry planner for observe/ask/search/suppress decisions."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import EpistemicDrive, InquiryPlan, CanonicalMeaningReport


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class InquiryPlannerEngine:
    module_name = "inquiry_planner"
    MEMORY_MARKERS = ("nhớ", "lần trước", "trước đó", "hôm qua", "tôi từng", "we discussed", "previously")

    def plan(self, frame: Any, drive: EpistemicDrive, meaning: CanonicalMeaningReport) -> InquiryPlan:
        """Lập kế hoạch inquiry nội bộ, không tự biến từ chỉ thời gian thành web action.

        Direct ``search_web`` đã bị loại khỏi runtime. Những chữ như "hôm nay",
        "hiện tại" hay "mới nhất" chỉ là ngữ nghĩa của câu, không phải quyền tự
        ý gọi mạng. Nghiên cứu ngoài, khi thật sự cần, thuộc Tutor policy riêng.
        """

        text = str(_get(frame, "user_text", "") or "").lower()
        explicit_memory = any(marker in text for marker in self.MEMORY_MARKERS)
        privacy = str(_get(frame, "channel", "")) not in {"chat", "test"} and drive.intrusion_risk > 0.55

        if explicit_memory:
            action, reason = "search_memory", "User tham chiếu lịch sử/continuity; ưu tiên memory có nguồn."
        elif drive.contradiction_pressure > 0.55:
            action, reason = "compare_patterns", "Có correction/contradiction cần đối chiếu trước khi tiếp tục."
        elif meaning.needs_clarification and drive.intrusion_risk < 0.72:
            action, reason = "ask_user", "Nghĩa chi phối chưa đủ chắc và một câu hỏi ngắn có giá trị."
        elif privacy or (drive.intrusion_risk > 0.68 and drive.knowledge_gap < 0.78):
            action, reason = "suppress_inquiry", "Privacy/overread cost cao hơn giá trị inquiry."
        elif drive.knowledge_gap > 0.58:
            action, reason = "search_memory", "Thiếu context nhưng có thể tự kiểm tra memory trước khi hỏi user."
        elif drive.inquiry_urgency < 0.18:
            action, reason = "observe_more", "Chưa có đủ áp lực để ngắt nhịp hiện tại."
        else:
            action, reason = "infer_quietly", "Evidence hiện tại đủ để tiếp tục với certainty có giới hạn."

        expected = max(drive.inquiry_urgency, 0.74 if explicit_memory else 0.0)
        return InquiryPlan(
            action=action,  # type: ignore[arg-type]
            reason=reason,
            expected_value=_clamp(expected),
            privacy_cost=_clamp(drive.intrusion_risk),
            interruption_cost=0.36 if action == "ask_user" else (0.10 if action == "search_memory" else 0.03),
        )


__all__ = ["InquiryPlannerEngine"]
