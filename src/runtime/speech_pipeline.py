from __future__ import annotations

from dataclasses import dataclass


SPEECH_INTENTS = (
    "no_speech", #không nói
    "brief_ack", # đáp ngắn
    "screen_observation", # nhận xét màn hình 
    "micro_observation", # nhận xét nhỏ
    "user_requested", #người dùng yêu cầu nói
    "system_warning",# cảnh báo hệ thống
    "playful_aside", #nhận xét vui vẻ
    "presence_maintenance", #giữ cảm giác hiện diện
    "micro_presence",# cảm giác hiện diện nhỏ
    "re_engagement",#tái kết nối khi cảm thấy có cơ hội
    "curious_question", # hỏi lại tò mò
    "social_presence", # giữ lại cảm giác hiện diện
    "scene_curiosity",
    "ambient_comment",
    "inner_whim",
    "random_chatter",
    "companionship_ping",
    "micro_story",
    "light_muse",
)


@dataclass(frozen=True, slots=True)
class SpeechIntentDecision:
    intent: str #kiểu nói
    reason: str #lý do chọn intent đó
    #frozen=True: không cho sửa sau khi tạo.
    #slots=True: tiết kiệm RAM, truy cập nhanh hơn.





class SpeechPipelineMixin:
    """Shared finalization path for public speech decisions.

    Trước đây chat/autonomous/force_speak/presence tự gọi Ti/filter theo các đường riêng.
    Kết quả: một đường quên guard là có câu lọt. File này gom lại một API nhỏ để các cycle
    có thể dùng chung dần, không cần đập coordinator ngay. Vâng, chúng ta đang thuần hóa
    con bạch tuộc từng xúc tu một.
    """

    def _finalize_speech_decision(
        self,
        decision,
        *,
        channel: str,
        frame=None,
        speech_core=None,
        snapshot=None,
        ti_report=None,
        user_text: str = "",
        momentum_topic: str = "",
    ):
        if ti_report is not None and callable(getattr(self.ti_governor, "enforce_decision", None)):
            decision = self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

        if callable(getattr(self, "_execute_system_action", None)) and snapshot is not None:
            decision = self._execute_system_action(decision, snapshot=snapshot, frame=frame)

        if channel == "chat" and callable(getattr(self, "_apply_chat_final_guards", None)):
            return self._apply_chat_final_guards(decision, user_text=user_text, frame=frame)

        if callable(getattr(self, "_apply_post_generation_filters", None)):
            return self._apply_post_generation_filters(
                decision,
                channel=channel,
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
                frame=frame,
            )
        return decision
