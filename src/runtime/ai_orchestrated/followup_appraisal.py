# -*- coding: utf-8 -*-
"""Lớp suy diễn nhắc lại và rút khỏi một câu hỏi bị bỏ lửng.

Mục tiêu của lớp này rất hẹp:

1. Khi ERIS vừa hỏi và user có thể chỉ chưa để ý, cho phép nhắc lại đúng một lần.
2. Nếu sau lần nhắc vẫn không có phản hồi, đóng quyền chờ của câu hỏi cũ.
3. Cho phép ERIS chuyển sang một chủ đề khác với độ thân mật giảm nhẹ.

Lớp này không sửa relationship lâu dài, không tăng rupture, không kết luận user
không thích ERIS. Im lặng là bằng chứng yếu. Con người còn có thể đang đi lấy
nước, một hoạt động ngoại tuyến táo bạo mà runtime thường quên mất.
"""
from __future__ import annotations
from core.di import resolve_dependency

import os
from dataclasses import dataclass, replace
from typing import Any

from .discourse_state import DiscourseState


def _env_seconds(name: str, default: float, *, minimum: float, maximum: float) -> float:
    """Đọc timer từ môi trường và kẹp biên để tránh cấu hình phá nhịp."""

    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class FollowUpPolicy:
    """Các mốc thời gian của một chu kỳ hỏi -> nhắc -> bỏ chủ đề."""

    remind_after_seconds: float = 30.0
    abandon_after_reminder_seconds: float = 48.0
    abandon_without_reminder_seconds: float = 105.0
    reserved_distance: float = 0.20

    @classmethod
    def from_environment(cls) -> "FollowUpPolicy":
        return cls(
            remind_after_seconds=_env_seconds(
                "ERIS_FOLLOWUP_REMIND_AFTER_SEC", 30.0, minimum=12.0, maximum=180.0
            ),
            abandon_after_reminder_seconds=_env_seconds(
                "ERIS_FOLLOWUP_ABANDON_AFTER_REMINDER_SEC", 48.0, minimum=20.0, maximum=300.0
            ),
            abandon_without_reminder_seconds=_env_seconds(
                "ERIS_FOLLOWUP_ABANDON_WITHOUT_REMINDER_SEC", 105.0, minimum=45.0, maximum=600.0
            ),
            reserved_distance=max(
                0.0,
                min(
                    0.35,
                    _env_seconds(
                        "ERIS_FOLLOWUP_RESERVED_DISTANCE", 0.20, minimum=0.0, maximum=0.35
                    ),
                ),
            ),
        )


class FollowUpAppraisalLayer:
    """Giữ trạng thái tạm thời cho đúng một câu hỏi đang chờ user.

    ``DiscourseFrame`` vẫn là semantic authority cho việc ERIS có đang chờ câu
    trả lời hay không. Lớp này chỉ suy diễn *cách cư xử theo thời gian* từ kết
    luận đó: chờ, nhắc một lần, rồi thôi.

    Một user turn mới luôn reset chu kỳ. Vì vậy sự xa cách ở đây chỉ là stance
    ngắn hạn, không bị ghi thành vết nứt quan hệ vĩnh viễn vì một lần user im.
    """

    def __init__(self, policy: FollowUpPolicy | None = None) -> None:
        self.policy = resolve_dependency(policy, FollowUpPolicy.from_environment)
        self._user_turn_marker = 0.0
        self._thread_key = "unknown"
        self._question_started_at = 0.0
        self._reminder_spoken_at = 0.0
        self._abandoned_at = 0.0
        self._topic_shift_spoken = False

    def reset(self) -> None:
        """Xóa appraisal cũ khi user đã quay lại hoặc thread không còn chờ."""

        self._thread_key = "unknown"
        self._question_started_at = 0.0
        self._reminder_spoken_at = 0.0
        self._abandoned_at = 0.0
        self._topic_shift_spoken = False

    @staticmethod
    def _marker_changed(previous: float, current: float) -> bool:
        return bool(previous > 0.0 and current > 0.0 and abs(previous - current) > 0.5)

    def evaluate(
        self,
        discourse: DiscourseState,
        *,
        now: float,
        user_turn_at: float,
        assistant_turn_at: float,
    ) -> DiscourseState:
        """Bổ sung follow-up state vào discourse baton của tick hiện tại."""

        now = max(0.0, float(now or 0.0))
        user_turn_at = max(0.0, float(user_turn_at or 0.0))
        assistant_turn_at = max(0.0, float(assistant_turn_at or 0.0))

        # Có user turn mới thì mọi suy diễn "có lẽ họ không để ý" lập tức hết hạn.
        if self._marker_changed(self._user_turn_marker, user_turn_at):
            self.reset()
        if user_turn_at > 0.0:
            self._user_turn_marker = user_turn_at

        # Khi topic shift đã được observer nhìn thấy và thread không còn chờ,
        # appraisal tạm thời hoàn tất. Khoảng cách nhẹ không được dính vĩnh viễn.
        if not discourse.reply_expected and self._topic_shift_spoken:
            self.reset()
            return replace(
                discourse,
                followup_state="none",
                followup_reminder_due=False,
                followup_reminder_count=0,
                followup_abandoned=False,
                suppress_same_topic=False,
                may_start_new_topic=False,
                social_distance=0.0,
            )

        # Nếu observer đóng thread trước khi reminder từng được phát, tôn trọng
        # semantic authority và reset. Sau khi reminder đã phát, user marker mới
        # là bằng chứng kết thúc; observer có thể cập nhật chậm hoặc coi câu nhắc
        # là một autonomous statement, nên vẫn giữ timer chờ lần cuối.
        active_after_reminder = bool(self._reminder_spoken_at > 0.0 or self._abandoned_at > 0.0)
        if not discourse.reply_expected and not active_after_reminder:
            self.reset()
            return replace(
                discourse,
                followup_state="none",
                followup_reminder_due=False,
                followup_reminder_count=0,
                followup_abandoned=False,
                suppress_same_topic=False,
                may_start_new_topic=False,
                social_distance=0.0,
            )

        if discourse.reply_expected and self._question_started_at <= 0.0:
            # Dùng timestamp assistant thật thay vì now để restart app giữa chừng
            # vẫn giữ tuổi tương đối đúng của câu hỏi đang chờ.
            fallback_started_at = max(0.0, now - discourse.seconds_since_assistant)
            self._question_started_at = assistant_turn_at or fallback_started_at or now
            self._thread_key = discourse.thread_key or "unknown"

        # Nếu topic shift đã phát thành công thì không tạo thêm lời nào từ thread
        # cũ. Observer ở lượt sau sẽ đóng discourse; đây là chốt chống lặp tại chỗ.
        if self._topic_shift_spoken:
            return replace(
                discourse,
                reply_expected=False,
                assistant_may_continue=False,
                followup_state="completed",
                followup_reminder_due=False,
                followup_reminder_count=1 if self._reminder_spoken_at > 0.0 else 0,
                followup_abandoned=True,
                suppress_same_topic=True,
                may_start_new_topic=False,
                social_distance=self.policy.reserved_distance,
            )

        # Sau khi đã nhắc một lần, chỉ chờ thêm một khoảng ngắn. Không nhắc lần hai.
        if self._reminder_spoken_at > 0.0 and self._abandoned_at <= 0.0:
            if now - self._reminder_spoken_at >= self.policy.abandon_after_reminder_seconds:
                self._abandoned_at = now

        # Nếu Surface liên tục lỗi và câu nhắc không phát được, cuối cùng vẫn phải
        # buông thread cũ. Không thể giữ cả ERIS làm con tin cho một API đang hấp hối.
        if (
            self._reminder_spoken_at <= 0.0
            and self._question_started_at > 0.0
            and self._abandoned_at <= 0.0
            and now - self._question_started_at >= self.policy.abandon_without_reminder_seconds
        ):
            self._abandoned_at = now

        if self._abandoned_at > 0.0:
            return replace(
                discourse,
                reply_expected=False,
                assistant_may_continue=False,
                followup_state="abandoned",
                followup_reminder_due=False,
                followup_reminder_count=1 if self._reminder_spoken_at > 0.0 else 0,
                followup_abandoned=True,
                suppress_same_topic=True,
                may_start_new_topic=True,
                social_distance=self.policy.reserved_distance,
            )

        reminder_due = bool(
            self._reminder_spoken_at <= 0.0
            and self._question_started_at > 0.0
            and now - self._question_started_at >= self.policy.remind_after_seconds
        )
        state = "reminder_due" if reminder_due else (
            "waiting_after_reminder" if self._reminder_spoken_at > 0.0 else "waiting"
        )
        return replace(
            discourse,
            reply_expected=True,
            followup_state=state,
            followup_reminder_due=reminder_due,
            followup_reminder_count=1 if self._reminder_spoken_at > 0.0 else 0,
            followup_abandoned=False,
            suppress_same_topic=False,
            may_start_new_topic=False,
            social_distance=0.0,
        )

    def note_spoken(self, plan: Any, *, now: float) -> None:
        """Ghi nhận câu nhắc/topic shift chỉ sau khi public commit thành công."""

        semantics = getattr(plan, "semantics", None)
        speech_act = str(getattr(semantics, "speech_act", "") or "").strip().lower()
        motive = str(getattr(plan, "motive", "") or "").strip().lower()
        if speech_act == "followup_reminder" or motive == "followup_reminder":
            if self._reminder_spoken_at <= 0.0:
                self._reminder_spoken_at = max(0.0, float(now or 0.0))
            return
        if speech_act == "independent_topic_shift" or motive == "abandoned_topic_shift":
            self._topic_shift_spoken = True


__all__ = ["FollowUpAppraisalLayer", "FollowUpPolicy"]
