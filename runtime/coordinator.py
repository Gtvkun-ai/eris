# -*- coding: utf-8 -*-
"""ERIS runtime composition root.

Behavior lives in typed services and compatibility mixins. This module keeps the
public ``RuntimeCoordinator`` import stable while refusing to become a second
implementation of every subsystem again. Humanity has tried the god-object
pattern often enough to know how that movie ends.
"""
from __future__ import annotations

from domain import Decision
from failure_meta import is_technical_failure_meta
from runtime.autonomous_loop_runtime import AutonomousLoopRuntimeMixin
from runtime.chat_cycle import ChatCycleMixin
from runtime.cognitive_event_runtime import CognitiveEventRuntimeMixin
from runtime.coordinator_bootstrap import CoordinatorBootstrapMixin
from runtime.coordinator_shutdown import CoordinatorShutdownMixin
from runtime.incoming_protocol_runtime import IncomingProtocolRuntimeMixin
from runtime.mental_process_runtime import MentalProcessRuntimeMixin
from runtime.model_memory_runtime import ModelMemoryRuntimeMixin
from runtime.observer_private_runtime import ObserverPrivateRuntimeMixin
from runtime.presence_controller import PresenceControllerMixin
from runtime.prompt_context_builder import PromptContextBuilderMixin
from runtime.provider_action_runtime import ProviderActionRuntimeMixin
from runtime.public_output_runtime import PublicOutputRuntimeMixin
from runtime.screen_vision_runtime import ScreenVisionRuntimeMixin
from runtime.settings_control_runtime import SettingsControlRuntimeMixin
from runtime.state_commit_service import StateCommitServiceMixin
from runtime.tutor_research_runtime import TutorResearchRuntimeMixin
from runtime.user_control_runtime import UserControlRuntimeMixin

VISION_TRACE_MARKER = "vision_facts_attached"

FALLBACK_BY_INTENT: dict[str, tuple[str, ...]] = {
    "random_chatter": (
        "bạn gọi tôi ra chỉ để nghe tôi nói linh tinh à.",
        "Tín hiệu mờ quá. Tôi lùi lại một nhịp.",
    ),
    "inner_whim": ("Mạch này vẫn hơi nghẽn lại.", "Nhịp này cứ để nhỏ thôi."),
    "micro_presence": ("Mạch này vẫn hơi nghẽn.", "Nhịp này vẫn còn ở đây."),
    "curious_question": ("Có chỗ nào đang vướng nhẹ không?", "Đoạn này còn mắc ở đâu à?"),
    "screen_observation": (
        "Tôi chỉ dám bám vào chỗ này: file_saved.",
        "Tôi giữ câu này sát phần đang hiện ra thôi.",
    ),
}


def _is_nonsemantic_fallback_decision(decision: Decision) -> bool:
    """Return whether a public decision is only a technical fallback."""

    intent = str(getattr(decision, "intent", "") or "")
    parse_mode = str(getattr(decision, "parse_mode", "") or "")
    debug_trace = str(getattr(decision, "debug_trace", "") or "")
    text = str(getattr(decision, "text", "") or "").lower()
    fallback_intents = {"fallback_reply", "format_repair_fallback", "service_error", "no_fallback_block"}
    fallback_modes = {"format_repair_fallback", "service_error", "no_fallback_block"}
    if is_technical_failure_meta(getattr(decision, "failure_meta", None)):
        return True
    if intent in fallback_intents or parse_mode in fallback_modes:
        return True
    if "http_5xx_fallback" in debug_trace or "format_violation_recovered" in debug_trace:
        return True
    return "lỗi định dạng" in text or "loi dinh dang" in text or "vấn đề đường truyền" in text


class RuntimeCoordinator(
    CoordinatorBootstrapMixin,
    ModelMemoryRuntimeMixin,
    PublicOutputRuntimeMixin,
    UserControlRuntimeMixin,
    CoordinatorShutdownMixin,
    AutonomousLoopRuntimeMixin,
    ObserverPrivateRuntimeMixin,
    CognitiveEventRuntimeMixin,
    MentalProcessRuntimeMixin,
    IncomingProtocolRuntimeMixin,
    SettingsControlRuntimeMixin,
    TutorResearchRuntimeMixin,
    ScreenVisionRuntimeMixin,
    ProviderActionRuntimeMixin,
    ChatCycleMixin,
    StateCommitServiceMixin,
    PromptContextBuilderMixin,
    PresenceControllerMixin,
):
    """Stable facade over the composed ERIS runtime services."""

    _CHAT_VISION_THROTTLE_SEC = 6.0
    _LIGHT_TUTOR_RESEARCH_CUES = (
        "nghiên cứu", "nghien cuu", "đào sâu", "dao sau", "kiểm chứng", "kiem chung",
        "hỏi gemini", "hoi gemini", "hỏi sư phụ", "hoi su phu", "fix elegant", "deep research",
    )
    _LIGHT_TUTOR_COMMAND_WORDS = (
        "hỏi", "hoi", "nhờ", "nho", "kêu", "keu", "gemini", "tutor", "sư phụ", "su phu",
    )
    _LIGHT_TUTOR_REFERENT_ONLY = (
        "cái này", "cai nay", "cái đó", "cai do", "phần này", "phan nay",
        "phần đó", "phan do", "ý này", "y nay",
    )
    _KNOWLEDGE_QUESTION_MARKERS = (
        "hỏi gemini", "hoi gemini", "hỏi sư phụ", "hoi su phu", "nhờ gemini",
        "nho gemini", "kêu gemini", "keu gemini", "tra gemini",
        "là gì", "là ai", "là con gì", "là cái gì", "là chất gì", "là nước nào",
        "là bệnh gì", "là môn gì", "là ngôn ngữ gì", "nghĩa là gì", "viết tắt của",
        "tại sao", "vì sao", "do đâu", "nguyên nhân", "ở đâu", "khi nào", "năm nào",
        "thế kỷ", "ai phát minh", "ai sáng", "ai là người", "khác nhau", "khác gì",
        "so với", "có tác dụng gì", "hoạt động như thế nào", "hoạt động ra sao", "định nghĩa",
    )

    def __init__(
        self,
        *,
        logger,
        transport,
        llm_service,
        parser,
        telemetry_service,
        memory_core,
        body_running_fn,
        action_executor=None,
        action_router=None,
        memory_semantic_parser=None,
    ):
        super().__init__(
            logger=logger,
            transport=transport,
            llm_service=llm_service,
            parser=parser,
            telemetry_service=telemetry_service,
            memory_core=memory_core,
            body_running_fn=body_running_fn,
            action_executor=action_executor,
            action_router=action_router,
            memory_semantic_parser=memory_semantic_parser,
        )
