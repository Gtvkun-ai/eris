# -*- coding: utf-8 -*-
"""Validation thuần cho speech/discourse contract do root AgentLoop tạo.

Validator chỉ trả PASS/FAIL. Nó không được thêm beat, bỏ beat, đổi thread, đổi mode,
viết fallback proposition hay tự sửa plan. Nếu contract sai, feedback quay lại vòng
AgentLoop kế tiếp để chính agent tự re-plan.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    ConversationSpeechPlan,
    DiscoursePlan,
    SpeechContinuationMode,
    TurnFloor,
    TurnProjection,
)


@dataclass(frozen=True, slots=True)
class SpeechPlanValidation:
    valid: bool
    reason: str = ""


class SpeechPlanValidator:
    """Boundary validator không có semantic agency."""

    DEFAULT_STYLE_NOTES = (
        "Nói tự nhiên như hội thoại; không đọc tên DialogueBeat ra ngoài.",
        "Không public chain-of-thought; chỉ nói kết luận, bằng chứng, ví dụ và lý do giải thích được.",
        "ConversationSpeechPlan là context dài hạn, không phải nội dung phải xổ hết ở turn hiện tại.",
    )

    def validate(
        self,
        discourse: DiscoursePlan,
        *,
        speech_plan: ConversationSpeechPlan,
        completion_candidate: bool,
        waiting_for_user: bool,
        turn_projection: TurnProjection | None = None,
    ) -> SpeechPlanValidation:
        projection = turn_projection or TurnProjection()
        public_count = sum(1 for beat in discourse.public_beats if beat.proposition)

        if speech_plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE:
            if not (speech_plan.next_intent or speech_plan.planned_threads):
                return SpeechPlanValidation(False, "auto_continue_requires_agent_authored_next_intent_or_thread")
            if speech_plan.resume_trigger not in {"auto_after_audio", "after_audio", "timer"}:
                return SpeechPlanValidation(False, "auto_continue_requires_audio_resume_trigger")

        if speech_plan.continuation_mode == SpeechContinuationMode.YIELD_USER:
            if speech_plan.resume_trigger not in {"user_reply", "user_turn", "user_response"}:
                return SpeechPlanValidation(False, "yield_user_requires_user_resume_trigger")

        if waiting_for_user and speech_plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE:
            return SpeechPlanValidation(False, "tutor_wait_cannot_auto_continue")

        # Projection là quyết định của agent, nhưng validator vẫn chặn các cặp
        # lifecycle tự mâu thuẫn khiến UI/body báo một đằng còn scheduler làm một nẻo.
        if projection.floor == TurnFloor.HOLD and speech_plan.continuation_mode != SpeechContinuationMode.AUTO_CONTINUE:
            return SpeechPlanValidation(False, "hold_floor_requires_auto_continue")
        if speech_plan.continuation_mode == SpeechContinuationMode.YIELD_USER and projection.floor == TurnFloor.HOLD:
            return SpeechPlanValidation(False, "yield_user_cannot_hold_floor")
        if speech_plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE and projection.floor == TurnFloor.YIELD:
            return SpeechPlanValidation(False, "auto_continue_cannot_yield_floor")

        if waiting_for_user and projection.floor != TurnFloor.YIELD:
            return SpeechPlanValidation(False, "waiting_user_requires_yield_floor")

        if waiting_for_user:
            if public_count != 1:
                return SpeechPlanValidation(False, "waiting_user_requires_exactly_one_public_beat")
            if not discourse.user_response_required:
                return SpeechPlanValidation(False, "waiting_user_requires_user_response_flag")
            return SpeechPlanValidation(True, "")

        if completion_candidate and public_count == 0:
            return SpeechPlanValidation(False, "completion_requires_public_beat")

        return SpeechPlanValidation(True, "")


__all__ = ["SpeechPlanValidation", "SpeechPlanValidator"]
