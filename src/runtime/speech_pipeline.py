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
)


@dataclass(frozen=True, slots=True)
class SpeechIntentDecision:
    intent: str #kiểu nói
    reason: str #lý do chọn intent đó
    #frozen=True: không cho sửa sau khi tạo.
    #slots=True: tiết kiệm RAM, truy cập nhanh hơn.





class SpeechPipelineMixin:
    """Reserved for the main parse -> Ti -> filter -> final decision speech flow.

    The coordinator still owns the high-level chat/autonomous loops; this mixin keeps
    shared speech intent types close to the future pipeline extraction point.
    """

    pass
