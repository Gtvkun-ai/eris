import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
#json: xử lý dữ liệu JSON.
#os: đọc biến môi trường, config hệ thống.
#random: chọn ngẫu nhiên fallback text, thời gian sleep.
#re: regex để normalize, lọc text.
#threading: chạy loop nền, lock state.
#time: timestamp, cooldown, delay.
#traceback: log lỗi chi tiết.
#unicodedata: chuẩn hóa Unicode, ví dụ tiếng Việt dấu má, thứ mà máy tính ghét bằng một tình yêu thầm kín.
from dataclasses import dataclass, replace
'''
dataclass: tạo class dữ liệu gọn hơn.
replace: copy dataclass và đổi vài field.
'''
from cortex.action_planner import ACTION_SPACE, ActionPlanner
from cortex.affect_semantics import AffectSemanticClassifier
from cortex.attention_salience import AttentionSalienceEngine
from cortex.appraisal import AppraisalEngine
from cortex.chat_light import ChatMeaningLayerLight, ChatPersonalityPressureLight
from cortex.conversation_dynamics import ConversationDynamicsEngine
from cortex.contracts import (
    AgentSpeechCore,
    AttentionCandidate,
    CognitiveActionPlan,
    CognitiveAppraisal,
    CognitiveBroadcast,
    CognitiveDisturbance,
    CognitiveFrame,
    InnerThought,
    CognitiveMemoryUpdate,
    MeaningLayerResult,
    PersonalityLensResult,
    PerceptEvent,
    SessionRitualReport,
    SilenceState,
    SubconsciousReport,
    ThoughtStreamReport,
    TiPolicyReport,
)
from cortex.inner_thought import InnerThoughtEngine
from cortex.internal_state import InternalStateEngine, PersistentInternalState
from cortex.meaning import MeaningLayer
from cortex.micro_policy import MicroLinePolicy, RelationalContext, SemanticRepeatGuard
from cortex.modes import QUIET_MODES
from cortex.ni import NiStateMachine
from cortex.personality import PersonalityLens
from cortex.relationship_dynamics import RelationshipDynamicsEngine, RelationshipTurnEvent
from cortex.self_observation import SelfObservationEngine
from cortex.self_model import SelfModelEngine
from cortex.session_ritual import SessionRitualEngine
from cortex.speech_core import SpeechCoreEngine
from cortex.thought_stream import ThoughtStream
from cortex.working_memory import WorkingMemoryEngine
from domain import Decision
from runtime.autonomous_cycle import AutonomousCycleMixin
from runtime.body_bias import BodyBiasProjector
from runtime.chat_cycle import ChatCycleMixin
from runtime.cognitive_cycle import CognitiveCycleMixin
from runtime.cognitive_frame_recorder import CognitiveFrameRecorderMixin
from runtime.fallback_policy import FALLBACK_BY_INTENT, FallbackPolicyMixin
from runtime.force_speak_cycle import ForceSpeakCycleMixin
from runtime.frame_builder import FrameBuilderMixin
from runtime.outcome_observer import OutcomeObserver
from runtime.post_generation_filters import PostGenerationFiltersMixin
from runtime.presence_controller import MicroPresenceSynthesis, PresenceControllerMixin, SocialPresenceEvent
from runtime.prompt_context_builder import PromptContextBuilderMixin
from runtime.source_grounding import SourceGroundingEngine
from runtime.speech_pipeline import SPEECH_INTENTS, SpeechIntentDecision, SpeechPipelineMixin
from runtime.state_commit_service import StateCommitServiceMixin

'''coordinator.py là “bộ điều phối runtime” (orchestrator) cho ERIS: nó đứng giữa telemetry 
(màn hình/hành vi), các tầng đánh giá (Ni/Ti/FE), LLM + parser, action system và kênh transport để quyết định
 “lúc nào nói/câm”, “nói gì”, “có thực thi action không”, rồi gửi Decision ra “body” (Godot) qua UDP.
'''


VISION_TRACE_MARKER = "vision_facts_attached"



class RuntimeCoordinator(
    CognitiveCycleMixin,
    ChatCycleMixin,
    AutonomousCycleMixin,
    ForceSpeakCycleMixin,
    StateCommitServiceMixin,
    FrameBuilderMixin,
    SpeechPipelineMixin,
    PromptContextBuilderMixin,
    CognitiveFrameRecorderMixin,
    PresenceControllerMixin,
    FallbackPolicyMixin,
    PostGenerationFiltersMixin,
):
    #Đây là trung tâm điều phối.
    def __init__(
        self,
        *,
        logger, #ghi log
        transport, #gửi dữ liệu ra body/Godot
        llm_service, #gọi LLM
        parser, #parse output LLM
        telemetry_service, #đọc màn hình/hành vi
        ni_engine, #tầng đánh giá Ni
        ti_governor,#tầng đánh giá Ti
        fe_renderer,#tầng đánh giá FE
        memory_core,# bộ nhớ
        body_running_fn,#kiểm tra body/Godot còn chạy không
        action_executor=None, #thực thi
        action_router=None,#định tuyến action
    ):
        self.logger = logger
        self.transport = transport
        self.llm_service = llm_service
        self.parser = parser
        self.telemetry_service = telemetry_service
        self.ni_engine = ni_engine
        self.ti_governor = ti_governor
        self.fe_renderer = fe_renderer
        self.memory_core = memory_core
        self.body_running_fn = body_running_fn
        self.action_executor = action_executor
        self.action_router = action_router
        # Khởi tạo các engine con
        self.attention_salience_engine = AttentionSalienceEngine()
        self.attention_broadcast_threshold = 0.50
        self.working_memory_engine = WorkingMemoryEngine()
        self.meaning_layer = MeaningLayer()
        self.chat_meaning_layer_light = ChatMeaningLayerLight()
        self.personality_lens = PersonalityLens()
        self.chat_personality_pressure_light = ChatPersonalityPressureLight()
        self.appraisal_engine = AppraisalEngine()
        self.affect_semantics = AffectSemanticClassifier()
        self.conversation_dynamics_engine = ConversationDynamicsEngine()
        self.relationship_dynamics_engine = RelationshipDynamicsEngine()
        self.internal_state_engine = InternalStateEngine()
        self.inner_thought_engine = InnerThoughtEngine()
        self.outcome_observer = OutcomeObserver()
        self.self_observer = SelfObservationEngine()
        self.self_model_engine = SelfModelEngine()
        self.session_ritual_engine = SessionRitualEngine()
        self.speech_core_engine = SpeechCoreEngine(inner_thought_engine=self.inner_thought_engine)
        self.action_planner = ActionPlanner()
        self.source_grounding_engine = SourceGroundingEngine()
        self.semantic_repeat_guard = SemanticRepeatGuard()
        self.micro_line_policy = MicroLinePolicy(repeat_guard=self.semantic_repeat_guard)
        self.body_bias_projector = BodyBiasProjector(self._get_internal_state)
        self._state_lock = threading.RLock()

        '''Các biến này lưu trạng thái hội thoại:
        có đang chat không,
        lịch sử chat,
        câu trả lời gần nhất,
        intent gần nhất,
        topic đang active,
        text cuối cùng đã nói,
        mood score,
        idle cycles,
        các guard chống lặp.
        '''
        self.chat_mode = False
        self.chat_history = []
        self.last_chat_answer = ""
        self.last_user_intent = ""
        self.active_conversational_topic = ""
        self.last_system_action = ""
        self.last_user_signature = ""
        self.repeated_user_count = 0
        self.running = True
        self.last_text = ""
        self.mood_score = 50 #mô phỏng trạng thái cảm xúc
        self.inferred_pos_x = 0.5 # vị trí avatar
        self.idle_cycles = 0
        self.last_autonomous_signature = ""
        self.repeated_autonomous_count = 0
        self.last_autonomous_spoken_at = 0.0
        self.presence_maintenance_silent_cycles = 0
        self.last_presence_maintenance_at = 0.0
        #Các hàm _load... đọc config/env.
        '''
        khi nào ERIS được tự nói để duy trì hiện diện,
        im bao lâu thì re-engage,
        cooldown bao nhiêu giây,
        có dùng LLM cho micro presence không.
        '''
        self.presence_maintenance_enabled = self._load_presence_maintenance_enabled()
        self.presence_maintenance_silent_loop_threshold = self._load_presence_maintenance_silent_loop_threshold()
        self.presence_maintenance_cooldown_sec = self._load_presence_maintenance_cooldown()
        self.micro_presence_llm_enabled = self._load_micro_presence_llm_enabled()
        self.micro_presence_llm_probability = self._load_micro_presence_llm_probability()
        self.reengagement_quiet_cycles = 0
        self.last_reengagement_at = 0.0
        self.reengagement_enabled = self._load_reengagement_enabled()
        self.reengagement_quiet_loop_threshold = self._load_reengagement_quiet_loop_threshold()
        self.reengagement_min_idle_sec = self._load_reengagement_min_idle()
        self.reengagement_cooldown_sec = self._load_reengagement_cooldown()
        self.autonomous_sleep_seconds = self._load_autonomous_sleep_seconds(
            "ERIS_AUTONOMOUS_SLEEP_SEC",
            default=(30, 45, 60, 90),
        )
        self.autonomous_suppressed_sleep_seconds = self._load_autonomous_sleep_seconds(
            "ERIS_AUTONOMOUS_SUPPRESSED_SLEEP_SEC",
            default=(45, 60, 90, 120),
        )
        self.force_speak_repeat_guard_count = 0
        self.force_speak_intent_guard_count = 0
        self._session_ritual_ran = False
        self.recent_inner_thought_intents: tuple[str, ...] = ()
        self.recent_inner_thought_seeds: tuple[str, ...] = ()
        self.recent_meaning_families: tuple[str, ...] = ()
        #Mỗi vòng xử lý tạo ra một CognitiveFrame: ảnh chụp đầy đủ của một chu kỳ nhận thức.
        self.cognitive_cycle_index = 0
        self.cognitive_frames: list[CognitiveFrame] = []
        self.last_cognitive_frame: CognitiveFrame | None = None
        self.mental_process_interval_sec = self._load_mental_process_interval()
        self.mental_process_enabled = self._load_mental_process_enabled()
        self._mental_process_stop_event = threading.Event()
        self._mental_process_thread: threading.Thread | None = None
        #Load bộ nhớ dài hạn từ memory core.
        self.long_term_memory = []
        self.memory_state = self._load_memory_state()
        self.long_term_memory = self._memory_recall_texts()
        self.active_memory_resonance = None
        self.last_grounding_context = None
        self.fe_style_memory = self.fe_renderer.create_memory()
        self.vision_facts_enabled, self.vision_interval_sec, self.vision_fact_max_items, self.vision_fact_max_len = (
            self._load_vision_fact_settings()
        )
        self.vision_facts: tuple[str, ...] = ()
        self.vision_last_capture_at = 0.0
        self.vision_disabled_until = 0.0
        self.vision_failure_count = 0
        self.vision_last_trace = ""
        self.vision_facts_signature = ""
        self.vision_facts_novelty_hint = "none"
        # NiStateMachine giữ state drift rời rạc theo thời gian (ON_GOAL / BORDERLINE / OFF_GOAL)
        #  dựa trên chuỗi GoalDriftReport, thay vì chỉ nhìn một snapshot đơn lẻ.
        self.autonomous_ni_state = NiStateMachine()
        self.chat_ni_state = NiStateMachine()
        #ThoughtStream là dòng suy nghĩ nền. Nó có thể sinh seed, tension, unresolved loops, attractor
        #nó giữ “mạch suy nghĩ ngầm” để ERIS không reset như cá vàng sau mỗi message
        self.thought_stream = ThoughtStream(
            context_provider=self._build_thought_stream_context,
            logger=self.logger,
        )
        self.subconscious_loop = self.thought_stream
        self.cognitive_substrate = self.thought_stream
        # Đọc biến môi trường để bật/tắt tầng Ni meta critic.
        flag = os.environ.get("ERIS_NI_META_CRITIC", "1").strip().lower()
        env_enabled = flag not in {"0", "false", "no", "off"}
        chat_cfg, auto_cfg = self._load_ni_meta_mode_flags()
        self.ni_meta_env_enabled = env_enabled
        #Tách riêng mode chat và autonomous.
        self.ni_meta_chat_enabled = env_enabled and chat_cfg
        self.ni_meta_auto_enabled = env_enabled and auto_cfg
        #Đảm bảo trong memory_state có internal_state. Nếu thiếu thì tạo mới.
        self._ensure_internal_state()

    def _log_raw_llm_output(self, channel: str, raw: str) -> None:
        preview = (raw or "").replace("\n", "\\n")
        if len(preview) > 5500:
            preview = preview[:5500].rstrip() + "..."
        self.logger.info("[%s raw] %s", channel, preview or "<empty>")

    def _preview_text(self, text: str, *, limit: int = 1000) -> str:
        preview = (text or "").replace("\n", "\\n").strip()
        if len(preview) > limit:
            preview = preview[:limit].rstrip() + "..."
        return preview or "<empty>"

    def _infer_active_conversational_topic(self, user_text: str, *, fe_plan=None, ti_report=None) -> str:
        normalized = self._normalize_user_message(user_text)
        if any(marker in normalized for marker in ("biết gì về tôi", "biết gì về mình", "bạn biết gì về tôi")):
            return "user_self_knowledge"
        if any(marker in normalized for marker in ("nói thử xem", "thử nói xem", "bạn nói thử", "nói đi")):
            return self.active_conversational_topic or "follow_up"
        intent = str(getattr(fe_plan, "intent_label", "") or "").strip()
        if intent:
            return intent[:80]
        mode = str(getattr(ti_report, "mode", "") or "").strip()
        return mode[:80] if mode else ""

    def _handle_incoming(self, msg: dict):
        msg_type = msg.get("type", "")
        if msg_type == "chat_start":
            self._enter_chat_cycle()
            return

        if msg_type == "chat":
            self._run_chat_cycle(str(msg.get("message", "") or "").strip())
            return

        if msg_type == "force_speak":
            self._handle_force_speak_request()
            return

        if msg_type == "chat_end":
            self._end_chat_cycle()
            return
