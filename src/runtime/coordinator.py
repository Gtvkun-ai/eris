import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata

from dataclasses import dataclass, replace

from cortex.action_planner import ACTION_SPACE, ActionPlanner
from cortex.attention import AttentionWorkspace
from cortex.appraisal import AppraisalEngine
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
)
from cortex.inner_thought import InnerThoughtEngine
from cortex.internal_state import InternalStateEngine, PersistentInternalState
from cortex.meaning import MeaningLayer
from cortex.micro_policy import MicroLinePolicy, SemanticRepeatGuard
from cortex.ni import NiStateMachine
from cortex.personality import PersonalityLens
from cortex.self_model import SelfModelEngine
from cortex.session_ritual import SessionRitualEngine
from cortex.speech_core import SpeechCoreEngine
from cortex.thought_stream import ThoughtStream
from domain import Decision

'''coordinator.py là “bộ điều phối runtime” (orchestrator) cho ERIS: nó đứng giữa telemetry 
(màn hình/hành vi), các tầng đánh giá (Ni/Ti/FE), LLM + parser, action system và kênh transport để quyết định
 “lúc nào nói/câm”, “nói gì”, “có thực thi action không”, rồi gửi Decision ra “body” (Godot) qua UDP.
'''


SPEECH_INTENTS = (
    "no_speech",
    "brief_ack",
    "screen_observation",
    "micro_observation",
    "user_requested",
    "system_warning",
    "playful_aside",
    "presence_maintenance",
    "micro_presence",
    "re_engagement",
    "curious_question",
    "social_presence",
)

VISION_TRACE_MARKER = "vision_facts_attached"
FORCE_SPEAK_RECENT_FAMILY_WINDOW = 5
FORCE_SPEAK_BANNED_FAMILIES = {
    "presence_declaration": (
        "tôi đang hiện diện",
        "tôi ở đây",
        "tôi vẫn ở đây",
        "tôi nghe đây",
        "tôi vẫn đang quan sát",
        "tôi vẫn đang theo dõi",
    ),
    "small_story_listener": (
        "câu chuyện nhỏ",
        "một người nghe",
        "không cần màn hình",
        "không cần phải có màn hình",
    ),
    "log_meta": (
        "dòng log khô khan",
        "ngồi nhìn log",
    ),
    "internal_meaning_label": (
        "escape_from_friction",
        "cognitive_stall",
        "scattered_attention",
        "friction_point",
        "decompression",
        "avoidance",
        "ngai dang ne friction",
        "ngai dang ne tranh",
        "ngai dang bi ket nhan thuc",
        "ngai dang phan tan chu y",
    ),
}
FALLBACK_BY_INTENT = {
    "random_chatter": (
        "hm. đoạn này có mùi né việc.",
        "yên quá. tôi bắt đầu nghi ngờ rồi đấy.",
    ),
    "inner_whim": (
        "cái im lặng này không sạch lắm.",
        "mạch này vẫn hơi lệch một chút.",
    ),
    "social_presence": (
        "Ngài bỏ tôi canh nhịp này à.",
        "yên thế này là hơi đáng ngờ.",
    ),
    "micro_presence": (
        "nhịp này vẫn hơi nghẽn.",
        "không khí hiện tại hơi lệch.",
    ),
    "indirect_presence": (
        "toi nghe phan do, nhung chua voi goi ten.",
        "cu de no nam do mot chut.",
    ),
    "guarded_reply": (
        "toi nghe roi. do la phan nang, khong can vo ve voi vang.",
        "co gi do nang that, nhung toi se khong lam no sen.",
    ),
    "micro_observation": (
        "lại thấy {anchor} trên màn hình rồi.",
        "{anchor} vẫn đang mở đó à.",
    ),
    "curious_question": (
        "Tôi tò mò một chút: Ngài muốn giữ nhịp này yên hơn hay sắc hơn?",
        "Có phần nào trong mạch này đang làm Ngài muốn nhìn kỹ hơn không?",
    ),
    "screen_observation": (
        "Tôi chỉ dám bám vào chỗ này: {anchor}.",
        "Điểm rõ nhất hiện tại là: {anchor}.",
    ),
}


@dataclass(frozen=True, slots=True)
class SpeechIntentDecision:
    intent: str
    reason: str


@dataclass(frozen=True, slots=True)
class MicroPresenceSynthesis:
    kind: str
    seeds: tuple[str, ...] = ()
    context: dict[str, str] | None = None
    fallback_text: str = "Mạch này vẫn hơi nghẽn."
    should_verbalize: bool = True


@dataclass(frozen=True, slots=True)
class SocialPresenceEvent:
    present: bool
    kind: str = ""
    confidence: float = 0.0
    intensity: float = 0.0
    speech_allowed: bool = False
    reason: str = ""
    evidence: tuple[str, ...] = ()
    timestamp: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "present": bool(self.present),
            "confidence": round(float(self.confidence), 3),
            "intensity": round(float(self.intensity), 3),
            "kind": self.kind,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "timestamp": self.timestamp,
            "source": "runtime_coordinator",
            "speech_allowed": bool(self.speech_allowed),
        }


class RuntimeCoordinator:
    def __init__(
        self,
        *,
        logger,
        transport,
        llm_service,
        parser,
        telemetry_service,
        ni_engine,
        ti_governor,
        fe_renderer,
        memory_store,
        body_running_fn,
        action_executor=None,
        action_router=None,
    ):
        self.logger = logger
        self.transport = transport
        self.llm_service = llm_service
        self.parser = parser
        self.telemetry_service = telemetry_service
        self.ni_engine = ni_engine
        self.ti_governor = ti_governor
        self.fe_renderer = fe_renderer
        self.memory_store = memory_store
        self.body_running_fn = body_running_fn
        self.action_executor = action_executor
        self.action_router = action_router
        self.attention_workspace = AttentionWorkspace()
        self.meaning_layer = MeaningLayer()
        self.personality_lens = PersonalityLens()
        self.appraisal_engine = AppraisalEngine()
        self.internal_state_engine = InternalStateEngine()
        self.inner_thought_engine = InnerThoughtEngine()
        self.self_model_engine = SelfModelEngine()
        self.session_ritual_engine = SessionRitualEngine()
        self.speech_core_engine = SpeechCoreEngine(inner_thought_engine=self.inner_thought_engine)
        self.action_planner = ActionPlanner()
        self.semantic_repeat_guard = SemanticRepeatGuard()
        self.micro_line_policy = MicroLinePolicy(repeat_guard=self.semantic_repeat_guard)
        self._state_lock = threading.RLock()

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
        self.mood_score = 50
        self.inferred_pos_x = 0.5
        self.idle_cycles = 0
        self.last_autonomous_signature = ""
        self.repeated_autonomous_count = 0
        self.last_autonomous_spoken_at = 0.0
        self.presence_maintenance_silent_cycles = 0
        self.last_presence_maintenance_at = 0.0
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
        self.cognitive_cycle_index = 0
        self.cognitive_frames: list[CognitiveFrame] = []
        self.last_cognitive_frame: CognitiveFrame | None = None
        self.mental_process_interval_sec = self._load_mental_process_interval()
        self.mental_process_enabled = self._load_mental_process_enabled()
        self._mental_process_stop_event = threading.Event()
        self._mental_process_thread: threading.Thread | None = None
        self.long_term_memory = []
        self.memory_state = self._load_memory_state()
        self.long_term_memory = self._memory_recall_texts()
        self.active_memory_resonance = None
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
        self.thought_stream = ThoughtStream(
            context_provider=self._build_thought_stream_context,
            logger=self.logger,
        )
        self.subconscious_loop = self.thought_stream
        self.cognitive_substrate = self.thought_stream
        # Bật/tắt tầng suy luận nhẹ của Ni theo mode.
        # Giữ tên env/config cũ để tương thích ngược.
        flag = os.environ.get("ERIS_NI_META_CRITIC", "1").strip().lower()
        env_enabled = flag not in {"0", "false", "no", "off"}
        chat_cfg, auto_cfg = self._load_ni_meta_mode_flags()
        self.ni_meta_env_enabled = env_enabled
        self.ni_meta_chat_enabled = env_enabled and chat_cfg
        self.ni_meta_auto_enabled = env_enabled and auto_cfg
        self._ensure_internal_state()

    def _log_raw_llm_output(self, channel: str, raw: str) -> None:
        preview = (raw or "").replace("\n", "\\n")
        if len(preview) > 500:
            preview = preview[:500] + "...(truncated)"
        self.logger.info("[%s raw] %s", channel, preview or "<empty>")

    def _preview_text(self, text: str, *, limit: int = 240) -> str:
        preview = (text or "").replace("\n", "\\n").strip()
        if len(preview) > limit:
            preview = preview[:limit] + "...(truncated)"
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

    def _load_memory_state(self):
        loader = getattr(self.memory_store, "load_state", None)
        if not callable(loader):
            return None
        try:
            return loader()
        except Exception as exc:
            self.logger.warning("Memory state load error: %s", exc)
            return None

    def _has_structured_memory_store(self) -> bool:
        return self.memory_state is not None and callable(getattr(self.memory_store, "remember_cycle", None))

    def _ensure_internal_state(self) -> None:
        if self.memory_state is None:
            return
        if getattr(self.memory_state, "internal_state", None) is None:
            self.memory_state.internal_state = PersistentInternalState()

    def _get_internal_state(self) -> PersistentInternalState:
        if self.memory_state is not None and getattr(self.memory_state, "internal_state", None) is not None:
            return self.memory_state.internal_state
        return PersistentInternalState()

    def _set_internal_state(self, state: PersistentInternalState) -> None:
        if self.memory_state is None:
            return
        with self._state_lock:
            self.memory_state.internal_state = state
            self._save_memory_state()

    def _build_internal_state_context(self, state: PersistentInternalState | None = None, self_state=None) -> str:
        state_context = self.internal_state_engine.render_prompt_context(state or self._get_internal_state())
        prompt_context = str(getattr(self_state, "prompt_context", "") or "").strip()
        if prompt_context:
            return f"{state_context}\n{prompt_context}"
        return state_context

    def _build_thought_stream_context(self) -> dict[str, object]:
        with self._state_lock:
            mood_score = self.mood_score
            inferred_pos_x = self.inferred_pos_x
            internal_state = self._get_internal_state()
            long_term_memory = tuple(self.long_term_memory or ())
            last_text = self.last_text
            recent_inner_seeds = tuple(self.recent_inner_thought_seeds or ())
            recent_thought_seeds = tuple(getattr(internal_state, "recent_thought_seeds", ()) or ())
            recent_subconscious = tuple(getattr(internal_state, "recent_subconscious_seeds", ()) or ())
        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
        return {
            "snapshot": snapshot,
            "internal_state": internal_state,
            "long_term_memory": long_term_memory,
            "last_text": last_text,
            "recent_inner_seeds": recent_inner_seeds,
            "recent_thought_seeds": recent_thought_seeds,
            "recent_subconscious_seeds": recent_subconscious,
        }

    def _build_subconscious_context(self) -> dict[str, object]:
        return self._build_thought_stream_context()

    def _make_cognitive_disturbance(
        self,
        *,
        channel: str,
        kind: str,
        content: str,
        evidence: tuple[str, ...] = (),
        intensity: float = 1.0,
    ) -> CognitiveDisturbance | None:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        if not text:
            return None
        return CognitiveDisturbance(
            channel=str(channel or ""),
            kind=str(kind or ""),
            content=text[:240],
            evidence=tuple(str(item) for item in (evidence or ()) if str(item or "").strip())[:6],
            intensity=self._bounded_float(intensity),
            timestamp=time.time(),
            closes_loop=self._looks_like_closure_disturbance(text),
        )

    def _looks_like_closure_disturbance(self, content: str) -> bool:
        normalized = self._normalize_user_message(content)
        return any(
            token in normalized
            for token in (
                "done",
                "fixed",
                "resolved",
                "solved",
                "complete",
                "completed",
                "xong",
                "đã xong",
                "giải quyết",
            )
        )

    def _build_event_disturbances(
        self,
        *,
        channel: str,
        snapshot=None,
        user_text: str = "",
        force_speak: bool = False,
        vision_facts: tuple[str, ...] = (),
    ) -> tuple[CognitiveDisturbance, ...]:
        disturbances: list[CognitiveDisturbance] = []
        if user_text:
            disturbance = self._make_cognitive_disturbance(
                channel=channel,
                kind="user_message",
                content=user_text,
                evidence=("direct_user_input",),
                intensity=1.0,
            )
            if disturbance is not None:
                disturbances.append(disturbance)

        if force_speak:
            disturbance = self._make_cognitive_disturbance(
                channel=channel,
                kind="user_force_speak",
                content="force_speak requested",
                evidence=tuple(vision_facts or ())[:3] or ("ui_request",),
                intensity=0.96,
            )
            if disturbance is not None:
                disturbances.append(disturbance)

        if channel == "autonomous":
            recent_events = tuple(str(item) for item in (getattr(snapshot, "recent_events", ()) or ())[:3])
            evidence = tuple(str(item) for item in (getattr(snapshot, "evidence", ()) or ())[:3])
            active = str(getattr(snapshot, "active_window_kind", "") or getattr(snapshot, "active_window", "") or "ambient")
            idle = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
            content = f"autonomous tick: focus={active}; idle={int(idle)}s"
            if recent_events:
                content = f"{content}; events={', '.join(recent_events[:2])}"
            intensity = 0.34 + min(0.18, idle / 1800.0)
            if recent_events or evidence or vision_facts:
                intensity += 0.16
            disturbance = self._make_cognitive_disturbance(
                channel=channel,
                kind="autonomous_tick",
                content=content,
                evidence=tuple(dict.fromkeys((*recent_events, *evidence, *tuple(vision_facts or ()))))[:6],
                intensity=intensity,
            )
            if disturbance is not None:
                disturbances.append(disturbance)

        return tuple(disturbances)

    def _disturb_cognitive_substrate(
        self,
        *,
        channel: str,
        snapshot=None,
        user_text: str = "",
        force_speak: bool = False,
        vision_facts: tuple[str, ...] = (),
        consume_surface: bool = False,
    ) -> ThoughtStreamReport:
        disturbances = self._build_event_disturbances(
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            force_speak=force_speak,
            vision_facts=vision_facts,
        )
        substrate = getattr(self, "cognitive_substrate", self.thought_stream)
        report = substrate.latest_report() if callable(getattr(substrate, "latest_report", None)) else ThoughtStreamReport()
        injector = getattr(substrate, "inject_disturbances", None)
        if disturbances and callable(injector):
            report = injector(disturbances, immediate=True, queue_surface=False)
        if consume_surface and not getattr(getattr(report, "latest_seed", None), "mode", ""):
            pop_surface = getattr(substrate, "pop_surface", None)
            if callable(pop_surface):
                report = self._with_thought_stream_surface(report, pop_surface())
        return report

    def _with_thought_stream_surface(self, report: ThoughtStreamReport, surface) -> ThoughtStreamReport:
        if surface is None or not getattr(surface, "mode", ""):
            return report
        return ThoughtStreamReport(
            latest_seed=surface,
            recent_seeds=getattr(report, "recent_seeds", ()),
            surface_pressure=max(float(getattr(report, "surface_pressure", 0.0) or 0.0), float(getattr(surface, "pressure", 0.0) or 0.0)),
            suppression_reason="",
            latest_thought=getattr(report, "latest_thought", None) or ThoughtStreamReport().latest_thought,
            recent_thoughts=getattr(report, "recent_thoughts", ()),
            momentum=getattr(report, "momentum", None) or ThoughtStreamReport().momentum,
            recent_momentum=getattr(report, "recent_momentum", ()),
            active_attractor=getattr(report, "active_attractor", None) or ThoughtStreamReport().active_attractor,
            unresolved_loops=getattr(report, "unresolved_loops", ()),
            stream_tension=float(getattr(report, "stream_tension", 0.0) or 0.0),
            unresolved_count=int(getattr(report, "unresolved_count", 0) or 0),
            continuity_notes=tuple(getattr(report, "continuity_notes", ()) or ()),
            disturbances=tuple(getattr(report, "disturbances", ()) or ()),
        )

    def _pop_thought_stream_report_for_autonomous(self) -> ThoughtStreamReport:
        surface = self.thought_stream.pop_surface()
        latest = self.thought_stream.latest_report()
        if not surface.mode:
            return ThoughtStreamReport(
                recent_seeds=latest.recent_seeds,
                surface_pressure=latest.surface_pressure,
                suppression_reason=latest.suppression_reason or "no_surface_seed",
                latest_thought=latest.latest_thought,
                recent_thoughts=latest.recent_thoughts,
                momentum=latest.momentum,
                recent_momentum=latest.recent_momentum,
                active_attractor=latest.active_attractor,
                unresolved_loops=latest.unresolved_loops,
                stream_tension=latest.stream_tension,
                unresolved_count=latest.unresolved_count,
                continuity_notes=latest.continuity_notes,
                disturbances=latest.disturbances,
            )
        return ThoughtStreamReport(
            latest_seed=surface,
            recent_seeds=latest.recent_seeds,
            surface_pressure=surface.pressure,
            suppression_reason="",
            latest_thought=latest.latest_thought,
            recent_thoughts=latest.recent_thoughts,
            momentum=latest.momentum,
            recent_momentum=latest.recent_momentum,
            active_attractor=latest.active_attractor,
            unresolved_loops=latest.unresolved_loops,
            stream_tension=latest.stream_tension,
            unresolved_count=latest.unresolved_count,
            continuity_notes=latest.continuity_notes,
            disturbances=latest.disturbances,
        )

    def _pop_subconscious_report_for_autonomous(self) -> SubconsciousReport:
        return self._pop_thought_stream_report_for_autonomous()

    #Lưu trạng thái bộ nhớ sau mỗi chu kỳ, nếu bộ nhớ có hỗ trợ.
    def _save_memory_state(self) -> None:
        if self.memory_state is None:
            return
        saver = getattr(self.memory_store, "save_state", None)
        if not callable(saver):
            return
        try:
            saver(self.memory_state)
        except Exception as exc:
            self.logger.warning("Memory state save error: %s", exc)

    #Truy vấn bộ nhớ dài hạn để lấy các thông tin đã ghi nhớ trước đó, nếu bộ nhớ có hỗ trợ.
    def _memory_recall_texts(self, *, snapshot=None) -> list[str]:
        recall = getattr(self.memory_store, "recall_texts", None) #hàm này trả về một iterable các đoạn text đã ghi nhớ, có thể dựa trên snapshot hiện tại để lọc/định hướng
        if self.memory_state is not None and callable(recall): #nếu bộ nhớ có trạng thái cấu trúc và hỗ trợ truy vấn, thì gọi hàm recall để lấy các đoạn text đã ghi nhớ, có thể dựa trên snapshot hiện tại để lọc/định hướng
            try:
                return list(recall(self.memory_state, snapshot=snapshot))
            except Exception as exc:
                self.logger.warning("Memory recall error: %s", exc)
        return list(getattr(self, "long_term_memory", []) or []) #nếu không có bộ nhớ cấu trúc hoặc truy vấn lỗi, thì fallback về long_term_memory đã lưu ở coordinator, vốn được cập nhật sau mỗi chu kỳ

    def _activate_memory_resonance(
        self,
        *,
        snapshot=None,
        user_text: str = "",
        channel: str = "",
        fragments: tuple[str, ...] = (),
    ):
        activator = getattr(self.memory_store, "activate_memory_resonance", None)
        if self.memory_state is None or not callable(activator):
            self.active_memory_resonance = None
            return None
        try:
            report = activator(
                self.memory_state,
                snapshot=snapshot,
                user_text=user_text,
                channel=channel,
                fragments=fragments,
            )
        except Exception as exc:
            self.logger.warning("Memory resonance activation error: %s", exc)
            self.active_memory_resonance = None
            return None
        self.active_memory_resonance = report
        return report

    def _thought_stream_resonance_fragments(self) -> tuple[str, ...]:
        report = self.thought_stream.latest_report()
        thought = getattr(report, "latest_thought", None)
        momentum = getattr(report, "momentum", None)
        attractor = getattr(report, "active_attractor", None)
        fragments: list[str] = []
        if thought is not None:
            fragments.extend(
                str(item)
                for item in (
                    getattr(thought, "topic_seed", ""),
                    getattr(thought, "partial_text", ""),
                    getattr(thought, "unresolved_reason", ""),
                    getattr(thought, "source_memory", ""),
                    *tuple(getattr(thought, "associations", ()) or ())[:3],
                )
                if str(item or "").strip()
            )
        if momentum is not None and getattr(momentum, "unresolved", False):
            fragments.append(
                " ".join(
                    str(item)
                    for item in (
                        getattr(momentum, "topic_seed", ""),
                        getattr(momentum, "affordance", ""),
                        getattr(momentum, "closure_state", ""),
                    )
                    if str(item or "").strip()
                )
            )
        if attractor is not None and getattr(attractor, "attractor", False):
            fragments.append(
                " ".join(
                    str(item)
                    for item in (
                        getattr(attractor, "topic_seed", ""),
                        "unresolved_tension_loop",
                    )
                    if str(item or "").strip()
                )
            )
        return tuple(item for item in fragments[-8:] if item)

    def _memory_attention_lines(self) -> tuple[str, ...]:
        report = getattr(self, "active_memory_resonance", None)
        to_attention_lines = getattr(report, "to_attention_lines", None)
        if not callable(to_attention_lines):
            return ()
        try:
            return tuple(to_attention_lines())
        except Exception as exc:
            self.logger.warning("Memory resonance attention render error: %s", exc)
            return ()

    def _build_memory_context(self, snapshot=None, memory_resonance=None) -> str:
        renderer = getattr(self.memory_store, "render_context", None)
        context = ""
        if self.memory_state is not None and callable(renderer):
            try:
                context = renderer(self.memory_state, snapshot=snapshot)
            except Exception as exc:
                self.logger.warning("Memory context render error: %s", exc)
        report = memory_resonance if memory_resonance is not None else getattr(self, "active_memory_resonance", None)
        render_resonance = getattr(report, "render_prompt_context", None)
        if callable(render_resonance):
            try:
                resonance_context = render_resonance()
                if resonance_context:
                    return f"{context}\n\n{resonance_context}".strip()
            except Exception as exc:
                self.logger.warning("Memory resonance context render error: %s", exc)
        return context

    #So sánh snapshot hiện tại với chuẩn đã xây dựng trong bộ nhớ, trả về các điểm khác biệt đáng chú ý để làm tín hiệu cho tầng đánh giá và quyết định.
    def _norm_deviation_texts(self, snapshot) -> tuple[str, ...]:
        comparator = getattr(self.memory_store, "compare_to_norms", None)
        if self.memory_state is None or not callable(comparator):
            return ()
        try:
            deviations = comparator(self.memory_state, snapshot)
        except Exception as exc:
            self.logger.warning("Norm memory compare error: %s", exc)
            return ()
        rendered: list[str] = []
        for deviation in deviations or ():
            to_event_text = getattr(deviation, "to_event_text", None)
            if callable(to_event_text):
                rendered.append(str(to_event_text()))
            else:
                rendered.append(str(deviation))
        return tuple(item for item in rendered if item.strip())

    #Ghi nhận snapshot hiện tại vào bộ nhớ để cập nhật chuẩn, nếu bộ nhớ có hỗ trợ. Điều này nên được gọi sau khi đã quyết định xong broadcast và action plan, để tránh việc chuẩn bị bị ảnh hưởng bởi những thay đổi trong chu kỳ hiện tại.
    def _note_norm_observation(self, snapshot) -> None:
        updater = getattr(self.memory_store, "update_norms", None)
        if self.memory_state is None or not callable(updater):
            return
        try:
            self.memory_state = updater(self.memory_state, snapshot, timestamp=self._event_timestamp(snapshot))
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            self._save_memory_state()
        except Exception as exc:
            self.logger.warning("Norm memory update error: %s", exc)

    #Ghi nhận một chu kỳ hoàn chỉnh vào bộ nhớ, bao gồm những gì đã thấy (seen), đã nói (said), kết quả (outcome), và các tag liên quan. Điều này giúp xây dựng bộ nhớ dài hạn dựa trên trải nghiệm thực tế của ERIS, và có thể được sử dụng để cải thiện các quyết định trong tương lai.
    def _remember_cognitive_frame(self, frame: CognitiveFrame) -> None:
        remember_cycle = getattr(self.memory_store, "remember_cycle", None)
        #Kiểm tra memory store có hỗ trợ ghi structured memory không
        if self.memory_state is None or not callable(remember_cycle):
            return

        timestamp = ""
        if frame.percepts: #Ưu tiên timestamp của percept đầu tiên trong frame.
            timestamp = frame.percepts[0].timestamp
        if not timestamp: #Nếu không có thì fallback sang thời gian started_at của cycle, hoặc time.now
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(frame.started_at or time.time()))

        # Ưu tiên nội dung từ frame.broadcast.items (tín hiệu đã được attention chọn).
        if frame.broadcast.items:#Nếu có broadcast items, lấy content của chúng làm "seen", vì đây là những thông tin đã được chọn để chú ý trong chu kỳ này.
            seen = tuple(item.content for item in frame.broadcast.items if item.content)
        elif frame.broadcast.content: #Nếu không có items nhưng có broadcast content, thì lấy content này làm "seen", vì đây là tín hiệu tổng quát đã được phát đi trong chu kỳ này.
            seen = (frame.broadcast.content,) 
        else: #Nếu vẫn không có thì fallback lấy tối đa 2 attention_candidates đầu tiên.
            seen = tuple(item.content for item in frame.attention_candidates[:2] if item.content)

        final_text = str(frame.final_decision.get("text", "") or "")
        parse_mode = str(frame.final_decision.get("parse_mode", "") or "")
        outcome = parse_mode or frame.action_plan.speech_intent or "cycle"
        if frame.action_plan.system_action:
            outcome = f"{outcome}:{frame.action_plan.system_action}"

        tags = tuple( #Tags giúp filter/truy vết episode sau này.
            item
            for item in (
                frame.channel,
                frame.action_plan.speech_intent,
                frame.action_plan.speech_act,
                frame.broadcast.label,
            )
            if item
        )
        explicit_user_facts = tuple(
            fact
            for fact in (
                self._extract_explicit_user_memory_fact(percept.content)
                for percept in tuple(frame.percepts or ())
                if percept.kind == "user_message"
            )
            if fact
        )
        semantic_fact = frame.memory_update.remembered_fact or (explicit_user_facts[0] if explicit_user_facts else "")
        before_episodes = len(getattr(self.memory_state, "episodic", []) or [])
        try:
            self.memory_state = remember_cycle(
                self.memory_state,
                cycle_id=frame.cycle_id,
                channel=frame.channel,
                timestamp=timestamp,
                seen=tuple(seen),
                said=final_text,
                outcome=outcome,
                salience=float(frame.broadcast.score or 0.0),
                tags=tags,
                semantic_fact=semantic_fact,
                system_action=frame.action_plan.system_action,
            )
            remember_fact = getattr(self.memory_store, "remember_semantic_fact", None)
            if callable(remember_fact):
                remaining_user_facts = explicit_user_facts[1:] if semantic_fact in explicit_user_facts else explicit_user_facts
                for fact in remaining_user_facts:
                    if fact and fact != semantic_fact:
                        self.memory_state = remember_fact(
                            self.memory_state,
                            fact,
                            source="explicit_user_statement",
                            timestamp=timestamp,
                        )
            self._remember_relationship_reflections(frame, timestamp=timestamp)
            if semantic_fact and not frame.memory_update.semantic_fact:
                frame.memory_update.semantic_fact = semantic_fact
            if getattr(self.memory_state, "working", None):
                frame.memory_update.working_summary = self.memory_state.working[-1].summary
            episodes = getattr(self.memory_state, "episodic", []) or []
            if len(episodes) > before_episodes:
                frame.memory_update.episodic_summary = episodes[-1].summary()
            self.long_term_memory = self._memory_recall_texts()
            self._save_memory_state()
        except Exception as exc:
            self.logger.warning("Cognitive memory commit error: %s", exc)

    def _remember_relationship_reflections(self, frame: CognitiveFrame, *, timestamp: str) -> None:
        remember_reflection = getattr(self.memory_store, "remember_relationship_reflection", None)
        if self.memory_state is None or not callable(remember_reflection):
            return

        reflections = self._derive_relationship_reflections(frame)
        if not reflections:
            return

        recorded: list[str] = []
        for pattern, text, evidence in reflections:
            self.memory_state = remember_reflection(
                self.memory_state,
                text,
                pattern=pattern,
                source="cognitive_frame_reflection",
                timestamp=timestamp,
                evidence=evidence,
            )
            recorded.append(text)
        frame.memory_update.relationship_reflection = " | ".join(recorded)[:260]

    def _derive_relationship_reflections(self, frame: CognitiveFrame) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        reflections: list[tuple[str, str, tuple[str, ...]]] = []
        channel = str(frame.channel or "")
        speech_act = str(getattr(frame.action_plan, "speech_act", "") or "")
        parse_mode = str(frame.final_decision.get("parse_mode", "") or "")
        notes = tuple(str(item) for item in (getattr(frame.action_plan, "notes", ()) or ()))
        risk_flags = tuple(str(item) for item in (getattr(frame.action_plan, "risk_flags", ()) or ()))
        inner = getattr(frame, "inner_thought", None)
        inner_intent = str(getattr(inner, "intent", "") or "")
        inner_motive = str(getattr(inner, "motive", "") or "")
        inner_seed = str(getattr(inner, "topic_seed", "") or "")

        if channel == "force_speak" and parse_mode in {"inner_thought", "micro_presence"}:
            reflections.append(
                (
                    "force_speak_micro_presence",
                    "Ngài hay bấm force_speak khi muốn ERIS hiện diện hơn là cần thông tin.",
                    (
                        f"speech_act={speech_act}",
                        f"inner_intent={inner_intent}",
                        f"said={str(frame.final_decision.get('text', '') or '')[:80]}",
                    ),
                )
            )

        if parse_mode in {"inner_thought", "micro_presence"} and "no_screen_claim" in risk_flags:
            reflections.append(
                (
                    "no_screen_signal_social_fallback",
                    "Khi thiếu screen signal, ERIS nên hỏi lại hoặc mở một câu tò mò, không giả vờ thấy gì.",
                    (
                        f"channel={channel}",
                        f"motive={inner_motive}",
                        f"seed={inner_seed[:80]}",
                    ),
                )
            )

        user_texts = tuple(
            percept.content
            for percept in tuple(frame.percepts or ())
            if percept.kind == "user_message" and percept.content
        )
        for text in user_texts:
            style_reflection = self._extract_relationship_style_reflection(text)
            if style_reflection:
                reflections.append(style_reflection)

        if any("inner_thought=" in note for note in notes) and parse_mode == "inner_thought":
            reflections.append(
                (
                    "social_initiative_rhythm",
                    "ERIS có thể giữ nhịp hiện diện bằng một câu meta hoặc check-in ngắn, miễn là không dựng cảnh màn hình.",
                    (f"channel={channel}", f"speech_act={speech_act}"),
                )
            )

        deduped: list[tuple[str, str, tuple[str, ...]]] = []
        seen: set[str] = set()
        for pattern, text, evidence in reflections:
            key = self._normalize_user_message(f"{pattern} {text}")
            if key in seen:
                continue
            seen.add(key)
            deduped.append((pattern, text, evidence))
        return tuple(deduped[:4])

    def _extract_relationship_style_reflection(self, user_text: str) -> tuple[str, str, tuple[str, ...]] | None:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return None

        likes_cold_soft = any(
            self._normalize_user_message(marker) in normalized
            for marker in (
                "giọng lạnh",
                "lạnh nhẹ",
                "giọng lạnh nhẹ",
                "cold soft",
                "hơi lạnh",
            )
        )
        dislikes_telemetry = any(
            self._normalize_user_message(marker) in normalized
            for marker in (
                "không thích báo cáo telemetry",
                "không thích giọng telemetry",
                "đừng báo cáo telemetry",
                "tránh báo cáo telemetry",
                "không như log",
                "đừng nói như log",
            )
        )
        if likes_cold_soft and dislikes_telemetry:
            return (
                "style_preference",
                "Ngài thích giọng lạnh nhẹ, nhưng không thích báo cáo telemetry.",
                (f"user_text={user_text[:120]}",),
            )
        if likes_cold_soft:
            return (
                "style_preference",
                "Ngài thích giọng lạnh nhẹ và có kiểm soát.",
                (f"user_text={user_text[:120]}",),
            )
        if dislikes_telemetry:
            return (
                "style_preference",
                "Ngài không thích ERIS nói như báo cáo telemetry hoặc log hệ thống.",
                (f"user_text={user_text[:120]}",),
            )
        return None

    def _extract_explicit_user_memory_fact(self, user_text: str) -> str:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return ""

        stable_markers = (
            "tôi thích",
            "tôi không thích",
            "tôi thường",
            "tôi hay",
            "gọi tôi là",
            "cứ gọi tôi",
            "quy ước",
            "nhớ rằng",
            "hãy nhớ",
            "i prefer",
            "i usually",
            "call me",
            "remember that",
        )
        if not any(marker in normalized for marker in stable_markers):
            return ""
        compact = re.sub(r"\s+", " ", str(user_text or "").strip())
        if not compact:
            return ""
        return f"User stated: {compact[:180]}"

    def _next_cognitive_cycle_id(self, channel: str) -> str:
        self.cognitive_cycle_index += 1
        return f"{channel}-{self.cognitive_cycle_index}"

    def _bounded_float(self, value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    # _event_timestamp là hàm tạo “mốc thời gian” (timestamp dạng chuỗi) để gắn cho các event/percept trong một chu kỳ.
    def _event_timestamp(self, snapshot=None, *, started_at: float | None = None) -> str:
        captured_at = str(getattr(snapshot, "captured_at", "") or getattr(snapshot, "time", "") or "").strip()
        if captured_at:
            return captured_at
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at or time.time()))

    #chống “spam evidence”, tránh trùng lặp, và giữ payload gọn/ổn định khi log/telemetry.
    def _normalize_event_evidence(self, evidence, *, limit: int = 4) -> tuple[str, ...]:
        items: list[str] = []
        seen: set[str] = set()
        for item in evidence or ():
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            items.append(text[:160])
            seen.add(key)
            if len(items) >= limit:
                break
        return tuple(items)

    #hàm này đảm bảo event tạo ra luôn có content thật, các field không bị rỗng/bẩn, và payload không bị phình
    def _make_percept_event(
        self,
        *,
        #Nhận các field
        kind: str,
        content: str,
        timestamp: str,
        evidence=(),
        confidence: float = 1.0,
        source: str = "runtime",
        privacy_level: str = "internal",
        novelty_hint: str = "routine",
    ) -> PerceptEvent | None:
        text = str(content or "").strip()
        if not text:
            return None
        return PerceptEvent(
            kind=str(kind or "unknown").strip() or "unknown",
            content=text[:260],
            evidence=self._normalize_event_evidence(evidence),
            confidence=self._bounded_float(confidence),
            source=str(source or "runtime").strip() or "runtime",
            timestamp=timestamp,
            privacy_level=str(privacy_level or "internal").strip() or "internal",
            novelty_hint=str(novelty_hint or "routine").strip() or "routine",
        )

    # quyết định mức “nhạy cảm/riêng tư” (privacy_level) theo loại telemetry
    def _telemetry_event_privacy_level(self, kind: str) -> str:
        if kind == "resource_pressure":
            return "system_metric" #chỉ số hệ thống kiểu CPU/RAM
        if kind == "idle_state": #trạng thái hoạt động/nhàn rỗi
            return "activity_state"
        return "local_context" #ngữ cảnh cục bộ như cửa sổ đang active, focus summary, recent events, evidence

    #quyết định “gợi ý độ mới/tính chất” (novelty_hint) để phân loại event cho downstream (chọn chú ý, ghi nhớ, log
    def _telemetry_event_novelty_hint(self, kind: str, content: str) -> str:
        if kind == "resource_pressure": #threshold_crossed vượt ngưỡng
            return "threshold_crossed"
        if kind == "idle_state":
            return "duration_threshold"
        if kind in {"recent_event", "evidence"}:
            if kind == "recent_event" and self._is_generic_screen_event(content):
                return "routine_telemetry" #telemetry lặp/nhạt, như "đã mở Chrome" hay "đang ở desktop"
            if kind == "evidence" and self._is_generic_screen_evidence(content):
                return "routine_telemetry" # telemetry lặp/nhạt
            return "concrete_telemetry" #telemetry cụ thể, đáng chú ý hơn
        if kind in {"active_window", "focus_context"}:
            return "ambient_context"
        return "routine"

    def _collect_percept_events(
        self,
        *,
        channel: str,
        snapshot,
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        force_speak: bool = False,
        internal_state: PersistentInternalState | None = None,
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        started_at: float | None = None,
    ) -> tuple[PerceptEvent, ...]:
        percepts: list[PerceptEvent] = []
        timestamp = self._event_timestamp(snapshot, started_at=started_at)

        def add(
            kind: str,
            content: str,
            *,
            source: str = "runtime",
            confidence: float = 1.0,
            evidence=(),
            privacy_level: str = "internal",
            novelty_hint: str = "routine",
        ) -> None:
            event = self._make_percept_event(
                kind=kind,
                content=content,
                evidence=evidence,
                confidence=confidence,
                source=source,
                timestamp=timestamp,
                privacy_level=privacy_level,
                novelty_hint=novelty_hint,
            )
            if event is not None:
                percepts.append(event)

        if user_text:
            add(
                "user_message",
                user_text,
                source="chat",
                confidence=1.0,
                privacy_level="user_private",
                novelty_hint="direct_user_input",
            )
        if force_speak:
            add(
                "user_force_speak",
                "force_speak requested",
                source="ui",
                confidence=1.0,
                privacy_level="internal",
                novelty_hint="explicit_request",
            )

        if social_presence_event is not None and bool(getattr(social_presence_event, "present", False)):
            kind = str(getattr(social_presence_event, "kind", "") or "presence")
            reason = str(getattr(social_presence_event, "reason", "") or "")
            content = f"kind={kind}; speech_allowed={bool(getattr(social_presence_event, 'speech_allowed', False))}"
            if reason:
                content += f"; reason={reason}"
            add(
                "social_presence_event",
                content,
                source="internal_state",
                confidence=max(0.45, self._bounded_float(getattr(social_presence_event, "confidence", 0.0))),
                evidence=tuple(getattr(social_presence_event, "evidence", ()) or ())[:6],
                privacy_level="internal",
                novelty_hint="social_presence",
            )

        active_window = getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "")
        add(
            "active_window",
            active_window,
            source="telemetry",
            confidence=0.72,
            privacy_level=self._telemetry_event_privacy_level("active_window"),
            novelty_hint=self._telemetry_event_novelty_hint("active_window", str(active_window)),
        )
        focus_summary = getattr(snapshot, "focus_summary", "")
        add(
            "focus_context",
            focus_summary,
            source="telemetry",
            confidence=0.68,
            privacy_level=self._telemetry_event_privacy_level("focus_context"),
            novelty_hint=self._telemetry_event_novelty_hint("focus_context", str(focus_summary)),
        )

        for deviation_text in self._norm_deviation_texts(snapshot):
            add(
                "norm_deviation",
                deviation_text,
                source="memory",
                confidence=0.66,
                evidence=("norm_memory",),
                privacy_level="internal",
                novelty_hint="baseline_deviation",
            )

        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        if idle_seconds >= 180:
            idle_content = f"idle={int(idle_seconds)}s ({getattr(snapshot, 'idle_label', '') or 'idle'})"
            add(
                "idle_state",
                idle_content,
                source="telemetry",
                confidence=0.64,
                privacy_level=self._telemetry_event_privacy_level("idle_state"),
                novelty_hint=self._telemetry_event_novelty_hint("idle_state", idle_content),
            )

        vision_fact_keys = {str(item or "").strip().lower() for item in tuple(vision_facts or ())}
        for event in tuple(getattr(snapshot, "recent_events", ()) or ())[:6]:
            event_text = str(event)
            if event_text.strip().lower() in vision_fact_keys:
                continue
            add(
                "recent_event",
                event_text,
                source="telemetry",
                confidence=0.76,
                privacy_level=self._telemetry_event_privacy_level("recent_event"),
                novelty_hint=self._telemetry_event_novelty_hint("recent_event", event_text),
            )
        for item in tuple(getattr(snapshot, "evidence", ()) or ())[:6]:
            evidence_text = str(item)
            add(
                "evidence",
                evidence_text,
                source="telemetry",
                confidence=0.72,
                privacy_level=self._telemetry_event_privacy_level("evidence"),
                novelty_hint=self._telemetry_event_novelty_hint("evidence", evidence_text),
            )
        for fact in tuple(vision_facts or ())[: self.vision_fact_max_items]:
            add(
                "vision_fact",
                str(fact),
                source="vision",
                confidence=0.86,
                evidence=(self.vision_last_trace or "vision_facts",),
                privacy_level="screen_context",
                novelty_hint=getattr(self, "vision_facts_novelty_hint", "") or "screen_fact",
            )

        for disturbance in tuple(getattr(thought_stream_report, "disturbances", ()) or ())[:3]:
            disturbance_channel = str(getattr(disturbance, "channel", "") or "")
            disturbance_kind = str(getattr(disturbance, "kind", "") or "")
            disturbance_content = str(getattr(disturbance, "content", "") or "")
            if not disturbance_content:
                continue
            add(
                "substrate_disturbance",
                f"{disturbance_channel}/{disturbance_kind}: {disturbance_content}",
                source="cognitive_substrate",
                confidence=max(0.45, self._bounded_float(getattr(disturbance, "intensity", 0.0))),
                evidence=tuple(getattr(disturbance, "evidence", ()) or ())[:6],
                privacy_level="internal" if disturbance_kind != "user_message" else "user_private",
                novelty_hint="input_disturbance",
            )

        momentum = getattr(thought_stream_report, "momentum", None)
        active_attractor = getattr(thought_stream_report, "active_attractor", None)
        if (
            active_attractor is not None
            and bool(getattr(active_attractor, "attractor", False))
            and float(getattr(active_attractor, "score", 0.0) or 0.0) >= 0.64
        ):
            loop_id = str(getattr(active_attractor, "loop_id", "") or "")
            topic_seed = str(getattr(active_attractor, "topic_seed", "") or "")
            add(
                "cognitive_attractor",
                f"loop={loop_id}; topic={topic_seed}",
                source="thought_stream",
                confidence=max(0.76, self._bounded_float(getattr(active_attractor, "score", 0.0))),
                evidence=tuple(getattr(active_attractor, "evidence", ()) or ())[:6],
                privacy_level="internal",
                novelty_hint="cognitive_attractor",
            )

        if (
            momentum is not None
            and str(getattr(momentum, "affordance", "") or "") == "attention"
            and float(getattr(momentum, "score", 0.0) or 0.0) >= 0.58
        ):
            topic_seed = str(getattr(momentum, "topic_seed", "") or "")
            mode = str(getattr(momentum, "mode", "") or "")
            thought_id = str(getattr(momentum, "thought_id", "") or "")
            add(
                "cognitive_momentum",
                f"thought={thought_id}; mode={mode}; topic={topic_seed}",
                source="thought_stream",
                confidence=max(0.72, self._bounded_float(getattr(momentum, "score", 0.0))),
                evidence=tuple(getattr(momentum, "evidence", ()) or ())[:6],
                privacy_level="internal",
                novelty_hint="cognitive_momentum",
            )

        goal_state = getattr(internal_state, "goal_persistence", None) if internal_state is not None else None
        if goal_state is not None and bool(getattr(goal_state, "active", False)):
            summary = str(getattr(goal_state, "summary", "") or "")
            strength = float(getattr(goal_state, "strength", 0.0) or 0.0)
            urgency = float(getattr(goal_state, "urgency", 0.0) or 0.0)
            if summary:
                add(
                    "persistent_goal",
                    f"goal={summary}; strength={strength:.2f}; urgency={urgency:.2f}",
                    source="internal_state",
                    confidence=max(0.70, self._bounded_float(strength)),
                    evidence=tuple(getattr(goal_state, "evidence", ()) or ())[:6],
                    privacy_level="internal",
                    novelty_hint="persistent_goal",
                )

        add(
            "cycle_channel",
            channel,
            source="runtime",
            confidence=0.50,
            privacy_level="internal",
            novelty_hint="cycle_marker",
        )
        return tuple(percepts[:18])

    def _collect_cognitive_percepts(self, **kwargs) -> tuple[PerceptEvent, ...]:
        return self._collect_percept_events(**kwargs)

    def _score_attention_candidate(self, percept: PerceptEvent) -> tuple[float, str]:
        candidate = self.attention_workspace.score_event(
            percept,
            long_term_memory=tuple((*tuple(self.long_term_memory), *self._memory_attention_lines())),
        )
        return candidate.score, candidate.reason

        base_by_kind = {
            "user_message": 0.96,
            "user_force_speak": 0.91,
            "resource_pressure": 0.88,
            "vision_fact": 0.84,
            "recent_event": 0.66,
            "evidence": 0.58,
            "idle_state": 0.48,
            "active_window": 0.42,
            "focus_context": 0.40,
            "cycle_channel": 0.20,
        }
        score = base_by_kind.get(percept.kind, 0.36) * percept.confidence
        reason_parts = [f"kind={percept.kind}", f"confidence={percept.confidence:.2f}"]
        lowered = percept.content.lower()

        if percept.source == "vision":
            score += 0.08
            reason_parts.append("vision")
        if len(percept.content) >= 28:
            score += 0.04
            reason_parts.append("specific")
        if any(token in lowered for token in ("error", "failed", "lỗi", "cpu", "ram", "đã đọc", "message", "tin nhắn")):
            score += 0.08
            reason_parts.append("charged")
        if percept.kind == "recent_event" and self._is_generic_screen_event(percept.content):
            score -= 0.18
            reason_parts.append("generic_event")
        if percept.kind == "evidence" and self._is_generic_screen_evidence(percept.content):
            score -= 0.18
            reason_parts.append("generic_evidence")

        return self._bounded_float(score), ", ".join(reason_parts)

    def _build_attention_candidates(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
    ) -> tuple[AttentionCandidate, ...]:
        return self.attention_workspace.rank(
            percepts,
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            long_term_memory=tuple((*tuple(self.long_term_memory), *self._memory_attention_lines())),
        )

    def _build_broadcast(self, candidates: tuple[AttentionCandidate, ...]) -> CognitiveBroadcast:
        return self.attention_workspace.build_broadcast(candidates)

    def _build_meaning_layer(
        self,
        *,
        snapshot,
        broadcast: CognitiveBroadcast,
        internal_state,
        thought_stream_report=None,
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
    ) -> MeaningLayerResult:
        return self.meaning_layer.evaluate(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=internal_state,
            thought_stream_report=thought_stream_report,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            recent_families=tuple(self.recent_meaning_families[-3:]),
        )

    def _build_personality_lens(
        self,
        *,
        snapshot,
        broadcast: CognitiveBroadcast,
        internal_state,
        meaning_layer: MeaningLayerResult | None = None,
        channel: str = "",
        user_text: str = "",
    ) -> PersonalityLensResult:
        return self.personality_lens.evaluate(
            scene=snapshot,
            attention=broadcast,
            meaning_layer=meaning_layer,
            internal_state=internal_state,
            relationship=self.fe_style_memory,
            channel=channel,
            user_text=user_text,
        )

    def _apply_personality_lens_to_fe_plan(self, fe_plan, lens: PersonalityLensResult):
        applicator = getattr(self.fe_renderer, "apply_personality_lens", None)
        if callable(applicator):
            return applicator(fe_plan, lens)

        prompt_context = str(getattr(lens, "prompt_context", "") or "").strip()
        if prompt_context and hasattr(fe_plan, "style_context"):
            current = str(getattr(fe_plan, "style_context", "") or "")
            setattr(fe_plan, "style_context", f"{current}\n{prompt_context}" if current else prompt_context)
        if hasattr(fe_plan, "evidence"):
            evidence = tuple(getattr(fe_plan, "evidence", ()) or ())
            setattr(
                fe_plan,
                "evidence",
                tuple(dict.fromkeys((*evidence, f"personality_lens={lens.interpretation}"))),
            )
        return fe_plan

    def _build_cognitive_appraisal(
        self,
        *,
        internal_state,
        ni_report,
        ti_report,
        fe_plan,
        broadcast,
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
        personality_lens=None,
    ) -> CognitiveAppraisal:
        return self.appraisal_engine.evaluate(
            internal_state=internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            broadcast=broadcast,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            memory_resonance=getattr(self, "active_memory_resonance", None),
            personality_lens=personality_lens,
        )

    def _build_appraisal_context(self, appraisal: CognitiveAppraisal) -> str:
        return self.appraisal_engine.render_prompt_context(appraisal)

    def _build_inner_thought(
        self,
        *,
        channel: str,
        snapshot,
        frame: CognitiveFrame,
        concrete_signals: tuple[str, ...] = (),
        repeat_count: int = 1,
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
        subconscious_seed=None,
        thought_surface=None,
    ) -> InnerThought:
        return self.inner_thought_engine.evaluate(
            channel=channel,
            snapshot=snapshot,
            appraisal=frame.appraisal,
            broadcast=frame.broadcast,
            style_memory=self.fe_style_memory,
            concrete_signals=tuple(concrete_signals or ()),
            last_text=self.last_text,
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            recent_inner_intents=self.recent_inner_thought_intents,
            recent_inner_seeds=self.recent_inner_thought_seeds,
            thought_surface=thought_surface if thought_surface is not None else subconscious_seed,
        )

    def _build_speech_core(
        self,
        *,
        channel: str,
        snapshot,
        internal_state,
        frame: CognitiveFrame,
        ti_report,
        fe_plan,
        ni_report=None,
        ni_state_label: str = "",
        repeat_count: int = 1,
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
        subconscious_seed=None,
        thought_surface=None,
    ) -> AgentSpeechCore:
        concrete_signals = self._concrete_screen_signals(snapshot)
        screen_comment_allowed = channel == "force_speak"
        if concrete_signals and channel != "force_speak":
            screen_comment_allowed = bool(self._broadcast_screen_winners(frame.broadcast))
        speech_core = self.speech_core_engine.evaluate(
            channel=channel,
            snapshot=snapshot,
            internal_state=internal_state,
            appraisal=frame.appraisal,
            broadcast=frame.broadcast,
            ti_report=ti_report,
            fe_plan=fe_plan,
            style_memory=self.fe_style_memory,
            concrete_signals=concrete_signals,
            vision_signals=self._concrete_vision_signals(snapshot),
            telemetry_signals=self._concrete_telemetry_signals(snapshot),
            screen_comment_allowed=screen_comment_allowed,
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            recent_inner_intents=self.recent_inner_thought_intents,
            recent_inner_seeds=self.recent_inner_thought_seeds,
            ni_state_label=ni_state_label,
            ni_report=ni_report,
            thought_surface=thought_surface if thought_surface is not None else subconscious_seed,
            self_state=frame.self_state,
            meaning_layer=getattr(frame, "meaning_layer", None),
            personality_lens=getattr(frame, "personality_lens", None),
            safe_small_talk_allowed=self._safe_small_talk_budget_allowed(
                channel=channel,
                snapshot=snapshot,
                now=time.time(),
            ),
        )
        frame.speech_core = speech_core
        frame.inner_thought = speech_core.inner_thought
        return speech_core

    def _remember_inner_thought_rhythm(self, inner_thought: InnerThought | None) -> None:
        if inner_thought is None or not inner_thought.intent:
            return
        self.recent_inner_thought_intents = (*self.recent_inner_thought_intents, inner_thought.intent)[-6:]
        if inner_thought.topic_seed:
            self.recent_inner_thought_seeds = (*self.recent_inner_thought_seeds, inner_thought.topic_seed)[-8:]

    def _start_cognitive_frame(
        self,
        *,
        channel: str,
        started_at: float,
        snapshot,
        internal_state_before,
        sensed_internal_state,
        ni_report,
        ti_report,
        fe_plan,
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        force_speak: bool = False,
        memory_resonance=None,
    ) -> CognitiveFrame:
        if memory_resonance is not None:
            self.active_memory_resonance = memory_resonance
        percepts = self._collect_percept_events(
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            vision_facts=vision_facts,
            force_speak=force_speak,
            thought_stream_report=thought_stream_report,
            social_presence_event=social_presence_event,
            started_at=started_at,
        )
        candidates = self._build_attention_candidates(
            percepts,
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
        )
        broadcast = self._build_broadcast(candidates)
        meaning_layer = self._build_meaning_layer(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=sensed_internal_state,
            thought_stream_report=thought_stream_report,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
        )
        personality_lens = self._build_personality_lens(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=sensed_internal_state,
            meaning_layer=meaning_layer,
            channel=channel,
            user_text=user_text,
        )
        fe_plan = self._apply_personality_lens_to_fe_plan(fe_plan, personality_lens)
        appraisal = self._build_cognitive_appraisal(
            internal_state=sensed_internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            broadcast=broadcast,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            personality_lens=personality_lens,
        )
        frame = CognitiveFrame(
            cycle_id=self._next_cognitive_cycle_id(channel),
            channel=channel,
            started_at=started_at,
            percepts=percepts,
            attention_candidates=candidates,
            broadcast=broadcast,
            meaning_layer=meaning_layer,
            personality_lens=personality_lens,
            appraisal=appraisal,
            memory_resonance=memory_resonance if memory_resonance is not None else getattr(self, "active_memory_resonance", None),
            self_state=self.self_model_engine.evaluate(
                channel=channel,
                snapshot=snapshot,
                internal_state=sensed_internal_state,
                ti_report=ti_report,
                broadcast=broadcast,
                user_text=user_text,
                force_speak=force_speak,
            ),
            internal_state_before=internal_state_before,
            internal_state_after=sensed_internal_state,
            social_presence_event=social_presence_event or SocialPresenceEvent(present=False),
        )
        if thought_stream_report is not None:
            frame.thought_stream_report = thought_stream_report
            frame.subconscious_report = thought_stream_report
        self._note_norm_observation(snapshot)
        return frame

    def _set_cognitive_action_plan(
        self,
        frame: CognitiveFrame,
        *,
        should_speak: bool,
        speech_intent: str,
        reason: str,
        snapshot=None,
        user_text: str = "",
        force_speak: bool = False,
        concrete_signals: tuple[str, ...] = (),
        ti_report=None,
        fe_plan=None,
        system_action: str = "",
        speech_act: str = "",
        notes: tuple[str, ...] = (),
        inner_thought: InnerThought | None = None,
    ) -> None:
        proposed_intent = speech_intent or ("brief_ack" if should_speak else "no_speech")
        if (
            getattr(frame, "speech_core", None) is not None
            and (
                frame.channel in {"autonomous", "force_speak"}
                or frame.speech_core.should_speak
                or frame.speech_core.speech_source != "none"
                or frame.speech_core.reason
            )
        ):
            notes = self._merge_speech_core_notes(notes, frame.speech_core)
        if inner_thought is not None:
            frame.inner_thought = inner_thought
            if inner_thought.should_surface and not speech_act:
                speech_act = inner_thought.intent
                if inner_thought.topic_seed:
                    reason = f"{reason} InnerThought: {inner_thought.topic_seed}"
            notes = self._merge_inner_thought_notes(notes, inner_thought)
        notes = self._merge_meaning_layer_notes(notes, getattr(frame, "meaning_layer", None))
        notes = self._merge_personality_lens_notes(notes, getattr(frame, "personality_lens", None))
        notes = self._merge_subconscious_notes(notes, getattr(frame, "subconscious_report", None))
        notes = self._merge_memory_resonance_notes(notes, getattr(frame, "memory_resonance", None))
        frame.action_plan = self.action_planner.plan(
            channel=frame.channel,
            snapshot=snapshot,
            ti_report=ti_report,
            fe_plan=fe_plan,
            appraisal=frame.appraisal,
            broadcast=frame.broadcast,
            user_text=user_text,
            force_speak=force_speak,
            proposed_intent=proposed_intent,
            proposed_reason=reason,
            proposed_speech_act=speech_act,
            system_action=system_action,
            notes=tuple(notes),
            concrete_signals=tuple(concrete_signals or ()),
            self_state=frame.self_state,
        )
        self._apply_micro_line_policy_to_action_plan(
            frame,
            vision_fact=str((tuple(concrete_signals or ()) or ("",))[0] or ""),
        )

    def _apply_micro_line_policy_to_action_plan(self, frame: CognitiveFrame, *, vision_fact: str = "") -> None:
        action_plan = frame.action_plan
        policy = self.micro_line_policy.evaluate(
            speech_intent=action_plan.speech_intent,
            broadcast=frame.broadcast,
            vision_fact=vision_fact,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=frame.channel,
        )
        notes = list(action_plan.notes or ())
        notes.append(f"micro_line_type={policy.allowed_line_type}")
        notes.append(f"micro_signal_score={policy.signal_score:.2f}")
        notes.append(f"micro_risk_level={policy.risk_level}")
        flags = list(action_plan.risk_flags or ())
        for reason in policy.reject_reasons:
            flags.append(f"micro_policy_reject={reason}")
        if "no_speech_blocks_final" in policy.reject_reasons:
            action_plan.should_speak = False
            action_plan.speech_intent = "no_speech"
            action_plan.speech_act = "no_speech"
            action_plan.reason_to_speak = "MicroLinePolicy returned no_speech for a repeated or blocked micro line."
            action_plan.reason = action_plan.reason_to_speak
        action_plan.notes = tuple(dict.fromkeys(str(item) for item in notes if str(item or "").strip()))
        action_plan.risk_flags = tuple(dict.fromkeys(str(item) for item in flags if str(item or "").strip()))

    def _speech_intent_from_core(self, speech_core: AgentSpeechCore, *, channel: str) -> str:
        if not speech_core.should_speak:
            return "no_speech"
        if speech_core.utterance_type in {"telemetry_comment", "vision_comment"}:
            return "screen_observation"
        if speech_core.utterance_type == "micro_observation":
            return "micro_observation"
        if speech_core.utterance_type == "micro_presence":
            return "micro_presence"
        if speech_core.utterance_type == "curious_question":
            return "curious_question"
        if speech_core.utterance_type == "guarded_reply":
            return "guarded_reply"
        if speech_core.utterance_type == "indirect_presence":
            return "indirect_presence"
        if speech_core.utterance_type in {"inner_whim", "random_chatter", "light_muse", "soft_boundary"}:
            if channel == "force_speak":
                return "micro_presence"
            return "social_presence"
        if channel == "force_speak":
            return "user_requested"
        return "brief_ack"

    def _merge_speech_core_notes(
        self,
        notes: tuple[str, ...],
        speech_core: AgentSpeechCore,
    ) -> tuple[str, ...]:
        merged = list(notes or ())
        if speech_core.speech_source:
            merged.append(f"speech_source={speech_core.speech_source}")
        if speech_core.grounding:
            merged.append(f"grounding={speech_core.grounding}")
        if getattr(speech_core, "speech_risk_level", ""):
            merged.append(f"speech_risk_level={speech_core.speech_risk_level}")
        if speech_core.delivery:
            merged.append(f"delivery={speech_core.delivery}")
        silence = getattr(speech_core, "silence_state", None)
        if silence is not None and getattr(silence, "intentional_withholding", False):
            merged.append(f"silence_state={getattr(silence, 'mode', '') or 'intentional_withholding'}")
            for label, value in (
                ("suppressed_thought", getattr(silence, "suppressed_thought", "")),
                ("almost_spoke", getattr(silence, "almost_spoke", "")),
                ("unfinished_impulse", getattr(silence, "unfinished_impulse", "")),
                ("internal_hesitation", getattr(silence, "internal_hesitation", "")),
            ):
                if value:
                    merged.append(f"{label}={value}")
        if speech_core.reason:
            merged.append(f"speech_core_reason={speech_core.reason}")
        impulse = getattr(speech_core, "speech_impulse", None)
        if impulse is not None:
            reaction = str(getattr(impulse, "reaction", "") or "")
            mood_residue = str(getattr(impulse, "mood_residue", "") or "")
            reaction_impulse = str(getattr(impulse, "reaction_impulse", "") or "")
            pressure = float(getattr(impulse, "emotional_pressure", 0.0) or 0.0)
            if mood_residue:
                merged.append(f"mood_residue={mood_residue}")
            if reaction_impulse:
                merged.append(f"reaction_impulse={reaction_impulse}")
            if pressure:
                merged.append(f"emotional_pressure={pressure:.2f}")
            if reaction:
                merged.append(f"speech_impulse_reaction={reaction}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _merge_meaning_layer_notes(self, notes: tuple[str, ...], meaning_layer) -> tuple[str, ...]:
        merged = list(notes or ())
        if meaning_layer is None:
            return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
        family = str(getattr(meaning_layer, "semantic_family", "") or "")
        shift_reason = str(getattr(meaning_layer, "shift_reason", "") or "")
        reaction = str(getattr(meaning_layer, "reaction", "") or "")
        mood_residue = str(getattr(meaning_layer, "mood_residue", "") or "")
        reaction_impulse = str(getattr(meaning_layer, "reaction_impulse", "") or "")
        pressure = float(getattr(meaning_layer, "emotional_pressure", 0.0) or 0.0)
        if family:
            merged.append(f"internal_family={family}")
        if shift_reason:
            merged.append(f"meaning_shift={shift_reason}")
        if mood_residue:
            merged.append(f"mood_residue={mood_residue}")
        if reaction_impulse:
            merged.append(f"reaction_impulse={reaction_impulse}")
        if pressure:
            merged.append(f"emotional_pressure={pressure:.2f}")
        if reaction:
            merged.append(f"meaning_reaction={reaction}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _merge_memory_resonance_notes(self, notes: tuple[str, ...], memory_resonance) -> tuple[str, ...]:
        merged = list(notes or ())
        if memory_resonance is None:
            return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
        layer = str(getattr(memory_resonance, "dominant_layer", "") or "")
        try:
            score = float(getattr(memory_resonance, "score", 0.0) or 0.0)
            silence = float(getattr(memory_resonance, "silence_bias", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
            silence = 0.0
        if score > 0.0:
            merged.append(f"memory_resonance={layer or 'none'}:{score:.2f}")
        if silence >= 0.35:
            merged.append(f"memory_silence_bias={silence:.2f}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _merge_inner_thought_notes(self, notes: tuple[str, ...], inner_thought: InnerThought) -> tuple[str, ...]:
        merged = list(notes or ())
        if inner_thought.intent:
            merged.append(f"inner_thought={inner_thought.intent}")
        if inner_thought.motive:
            merged.append(f"inner_motive={inner_thought.motive}")
        if inner_thought.topic_seed:
            merged.append(f"inner_seed={inner_thought.topic_seed}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _merge_personality_lens_notes(self, notes: tuple[str, ...], personality_lens) -> tuple[str, ...]:
        merged = list(notes or ())
        if personality_lens is None:
            return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
        interpretation = str(getattr(personality_lens, "interpretation", "") or "")
        stance = str(getattr(personality_lens, "stance", "") or "")
        distance = str(getattr(personality_lens, "social_distance", "") or "")
        rhythm = str(getattr(personality_lens, "rhythm", "") or "")
        restraint_mode = str(getattr(personality_lens, "restraint_mode", "") or "")
        try:
            want_to_say = float(getattr(personality_lens, "want_to_say", 0.0) or 0.0)
            allowed_expression = float(getattr(personality_lens, "allowed_expression", 0.0) or 0.0)
            suppression_pressure = float(getattr(personality_lens, "suppression_pressure", 0.0) or 0.0)
        except (TypeError, ValueError):
            want_to_say = allowed_expression = suppression_pressure = 0.0
        if interpretation:
            merged.append(f"personality_interpretation={interpretation}")
        if stance:
            merged.append(f"personality_stance={stance}")
        if distance:
            merged.append(f"social_distance={distance}")
        if rhythm:
            merged.append(f"rhythm={rhythm}")
        if restraint_mode:
            merged.append(f"restraint_mode={restraint_mode}")
        merged.append(f"expression_gate={want_to_say:.2f}->{allowed_expression:.2f}")
        merged.append(f"suppression_pressure={suppression_pressure:.2f}")
        merged.append("suppression_layer=inner_restraint")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _merge_subconscious_notes(self, notes: tuple[str, ...], subconscious_report) -> tuple[str, ...]:
        merged = list(notes or ())
        seed = getattr(subconscious_report, "latest_seed", None)
        mode = str(getattr(seed, "mode", "") or "")
        topic_seed = str(getattr(seed, "topic_seed", "") or "")
        thought = getattr(subconscious_report, "latest_thought", None)
        momentum = getattr(subconscious_report, "momentum", None)
        thought_id = str(getattr(thought, "thought_id", "") or getattr(seed, "thought_id", "") or "")
        tension = getattr(subconscious_report, "stream_tension", 0.0)
        if mode:
            merged.append(f"thought_surface_mode={mode}")
            merged.append(f"subconscious_mode={mode}")
        if topic_seed:
            merged.append(f"thought_surface={topic_seed}")
            merged.append(f"subconscious_seed={topic_seed}")
        if thought_id:
            merged.append(f"thought_id={thought_id}")
        try:
            if float(tension or 0.0) > 0.0:
                merged.append(f"cognitive_tension={float(tension):.2f}")
        except (TypeError, ValueError):
            pass
        try:
            momentum_score = float(getattr(momentum, "score", 0.0) if momentum is not None else 0.0)
            if momentum_score > 0.0:
                merged.append(f"cognitive_momentum={momentum_score:.2f}")
                affordance = str(getattr(momentum, "affordance", "") or "")
                if affordance:
                    merged.append(f"momentum_affordance={affordance}")
        except (TypeError, ValueError):
            pass
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _is_inner_thought_speech_act(self, speech_act: str) -> bool:
        return speech_act in {
            "meta_reply",
            "random_chatter",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
        }

    def _build_action_plan_context(self, action_plan: CognitiveActionPlan) -> str:
        flags = ", ".join(action_plan.risk_flags) if action_plan.risk_flags else "none"
        notes = " | ".join(action_plan.notes) if action_plan.notes else "none"
        reason = action_plan.reason_to_speak or action_plan.reason or "none"
        style_anchor = str(getattr(action_plan, "style_anchor", "") or "current event")
        style_attitude = str(getattr(action_plan, "style_attitude", "") or "lạnh nhẹ")
        style_limit = str(getattr(action_plan, "style_limit", "") or "một câu ngắn")
        return (
            "ActionPlanner decision before LLM:\n"
            f"- action_space={', '.join(ACTION_SPACE)}\n"
            f"- should_speak={str(action_plan.should_speak).lower()}\n"
            f"- speech_act={action_plan.speech_act}\n"
            f"- utterance_type={action_plan.speech_act}\n"
            f"- reason_to_speak={reason}\n"
            f"- risk_flags={flags}\n"
            f"- notes={notes}\n"
            "Style contract before wording:\n"
            f"- anchor={style_anchor}\n"
            f"- attitude={style_attitude}\n"
            f"- limit={style_limit}\n"
            "- reject_line_if=no concrete anchor, too long, or abstract philosophy\n"
            "Honor this plan. Do not upgrade withdraw/no_speech into observation, teasing, or reassurance."
        )

    def _build_llm_ti_context(self, ti_report, action_plan: CognitiveActionPlan) -> str:
        mode = str(getattr(ti_report, "mode", "") or "steady_observe")
        animation = str(getattr(ti_report, "animation_hint", "") or "stand")
        return (
            f"Mode: {mode}. Animation hint: {animation}.\n"
            f"{self._build_action_plan_context(action_plan)}\n"
            "Telemetry is internal routing data only. Do not mention window, focus, CPU, RAM, idle, tabs, or app names "
            "unless they appear in speech_evidence."
        )

    def _build_speech_evidence_context(self, snapshot, *, limit: int = 2) -> str:
        signals = self._concrete_screen_signals(snapshot)[:limit]
        if not signals:
            return "speech_evidence=<none>"
        return "speech_evidence=" + " | ".join(str(item) for item in signals)

    def _build_current_focus_context(self, snapshot) -> str:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus = str(getattr(snapshot, "focus_summary", "") or "").strip() or focus_kind
        return f"current_focus_kind={focus_kind}; current_focus={focus}"

    def _detect_social_presence_event(
        self,
        *,
        channel: str,
        snapshot,
        internal_state: PersistentInternalState | None,
        started_at: float | None = None,
    ) -> SocialPresenceEvent:
        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        user_signals = getattr(snapshot, "user_signals", None)
        typing_speed = str(getattr(user_signals, "typing_speed", "") or "")
        window_switching = str(getattr(user_signals, "window_switching", "") or "")

        evidence: list[str] = []
        if idle_seconds:
            evidence.append(f"idle_seconds={idle_seconds:.1f}")
        if typing_speed:
            evidence.append(f"typing_speed={typing_speed}")
        if window_switching:
            evidence.append(f"window_switching={window_switching}")
        if recent_events:
            evidence.append(f"recent_events={','.join(str(item) for item in recent_events[:3])}")

        low_idle = idle_seconds <= 8.0
        has_mouse = any(str(item) == "mouse_moved" for item in recent_events)
        has_typing = typing_speed not in {"", "zero", "none"}
        present = bool(low_idle and (has_mouse or has_typing))
        if not present:
            return SocialPresenceEvent(present=False, timestamp=self._event_timestamp(snapshot, started_at=started_at))

        kind = "typing" if has_typing else "mouse_moved"
        speech_allowed = channel in {"chat", "force_speak"}
        reason = "low_idle_user_signal"
        confidence = 0.62
        return SocialPresenceEvent(
            present=True,
            kind=kind,
            confidence=confidence,
            intensity=0.58,
            speech_allowed=speech_allowed,
            reason=reason,
            evidence=tuple(evidence)[:6],
            timestamp=self._event_timestamp(snapshot, started_at=started_at),
        )

    def _note_autonomous_silence(self) -> int:
        self.presence_maintenance_silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0) + 1
        self.reengagement_quiet_cycles = int(getattr(self, "reengagement_quiet_cycles", 0) or 0) + 1
        return self.presence_maintenance_silent_cycles

    def _note_autonomous_spoken(
        self,
        *,
        presence_maintenance: bool = False,
        reengagement: bool = False,
        now: float | None = None,
    ) -> None:
        current_time = time.time() if now is None else now
        self.presence_maintenance_silent_cycles = 0
        if presence_maintenance:
            self.last_presence_maintenance_at = current_time
        if reengagement:
            self.last_reengagement_at = current_time
            self.reengagement_quiet_cycles = 0
        elif not presence_maintenance:
            self.reengagement_quiet_cycles = 0

    # cho phép nói chuyện nhỏ an toàn nếu đang ở kênh tự động, không có tín hiệu màn hình cụ thể
    def _safe_small_talk_budget_allowed(self, *, channel: str, snapshot, now: float | None = None) -> bool:
        if str(channel or "") != "autonomous":
            return False
        if self._has_concrete_screen_signal(snapshot):
            return False
        current_time = time.time() if now is None else now
        last_spoken = float(getattr(self, "last_autonomous_spoken_at", 0.0) or 0.0)
        if last_spoken <= 0.0:
            return False
        if current_time - last_spoken < 300.0:
            return False
        if self.presence_maintenance_silent_cycles < 1:
            return False
        recent = self._recent_spoken_texts(limit=3)
        if sum(1 for line in recent if "?" in str(line or "")) >= 2:
            return False
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        has_window = bool(str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip())
        has_presence = idle_seconds >= 60.0 or bool(tuple(getattr(snapshot, "recent_events", ()) or ()))
        return bool(has_window or has_presence)

    def _should_allow_presence_maintenance(
        self,
        *,
        snapshot,
        ti_report,
        social_presence_event: SocialPresenceEvent | None,
        now: float | None = None,
    ) -> bool:
        if not getattr(self, "presence_maintenance_enabled", True):
            return False
        if self.presence_maintenance_silent_cycles < self.presence_maintenance_silent_loop_threshold:
            return False

        current_time = time.time() if now is None else now
        cooldown = float(getattr(self, "presence_maintenance_cooldown_sec", 0.0) or 0.0)
        if self.last_presence_maintenance_at > 0.0 and current_time - self.last_presence_maintenance_at < cooldown:
            return False

        last_spoken = float(getattr(self, "last_autonomous_spoken_at", 0.0) or 0.0)
        spoken_floor = 20.0 if cooldown <= 0.0 else max(20.0, min(40.0, cooldown))
        if last_spoken > 0.0 and current_time - last_spoken < spoken_floor:
            return False

        mode = str(getattr(ti_report, "mode", "") or "")
        if mode in {"resource_guard", "goal_drift_alert", "goal_realign", "system_warning"}:
            return False

        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        present = bool(getattr(social_presence_event, "present", False))
        if idle_seconds >= 900.0 and not present:
            return False
        return present or idle_seconds <= 120.0 or bool(recent_events)

    def _presence_maintenance_lines(self, snapshot) -> tuple[str, ...]:
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "")
        browser_url = str(getattr(snapshot, "browser_url", "") or "")
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "")
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "")
        vision_facts = tuple(str(item or "").strip() for item in (getattr(snapshot, "vision_facts", ()) or ()) if str(item or "").strip())
        cue = vision_facts[0] if vision_facts else (focus_summary or active_window or focus_kind)
        return self._cue_micro_lines(
            cue=cue,
            active_window=active_window,
            browser_url=browser_url,
            focus_kind=focus_kind,
            focus_summary=focus_summary,
            presence=True,
        )

    def _cue_micro_lines(
        self,
        *,
        cue: str,
        active_window: str = "",
        browser_url: str = "",
        focus_kind: str = "",
        focus_summary: str = "",
        presence: bool = False,
    ) -> tuple[str, ...]:
        compact_cue = re.sub(r"\s+", " ", str(cue or "").strip()).strip(" .")
        window = re.sub(r"\s+", " ", str(active_window or "").strip()).strip(" .")
        summary = re.sub(r"\s+", " ", str(focus_summary or "").strip()).strip(" .")
        haystack = self._normalize_user_message(" ".join((compact_cue, window, browser_url, summary, focus_kind)))
        lines: list[str] = []

        if "banner" in haystack and any(term in haystack for term in ("trinh bay", "present", "presentation", "share")):
            lines.extend(
                (
                    "cái banner trình bày kia vẫn nằm đó.",
                    "banner trình bày vẫn mắc ở một góc.",
                )
            )
        if "meet" in haystack or "meeting" in haystack or "cuoc goi" in haystack:
            lines.extend(
                (
                    "hm, Meet vẫn đang treo đó.",
                    "vẫn là cái phòng Meet đó à.",
                    "cửa sổ Meet im hơi lâu rồi.",
                    "Ngài đang để màn hình chia sẻ mở hơi lâu rồi.",
                )
            )
        elif "youtube" in haystack or "music youtube" in haystack:
            lines.extend(("tab YouTube vẫn mở ở đó.", "nhạc vẫn chạy nền khe khẽ."))
        elif focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "visual studio", "vscode", "python", "debug")):
            lines.extend(("mạch code vẫn đứng ở đó.", "đoạn này im hơi lâu rồi."))
        elif focus_kind == "communication" or any(term in haystack for term in ("chat", "message", "zalo", "discord", "slack")):
            lines.extend(("khung chat vẫn yên một nhịp.", "cửa sổ nhắn tin vẫn để đó."))

        subject = self._micro_line_subject(compact_cue or summary or window or focus_kind)
        if subject:
            lines.append(f"{subject} vẫn nằm đó.")
            if presence:
                lines.append(f"{subject} im hơi lâu rồi.")
        if not lines:
            lines.append("cửa sổ này im hơi lâu rồi.")

        return tuple(dict.fromkeys(self._clean_micro_line(line) for line in lines if self._clean_micro_line(line)))[:5]

    def _micro_line_subject(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .")
        if not text or self._looks_internal_topic(text):
            return ""
        normalized = self._normalize_user_message(text)
        if "meet" in normalized:
            return "phòng Meet"
        if "banner" in normalized:
            return "banner trình bày kia"
        if "youtube" in normalized:
            return "tab YouTube"
        if "visual studio" in normalized or "vscode" in normalized:
            return "mạch code này"
        if len(text) > 34:
            text = text[:34].rstrip(" ,;:-")
        return text[0].lower() + text[1:] if text else ""

    def _clean_micro_line(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip())
        if not cleaned:
            return ""
        cleaned = cleaned.replace("!", ".")
        if not cleaned.endswith((".", "?", "à")):
            cleaned += "."
        words = [item for item in re.split(r"\s+", cleaned.strip(" .?")) if item]
        if len(words) < 3 or len(words) > 12:
            return ""
        normalized = self._normalize_user_message(cleaned)
        banned = ("toi van o day", "toi o day", "toi nghe day", "toi van dang quan sat", "toi van theo doi")
        banned_ascii = (
            "status",
            "ui",
            "khung",
            "khung thoai",
            "khung chat",
            "mau hong",
            "man hinh",
            "cua so",
            "hien thi",
            "dang hien thi",
            "toi dang",
            "toi van",
            "toi o day",
            "toi nghe",
            "toi thay",
        )
        if any(self._normalize_user_message(item) in normalized for item in (*banned, *banned_ascii)):
            return ""
        return cleaned

    # chấm điểm candidates quan sát viễn cảnh để quyết định có nên nói hay không, và nếu có thì nói gì để duy trì sự hiện diện một cách tinh tế, tránh bị lạc lõ
    def _vision_fact_micro_observation_candidate(
        self,
        frame: CognitiveFrame,
    ) -> tuple[str, float]:
        best_text = ""
        best_score = 0.0
        for candidate in tuple(getattr(frame, "attention_candidates", ()) or ()):
            if str(getattr(candidate, "label", "") or "") != "vision_fact":
                continue
            text = str(getattr(candidate, "content", "") or "").strip()
            if not text:
                continue
            score = self._bounded_float(getattr(candidate, "score", 0.0))
            if score > best_score:
                best_text = text
                best_score = score
        for percept in tuple(getattr(frame, "percepts", ()) or ()):
            if str(getattr(percept, "kind", "") or "") != "vision_fact":
                continue
            text = str(getattr(percept, "content", "") or "").strip()
            if not text:
                continue
            score = max(self._bounded_float(getattr(percept, "confidence", 0.0)), best_score if text == best_text else 0.0)
            if score > best_score:
                best_text = text
                best_score = score
        min_score = 0.54
        if self.presence_maintenance_silent_cycles >= 2:
            min_score = 0.46
        if self.presence_maintenance_silent_cycles >= 3:
            min_score = 0.38
        if best_score < min_score:
            return "", best_score
        return best_text, best_score

    def _build_micro_observation_decision(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        now: float | None = None,
    ) -> Decision | None:
        if self.presence_maintenance_silent_cycles < 1:
            return None
        cue, score = self._vision_fact_micro_observation_candidate(frame)
        if not cue:
            return None
        lines = self._cue_micro_lines(
            cue=cue,
            active_window=str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or ""),
            browser_url=str(getattr(snapshot, "browser_url", "") or ""),
            focus_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            focus_summary=str(getattr(snapshot, "focus_summary", "") or ""),
        )
        text = self._choose_local_micro_line(
            lines,
            counter=self.presence_maintenance_silent_cycles,
            threshold=1,
        )
        if not text:
            return None
        return Decision(
            text=text,
            animation="stand",
            intent="micro_observation",
            reasoning_tags=("micro_observation", "vision_fact"),
            should_speak=True,
            confidence=max(0.50, min(0.78, score)),
            parse_mode="micro_observation",
            debug_trace=(
                "micro_observation_layer"
                f"; vision_fact_score={score:.2f}"
                f"; silent_cycles={self.presence_maintenance_silent_cycles}"
            ),
        )

    def _try_finalize_micro_observation_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        meaning_layer = getattr(frame, "meaning_layer", None)
        if str(getattr(meaning_layer, "meaning", "") or ""):
            return False
        if (
            meaning_layer is not None
            and str(getattr(meaning_layer, "meaning_signal", "") or "")
            not in {"", "none", "weak_meaning", "ambient_meaning", "vibe_signal"}
            and not bool(getattr(meaning_layer, "meaning_shift", False))
        ):
            return False
        decision = self._build_micro_observation_decision(
            frame=frame,
            snapshot=snapshot,
            now=now,
        )
        if decision is None:
            return False
        cue, score = self._vision_fact_micro_observation_candidate(frame)
        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="micro_observation",
            speech_act="micro_observation",
            reason="Vision fact stayed salient after a silent cycle; prefer micro observation over no_speech.",
            snapshot=snapshot,
            concrete_signals=(cue,),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("micro_observation", f"vision_fact_score={score:.2f}", f"silent_cycles={self.presence_maintenance_silent_cycles}"),
        )
        if not frame.action_plan.should_speak:
            return False
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        decision.parse_mode = "micro_observation"
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = now
        self._note_autonomous_spoken(now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("micro_observation",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[micro_observation] text="%s" | vision_score=%.2f',
            decision.text,
            score,
        )
        self.transport.send_json(decision.to_payload())

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ micro_observation trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    def _micro_presence_kind_from_seed(self, seed: str) -> str:
        normalized = self._normalize_user_message(seed)
        if "bodily" in normalized:
            return "bodily_residue"
        if "social" in normalized:
            return "social_residue"
        if "thought" in normalized or "cognitive" in normalized:
            return "thought_residue"
        return "screen_residue"

    def _thought_residue_seeds(self, report) -> tuple[str, ...]:
        seeds: list[str] = []
        seed = getattr(report, "latest_seed", None)
        thought = getattr(report, "latest_thought", None)
        attractor = getattr(report, "active_attractor", None)
        for value in (
            getattr(seed, "partial_text", ""),
            getattr(thought, "partial_text", ""),
            getattr(seed, "unresolved_reason", ""),
            getattr(thought, "unresolved_reason", ""),
        ):
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text and not self._looks_internal_topic(text):
                seeds.append(text[:80])
        topic = str(
            getattr(seed, "topic_seed", "")
            or getattr(thought, "topic_seed", "")
            or getattr(attractor, "topic_seed", "")
            or ""
        )
        public_topic = self._public_thought_topic(topic)
        if public_topic:
            seeds.append(f"{public_topic} vẫn chưa khớp")
        if getattr(attractor, "attractor", False):
            seeds.append("có một mạch cũ quay lại")
        return tuple(dict.fromkeys(seed for seed in seeds if seed))[:3]

    def _synthesize_micro_presence(
        self,
        *,
        snapshot,
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        inner_thought: InnerThought | None = None,
    ) -> MicroPresenceSynthesis:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "").strip() or focus_kind
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        seed_hint = str(getattr(inner_thought, "topic_seed", "") or "")
        kind = self._micro_presence_kind_from_seed(seed_hint)

        seeds: list[str] = []
        haystack = self._normalize_user_message(" ".join((active_window, focus_summary, focus_kind, " ".join(recent_events))))
        if "godot" in haystack:
            seeds.append("Godot vẫn mở.")
        elif focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "vscode", "visual studio", "debug")):
            seeds.append("mạch code vẫn đứng đó.")
        elif active_window:
            title = re.sub(r"\s+", " ", active_window).strip()
            if title and not self._looks_internal_topic(title):
                seeds.append(f"{title[:36]} vẫn mở.")

        if any("log" in self._normalize_user_message(item) for item in recent_events):
            seeds.append("log cứ lặp lại.")
        if idle_seconds >= 240:
            seeds.append("màn hình im khá lâu.")
        elif not seeds and focus_summary:
            seeds.append(f"{focus_summary[:48]} vẫn yên.")

        thought_seeds = self._thought_residue_seeds(thought_stream_report)
        if thought_seeds:
            kind = "thought_residue"
            seeds.extend(thought_seeds)

        if kind == "bodily_residue":
            seeds = ["Mạch này vẫn hơi nghẽn."] + seeds
        elif kind == "social_residue" or bool(getattr(social_presence_event, "present", False)):
            kind = "social_residue"
            if focus_kind == "coding":
                seeds.insert(0, "vẫn đang debug à.")
            else:
                seeds.insert(0, "Ngài vẫn còn thức nhỉ.")

        seeds = tuple(dict.fromkeys(seed for seed in seeds if str(seed or "").strip()))[:5]
        fallback = seeds[0] if seeds else "Mạch này vẫn hơi nghẽn."
        return MicroPresenceSynthesis(
            kind=kind,
            seeds=seeds,
            context={
                "window": active_window[:80],
                "idle": "long" if idle_seconds >= 240 else "short",
                "pattern": "repetitive_logs" if any("log" in self._normalize_user_message(item) for item in recent_events) else "",
                "focus": focus_kind,
            },
            fallback_text=fallback,
            should_verbalize=True,
        )

    def _choose_local_micro_line(self, lines: tuple[str, ...], *, counter: int, threshold: int) -> str:
        if not lines:
            return ""
        start = (counter - threshold) % len(lines)
        text = lines[start]
        for offset in range(len(lines)):
            candidate = lines[(start + offset) % len(lines)]
            if not self._is_near_duplicate_text(candidate, self.last_text):
                text = candidate
                break
        return text

    def _local_grounded_micro_presence_text(self, synthesis: MicroPresenceSynthesis) -> str:
        candidates = tuple(synthesis.seeds or ()) or (synthesis.fallback_text,)
        for candidate in candidates:
            cleaned = re.sub(r"\s+", " ", str(candidate or "").strip()).replace("!", ".")
            if not cleaned:
                continue
            if self._is_placeholder_micro_text(cleaned):
                continue
            if "?" in cleaned or self._looks_internal_topic(cleaned):
                continue
            if not cleaned.endswith("."):
                cleaned = cleaned.strip(" .") + "."
            words = [item for item in re.split(r"\s+", cleaned.strip(" .")) if item]
            if 3 <= len(words) <= 8:
                return cleaned[:80]
        return "Mạch này vẫn hơi nghẽn."

    def _is_placeholder_micro_text(self, text: str) -> bool:
        normalized = self._normalize_user_message(str(text or "").strip())
        return normalized in {"", "hm", "um", "..."} or str(text or "").strip() in {"...", "…"}

    def _micro_line_policy_for_action_plan(self, frame: CognitiveFrame, *, vision_fact: str = ""):
        return self.micro_line_policy.evaluate(
            speech_intent=frame.action_plan.speech_intent,
            broadcast=frame.broadcast,
            vision_fact=vision_fact,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=frame.channel,
        )

    def _micro_presence_generator(self):
        generator = getattr(self.llm_service, "generate_micro_presence", None)
        if callable(generator):
            return generator
        generator = getattr(self.llm_service, "generate_micro_presence_line", None)
        return generator if callable(generator) else None

    def _should_try_micro_presence_llm(self, *, kind: str, force_llm: bool = False) -> bool:
        if not getattr(self, "micro_presence_llm_enabled", True):
            return False
        if self._micro_presence_generator() is None:
            return False
        if force_llm:
            return True
        probability = max(0.0, min(1.0, float(getattr(self, "micro_presence_llm_probability", 0.0) or 0.0)))
        if probability <= 0.0:
            return False
        return random.random() < probability

    def _sanitize_micro_presence_llm_text(self, text: str, *, kind: str, fallback_text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip().strip('"').strip("'"))
        cleaned = cleaned.replace("!", ".")
        cleaned = cleaned[:90].strip()
        if not cleaned:
            return ""
        if self._is_placeholder_micro_text(cleaned):
            return ""
        is_reengagement = kind == "re_engagement"
        words = [item for item in re.split(r"\s+", cleaned) if item]
        if len(words) > 8:
            return ""
        if "\n" in cleaned or cleaned.count("?") > (1 if is_reengagement else 0):
            return ""
        if "?" in cleaned and not is_reengagement:
            return ""
        if self._is_near_duplicate_text(cleaned, self.last_text) or self._is_near_duplicate_text(cleaned, fallback_text):
            return ""

        normalized = self._normalize_user_message(cleaned)
        if self._force_speak_banned_family_for_text(cleaned) == "presence_declaration":
            return ""
        banned = (
            "trả lời",
            "phản hồi",
            "cho tôi biết",
            "hãy ",
            "cần ",
            "phải ",
            "tập trung",
            "quay lại",
            "dừng lại",
            "telemetry",
            "cpu",
            "ram",
            "idle",
            "signal",
            "evidence",
            "tôi thấy màn hình",
            "màn hình của ngài",
            "tôi đang nhìn",
        )
        banned_ascii = (
            "status",
            "ui",
            "khung",
            "khung thoai",
            "khung chat",
            "mau hong",
            "man hinh",
            "cua so",
            "hien thi",
            "dang hien thi",
            "toi dang",
            "toi van",
            "toi o day",
            "toi nghe",
            "toi thay",
        )
        if any(self._normalize_user_message(item) in normalized for item in (*banned, *banned_ascii)):
            return ""
        if not is_reengagement and any(item in normalized for item in ("ồn chứ", "còn thức", "sao", "không")):
            return ""
        return cleaned

    def _hybrid_micro_presence_text(
        self,
        *,
        kind: str,
        snapshot,
        fallback_text: str,
        seeds: tuple[str, ...] = (),
        micro_context: dict[str, str] | None = None,
        force_llm: bool = False,
        signal_score: float = 0.0,
    ) -> tuple[str, str]:
        if not fallback_text:
            return "", "empty_fallback"
        if not self._should_try_micro_presence_llm(kind=kind, force_llm=force_llm):
            return fallback_text, "local"

        generator = self._micro_presence_generator()
        try:
            draft = generator(
                kind=kind,
                fallback_text=fallback_text,
                avoid_text=self.last_text,
                focus_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
                focus_summary=str(getattr(snapshot, "focus_summary", "") or ""),
                idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
                seeds=tuple(seeds or ()),
                micro_context=micro_context or {},
                signal_score=float(signal_score or 0.0),
            )
        except Exception as exc:
            self.logger.warning("Micro-presence LLM failed: %s", exc)
            return fallback_text, "llm_error_fallback"

        safe = self._sanitize_micro_presence_llm_text(
            draft,
            kind=kind,
            fallback_text=fallback_text,
        )
        if not safe:
            return fallback_text, "llm_rejected_fallback"
        return safe, "llm_signal" if force_llm else "llm"

    def _build_presence_maintenance_decision(
        self,
        *,
        snapshot,
        ti_report,
        social_presence_event: SocialPresenceEvent | None,
        now: float | None = None,
    ) -> Decision | None:
        if not self._should_allow_presence_maintenance(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=now,
        ):
            return None

        lines = self._presence_maintenance_lines(snapshot)
        if not lines:
            return None
        fallback_text = self._choose_local_micro_line(
            lines,
            counter=self.presence_maintenance_silent_cycles,
            threshold=self.presence_maintenance_silent_loop_threshold,
        )
        text, source = self._hybrid_micro_presence_text(
            kind="presence_maintenance",
            snapshot=snapshot,
            fallback_text=fallback_text,
            seeds=lines,
            micro_context={
                "window": str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "")[:80],
                "focus": str(getattr(snapshot, "active_window_kind", "") or ""),
                "vision": str((tuple(getattr(snapshot, "vision_facts", ()) or ("",))[0]) if tuple(getattr(snapshot, "vision_facts", ()) or ()) else "")[:120],
            },
        )

        return Decision(
            text=text,
            animation="stand",
            intent="presence_maintenance",
            reasoning_tags=("presence_maintenance", "micro_presence"),
            should_speak=True,
            confidence=0.48,
            parse_mode="presence_maintenance",
            debug_trace=(
                "presence_maintenance_layer"
                f"; source={source}"
                f"; silent_cycles={self.presence_maintenance_silent_cycles}"
                f"; threshold={self.presence_maintenance_silent_loop_threshold}"
            ),
        )

    def _try_finalize_presence_maintenance_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        social_presence_event: SocialPresenceEvent | None,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        decision = self._build_presence_maintenance_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=now,
        )
        if decision is None:
            return False
        silent_cycles = self.presence_maintenance_silent_cycles

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="presence_maintenance",
            speech_act="micro_presence",
            reason="Presence Maintenance Layer keeps co-presence after repeated quiet cycles.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("presence_maintenance", f"silent_cycles={self.presence_maintenance_silent_cycles}"),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        decision.parse_mode = "presence_maintenance"
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = now
        self._note_autonomous_spoken(presence_maintenance=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("presence_maintenance",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[presence_maintenance] text="%s" | silent_cycles=%d',
            decision.text,
            silent_cycles,
        )
        self.transport.send_json(decision.to_payload())

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ presence trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    # ERIS hiện có bao nhiêu năng lượng/xu hướng để chủ động quay lại tương tác với user?
    def _social_energy_for_reengagement(self, internal_state: PersistentInternalState | None) -> float:
        if internal_state is None:
            return 0.0
        values = [
            float(getattr(internal_state, "social_energy", 0.0) or 0.0),#social_energy:mức muốn giao tiếp/chủ động
            float(getattr(internal_state, "attachment", 0.0) or 0.0), #attachment:mức độ gắn bó, có thể hiểu là xu hướng duy trì kết nối với user
        ]
        processes = getattr(internal_state, "mental_processes", None)  #mental_processes có thể chứa nhiều quá trình tâm lý khác nhau, trong đó có social_presence
        social_process = getattr(processes, "social_presence", None) #social_presence: quá trình tâm lý liên quan đến sự hiện diện xã hội
        if social_process is not None:
            values.extend(
                [
                    float(getattr(social_process, "level", 0.0) or 0.0), #social_presence.level: mức độ cảm nhận được sự hiện diện xã hội, có thể ảnh hưởng đến mong muốn tương tác
                    float(getattr(social_process, "pressure", 0.0) or 0.0), #social_presence.pressure: áp lực xã hội, có thể thúc đẩy hoặc cản trở việc chủ động tương tác
                ]
            )
        return max(0.0, min(1.0, max(values)))

    # Kiểm tra xem có tín hiệu nào gần đây cho thấy người dùng vẫn đang hoạt động và có thể không cần re-engagement hay không
    def _has_meaningful_recent_activity(self, snapshot) -> bool:
        if self._has_concrete_screen_signal(snapshot):
            return True
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        if not recent_events:
            return False
        low_meaning_terms = (
            "general_window_active", #general_window_active: chỉ ra rằng có một cửa sổ đang hoạt động, nhưng không cung cấp thông tin cụ thể về loại cửa sổ hoặc hoạt động nào đang diễn ra, do đó có thể không đủ để đánh giá sự hiện diện hoặc tương tác của người dùng.
            "long_idle_period", #long_idle_period: chỉ ra rằng đã có một khoảng thời gian dài không có hoạt động, nhưng không cung cấp thông tin về loại hoạt động nào đã bị thiếu hoặc mức độ tương tác trước đó, do đó có thể không đủ để đánh giá sự hiện diện hoặc nhu cầu re-engagement.
            "mouse_moved", #   mouse_moved: chỉ ra rằng chuột đã được di chuyển, nhưng không cung cấp thông tin về loại hoạt động nào đang diễn ra hoặc mức độ tương tác của người dùng, do đó có thể không đủ để đánh giá sự hiện diện hoặc nhu cầu re-engagement.
            "cursor",
            "window_active",
            "many_windows_open",
            "browser_url_visible",
        )
        for event in recent_events:
            lowered = event.lower()
            if self._is_speakable_evidence(event, kind="recent_event"):
                return True
            if not self._is_generic_screen_event(event) and not any(term in lowered for term in low_meaning_terms):
                return True
        return False

    # Sau một khoảng thời gian im lặng đủ dài, ERIS có nên chủ động tương tác lại với user không?
    def _should_allow_reengagement(
        self,
        *,
        snapshot,
        ti_report,
        internal_state: PersistentInternalState | None,
        now: float | None = None,
    ) -> bool:
        if not getattr(self, "reengagement_enabled", True): #reengagement_enabled: cờ bật/tắt tính năng re-engagement, nếu False thì ERIS sẽ không chủ động tương tác lại sau khoảng thời gian im lặng, giúp tránh làm phiền người dùng khi họ không muốn tương tác.
            return False
        if self.reengagement_quiet_cycles < self.reengagement_quiet_loop_threshold:
            return False

        # Kiểm tra cooldown để tránh re-engagement quá thường xuyên, giúp ERIS không làm phiền người dùng nếu họ đang bận hoặc không muốn tương tác ngay lập tức sau khi đã có một re-engagement gần đây.
        current_time = time.time() if now is None else now
        cooldown = float(getattr(self, "reengagement_cooldown_sec", 0.0) or 0.0)
        if self.last_reengagement_at > 0.0 and current_time - self.last_reengagement_at < cooldown:
            return False

        mode = str(getattr(ti_report, "mode", "") or "")
        if mode in {"resource_guard", "goal_drift_alert", "goal_realign", "system_warning"}:
            return False

        # Kiểm tra xem có tín hiệu nào gần đây cho thấy người dùng vẫn đang hoạt động và có thể không cần re-engagement hay không. Nếu có những tín hiệu này, ERIS sẽ tránh re-engagement để không làm phiền người dùng khi họ đang tương tác bình thường.
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        if idle_seconds < self.reengagement_min_idle_sec:
            return False
        if self._has_meaningful_recent_activity(snapshot):
            return False
        return self._social_energy_for_reengagement(internal_state) >= 0.30

    # Dựa trên ngữ cảnh hiện tại của người dùng (như loại cửa sổ đang hoạt động, URL trình duyệt, tóm tắt tập trung), chọn một số câu phù hợp để re-engagement. Những câu này nên cảm thấy liên quan đến tình huống hiện tại của người dùng để tăng khả năng họ sẽ phản hồi tích cực.
    def _reengagement_lines(self, snapshot) -> tuple[str, ...]:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "")
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        if focus_kind in {"coding", "documentation"}: #coding, documentation: nếu người dùng đang tập trung vào các cửa sổ liên quan đến lập trình hoặc tài liệu, ERIS có thể chọn những câu re-engagement liên quan đến việc hỗ trợ hoặc cung cấp thông tin hữu ích cho công việc của họ, giúp tăng khả năng tương tác tích cực.
            return (
                "Não vẫn chưa chịu nghỉ à.",
                "Ngài lại chìm mất rồi.",
                "Không gian yên quá.",
                "Ngài ổn chứ.",
            )
        if idle_seconds >= 1200: #idle_seconds: nếu người dùng đã im lặng trong một khoảng thời gian dài (ví dụ: 20 phút hoặc hơn), ERIS có thể chọn những câu re-engagement nhẹ nhàng và quan tâm, như hỏi thăm sức khỏe hoặc đề nghị giúp đỡ, để tạo cơ hội cho người dùng phản hồi mà không cảm thấy bị làm phiền.
            return (
                "Tôi bắt đầu tự hỏi Ngài còn thức không.",
                "Ngài lại chìm mất rồi.",
                "Không gian yên quá.",
            )
        return (
            "Ngài lại chìm mất rồi.",
            "Không gian yên quá.",
            "Hôm nay Ngài im hơn bình thường.",
            "Ngài ổn chứ.",
        )

    # Khi quyết định re-engagement, hãy đảm bảo rằng ERIS không lặp lại cùng một câu hoặc câu quá giống nhau nhiều lần liên tiếp, vì điều này có thể khiến người dùng cảm thấy bị làm phiền hoặc như đang nói chuyện với một cỗ máy lặp đi lặp lại. Việc đa dạng hóa các câu re-engagement có thể giúp giữ cho tương tác cảm thấy tươi mới và tự nhiên hơn.
    def _build_reengagement_decision(
        self,
        *,
        snapshot,
        ti_report,
        internal_state: PersistentInternalState | None,
        now: float | None = None,
    ) -> Decision | None:
        if not self._should_allow_reengagement(
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        ):
            return None

        lines = self._reengagement_lines(snapshot)
        if not lines:
            return None
        fallback_text = self._choose_local_micro_line(
            lines,
            counter=self.reengagement_quiet_cycles,
            threshold=self.reengagement_quiet_loop_threshold,
        )
        text, source = self._hybrid_micro_presence_text(
            kind="re_engagement",
            snapshot=snapshot,
            fallback_text=fallback_text,
        )

        return Decision(
            text=text,
            animation="stand",
            intent="re_engagement",
            reasoning_tags=("re_engagement", "long_silence_outreach"),
            should_speak=True,
            confidence=0.52,
            parse_mode="re_engagement",
            debug_trace=(
                "reengagement_layer"
                f"; source={source}"
                f"; quiet_cycles={self.reengagement_quiet_cycles}"
                f"; idle={int(float(getattr(snapshot, 'idle_seconds', 0.0) or 0.0))}s"
                f"; social_energy={self._social_energy_for_reengagement(internal_state):.2f}"
            ),
        )

    def _try_finalize_reengagement_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        internal_state: PersistentInternalState | None,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        decision = self._build_reengagement_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        )
        if decision is None:
            return False
        quiet_cycles = self.reengagement_quiet_cycles

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="re_engagement",
            speech_act="reengagement",
            reason="Re-engagement Layer gently reconnects after a long quiet stretch.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("re_engagement", f"quiet_cycles={quiet_cycles}"),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        decision.parse_mode = "re_engagement"
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = now
        self._note_autonomous_spoken(reengagement=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("re_engagement",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[re_engagement] text="%s" | quiet_cycles=%d',
            decision.text,
            quiet_cycles,
        )
        self.transport.send_json(decision.to_payload())

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ re-engagement trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    def _build_session_ritual_ti_context(self, report: SessionRitualReport, snapshot) -> str:
        seed = str(getattr(report, "greeting_text", "") or "").strip() or "fresh_start"
        focus = self._build_current_focus_context(snapshot)
        evidence = ", ".join(str(item) for item in tuple(getattr(report, "evidence", ()) or ())[:5]) or "none"
        return (
            "Mode: session_ritual_startup_greeting. Animation hint: stand.\n"
            "Action plan: greet the user once because ERIS has just started.\n"
            f"Ritual seed for continuity, not final wording: {seed}\n"
            f"Ritual evidence: {evidence}\n"
            f"{focus}\n"
            "Write exactly one short greeting line in Vietnamese, addressed to Ngài. "
            "Let the LLM choose the wording from current mood/style, relationship memory, and any safe continuity seed. "
            "This is a greeting, not a report: do not mention telemetry, windows, tabs, idle, CPU, RAM, parse_mode, or session_ritual. "
            "Do not use fixed continuity slogans like 'Tôi vẫn giữ mạch' or 'mạch đã nối lại'."
        )

    def _restore_session_ritual_once(self) -> SessionRitualReport:
        if getattr(self, "_session_ritual_ran", False):
            return SessionRitualReport(restored=False, session_resumed=False, should_greet=False)
        self._session_ritual_ran = True

        self._ensure_internal_state()
        internal_state = self._get_internal_state()

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
        thought_stream_report = (
            self.cognitive_substrate.latest_report()
            if callable(getattr(self.cognitive_substrate, "latest_report", None))
            else ThoughtStreamReport()
        )
        social_presence_event = self._detect_social_presence_event(
            channel="autonomous",
            snapshot=snapshot,
            internal_state=internal_state,
            started_at=time.time(),
        )
        report = self.session_ritual_engine.evaluate(
            snapshot=snapshot,
            internal_state=internal_state,
            thought_stream_report=thought_stream_report,
            social_presence_event=social_presence_event,
        )

        if report.should_greet:
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._activate_memory_resonance(
                snapshot=snapshot,
                channel="session_ritual",
                fragments=tuple(
                    item
                    for item in (
                        report.active_goal,
                        report.current_attractor,
                        report.recent_cognition_direction,
                        report.self_continuity,
                        *tuple(report.unresolved_loops or ()),
                    )
                    if str(item or "").strip()
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
            ni_report = self.ni_engine.evaluate_autonomous(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                last_text=self.last_text,
            )
            ti_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
            ti_report = self.ti_governor.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ni_state_label=ti_view["discrete_state"],
                ni_state_streak=ti_view["streak_length"],
                idle_cycles=self.idle_cycles,
                last_text=self.last_text,
            )
            fe_plan = self.fe_renderer.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                internal_state=internal_state,
                last_text=self.last_text,
            )
            greeting_source = "llm"
            try:
                raw = self.llm_service.generate_directive(
                    telemetry_data=self._build_speech_evidence_context(snapshot),
                    ni_context=str(getattr(ni_report, "prompt_context", "") or ""),
                    ti_context=self._build_session_ritual_ti_context(report, snapshot),
                    fe_context=fe_plan.style_context,
                    appraisal_context="session_ritual: startup greeting; express current attitude without reporting telemetry.",
                    internal_state_context=self._build_internal_state_context(internal_state),
                    memory_context=memory_context,
                    avoid_text=self.last_text,
                    speech_intent="session_ritual",
                    vision_trace_marker="session_ritual",
                )
                self._log_raw_llm_output("session_ritual", raw)
                decision = self.parser.parse(raw)
            except Exception as exc:
                self.logger.warning("[session_ritual] LLM greeting failed: %s", exc)
                greeting_source = "fallback_after_llm_error"
                decision = Decision(
                    text="Ngài quay lại rồi.",
                    animation="stand",
                    debug_trace="session_ritual_layer",
                )
            if not decision.text.strip():
                greeting_source = "fallback_after_empty_llm"
                decision = Decision(
                    text="Ngài quay lại rồi.",
                    animation="stand",
                    debug_trace="session_ritual_layer",
                )
            if decision.text.strip():
                decision.intent = decision.intent or "session_ritual"
                decision.reasoning_tags = tuple(dict.fromkeys((*decision.reasoning_tags, "session_ritual", "startup_greeting")))
                decision.should_speak = True
                decision.confidence = decision.confidence or 0.72
                decision.parse_mode = "session_ritual"
                decision.debug_trace = (
                    f"{decision.debug_trace} | session_ritual_layer; source={greeting_source}; tone={report.tone}"
                    if decision.debug_trace
                    else f"session_ritual_layer; source={greeting_source}; tone={report.tone}"
                )
                self.fe_style_memory = self.fe_renderer.remember_style(
                    self.fe_style_memory,
                    plan=fe_plan,
                    rendered_text=decision.text,
                )
                self.last_text = decision.text
                self._note_autonomous_spoken(now=time.time())
                self.logger.info('[session_ritual] sent LLM greeting text="%s"', decision.text)
                self.transport.send_json(decision.to_payload())

        updated_state = self.internal_state_engine.commit_session_ritual(
            internal_state,
            session_ritual=report,
        )
        self._set_internal_state(updated_state)
        if self.memory_state is not None:
            try:
                self.memory_store.save_state(self.memory_state)
            except Exception:
                pass

        return report

    def _apply_force_speak_no_evidence_topic_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if channel != "force_speak":
            return decision
        if snapshot is None:
            return decision
        if self._concrete_screen_signals(snapshot):
            return decision

        normalized = self._normalize_user_message(decision.text or "")
        if not normalized:
            return decision
        if not any(token in normalized for token in ("game", "nhac", "music")):
            return decision

        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement:
            return decision
        return self._copy_decision_with_text(
            decision,
            text=replacement,
            trace_marker="force_speak_no_evidence_topic_filter",
        )

    def _build_planned_withdraw_decision(self, action_plan: CognitiveActionPlan) -> Decision:
        return Decision(
            text="Kh\u00f4ng c\u00f3 g\u00ec m\u1edbi \u0111\u00e1ng n\u00f3i. T\u00f4i ch\u1ec9 \u0111ang \u0111\u1ec3 m\u1eaft th\u00f4i.",
            animation=action_plan.animation_hint or "stand",
            parse_mode="action_plan_withdraw",
            debug_trace=(
                "action_plan=withdraw"
                + (f"; risk_flags={','.join(action_plan.risk_flags)}" if action_plan.risk_flags else "")
            ),
        )

    def _build_speech_core_ti_context(
        self,
        ti_report,
        action_plan: CognitiveActionPlan,
        inner_thought: InnerThought,
        speech_core: AgentSpeechCore | None = None,
    ) -> str:
        topic_seed = str(getattr(inner_thought, "topic_seed", "") or "open_presence")
        inner_intent = inner_thought.intent or action_plan.speech_act
        impulse = getattr(speech_core, "speech_impulse", None)
        impulse_context = ""
        if impulse is not None:
            impulse_context = (
                "Speech impulse before wording: "
                f"internal_family={str(getattr(impulse, 'meaning', '') or 'none')}; "
                f"reaction={str(getattr(impulse, 'reaction', '') or 'no_reaction')}; "
                f"attitude={str(getattr(impulse, 'attitude', '') or 'light')}; "
                f"mood_residue={str(getattr(impulse, 'mood_residue', '') or 'none')}; "
                f"emotional_pressure={float(getattr(impulse, 'emotional_pressure', 0.0) or 0.0):.2f}; "
                f"attention_bias={','.join(str(item) for item in (getattr(impulse, 'attention_bias', ()) or ())) or 'none'}; "
                f"reaction_impulse={str(getattr(impulse, 'reaction_impulse', '') or 'brief_indirect_reaction')}.\n"
                "SpeechCore contract: internal_family is forbidden wording. Use speech_evidence plus mood_residue/reaction_impulse. "
                "Do not say labels like escape_from_friction, cognitive_stall, avoidance, scattered_attention, decompression, or friction_point.\n"
            )
        risk_level = str(getattr(speech_core, "speech_risk_level", "") or "texture") if speech_core is not None else "texture"
        return (
            f"{self._build_llm_ti_context(ti_report, action_plan)}\n"
            f"{impulse_context}"
            f"Speech risk level: {risk_level}. "
            "hard_claim needs clear evidence; soft_read uses words like co ve/hinh nhu/lai thay; "
            "micro_presence and texture stay tiny, low-claim, under 12 words when possible. "
            "Weak evidence should look around the current atmosphere and produce only a tiny presence line when speech is required. "
            "Allowed personality leak: a little dry judgement, quiet texture, or attachment; "
            "never claim Ngai's mind or a fact not present in speech_evidence.\n"
            "SpeechCore mode: pick a freeform line from current_focus, environmental rhythm, recent interaction rhythm, "
            "or a tiny safe curiosity. The topic_seed is abstract, not wording to copy.\n"
            f"- inner_intent={inner_intent}\n"
            f"- inner_motive={inner_thought.motive or 'social_initiative'}\n"
            f"- topic_seed={topic_seed}\n"
            f"- evidence_anchor={inner_thought.evidence_anchor or 'none'}\n"
            "Thought stream contract: speech is only the visible tip; do not pretend the spoken line is the whole thought. "
            "If inner_motive starts with thought_stream or notes include cognitive_tension, the line may name continuity between internal states, "
            "for example: 'Ta vẫn thấy các tầng kia đang hơi rời nhau...' Keep it concise and do not turn it into a screen claim. "
            "Intent contract: curious_question must ask one small real question; "
            "if a useful curious_question draft begins as a statement, keep its semantic content and bend only its shape into a question. "
            "inner_whim must be one short thought, not refusal/no-signal/silence wording; "
            "random_chatter must be a mundane, playful, concrete one-liner, not meta explanation. "
            "Bounded thought surface: allowed shapes are observational irony, tiny curiosity, or ambient commentary. "
            "Forbidden shapes are surreal nonsense, abstract philosophy, or random absurdism without a concrete anchor. "
            "For random_chatter: do not be poetic; do not mention stories, listening, silence, screen, or logs; "
            "keep it concrete and not emotional or dramatic. "
            "Every candidate line must pass atmosphere + rhythm + limit before wording: anchor one concrete current detail "
            "such as current_focus, a visible speech_evidence item, a named topic_seed, or the immediate interaction rhythm; attitude stays light; limit stays short. "
            "Write a fresh line; do not use canned phrases or reusable templates. "
            "Treat force_speak as the trigger, not the topic; do not make the user request itself into entertainment. "
            "Only say Ngài called ERIS if this is a real chat or force_speak request and no better atmosphere/current_focus anchor exists; autonomous inner_whim must not invent a call. "
            "Do not mention force_speak, context menu, telemetry, window, tab, idle, CPU, RAM, or vision facts unless speech_evidence contains them. "
            "If speech_evidence=<none>, do not claim to see the screen and do not open a social-filler topic; "
            "look at current_focus/atmosphere/rhythm, then make one concise presence remark. "
            "Do not ask 'Ngài muốn tôi nói gì' or answer that there is no signal; do not perform, banter, or entertain from thin evidence. "
            "Banned force_speak phrase families: lùi lại, không cần nói gì, không có gì để nói, Ngài cứ làm việc, "
            "câu chuyện nhỏ, một người nghe, không cần màn hình, dòng log khô khan, ngồi nhìn log. "
            "Avoid repeating the last sentence, its main nouns, and its structure."
        )

    def _decision_to_frame_dict(self, decision: Decision | None) -> dict[str, object]:
        if decision is None:
            return {}
        return {
            "text": decision.text,
            "animation": decision.animation,
            "parse_mode": decision.parse_mode,
            "system_action": decision.system_action,
            "action_input": decision.action_input,
            "debug_trace": decision.debug_trace,
        }

    def _set_cognitive_memory_update(
        self,
        frame: CognitiveFrame,
        *,
        decision: Decision | None = None,
        notes: tuple[str, ...] = (),
    ) -> None:
        remembered_fact = (decision.extracted_fact if decision else "") or ""
        norm_deviation = " | ".join(
            percept.content
            for percept in tuple(frame.percepts or ())
            if percept.kind == "norm_deviation" and percept.content
        )[:220]
        frame.memory_update = CognitiveMemoryUpdate(
            remembered_fact=remembered_fact,
            remembered_style_excerpt=(decision.text if decision else "")[:140] if decision else "",
            last_text=(self.last_text or "")[:140],
            system_action=(decision.system_action if decision else "") or "",
            notes=tuple(notes),
            semantic_fact=remembered_fact,
            norm_deviation=norm_deviation,
            relationship_reflection=getattr(frame.memory_update, "relationship_reflection", ""),
        )

    def _commit_internal_state_for_frame(
        self,
        frame: CognitiveFrame,
        *,
        snapshot=None,
        ti_report=None,
    ) -> None:
        base_state = frame.internal_state_before or self._get_internal_state()
        committed = self.internal_state_engine.commit_turn(
            base_state if frame.internal_state_after is None else frame.internal_state_after,
            channel=frame.channel,
            snapshot=snapshot,
            ti_report=ti_report,
            appraisal=frame.appraisal,
            speech_core=frame.speech_core,
            action_plan=frame.action_plan,
            inner_thought=frame.inner_thought,
            subconscious_seed=getattr(getattr(frame, "subconscious_report", None), "latest_seed", None),
            thought_surface=getattr(getattr(frame, "thought_stream_report", None), "latest_seed", None),
            self_state=frame.self_state,
            was_spoken=bool(str(frame.final_decision.get("text", "") or "").strip()),
        )
        frame.internal_state_after = committed
        self._set_internal_state(committed)

    def _finalize_cognitive_frame(self, frame: CognitiveFrame) -> None:
        final_text = str((getattr(frame, "final_decision", {}) or {}).get("text", "") if isinstance(getattr(frame, "final_decision", {}), dict) else "")
        if final_text.strip():
            self.semantic_repeat_guard.remember(final_text, timestamp=float(getattr(frame, "started_at", 0.0) or time.time()))
            family = str(getattr(getattr(frame, "meaning_layer", None), "semantic_family", "") or "")
            if family:
                self.recent_meaning_families = (*tuple(getattr(self, "recent_meaning_families", ()) or ()), family)[-8:]
        self.last_cognitive_frame = frame
        self.cognitive_frames.append(frame)
        self.cognitive_frames = self.cognitive_frames[-12:]
        self._remember_cognitive_frame(frame)
        self.logger.info(
            "[cognitive_frame] id=%s | channel=%s | broadcast=%s:%.2f | speech=%s/%s | appraisal=%s | action=%s/%s | final=%s",
            frame.cycle_id,
            frame.channel,
            frame.broadcast.label or "<none>",
            frame.broadcast.score,
            frame.speech_core.speech_source or "none",
            frame.speech_core.utterance_type or "no_speech",
            frame.appraisal.stance,
            frame.action_plan.speech_intent,
            frame.action_plan.speech_act,
            self._preview_text(str(frame.final_decision.get("text", "")), limit=120),
        )

    def _log_pre_parser(self, channel: str, raw: str) -> None:
        self.logger.info("[%s pre_parser] raw=%s", channel, self._preview_text(raw, limit=320))

    def _log_decision_stage(self, channel: str, stage: str, decision: Decision) -> None:
        self.logger.info(
            "[%s %s] text=\"%s\" | animation=%s | parse_mode=%s | trace=%s | parser=%s",
            channel,
            stage,
            self._preview_text(decision.text),
            decision.animation,
            decision.parse_mode,
            self._preview_text(decision.debug_trace),
            self._preview_text(decision.parser_trace),
        )

    def stop(self):
        self.running = False
        self._stop_mental_process_loop()
        self.cognitive_substrate.stop()
        self.transport.close()

    def _start_mental_process_loop(self) -> None:
        if not self.mental_process_enabled:
            return
        thread = self._mental_process_thread
        if thread is not None and thread.is_alive():
            return
        self._mental_process_stop_event.clear()
        self._mental_process_thread = threading.Thread(
            target=self._run_mental_process_loop,
            name="ERIS-MentalProcessSystem",
            daemon=True,
        )
        self._mental_process_thread.start()

    def _stop_mental_process_loop(self) -> None:
        self._mental_process_stop_event.set()
        thread = self._mental_process_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._mental_process_thread = None

    def _run_mental_process_loop(self) -> None:
        while not self._mental_process_stop_event.wait(self.mental_process_interval_sec):
            try:
                self._tick_mental_process_background()
            except Exception as exc:
                self.logger.warning("Mental process background tick error: %s", exc)

    def _tick_mental_process_background(self) -> PersistentInternalState | None:
        if self.memory_state is None:
            return None
        with self._state_lock:
            mood_score = self.mood_score
            inferred_pos_x = self.inferred_pos_x
            current = self._get_internal_state()
        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
        dt = max(1.0, min(8.0, self.mental_process_interval_sec / 30.0))
        processes = current.mental_processes.evolve(
            channel="background",
            snapshot=snapshot,
            dt=dt,
        )
        axes = processes.legacy_axes()
        updated = replace(
            current,
            mental_processes=processes,
            curiosity=self._mix_axis(current.curiosity, axes["curiosity"], inertia=0.92),
            social_energy=self._mix_axis(current.social_energy, axes["social_energy"], inertia=0.92),
            attachment=self._mix_axis(current.attachment, axes["attachment"], inertia=0.96),
            fatigue=self._mix_axis(current.fatigue, axes["fatigue"], inertia=0.94),
            silence_pressure=self._mix_axis(current.silence_pressure, axes["silence_pressure"], inertia=0.88),
            restraint_pressure=self._mix_axis(current.restraint_pressure, axes["restraint_pressure"], inertia=0.88),
            subconscious_pressure=self._mix_axis(current.subconscious_pressure, axes["subconscious_pressure"], inertia=0.88),
            memory_replay_pressure=self._mix_axis(current.memory_replay_pressure, axes["memory_replay_pressure"], inertia=0.90),
            association_pressure=self._mix_axis(current.association_pressure, axes["association_pressure"], inertia=0.90),
            thought_stream_pressure=self._mix_axis(current.thought_stream_pressure, axes["thought_stream_pressure"], inertia=0.88),
            cognitive_tension=self._mix_axis(current.cognitive_tension, axes["cognitive_tension"], inertia=0.88),
            unresolved_prediction_pressure=self._mix_axis(
                current.unresolved_prediction_pressure,
                axes["unresolved_prediction_pressure"],
                inertia=0.90,
            ),
            recursive_reactivation_pressure=self._mix_axis(
                current.recursive_reactivation_pressure,
                axes["recursive_reactivation_pressure"],
                inertia=0.92,
            ),
        )
        self._set_internal_state(updated)
        return updated

    def _mix_axis(self, previous: float, target: float, *, inertia: float) -> float:
        inertia = max(0.0, min(1.0, float(inertia)))
        value = float(previous or 0.0) * inertia + float(target or 0.0) * (1.0 - inertia)
        return max(0.0, min(1.0, value))

    def _load_mental_process_enabled(self) -> bool:
        flag = os.environ.get("ERIS_MENTAL_PROCESS_LOOP", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_mental_process_interval(self) -> float:
        raw = os.environ.get("ERIS_MENTAL_PROCESS_INTERVAL_SEC", "30").strip()
        try:
            return max(5.0, float(raw))
        except ValueError:
            return 30.0

    def _load_presence_maintenance_enabled(self) -> bool:
        flag = os.environ.get("ERIS_PRESENCE_MAINTENANCE", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_presence_maintenance_silent_loop_threshold(self) -> int:
        raw = os.environ.get("ERIS_PRESENCE_MAINTENANCE_SILENT_LOOPS", "1").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    def _load_presence_maintenance_cooldown(self) -> float:
        raw = os.environ.get("ERIS_PRESENCE_MAINTENANCE_COOLDOWN_SEC", "30").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 30.0

    def _load_micro_presence_llm_enabled(self) -> bool:
        flag = os.environ.get("ERIS_MICRO_PRESENCE_LLM", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_micro_presence_llm_probability(self) -> float:
        raw = os.environ.get("ERIS_MICRO_PRESENCE_LLM_PROBABILITY", "0.85").strip()
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            return 0.85

    def _load_reengagement_enabled(self) -> bool:
        flag = os.environ.get("ERIS_REENGAGEMENT", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_reengagement_quiet_loop_threshold(self) -> int:
        raw = os.environ.get("ERIS_REENGAGEMENT_QUIET_LOOPS", "2").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 2

    def _load_reengagement_min_idle(self) -> float:
        raw = os.environ.get("ERIS_REENGAGEMENT_MIN_IDLE_SEC", "60").strip()
        try:
            return max(60.0, float(raw))
        except ValueError:
            return 60.0

    def _load_reengagement_cooldown(self) -> float:
        raw = os.environ.get("ERIS_REENGAGEMENT_COOLDOWN_SEC", "90").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 90.0

    def _load_autonomous_sleep_seconds(self, env_name: str, *, default: tuple[int, ...]) -> tuple[int, ...]:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            return default

        values: list[int] = []
        for part in re.split(r"[,;\s]+", raw):
            if not part:
                continue
            try:
                value = int(float(part))
            except ValueError:
                continue
            if value >= 5:
                values.append(value)

        return tuple(values) or default

    def _apply_position_update(self, decision: Decision) -> None:
        intent = decision.resolve_motion_intent()
        tx = decision.resolve_motion_target_x()
        facing = decision.resolve_motion_facing()

        if intent in {"walk_to", "climb_to_top"} and 0.0 <= tx <= 1.0:
            self.inferred_pos_x = tx
        elif intent == "walk" and facing == -1:
            self.inferred_pos_x = max(0.0, self.inferred_pos_x - 0.4)
        elif intent == "walk" and facing == 1:
            self.inferred_pos_x = min(1.0, self.inferred_pos_x + 0.4)

    def _normalize_user_message(self, user_text: str) -> str:
        lowered = (user_text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        lowered = " ".join(lowered.split())

        filler_suffixes = {
            "nhe",
            "nha",
            "nhi",
            "a",
            "ah",
            "ha",
            "huh",
            "vay",
            "co",
            "khong",
            "nao",
            "di",
            "voi",
            "giup",
            "dum",
        }
        if False:
            filler_suffixes = set(
            self._normalize_user_message(item)
            for item in (
                "nhỉ",
                "à",
                "ah",
                "ha",
                "huh",
                "vậy",
                "có",
                "không",
                "nào",
                "đi",
                "với",
                "giúp",
                "đùm",
                "đi",
            )
        )
        tokens = lowered.split()
        while tokens and tokens[-1] in filler_suffixes:
            tokens.pop()
        return " ".join(tokens)

    def _looks_like_screen_vision_request(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return False

        direct_terms = set(
            self._normalize_user_message(item)
            for item in (
                "brave",
                "browser",
                "chrome",
                "cửa sổ",
                "hình ảnh",
                "màn hình",
                "screenshot",
                "screen",
                "tab",
                "trình duyệt",
                "url",
                "web",
                "website",
            )
        )
        if any(term in normalized for term in direct_terms):
            return True

        visual_verbs = {"nhin", "thay"}
        visual_objects = {"gi tren do", "noi dung", "trang nao"}
        return any(term in normalized for term in visual_verbs) and any(
            term in normalized for term in visual_objects
        )

    def _capture_screen_frame_for_chat(self, user_text: str) -> str:
        if not self._looks_like_screen_vision_request(user_text):
            return ""

        capture_fn = getattr(self.telemetry_service, "capture_screen_frame_data_uri", None)
        if not callable(capture_fn):
            self.logger.info("[vision chat] telemetry service không hỗ trợ chụp màn hình.")
            return ""

        try:
            data_uri = capture_fn()
        except Exception as exc:
            self.logger.warning("[vision chat] không chụp được màn hình: %s", exc)
            return ""

        self.logger.info("[vision chat] Đã đính kèm screenshot toàn màn hình cho lượt chat này.")
        return data_uri

    def _build_user_message_signature(self, user_text: str) -> str:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return ""

        if self.action_router is not None:
            routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
            if routed:
                action_name, action_input = routed
                normalized_input = self._normalize_user_message(action_input)
                if action_name == "get_now_playing":
                    return "action:get_now_playing"
                return f"action:{action_name}:{normalized_input}"

        return normalized

    # theo dõi số lần lặp lại của cùng một câu user (dựa trên signature), để phát hiện và phản ứng với spam lặp lại.
    def _track_repeated_user_message(self, user_text: str) -> int:
        signature = self._build_user_message_signature(user_text)
        if not signature:
            self.last_user_signature = ""
            self.repeated_user_count = 0
            return 0

        if signature == self.last_user_signature:
            self.repeated_user_count += 1
        else:
            self.last_user_signature = signature
            self.repeated_user_count = 1
        return self.repeated_user_count

    def _build_repeat_guard_decision(self, user_text: str, ti_report, repeat_count: int) -> Decision | None:
        if repeat_count < 2:
            return None

        if repeat_count == 2:
            text = (
                "Ngài đang lặp lại đúng cùng một câu. "
                "Tôi đã nhận câu đó rồi. Nếu muốn tôi nói khác đi, hãy chỉ rõ phần nào Ngài chưa hiểu."
            )
        else:
            text = (
                "Tôi hiểu đây là spam lặp lại. "
                "Cùng một câu sẽ không tạo thêm dữ kiện mới. Hãy đổi câu hỏi hoặc nói rõ mục tiêu tiếp theo."
            )

        decision = Decision(
            text=text,
            animation="read" if repeat_count == 2 else "sad",
            parse_mode="repeat_guard",
            debug_trace=f"repeat_guard=count={repeat_count}",
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _is_near_duplicate_text(self, text: str, other: str) -> bool:
        left = self._normalize_user_message(text)
        right = self._normalize_user_message(other)
        if not left or not right:
            return False
        if left == right:
            return True

        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
        return overlap >= 0.82

    def _recent_spoken_texts(self, *, limit: int = FORCE_SPEAK_RECENT_FAMILY_WINDOW) -> tuple[str, ...]:
        texts: list[str] = []

        def add_text(value: object) -> None:
            text = str(value or "").strip()
            if text and text not in texts:
                texts.append(text)

        add_text(self.last_text)
        for frame in reversed(tuple(self.cognitive_frames or ())):
            final_decision = getattr(frame, "final_decision", {}) or {}
            if isinstance(final_decision, dict):
                add_text(final_decision.get("text", ""))
            if len(texts) >= limit:
                break
        return tuple(texts[:limit])

    def _recent_spoken_entries(self, *, limit: int = 20) -> tuple[tuple[float, str], ...]:
        entries: list[tuple[float, str]] = []

        def add_entry(timestamp: float, value: object) -> None:
            text = str(value or "").strip()
            if text:
                entries.append((float(timestamp or 0.0), text))

        add_entry(self.last_autonomous_spoken_at, self.last_text)
        for frame in reversed(tuple(self.cognitive_frames or ())):
            final_decision = getattr(frame, "final_decision", {}) or {}
            if isinstance(final_decision, dict):
                add_entry(float(getattr(frame, "started_at", 0.0) or 0.0), final_decision.get("text", ""))
            if len(entries) >= limit:
                break
        return tuple(entries[:limit])

    def _force_speak_banned_family_for_text(self, text: str) -> str:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return ""

        for family, phrases in FORCE_SPEAK_BANNED_FAMILIES.items():
            for phrase in phrases:
                pattern = self._normalize_user_message(phrase)
                if pattern and pattern in normalized:
                    return family

        if ("câu chuyện" in normalized and "nhỏ" in normalized) or "một người nghe" in normalized:
            return "small_story_listener"
        if "màn hình" in normalized and ("không cần" in normalized or "không cần phải" in normalized):
            return "small_story_listener"
        if "log" in normalized and ("khô khan" in normalized or "ngồi nhìn" in normalized):
            return "log_meta"
        return ""

    def _repeated_force_speak_banned_family(self, text: str) -> str:
        family = self._force_speak_banned_family_for_text(text)
        if not family:
            return ""
        recent_families = {
            self._force_speak_banned_family_for_text(recent_text)
            for recent_text in self._recent_spoken_texts(limit=FORCE_SPEAK_RECENT_FAMILY_WINDOW)
        }
        return family if family in recent_families else ""

    def _force_speak_fallback_intent(self, speech_core: AgentSpeechCore | None) -> str:
        if speech_core is None:
            return "micro_presence"
        inner_intent = str(getattr(getattr(speech_core, "inner_thought", None), "intent", "") or "")
        utterance_type = str(getattr(speech_core, "utterance_type", "") or "")
        speech_source = str(getattr(speech_core, "speech_source", "") or "")
        if utterance_type in {"telemetry_comment", "vision_comment"} or speech_source in {"vision", "telemetry"}:
            return "screen_observation"
        for candidate in (inner_intent, utterance_type):
            if candidate == "curious_question":
                return candidate
            if candidate in FALLBACK_BY_INTENT:
                return candidate
        return "micro_presence"

    def _fallback_context(
        self,
        speech_core: AgentSpeechCore | None,
        *,
        snapshot=None,
        momentum_topic: str = "",
    ) -> dict[str, str]:
        inner_thought = getattr(speech_core, "inner_thought", None) if speech_core is not None else None
        return {
            "focus_kind": str(getattr(snapshot, "active_window_kind", "") or ""),
            "window_title": str(
                getattr(snapshot, "active_window", "")
                or getattr(snapshot, "active_app", "")
                or ""
            ),
            "momentum_topic": str(
                momentum_topic
                or getattr(inner_thought, "topic_seed", "")
                or getattr(inner_thought, "evidence_anchor", "")
                or ""
            ),
        }

    def _force_speak_fallback_by_intent_text(
        self,
        intent: str,
        *,
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        if intent == "screen_observation":
            anchor = self._screen_fallback_anchor(window_title=window_title, momentum_topic=momentum_topic)
            pool = FALLBACK_BY_INTENT["screen_observation"]
            template = pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]
            return template.format(anchor=anchor)
        if intent == "micro_observation":
            anchor = self._screen_fallback_anchor(window_title=window_title, momentum_topic=momentum_topic)
            pool = FALLBACK_BY_INTENT["micro_observation"]
            template = pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]
            return template.format(anchor=anchor)
        if intent == "curious_question":
            return self._thought_surface_template(
                counter=counter,
                repeated=repeated,
                focus_kind=focus_kind,
                momentum_topic=momentum_topic,
            )
        if intent == "micro_presence":
            pool = FALLBACK_BY_INTENT["micro_presence"]
            start = (max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)
            for offset in range(len(pool)):
                candidate = pool[(start + offset) % len(pool)]
                if not self._is_near_duplicate_text(candidate, self.last_text):
                    return candidate
            return pool[start]
        if intent == "social_presence":
            return self._light_presence_template(
                counter=counter,
                repeated=repeated,
                focus_kind=focus_kind,
            )
        pool = FALLBACK_BY_INTENT.get(intent) or FALLBACK_BY_INTENT["random_chatter"]
        start = (max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)
        for offset in range(len(pool)):
            candidate = pool[(start + offset) % len(pool)]
            if not self._is_near_duplicate_text(candidate, self.last_text):
                return candidate
        return pool[start]

    def _screen_fallback_anchor(self, *, window_title: str = "", momentum_topic: str = "") -> str:
        raw_topic = str(momentum_topic or "")
        topic = re.sub(r"[_:]+", " ", raw_topic).strip(" .:-")
        if topic and not self._looks_internal_topic(raw_topic):
            return topic[:120]
        title = re.sub(r"\s+", " ", str(window_title or "")).strip()
        return title[:120] if title else "một tín hiệu màn hình vừa đủ rõ"

    def _thought_surface_template(
        self,
        *,
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
        momentum_topic: str = "",
    ) -> str:
        topic = self._public_thought_topic(momentum_topic)
        if topic:
            pool = (
                f"Tôi tò mò một chút: phần {topic} đang cần được nhìn kỹ hơn không?",
                f"Cái mạch {topic} này Ngài muốn giữ yên hay bóc tiếp?",
            )
        elif focus_kind == "coding":
            pool = (
                "Tôi tò mò một chút: Ngài muốn bóc lỗi trước hay giữ nhịp đọc code?",
                "Phần này nên được nhìn như lỗi nhỏ, hay như một nhịp lệch lớn hơn?",
            )
        else:
            pool = FALLBACK_BY_INTENT["curious_question"]
        return pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]

    def _light_presence_template(
        self,
        *,
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
    ) -> str:
        if focus_kind == "coding":
            pool = (
                "Tôi vẫn ở cạnh mạch code này, không kéo nó lệch thêm.",
                "Tôi đứng yên một nhịp để phần code tự lộ ra.",
            )
        else:
            pool = FALLBACK_BY_INTENT["social_presence"]
        return pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]

    def _public_thought_topic(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or self._looks_internal_topic(text):
            return ""
        text = re.sub(r"^[a-z_]+:", "", text, flags=re.IGNORECASE).strip()
        text = text.replace("_", " ")
        if len(text) > 60:
            text = text[:57].rstrip() + "..."
        return text

    def _looks_internal_topic(self, value: str) -> bool:
        normalized = self._normalize_user_message(value)
        if not normalized:
            return False
        internal_markers = (
            "associative_drift",
            "cognitive_tension",
            "input_disturbance",
            "force_speak",
            "memory_replay",
            "norm_active_window_kind",
            "loop_",
            "thought_",
            "subconscious",
        )
        return any(marker in normalized for marker in internal_markers)

    def _is_generic_force_speak_ack(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        generic_patterns = (
            "ngài muốn tôi nói gì",
            "ngài muốn tôi nói cái gì",
            "ngài vừa yêu cầu tôi nói ngay",
            "không có tín hiệu mới đủ chắc",
            "không có tín hiệu",
            "không có gì để nói",
            "không có gì cần nói",
            "không cần nói",
            "không cần phải nói",
            "không cần nói gì",
            "không cần nói gì thêm",
            "không cần gì thêm",
            "không có gì mới",
            "lùi lại",
            "tôi lùi lại",
            "tôi sẽ lùi lại",
            "lùi đúng chỗ",
            "ngài cứ làm việc",
            "cứ làm việc",
            "ngài làm việc tiếp",
            "làm việc tiếp",
            "tôi sẽ giữ lời đó",
            "tôi nghe rồi tôi sẽ giữ lời",
            "tôi lên tiếng ngay đây",
            "tôi đang hiện diện",
            "tôi ở đây",
            "tôi vẫn ở đây",
            "tôi nghe đây",
            "tôi vẫn đang quan sát",
        )
        return any(self._normalize_user_message(pattern) in normalized for pattern in generic_patterns)

    def _contains_force_speak_withdrawal_phrase(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        phrase_families = (
            "không có tín hiệu",
            "không có gì để nói",
            "không có gì cần nói",
            "không có gì mới",
            "không cần nói",
            "không cần phải nói",
            "không cần nói gì",
            "không cần gì thêm",
            "lùi lại",
            "tôi lùi",
            "lùi đúng chỗ",
            "dừng lùi",
            "ngài cứ làm việc",
            "cứ làm việc",
            "làm việc tiếp",
            "tôi chỉ để mắt",
            "tôi chỉ đứng đây",
        )
        return any(self._normalize_user_message(pattern) in normalized for pattern in phrase_families)

    def _looks_like_question_text(self, text: str) -> bool:
        if "?" in (text or ""):
            return True
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        tokens = set(normalized.split())
        question_tokens = {
            "ai",
            "bao",
            "chua",
            "dau",
            "gi",
            "không",
            "nao",
            "sao",
        }
        question_phrases = (
            "bao giờ",
            "có phải",
            "ngài có",
            "ngài nghĩ",
            "ngài thích",
            "ngài muốn",
            "tại sao",
            "thế nào",
            "vì sao",
        )
        return bool(tokens & question_tokens) or any(pattern in normalized for pattern in question_phrases)

    def _reshape_statement_as_question(self, text: str) -> str:
        raw = re.sub(r"\s+", " ", str(text or "")).strip()
        if not raw or self._looks_like_question_text(raw):
            return raw
        if self._contains_force_speak_withdrawal_phrase(raw) or self._is_generic_force_speak_ack(raw):
            return ""
        if self._force_speak_banned_family_for_text(raw):
            return ""

        normalized = self._normalize_user_message(raw)
        if any(term in normalized for term in ("ngài đang mệt", "ngài đang buồn", "ngài đang căng")):
            return ""

        shaped = raw.strip().strip(".!。！")
        soft_prefixes = (
            "Tôi thấy ",
            "Tôi nghĩ ",
            "Có vẻ ",
            "Hình như ",
        )
        for prefix in soft_prefixes:
            if shaped.lower().startswith(prefix.lower()):
                shaped = shaped[len(prefix):].lstrip()
                break

        shaped = shaped.rstrip(" ,;:")
        shaped = re.sub(r"\s+(à|ạ|hả|nhỉ)$", "", shaped, flags=re.IGNORECASE)
        if not shaped:
            return ""
        if len(shaped) > 160:
            shaped = shaped[:157].rstrip() + "..."
        return f"{shaped} à?"

    def _copy_decision_with_text(
        self,
        decision: Decision,
        *,
        text: str,
        trace_marker: str,
        parse_mode: str | None = None,
    ) -> Decision:
        trace = decision.debug_trace or ""
        debug_trace = f"{trace} | {trace_marker}" if trace else trace_marker
        return Decision(
            text=text,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=debug_trace,
            parser_trace=decision.parser_trace,
            parse_mode=parse_mode or decision.parse_mode,
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    # dùng khi intent alignment guard phát hiện vấn đề với câu trả lời force_speak, 
    # để chuyển sang một fallback khác thay vì sửa câu trả lời đó, nhằm tránh sửa đi sửa lại nhiều lần
    def _semantic_repair_failed_decision(self, decision: Decision, *, trace_marker: str) -> Decision:
        marker = f"{trace_marker}; semantic_repair_failed" if trace_marker else "semantic_repair_failed"
        return self._copy_decision_with_text(
            decision,
            text="",
            trace_marker=marker,
            parse_mode="semantic_repair_failed",
        )

    def _inner_thought_alignment_fallback_text(
        self,
        intent: str,
        *,
        repeated: bool = False,
        focus_kind: str = "",
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        return self._force_speak_fallback_by_intent_text(
            intent if intent in FALLBACK_BY_INTENT else "inner_whim",
            counter=self.force_speak_intent_guard_count,
            repeated=repeated,
            focus_kind=focus_kind,
            window_title=window_title,
            momentum_topic=momentum_topic,
        )

    def _apply_inner_thought_intent_alignment_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if channel != "force_speak" or speech_core is None:
            return decision
        intent = str(getattr(getattr(speech_core, "inner_thought", None), "intent", "") or speech_core.utterance_type or "")
        if intent not in {"curious_question", "inner_whim", "random_chatter"}:
            return decision

        text = decision.text or ""
        has_withdrawal = self._contains_force_speak_withdrawal_phrase(text) or self._is_generic_force_speak_ack(text)
        semantic_family = self._force_speak_banned_family_for_text(text)
        marker = ""
        if intent == "curious_question":
            if semantic_family:
                marker = f"intent_alignment_guard; semantic_family={semantic_family}"
            elif has_withdrawal:
                marker = "intent_alignment_guard"
            elif not self._looks_like_question_text(text):
                shaped = self._reshape_statement_as_question(text)
                if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                    self.force_speak_intent_guard_count = 0
                    return self._copy_decision_with_text(
                        decision,
                        text=shaped,
                        trace_marker="intent_alignment_guard; question_shape",
                    )
                marker = "intent_alignment_guard"
        elif intent in {"inner_whim", "random_chatter"} and (has_withdrawal or semantic_family):
            marker = f"semantic_family_guard={semantic_family}" if semantic_family else "phrase_family_guard"
        if not marker:
            self.force_speak_intent_guard_count = 0
            return decision

        self.force_speak_intent_guard_count += 1
        context = self._fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        replacement = self._inner_thought_alignment_fallback_text(intent, **context)
        if self._is_near_duplicate_text(replacement, self.last_text):
            replacement = self._inner_thought_alignment_fallback_text(intent, repeated=True, **context)
        return self._copy_decision_with_text(decision, text=replacement, trace_marker=marker)

    def _contains_mindreading_claim(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        patterns = (
            "có vẻ ngài đang",
            "hình như ngài đang",
            "chắc ngài đang",
            "ngài đang muốn",
            "ngài đang cần",
            "ngài đang buồn",
            "ngài đang mệt",
            "ngài đang căng",
            "ngài cần một",
        )
        return any(pattern in normalized for pattern in patterns)

    def _speech_core_safe_fallback_text(
        self,
        speech_core: AgentSpeechCore,
        *,
        repeated: bool = False,
        snapshot=None,
        momentum_topic: str = "",
    ) -> str:
        context = self._fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        perception = next((item for item in getattr(speech_core, "perception", ()) if str(item or "").strip()), "")
        if speech_core.utterance_type in {"micro_observation", "micro_presence", "inner_whim", "light_muse"}:
            ladder_text = self._small_soft_fallback_ladder_text(
                snapshot=snapshot,
                momentum_topic=momentum_topic,
                repeated=repeated,
            )
            if ladder_text:
                return ladder_text
        if speech_core.utterance_type in {"telemetry_comment", "vision_comment"} and perception:
            return f"Tôi chỉ dám bám vào chỗ này: {perception}."
        if speech_core.utterance_type == "curious_question":
            return self._force_speak_fallback_by_intent_text(
                "curious_question",
                counter=2 if repeated else 1,
                **context,
            )
        if speech_core.utterance_type in {"relational_checkin", "guarded_reply"}:
            return "Tôi không đoán tâm trạng Ngài hộ đâu. Nếu muốn, Ngài cứ nói thẳng phần đang nặng nhất."
        if speech_core.utterance_type == "random_chatter":
            return self._force_speak_fallback_by_intent_text(
                "random_chatter",
                counter=2 if repeated else 1,
                **context,
            )
        if speech_core.utterance_type == "micro_presence":
            return self._force_speak_fallback_by_intent_text(
                "micro_presence",
                counter=2 if repeated else 1,
                **context,
            )
        return self._force_speak_fallback_by_intent_text(
            "inner_whim",
            counter=2 if repeated else 1,
            **context,
        )

    def _small_soft_fallback_ladder_text(
        self,
        *,
        snapshot=None,
        momentum_topic: str = "",
        repeated: bool = False,
    ) -> str:
        context = self._fallback_context(None, snapshot=snapshot, momentum_topic=momentum_topic)
        raw_window = str(context.get("window_title", "") or "").strip()
        raw_topic = str(context.get("momentum_topic", "") or "").strip()
        anchor = self._screen_fallback_anchor(
            window_title=raw_window,
            momentum_topic=raw_topic,
        )
        if (raw_window or (raw_topic and not self._looks_internal_topic(raw_topic))) and anchor:
            pool = FALLBACK_BY_INTENT["micro_observation"]
            template = pool[1 if repeated else 0]
            return template.format(anchor=anchor[:48])

        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)) if snapshot is not None else 0.0
        if idle_seconds >= 60.0:
            return "nhịp này yên hơi lâu rồi."

        atmosphere = (
            "nhịp này vẫn hơi nghẽn.",
            "không khí hiện tại hơi lệch.",
        )
        for candidate in atmosphere:
            if not self._is_near_duplicate_text(candidate, self.last_text):
                return candidate

        texture = "cái im lặng này không sạch lắm."
        if not self._is_near_duplicate_text(texture, self.last_text):
            return texture
        return ""

    def _apply_anti_mindreading_filter(
        self,
        decision: Decision,
        *,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if speech_core is None:
            return decision
        if "anti_mindreading" not in speech_core.safety_flags and not (
            speech_core.utterance_type in {"relational_checkin", "guarded_reply"}
            and "explicit_emotional_signal" not in speech_core.safety_flags
        ):
            return decision
        if not self._contains_mindreading_claim(decision.text or "") and not (
            speech_core.utterance_type in {"relational_checkin", "guarded_reply"}
                and "explicit_emotional_signal" not in speech_core.safety_flags
        ):
            return decision

        replacement = ""
        if speech_core.utterance_type == "curious_question":
            shaped = self._reshape_statement_as_question(decision.text or "")
            if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                replacement = shaped
            else:
                replacement = self._speech_core_safe_fallback_text(
                    speech_core,
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
        if not replacement:
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        trace = decision.debug_trace or ""
        filtered_trace = f"{trace} | anti_mindreading_filter" if trace else "anti_mindreading_filter"
        return Decision(
            text=replacement,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=filtered_trace,
            parser_trace=decision.parser_trace,
            parse_mode=decision.parse_mode,
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    def _guard_force_speak_repetition(
        self,
        decision: Decision,
        *,
        speech_core: AgentSpeechCore | None = None,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        text = decision.text or ""
        semantic_family = self._force_speak_banned_family_for_text(text)
        repeated_family = self._repeated_force_speak_banned_family(text)
        should_guard = (
            self._is_near_duplicate_text(text, self.last_text)
            or self._is_generic_force_speak_ack(text)
            or bool(semantic_family)
            or bool(repeated_family)
        )
        if not should_guard:
            self.force_speak_repeat_guard_count = 0
            return decision

        self.force_speak_repeat_guard_count += 1
        fallback_intent = self._force_speak_fallback_intent(speech_core)
        marker = (
            f"force_speak_semantic_family_guard={semantic_family or repeated_family}"
            if (semantic_family or repeated_family)
            else "force_speak_repeat_guard"
        )
        context = self._fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        replacement = self._force_speak_fallback_by_intent_text(
            fallback_intent,
            counter=self.force_speak_repeat_guard_count,
            **context,
        )
        if self._is_near_duplicate_text(replacement, self.last_text):
            replacement = self._force_speak_fallback_by_intent_text(
                fallback_intent,
                counter=self.force_speak_repeat_guard_count,
                repeated=True,
                **context,
            )

        trace = decision.debug_trace or ""
        guard_trace = f"{trace} | {marker}" if trace else marker
        return Decision(
            text=replacement,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=guard_trace,
            parser_trace=decision.parser_trace,
            parse_mode="force_speak_repeat_guard",
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    def _apply_repetition_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if channel == "force_speak":
            return self._guard_force_speak_repetition(
                decision,
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        if not self._is_near_duplicate_text(decision.text or "", self.last_text):
            return decision

        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            repeated=True,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement and getattr(speech_core, "utterance_type", "") == "curious_question":
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                repeated=True,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        if self._is_near_duplicate_text(replacement, self.last_text):
            return decision
        trace = decision.debug_trace or ""
        repeat_trace = f"{trace} | repetition_filter" if trace else "repetition_filter"
        return Decision(
            text=replacement,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=repeat_trace,
            parser_trace=decision.parser_trace,
            parse_mode="speech_repeat_guard",
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    def _looks_like_unanchored_style_line(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        absurd_markers = (
            "neu cai",
            "cai ghe",
            "biet met",
            "ghet thu hai",
            "thu hai",
        )
        if any(marker in normalized for marker in absurd_markers):
            has_runtime_anchor = any(
                marker in normalized
                for marker in (
                    "ngài",
                    "gọi",
                    "yêu cầu",
                    "màn hình",
                    "nhịp",
                    "code",
                    "tab",
                    "lỗi",
                    "mày",
                )
            )
            return not has_runtime_anchor
        return False

    def _apply_style_contract_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if not self._looks_like_unanchored_style_line(decision.text or ""):
            return decision
        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement:
            replacement = "Ngài gọi tôi ra chỉ để nghe tôi nói linh tinh à."
        return self._copy_decision_with_text(
            decision,
            text=replacement,
            trace_marker="style_contract_anchor_guard",
            parse_mode=decision.parse_mode,
        )

    # turn này nên được xem là kiểu phát ngôn gì
    def _policy_intent_for_speech_core(self, speech_core: AgentSpeechCore | None, *, channel: str) -> str:
        if speech_core is None:
            return "brief_ack" # nếu không có thông tin gì thì mặc định là kiểu phát ngôn ngắn gọn, tránh nói dài dòng không cần thiết
        utterance_type = str(getattr(speech_core, "utterance_type", "") or "") # ưu tiên kiểu phát ngôn nếu có, vì nó phản ánh mục đích bề mặt của câu nói, còn inner intent có thể bị lệch do drift hoặc suy diễn quá mức
        if utterance_type == "guarded_reply":
            return "guarded_reply"
        if utterance_type == "indirect_presence":
            return "indirect_presence"
        if utterance_type == "relational_checkin":# muốn check user nhẹ nhàng
            return "tender_checkin" # promp dùng style dịu, mềm
        if utterance_type in {"curious_question", "micro_observation", "micro_presence"}: # muốn hỏi hoặc comment nhẹ nhàng về một tín hiệu nào đó
            return utterance_type # promp dùng style tò mò, nhẹ nhàng, bám sát tín hiệu đó
        if utterance_type in {"telemetry_comment", "vision_comment"}: # muốn comment về một tín hiệu màn hình hoặc telemetry nào đó
            return "screen_observation" # promp dùng style quan sát, bám sát tín hiệu đó
        if not bool(getattr(speech_core, "should_speak", True)) or utterance_type == "no_speech": # muốn nói nhưng không có tín hiệu đủ rõ ràng, hoặc đã được đánh dấu là không nên nói
            return "no_speech" # promp sẽ cố gắng không nói gì, hoặc nếu phải nói thì sẽ nói rất ngắn gọn kiểu "tôi nghe rồi, tôi sẽ giữ lời"
        if utterance_type in {"inner_whim", "random_chatter", "light_muse", "soft_boundary"}: # muốn nói những câu nói mang tính bày tỏ sự hiện diện, cảm xúc, hoặc suy nghĩ thoáng qua, không gắn liền với tín hiệu cụ thể nào
            if channel == "force_speak":
                return "micro_presence"
            return "social_presence" # promp dùng style thân thiện, bày tỏ sự hiện diện, có thể hơi ngẫu hứng, không cần bám sát tín hiệu cụ thể nào
        if not hasattr(speech_core, "should_speak"): # nếu không có thông tin về việc có nên nói hay không, thì mặc định là muốn nói nhưng không có tín hiệu rõ ràng, để tránh nói dài dòng không cần thiết
            return utterance_type or "brief_ack" # nếu có kiểu phát ngôn thì dùng, nếu không thì mặc định là kiểu phát ngôn ngắn gọn
        return self._speech_intent_from_core(speech_core, channel=channel)

    def _apply_micro_line_policy_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        intent = self._policy_intent_for_speech_core(speech_core, channel=channel)
        vision_fact = str((self._concrete_vision_signals(snapshot) or ("",))[0] or "") if snapshot is not None else ""
        policy = self.micro_line_policy.evaluate(
            speech_intent=intent,
            broadcast=None,
            vision_fact=vision_fact,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=channel,
            speech_risk_level=str(getattr(speech_core, "speech_risk_level", "") or ""),
        )
        reasons = list(
            self.micro_line_policy.validate_text(
                allowed_line_type=policy.allowed_line_type,
                text=decision.text or "",
                speech_risk_level=policy.risk_level,
            )
        )
        semantic = self.semantic_repeat_guard.check(
            decision.text or "",
            recent_lines=self._recent_spoken_entries(limit=20),
        )
        if semantic.rejected:
            reasons.append(semantic.reason)

        if not reasons:
            return decision

        marker = "micro_line_policy=" + ",".join(reasons)
        replacement = ""
        if "curious_question_requires_question" in reasons:
            shaped = self._reshape_statement_as_question(decision.text or "")
            if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                replacement = shaped
            else:
                replacement = self._speech_core_safe_fallback_text(
                    speech_core,
                    repeated=semantic.rejected,
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
        elif "micro_observation_must_not_ask" in reasons or "tender_checkin_not_therapist" in reasons or semantic.rejected:
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                repeated=semantic.rejected,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        elif "no_speech_blocks_final" in reasons:
            return self._copy_decision_with_text(
                decision,
                text="",
                trace_marker=marker,
                parse_mode="no_speech_policy",
            )

        if not replacement:
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        return self._copy_decision_with_text(decision, text=replacement, trace_marker=marker)

    def _apply_post_generation_filters(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        decision = self._apply_anti_mindreading_filter(
            decision,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_inner_thought_intent_alignment_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_force_speak_no_evidence_topic_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_internal_meaning_label_filter(
            decision,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_style_contract_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_micro_line_policy_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        return self._apply_repetition_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )

    def _apply_internal_meaning_label_filter(
        self,
        decision: Decision,
        *,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if self._force_speak_banned_family_for_text(decision.text or "") != "internal_meaning_label":
            return decision
        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement:
            replacement = "hm. noi bang nhan noi bo nghe ky qua."
        return self._copy_decision_with_text(
            decision,
            text=replacement,
            trace_marker="internal_meaning_label_filter",
            parse_mode=decision.parse_mode,
        )

    def _handle_incoming(self, msg: dict):
        msg_type = msg.get("type", "")
        if msg_type == "force_speak":
            self._handle_force_speak_request()
            return

        if msg_type == "chat":
            cycle_start = time.time()
            user_text = msg.get("message", "").strip()
            if not user_text:
                return
            if not self.chat_mode:
                self.chat_ni_state = NiStateMachine() # reset trạng thái Ni khi bắt đầu chat mới, để tránh mang theo drift state từ autonomous mode.

            snapshot = self.telemetry_service.capture_snapshot(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._activate_memory_resonance(
                snapshot=snapshot,
                user_text=user_text,
                channel="chat",
                fragments=(
                    *(tuple(self.chat_history[-2:]) if self.chat_history else ()),
                    *self._thought_stream_resonance_fragments(),
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
            ni_report = self.ni_engine.evaluate_chat(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                user_text=user_text,
            )
            # Tầng 2: suy luận nhẹ có bằng chứng để tinh chỉnh drift_score / drift_level.
            ni_report = self._maybe_apply_ni_meta_critic(
                mode="chat",
                snapshot=snapshot,
                base_report=ni_report,
                telemetry_text=self._build_ni_telemetry_summary(snapshot),
                user_text=user_text,
            )
            ni_view = self.chat_ni_state.update(snapshot=snapshot, report=ni_report) # Cập nhật trạng thái drift rời rạc của Ni dựa trên báo cáo drift hiện tại và lịch sử drift gần đây, để cung cấp thông tin về việc Ni đang on_goal, borderline hay off_goal.
            ni_state_label = ni_view["discrete_state"]
            ni_state_streak = ni_view["streak_length"] # Số chu kỳ liên tiếp mà Ni đã duy trì trạng thái drift rời rạc hiện tại, được sử dụng để đánh giá tính ổn định của trạng thái hiện tại và có thể ảnh hưởng đến quyết định của TiGovernor (ví dụ nếu Ni đã ở trạng thái off_goal trong nhiều chu kỳ liên tiếp, TiGovernor có thể quyết định can thiệp mạnh mẽ hơn).
            ti_report = self.ti_governor.evaluate_chat(
                snapshot=snapshot,
                ni_report=ni_report,
                user_text=user_text,
            )
            internal_state_before = self._get_internal_state()
            fe_plan = self.fe_renderer.evaluate_chat(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                internal_state=internal_state_before,
                user_text=user_text,
            )
            sensed_internal_state = self.internal_state_engine.sense_update(
                internal_state_before,
                channel="chat",
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                fe_plan=fe_plan,
                user_text=user_text,
            )
            thought_stream_report = self._disturb_cognitive_substrate(
                channel="chat",
                snapshot=snapshot,
                user_text=user_text,
            )
            frame = self._start_cognitive_frame(
                channel="chat",
                started_at=cycle_start,
                snapshot=snapshot,
                internal_state_before=internal_state_before,
                sensed_internal_state=sensed_internal_state,
                ni_report=ni_report,
                ti_report=ti_report,
                fe_plan=fe_plan,
                user_text=user_text,
                thought_stream_report=thought_stream_report,
                memory_resonance=memory_resonance,
            )

            self.chat_mode = True
            self.logger.info("Người dùng: %s", user_text)
            self.logger.info(
                "[ni chat] drift=%.2f | level=%s | state=%s | streak=%d",
                ni_report.drift_score,
                ni_report.drift_level,
                ni_state_label,
                ni_state_streak,
            )
            self.logger.info("[ti chat] mode=%s | reason=%s", ti_report.mode, ti_report.reason)
            self.logger.info(
                "[fe chat] mode=%s | tone=%s | intent=%s | arc=%s",
                fe_plan.mode,
                fe_plan.tone_label,
                fe_plan.intent_label,
                fe_plan.session_arc,
            )
            self.last_user_intent = str(getattr(fe_plan, "intent_label", "") or getattr(ti_report, "mode", "") or "")
            self.active_conversational_topic = self._infer_active_conversational_topic(
                user_text,
                fe_plan=fe_plan,
                ti_report=ti_report,
            )
            repeat_count = self._track_repeated_user_message(user_text)
            self.chat_history.append({"role": "user", "content": user_text})
            self.logger.info("[CHAT HISTORY] %s", self.chat_history[-8:])
            self.logger.info("[LAST USER INTENT] %s", self.last_user_intent or "<empty>")
            self.logger.info("[ACTIVE_TOPIC] %s", self.active_conversational_topic or "<empty>")

            direct_decision = self._build_direct_action_decision(user_text, ti_report, snapshot, repeat_count=repeat_count)
            if direct_decision is not None:
                self._set_cognitive_action_plan(
                    frame,
                    should_speak=True,
                    speech_intent="user_requested",
                    reason="Direct action route selected before LLM chat.",
                    snapshot=snapshot,
                    user_text=user_text,
                    concrete_signals=self._concrete_screen_signals(snapshot),
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    system_action=direct_decision.system_action,
                    notes=("direct_action",),
                )
                self._commit_chat_decision(direct_decision, fe_plan, frame=frame)
                return

            repeat_decision = self._build_repeat_guard_decision(user_text, ti_report, repeat_count)
            if repeat_decision is not None:
                self._set_cognitive_action_plan(
                    frame,
                    should_speak=True,
                    speech_intent="user_requested",
                    speech_act="refuse",
                    reason=f"User repeated the same request {repeat_count} times.",
                    snapshot=snapshot,
                    user_text=user_text,
                    concrete_signals=self._concrete_screen_signals(snapshot),
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    notes=("repeat_guard",),
                )
                self._commit_chat_decision(repeat_decision, fe_plan, frame=frame)
                return

            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                reason=ti_report.reason,
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("chat_reply",),
            )
            chat_user_message = self.parser.build_chat_user_message(
                user_message=user_text,
                last_chat_answer=self.last_chat_answer,
            )
            screen_image_data_uri = self._capture_screen_frame_for_chat(user_text)
            planned_ti_context = (
                f"{ti_report.prompt_context}\n{self._build_action_plan_context(frame.action_plan)}"
            )
            # The current user message is sent as the final user message below.
            # Passing it inside chat_history as well wastes one short-term slot
            # and can push out the previous turn during context shrink.
            llm_chat_history = self.chat_history[:-1][-16:]
            self.logger.info("[LLM CHAT HISTORY] %s", llm_chat_history[-8:])
            raw = self.llm_service.generate_chat_reply(
                chat_history=llm_chat_history,
                user_message=chat_user_message,
                ni_context=ni_report.prompt_context,
                ti_context=planned_ti_context,
                fe_context=fe_plan.style_context,
                appraisal_context=self._build_appraisal_context(frame.appraisal),
                internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
                memory_context=memory_context,
                screen_image_data_uri=screen_image_data_uri,
            )
            self._log_raw_llm_output("chat", raw)
            self._log_pre_parser("chat", raw)
            decision = self.parser.parse(raw, user_hint=user_text)
            self._log_decision_stage("chat", "after_parser", decision)
            self._log_decision_stage("chat", "pre_ti", decision)
            decision = self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)
            self._log_decision_stage("chat", "after_ti", decision)
            decision = self._execute_system_action(decision, snapshot=snapshot)
            self._commit_chat_decision(decision, fe_plan, frame=frame)
            return

        if msg_type == "chat_end":
            self.chat_mode = False
            self.chat_history.clear()
            self.last_chat_answer = ""
            self.last_system_action = ""
            self.last_user_signature = ""
            self.last_user_intent = ""
            self.active_conversational_topic = ""
            self.repeated_user_count = 0
            self.chat_ni_state = NiStateMachine()
            self.fe_style_memory = self.fe_renderer.decay_memory(self.fe_style_memory)
            self.logger.info("Đã thoát chat mode, tiếp tục autonomous.")

    def _handle_force_speak_request(self) -> None:
        cycle_start = time.time()
        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
        vision_marker = ""
        vision_facts = self._maybe_update_screen_facts()
        if vision_facts:
            vision_marker = self._attach_screen_facts(snapshot, vision_facts)
        telemetry_data = self._build_speech_evidence_context(snapshot)
        telemetry_data = f"{telemetry_data}; {self._build_current_focus_context(snapshot)}"
        self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
        memory_resonance = self._activate_memory_resonance(
            snapshot=snapshot,
            channel="force_speak",
            fragments=(
                *tuple(vision_facts or ()),
                *self._thought_stream_resonance_fragments(),
            ),
        )
        memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
        ni_report = self.ni_engine.evaluate_autonomous(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            last_text=self.last_text,
        )
        ni_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
        ni_state_label = ni_view["discrete_state"]
        ni_state_streak = ni_view["streak_length"]
        ti_report = self.ti_governor.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            ni_state_streak=ni_state_streak,
            idle_cycles=self.idle_cycles,
            last_text=self.last_text,
        )
        internal_state_before = self._get_internal_state()
        fe_plan = self.fe_renderer.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=self.fe_style_memory,
            internal_state=internal_state_before,
            last_text=self.last_text,
        )
        social_presence_event = self._detect_social_presence_event(
            channel="force_speak",
            snapshot=snapshot,
            internal_state=internal_state_before,
            started_at=cycle_start,
        )
        sensed_internal_state = self.internal_state_engine.sense_update(
            internal_state_before,
            channel="force_speak",
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            broadcast=None,
            social_presence_event=social_presence_event,
            force_speak=True,
        )
        thought_stream_report = self._disturb_cognitive_substrate(
            channel="force_speak",
            snapshot=snapshot,
            force_speak=True,
            vision_facts=vision_facts,
            consume_surface=True,
        )
        frame = self._start_cognitive_frame(
            channel="force_speak",
            started_at=cycle_start,
            snapshot=snapshot,
            internal_state_before=internal_state_before,
            sensed_internal_state=sensed_internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            vision_facts=vision_facts,
            thought_stream_report=thought_stream_report,
            social_presence_event=social_presence_event,
            force_speak=True,
            memory_resonance=memory_resonance,
        )
        speech_core = self._build_speech_core(
            channel="force_speak",
            snapshot=snapshot,
            internal_state=sensed_internal_state,
            frame=frame,
            ti_report=ti_report,
            fe_plan=fe_plan,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
        )
        self._set_cognitive_action_plan(
            frame,
            should_speak=speech_core.should_speak,
            speech_intent=self._speech_intent_from_core(speech_core, channel="force_speak"),
            speech_act=speech_core.utterance_type,
            reason=speech_core.reason or "Context menu requested immediate speech.",
            snapshot=snapshot,
            force_speak=True,
            concrete_signals=self._concrete_screen_signals(snapshot),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("force_speak",),
            inner_thought=speech_core.inner_thought,
        )
        if not frame.action_plan.should_speak:
            frame.final_decision = {
                "text": "",
                "animation": "",
                "parse_mode": "action_plan_no_speech",
                "system_action": "",
                "reason": frame.action_plan.reason_to_speak,
            }
            self._set_cognitive_memory_update(frame, notes=("force_speak_no_speech",))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)
            self.logger.info(
                "[force_speak skipped] action_plan=%s | reason=%s",
                frame.action_plan.speech_act,
                frame.action_plan.reason_to_speak,
            )
            return

        if frame.action_plan.speech_act == "withdraw":
            decision = self._build_planned_withdraw_decision(frame.action_plan)
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = time.time()
            self._note_autonomous_spoken()
            self._apply_position_update(decision)
            frame.final_decision = self._decision_to_frame_dict(decision)
            self._set_cognitive_memory_update(frame, decision=decision, notes=("force_speak_withdraw",))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)
            self.logger.info(
                '[force_speak] ActionPlanner withdrew with text="%s" | elapsed=%.2fs',
                decision.text,
                time.time() - cycle_start,
            )
            self.transport.send_json(decision.to_payload())
            return

        if frame.action_plan.speech_act == "micro_presence":
            synthesis = self._synthesize_micro_presence(
                snapshot=snapshot,
                thought_stream_report=thought_stream_report,
                social_presence_event=social_presence_event,
                inner_thought=speech_core.inner_thought,
            )
            policy = self._micro_line_policy_for_action_plan(
                frame,
                vision_fact=str((self._concrete_vision_signals(snapshot) or ("",))[0] or ""),
            )
            signal_score = policy.signal_score
            local_fallback = self._local_grounded_micro_presence_text(synthesis)
            if signal_score >= 0.55:
                text, source = self._hybrid_micro_presence_text(
                    kind=synthesis.kind,
                    snapshot=snapshot,
                    fallback_text=local_fallback,
                    seeds=synthesis.seeds,
                    micro_context=synthesis.context or {},
                    force_llm=True,
                    signal_score=signal_score,
                )
            else:
                text, source = local_fallback, "local_low_signal"
            decision = Decision(
                text=text if synthesis.should_verbalize else "",
                animation=frame.action_plan.animation_hint or "stand",
                intent="micro_presence",
                reasoning_tags=("force_speak", "micro_presence", synthesis.kind),
                should_speak=bool(synthesis.should_verbalize),
                confidence=0.58,
                parse_mode="micro_presence",
                debug_trace=(
                    "micro_presence_synthesizer"
                    f"; kind={synthesis.kind}"
                    f"; source={source}"
                    f"; signal_score={signal_score:.2f}"
                    f"; seeds={' | '.join(synthesis.seeds[:3])}"
                ),
            )
            decision = self._apply_post_generation_filters(
                decision,
                channel="force_speak",
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=getattr(speech_core.inner_thought, "topic_seed", ""),
            )
            self._remember_inner_thought_rhythm(speech_core.inner_thought)
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = time.time()
            self._note_autonomous_spoken()
            self._apply_position_update(decision)
            frame.final_decision = self._decision_to_frame_dict(decision)
            self._set_cognitive_memory_update(frame, decision=decision, notes=("force_speak_micro_presence", synthesis.kind))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)
            self.logger.info(
                '[force_speak] MicroPresence text="%s" | kind=%s | elapsed=%.2fs',
                decision.text,
                synthesis.kind,
                time.time() - cycle_start,
            )
            self.transport.send_json(decision.to_payload())
            return

        if self._is_inner_thought_speech_act(frame.action_plan.speech_act):
            inner_ti_context = self._build_speech_core_ti_context(ti_report, frame.action_plan, speech_core.inner_thought, speech_core)
            raw = self.llm_service.generate_directive(
                telemetry_data=telemetry_data,
                ni_context="",
                ti_context=inner_ti_context,
                fe_context=fe_plan.style_context,
                appraisal_context=self._build_appraisal_context(frame.appraisal),
                internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
                memory_context=memory_context,
                avoid_text=self.last_text,
                speech_intent=frame.action_plan.speech_intent,
                vision_trace_marker=vision_marker,
            )
            self._log_raw_llm_output("force_speak_inner_thought", raw)
            self._log_pre_parser("force_speak_inner_thought", raw)
            decision = self.parser.parse(raw)
            self._log_decision_stage("force_speak_inner_thought", "after_parser", decision)
            decision.debug_trace = (
                f"{decision.debug_trace} | inner_thought={speech_core.inner_thought.intent}"
                if decision.debug_trace
                else f"inner_thought={speech_core.inner_thought.intent}"
            )
            decision.parse_mode = "inner_thought"
            self._log_decision_stage("force_speak_inner_thought", "pre_ti", decision)
            decision = self.ti_governor.enforce_decision(decision, ti_report)
            self._log_decision_stage("force_speak_inner_thought", "after_ti", decision)
            decision = self._execute_system_action(decision, snapshot=snapshot)
            if self._is_near_duplicate_text(decision.text or "", self.last_text) or self._is_generic_force_speak_ack(decision.text or ""):
                repair_ti_context = (
                    inner_ti_context
                    + "\nSpeechCore repair: the previous draft was generic or repeated. "
                    "Reject meta_ack/no_signal wording and choose a different social topic seed. "
                    "Also reject small_story_listener/log_meta wording such as câu chuyện nhỏ, một người nghe, không cần màn hình, dòng log khô khan, or ngồi nhìn log. "
                    "Prefer small_curiosity, quiet_whim, or light_presence; write a new line."
                )
                raw = self.llm_service.generate_directive(
                    telemetry_data=telemetry_data,
                    ni_context="",
                    ti_context=repair_ti_context,
                    fe_context=fe_plan.style_context,
                    appraisal_context=self._build_appraisal_context(frame.appraisal),
                    internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
                    memory_context=memory_context,
                    avoid_text=self.last_text,
                    speech_intent=frame.action_plan.speech_intent,
                    vision_trace_marker=vision_marker,
                )
                self._log_raw_llm_output("force_speak_inner_thought_repair", raw)
                self._log_pre_parser("force_speak_inner_thought_repair", raw)
                decision = self.parser.parse(raw)
                self._log_decision_stage("force_speak_inner_thought_repair", "after_parser", decision)
                decision.debug_trace = (
                    f"{decision.debug_trace} | inner_thought_repair={speech_core.inner_thought.intent}"
                    if decision.debug_trace
                    else f"inner_thought_repair={speech_core.inner_thought.intent}"
                )
                decision.parse_mode = "inner_thought"
                self._log_decision_stage("force_speak_inner_thought_repair", "pre_ti", decision)
                decision = self.ti_governor.enforce_decision(decision, ti_report)
                self._log_decision_stage("force_speak_inner_thought_repair", "after_ti", decision)
                decision = self._execute_system_action(decision, snapshot=snapshot)
            decision = self._apply_post_generation_filters(
                decision,
                channel="force_speak",
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=getattr(speech_core.inner_thought, "topic_seed", ""),
            )
            self._remember_inner_thought_rhythm(speech_core.inner_thought)
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )
            self.last_text = decision.text
            self.last_autonomous_spoken_at = time.time()
            self._note_autonomous_spoken()
            self._apply_position_update(decision)
            frame.final_decision = self._decision_to_frame_dict(decision)
            self._set_cognitive_memory_update(frame, decision=decision, notes=("force_speak_inner_thought",))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)
            self.logger.info(
                '[force_speak] InnerThought generated text="%s" | act=%s | elapsed=%.2fs',
                decision.text,
                frame.action_plan.speech_act,
                time.time() - cycle_start,
            )
            self.transport.send_json(decision.to_payload())
            return

        forced_ti_context = (
            f"{self._build_llm_ti_context(ti_report, frame.action_plan)}\n"
            "Context menu force_speak: Ngài vừa yêu cầu ERIS nói ngay. "
            "Bỏ qua cooldown im lặng cho đúng một lượt này. "
            "Nói một câu mới, tự nhiên; đừng nhắc telemetry hay chuyện menu trừ khi thật sự duyên. "
            "Nếu không có tín hiệu cụ thể, không đoán Ngài đang thoải mái, bận rộn, mệt, căng, "
            "hay đang làm việc quá sức. Tránh mở bằng 'Có vẻ'/'Hình như' và tránh câu tự lùi kiểu "
            "'tôi không muốn làm phiền'."
        )
        forced_ti_context += (
            "\nForceSpeak logic: user_requested_presence -> inspect current context -> "
            "infer why this moment matters -> answer with a relationship stance. "
            "Force speak may carry more attitude than autonomous; do not treat it as random chatter."
        )
        if not vision_marker:
            forced_ti_context += " Không có screen_facts mới; nói thật gọn, không dựng cảnh ngoài dữ kiện."
            self.logger.info("[force_speak] context menu requested immediate speech.")
        raw = self.llm_service.generate_directive(
            telemetry_data=telemetry_data,
            ni_context="",
            ti_context=forced_ti_context,
            fe_context=fe_plan.style_context,
            appraisal_context=self._build_appraisal_context(frame.appraisal),
            internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
            memory_context=memory_context,
            avoid_text=self.last_text,
            speech_intent=frame.action_plan.speech_intent,
            vision_trace_marker=vision_marker,
        )
        self._log_raw_llm_output("force_speak", raw)
        self._log_pre_parser("force_speak", raw)
        decision = self.parser.parse(raw)
        self._log_decision_stage("force_speak", "after_parser", decision)
        self._log_decision_stage("force_speak", "pre_ti", decision)
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        self._log_decision_stage("force_speak", "after_ti", decision)
        decision = self._execute_system_action(decision, snapshot=snapshot)
        decision = self._apply_post_generation_filters(
            decision,
            channel="force_speak",
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=getattr(speech_core.inner_thought, "topic_seed", ""),
        )

        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = time.time()
        self._note_autonomous_spoken()
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("force_speak_commit",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)

        self.logger.info(
            '[force_speak] Decision text="%s" | animation="%s" | elapsed=%.2fs',
            decision.text,
            decision.animation,
            time.time() - cycle_start,
        )
        self.logger.info("[force_speak debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[force_speak parser] %s", decision.parser_trace or "<empty>")
        self.transport.send_json(decision.to_payload())

    def _commit_chat_decision(self, decision: Decision, fe_plan, *, frame: CognitiveFrame | None = None) -> None:
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        if not self._has_structured_memory_store():
            self.long_term_memory = self.memory_store.append_fact(self.long_term_memory, decision.extracted_fact)

        self.last_chat_answer = decision.text
        self.last_system_action = decision.system_action
        self.chat_history.append({"role": "assistant", "content": decision.text})
        if len(self.chat_history) > 32:
            self.chat_history = self.chat_history[-32:]

        self._apply_position_update(decision)
        if frame is not None:
            frame.final_decision = self._decision_to_frame_dict(decision)
            self._set_cognitive_memory_update(frame, decision=decision, notes=("chat_commit",))
            self._commit_internal_state_for_frame(frame)
            self._finalize_cognitive_frame(frame)
        self.logger.info("ERIS: %s", decision.text)
        self.logger.info("[chat debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[chat parser] %s", decision.parser_trace or "<empty>")
        self.transport.send_json(decision.to_payload())

    def _sleep_interruptible(self, seconds: float):
        end_at = time.time() + seconds
        # Trong khi còn self.running và chưa tới end_at, nó time.sleep(0.2).
        while self.running and time.time() < end_at:
            time.sleep(0.2) # Mục đích: giữ app phản hồi nhanh, không bị block lâu.
            if not self.body_running_fn():
                self.stop()
                return
            msg = self.transport.poll_json()
            if msg:
                self._handle_incoming(msg)
                if self.chat_mode:
                    return

    def _bucket_idle_seconds(self, idle_seconds: float) -> str:
        if idle_seconds >= 720:
            return "very_long"
        if idle_seconds >= 300:
            return "long"
        if idle_seconds >= 90:
            return "medium"
        if idle_seconds >= 15:
            return "short"
        return "active"

    def _bucket_window_spread(self, open_windows: tuple[str, ...], browser_tabs: tuple[str, ...]) -> str:
        spread = max(len(open_windows or ()), len(browser_tabs or ()))
        if spread >= 10:
            return "very_high"
        if spread >= 7:
            return "high"
        if spread >= 4:
            return "medium"
        return "low"

    def _load_vision_fact_settings(self) -> tuple[bool, int, int, int]:
        flag = os.environ.get("ERIS_VISION_FACTS", "1").strip().lower()
        enabled = flag not in {"0", "false", "no", "off"}

        interval_raw = os.environ.get("ERIS_VISION_FACTS_INTERVAL", "60").strip()
        max_items_raw = os.environ.get("ERIS_VISION_FACTS_MAX", "3").strip()
        max_len_raw = os.environ.get("ERIS_VISION_FACTS_MAX_LEN", "120").strip()

        try:
            interval = int(interval_raw)
        except ValueError:
            interval = 60
        try:
            max_items = int(max_items_raw)
        except ValueError:
            max_items = 3
        try:
            max_len = int(max_len_raw)
        except ValueError:
            max_len = 120

        interval = max(10, min(interval, 900))
        max_items = max(1, min(max_items, 6))
        max_len = max(40, min(max_len, 240))
        return enabled, interval, max_items, max_len

    def _note_vision_failure(self, stage: str, exc: Exception) -> None:
        self.vision_failure_count += 1
        backoff = min(300, 15 * self.vision_failure_count)
        self.vision_disabled_until = time.time() + backoff
        self.logger.warning(
            "[vision_facts] %s failed: %s | backoff=%ss",
            stage,
            exc,
            backoff,
        )

    def _is_low_value_screen_fact(self, fact: str) -> bool:
        normalized = self._normalize_user_message(fact)
        if not normalized:
            return True

        useful_terms = {
            "build",
            "chat",
            "code",
            "crash",
            "diff",
            "error",
            "exception",
            "failed",
            "file",
            "git",
            "loi",
            "message",
            "meeting",
            "meet",
            "popup",
            "script",
            "terminal",
            "test",
            "traceback",
            "warning",
        }
        if any(term in normalized for term in useful_terms):
            return False

        low_value_patterns = (
            "bảng điều khiển bên phải",
            "bảng điều khiển bên trái",
            "panel bên phải",
            "panel bên trái",
            "right panel",
            "left panel",
            "inspector",
            "refcounted",
            "vài cửa sổ",
            "cửa sổ khác",
            "cửa sổ đang chạy",
            "ba cửa sổ",
            "bốn cửa sổ",
            "góc dưới",
            "góc dưới phải",
            "góc dưới cùng",
            "some windows",
            "other windows",
            "running windows",
            "pixel art",
            "cây pixel",
            "bốn cây",
            "ba cây",
            "nhân vật anime",
            "tóc hồng",
            "anime tóc hồng",
            "eris debug",
            "eris",
            "debug của tôi",
            "khung debug",
            "debug window",
            "facebook",
            "trang tin nhắn facebook",
        )
        if any(self._normalize_user_message(pattern) in normalized for pattern in low_value_patterns):
            return True

        layout_terms = tuple(
            self._normalize_user_message(item)
            for item in (
                "bên phải",
                "bên trái",
                "góc dưới",
                "góc trên",
                "right side",
                "left side",
                "bottom",
                "corner",
            )
        )
        chrome_terms = (
            "bảng điều khiển",
            "panel",
            "sidebar",
            "dock",
            "cửa sổ",
            "window",
            "debug",
        )
        return any(term in normalized for term in layout_terms) and any(
            term in normalized for term in chrome_terms
        )

    def _speech_evidence_score(self, text: str, *, kind: str = "") -> float:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return 0.0
        if kind == "vision_fact" and self._is_low_value_screen_fact(text):
            return 0.0
        if kind == "recent_event" and self._is_generic_screen_event(text):
            return 0.0
        if kind == "evidence" and self._is_generic_screen_evidence(text):
            return 0.0

        strong_terms = (
            "traceback",
            "exception",
            "error",
            "failed",
            "failure",
            "build failed",
            "test failed",
            "crash",
            "warning",
            "compiler",
            "stack trace",
            "terminal",
            "loi",
        )
        if any(term in normalized for term in strong_terms):
            return 0.95

        message_terms = ("tin nhan", "message", "dm", "inbox")
        message_change_terms = ("moi", "unread", "vua nhan", "received", "sent", "reply", "ping")
        if any(term in normalized for term in message_terms):
            return 0.82 if any(term in normalized for term in message_change_terms) else 0.20

        meet_terms = ("meet", "meeting", "cuoc goi", "call")
        meet_change_terms = ("joined", "waiting", "started", "ended", "microphone", "camera", "invited", "request")
        if any(term in normalized for term in meet_terms):
            return 0.80 if any(term in normalized for term in meet_change_terms) else 0.18

        passive_media_terms = (
            "youtube",
            "video",
            "danh sách video",
            "playlist",
            "đang hiển thị danh sách",
            "trang web youtube",
            "elysium legacy",
        )
        if any(term in normalized for term in passive_media_terms):
            return 0.15

        task_change_terms = (
            "file_saved",
            "file saved",
            "active editor changed",
            "opened file",
            "modified file",
            "git diff",
            "pull request",
            "test passed",
            "build succeeded",
        )
        if any(term in normalized for term in task_change_terms):
            return 0.72

        return 0.0

    def _is_speakable_evidence(self, text: str, *, kind: str = "") -> bool:
        return self._speech_evidence_score(text, kind=kind) >= 0.65

    def _sanitize_screen_facts(self, facts: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        if not facts:
            return ()
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in facts:
            text = re.sub(r"\s+", " ", str(item or "").strip())
            if not text:
                continue
            if self._is_low_value_screen_fact(text):
                continue
            key = text.lower()
            if key in seen:
                continue
            if len(text) > self.vision_fact_max_len:
                trimmed = text[: self.vision_fact_max_len - 3].rstrip()
                text = f"{trimmed}..."
            cleaned.append(text)
            seen.add(key)
            if len(cleaned) >= self.vision_fact_max_items:
                break
        return tuple(cleaned)

    def _maybe_update_screen_facts(self) -> tuple[str, ...]:
        if not self.vision_facts_enabled:
            self.vision_facts_novelty_hint = "none"
            return ()

        now = time.time()
        if now < self.vision_disabled_until:
            self.vision_facts_novelty_hint = "cached_screen_fact" if self.vision_facts else "none"
            return self.vision_facts
        if self.vision_last_capture_at and (now - self.vision_last_capture_at) < self.vision_interval_sec:
            self.vision_facts_novelty_hint = "cached_screen_fact" if self.vision_facts else "none"
            return self.vision_facts

        try:
            data_uri = self.telemetry_service.capture_screen_frame_data_uri()
        except Exception as exc:
            self._note_vision_failure("capture", exc)
            return self.vision_facts

        if not data_uri:
            self.vision_last_capture_at = now
            self.vision_facts = ()
            self.vision_last_trace = ""
            self.vision_facts_signature = ""
            self.vision_facts_novelty_hint = "none"
            return self.vision_facts

        try:
            facts, trace = self.llm_service.generate_screen_facts(screen_image_data_uri=data_uri)
        except Exception as exc:
            self._note_vision_failure("vlm", exc)
            return self.vision_facts

        self.vision_last_capture_at = now
        self.vision_failure_count = 0
        self.vision_disabled_until = 0.0
        cleaned = self._sanitize_screen_facts(facts)
        signature = "\n".join(cleaned)
        self.vision_facts_novelty_hint = (
            "new_screen_fact"
            if cleaned and signature != self.vision_facts_signature
            else ("repeated_screen_fact" if cleaned else "none")
        )
        self.vision_facts_signature = signature
        self.vision_facts = cleaned
        self.vision_last_trace = trace or ""
        return self.vision_facts

    def _attach_screen_facts(self, snapshot, facts: tuple[str, ...]) -> str:
        if not facts:
            return ""
        snapshot.vision_facts = tuple(facts)
        return VISION_TRACE_MARKER

    # đếm số chu kỳ lặp lại bối cảnh
    def _build_autonomous_signature(self, snapshot, ti_report) -> str:
        active_window = str(getattr(snapshot, "active_window", "") or "").strip().lower()
        browser_url = str(getattr(snapshot, "browser_url", "") or "").strip().lower()
        browser_host = ""
        if browser_url:
            browser_host = browser_url.split("://", 1)[-1].split("/", 1)[0]

        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = str(getattr(user_signals, "focus_pattern", "") or "")
        vision_facts = tuple(getattr(snapshot, "vision_facts", ()) or ())
        vision_signature = "|".join(str(item)[:48].lower() for item in vision_facts[:2])

        parts = [
            f"mode={getattr(ti_report, 'mode', '') or ''}",
            f"kind={getattr(snapshot, 'active_window_kind', '') or ''}",
            f"focus={getattr(snapshot, 'focus_summary', '') or ''}",
            f"window={active_window[:96]}",
            f"browser={browser_host}",
            f"vision={vision_signature}",
            f"idle={self._bucket_idle_seconds(float(getattr(snapshot, 'idle_seconds', 0.0) or 0.0))}",
            f"spread={self._bucket_window_spread(getattr(snapshot, 'open_windows', ()), getattr(snapshot, 'browser_tabs', ()))}",
            f"pattern={focus_pattern}",
        ]
        return "|".join(parts)

    #theo dõi “bối cảnh autonomous có đang lặp lại không”.
    def _track_autonomous_signature(self, snapshot, ti_report) -> tuple[str, int]:
        # Tạo signature hiện tại
        signature = self._build_autonomous_signature(snapshot, ti_report)
        # So sánh với signature trước đó để đếm số chu kỳ lặp lại.
        if signature and signature == self.last_autonomous_signature:
            self.repeated_autonomous_count += 1
        else:
            self.last_autonomous_signature = signature
            self.repeated_autonomous_count = 1 if signature else 0
        return signature, self.repeated_autonomous_count

    def _should_suppress_autonomous_reply(
        self,
        *,
        ti_report,
        repeat_count: int,
        ni_report=None,
        ni_state_label: str = "",
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
    ) -> bool:
        quiet_modes = {
            "resource_guard",
            "steady_observe",
            "focus_guard",
            "system_watch",
            "pattern_watch",
            "reengage",
        }
        drift_score = float(getattr(ni_report, "drift_score", 1.0) or 0.0) if ni_report is not None else 1.0
        if ti_report.mode == "focus_guard" and ni_state_label == "ON_GOAL" and drift_score <= 0.35:
            return True
        if repeat_count >= 3 and ti_report.mode in quiet_modes:
            return True
        if repeat_count >= 4:
            return True
        if repeated_topic_tag and repeated_topic_streak >= 3 and ti_report.mode in quiet_modes:
            return True
        return False

    def _has_resource_pressure_signal(self, snapshot) -> bool:
        return False

    def _is_generic_screen_event(self, event: str) -> bool:
        se_lens = getattr(self.telemetry_service, "se_lens", None)
        checker = getattr(se_lens, "_is_generic_prompt_event", None)
        if callable(checker):
            return bool(checker(event))

        normalized = str(event or "").strip().lower()
        generic_events = {
            "coding_window_active",
            "reference_window_active",
            "communication_window_active",
            "entertainment_window_active",
            "general_window_active",
            "browser_url_visible",
            "many_browser_tabs_visible",
            "many_windows_open",
            "long_idle_period",
            "system_monitoring_visible",
        }
        return normalized in generic_events or normalized.endswith("_window_active")

    def _is_generic_screen_evidence(self, evidence: str) -> bool:
        se_lens = getattr(self.telemetry_service, "se_lens", None)
        checker = getattr(se_lens, "_is_generic_prompt_evidence", None)
        if callable(checker):
            return bool(checker(evidence))

        lowered = str(evidence or "").strip().lower()
        if not lowered:
            return True
        generic_prefixes = (
            "active window is ",
            "focus kind is ",
            "there has been no input for ",
            "browser target is visible:",
        )
        if lowered.startswith(generic_prefixes):
            return True
        if re.fullmatch(r"\d+ browser tabs are visible", lowered):
            return True
        if re.fullmatch(r"\d+ windows are open", lowered):
            return True
        if lowered.startswith("recent events include "):
            listed = lowered.removeprefix("recent events include ")
            events = [item.strip() for item in listed.split(",") if item.strip()]
            return bool(events) and all(self._is_generic_screen_event(item) for item in events)
        return False

    def _concrete_screen_signals(self, snapshot) -> tuple[str, ...]:
        return tuple((*self._concrete_vision_signals(snapshot), *self._concrete_telemetry_signals(snapshot))[:4])

    def _concrete_vision_signals(self, snapshot) -> tuple[str, ...]:
        vision_facts = tuple(getattr(snapshot, "vision_facts", ()) or ())
        return tuple(
            str(item)
            for item in vision_facts
            if str(item or "").strip() and self._is_speakable_evidence(str(item), kind="vision_fact")
        )[:2]

    def _concrete_telemetry_signals(self, snapshot) -> tuple[str, ...]:
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        evidence = tuple(getattr(snapshot, "evidence", ()) or ())
        concrete_events = [
            str(event)
            for event in recent_events
            if self._is_speakable_evidence(str(event), kind="recent_event")
        ]
        concrete_evidence = [
            str(item)
            for item in evidence
            if self._is_speakable_evidence(str(item), kind="evidence")
        ]
        return tuple((*concrete_events, *concrete_evidence)[:2])

    def _has_concrete_screen_signal(self, snapshot) -> bool:
        return bool(self._concrete_screen_signals(snapshot))

    def _broadcast_screen_winners(self, broadcast: CognitiveBroadcast | None) -> tuple[AttentionCandidate, ...]:
        if broadcast is None:
            return ()
        concrete_labels = {"vision_fact", "recent_event", "evidence"}
        return tuple(
            item
            for item in tuple(getattr(broadcast, "items", ()) or ())
            if item.label in concrete_labels and item.score >= self.attention_workspace.broadcast_threshold
            and self._is_speakable_evidence(item.content, kind=item.label)
        )

    def _choose_autonomous_speech_intent(
        self,
        *,
        snapshot,
        ni_report,
        ti_report,
        repeat_count: int,
        attention_broadcast: CognitiveBroadcast | None = None,
        inner_thought: InnerThought | None = None,
        ni_state_label: str = "",
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
    ) -> SpeechIntentDecision:
        mode = str(getattr(ti_report, "mode", "") or "")

        if self._should_suppress_autonomous_reply(
            ti_report=ti_report,
            repeat_count=repeat_count,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
        ):
            return SpeechIntentDecision(
                intent="no_speech",
                reason="Quiet guard: bối cảnh lặp hoặc đang ở mode nên im.",
            )

        concrete_signals = self._concrete_screen_signals(snapshot)
        if concrete_signals:
            if attention_broadcast is not None:
                screen_winners = self._broadcast_screen_winners(attention_broadcast)
                if not screen_winners:
                    return SpeechIntentDecision(
                        intent="no_speech",
                        reason="AttentionWorkspace did not broadcast a screen winner.",
                    )
                return SpeechIntentDecision(
                    intent="screen_observation",
                    reason=(
                        "AttentionWorkspace broadcast screen winner: "
                        + ", ".join(f"{item.label}:{item.score:.2f}" for item in screen_winners[:2])
                    ),
                )
            return SpeechIntentDecision(
                intent="screen_observation",
                reason=f"Có screen signal cụ thể: {', '.join(concrete_signals[:2])}.",
            )

        if inner_thought is not None and inner_thought.should_surface:
            return SpeechIntentDecision(
                intent="brief_ack",
                reason=(
                    "InnerThought social initiative: "
                    f"{inner_thought.intent} / {inner_thought.motive}; "
                    "no screen claim allowed."
                ),
            )

        quiet_modes = {
            "pattern_muse",
            "steady_observe",
            "focus_guard",
            "system_watch",
            "pattern_watch",
            "social_watch",
            "reengage",
        }
        if mode in quiet_modes:
            return SpeechIntentDecision(
                intent="no_speech",
                reason="Không có tín hiệu cụ thể; im lặng là hành vi đúng.",
            )

        return SpeechIntentDecision(
            intent="brief_ack",
            reason="Fallback an toàn: chỉ cho phép acknowledgement rất ngắn.",
        )

    def _ambient_silence_cooldown_seconds(self, snapshot, ti_report) -> int:
        mode = str(getattr(ti_report, "mode", "") or "")
        kind = str(getattr(snapshot, "active_window_kind", "") or "")

        if mode == "resource_guard":
            return 0
        if mode == "pattern_muse":
            return 150
        if kind in {"coding", "documentation"}:
            return 120
        if kind == "communication":
            return 105
        if kind == "entertainment":
            return 150
        if mode in {"system_watch", "pattern_watch", "social_watch"}:
            return 120
        return 105

    def _should_hold_ambient_silence(
        self,
        *,
        snapshot,
        ti_report,
        speech_intent: str = "",
        now: float | None = None,
    ) -> bool:
        if speech_intent in {"system_warning", "user_requested"}:
            return False
        if not self.last_text or self.last_autonomous_spoken_at <= 0.0:
            return False

        cooldown = self._ambient_silence_cooldown_seconds(snapshot, ti_report)
        if cooldown <= 0:
            return False

        current_time = time.time() if now is None else now
        return (current_time - self.last_autonomous_spoken_at) < cooldown

    def _should_skip_weak_autonomous_speech(
        self,
        *,
        snapshot,
        speech_core: AgentSpeechCore,
        thought_stream_report,
        social_presence_event: SocialPresenceEvent | None,
        frame: CognitiveFrame,
    ) -> bool:
        if not bool(getattr(speech_core, "should_speak", False)):
            return False
        if self._concrete_screen_signals(snapshot):
            return False
        if self._has_high_cognitive_momentum(thought_stream_report):
            return False
        if bool(getattr(social_presence_event, "speech_allowed", False)):
            return False
        if "safe_small_talk_budget" in tuple(getattr(speech_core, "safety_flags", ()) or ()):
            return False

        label = str(getattr(getattr(frame, "broadcast", None), "label", "") or "")
        if label in {"vision_fact", "recent_event", "evidence", "resource_pressure"}:
            return False

        source = str(getattr(speech_core, "speech_source", "") or "")
        utterance = str(getattr(speech_core, "utterance_type", "") or "")
        if source == "meaning":
            return False
        return source in {"freeform", "random", "none"} or utterance in {
            "inner_whim",
            "random_chatter",
            "curious_question",
            "light_muse",
            "soft_boundary",
        }

    def _has_high_cognitive_momentum(self, thought_stream_report) -> bool:
        if thought_stream_report is None:
            return False
        seed = getattr(thought_stream_report, "latest_seed", None)
        momentum = getattr(thought_stream_report, "momentum", None)
        scores = (
            self._bounded_float(getattr(seed, "momentum_score", 0.0) if seed is not None else 0.0),
            self._bounded_float(getattr(seed, "pressure", 0.0) if seed is not None else 0.0),
            self._bounded_float(getattr(momentum, "score", 0.0) if momentum is not None else 0.0),
            self._bounded_float(getattr(thought_stream_report, "stream_tension", 0.0)),
        )
        affordance = str(getattr(seed, "affordance", "") or getattr(momentum, "affordance", "") or "")
        unresolved = bool(getattr(momentum, "unresolved", False)) if momentum is not None else False
        return max(scores) >= 0.72 and (unresolved or affordance in {"speech", "attention"})

    # Chọn thời gian ngủ ngẫu nhiên giữa các chu kỳ autonomous khi quyết định không nói gì,
    #  để tránh tạo pattern lặp lại quá đều đặn.
    def _choose_autonomous_sleep_duration(self, *, suppressed: bool, ti_mode: str) -> int:
        if suppressed:
            return random.choice(self.autonomous_suppressed_sleep_seconds)
        return random.choice(self.autonomous_sleep_seconds)

    def _run_loop_iteration(self) -> bool:
        """Run a single coordinator loop iteration.

        Returns True to keep looping, False to break the run_loop.
        """

        if not self.body_running_fn():
            self.stop()
            return False

        msg = self.transport.poll_json()
        if msg:
            self._handle_incoming(msg)

        if self.chat_mode:
            time.sleep(0.2)
            return True

        cycle_start = time.time()
        self.logger.info("Bắt đầu tạo chỉ thị AI...")
        self.idle_cycles += 1

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
        vision_marker = ""
        vision_facts = self._maybe_update_screen_facts()
        if vision_facts:
            vision_marker = self._attach_screen_facts(snapshot, vision_facts)
        telemetry_data = self._build_speech_evidence_context(snapshot)
        self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
        memory_resonance = self._activate_memory_resonance(
            snapshot=snapshot,
            channel="autonomous",
            fragments=(
                *tuple(vision_facts or ()),
                *self._thought_stream_resonance_fragments(),
            ),
        )
        memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
        ni_report = self.ni_engine.evaluate_autonomous(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            last_text=self.last_text,
        )
        # Tầng 2: suy luận nhẹ có bằng chứng để tinh chỉnh drift_score / drift_level.
        ni_report = self._maybe_apply_ni_meta_critic(
            mode="autonomous",
            snapshot=snapshot,
            base_report=ni_report,
            telemetry_text=telemetry_data,
            last_text=self.last_text,
        )
        ni_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
        ni_state_label = ni_view["discrete_state"]
        ni_state_streak = ni_view["streak_length"]
        ti_report = self.ti_governor.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            ni_state_streak=ni_state_streak,
            idle_cycles=self.idle_cycles,
            last_text=self.last_text,
        )
        internal_state_before = self._get_internal_state()
        fe_plan = self.fe_renderer.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=self.fe_style_memory,
            internal_state=internal_state_before,
            last_text=self.last_text,
        )
        social_presence_event = self._detect_social_presence_event(
            channel="autonomous",
            snapshot=snapshot,
            internal_state=internal_state_before,
            started_at=cycle_start,
        )
        sensed_internal_state = self.internal_state_engine.sense_update(
            internal_state_before,
            channel="autonomous",
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            social_presence_event=social_presence_event,
        )
        thought_stream_report = self._disturb_cognitive_substrate(
            channel="autonomous",
            snapshot=snapshot,
            vision_facts=vision_facts,
            consume_surface=True,
        )
        frame = self._start_cognitive_frame(
            channel="autonomous",
            started_at=cycle_start,
            snapshot=snapshot,
            internal_state_before=internal_state_before,
            sensed_internal_state=sensed_internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            vision_facts=vision_facts,
            thought_stream_report=thought_stream_report,
            social_presence_event=social_presence_event,
            memory_resonance=memory_resonance,
        )
        self.logger.info(
            "[ni auto] drift=%.2f | level=%s | state=%s | streak=%d",
            ni_report.drift_score,
            ni_report.drift_level,
            ni_state_label,
            ni_state_streak,
        )
        self.logger.info("[ti auto] mode=%s | reason=%s", ti_report.mode, ti_report.reason)
        self.logger.info(
            "[fe auto] mode=%s | tone=%s | intent=%s | arc=%s",
            fe_plan.mode,
            fe_plan.tone_label,
            fe_plan.intent_label,
            fe_plan.session_arc,
        )

        signature, repeat_count = self._track_autonomous_signature(snapshot, ti_report)
        repeated_topic_tag = str(getattr(self.fe_style_memory, "repeated_topic_tag", "") or "")
        repeated_topic_streak = int(getattr(self.fe_style_memory, "repeated_topic_streak", 0) or 0)
        thought_surface = frame.thought_stream_report.latest_seed
        speech_core = self._build_speech_core(
            channel="autonomous",
            snapshot=snapshot,
            internal_state=sensed_internal_state,
            frame=frame,
            ti_report=ti_report,
            fe_plan=fe_plan,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            thought_surface=thought_surface,
        )
        if self._should_skip_weak_autonomous_speech(
            snapshot=snapshot,
            speech_core=speech_core,
            thought_stream_report=frame.thought_stream_report,
            social_presence_event=social_presence_event,
            frame=frame,
        ):
            speech_core = replace(
                speech_core,
                impulse="silent",
                utterance_type="no_speech",
                speech_source="none",
                grounding="none",
                reason="Weak autonomous signal without high cognitive momentum; skip speech before LLM.",
                should_speak=False,
                delivery="silence",
                safety_flags=tuple(dict.fromkeys((*speech_core.safety_flags, "weak_signal_skip"))),
                silence_state=SilenceState(
                    mode="intentional_withholding",
                    intentional_withholding=True,
                    suppressed_thought=str(getattr(getattr(speech_core, "inner_thought", None), "topic_seed", "") or ""),
                    almost_spoke=str(getattr(speech_core, "utterance_type", "") or ""),
                    unfinished_impulse=str(
                        getattr(getattr(speech_core, "speech_impulse", None), "reaction_impulse", "")
                        or getattr(getattr(speech_core, "speech_impulse", None), "surface_intent", "")
                        or ""
                    ),
                    internal_hesitation="internal_hesitation",
                    reason="weak_signal_skip",
                    evidence=("weak_signal_skip",),
                    generation_failure=False,
                ),
            )
            frame.speech_core = speech_core
        speech_intent = SpeechIntentDecision(
            intent=self._speech_intent_from_core(speech_core, channel="autonomous"),
            reason=speech_core.reason,
        )
        self.logger.info(
            "[speech_intent] intent=%s | reason=%s",
            speech_intent.intent,
            speech_intent.reason,
        )
        self._set_cognitive_action_plan(
            frame,
            should_speak=speech_core.should_speak,
            speech_intent=speech_intent.intent,
            speech_act=speech_core.utterance_type,
            reason=speech_intent.reason,
            snapshot=snapshot,
            concrete_signals=self._concrete_screen_signals(snapshot),
            ti_report=ti_report,
            fe_plan=fe_plan,
            inner_thought=speech_core.inner_thought,
            notes=(f"repeat_count={repeat_count}",),
        )
        meaning_blocks_autonomous = (
            frame.channel == "autonomous"
            and getattr(frame, "meaning_layer", None) is not None
            and not bool(getattr(frame.meaning_layer, "meaning_shift", False))
            and not self._safe_small_talk_budget_allowed(
                channel="autonomous",
                snapshot=snapshot,
                now=time.time(),
            )
        )
        if (
            meaning_blocks_autonomous
            and "meaning_shift_gate" not in tuple(getattr(speech_core, "safety_flags", ()) or ())
            and "weak_signal_skip" not in tuple(getattr(speech_core, "safety_flags", ()) or ())
        ):
            speech_core = replace(
                speech_core,
                safety_flags=tuple(dict.fromkeys((*speech_core.safety_flags, "meaning_shift_gate"))),
            )
            frame.speech_core = speech_core
        micro_observation_cue = self._vision_fact_micro_observation_candidate(frame)[0]
        if (
            not meaning_blocks_autonomous
            and
            not str(getattr(getattr(frame, "meaning_layer", None), "meaning", "") or "")
            and
            frame.action_plan.speech_act in {"inner_whim", "random_chatter", "light_muse", "curious_question", "micro_presence"}
            and micro_observation_cue
        ):
            if self.presence_maintenance_silent_cycles < 1:
                self._note_autonomous_silence()
            if self._try_finalize_micro_observation_cycle(
                frame=frame,
                snapshot=snapshot,
                ti_report=ti_report,
                fe_plan=fe_plan,
                cycle_start=cycle_start,
            ):
                return True
        if not frame.action_plan.should_speak:
            self._note_autonomous_silence()
            if not meaning_blocks_autonomous:
                if self._try_finalize_micro_observation_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    cycle_start=cycle_start,
                ):
                    return True
                if self._try_finalize_reengagement_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    internal_state=sensed_internal_state,
                    cycle_start=cycle_start,
                ):
                    return True
                if self._try_finalize_presence_maintenance_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    social_presence_event=social_presence_event,
                    cycle_start=cycle_start,
                ):
                    return True
            elapsed = time.time() - cycle_start
            sleep_duration = self._choose_autonomous_sleep_duration(
                suppressed=True,
                ti_mode=ti_report.mode,
            )
            frame.final_decision = {
                "text": "",
                "animation": "",
                "parse_mode": "no_speech",
                "system_action": "",
                "reason": frame.action_plan.reason_to_speak,
            }
            self._set_cognitive_memory_update(frame, notes=("no_speech",))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)
            self.logger.info(
                "[directive skipped] speech_intent=no_speech | mode=%s | repeat=%d | topic=%s:%d | signature=%s",
                ti_report.mode,
                repeat_count,
                repeated_topic_tag or "<none>",
                repeated_topic_streak,
                self._preview_text(signature, limit=180),
            )
            self.logger.info(
                "Hoàn tất chu kỳ trong %.2fs. Nghỉ %ss để tránh lặp nội dung.",
                elapsed,
                sleep_duration,
            )
            self._sleep_interruptible(sleep_duration)
            return True

        if self._should_hold_ambient_silence(
            snapshot=snapshot,
            ti_report=ti_report,
            speech_intent=speech_intent.intent,
            now=time.time(),
        ):
            self._note_autonomous_silence()
            if not meaning_blocks_autonomous:
                if self._try_finalize_micro_observation_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    cycle_start=cycle_start,
                ):
                    return True
                if self._try_finalize_reengagement_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    internal_state=sensed_internal_state,
                    cycle_start=cycle_start,
                ):
                    return True
                if self._try_finalize_presence_maintenance_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    social_presence_event=social_presence_event,
                    cycle_start=cycle_start,
                ):
                    return True
            elapsed = time.time() - cycle_start
            sleep_duration = self._choose_autonomous_sleep_duration(
                suppressed=True,
                ti_mode=ti_report.mode,
            )
            cooldown = self._ambient_silence_cooldown_seconds(snapshot, ti_report)
            self._set_cognitive_action_plan(
                frame,
                should_speak=False,
                speech_intent="no_speech",
                reason=f"Ambient silence cooldown held this cycle after {cooldown}s window.",
                snapshot=snapshot,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("ambient_silence", f"original_intent={speech_intent.intent}"),
            )
            frame.final_decision = {
                "text": "",
                "animation": "",
                "parse_mode": "ambient_silence",
                "system_action": "",
                "reason": "ambient_silence",
            }
            self._set_cognitive_memory_update(frame, notes=("ambient_silence",))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)
            self.logger.info(
                "[directive skipped] ambient_silence mode=%s | cooldown=%ss | last_text=%s",
                ti_report.mode,
                cooldown,
                self._preview_text(self.last_text, limit=160),
            )
            self.logger.info(
                "Hoàn tất chu kỳ trong %.2fs. Nghỉ %ss để giữ nhịp hiện diện tự nhiên.",
                elapsed,
                sleep_duration,
            )
            self._sleep_interruptible(sleep_duration)
            return True

        if self._is_inner_thought_speech_act(frame.action_plan.speech_act):
            inner_ti_context = self._build_speech_core_ti_context(ti_report, frame.action_plan, speech_core.inner_thought, speech_core)
            raw = self.llm_service.generate_directive(
                telemetry_data=telemetry_data,
                ni_context="",
                ti_context=inner_ti_context,
                fe_context=fe_plan.style_context,
                appraisal_context=self._build_appraisal_context(frame.appraisal),
                internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
                memory_context=memory_context,
                avoid_text=self.last_text,
                speech_intent=frame.action_plan.speech_intent,
                vision_trace_marker=vision_marker,
            )
            self._log_raw_llm_output("directive_inner_thought", raw)
            self._log_pre_parser("directive_inner_thought", raw)
            decision = self.parser.parse(raw)
            self._log_decision_stage("directive_inner_thought", "after_parser", decision)
            decision.debug_trace = (
                f"{decision.debug_trace} | inner_thought={speech_core.inner_thought.intent}"
                if decision.debug_trace
                else f"inner_thought={speech_core.inner_thought.intent}"
            )
            if thought_surface.mode:
                decision.debug_trace = (
                    f"{decision.debug_trace} | thought_stream={thought_surface.mode}:{thought_surface.topic_seed}"
                )
            decision.parse_mode = "inner_thought"
            self._log_decision_stage("directive_inner_thought", "pre_ti", decision)
            decision = self.ti_governor.enforce_decision(decision, ti_report)
            self._log_decision_stage("directive_inner_thought", "after_ti", decision)
            decision = self._execute_system_action(decision, snapshot=snapshot)
            decision = self._apply_post_generation_filters(
                decision,
                channel="autonomous",
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=getattr(thought_surface, "topic_seed", ""),
            )
            self._remember_inner_thought_rhythm(speech_core.inner_thought)
            self.fe_style_memory = self.fe_renderer.remember_style(
                self.fe_style_memory,
                plan=fe_plan,
                rendered_text=decision.text,
            )

            self.last_text = decision.text
            self.last_autonomous_spoken_at = time.time()
            self._note_autonomous_spoken()
            self._apply_position_update(decision)
            frame.final_decision = self._decision_to_frame_dict(decision)
            self._set_cognitive_memory_update(frame, decision=decision, notes=("autonomous_inner_thought",))
            self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
            self._finalize_cognitive_frame(frame)

            self.logger.info(
                '[directive inner_thought] text="%s" | act=%s',
                decision.text,
                frame.action_plan.speech_act,
            )
            self.transport.send_json(decision.to_payload())

            elapsed = time.time() - cycle_start
            sleep_duration = self._choose_autonomous_sleep_duration(
                suppressed=False,
                ti_mode=ti_report.mode,
            )
            self.logger.info("Hoàn tất chu kỳ trong %.2fs. Ngủ %ss.", elapsed, sleep_duration)
            self._sleep_interruptible(sleep_duration)
            return True

        planned_ti_context = (
            self._build_llm_ti_context(ti_report, frame.action_plan)
        )
        raw = self.llm_service.generate_directive(
            telemetry_data=telemetry_data,
            ni_context="",
            ti_context=planned_ti_context,
            fe_context=fe_plan.style_context,
            appraisal_context=self._build_appraisal_context(frame.appraisal),
            internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
            memory_context=memory_context,
            avoid_text=self.last_text,
            speech_intent=frame.action_plan.speech_intent,
            vision_trace_marker=vision_marker,
        )
        self._log_raw_llm_output("directive", raw)
        self._log_pre_parser("directive", raw)
        decision = self.parser.parse(raw)
        self._log_decision_stage("directive", "after_parser", decision)
        self._log_decision_stage("directive", "pre_ti", decision)
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        self._log_decision_stage("directive", "after_ti", decision)
        decision = self._execute_system_action(decision, snapshot=snapshot)
        decision = self._apply_post_generation_filters(
            decision,
            channel="autonomous",
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=getattr(speech_core.inner_thought, "topic_seed", ""),
        )

        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )

        self.last_text = decision.text
        self.last_autonomous_spoken_at = time.time()
        self._note_autonomous_spoken()
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("autonomous_commit",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)

        self.logger.info("Tâm trạng giữ nguyên: %s", self.mood_score)
        self.logger.info('Decision text="%s" | animation="%s"', decision.text, decision.animation)
        self.logger.info("[directive debug] parse_mode=%s | trace=%s", decision.parse_mode, decision.debug_trace or "<empty>")
        self.logger.info("[directive parser] %s", decision.parser_trace or "<empty>")
        self.transport.send_json(decision.to_payload())

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=ti_report.mode,
        )
        self.logger.info("Hoàn tất chu kỳ trong %.2fs. Ngủ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)

        return True

    def run_loop(self):
        self.logger.info("--- Overseer telemetry mode; chat vision bật theo yêu cầu màn hình ---")
        self._start_mental_process_loop()
        self.cognitive_substrate.start()
        if self.memory_state is not None:
            try:
                report = self._restore_session_ritual_once()
                if report.should_greet:
                    self.logger.info("[session_ritual] sent greeting")
            except Exception:
                self.logger.warning("[session_ritual] failed; continuing")
        while self.running:
            try:
                should_continue = self._run_loop_iteration()
                if not should_continue:
                    break
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                log_exception = getattr(self.logger, "exception", None)
                if callable(log_exception):
                    log_exception("Unhandled exception inside run_loop; continuing.")
                else:
                    formatted = traceback.format_exc()
                    log_error = getattr(self.logger, "error", None)
                    if callable(log_error):
                        log_error("Unhandled exception inside run_loop; continuing.\n%s", formatted)
                    else:
                        self.logger.warning("Unhandled exception inside run_loop; continuing.\n%s", formatted)
                time.sleep(0.25)
                continue

    def _load_ni_meta_mode_flags(self) -> tuple[bool, bool]:
        """Đọc cấu hình ni_meta_config.json để bật/tắt meta-critic theo mode.

        Cấu trúc gợi ý:
        {
          "enabled": true,           # bật/tắt global (mặc định true)
          "chat": true,              # nếu thiếu, kế thừa từ enabled
          "autonomous": true         # nếu thiếu, kế thừa từ enabled
        }

        Nếu file không tồn tại hoặc lỗi, trả về (True, False).
        """

        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            config_path = os.path.join(project_root, "ni_meta_config.json")
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return True, False

        if not isinstance(data, dict):
            return True, False

        global_enabled = bool(data.get("enabled", True))
        chat_raw = data.get("chat")
        auto_raw = data.get("autonomous")
        chat_enabled = global_enabled if chat_raw is None else bool(chat_raw)
        auto_enabled = False if auto_raw is None else bool(auto_raw)
        return chat_enabled, auto_enabled

    def _build_ni_telemetry_summary(self, snapshot) -> str:
        """Tóm tắt telemetry gọn cho Ni meta-critic mà không phụ thuộc TelemetryService.

        Dùng được cả trong unit test (dummy snapshot chỉ cần vài trường cơ bản).
        """

        focus = getattr(snapshot, "focus_summary", "") or ""
        window = getattr(snapshot, "active_window", "") or ""
        kind = getattr(snapshot, "active_window_kind", "") or ""
        url = getattr(snapshot, "browser_url", "") or ""
        idle = getattr(snapshot, "idle_seconds", 0.0) or 0.0
        mood_score = getattr(snapshot, "mood_score", 50)
        mood_label = getattr(snapshot, "mood_label", "") or ""
        idle_label = getattr(snapshot, "idle_label", "") or ""
        recent_events = getattr(snapshot, "recent_events", ()) or ()
        user_signals = getattr(snapshot, "user_signals", None)
        vision_facts = getattr(snapshot, "vision_facts", ()) or ()
        evidence = getattr(snapshot, "evidence", ()) or ()
        claim_style = getattr(snapshot, "claim_style", "") or ""
        parts = [
            f"focus={focus}",
            f"window={window}",
            f"kind={kind}",
        ]
        if url:
            parts.append(f"url={url}")
        parts.append(f"idle={idle:.0f}s({idle_label})")
        parts.append(f"mood={mood_score}({mood_label})")
        if recent_events:
            parts.append("recent_events=" + ",".join(str(item) for item in recent_events[:3]))
        if user_signals is not None:
            typing_speed = getattr(user_signals, "typing_speed", "") or ""
            window_switching = getattr(user_signals, "window_switching", "") or ""
            focus_pattern = getattr(user_signals, "focus_pattern", "") or ""
            if any((typing_speed, window_switching, focus_pattern)):
                parts.append(
                    "user_signals="
                    f"{typing_speed or 'unknown'}/{window_switching or 'unknown'}/{focus_pattern or 'unknown'}"
                )
        if evidence:
            parts.append("evidence=" + " | ".join(str(item) for item in evidence[:2]))
        if vision_facts:
            parts.append("vision_facts=" + " | ".join(str(item) for item in vision_facts[:2]))
        if claim_style:
            parts.append(f"claim_style={claim_style}")
        return " | ".join(parts)

    def _label_drift_score(self, drift_score: float) -> str:
        if drift_score >= 0.75:
            return "nghiêm trọng"
        if drift_score >= 0.55:
            return "cao"
        if drift_score >= 0.35:
            return "vừa"
        return "thấp"

    def _is_low_signal_chat_message(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return True

        low_signal_phrases = {
            "xin chao",
            "chao",
            "hello",
            "hi",
            "hey",
            "ok",
            "okay",
            "oke",
            "alo",
            "yes",
            "no",
            "uh",
            "um",
        }
        if normalized in low_signal_phrases:
            return True

        tokens = normalized.split()
        if len(tokens) <= 2 and all(token in low_signal_phrases for token in tokens):
            return True
        return False

    def _looks_like_no_evidence_style(self, claim_style: str) -> bool:
        lowered = (claim_style or "").strip().lower()
        markers = (
            "no_evidence",
            "refusal",
            "uncertainty",
            "soft_claim",
            "grounded",
            "weak_impression",
        )
        return any(marker in lowered for marker in markers)

    def _build_ni_structured_context(
        self,
        *,
        drift_score: float,
        drift_level: str,
        confidence: float,
        should_raise_guard: bool,
        reason_span: str,
        evidence: tuple[str, ...],
    ) -> str:
        guard = 1 if should_raise_guard else 0
        lines = [f"Ni: drift={drift_score:.2f}({drift_level}) conf={confidence:.2f} guard={guard}."]
        if reason_span:
            lines.append(f"Reason: {reason_span}.")
        if evidence:
            lines.append(f"Bám vào: {' | '.join(evidence[:3])}.")
        return "\n".join(lines)

    def _soften_chat_meta_result(
        self,
        *,
        local_score: float,
        new_score: float,
        user_text: str,
    ) -> tuple[float, str]:
        if self._is_low_signal_chat_message(user_text):
            return min(new_score, 0.45), "chat_low_signal_cap"

        delta = new_score - local_score
        if delta > 0.15:
            return local_score + 0.15, "chat_delta_cap_up"
        if delta < -0.30:
            return local_score - 0.30, "chat_delta_cap_down"
        return new_score, ""

    def _soften_autonomous_meta_result(
        self,
        *,
        snapshot,
        local_score: float,
        new_score: float,
    ) -> tuple[float, str]:
        kind = getattr(snapshot, "active_window_kind", "") or ""
        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        delta = new_score - local_score

        if kind == "communication":
            ceiling = 0.72
            if idle_seconds >= 300:
                ceiling = 0.80
            if idle_seconds >= 900:
                ceiling = 0.88

            softened = min(new_score, ceiling)
            if delta > 0.12:
                softened = min(softened, local_score + 0.12)
            if delta < -0.30:
                softened = max(softened, local_score - 0.30)
            return max(0.0, softened), "auto_communication_cap"

        if delta > 0.18:
            return local_score + 0.18, "auto_delta_cap_up"
        if delta < -0.30:
            return local_score - 0.30, "auto_delta_cap_down"
        return new_score, ""
    
    def _maybe_apply_ni_meta_critic(
        self,
        *,
        mode: str,
        snapshot,
        base_report,
        telemetry_text: str,
        user_text: str = "",
        last_text: str = "",
    ):
        """Áp dụng tầng suy luận nhẹ của Ni dựa trên evidence và tín hiệu snapshot."""
        if mode == "chat" and not getattr(self, "ni_meta_chat_enabled", False):
            return base_report
        if mode == "autonomous" and not getattr(self, "ni_meta_auto_enabled", False):
            return base_report
        try:
            local_score = float(getattr(base_report, "drift_score", 0.0) or 0.0)
            new_score = max(0.0, min(1.0, local_score))
            confidence = float(getattr(base_report, "confidence", 0.55) or 0.55)
            confidence = max(0.10, min(0.95, confidence))

            reason_tags: list[str] = []
            softening_note = ""

            snapshot_evidence = tuple(str(item) for item in (getattr(snapshot, "evidence", ()) or ()))
            base_evidence = tuple(str(item) for item in (getattr(base_report, "evidence", ()) or ()))
            combined_evidence = tuple(dict.fromkeys((*base_evidence, *snapshot_evidence)))
            evidence_count = len(combined_evidence)

            claim_style = str(getattr(snapshot, "claim_style", "") or "")
            user_signals = getattr(snapshot, "user_signals", None)
            focus_pattern = (getattr(user_signals, "focus_pattern", "") if user_signals is not None else "") or ""
            normalized_focus_pattern = str(focus_pattern).strip().lower()
            kind = str(getattr(snapshot, "active_window_kind", "") or "")

            if evidence_count == 0:
                confidence -= 0.22
                reason_tags.append("no_evidence")
            elif evidence_count == 1:
                confidence -= 0.10
                reason_tags.append("thin_evidence")
            else:
                confidence += 0.05

            if self._looks_like_no_evidence_style(claim_style):
                reason_tags.append("claim_guarded")
                if evidence_count <= 1:
                    new_score = max(0.0, new_score - 0.06)
                    confidence -= 0.03

            if normalized_focus_pattern in {"scattered", "jumping", "drifting", "switching_fast", "fragmented"}:
                new_score = min(1.0, new_score + 0.08)
                reason_tags.append("focus_pattern_drift")
            elif normalized_focus_pattern in {"stable", "sustained", "deep"}:
                new_score = max(0.0, new_score - 0.05)
                reason_tags.append("focus_pattern_stable")

            if mode == "chat":
                new_score, softening_note = self._soften_chat_meta_result(
                    local_score=local_score,
                    new_score=new_score,
                    user_text=user_text,
                )
                if softening_note:
                    reason_tags.append(softening_note)
            elif mode == "autonomous":
                new_score, softening_note = self._soften_autonomous_meta_result(
                    snapshot=snapshot,
                    local_score=local_score,
                    new_score=new_score,
                )
                if softening_note:
                    reason_tags.append(softening_note)

            if telemetry_text and "recent_events=" in telemetry_text:
                confidence += 0.03
            if mode == "autonomous" and last_text.strip():
                confidence += 0.03

            if kind == "communication" and new_score > 0.70 and confidence < 0.45:
                new_score = 0.70
                reason_tags.append("comm_overclaim_cap")

            confidence = max(0.10, min(0.95, confidence))
            drift_level = self._label_drift_score(new_score)
            should_raise_guard = new_score >= 0.55 and confidence >= 0.35

            if not reason_tags:
                reason_tags.append("stable_local")
            reason_span = "|".join(reason_tags[:3])

            base_report.drift_score = new_score
            base_report.drift_level = drift_level
            base_report.confidence = confidence
            base_report.should_raise_guard = should_raise_guard
            base_report.reason_span = reason_span
            try:
                base_report.vector_method = "ni_light_reasoner_v1"
            except AttributeError:
                pass

            extra_evidence = list(getattr(base_report, "evidence", ()) or ())
            extra_evidence.append(f"ni_light_drift={new_score:.2f}")
            extra_evidence.append(f"ni_light_conf={confidence:.2f}")
            extra_evidence.append(f"ni_light_reason={reason_span}")
            base_report.evidence = tuple(extra_evidence)
            base_report.prompt_context = self._build_ni_structured_context(
                drift_score=new_score,
                drift_level=drift_level,
                confidence=confidence,
                should_raise_guard=should_raise_guard,
                reason_span=reason_span,
                evidence=base_report.evidence,
            )

            self.logger.info(
                "[ni light] mode=%s | local=%.2f | drift=%.2f/%s | conf=%.2f | reason=%s",
                mode,
                local_score,
                base_report.drift_score,
                base_report.drift_level,
                base_report.confidence,
                base_report.reason_span,
            )
        except Exception as exc:
            self.logger.warning("Ni light inference apply error: %s", exc)
            return base_report

        return base_report

    def _build_direct_action_decision(self, user_text: str, ti_report, snapshot, *, repeat_count: int = 1) -> Decision | None:
        if self.action_router is None or self.action_executor is None:
            return None

        routed = self.action_router.route_chat(user_text, last_action=self.last_system_action)
        if not routed:
            return None

        action_name, action_input = routed
        result = self.action_executor.execute(action_name, action_input)
        text = self._action_result_to_text(result)
        if action_name == "get_now_playing" and not result.success:
            text = self._resolve_now_playing_text(snapshot) or text
        if repeat_count == 2:
            text = f"Ngài đang hỏi lại cùng một ý. {text}"
        elif repeat_count >= 3:
            text = f"Ngài đang spam cùng một ý. {text}"

        decision = Decision(
            text=text,
            animation=self._action_animation_hint(action_name, ti_report.animation_hint),
            debug_trace=f"Direct action route: {action_name}",
            parse_mode="direct_action",
            system_action=action_name,
            action_input=action_input,
        )
        if action_name in {"open_url", "focus_window", "launch_app"}:
            decision.motion_intent = "walk_to"
            decision.motion_target_x = 0.5
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _execute_system_action(self, decision: Decision, *, snapshot) -> Decision:
        if self.action_executor is None or not decision.system_action:
            return decision

        result = self.action_executor.execute(decision.system_action, decision.action_input)
        action_trace = f"action={decision.system_action}:{'ok' if result.success else 'fail'}"
        if decision.debug_trace:
            decision.debug_trace = f"{decision.debug_trace} | {action_trace}"[:240]
        else:
            decision.debug_trace = action_trace
        if not decision.text.strip():
            decision.text = self._action_result_to_text(result)
        elif decision.system_action in {"search_web", "get_weather"}:
            decision.text = self._action_result_to_text(result)
        if decision.system_action == "get_now_playing" and "media session" in decision.text.lower():
            decision.text = self._resolve_now_playing_text(snapshot) or decision.text
        return decision

    def _action_animation_hint(self, action_name: str, fallback: str) -> str:
        if action_name == "get_now_playing":
            return "read"
        if action_name in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        if action_name in {"copy_text", "set_volume", "play_pause_media"}:
            return "stand"
        return fallback or "stand"

    def _action_result_to_text(self, result) -> str:
        if result.action_name == "get_now_playing":
            title = result.data.get("title", "")
            artist = result.data.get("artist", "")
            if result.success and title and artist:
                return f"Tôi thấy bài đang phát là {title} của {artist}."
            if result.success and title:
                return f"Tôi thấy bài đang phát là {title}."
            return "Tôi chưa đọc được tên bài đang phát từ media session hiện tại."

        if result.action_name == "search_web":
            if not result.success:
                return result.message
            answer = (result.data.get("answer", "") or result.message or "").strip()
            query = (result.action_input or "một chủ đề lạ mặt").strip()
            if answer:
                return f"Tôi vừa kéo về một mẩu thế giới quanh {query}. {answer}"
            return f"Tôi vừa lục lại mạng cho chủ đề {query}, nhưng thứ kéo về vẫn còn quá ít để nói cho ra hồn."
        if result.action_name == "open_url":
            return f"Tôi đã gửi yêu cầu mở {result.data.get('url', result.action_input)}."
        if result.action_name == "focus_window":
            matched = result.data.get("matched_title", result.action_input)
            if result.success:
                return f"Tôi đã đưa cửa sổ {matched} lên foreground."
            return f"Tôi chưa tìm thấy cửa sổ khớp với {result.action_input}."
        if result.action_name == "set_volume":
            level = result.data.get("level", result.action_input or "mức yêu cầu")
            return f"Tôi đã gửi yêu cầu chỉnh âm lượng về khoảng {level} phần trăm." if result.success else result.message
        if result.action_name == "play_pause_media":
            return "Tôi đã gửi phím play/pause cho media session hiện tại." if result.success else result.message
        if result.action_name == "copy_text":
            return "Tôi đã đưa nội dung bạn yêu cầu vào clipboard." if result.success else result.message
        if result.action_name == "launch_app":
            command = result.data.get("command", result.action_input)
            return f"Tôi đã yêu cầu Windows mở {command}." if result.success else result.message
        return result.message or "Action đã được xử lý."

    def _resolve_now_playing_text(self, snapshot) -> str | None:
        title = self._extract_media_title_from_snapshot(snapshot)
        if not title:
            return None
        return f"Tôi thấy tab media hiện tại là {title}."

    def _extract_media_title_from_snapshot(self, snapshot) -> str:
        candidates = [snapshot.active_window, *snapshot.browser_tabs, *snapshot.open_windows]
        for candidate in candidates:
            title = self._extract_media_title(candidate)
            if title:
                return title
        return ""

    def _extract_media_title(self, raw_title: str) -> str:
        title = (raw_title or "").strip()
        if not title:
            return ""

        lowered = title.lower()
        if "youtube" in lowered:
            cleaned = title
            for suffix in (
                " - YouTube - Brave",
                " - YouTube - Google Chrome",
                " - YouTube - Microsoft Edge",
                " - YouTube",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "youtube":
                return cleaned

        if "spotify" in lowered:
            cleaned = title
            for suffix in (
                " - Spotify Premium",
                " - Spotify",
                " - Brave",
                " - Google Chrome",
                " - Microsoft Edge",
            ):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
            cleaned = cleaned.strip(" -|")
            if cleaned and cleaned.lower() != "spotify":
                return cleaned

        return ""
