# -*- coding: utf-8 -*-
"""autonomous_show_formats.py - format biểu diễn có neo cho Autonomous VTuber.

Phase 9 tách *format show* khỏi câu chữ. Opportunity nói Eris có lý do gì để mở
miệng; format nói màn đó nên là technical sting, quiet presence, callback bit,
hay cold open có neo. Model chính vẫn viết câu, nhưng không còn tự phát minh vai
MC, khán giả hoặc một nhiệm vụ tưởng tượng chỉ vì câu đó nghe kêu.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ShowFormatDirective:
    format_id: str
    family: str
    variant: int
    max_beats: int
    stage_energy: float
    audience_address: str
    opening_mode: str
    closing_mode: str
    anchor_policy: str
    required_evidence_refs: tuple[str, ...]
    surface_rules: tuple[str, ...]
    fallback_mode: str
    reason: str

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_evidence_refs"] = list(self.required_evidence_refs)
        payload["surface_rules"] = list(self.surface_rules)
        return payload


class AutonomousShowFormatDirector:
    """Chọn format ngắn, có neo, tránh lặp cùng kiểu màn diễn liên tiếp."""

    def __init__(self, history_size: int = 8) -> None:
        self._recent: deque[str] = deque(maxlen=max(4, int(history_size)))

    def select(
        self,
        *,
        scene: Any,
        opportunity: Any,
        show_arc: Any = None,
        session_directive: Any = None,
        stage_preset: Any = None,
        audience_feedback: Any = None,
    ) -> ShowFormatDirective:
        if opportunity is None:
            return self._directive(
                "silent_presence", "presence", 1, 0.08, "none", "none", "none",
                (), ("Không tạo text khi không có opportunity.",), "body_only", "no_opportunity",
            )

        kind = str(getattr(opportunity, "kind", "autonomous") or "autonomous")
        scene_name = str(getattr(scene, "name", "private_idle") or "private_idle")
        evidence = tuple(str(x) for x in (getattr(opportunity, "evidence_refs", ()) or ()) if str(x))
        arc_stage = str(getattr(show_arc, "arc_stage", "setup") or "setup")
        feedback_mode = str(getattr(audience_feedback, "mode", "normal") or "normal")

        if feedback_mode == "recovery":
            fmt = self._directive(
                "recovery_bridge", "recovery", 1, 0.12, "direct", "quick_focus", "soft_return",
                evidence,
                (
                    "Nói thẳng sự kiện có neo; không callback, không khịa, không mở chủ đề mới.",
                    "Nếu neo không đủ cụ thể, hạ xuống body-only.",
                ),
                "body_only", "audience_recovery",
            )
        elif kind in {"new_error", "repeated_error", "task_failure", "error_loop"}:
            fmt = self._directive(
                "technical_sting", "technical", 2, 0.56, "direct", "quick_focus", "focused_hold",
                evidence,
                (
                    "Nêu tín hiệu lỗi có thật rồi bẻ sang hướng xử lý; không tự nhận đã sửa.",
                    "Không đoán nguyên nhân nếu evidence chỉ chứng minh có lỗi.",
                ),
                "short_line", f"technical:{kind}",
            )
        elif kind in {"task_progress", "task_complete", "milestone"}:
            fmt = self._directive(
                "payoff_nod", "payoff", 2, 0.48, "direct", "recognition_hold", "clean_release",
                evidence,
                (
                    "Ghi nhận tiến triển có neo; payoff ngắn, không tâng bốc đại trà.",
                    "Không gọi đây là hoàn thành nếu evidence chỉ nói có tiến triển.",
                ),
                "short_line", f"progress:{kind}",
            )
        elif kind in {"scene_transition", "return_after_idle", "session_return"}:
            fmt = self._directive(
                "anchored_cold_open", "opening", 1, 0.34, "private", "reentry_hold", "soft_return",
                evidence,
                (
                    "Chỉ nói về chuyển nhịp/việc quay lại đã được quan sát.",
                    "Không tự dựng nhiệm vụ, lỗi, tâm trạng hoặc ý định của user.",
                ),
                "body_only", f"transition:{kind}",
            )
        elif kind in {"dead_air", "idle_presence", "presence_maintenance"}:
            fmt = self._directive(
                "quiet_presence", "presence", 1, 0.18, "none", "ambient_hold", "linger_short",
                evidence,
                (
                    "Không hỏi user phải trả lời; không giả định họ bận, buồn hay cần giúp.",
                    "Câu phải tự đứng được và rời sân khấu gọn.",
                ),
                "body_only", f"presence:{kind}",
            )
        elif kind in {"running_bit", "topic_callback", "memory_callback"} or arc_stage in {"callback", "payoff"}:
            fmt = self._directive(
                "callback_bit", "callback", 2, 0.52, "private", "recognition_hold", "clean_release",
                evidence,
                (
                    "Callback ý gần đây bằng neo thật; không kể lại nguyên câu cũ.",
                    "Ký ức chỉ là continuity, không phải bằng chứng cho hiện tại.",
                ),
                "short_line", f"callback:{kind}:{arc_stage}",
            )
        elif scene_name in {"stream_host", "collab", "announcement"}:
            fmt = self._directive(
                "host_bridge", "public_host", 2, 0.64, "audience_safe", "scene_set", "clean_release",
                evidence,
                (
                    "Câu phải public-safe và hiểu được nếu khán giả không biết ký ức riêng.",
                    "Không gọi chat/khán giả nếu runtime không có audience evidence.",
                ),
                "body_only", f"host:{scene_name}:{kind}",
            )
        else:
            fmt = self._directive(
                "micro_reaction", "reaction", 1, 0.32, "direct", "scene_set", "neutral_settle",
                evidence,
                (
                    "Một phản ứng, một ý, không tự dựng bối cảnh ngoài evidence.",
                    "Nếu user hỏi 'ý là gì?', phải chỉ được vào opportunity hiện tại.",
                ),
                "body_only", f"default:{scene_name}:{kind}",
            )

        # Lặp cùng format ba lần thì đổi variant để Stage planner hạ bớt cử chỉ
        # và prompt tránh cùng một nhịp mở. Không đổi ý nghĩa hay tự sinh content.
        repeats = sum(1 for item in self._recent if item == fmt.format_id)
        variant = 2 if repeats >= 2 else 1
        if variant != fmt.variant:
            fmt = ShowFormatDirective(**{**asdict(fmt), "variant": variant, "stage_energy": max(0.08, fmt.stage_energy - 0.12)})
        return fmt

    def record_spoken(self, directive: ShowFormatDirective | None) -> None:
        if directive is not None and directive.format_id:
            self._recent.append(directive.format_id)

    @staticmethod
    def _directive(
        format_id: str,
        family: str,
        max_beats: int,
        energy: float,
        audience_address: str,
        opening_mode: str,
        closing_mode: str,
        evidence: tuple[str, ...],
        rules: tuple[str, ...],
        fallback_mode: str,
        reason: str,
    ) -> ShowFormatDirective:
        return ShowFormatDirective(
            format_id=format_id,
            family=family,
            variant=1,
            max_beats=max(1, min(3, int(max_beats))),
            stage_energy=max(0.0, min(1.0, float(energy))),
            audience_address=audience_address,
            opening_mode=opening_mode,
            closing_mode=closing_mode,
            anchor_policy="require_surface_anchor",
            required_evidence_refs=tuple(evidence),
            surface_rules=tuple(rules),
            fallback_mode=fallback_mode,
            reason=reason,
        )


__all__ = ["AutonomousShowFormatDirector", "ShowFormatDirective"]
