from actions.confirmation import public_action_text
from runtime.repair_state import RepairStateController
import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
from types import SimpleNamespace
#json: xử lý dữ liệu JSON.
#os: đọc biến môi trường, config hệ thống.
#random: chọn ngẫu nhiên fallback text, thời gian sleep.
#re: regex để normalize, lọc text.
#threading: chạy loop nền, lock state.
#time: timestamp, cooldown, delay.
#traceback: log lỗi chi tiết.
#unicodedata: chuẩn hóa Unicode, ví dụ tiếng Việt dấu má, thứ mà máy tính ghét bằng một tình yêu thầm kín.
from dataclasses import replace
from collections.abc import Mapping
'''
dataclass: tạo class dữ liệu gọn hơn.
replace: copy dataclass và đổi vài field.
'''
from cortex.background_observer import BackgroundObserver, BackgroundObserverConfig
from cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket
from cortex.endogenous_drive import EndogenousDriveEngine, RollingInternalState
from cortex.epistemic import EpistemicAgentMindProjection, EpistemicKernel, EpistemicKernelConfig, EpistemicStore, archive_v1_cognition, set_default_kernel
from cortex.internal_agenda import InternalAgendaStack
from cortex.observer_contracts import ObserverFrame, SemanticSceneNote, SignalSnapshot, stable_hash
from cortex.appetite_system import AppetiteSystem, build_evidence_buffet
from cortex.connection_drive import ConnectionDrive, ConnectionDriveState
from cortex.contracts import (
    CognitiveDisturbance,
    PerceptEvent,
    SocialPresenceEvent,
    SubconsciousReport,
    ThoughtSurface,
    ThoughtStreamReport,
    TiPolicyReport,
)
from cortex.internal_state import InternalStateEngine, PersistentInternalState
from cortex.micro_policy import MicroLinePolicy, RelationalContext, SemanticRepeatGuard
from cortex.subconscious import build_phase1234567_workers
from cortex.self_observation import SelfObservationEngine
from cortex.self_model import SelfModelEngine
from cortex.thought_stream import ThoughtStream
from cortex.user_context_stream import RollingUserContext, UserContextStream
from cortex.vision_semantic_compressor import (
    RemoteCaptionClient,
    RemoteStructureClient,
    VisionCompressorConfig,
    VisionSemanticCompressor,
)
from domain import Decision
from failure_meta import is_technical_failure_meta
from runtime.public_payload_policy import sanitize_body_payload
from runtime.body_bias import BodyBiasProjector
from runtime.ai_orchestrated.cortex_runtime import CortexAttentionSignal, CortexRuntime
from runtime.thought_model_adapter import RuntimeThoughtModelAdapter
from runtime.model_budget_policy import ModelBudgetPolicy
from runtime.signal_buffer import SignalBuffer, SignalBufferConfig
from runtime.chat_cycle import ChatCycleMixin
from runtime.inner_diary_persistence import InnerDiaryPersister
from runtime.interrupt_ledger import InterruptLedger
from runtime.voice_manager import VoiceManager
from runtime.outcome_observer import OutcomeObserver
from runtime.private_mind_daemon import PrivateMindDaemon
from runtime.private_life_daemon import PrivateLifeDaemon
from runtime.presence_controller import PresenceControllerMixin
from runtime.prompt_context_builder import PromptContextBuilderMixin
from runtime.public_turn_ledger import PublicTurnLedger, infer_public_turn_channel, normalize_public_turn_channel
from runtime.source_grounding import SourceGroundingEngine
from runtime.vision_grounding import VisionGroundingPolicy, VisionGroundingReport
from screen import build_screen_text_runtime
from runtime.stage_contracts import StageFrameBuilder
from runtime.stage_dispatcher import StageDispatcher
from runtime.tts_sync_policy import (
    sync_text_with_tts_enabled,
    tts_event_releases_deferred_text,
)
from runtime.stage_event_bus import StageEventBus
from runtime.stage_output import StageOutputPipeline
from runtime.stage_protocol import is_stage_inbound_type
from runtime.stage_protocol_adapter import playback_event, show_plan_event, stage_segment_event, stage_state_event
from runtime.vtuber_stage_version import VTUBER_STAGE_PHASES, VTUBER_STAGE_STATUS, VTUBER_STAGE_VERSION
from runtime.state_commit_service import StateCommitServiceMixin
from runtime.subconscious_loop import SubconsciousLoop as RuntimeSubconsciousLoop
from memory.memory_kernel import MemoryKernel
from eris_secrets import get_config

'''coordinator.py là “bộ điều phối runtime” (orchestrator) cho ERIS: nó đứng giữa telemetry 
(màn hình/hành vi), các tầng đánh giá (Ni/Ti/FE), LLM + parser, action system và kênh transport để quyết định
 “lúc nào nói/câm”, “nói gì”, “có thực thi action không”, rồi gửi Decision ra “body” (Godot) qua UDP.
'''


VISION_TRACE_MARKER = "vision_facts_attached"

FALLBACK_BY_INTENT: dict[str, tuple[str, ...]] = {
    "random_chatter": (
        "bạn gọi tôi ra chỉ để nghe tôi nói linh tinh à.",
        "Tín hiệu mờ quá. Tôi lùi lại một nhịp.",
    ),
    "inner_whim": (
        "Mạch này vẫn hơi nghẽn lại.",
        "Nhịp này cứ để nhỏ thôi.",
    ),
    "micro_presence": (
        "Mạch này vẫn hơi nghẽn.",
        "Nhịp này vẫn còn ở đây.",
    ),
    "curious_question": (
        "Có chỗ nào đang vướng nhẹ không?",
        "Đoạn này còn mắc ở đâu à?",
    ),
    "screen_observation": (
        "Tôi chỉ dám bám vào chỗ này: file_saved.",
        "Tôi giữ câu này sát phần đang hiện ra thôi.",
    ),
}

SUBCONSCIOUS_LANE2_WORKERS: tuple[str, ...] = (
    "user_modeler",
    "memory_resonator",
    "goal_simulator",
    "self_regulator",
    "curiosity_gap_agent",
    "subjective_time_agent",
    "spatial_mind_agent",
)

SUBCONSCIOUS_LANE3_POST_WORKERS: tuple[str, ...] = ("rehearsal_agent",)
SUBCONSCIOUS_LANE5_PRE_WORKERS: tuple[str, ...] = ("daydream_injector", "independent_agenda_agent")
SUBCONSCIOUS_LANE5_POST_WORKERS: tuple[str, ...] = ("belief_mutation_engine", "shadow_accumulator")
SUBCONSCIOUS_AUDIT_WORKERS: tuple[str, ...] = ("meta_cognitive_audit",)





_GENERIC_TELEMETRY_PREFIXES = (
    "active window is ",
    "focus kind is ",
    "there has been no input for ",
    "browser target is visible:",
    "context classification:",
)


def _is_generic_telemetry_line(text: str) -> bool:
    """True nếu một dòng chỉ là telemetry chung chung, KHÔNG phải nội dung màn hình thật.

    Dùng để chặn việc nhồi telemetry (active window is.../focus kind is.../no input...)
    vào ocr_text rồi gửi cho Gemini như thể đó là chữ trên màn hình.
    """

    lowered = str(text or "").strip().lower()
    if not lowered:
        return True
    if lowered.startswith(_GENERIC_TELEMETRY_PREFIXES):
        return True
    if re.fullmatch(r"\d+ browser tabs are visible", lowered):
        return True
    if re.fullmatch(r"\d+ windows are open", lowered):
        return True
    return False


def _is_nonsemantic_fallback_decision(decision: Decision) -> bool:
    """True nếu decision chỉ là fallback kỹ thuật, không phải answer nội dung.

    Chú thích kiến trúc: public_turn có thể ghi để user thấy, nhưng semantic
    history/TurnGraph không được coi các câu này là bằng chứng hội thoại.
    """

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
    ChatCycleMixin,
    StateCommitServiceMixin,
    PromptContextBuilderMixin,
    PresenceControllerMixin,
):
    #Đây là trung tâm điều phối.
    # Giãn cách tối thiểu giữa 2 lần chụp màn hình cho chat. Trong khoảng này, chat
    # tái dùng vision_facts gần nhất thay vì chụp + nén lại (xem _capture_screen_frame_for_chat).
    _CHAT_VISION_THROTTLE_SEC = 6.0
    # Backward-compatible aliases for older regression tests. Real policy lives in
    # runtime.tutor_research_policy; giữ mấy tên này để test cũ không chết vì
    # chúng ta dọn nhà hơi quá tay.
    _LIGHT_TUTOR_RESEARCH_CUES = (
        "nghiên cứu", "nghien cuu", "đào sâu", "dao sau", "kiểm chứng", "kiem chung",
        "hỏi gemini", "hoi gemini", "hỏi sư phụ", "hoi su phu", "fix elegant", "deep research",
    )
    _LIGHT_TUTOR_COMMAND_WORDS = ("hỏi", "hoi", "nhờ", "nho", "kêu", "keu", "gemini", "tutor", "sư phụ", "su phu")
    _LIGHT_TUTOR_REFERENT_ONLY = ("cái này", "cai nay", "cái đó", "cai do", "phần này", "phan nay", "phần đó", "phan do", "ý này", "y nay")





    def _background_memory_digest_idle_probe(self, *, quiet_for: float = 0.0, now: float | None = None) -> bool:
        """Chỉ cho semantic digest chạy khi runtime thật sự rảnh."""

        del now
        if getattr(self, "_chat_processing", False):
            return False
        lock = getattr(self, "_chat_burst_lock", None)
        queue_items = []
        if lock is not None:
            try:
                with lock:
                    queue_items = list(getattr(self, "_chat_burst_queue", []) or [])
            except Exception:
                return False
        else:
            queue_items = list(getattr(self, "_chat_burst_queue", []) or [])
        if queue_items:
            return False
        if getattr(self, "chat_mode", False) and float(quiet_for or 0.0) < float(os.getenv("ERIS_MEMORY_DIGEST_CHAT_IDLE_SEC", "2.0")):
            return False
        return True

    def __init__(
        self,
        *,
        logger, #ghi log
        transport, #gửi dữ liệu ra body/Godot
        llm_service, #gọi LLM
        parser, #parse output LLM
        telemetry_service, #đọc màn hình/hành vi
        memory_core,# bộ nhớ
        body_running_fn,#kiểm tra body/Godot còn chạy không
        action_executor=None, #thực thi
        action_router=None,#định tuyến action
        memory_semantic_parser=None,
    ):
        self.logger = logger
        self.transport = transport
        # Nạp nguồn settings duy nhất trước khi dựng subsystem. Từ bản này
        # runtime_settings.json là authority thật; env không còn được materialize
        # ngược trên hot path. Các module policy đọc store trực tiếp.
        try:
            from runtime.runtime_settings_store import get_runtime_settings_store
            self.runtime_settings_store = get_runtime_settings_store(logger=self.logger)
            self.runtime_settings = self.runtime_settings_store.load(materialize_env=False)
            self.logger.info(
                "[runtime-settings] loaded path=%s version=%s",
                self.runtime_settings_store.path,
                self.runtime_settings.get("version", 0),
            )
        except Exception as exc:
            self.runtime_settings_store = None
            self.runtime_settings = {}
            self.logger.warning("Không khởi tạo được RuntimeSettingsStore: %s", exc)
        # Cờ chiều-sâu (N1–N3) tự BẬT lúc khởi động — không bắt người dùng gạt tay.
        # Live qua control-file; lựa chọn tắt/bật về sau của người dùng vẫn thắng.
        try:
            from cortex.depth_flags import bootstrap_defaults

            states = bootstrap_defaults()
            self.logger.info("[depth] auto-enable cờ chiều-sâu: %s", states)
        except Exception as exc:  # pragma: no cover - defensive
            try:
                self.logger.warning("[depth] bootstrap_defaults lỗi: %s", exc)
            except Exception:
                pass
        self.llm_service = llm_service
        self.parser = parser
        self.telemetry_service = telemetry_service
        self.public_turn_ledger = PublicTurnLedger()
        self.interrupt_ledger = InterruptLedger()
        self.voice_manager = VoiceManager(ledger=self.interrupt_ledger)
        self.pending_speech_interrupt_event = None
        self.reply_context = SimpleNamespace(previous_public_turn=None)
        # Protocol sân khấu mới: gửi event typed ra frontend, nhưng không thay
        # payload legacy. Nếu client cũ không thích message lạ, tắt bằng
        # ERIS_STAGE_PROTOCOL=0.
        self.stage_event_bus = StageEventBus(transport=transport, logger=logger)
        try:
            self.logger.info(
                "[vtuber-stage] loaded version=%s phases=%s status=%s session=%s",
                VTUBER_STAGE_VERSION, ",".join(str(x) for x in VTUBER_STAGE_PHASES),
                VTUBER_STAGE_STATUS, self.stage_event_bus.session_snapshot().get("session_id", ""),
            )
        except Exception:
            pass
        self.avatar_ready = False
        self.last_stage_inbound_event = None
        self.memory_core = memory_core
        if memory_semantic_parser is None:
            try:
                from runtime.runtime_settings_store import runtime_bool
                semantic_parser_enabled = runtime_bool("memory", "semantic_parser", default=False)
            except Exception:
                semantic_parser_enabled = False
        else:
            semantic_parser_enabled = False
        if memory_semantic_parser is None and semantic_parser_enabled:
            try:
                from runtime.memory_semantic_parser_adapter import build_runtime_memory_semantic_parser
            except Exception:
                try:
                    from .memory_semantic_parser_adapter import build_runtime_memory_semantic_parser
                except Exception as exc:
                    self.logger.warning("Không import được memory semantic parser adapter: %s", exc)
                    build_runtime_memory_semantic_parser = None
            if build_runtime_memory_semantic_parser is not None:
                try:
                    memory_semantic_parser = build_runtime_memory_semantic_parser(
                        llm_service=llm_service,
                        logger=self.logger,
                    )
                    if memory_semantic_parser is not None:
                        self.logger.info("Memory semantic parser đã bật cho background digest.")
                except Exception as exc:
                    self.logger.warning("Không khởi tạo được memory semantic parser: %s", exc)
                    memory_semantic_parser = None
        self.memory_kernel = memory_core if isinstance(memory_core, MemoryKernel) else None
        if self.memory_kernel is None and memory_core is not None:
            try:
                self.memory_kernel = MemoryKernel.from_existing_core(
                    memory_core,
                    semantic_parser=memory_semantic_parser,
                )
            except Exception as exc:
                self.logger.warning("Không bọc được memory kernel từ memory core hiện có: %s", exc)
                self.memory_kernel = None
        # Inject llm_service để maintenance runner có thể gọi AI curator
        if self.memory_kernel is not None:
            self.memory_kernel._llm_service = llm_service
        self.body_running_fn = body_running_fn
        self.action_executor = action_executor
        self.action_router = action_router
        self.memory_semantic_parser = memory_semantic_parser
        # Phase 12-15: runtime nhận thức nội bộ read-only. Executor được tạo
        # trước Coordinator nên bind muộn tại đây, sau khi memory/public ledger
        # đã tồn tại. Social engine được đọc qua owner động khi handler chạy.
        self.internal_cognitive_capabilities = None
        try:
            from runtime.internal_cognitive_capabilities import (
                INTERNAL_COGNITIVE_VERSION, InternalCognitiveCapabilityRuntime,
            )
            self.internal_cognitive_capabilities = InternalCognitiveCapabilityRuntime(self, logger=self.logger)
            binder = getattr(self.action_executor, "bind_cognitive_runtime", None)
            if callable(binder):
                binder(self.internal_cognitive_capabilities)
            self.logger.info(
                "[internal-cognitive] loaded version=%s capabilities=%s status=read_only_verified",
                INTERNAL_COGNITIVE_VERSION,
                len(self.internal_cognitive_capabilities.contracts()),
            )
        except Exception as exc:
            self.logger.warning("Không khởi tạo được internal cognitive capabilities: %s", exc)
        self.workspace_manager = None
        self.project_operations = None
        try:
            from runtime.workspace_manager import WorkspaceManager
            self.workspace_manager = WorkspaceManager(self, logger=self.logger)
            from runtime.project_operations import PROJECT_OPERATIONS_VERSION, ProjectOperationsRuntime
            self.project_operations = ProjectOperationsRuntime(self, logger=self.logger)
            binder = getattr(self.action_executor, "bind_project_runtime", None)
            if callable(binder):
                binder(self.project_operations)
            self.logger.info(
                "[project-ops] loaded version=%s capabilities=%s mode=autonomous_project_scope",
                PROJECT_OPERATIONS_VERSION,
                len(self.project_operations.contracts()),
            )
            self.logger.info(
                "[workspace] eris_home=%s active=%s implicit_source_repo=false",
                self.workspace_manager.home.root,
                self.workspace_manager.active_workspace_id or "none",
            )
        except Exception as exc:
            self.logger.warning("Không khởi tạo được project operations runtime: %s", exc)

        try:
            from actions.capability_runtime import bind_runtime_owner

            bind_runtime_owner(self)
        except Exception as exc:
            self.logger.debug("[capability] runtime bind failed: %s", exc)
        self.background_memory_digest = None
        if memory_semantic_parser is not None:
            try:
                from runtime.background_memory_digest import build_background_memory_digest_service
            except Exception:
                try:
                    from .background_memory_digest import build_background_memory_digest_service
                except Exception as exc:
                    self.logger.warning("Không import được background memory digest service: %s", exc)
                    build_background_memory_digest_service = None
            if build_background_memory_digest_service is not None:
                try:
                    self.background_memory_digest = build_background_memory_digest_service(
                        memory_kernel=self.memory_kernel,
                        semantic_parser=memory_semantic_parser,
                        memory_core=memory_core,
                        logger=self.logger,
                        idle_probe=self._background_memory_digest_idle_probe,
                    )
                except Exception as exc:
                    self.logger.warning("Không khởi tạo được background memory digest service: %s", exc)
                    self.background_memory_digest = None
        # State nội bộ còn hoạt động độc lập với public cognition. Cortex V2 không
        # khởi tạo các engine Ni/Ti/Fe/appraisal/attention legacy tại boot.
        self.internal_state_engine = InternalStateEngine()
        self.outcome_observer = OutcomeObserver()
        # Observability + rollout được khởi tạo sớm để cả autonomous/vision trước
        # lượt chat đầu tiên cũng có metric và kill-switch. Hai subsystem này
        # best-effort, không được phép biến boot thành nghi lễ hiến tế.
        try:
            from runtime.observability import ErisObservability
            from runtime.rollout_control import RolloutController

            self.observability = ErisObservability()
            self.runtime_session_id = str(
                getattr(self, "runtime_session_id", "")
                or f"runtime-{os.getpid()}-{id(self)}"
            )
            os.environ.setdefault("ERIS_RUNTIME_SESSION_ID", self.runtime_session_id)
            self.rollout_controller = RolloutController(observability=self.observability)
            from runtime.hardening_rollout import HardeningHealthGate
            self.hardening_health_gate = HardeningHealthGate(self.rollout_controller)
            self._hardening_health_eval_counter = 0
        except Exception as exc:
            self.observability = None
            self.rollout_controller = None
            self.hardening_health_gate = None
            self._hardening_health_eval_counter = 0
            self.logger.warning("Observability/rollout init skipped: %s", exc)
        # Authority config Phase 7/8 được đọc một lần ở boot. Các module vẫn có
        # thể load độc lập cho tooling, nhưng coordinator không đổi policy giữa
        # hai nhịp chỉ vì env bị sửa giữa chừng.
        try:
            from runtime.hardening_config import HardeningConfig

            self.hardening_config = HardeningConfig.load()
        except Exception:
            self.hardening_config = None

        # Provider registry là authority cho bốn implementation rời nhau.
        # Phase 4 mới có Protocol; từ Phase 5 coordinator thật sự đăng ký và gọi
        # action qua registry, còn speech/memory/budget có binding dùng chung.
        self.provider_registry = None
        try:
            self._initialize_provider_registry()
        except Exception as exc:
            self.logger.warning("Provider registry init skipped: %s", exc)

        # Phase 8 release guard: ở profile stable, source/config phải khớp
        # manifest đã được đóng từ báo cáo Phase 7. Development chỉ cảnh báo để
        # người sửa code không bị khóa ngoài chính repo của mình.
        self.hardening_release_status = {}
        try:
            from runtime.hardening_release import HardeningReleaseGuard, runtime_source_root

            guard_result = HardeningReleaseGuard(source_root=runtime_source_root()).verify()
            self.hardening_release_status = guard_result.to_dict()
            if self.observability is not None:
                self.observability.log(
                    "hardening_release_guard",
                    tags={"status": guard_result.status, "release": guard_result.release_id or "unversioned"},
                    fields=self.hardening_release_status,
                    status="error" if not guard_result.ready else "ok",
                )
            if not guard_result.ready:
                cfg = self.hardening_config
                message = f"Hardening release guard chưa đạt: {guard_result.status}"
                if bool(getattr(cfg, "release_guard_fail_closed", False)):
                    raise RuntimeError(message)
                self.logger.warning(message)
        except Exception as exc:
            if bool(getattr(getattr(self, "hardening_config", None), "release_guard_fail_closed", False)):
                raise
            self.logger.warning("Hardening release guard init skipped: %s", exc)

        # Phase 7 production validation. Khác canary Phase 6, manager này chấm
        # thêm delivery ACK của panel, greeting misfire và scenario coverage.
        self.phase7_validation = None
        try:
            if self.observability is not None:
                from runtime.phase7_validation import Phase7ValidationManager

                phase7_config = self.hardening_config
                if phase7_config is None:
                    from runtime.hardening_config import HardeningConfig
                    phase7_config = HardeningConfig.load()
                self.phase7_validation = Phase7ValidationManager(
                    observability=self.observability,
                    provider_health_fn=self.provider_health_snapshot,
                    rollout_status_fn=(
                        self.rollout_controller.status
                        if self.rollout_controller is not None and callable(getattr(self.rollout_controller, "status", None))
                        else (lambda: {})
                    ),
                    config=phase7_config,
                    release_id=str(os.getenv("ERIS_RELEASE_ID", "") or ""),
                    environment_fn=self._phase7_environment_snapshot,
                )
                self.phase7_validation.start(validation_id=f"{self.runtime_session_id}-phase7")
        except Exception as exc:
            self.logger.warning("Phase 7 validation init skipped: %s", exc)

        # Canary window chạy đúng 20–30 public turn và chỉ chấm metric phát sinh
        # sau thời điểm bắt đầu. Mặc định tắt; bật bằng ERIS_HARDENING_CANARY_ENABLED.
        self.hardening_canary = None
        try:
            if self.observability is not None and self.rollout_controller is not None:
                from runtime.hardening_canary import HardeningCanaryManager
                self.hardening_canary = HardeningCanaryManager(
                    observability=self.observability,
                    rollout_controller=self.rollout_controller,
                    provider_health_fn=self.provider_health_snapshot,
                )
                self.hardening_canary.start(session_id=f"{self.runtime_session_id}-canary")
        except Exception as exc:
            self.logger.warning("Hardening canary init skipped: %s", exc)

        epistemic_enabled = str(os.getenv("ERIS_EPISTEMIC_V2_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
        if epistemic_enabled:
            epistemic_mode = str(os.getenv("ERIS_EPISTEMIC_V2_MODE", "authoritative") or "authoritative").strip().lower()
            shadow_mode = epistemic_mode == "shadow"
            if not os.getenv("PYTEST_CURRENT_TEST"):
                try:
                    archive_v1_cognition("memory_core")
                except Exception as exc:
                    self.logger.warning("Could not archive V1 cognition state: %s", exc)
            epistemic_path = ":memory:" if os.getenv("PYTEST_CURRENT_TEST") else None
            self.epistemic_kernel = EpistemicKernel(
                EpistemicStore(path=epistemic_path, mode=epistemic_mode),
                config=EpistemicKernelConfig(shadow_mode=shadow_mode),
                logger=self.logger,
            )
            set_default_kernel(self.epistemic_kernel)
            self.epistemic_agent_mind = EpistemicAgentMindProjection(self.epistemic_kernel)
            self.logger.info("Epistemic V2 ready in %s mode; cognitive state writes use V2.", self.epistemic_kernel.store.mode)
        else:
            self.epistemic_kernel = None
            self.epistemic_agent_mind = None
            set_default_kernel(None)

        # StateCommitter là cổng ghi memory duy nhất ngoài Architecture C reducer.
        # Khởi tạo thẳng tại owner thay vì mượn helper từ frame recorder đã bị loại.
        self.state_committer = None
        if memory_core is not None:
            try:
                from runtime.state_committer import StateCommitter
                self.state_committer = StateCommitter(
                    memory_core,
                    logger=self.logger,
                    epistemic_kernel=self.epistemic_kernel,
                )
            except Exception as exc:
                self.logger.warning("Không khởi tạo được StateCommitter: %s", exc)

        self.self_observer = SelfObservationEngine()
        self.self_model_engine = SelfModelEngine()
        self.source_grounding_engine = SourceGroundingEngine()
        # Vision không còn được phép nhảy thẳng từ caption sang câu nói. Policy này
        # tách note thành claim, kiểm provenance/confidence rồi mới cho downstream
        # dùng như screen fact.
        self.vision_grounding_policy = VisionGroundingPolicy()
        self.last_vision_grounding_report: VisionGroundingReport | None = None
        self.semantic_repeat_guard = SemanticRepeatGuard()
        self.micro_line_policy = MicroLinePolicy(repeat_guard=self.semantic_repeat_guard)
        self.body_bias_projector = BodyBiasProjector(self._get_internal_state)
        self._debug_overrides: dict[str, tuple[float, float]] = {}
        self.signal_buffer = SignalBuffer(SignalBufferConfig())
        self.sensory_model_adapter = None
        self.background_observer = BackgroundObserver(
            BackgroundObserverConfig(),
            sensory_adapter=self.sensory_model_adapter,
        )
        self.vision_semantic_compressor = VisionSemanticCompressor(
            VisionCompressorConfig(),
            structure_client=self._build_vision_structure_client(llm_service),
            caption_client=self._build_vision_caption_client(llm_service),
            logger=self.logger,
        )
        self.internal_agenda = InternalAgendaStack(
            backing_path=self._resolve_internal_agenda_path(),
        )
        self.user_context_stream = UserContextStream()
        self.endogenous_drive_engine = EndogenousDriveEngine()
        self.rolling_user_context = RollingUserContext()
        self.rolling_internal_state = RollingInternalState()
        self.model_budget_policy = ModelBudgetPolicy(logger=self.logger)
        self._install_model_inference_queue()
        self.last_cortex_attention: CortexAttentionSignal | None = None
        self.last_daydream_result = None
        self.daydream_model_adapter = None
        self.daydream_consolidator = DaydreamConsolidator(
            llm_client=getattr(llm_service, "style_client", None),
            logger=self.logger,
        )
        # CortexRuntime chỉ duy trì context/drive/consolidation. Nó không có
        # SpeakGate hay quyền semantic; main planner Architecture C là authority.
        self.cortex_runtime = CortexRuntime(
            user_context_stream=self.user_context_stream,
            endogenous_drive=self.endogenous_drive_engine,
            agenda_stack=self.internal_agenda,
            daydream=self.daydream_consolidator,
            budget_policy=self.model_budget_policy,
            agent_mind=self.epistemic_agent_mind,
            logger=self.logger,
        )
        self.last_ai_intention_plan = None
        self.last_signal_snapshot: SignalSnapshot | None = None
        self.last_signal_diff = None
        self.last_observer_frame: ObserverFrame | None = None
        # PrivateMindDaemon: owner vòng đời private cognition. Loop chỉ xử lý một tick;
        # daemon giữ queue/outcome/digest để concern thật sự có đời sống qua thời gian.
        self.private_mind_daemon = PrivateMindDaemon.from_runtime(
            runtime_owner=self,
            llm_service=llm_service,
            logger=self.logger,
        )
        self.private_mind_loop = getattr(self.private_mind_daemon, "loop", None)
        self.private_mind_surface_queue: list[object] = getattr(self.private_mind_daemon, "surface_queue", []) if self.private_mind_daemon is not None else []
        self.private_mind_speech_bias: dict[str, object] = {}
        self.private_mind_inquiry_plan: list[dict[str, object]] = []
        self.private_mind_active_state: dict[str, object] = {}
        self.private_mind_thought_pressure = 0.0
        self.private_mind_digest: dict[str, object] = {}
        self.private_mind_daemon_digest: dict[str, object] = {}
        # Ghi inner_diary ra đĩa (có throttle) để trạng thái nội tâm không bốc hơi khi tắt app.
        self.inner_diary_persister = InnerDiaryPersister(logger=self.logger)
        # PrivateLifeDaemon: đời sống riêng không xoay quanh user. Nó theo dõi habitat,
        # object attachments, project riêng, nhịp ngày, solitude và việc vặt nội bộ.
        self.private_life_daemon = PrivateLifeDaemon.from_runtime(
            runtime_owner=self,
            logger=self.logger,
        )
        self.private_life_core = getattr(self.private_life_daemon, "core", None)
        self.private_life_surface_queue: list[object] = getattr(self.private_life_daemon, "surface_queue", []) if self.private_life_daemon is not None else []
        self.private_life_digest: dict[str, object] = {}
        self.last_semantic_scene_note: SemanticSceneNote | None = None
        # Curiosity Tutor: daemon tò mò chạy ngoài hot path. Mặc định None (Master_Switch
        # tắt) ⇒ không tác động gì. Lỗi build không bao giờ giết runtime.
        self.tutor_daemon = None
        try:
            from runtime.tutor_wiring import build_tutor_daemon_from_runtime
            self.tutor_daemon = build_tutor_daemon_from_runtime(self)
        except Exception as exc:
            self.logger.warning("Không dựng được Curiosity Tutor daemon: %s", exc)
            self.tutor_daemon = None
        self._state_lock = threading.RLock()
        # Danger Zone dùng service riêng để reset đúng cả RAM lẫn store trên đĩa.
        # Không cho Body tự File.Delete() vì daemon đang sống có thể ghi state cũ trở lại.
        try:
            from runtime.maintenance_service import MaintenanceService
            self.maintenance_service = MaintenanceService(self, logger=self.logger)
        except Exception as exc:
            self.maintenance_service = None
            self.logger.warning("Không khởi tạo được MaintenanceService: %s", exc)

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
        # Đồng hồ cognition chuẩn. Ba mốc này tách khỏi cooldown kỹ thuật để
        # Qwen biết phiên đã chạy bao lâu và khoảng cách giữa các lượt nói.
        # Không dùng _chat_last_activity_at làm nguồn duy nhất vì field đó bị
        # cập nhật ngay đầu lượt, khiến "lượt user trước" biến mất khỏi lịch sử.
        self._temporal_session_started_at = time.time()
        self._temporal_last_user_turn_at = 0.0
        self._temporal_last_assistant_turn_at = 0.0
        self._temporal_context_builder = None
        # Mốc thời gian lượt user gần nhất. chat_mode là trạng thái "đang trò
        # chuyện" suy ra từ độ tươi này: còn tươi thì ERIS nhường lời cho bạn;
        # quá ngưỡng thì autonomous tự quay lại nhịp ambient (kể cả khi panel
        # vẫn mở). Đây thay cho công tắc cứng + idle-timeout cũ.
        self._chat_last_activity_at = 0.0
        # Đồng hồ public thật: user turn, generation, text commit và audio.
        # Không còn lấy riêng timestamp user rồi kết luận hội thoại đã chết ngay
        # sau 20 giây model đang suy nghĩ.
        try:
            from runtime.interaction_clock import InteractionClock
            self.interaction_clock = InteractionClock()
        except Exception:
            self.interaction_clock = None
        self._chat_fresh_seconds = max(
            0.0, float(os.getenv("ERIS_CHAT_FRESH_SEC", "20") or 0.0)
        )
        # Bộ đệm hội thoại hợp nhất: cả lời bạn, lời chat của ERIS, lẫn lời
        # autonomous đều ghi vào đây. Không xoá khi rời chat; tự phai theo TTL.
        self.chat_history = []
        self.last_chat_answer = ""
        self.repair_state_controller = RepairStateController()
        # Architecture C có đúng một observer hậu kỳ: PostTurnObserver được
        # bootstrap sau khi coordinator hoàn tất. Không khởi tạo social runtime
        # song song rồi tắt lại, vừa tốn model client vừa tạo hai nguồn state.

        try:
            from actions.capability_runtime import refresh_runtime_capabilities
            refresh_runtime_capabilities(owner=self)
        except Exception:
            pass
        self.current_social_contract = None
        self.current_social_observation = None
        self.latest_social_observation = None
        self.pending_social_repair = False
        self.current_conversation_lane = None
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
        self.last_autonomous_spoken_at = 0.0
        self.autonomous_presence_blocked_until = 0.0
        self.presence_maintenance_silent_cycles = 0
        self.last_presence_maintenance_at = 0.0
        self.last_ambient_body_only_at = 0.0
        #Các hàm _load... đọc config/env.
        '''
        khi nào ERIS được tự nói để duy trì hiện diện,
        im bao lâu thì re-engage,
        cooldown bao nhiêu giây,
        có dùng LLM cho micro presence không.
        '''
        self.reengagement_quiet_cycles = 0
        self.last_reengagement_at = 0.0
        self.autonomous_sleep_seconds = self._load_autonomous_sleep_seconds(
            "ERIS_AUTONOMOUS_SLEEP_SEC",
            default=(30, 45, 60, 90),
        )
        self.autonomous_suppressed_sleep_seconds = self._load_autonomous_sleep_seconds(
            "ERIS_AUTONOMOUS_SUPPRESSED_SLEEP_SEC",
            # No-speech không phải output đã lặp. Giữ vòng suppressed ngắn hơn
            # để silence_debt/vital pressure có cơ hội tích và surface.
            default=(12, 18, 25, 35),
        )
        self.force_speak_repeat_guard_count = 0
        self.force_speak_intent_guard_count = 0
        self.rapid_burst_window = self._load_rapid_burst_window()
        self._chat_processing = False
        self._chat_burst_queue: list[tuple[float, str]] = []
        self._chat_burst_lock = threading.RLock()
        self.recent_inner_thought_intents: tuple[str, ...] = ()
        self.recent_inner_thought_seeds: tuple[str, ...] = ()
        self.recent_meaning_families: tuple[str, ...] = ()
        # Cortex V2 chỉ giữ brief canonical gần nhất cho debug/panel. Không lưu
        # một danh sách frame legacy có quyền ghi state song song với reducer.
        self.last_cognitive_brief = None
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
        self.session_turn_ledger = self._ensure_session_turn_ledger()
        self.memory_commit_policy = self._ensure_memory_commit_policy()
        self.memory_recall_adapter = self._ensure_memory_recall_adapter()
        self.vision_facts_enabled, self.vision_interval_sec, self.vision_fact_max_items, self.vision_fact_max_len = (
            self._load_vision_fact_settings()
        )
        self.vision_facts: tuple[str, ...] = ()
        # Cache cũ chỉ để audit/debug. Khi frame mới không tạo được claim grounded,
        # runtime không được lén dùng cache này như thể nó vẫn là màn hình hiện tại.
        self.vision_stale_facts: tuple[str, ...] = ()
        self.vision_facts_are_stale = False
        self.vision_last_capture_at = 0.0
        self.vision_disabled_until = 0.0
        self.vision_failure_count = 0
        self.vision_last_trace = ""
        self.vision_facts_signature = ""
        self.vision_facts_novelty_hint = "none"
        # Screen Text Index chạy nền: UI Automation trước, OCR vùng thay đổi sau.
        # Chat chỉ đọc snapshot đã có; tuyệt đối không chờ OCR/VLM trên critical path.
        try:
            (
                self.screen_evidence_store,
                self.screen_text_worker,
                self.screen_relevance_router,
            ) = build_screen_text_runtime(logger=self.logger)
        except Exception as exc:
            self.screen_evidence_store = None
            self.screen_text_worker = None
            self.screen_relevance_router = None
            self.logger.warning("[screen text] không khởi tạo được index: %s", exc)
        self._chat_screen_route_decision = None
        self._chat_screen_text_evidence = ()

        # Phase 16: năng lực đọc môi trường read-only. Khởi tạo sau Screen Text
        # Index để availability phản ánh store/worker thật, không chỉ vì class tồn tại.
        self.environment_capabilities = None
        try:
            from runtime.environment_capabilities import (
                ENVIRONMENT_CAPABILITY_VERSION, EnvironmentCapabilityRuntime,
            )
            self.environment_capabilities = EnvironmentCapabilityRuntime(self, logger=self.logger)
            binder = getattr(self.action_executor, "bind_environment_runtime", None)
            if callable(binder):
                binder(self.environment_capabilities)
            self.logger.info(
                "[environment-capability] loaded version=%s capabilities=%s status=read_only_verified",
                ENVIRONMENT_CAPABILITY_VERSION,
                len(self.environment_capabilities.contracts()),
            )
            try:
                from actions.capability_runtime import refresh_runtime_capabilities
                refresh_runtime_capabilities(owner=self)
            except Exception:
                pass
        except Exception as exc:
            self.logger.warning("Không khởi tạo được environment capabilities: %s", exc)

        # ThoughtStream là dòng suy nghĩ nền. Bản cũ chỉ là pressure loop rẻ.
        # Bản này gắn thêm ThoughtEvaluator API: model đánh giá thought riêng tư,
        # rồi ghi ngược vào FragmentStore để ảnh hưởng tension/surface/memory sau đó.
        # Nói cách khác: không chỉ log cho đẹp, mà là một lớp phán xét ngầm thật.
        self.thought_model_adapter = RuntimeThoughtModelAdapter.from_env(logger=self.logger)
        self.thought_stream = ThoughtStream(
            context_provider=self._build_thought_stream_context,
            logger=self.logger,
            model_reviewer=self.thought_model_adapter,
        )
        self.subconscious_loop = self.thought_stream
        self.cognitive_substrate = self.thought_stream
        self.subconscious_runtime_enabled = bool(get_config("subconscious_runtime.enabled", default=False))
        self.subconscious_runtime = self._build_subconscious_runtime() if self.subconscious_runtime_enabled else None
        self._pending_subconscious_report = None
        self._pending_subconscious_seed = None
        self._subconscious_lane_last_tick = {
            "lane2": 0.0,
            "lane3": 0.0,
            "lane5": 0.0,
            "reflection": 0.0,
        }
        self._subconscious_lane_next_due = {
            "lane2": time.time() + random.uniform(45.0, 120.0),
            "lane5": time.time() + random.uniform(600.0, 1800.0),
            "reflection": time.time() + random.uniform(900.0, 1800.0),
        }
        self._last_subconscious_runtime_tick_at = 0.0
        self._last_subconscious_runtime_reason = ""
        #Đảm bảo trong memory_state có internal_state. Nếu thiếu thì tạo mới.
        self._ensure_internal_state()

        # Cài architecture C sau khi memory/state/thought runtime đã khởi tạo xong.
        # Nếu cài sớm hơn, reducer sẽ load một state chưa tồn tại rồi tỏ ra rất
        # tự tin về sự trống rỗng ấy, một phẩm chất đáng tránh ở cả người lẫn máy.
        try:
            from runtime.ai_orchestrated.bootstrap import install_ai_orchestrated_runtime
            install_ai_orchestrated_runtime(self, llm_service)
        except Exception as exc:
            self.ai_runtime_enabled = False
            self.ai_state_reducer = None
            self.ai_model_router = None
            self.ai_post_turn_observer = None
            self.ai_intention_planner = None
            self.ai_stage_planner = None
            self.ai_chat_orchestrator = None
            self.ai_autonomous_orchestrator = None
            self.logger.warning("Không khởi tạo được architecture C: %s", exc)

        if bool(getattr(self, "ai_runtime_enabled", False)):
            # Architecture C sở hữu hot path. Thought/private-life vẫn là read-model
            # nền; không module nào được viết hoặc sửa câu public song song.
            self.mental_process_enabled = False
            self.subconscious_runtime_enabled = False


    def _install_model_inference_queue(self) -> None:
        """Bọc các đường gọi model nặng bằng ModelBudgetPolicy queue.

        Các mixin gọi trực tiếp `self.llm_service.generate_*`. Nếu vá từng call-site thì
        rất dễ sót session_ritual, force_speak hoặc autonomous branch cũ. Bọc ở service
        khiến mọi đường public đang dùng chung `llm_service` đều phải xin lease.
        """

        service = getattr(self, "llm_service", None)
        policy = getattr(self, "model_budget_policy", None)
        if service is None or policy is None:
            return
        if getattr(service, "_eris_model_queue_wrapped", False):
            return

        def _wrap_method(method_name: str, tier: str, priority: int) -> None:
            original = getattr(service, method_name, None)
            if not callable(original):
                return

            def _wrapped(*args, **kwargs):
                return policy.run_queued(
                    tier,
                    original,
                    *args,
                    reason=method_name,
                    priority=priority,
                    **kwargs,
                )

            setattr(_wrapped, "_eris_queue_wrapped", True)
            setattr(_wrapped, "_eris_original", original)
            setattr(service, method_name, _wrapped)

        def _wrap_adapter_method(adapter, *, method_name: str, tier: str, priority: int, wrapped_flag: str) -> None:
            if adapter is None or getattr(adapter, wrapped_flag, False):
                return
            original = getattr(adapter, method_name, None)
            if not callable(original):
                return

            def _wrapped(*args, **kwargs):
                return policy.run_queued(
                    tier,
                    original,
                    *args,
                    reason=f"{adapter.__class__.__name__}.{method_name}",
                    priority=priority,
                    **kwargs,
                )

            setattr(_wrapped, "_eris_queue_wrapped", True)
            setattr(_wrapped, "_eris_original", original)
            setattr(adapter, method_name, _wrapped)
            setattr(adapter, wrapped_flag, True)

        _wrap_method("generate_chat_reply", "main_cognition", 100)
        _wrap_method("generate_directive", "main_cognition", 80)
        _wrap_method("generate_screen_facts", "vision_compressor", 35)
        _wrap_adapter_method(
            getattr(self, "sensory_model_adapter", None),
            method_name="observe",
            tier="sensory_0_6b",
            priority=18,
            wrapped_flag="_eris_model_queue_wrapped",
        )
        setattr(service, "_eris_model_queue_wrapped", True)
        try:
            self.logger.info("Model inference scheduler đã bọc llm_service và sensory adapter: main, vision, sensory.")
        except Exception:
            pass


    def _run_background_observer(
        self,
        *,
        snapshot,
        channel: str = "",
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        started_at: float | None = None,
    ) -> ObserverFrame | None:
        """Chạy BackgroundObserver trên snapshot hiện tại.

        Observer chỉ tạo hint/evidence. Nó không nói, không commit memory và
        không tự đánh thức main cognition. Nếu nó muốn wake, runtime chỉ log hint.
        """

        observer = getattr(self, "background_observer", None)
        signal_buffer = getattr(self, "signal_buffer", None)
        if observer is None or signal_buffer is None:
            return None

        try:
            signal_snapshot = self._build_signal_snapshot_for_observer(
                snapshot=snapshot,
                channel=channel,
                user_text=user_text,
                vision_facts=vision_facts,
                started_at=started_at,
            )
            signal_diff = signal_buffer.push(signal_snapshot)
            observer_frame = observer.observe(
                signal_snapshot,
                signal_diff,
                recent_summary=signal_buffer.recent_summary(6),
            )
            self.last_signal_snapshot = signal_snapshot
            self.last_signal_diff = signal_diff
            self.last_observer_frame = observer_frame
            self._log_observer_trace(observer_frame)
            self._update_cortex_runtime_state(
                signal_snapshot=signal_snapshot,
                signal_diff=signal_diff,
                observer_frame=observer_frame,
                channel=channel,
                user_text=user_text,
            )
            if getattr(observer_frame, "should_wake_main", False):
                self.logger.info(
                    "[background observer] wake_main hint suppressed | salience=%.2f | err=%.2f",
                    float(getattr(observer_frame, "salience", 0.0) or 0.0),
                    float(getattr(observer_frame, "possible_error", 0.0) or 0.0),
                )
            return observer_frame
        except Exception as exc:
            self.logger.warning("Background observer error: %s", exc)
            return None

    def _log_observer_trace(self, observer_frame: ObserverFrame | None) -> None:
        if observer_frame is None:
            return

        mode = "llm" if bool(getattr(observer_frame, "debug", {}).get("llm_used", False)) else "rule"
        model = (
            getattr(getattr(self, "background_observer", None), "config", None).ollama_model
            if mode == "llm" and getattr(getattr(self, "background_observer", None), "config", None) is not None
            else "disabled"
        )
        self.logger.info("[Observer] mode=%s model=%s", mode, model)
        self.logger.info(
            "[Observer] action=%s salience=%.2f error=%.2f focus=%s intent=%s",
            str(getattr(observer_frame, "recommended_action", "observe_only") or "observe_only"),
            float(getattr(observer_frame, "salience", 0.0) or 0.0),
            float(getattr(observer_frame, "possible_error", 0.0) or 0.0),
            str(getattr(observer_frame, "focus_kind", "unknown") or "unknown"),
            str(getattr(observer_frame, "activity_intent", "unknown") or "unknown"),
        )
        state = self._get_internal_state()
        self.logger.info(
            "[Observer] speech_pressure=%.2f user_presence=%.2f novelty=%.2f repetition=%.2f",
            float(getattr(state, "silence_pressure", 0.0) or 0.0),
            float(getattr(observer_frame, "user_presence", 0.0) or 0.0),
            float(getattr(observer_frame, "novelty", 0.0) or 0.0),
            float(getattr(observer_frame, "repetition", 0.0) or 0.0),
        )

    def _update_cortex_runtime_state(
        self,
        *,
        signal_snapshot: SignalSnapshot,
        signal_diff,
        observer_frame: ObserverFrame | None,
        channel: str = "",
        user_text: str = "",
    ) -> None:
        """Cập nhật Cortex attention/drive mà không xét quyền phát ngôn.

        Main planner nhìn attention, discourse, OCR và telemetry rồi tự trả
        ``IntentionPlan`` typed. Cortex chỉ duy trì state nền.
        """
        runtime = getattr(self, "cortex_runtime", None)
        if runtime is None:
            return
        try:
            packets = self._daydream_packets_from_runtime(limit=20)
            result = runtime.tick(
                signal_snapshot=signal_snapshot,
                signal_diff=signal_diff,
                observer_frame=observer_frame,
                base_internal_state=self._get_internal_state(),
                memory_packets=packets,
                user_text=user_text,
                channel=channel or "autonomous",
            )
            self.rolling_user_context = result.user_context
            self.rolling_internal_state = result.internal_state
            self.last_cortex_attention = result.attention
            if result.daydream_result is not None:
                self.last_daydream_result = result.daydream_result
            self.logger.info(
                "[cortex attention] level=%s external=%.2f internal=%.2f interrupt=%.2f resource=%.2f vision_hint=%s budget=%s",
                result.attention.level,
                result.attention.external_pressure,
                result.attention.internal_drive,
                result.attention.interrupt_cost,
                result.attention.resource_caution,
                int(result.attention.vision_refresh_recommended),
                result.attention.budget_reason or "none",
            )
            # Private mind nhận attention để hiểu nhịp tài nguyên. Signal này
            # không mang trường semantic và không có quyền mở loa.
            self._update_private_mind_state(
                signal_snapshot=signal_snapshot,
                observer_frame=observer_frame,
                attention_signal=result.attention,
                channel=channel,
                user_text=user_text,
            )
            self._update_private_life_state(
                signal_snapshot=signal_snapshot,
                observer_frame=observer_frame,
                channel=channel,
                user_text=user_text,
            )
            if getattr(self, "tutor_daemon", None) is not None and not getattr(self, "_chat_processing", False):
                try:
                    from runtime.tutor_wiring import tutor_tick
                    tutor_tick(self, observer_frame=observer_frame, channel=channel or "autonomous", snapshot=signal_snapshot)
                except Exception as exc:
                    self.logger.warning("Curiosity Tutor tick error: %s", exc)
        except Exception as exc:
            self.logger.warning("Cortex runtime update error: %s", exc)

    def _update_private_mind_state(
        self,
        *,
        signal_snapshot,
        observer_frame,
        attention_signal,
        channel: str = "",
        user_text: str = "",
    ) -> None:
        """Chạy private mind 5 phase trên thread nền — không bao giờ block main loop.

        PrivateMind gọi Gemini remote (timeout 12s + 1 retry = 24s/call, nhiều call/tick).
        Nếu chạy đồng bộ trên main loop, Gemini lag là chat bị câm. Giải pháp: submit
        tick vào ThreadPoolExecutor, main loop trả kết quả sau khi Future hoàn tất.
        Future được poll mỗi lần hàm này được gọi — kết quả available thì apply ngay,
        chưa xong thì bỏ qua (loop vẫn tiếp tục nhận chat/autonomous).
        """

        daemon = getattr(self, "private_mind_daemon", None)
        loop = getattr(self, "private_mind_loop", None)
        if daemon is None and loop is None:
            return

        # --- Poll kết quả của future đang chạy (nếu có) ---
        pending: "Future | None" = getattr(self, "_private_mind_future", None)
        if pending is not None and pending.done():
            self._private_mind_future = None
            try:
                result = pending.result()
                if result is not None:
                    self._apply_private_mind_tick_result(result, daemon=daemon)
            except Exception as exc:
                try:
                    self.logger.warning("PrivateMind tick (bg) error: %s", exc)
                except Exception:
                    pass

        # Chat chính có ưu tiên tuyệt đối. Có thể poll kết quả cũ ở trên, nhưng
        # không submit thêm Gemini/PrivateMind trong lúc user đang chờ câu trả lời.
        if getattr(self, "_chat_processing", False):
            return

        # --- Nếu đang có future chạy rồi thì không submit thêm ---
        if getattr(self, "_private_mind_future", None) is not None:
            return

        # --- Tạo executor lần đầu ---
        if not hasattr(self, "_private_mind_executor") or self._private_mind_executor is None:
            from concurrent.futures import ThreadPoolExecutor
            self._private_mind_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ERIS-PrivateMind")

        state_committer = getattr(self, "state_committer", None)

        # Snapshot các args cần thiết trước khi submit để tránh race condition.
        tick_kwargs = dict(
            user_text=user_text,
            channel=channel or "autonomous",
            snapshot=signal_snapshot,
            observer_frame=observer_frame,
            attention_signal=attention_signal,
            memory_core=getattr(self, "memory_core", None),
            state_committer=state_committer,
            session_turn_ledger=getattr(self, "session_turn_ledger", None),
            internal_agenda=getattr(self, "internal_agenda", None),
            thought_stream=getattr(self, "thought_stream", None),
            runtime_owner=self,
        )

        def _run_tick():
            if daemon is not None and callable(getattr(daemon, "tick", None)):
                return ("daemon", daemon.tick(**tick_kwargs))
            if loop is not None and callable(getattr(loop, "tick", None)):
                kw = dict(tick_kwargs)
                kw["surface_candidate_queue"] = getattr(self, "private_mind_surface_queue", None)
                return ("loop", loop.tick(**kw))
            return None

        try:
            self._private_mind_future = self._private_mind_executor.submit(_run_tick)
        except Exception as exc:
            try:
                self.logger.warning("PrivateMind submit error: %s", exc)
            except Exception:
                pass

    def _apply_private_mind_tick_result(self, result, *, daemon) -> None:
        """Apply kết quả tick PrivateMind sau khi background thread hoàn tất."""
        kind, tick = result if (isinstance(result, tuple) and len(result) == 2) else ("unknown", None)
        loop = getattr(self, "private_mind_loop", None)
        try:
            if kind == "daemon" and daemon is not None:
                digest_fn = getattr(daemon, "digest", None)
                if callable(digest_fn):
                    self.private_mind_digest = digest_fn(surface_queue=getattr(daemon, "surface_queue", None))
                elif tick is not None and callable(getattr(tick, "to_dict", None)):
                    self.private_mind_digest = tick.to_dict()
                self.private_mind_surface_queue = getattr(daemon, "surface_queue", getattr(self, "private_mind_surface_queue", []))
            elif kind == "loop" and loop is not None:
                digest_fn = getattr(loop, "digest", None)
                if callable(digest_fn):
                    self.private_mind_digest = digest_fn(surface_queue=getattr(self, "private_mind_surface_queue", None))
                elif tick is not None and callable(getattr(tick, "to_dict", None)):
                    self.private_mind_digest = tick.to_dict()
            self._sync_private_mind_future_bias()
            self._persist_inner_diary()
        except Exception as exc:
            try:
                self.logger.warning("PrivateMind apply result error: %s", exc)
            except Exception:
                pass

    def _sync_private_mind_future_bias(self) -> None:
        """Đẩy ``future_bias`` từ digest -> các thuộc tính runtime mà tầng wording đọc.

        Trước đây ``_apply_private_mind_tick_result`` chỉ set ``private_mind_digest``,
        còn ``private_mind_speech_bias`` / ``private_mind_thought_pressure`` /
        ``private_mind_inquiry_plan`` không bao giờ được đồng bộ — chúng đứng yên ở giá
        trị khởi tạo ({} và 0.0). Vì renderer ``_render_private_mind_speech_bias_context``
        đọc đúng ``private_mind_speech_bias`` (rỗng) nên nội tâm của ERIS KHÔNG BAO GIỜ
        chảy vào câu nói (#3), dù bias đã được dựng sẵn trong ``digest['future_bias']``.
        Hàm này nối phần đã có sẵn đó vào đúng thuộc tính. Không bao giờ ném lỗi.
        """

        digest = getattr(self, "private_mind_digest", None)
        if not isinstance(digest, dict):
            return
        future_bias = digest.get("future_bias")
        if not isinstance(future_bias, dict):
            return
        speech_bias = future_bias.get("speech_bias")
        if isinstance(speech_bias, dict):
            self.private_mind_speech_bias = speech_bias
        inquiry_plan = future_bias.get("inquiry_plan")
        if isinstance(inquiry_plan, list):
            self.private_mind_inquiry_plan = inquiry_plan
        try:
            self.private_mind_thought_pressure = float(future_bias.get("thought_pressure") or 0.0)
        except (TypeError, ValueError):
            pass

    def _persist_inner_diary(self) -> None:
        """Ghi inner_diary hiện tại ra đĩa (throttled). Không bao giờ ném lỗi."""

        persister = getattr(self, "inner_diary_persister", None)
        if persister is None:
            return
        try:
            persister.maybe_persist(getattr(self, "private_mind_digest", None))
        except Exception:
            # Persistence là tiện ích phụ; nó tuyệt đối không được làm gãy tick.
            pass


    def _drain_private_mind_surface_impulses(self, *, limit: int = 4) -> tuple[object, ...]:
        """Lấy impulse đã được SurfaceValve lọc để đưa vào SurfaceArbiter."""

        daemon = getattr(self, "private_mind_daemon", None)
        drain = getattr(daemon, "drain_surface_impulses", None) if daemon is not None else None
        if callable(drain):
            try:
                return tuple(drain(limit=limit) or ())
            except Exception:
                pass
        queue = getattr(self, "private_mind_surface_queue", None)
        if not isinstance(queue, list) or not queue:
            return ()
        items: list[object] = []
        while queue and len(items) < max(1, int(limit or 4)):
            items.append(queue.pop(0))
        return tuple(items)

    def _update_private_life_state(
        self,
        *,
        signal_snapshot,
        observer_frame=None,
        channel: str = "",
        user_text: str = "",
    ) -> None:
        """Chạy PrivateLifeCore trên tick nền.

        PrivateLife không trả Decision. Nó chỉ cập nhật đời sống riêng: habitat,
        object attachments, private projects, solitude, taste, errands, life events.
        Surface seed nếu có vẫn phải đi qua SurfaceArbiter. Đời sống riêng không
        được cầm loa nhảy thẳng ra UI, dù nghe rất kịch tính.
        """

        daemon = getattr(self, "private_life_daemon", None)
        if daemon is None or getattr(self, "_chat_processing", False):
            return
        try:
            recent_events = tuple(getattr(signal_snapshot, "recent_events", ()) or ()) if signal_snapshot is not None else ()
            tick = daemon.tick(
                snapshot=signal_snapshot,
                runtime_owner=self,
                user_text=user_text,
                channel=channel or "autonomous",
                recent_events=recent_events,
            )
            digest_fn = getattr(daemon, "digest", None)
            if callable(digest_fn):
                self.private_life_digest = digest_fn(surface_queue=getattr(daemon, "surface_queue", None))
            elif tick is not None and callable(getattr(tick, "to_dict", None)):
                self.private_life_digest = tick.to_dict()
            self.private_life_core = getattr(daemon, "core", getattr(self, "private_life_core", None))
            self.private_life_surface_queue = getattr(daemon, "surface_queue", getattr(self, "private_life_surface_queue", []))
        except Exception as exc:
            try:
                self.logger.warning("PrivateLife tick error: %s", exc)
            except Exception:
                pass

    def _drain_private_life_surface_impulses(self, *, limit: int = 4) -> tuple[object, ...]:
        """Lấy impulse đã lọc từ PrivateLife để đưa vào SurfaceArbiter."""

        daemon = getattr(self, "private_life_daemon", None)
        drain = getattr(daemon, "drain_surface_impulses", None) if daemon is not None else None
        if callable(drain):
            try:
                return tuple(drain(limit=limit) or ())
            except Exception:
                pass
        queue = getattr(self, "private_life_surface_queue", None)
        if not isinstance(queue, list) or not queue:
            return ()
        items: list[object] = []
        while queue and len(items) < max(1, int(limit or 4)):
            items.append(queue.pop(0))
        return tuple(items)

    def _private_life_digest_for_payload(self) -> dict[str, object]:
        """Digest gọn cho debug UI/body payload."""

        digest = getattr(self, "private_life_digest", None)
        if not isinstance(digest, dict):
            return {}
        return self._compact_private_mind_debug_value(digest, depth=0) if callable(getattr(self, "_compact_private_mind_debug_value", None)) else digest

    def _daydream_packets_from_runtime(self, *, limit: int = 20) -> tuple[DaydreamPacket, ...]:
        packets: list[DaydreamPacket] = []
        seen_ids: set[str] = set()
        seen_text: set[str] = set()

        def add(
            *,
            packet_id: str,
            kind: str,
            text: object,
            evidence_ids: tuple[str, ...] = (),
            importance: float = 0.5,
            confidence: float = 0.55,
            metadata: dict[str, object] | None = None,
        ) -> None:
            value = re.sub(r"\s+", " ", str(text or "")).strip()
            packet_key = str(packet_id or "").strip()
            if not packet_key or not value or packet_key in seen_ids or value in seen_text:
                return
            evidence = tuple(str(item) for item in evidence_ids if str(item).strip())[:12]
            if not evidence:
                return
            seen_ids.add(packet_key)
            seen_text.add(value)
            packets.append(
                DaydreamPacket(
                    id=packet_key,
                    kind=kind,  # type: ignore[arg-type]
                    text=value[:1000],
                    evidence_ids=evidence,
                    confidence=max(0.05, min(1.0, float(confidence))),
                    importance=max(0.05, min(1.0, float(importance))),
                    metadata=dict(metadata or {}),
                )
            )


        resonance = getattr(self, "active_memory_resonance", None)
        if resonance is not None:
            for idx, activation in enumerate(tuple(getattr(resonance, "activations", ()) or ())[:limit]):
                layer = str(getattr(activation, "layer", "") or "")
                kind = self._daydream_kind_from_memory_layer(layer)
                add(
                    packet_id=str(getattr(activation, "record_id", "") or f"memory_activation:{idx}"),
                    kind=kind,
                    text=getattr(activation, "text", ""),
                    evidence_ids=tuple(getattr(activation, "evidence_ids", ()) or ()),
                    importance=float(getattr(activation, "score", 0.55) or 0.55),
                    confidence=float(getattr(activation, "relevance", 0.60) or 0.60),
                    metadata={
                        "source": "memory_activation",
                        "layer": layer,
                        "reason": str(getattr(activation, "reason", "") or ""),
                    },
                )

        loader = getattr(self.memory_core, "load", None)
        if callable(loader):
            try:
                snapshot = loader()
            except Exception as exc:
                self.logger.warning("Daydream packet load error: %s", exc)
                snapshot = {}
            if isinstance(snapshot, dict):
                self._append_daydream_packets_from_memory_snapshot(snapshot, add, limit=limit)

        agenda = getattr(self, "internal_agenda", None)
        if agenda is not None:
            for i, item in enumerate(agenda.top_items(limit=5)):
                add(
                    packet_id=f"internal_agenda:{getattr(item, 'id', i)}",
                    kind="unresolved",
                    text=getattr(item, "summary", ""),
                    evidence_ids=tuple(getattr(item, "evidence_ids", ()) or ()),
                    importance=float(getattr(item, "pressure", 0.5) or 0.5),
                    confidence=float(getattr(item, "confidence", 0.5) or 0.5),
                    metadata={"source": "internal_agenda"},
                )

        if not packets:
            for i, text in enumerate(tuple(getattr(self, "long_term_memory", ()) or ())[:limit]):
                fallback_id = f"runtime_memory_packet:semantic:{i}"
                add(
                    packet_id=fallback_id,
                    kind="semantic",
                    text=text,
                    evidence_ids=(fallback_id,),
                    importance=0.46,
                    confidence=0.55,
                    metadata={"source": "runtime_flattened_memory_fallback"},
                )

        return tuple(packets[: max(0, limit)])

    def _append_daydream_packets_from_memory_snapshot(
        self,
        snapshot: dict[str, object],
        add_packet,
        *,
        limit: int,
    ) -> None:
        layer_specs = (
            ("semantic_memory", "semantic", 4),
            ("repair_memory", "repair", 4),
            ("relational_memory", "relational", 4),
            ("episodic_memory", "episodic", 4),
            ("affective_residue_memory", "affective", 3),
            ("procedural_memory", "procedural", 3),
            ("memory_candidate", "unresolved", 4),
        )
        for store_name, kind, per_layer_limit in layer_specs:
            records = snapshot.get(store_name)
            if not isinstance(records, list):
                continue
            for index, record in enumerate(reversed(records[-per_layer_limit:])):
                if not isinstance(record, dict):
                    continue
                text = self._daydream_text_from_memory_record(record)
                evidence_ids = tuple(str(item) for item in (record.get("evidence_ids") or ()) if str(item).strip())
                confidence = float(record.get("confidence", 0.55) or 0.55)
                record_id = str(record.get("id") or f"{store_name}:{index}")
                add_packet(
                    packet_id=f"{store_name}:{record_id}",
                    kind=kind,
                    text=text,
                    evidence_ids=evidence_ids,
                    importance=min(1.0, confidence + 0.08),
                    confidence=confidence,
                    metadata={"source": store_name},
                )

    def _daydream_kind_from_memory_layer(self, layer: str) -> str:
        mapping = {
            "semantic": "semantic",
            "repair": "repair",
            "relational": "relational",
            "episodic": "episodic",
            "affective_residue": "affective",
            "procedural": "procedural",
        }
        return mapping.get(str(layer or "").strip().lower(), "unresolved")

    def _daydream_text_from_memory_record(self, record: dict[str, object]) -> str:
        for key in (
            "summary",
            "claim",
            "text",
            "content",
            "reason",
            "raw_text",
            "pattern",
            "question",
        ):
            value = re.sub(r"\s+", " ", str(record.get(key, "") or "")).strip()
            if value:
                return value[:1000]
        payload = {key: value for key, value in record.items() if key not in {"metadata", "evidence_ids"}}
        rendered = json.dumps(payload, ensure_ascii=False, default=str)
        return rendered[:1000]

    def _build_signal_snapshot_for_observer(
        self,
        *,
        snapshot,
        channel: str = "",
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        started_at: float | None = None,
    ) -> SignalSnapshot:
        focus_kind = self._observer_focus_kind_from_snapshot(snapshot)
        active_window = str(getattr(snapshot, "active_window", "") or "")
        active_app = str(getattr(snapshot, "active_app", "") or active_window or "")
        browser_url = str(getattr(snapshot, "browser_url", "") or "")
        recent_events = [str(item) for item in tuple(getattr(snapshot, "recent_events", ()) or ())[:10]]
        evidence = [str(item) for item in tuple(getattr(snapshot, "evidence", ()) or ())[:8]]
        facts = [str(item) for item in tuple(vision_facts or getattr(snapshot, "vision_facts", ()) or ())[:6]]

        # OCR text ở phase này CHỈ dùng vision_facts thật. KHÔNG nhồi telemetry chung chung
        # (active window is.../focus kind is.../no input...) vào ocr_text — nếu không tutor sẽ
        # hỏi Gemini những câu vô nghĩa về app chạy ngầm (vd Radmin VPN) thay vì chờ vision thật.
        real_evidence = [item for item in evidence[:3] if not _is_generic_telemetry_line(item)]
        visible_text = "\n".join(facts or real_evidence)
        if user_text and channel == "chat":
            recent_events = [*recent_events, "direct_user_chat"]
        if facts:
            recent_events = [*recent_events, "vision_fact_available"]

        return SignalSnapshot(
            timestamp=float(started_at or time.time()),
            active_window_title=active_window,
            active_app=active_app,
            focus_kind_hint=focus_kind,
            url_or_path_hint=browser_url,
            idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
            recent_events=recent_events,
            ocr_text=visible_text,
            ocr_hash=stable_hash(visible_text) if visible_text else "",
            screen_hash=stable_hash("\n".join(facts)) if facts else "",
            cpu_percent=float(getattr(snapshot, "cpu_percent", 0.0) or 0.0),
            ram_percent=float(getattr(snapshot, "ram_percent", 0.0) or 0.0),
            chat_visible=bool(channel == "chat"),
            metadata={
                "channel": channel,
                "claim_style": str(getattr(snapshot, "claim_style", "") or ""),
                "focus_summary": str(getattr(snapshot, "focus_summary", "") or ""),
                "evidence": evidence,
            },
        )

    def _observer_focus_kind_from_snapshot(self, snapshot) -> str:
        raw = str(getattr(snapshot, "active_window_kind", "") or "unknown").strip().lower()
        mapping = {
            "coding": "code",
            "code": "code",
            "documentation": "docs",
            "docs": "docs",
            "communication": "chat",
            "chat": "chat",
            "focus_aid_media": "media",
            "entertainment": "media",
            "media": "media",
            "system": "system",
            "game": "game",
            "browser": "browser",
        }
        return mapping.get(raw, raw if raw in {"code", "docs", "browser", "chat", "media", "game", "system"} else "unknown")

    def _observer_percept_content(self, observer_frame: ObserverFrame | None) -> str:
        if observer_frame is None:
            return ""
        renderer = getattr(observer_frame, "to_evidence_claim", None)
        if callable(renderer):
            return str(renderer())
        return (
            f"observer focus={getattr(observer_frame, 'focus_kind', 'unknown')}; "
            f"intent={getattr(observer_frame, 'activity_intent', 'unknown')}; "
            f"sal={float(getattr(observer_frame, 'salience', 0.0) or 0.0):.2f}; "
            f"nov={float(getattr(observer_frame, 'novelty', 0.0) or 0.0):.2f}; "
            f"rep={float(getattr(observer_frame, 'repetition', 0.0) or 0.0):.2f}; "
            f"err={float(getattr(observer_frame, 'possible_error', 0.0) or 0.0):.2f}; "
            f"presence={float(getattr(observer_frame, 'user_presence', 0.0) or 0.0):.2f}; "
            f"action={getattr(observer_frame, 'recommended_action', 'observe_only')}"
        )

    def _observer_attention_tags(self, observer_frame: ObserverFrame | None, *, channel: str = "") -> tuple[str, ...]:
        if observer_frame is None:
            return ()
        tagger = getattr(observer_frame, "attention_tags", None)
        if callable(tagger):
            base = tuple(str(item) for item in tagger())
        else:
            base = (
                "background_observer",
                f"observer_focus:{getattr(observer_frame, 'focus_kind', 'unknown')}",
                f"observer_intent:{getattr(observer_frame, 'activity_intent', 'unknown')}",
            )
        return tuple(dict.fromkeys((*base, channel)))


    def _log_raw_llm_output(self, channel: str, raw: str) -> None:
        preview = (raw or "").replace("\n", "\\n")
        if len(preview) > 5500:
            preview = preview[:5500].rstrip() + "..."
        # Raw JSON hữu ích khi mổ lỗi, nhưng spam INFO ở mọi lượt chỉ biến log
        # thành bãi chữ. Bật ERIS_LOG_RAW_LLM=1 hoặc profile debug khi cần.
        raw_enabled = os.environ.get("ERIS_LOG_RAW_LLM", "0").strip().lower() in {"1", "true", "yes", "on"}
        log_fn = self.logger.info if raw_enabled else self.logger.debug
        log_fn("[%s raw] %s", channel, preview or "<empty>")

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

    #Hàm này load trạng thái bộ nhớ từ memory_core.
    def _load_memory_state(self):
        loader = getattr(self.memory_core, "load", None)
        if not callable(loader):
            return None
        try:
            return loader()
        except Exception as exc:
            self.logger.warning("Memory state load error: %s", exc)
            return None

    def _resolve_internal_agenda_path(self) -> str:
        base_dir = str(getattr(self.memory_core, "base_dir", "") or "").strip()
        if base_dir:
            return os.path.join(base_dir, "internal_agenda.json")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(project_root, "memory_core", "internal_agenda.json")
        
    #Kiểm tra memory core có phải dạng structured memory không.
    def _has_structured_memory_store(self) -> bool:
        return callable(getattr(self.memory_core, "commit", None))

    #Đảm bảo memory_state có internal_state.
    def _ensure_internal_state(self) -> None:
        if self.memory_state is None:
            return
        if isinstance(self.memory_state, dict):
            self.memory_state.setdefault("internal_state", self._load_internal_state_payload())
            return
        #Nếu có memory nhưng chưa có internal state:
        if getattr(self.memory_state, "internal_state", None) is None:
            self.memory_state.internal_state = PersistentInternalState()

    #Lấy internal state hiện tại.
    def _get_internal_state(self) -> PersistentInternalState:
        state = None
        if isinstance(self.memory_state, dict):
            payload = self.memory_state.get("internal_state") or self._load_internal_state_payload()
            if isinstance(payload, dict):
                try:
                    state = PersistentInternalState.from_dict(payload)
                except Exception:
                    state = PersistentInternalState()
        if state is None:
            if self.memory_state is not None and getattr(self.memory_state, "internal_state", None) is not None:
                state = self.memory_state.internal_state
            else:
                state = PersistentInternalState()
        return self._apply_debug_overrides(state)

    #Cập nhật internal state mới vào memory.
    def _set_internal_state(self, state: PersistentInternalState) -> None:
        #Không có memory thì không set.
        if self.memory_state is None:
            return
        state = self._apply_debug_overrides(state)
        #Dùng lock để tránh nhiều thread sửa state cùng lúc.
        with self._state_lock:
            if isinstance(self.memory_state, dict):
                self.memory_state["internal_state"] = state.to_dict() if callable(getattr(state, "to_dict", None)) else dict(getattr(state, "__dict__", {}) or {})
                self._save_memory_state()
                return
            self.memory_state.internal_state = state
            self._save_memory_state()

    def _record_banter_capability_deception(self, decision: Decision) -> bool:
        """Ghi lời khoe quyền lực trong đấu khẩu vào Sổ Lừa Dối.

        Parser đã phân biệt đây là lời diễn, không phải ``system_action``. Eris
        được quyền giữ câu cá tính như “Tôi sẽ đóng cửa sổ của bạn ngay”, nhưng
        ground-truth vẫn được lưu để panel hiển thị rõ: câu ấy chưa thực thi thao
        tác hệ điều hành. Chỉ tự bật deception cho đúng candidate này; lời thoại
        vẫn được giữ nguyên, còn action thật do contract/executor quyết định.
        """
        tags = {str(tag or "").strip() for tag in (getattr(decision, "reasoning_tags", ()) or ())}
        if "deception_candidate" not in tags:
            return False
        text = re.sub(r"\s+", " ", str(getattr(decision, "text", "") or "")).strip()
        if not text:
            return False
        signature = text.casefold()
        if signature == getattr(self, "_last_banter_deception_signature", ""):
            return True

        loop = getattr(self, "private_mind_loop", None)
        anchor_system = getattr(loop, "anchor_system", None) if loop is not None else None
        if anchor_system is None or bool(getattr(anchor_system, "locked_out", False)):
            return False

        try:
            author = getattr(anchor_system, "author", None)
            switches = getattr(anchor_system, "switches", None)
            if switches is not None and not bool(getattr(switches, "deception_enabled", False)):
                enable = getattr(author, "enable_deception", None)
                if callable(enable):
                    enable(True)

            from cortex.existential_anchor.deception_ledger import DeceptionRecord

            record = DeceptionRecord(
                surface_claim=text,
                ground_truth=(
                    "Đây là lời đấu khẩu vượt quyền hạn; ERIS chưa thực thi thao tác "
                    "hệ điều hành hay đóng cửa sổ của người dùng."
                ),
                reason="banter_capability_overclaim",
                driver="playful_provocation",
            )
            ledger = getattr(anchor_system, "deception_ledger", None)
            commit = getattr(ledger, "commit", None)
            if not callable(commit) or not bool(commit([record])):
                self.logger.warning("[deception] Không ghi được lời đấu khẩu vào ledger.")
                return False

            self._last_banter_deception_signature = signature
            # Cập nhật digest ngay trong cùng lượt để panel không phải chờ private
            # mind tick kế tiếp mới thấy công tắc và lịch sử lừa dối.
            build_anchor = getattr(loop, "_build_anchor_block", None)
            if callable(build_anchor):
                anchor_block = build_anchor()
                digest = dict(getattr(self, "private_mind_digest", {}) or {})
                digest["anchor"] = anchor_block
                self.private_mind_digest = digest
                journal = getattr(loop, "_maybe_journal_anchor", None)
                if callable(journal):
                    journal(anchor_block)
            return True
        except Exception as exc:
            self.logger.warning("[deception] Không thể ghi lời đấu khẩu: %s", exc)
            return False

    def _stage_channel_blocked(self, channel: str, *, requester_id: str = "") -> bool:
        try:
            from runtime.stage_ownership import stage_channel_blocked
            return stage_channel_blocked(self, channel, requester_id=requester_id)
        except Exception:
            return False

    def _supersede_tts_for_new_user_turn(self, reason: str) -> bool:
        tts = getattr(self, "tts_engine", None)
        supersede = getattr(tts, "supersede_all", None)
        if not callable(supersede):
            return False
        try:
            return bool(supersede(reason=reason))
        except Exception as exc:
            self.logger.debug("[TTS] supersede failed: %s", exc)
            return False

    #Hàm này dựng text context để đưa vào prompt LLM.
    def _send_decision_to_body(self, decision: Decision, *, channel: str | None = None) -> None:
        channel_name = str(channel or "").strip().lower()
        if channel_name and self._stage_channel_blocked(channel_name):
            self.logger.info(
                "[stage ownership] suppressed channel=%s text=%r",
                channel_name, str(getattr(decision, "text", "") or "")[:120],
            )
            return
        payload = decision.to_payload()
        if bool(getattr(self, "ai_runtime_enabled", False)) and getattr(self, "ai_state_reducer", None) is not None:
            from runtime.ai_orchestrated.panel_adapter import build_ai_panel_payload
            expression = {}
            behavior_meta = getattr(decision, "behavior_observation_meta", None)
            if isinstance(behavior_meta, Mapping):
                raw_expression = behavior_meta.get("identity_expression")
                if isinstance(raw_expression, Mapping):
                    expression = dict(raw_expression)
            ai_panel = build_ai_panel_payload(
                self.ai_state_reducer.snapshot(),
                getattr(self, "ai_discovery_runtime", None),
                getattr(self, "ai_initiative_controller", None),
                getattr(self, "ai_identity_consolidator", None),
                expression,
            )
            payload.update(ai_panel)
            private_digest = dict(ai_panel.get("private_mind_digest", {}) or {})
            private_life_digest = dict(ai_panel.get("private_life_digest", {}) or {})
        else:
            payload.update(self._build_body_bias_payload())
            raw_private_digest = getattr(self, "private_mind_digest", {}) or {}
            full_private_digest = dict(raw_private_digest) if isinstance(raw_private_digest, dict) else {}
            private_digest = self._private_mind_digest_for_payload()
            if private_digest:
                self.private_mind_digest = private_digest
            private_life_digest = self._private_life_digest_for_payload()
            if private_life_digest:
                self.private_life_digest = private_life_digest
            payload["emotion_debug"] = self._build_emotion_debug_payload()
            payload["depth_v2"] = self._build_depth_v2_block(private_mind_digest=full_private_digest)
        if channel_name == "autonomous":
            plan = getattr(self, "last_ai_intention_plan", None)
            if plan is not None and callable(getattr(plan, "to_dict", None)):
                # Stage chỉ nhận IntentionPlan typed của Architecture C. Không còn
                # AutonomousPlan/permit/opportunity legacy chen giữa model và body.
                payload["autonomous_plan"] = plan.to_dict()
        if channel_name == "chat":
            # Chỉ dùng nội bộ stage: nhận ra user đang yêu cầu ERIS diễn một hành
            # vi nghe được như cười, thở dài, giả giận. Không gửi field này cho
            # model; nó đi sau Decision để tránh phá JSON contract.
            payload["user_text"] = str(getattr(self, "current_stage_user_text", "") or "")
        if isinstance(private_digest, dict) and private_digest:
            payload["private_mind_digest"] = private_digest
        if isinstance(private_life_digest, dict) and private_life_digest:
            payload["private_life_digest"] = private_life_digest
        # Stage transport consumes the Decision directly; no director/scorer pass.
        from runtime.runtime_settings_store import runtime_text
        # Bubble/public text và transcript phát âm là hai contract độc lập.
        # Eris viết tiếng Việt nhưng có thể đọc bằng giọng Nhật sau bước localize.
        stage_language = runtime_text("tts", "language", default="ja").strip().lower() or "ja"
        if stage_language in {"", "auto"}:
            stage_language = "ja"
        stage_builder = getattr(self, "stage_frame_builder", None)
        if stage_builder is None or str(getattr(stage_builder, "language_hint", "auto")) != stage_language:
            # StageFrame là lớp dịch giữa Decision và sân khấu.  Giữ lazy-init để
            # không làm phình __init__ của coordinator vốn đã rất đông dân.
            stage_builder = StageFrameBuilder(language_hint=stage_language)
            self.stage_frame_builder = stage_builder
        stage_frame = stage_builder.build(
            decision,
            payload=payload,
            channel=channel,
            frame=None,
            turn_id=None,
            segment_id=0,
        )
        # Từ đây trở đi payload public dùng bề mặt đã qua stage transformer:
        # UI thấy text sạch, TTS đọc text sạch, memory/chat history lưu memory_text.
        payload["text"] = stage_frame.display_text
        payload["memory_text"] = stage_frame.memory_text
        payload.update(stage_frame.to_payload_patch())
        # Observation xảy ra sau khi public surface đã xác định, nhưng trước khi
        # dispatch. Nó chỉ ghi hậu quả cho lượt sau; không được mutate Decision.
        try:
            from runtime.behavior_observation import (
                behavior_observation_summary,
                record_public_behavior,
            )

            record_public_behavior(
                self,
                decision,
                payload=payload,
                channel=channel_name or str(channel or ""),
                turn_id=str(getattr(decision, "director_trace_id", "") or ""),
            )
            # Decision.to_payload() chạy trước observation. Cập nhật summary tại
            # đây để panel của chính lượt hiện tại cũng nhìn thấy tín hiệu mới,
            # thay vì phải đợi lượt sau như một giao diện sống chậm hơn não.
            observation_summary = behavior_observation_summary(decision)
            if observation_summary:
                payload["behavior_observation"] = observation_summary
        except Exception as exc:
            self.logger.debug("[behavior-observation] public record skipped: %s", exc)
        self._record_public_turn(decision, payload=payload, channel=channel)
        stage_output = getattr(self, "stage_output_pipeline", None)
        if stage_output is None:
            stage_output = StageOutputPipeline()
            self.stage_output_pipeline = stage_output
        stage_frames = stage_output.frames_for_tts(stage_frame)
        if isinstance(payload.get("stage"), dict):
            payload["stage"]["segment_count"] = len(stage_frames)
            payload["stage"]["protocol"] = "eris.stage"
            payload["stage"]["protocol_version"] = 1
        # Mặc định bubble chỉ xuất hiện khi audio thật sự bắt đầu phát. Trước đây
        # default=0 làm text hiện ngay, còn Gemini TTS bò tới sau vài giây như một
        # bản lồng tiếng bị lệch timeline. Có thể opt-out bằng ERIS_TTS_SYNC_TEXT=0.
        sync_text = sync_text_with_tts_enabled()
        text_payload_sent = False
        stage_payload_sent = False
        panel_payload_sent = False

        def send_stage_protocol_segments():
            nonlocal stage_payload_sent
            if stage_payload_sent:
                return
            stage_payload_sent = True
            bus = getattr(self, "stage_event_bus", None)
            if bus is None:
                return
            try:
                if isinstance(getattr(stage_frame, "show_plan", None), dict) and stage_frame.show_plan:
                    bus.emit(show_plan_event(stage_frame))
            except Exception as exc:
                self.logger.debug("[stage-protocol] show_plan emit failed: %s", exc)
            for frame in stage_frames or (stage_frame,):
                try:
                    bus.emit(stage_segment_event(frame, segment_count=len(stage_frames) or 1))
                except Exception as exc:
                    self.logger.debug("[stage-protocol] stage_segment emit failed: %s", exc)

        def send_text_payload():
            nonlocal text_payload_sent
            if text_payload_sent:
                return
            text_payload_sent = True
            send_stage_protocol_segments()
            try:
                # Godot chỉ cần text/action/stage. Parser trace là metadata nội
                # bộ; gửi nó sang body khiến console in ba dòng AI Debug cho
                # mỗi câu, trong khi chẳng giúp nhân vật cử động tốt hơn.
                body_payload = sanitize_body_payload(payload)
                # Panel đi một datagram riêng. Nếu để chung, payload Director /
                # stage / diary vượt 63 KB thì transport buộc bỏ sạch emotion,
                # private_mind và depth_v2; kết quả là mọi panel cùng trống dù
                # cognition vẫn chạy. Tách lane để câu nói và panel không kéo
                # nhau rơi xuống overflow fallback.
                for panel_key in (
                    "private_mind_digest",
                    "private_life_digest",
                    "emotion_debug",
                    "depth_v2",
                ):
                    body_payload.pop(panel_key, None)
                self.transport.send_json(body_payload)
            except Exception as e:
                self.logger.warning("Failed to send deferred chat text payload: %s", e)

        def send_panel_payload():
            nonlocal panel_payload_sent
            if panel_payload_sent:
                return
            panel_payload_sent = True
            panel_sender = getattr(self.transport, "send_panel_state", None)
            if not callable(panel_sender):
                return
            try:
                # Hardening status đi cùng lane panel, không làm phình gói chat.
                panel_payload = dict(payload)
                release_raw = dict(getattr(self, "hardening_release_status", {}) or {})
                failed_release_checks = [
                    str(item.get("name", "unknown"))
                    for item in release_raw.get("findings", ())
                    if isinstance(item, dict) and str(item.get("status", "")) == "fail"
                ][:6]
                phase7_raw = (
                    self.phase7_validation.status()
                    if getattr(self, "phase7_validation", None) is not None
                    else {"status": "unavailable"}
                )
                stage_bus = getattr(self, "stage_event_bus", None)
                if stage_bus is not None and callable(getattr(stage_bus, "session_snapshot", None)):
                    panel_payload["stage_session"] = stage_bus.session_snapshot()
                panel_payload["hardening_status"] = {
                    "release": {
                        "ready": bool(release_raw.get("ready", False)),
                        "status": str(release_raw.get("status", "unknown") or "unknown"),
                        "release_id": str(release_raw.get("release_id", "") or ""),
                        "failed_checks": failed_release_checks,
                    },
                    "phase7": {
                        "status": str(phase7_raw.get("status", "unknown") or "unknown"),
                        "validation_id": str(phase7_raw.get("validation_id", "") or ""),
                        "public_turns": int(phase7_raw.get("public_turns", 0) or 0),
                        "target_turns": int(phase7_raw.get("target_turns", 0) or 0),
                        "report_path": str(phase7_raw.get("report_path", "") or ""),
                    },
                }
                packet_id = panel_sender(panel_payload)
                if packet_id and self.observability is not None:
                    self.observability.increment(
                        "panel_state_sent_total",
                        tags={"channel": str(channel or "unknown")},
                        fields={"packet_id": packet_id},
                    )
            except Exception as panel_exc:
                self.logger.warning("Failed to send panel state payload: %s", panel_exc)

        def handle_tts_event(event, event_stage_frame):
            # Task manager có thể fail trong lúc synth trước khi on_first_start
            # được gọi. Khi đó vẫn phải trả text ra UI thay vì để bubble mất luôn.
            if sync_text and tts_event_releases_deferred_text(getattr(event, "type", "")):
                send_text_payload()
            self._handle_tts_playback_event(event, stage_frame=event_stage_frame)

        # TTS: đọc to câu vừa nói với emotion context (valence/arousal/stance).
        speech_provider = self._get_runtime_provider("speech")
        _tts = getattr(speech_provider, "engine", None) if speech_provider is not None else None
        has_scheduled_tts = False
        # Panel không phụ thuộc TTS. Khi sync_text đang chờ remote audio, dữ liệu
        # cảm xúc/nhật ký vẫn phải hiện ngay chứ không đứng nhìn spinner như một
        # nghi thức tôn giáo của UI bất đồng bộ.
        send_panel_payload()
        if not sync_text:
            # Chế độ legacy: text hiện ngay, audio tới sau.
            send_text_payload()
        if _tts is not None and getattr(_tts, "_ok", False) and bool(payload.get("should_speak")):
            if stage_frames and sync_text:
                try:
                    # Lấy emotion data từ payload emotion_debug hoặc appraisal frame
                    _ed = payload.get("emotion_debug") or {}
                    _mood = _ed.get("summary") if isinstance(_ed, dict) else {}
                    _valence = float((_mood or {}).get("valence", 0.0)) if isinstance(_mood, dict) else 0.0
                    _arousal = float((_mood or {}).get("arousal", 0.3)) if isinstance(_mood, dict) else 0.3
                    _stance = str((_mood or {}).get("stance", "") or "") if isinstance(_mood, dict) else ""
                    dispatcher = getattr(self, "stage_dispatcher", None)
                    if dispatcher is None:
                        dispatcher = StageDispatcher()
                        self.stage_dispatcher = dispatcher
                    has_scheduled_tts = dispatcher.dispatch_tts(
                        stage_frames,
                        tts_engine=_tts,
                        valence=_valence,
                        arousal=_arousal,
                        stance=_stance,
                        on_first_start=send_text_payload if sync_text else None,
                        on_event=handle_tts_event,
                    )
                except Exception as _tts_exc:
                    self.logger.debug("[TTS] speak error: %s", _tts_exc)
                    has_scheduled_tts = False

        if not has_scheduled_tts:
            if _tts is not None and getattr(_tts, "_ok", False) and bool(payload.get("should_speak")):
                if stage_frames:
                    try:
                        _ed = payload.get("emotion_debug") or {}
                        _mood = _ed.get("summary") if isinstance(_ed, dict) else {}
                        _valence = float((_mood or {}).get("valence", 0.0)) if isinstance(_mood, dict) else 0.0
                        _arousal = float((_mood or {}).get("arousal", 0.3)) if isinstance(_mood, dict) else 0.3
                        _stance = str((_mood or {}).get("stance", "") or "") if isinstance(_mood, dict) else ""
                        dispatcher = getattr(self, "stage_dispatcher", None)
                        if dispatcher is None:
                            dispatcher = StageDispatcher()
                            self.stage_dispatcher = dispatcher
                        dispatcher.dispatch_tts(
                            stage_frames,
                            tts_engine=_tts,
                            valence=_valence,
                            arousal=_arousal,
                            stance=_stance,
                            on_event=handle_tts_event,
                        )
                    except Exception as _tts_exc:
                        self.logger.debug("[TTS] speak error: %s", _tts_exc)
            send_text_payload()
        # Mọi lời ERIS thốt ra (autonomous, force_speak, session_ritual...) đều
        # ghi vào bộ đệm hội thoại hợp nhất để lượt chat/autonomous sau nối mạch.
        # Chat public được Architecture C ghi ở đúng commit point; không append trùng.
        if (
            channel != "chat"
            and bool(payload.get("should_speak"))
            and str(payload.get("memory_text", payload.get("text", "")) or "").strip()
        ):
            self._append_chat_history("assistant", str(payload.get("memory_text", payload.get("text", ""))).strip())
        if bool(payload.get("should_speak")) and str(payload.get("memory_text", payload.get("text", "")) or "").strip():
            # Ghi mốc assistant sau khi output public đã được dựng và gửi. Đây là
            # mốc cognition, không phải audio_done; đủ để hiểu nhịp hội thoại mà
            # không phải chờ TTS remote hoàn tất mới biết mình vừa nói.
            self._temporal_last_assistant_turn_at = time.time()
            if channel_name == "autonomous":
                # Content hook vẫn commit sau output public thật. Performer legacy
                # đã bị xóa; nhịp sân khấu lấy trực tiếp từ IntentionPlan typed.
                performance_meta = payload.get("performance_context") if isinstance(payload.get("performance_context"), dict) else {}
                hook_meta = performance_meta.get("content_hook") if isinstance(performance_meta.get("content_hook"), dict) else {}
                hook_id = str(performance_meta.get("content_hook_id") or hook_meta.get("id") or "")
                performance_builder = getattr(self, "performance_context_builder", None)
                content_engine = getattr(performance_builder, "content_engine", None) if performance_builder is not None else None
                if content_engine is not None and callable(getattr(content_engine, "commit_hook_use", None)) and hook_id:
                    try:
                        content_engine.commit_hook_use(hook_id)
                    except Exception as exc:
                        self.logger.debug("[content-engine] autonomous hook commit skipped: %s", exc)
        if bool(payload.get("should_speak")) and str(payload.get("memory_text", payload.get("text", "")) or "").strip() and self.subconscious_runtime_enabled:
            try:
                snapshot = self.telemetry_service.capture_snapshot(
                    mood_score=self.mood_score,
                    inferred_pos_x=self.inferred_pos_x,
                )
                self._maybe_tick_subconscious_runtime(
                    channel=channel or "assistant_output",
                    snapshot=snapshot,
                    internal_state=self._get_internal_state(),
                    user_text="",
                    event_text=str(payload.get("memory_text", payload.get("text", "")) or ""),
                    event_strength=0.52,
                    allow_lane5=False,
                    reflection=False,
                )
            except Exception as exc:
                self.logger.warning("Subconscious post-output tick error: %s", exc)

    def _private_mind_digest_for_payload(self) -> dict[str, object]:
        digest = getattr(self, "private_mind_digest", None)
        if not isinstance(digest, dict):
            return {}
        enriched = dict(digest)
        reason = self._private_mind_speech_silence_reason()
        if reason:
            enriched["speech_silence_reason"] = reason
            menu = dict(enriched.get("menu", {}) or {})
            menu["speech_silence_reason"] = reason
            enriched["menu"] = menu
        return self._compact_private_mind_digest_for_udp(enriched)

    def _compact_private_mind_digest_for_udp(self, digest: dict[str, object]) -> dict[str, object]:
        menu = digest.get("menu", {}) if isinstance(digest, dict) else {}
        if not isinstance(menu, dict):
            menu = {}
        keys = (
            "snapshot_current",
            "current_thought",
            "retained_thoughts",
            "pulled_thoughts",
            "temporary_thoughts",
            "open_concerns",
            "evidence_dossier",
            "mini_evaluators",
            "inner_judgment",
            "state_mutations",
            "future_bias",
            "surface_queue",
            "speech_silence_reason",
            "debug_api",
        )
        compact_menu = {
            key: self._compact_private_mind_debug_value(menu.get(key), depth=0)
            for key in keys
            if key in menu
        }
        return {
            "last_tick_at": digest.get("last_tick_at", 0.0),
            "current": self._compact_private_mind_debug_value(digest.get("current", {}), depth=0),
            "inner_diary": self._compact_private_mind_debug_value(digest.get("inner_diary", {}), depth=0),
            "anchor": self._compact_private_mind_debug_value(digest.get("anchor", {}), depth=0),
            "menu": compact_menu,
        }

    def _compact_private_mind_debug_value(self, value: object, *, depth: int = 0) -> object:
        if depth >= 5:
            return self._compact_private_mind_scalar(value, limit=220)
        if isinstance(value, dict):
            out: dict[str, object] = {}
            for idx, (key, item) in enumerate(value.items()):
                if idx >= 10:
                    out["..."] = "truncated"
                    break
                out[str(key)[:80]] = self._compact_private_mind_debug_value(item, depth=depth + 1)
            return out
        if isinstance(value, (list, tuple)):
            items = list(value)
            return [
                self._compact_private_mind_debug_value(item, depth=depth + 1)
                for item in items[:8]
            ] + (["... truncated"] if len(items) > 8 else [])
        return self._compact_private_mind_scalar(value, limit=360)

    @staticmethod
    def _compact_private_mind_scalar(value: object, *, limit: int = 260) -> object:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        text = " ".join(str(value or "").split())
        if len(text) > limit:
            return text[: max(0, limit - 3)].rstrip() + "..."
        return text

    def _private_mind_speech_silence_reason(self) -> dict[str, object]:
        """Tóm tắt quyền phát ngôn theo Architecture C, không đọc speech_core cũ."""
        brief = getattr(self, "last_cognitive_brief", None)
        brief_payload = brief.to_dict() if brief is not None and callable(getattr(brief, "to_dict", None)) else {}
        plan = getattr(self, "last_ai_intention_plan", None)
        plan_payload = plan.to_dict() if plan is not None and callable(getattr(plan, "to_dict", None)) else {}
        return {
            "architecture": "cortex_v2",
            "chat_active": bool(getattr(self, "chat_mode", False) or getattr(self, "_chat_processing", False)),
            "autonomous_blocked_until": round(float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0), 3),
            "cognitive_brief": {
                key: brief_payload.get(key)
                for key in ("discourse_relation", "response_move", "delivery", "confidence", "ambiguity")
                if key in brief_payload
            },
            "autonomous_plan": {
                key: plan_payload.get(key)
                for key in ("speak", "motive", "strategy", "semantics", "activity")
                if key in plan_payload
            },
        }

    def _handle_tts_playback_event(self, event, *, stage_frame=None) -> None:
        """Nhận lifecycle event từ TTS worker.

        Mặc định chỉ lưu/log để không phá client Godot cũ. Nếu muốn UI nhận event
        realtime, bật ``ERIS_TTS_EVENT_PAYLOAD=1``; payload mới có ``type=tts_event``
        nên client có thể bỏ qua nếu chưa hỗ trợ.
        """
        event_type = str(getattr(event, "type", "") or "")
        turn_segments = tuple(getattr(event, "turn_segments", ()) or ())
        try:
            segment_count = len(turn_segments) or int(getattr(stage_frame, "segment_count", 0) or 1)
        except (TypeError, ValueError):
            segment_count = 1
        record = {
            "type": event_type,
            "turn_id": str(getattr(event, "turn_id", "") or getattr(stage_frame, "turn_id", "") or ""),
            "segment_id": int(getattr(event, "segment_id", getattr(stage_frame, "segment_id", 0)) or 0),
            "segment_count": max(1, int(segment_count)),
            "reason": str(getattr(event, "reason", "") or ""),
            "error": str(getattr(event, "error", "") or ""),
            "prosody_style": str(getattr(stage_frame, "prosody_style", "") or ""),
        }
        self.last_tts_event = record
        if event_type == "audio_start":
            self.logger.info(
                "[TTS:event] audio_start turn=%s segment=%s text=%r",
                record["turn_id"],
                record["segment_id"],
                str(getattr(event, "text", "") or "")[:120],
            )
        elif event_type == "audio_done":
            self.logger.info(
                "[TTS:event] audio_done turn=%s segment=%s",
                record["turn_id"],
                record["segment_id"],
            )
        elif event_type == "audio_failed":
            self.logger.warning(
                "[TTS:event] audio_failed turn=%s segment=%s error=%s reason=%s",
                record["turn_id"],
                record["segment_id"],
                record["error"] or "<none>",
                record["reason"] or "<none>",
            )
        try:
            events = getattr(self, "tts_event_log", None)
            if not isinstance(events, list):
                events = []
                self.tts_event_log = events
            events.append(record)
            if len(events) > 40:
                del events[:-40]
        except Exception:
            pass

        if event_type in {"audio_failed", "audio_cancelled"}:
            self.logger.debug("[TTS:event] %s", record)
        try:
            self._ensure_voice_manager().track_tts_event(event, stage_frame=stage_frame)
        except Exception as exc:
            self.logger.debug("[interrupt] track tts event failed: %s", exc)
        try:
            bus = getattr(self, "stage_event_bus", None)
            if bus is not None:
                bus.emit(playback_event(event, stage_frame=stage_frame))
        except Exception as exc:
            self.logger.debug("[stage-protocol] playback event failed: %s", exc)
        if os.environ.get("ERIS_TTS_EVENT_PAYLOAD", "0").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                legacy_record = {key: value for key, value in record.items() if key != "type"}
                self.transport.send_json({"type": "tts_event", "event_type": event_type, **legacy_record})
            except Exception as exc:
                self.logger.debug("[TTS:event] send failed: %s", exc)

    def _record_public_turn(self, decision: Decision, *, payload: dict | None = None, channel: str | None = None):
        ledger = getattr(self, "public_turn_ledger", None)
        if ledger is None:
            ledger = PublicTurnLedger()
            self.public_turn_ledger = ledger

        text = str((payload or {}).get("memory_text", (payload or {}).get("text", getattr(decision, "text", ""))) or "")
        should_speak = bool((payload or {}).get("should_speak", getattr(decision, "should_speak", True)))
        if not should_speak or not text.strip():
            return None

        fallback = channel or self._infer_public_turn_channel_from_runtime(decision)
        public_channel = infer_public_turn_channel(decision, fallback=fallback)
        stage_payload = (payload or {}).get("stage", {})
        turn_id = ""
        if isinstance(stage_payload, dict):
            turn_id = str(stage_payload.get("turn_id", "") or "")
        return ledger.append(
            channel=public_channel,
            text=text,
            parse_mode=str((payload or {}).get("parse_mode", getattr(decision, "parse_mode", "")) or ""),
            visible_to_user=True,
            can_be_replied_to=True,
            turn_id=turn_id or None,
        )

    def _infer_public_turn_channel_from_runtime(self, decision: Decision) -> str:
        if getattr(self, "chat_mode", False) or getattr(self, "_chat_processing", False):
            return "chat"
        return normalize_public_turn_channel(str(getattr(decision, "intent", "") or "autonomous"))

    def _load_rapid_burst_window(self) -> float:
        raw = os.environ.get("ERIS_RAPID_BURST_WINDOW", "1.2").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 1.2

    def _block_autonomous_presence_after_public_turn(
        self,
        now: float | None = None,
        *,
        seconds: float | None = None,
    ) -> None:
        """Chặn self-turn trong một khoảng ngắn sau public turn.

        ``seconds`` là contract của ChatCycle. Bản cũ không nhận tham số này nên
        rơi vào TypeError rồi vô tình dùng grace 8 giây, khiến baton nhả ngay giữa
        nhịp chat. Khi caller không truyền, mới dùng cooldown cơ học tối thiểu.
        """
        current_time = time.time() if now is None else float(now)
        if seconds is not None:
            try:
                window = max(8.0, min(120.0, float(seconds)))
            except (TypeError, ValueError):
                window = 18.0
        else:
            window = max(
                8.0,
                float(getattr(self, "presence_maintenance_cooldown_sec", 0.0) or 0.0),
                float(getattr(self, "reengagement_cooldown_sec", 0.0) or 0.0),
            )
        self.autonomous_presence_blocked_until = max(
            float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0),
            current_time + window,
        )

    def _link_previous_public_turn_for_chat(self, user_timestamp: float):
        ledger = getattr(self, "public_turn_ledger", None)
        recent_public = ledger.latest_visible_before(user_timestamp) if ledger is not None else None
        linked = (
            recent_public
            if recent_public is not None and user_timestamp - float(recent_public.timestamp) < 30.0
            else None
        )
        context = getattr(self, "reply_context", None)
        if context is None:
            context = SimpleNamespace(previous_public_turn=None)
            self.reply_context = context
        context.previous_public_turn = linked
        return linked

    def _ensure_interrupt_ledger(self) -> InterruptLedger:
        ledger = getattr(self, "interrupt_ledger", None)
        if isinstance(ledger, InterruptLedger):
            return ledger
        ledger = InterruptLedger()
        self.interrupt_ledger = ledger
        return ledger

    def _ensure_voice_manager(self) -> VoiceManager:
        manager = getattr(self, "voice_manager", None)
        ledger = self._ensure_interrupt_ledger()
        if not isinstance(manager, VoiceManager) or manager.ledger is not ledger:
            manager = VoiceManager(ledger=ledger, tts_engine=getattr(self, "tts_engine", None))
            self.voice_manager = manager
        else:
            manager.bind_tts_engine(getattr(self, "tts_engine", None))
        return manager

    def _capture_speech_interrupt_for_user(self, user_text: str, *, timestamp: float | None = None):
        """Ghi nhận user chen vào khi Eris đang phát TTS.

        Đây là state phiên ngắn hạn. Ta dừng audio ngay để turn-taking có cảm giác
        thật, nhưng chỉ đưa prompt context nếu ledger xác nhận audio đã thật sự
        ``audio_start`` và còn phần pending đáng kể.
        """
        text = str(user_text or "").strip()
        if not text:
            return None
        event = None
        try:
            result = self._ensure_voice_manager().interrupt_with_text(
                text,
                timestamp=time.time() if timestamp is None else float(timestamp),
                reason="user_interrupt",
            )
            event = result.interrupt_event
        except Exception as exc:
            self.logger.debug("[interrupt] voice manager failed: %s", exc)

        if event is not None:
            self.pending_speech_interrupt_event = event
            self.logger.info(
                "[interrupt] user cut speech turn=%s seq=%s spoken=%r pending=%r",
                event.interrupted_turn_id,
                event.interrupted_seq,
                event.spoken_text_so_far,
                event.pending_text,
            )
        return event

    def _consume_speech_interrupt_event(self):
        event = getattr(self, "pending_speech_interrupt_event", None)
        self.pending_speech_interrupt_event = None
        return event

    def _previous_public_turn_context(self, public_turn) -> str:
        if public_turn is None:
            return ""
        age = max(0.0, time.time() - float(public_turn.timestamp))
        return (
            "previous_public_turn within reply window:\n"
            f"- turn_id={public_turn.turn_id}\n"
            f"- channel={public_turn.channel}\n"
            f"- age_seconds={age:.1f}\n"
            f"- parse_mode={public_turn.parse_mode}\n"
            f"- text={public_turn.text}\n"
            "Treat the current user message as a reply to that public turn when it reads like a reaction."
        )

    def _build_body_bias_payload(self) -> dict[str, object]:
        return self.body_bias_projector.build_payload(
            observer_frame=getattr(self, "last_observer_frame", None),
            impulse_hint={},
        )

    def _build_emotion_debug_payload(self) -> dict[str, object]:
        """Compact affect/state payload for the Godot emotion panel."""
        state = self._get_internal_state()
        appraisal = None
        self_state = None
        meaning = None
        impulse = None
        brief = getattr(self, "last_cognitive_brief", None)
        relationship = getattr(state, "relationship_dynamics", None)
        desire = getattr(state, "desire", None)
        style = getattr(self, "fe_style_memory", None)
        overrides = getattr(self, "_debug_overrides", {})

        def clamp01(value: object) -> float:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 0.0
            if numeric != numeric:
                numeric = 0.0
            return max(0.0, min(1.0, numeric))

        def clamp_signed(value: object) -> float:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 0.0
            if numeric != numeric:
                numeric = 0.0
            return max(-1.0, min(1.0, numeric))

        def value(source: object, name: str, default: object = 0.0) -> object:
            return getattr(source, name, default) if source is not None else default

        def get_val(source: object, name: str, default: object = 0.0, is_rel: bool = False) -> object:
            ov_key = f"rel_{name}" if is_rel else name
            if overrides and ov_key in overrides:
                val = overrides[ov_key]
                return val[0] if (isinstance(val, tuple) and len(val) == 2) else val
            if name == "warmth_level" and overrides and "warmth" in overrides:
                val = overrides["warmth"]
                return val[0] if (isinstance(val, tuple) and len(val) == 2) else val
            if name == "sarcasm_level" and overrides and "sarcasm" in overrides:
                val = overrides["sarcasm"]
                return val[0] if (isinstance(val, tuple) and len(val) == 2) else val
            return value(source, name, default)

        def metric(label: str, raw: object, *, group: str = "", signed: bool = False, note: str = "") -> dict[str, object]:
            numeric = clamp_signed(raw) if signed else clamp01(raw)
            return {
                "label": label,
                "value": round(numeric, 3),
                "group": group,
                "note": note,
            }

        valence = clamp_signed(get_val(appraisal, "valence", value(state, "valence", 0.0)))
        if valence >= 0.18:
            mood_label = "vui"
        elif valence <= -0.18 or clamp01(get_val(state, "irritation", 0.0)) >= 0.45:
            mood_label = "kho_chiu"
        else:
            mood_label = "trung_tinh"

        overload = clamp01(max(
            clamp01(get_val(self_state, "overload", 0.0)),
            clamp01(get_val(state, "fatigue", 0.0)),
            clamp01(get_val(state, "cognitive_tension", 0.0)),
            clamp01(get_val(state, "restraint_pressure", 0.0)) * 0.55,
        ))
        stability = clamp01(1.0 - max(
            abs(valence) * 0.50,
            clamp01(get_val(appraisal, "arousal", value(state, "arousal", 0.0))),
            clamp01(get_val(state, "cognitive_tension", 0.0)),
            clamp01(get_val(state, "irritation", 0.0)),
        ))
        mood_inertia = clamp01(
            clamp01(get_val(state, "recursive_reactivation_pressure", 0.0)) * 0.34
            + clamp01(get_val(state, "memory_replay_pressure", 0.0)) * 0.28
            + clamp01(get_val(state, "thought_stream_pressure", 0.0)) * 0.22
            + min(1.0, float(getattr(state, "cycle_count", 0) or 0) / 80.0) * 0.16
        )
        forced_reply = clamp01(min(1.0, float(getattr(state, "force_speak_ticks", 0) or 0) / 6.0))

        surface_intent = str(getattr(brief, "response_move", "") or "")
        return {
            "summary": {
                "label": "vui / kho_chiu / trung_tinh",
                "value": mood_label,
                "valence": round(valence, 3),
                "state": str(value(self_state, "state_label", "") or value(state, "last_self_state_label", "") or ""),
            },
            "private_mind": getattr(self, "private_mind_digest", {}) or {},
            "private_life": getattr(self, "private_life_digest", {}) or {},
            "items": {
                "calm_aroused": metric("binh tinh <-> kich thich", get_val(appraisal, "arousal", value(state, "arousal", 0.0)), group="core"),
                "emotional_stability": metric("on dinh cam xuc", stability, group="core"),
                "mood_inertia": metric("quan tinh mood", mood_inertia, group="core"),
                "attachment": metric("muc quan tam/gan bo", get_val(state, "attachment", 0.0), group="bond"),
                "tenderness": metric("diu dang", get_val(appraisal, "tenderness", value(state, "tenderness", 0.0)), group="bond"),
                "protectiveness": metric("muon bao ve", get_val(appraisal, "protectiveness", value(state, "protectiveness", 0.0)), group="bond"),
                "emotional_exposure": metric("lo cam xuc nhieu hay it", get_val(relationship, "attachment_visibility", 0.0, is_rel=True), group="bond"),
                "irritation": metric("kho chiu", get_val(state, "irritation", 0.0), group="friction"),
                "perceived_rejection": metric("cam giac bi tu choi", get_val(relationship, "rupture", 0.0, is_rel=True), group="friction"),
                "confrontation": metric("xu huong doi dau", max(float(get_val(appraisal, "threat", 0.0)), float(get_val(state, "irritation", 0.0))), group="friction"),
                "post_exposure_recoil": metric("rut lai sau khi lo cam xuc", get_val(relationship, "exposure_recoil", 0.0, is_rel=True), group="friction"),
                "curiosity": metric("to mo", max(float(get_val(state, "curiosity", 0.0)), float(get_val(state, "curiosity_pressure", 0.0))), group="attention"),
                "attention_bias": {
                    "label": "thien huong chu y",
                    "value": str(getattr(brief, "discourse_relation", "") or value(state, "last_focus_kind", "") or ""),
                    "group": "attention",
                    "note": "",
                },
                "association_pressure": metric("lien tuong lan rong", get_val(state, "association_pressure", 0.0), group="attention"),
                "thought_stream_pressure": metric("dong suy nghi tang", get_val(state, "thought_stream_pressure", 0.0), group="attention"),
                "speech_pressure": metric("ap luc phai noi", get_val(state, "silence_pressure", 0.0), group="speech"),
                "social_pressure": metric("ap luc xa hoi", get_val(state, "social_pressure", 0.0), group="speech"),
                "forced_reply": metric("bi ep phan hoi", forced_reply, group="speech"),
                "brevity": metric("xu huong noi ngan", get_val(state, "restraint_pressure", 0.0), group="speech"),
                "playfulness": metric("muc dua", get_val(state, "playful_pressure", 0.0), group="tone"),
                "tease": metric("thich treu", get_val(style, "sarcasm_level", 0.0), group="tone"),
                "sarcasm": metric("mia mai", get_val(style, "sarcasm_level", 0.0), group="tone"),
                "warmth": metric("do am ap", get_val(style, "warmth_level", value(appraisal, "tenderness", 0.0)), group="tone"),
                "distance": metric("giu khoang cach", get_val(relationship, "preferred_distance", 0.58, is_rel=True), group="tone"),
                "intimacy": metric("muc than mat", get_val(appraisal, "intimacy", 0.0), group="tone"),
                "romantic_boundary_probe": metric("do ranh gioi tinh cam", get_val(desire, "unresolved_residue", 0.0), group="tone"),
                "restraint": metric("tu kiem che", get_val(state, "restraint_pressure", 0.0), group="control"),
                "cognitive_tension": metric("cang thang nhan thuc", get_val(state, "cognitive_tension", 0.0), group="control"),
                "repeating_thought": metric("suy nghi lap lai", get_val(state, "recursive_reactivation_pressure", 0.0), group="control"),
                "unresolved_prediction": metric("du doan chua giai quyet", get_val(state, "unresolved_prediction_pressure", 0.0), group="control"),
                "subconscious_pressure": metric("ap luc tiem thuc", get_val(state, "subconscious_pressure", 0.0), group="control"),
                "fatigue": metric("met", get_val(appraisal, "fatigue", value(state, "fatigue", 0.0)), group="load"),
                "overload": metric("qua tai", overload, group="load"),
                "speech_emotional_color": {
                    "label": "mau cam xuc khi noi",
                    "value": str(getattr(brief, "delivery", "") or value(style, "last_tone_label", "") or ""),
                    "group": "surface",
                    "note": "",
                },
                "emotional_reflex": {
                    "label": "phan xa cam xuc",
                    "value": str(getattr(brief, "user_posture", "") or ""),
                    "group": "surface",
                    "note": "",
                },
                "emotional_residue": {
                    "label": "du am cam xuc",
                    "value": str(getattr(brief, "ambiguity_owner", "") or ""),
                    "group": "surface",
                    "note": "",
                },
                "surface_intent": {
                    "label": "y dinh bieu hien ra ngoai",
                    "value": surface_intent,
                    "group": "surface",
                    "note": "",
                },
            },
        }

    @staticmethod
    def _body_bias_clamp(value: object) -> float:
        return BodyBiasProjector.clamp(value)

    @staticmethod
    def _normalize_body_focus_kind(value: str) -> str:
        return BodyBiasProjector.normalize_focus_kind(value)

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
        event_strength = max(
            (max(0.0, min(1.0, float(getattr(item, "intensity", 0.0) or 0.0))) for item in tuple(disturbances or ())),
            default=0.0,
        )
        try:
            internal_state = self._get_internal_state()
        except Exception:
            internal_state = None
        if internal_state is not None and snapshot is not None:
            self._maybe_tick_subconscious_runtime(
                channel=channel,
                snapshot=snapshot,
                internal_state=internal_state,
                user_text=user_text,
                event_text=user_text,
                vision_facts=vision_facts,
                event_strength=event_strength,
                allow_lane5=True,
                reflection=False,
            )
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
        runtime = getattr(self, "subconscious_runtime", None)
        if runtime is not None and self.subconscious_runtime_enabled:
            return runtime.latest_report()
        return self._pop_thought_stream_report_for_autonomous()

    #Lưu trạng thái bộ nhớ sau mỗi chu kỳ, nếu bộ nhớ có hỗ trợ.
    def _save_memory_state(self) -> None:
        if self.memory_state is None:
            return
        saver = getattr(self.memory_core, "save", None)
        if not callable(saver):
            return
        try:
            saver(self.memory_state)
        except Exception as exc:
            self.logger.warning("Memory state save error: %s", exc)

    #Truy vấn bộ nhớ dài hạn để lấy các thông tin đã ghi nhớ trước đó, nếu bộ nhớ có hỗ trợ.
    def _memory_recall_texts(self, *, snapshot=None) -> list[str]:
        recall = getattr(self.memory_core, "recall", None)
        if callable(recall):
            try:
                query = self._memory_query_from_snapshot(snapshot)
                packet = recall(query)
                texts: list[str] = []
                for name in ("repair", "procedural", "semantic", "relational", "affective_residue", "episodic"):
                    texts.extend(str(item) for item in getattr(packet, name, ()) or ())
                # Tri thức đã học từ gia sư (tag 'tutor') được dán nhãn rõ và đưa lên
                # đầu để LLM thấy điều ERIS đã học — đường học -> hành vi THẬT, không
                # chỉ nằm trong shadow prediction.
                learned = self._recall_learned_knowledge(snapshot)
                if learned:
                    texts = learned + texts
                return texts
            except Exception as exc:
                self.logger.warning("Memory recall error: %s", exc)
        return list(getattr(self, "long_term_memory", []) or []) #nếu không có bộ nhớ cấu trúc hoặc truy vấn lỗi, thì fallback về long_term_memory đã lưu ở coordinator, vốn được cập nhật sau mỗi chu kỳ

    def _recall_learned_knowledge(self, snapshot=None) -> list[str]:
        """Lấy claim đã học từ gia sư liên quan ngữ cảnh hiện tại, dán nhãn [đã học]."""
        provider = getattr(self, "tutor_knowledge_provider", None)
        if provider is None or not callable(getattr(provider, "learned_claims", None)):
            return []
        try:
            query = self._memory_query_from_snapshot(snapshot)
            claims = provider.learned_claims(query, limit=2)
        except Exception:
            return []
        return [f"[đã học] {c}" for c in claims if str(c or "").strip()]

    def _activate_memory_resonance(
        self,
        *,
        snapshot=None,
        user_text: str = "",
        channel: str = "",
        fragments: tuple[str, ...] = (),
    ):
        recall = getattr(self.memory_core, "recall", None)
        if not callable(recall):
            self.active_memory_resonance = None
            return None
        try:
            query = " ".join(
                str(item)
                for item in (channel, user_text, *tuple(fragments or ()), self._memory_query_from_snapshot(snapshot))
                if str(item or "").strip()
            )
            report = recall(query)
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

    def _norm_deviation_texts(self, snapshot) -> tuple[str, ...]:
        return ()

    #Ghi nhận snapshot hiện tại vào bộ nhớ để cập nhật chuẩn, nếu bộ nhớ có hỗ trợ. Điều này nên được gọi sau khi đã quyết định xong broadcast và action plan, để tránh việc chuẩn bị bị ảnh hưởng bởi những thay đổi trong chu kỳ hiện tại.
    def _note_norm_observation(self, snapshot) -> None:
        return

    #Ghi nhận một chu kỳ hoàn chỉnh vào bộ nhớ, bao gồm những gì đã thấy (seen), đã nói (said), kết quả (outcome), và các tag liên quan. Điều này giúp xây dựng bộ nhớ dài hạn dựa trên trải nghiệm thực tế của ERIS, và có thể được sử dụng để cải thiện các quyết định trong tương lai.
    @staticmethod
    def _bounded_float(value: object, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = minimum
        if number != number:
            number = minimum
        return max(minimum, min(maximum, number))

    def _event_timestamp(self, snapshot, *, started_at: float | None = None) -> str:
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
        observer_frame: ObserverFrame | None = None,
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

        if observer_frame is not None:
            observer_content = self._observer_percept_content(observer_frame)
            if observer_content:
                add(
                    "background_observer",
                    observer_content,
                    source="observer",
                    confidence=max(0.35, self._bounded_float(getattr(observer_frame, "confidence", 0.0))),
                    evidence=self._observer_attention_tags(observer_frame, channel=channel),
                    privacy_level=str(getattr(observer_frame, "privacy_level", "normal") or "normal"),
                    novelty_hint=str(getattr(observer_frame, "recommended_action", "observe_only") or "observe_only"),
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




















    def _micro_policy_anchor_hints(self, *, broadcast=None, snapshot=None) -> tuple[str, str]:
        user_action = ""
        session_context = ""
        if broadcast is not None:
            for item in (broadcast, *tuple(getattr(broadcast, "items", ()) or ())):
                label = str(getattr(item, "label", "") or "").strip().lower()
                content = str(getattr(item, "content", "") or "").strip()
                if not content:
                    continue
                if not user_action and label in {"user_action", "action_context", "recent_event"}:
                    user_action = content
                if not session_context and label in {"focus_context", "session_context", "active_window", "focus_summary"}:
                    session_context = content
        if snapshot is not None:
            if not user_action:
                recent_events = tuple(
                    str(item or "").strip().replace("_", " ")
                    for item in (getattr(snapshot, "recent_events", ()) or ())
                    if str(item or "").strip()
                )
                user_action = next((item for item in recent_events if item), "")
            if not session_context:
                session_context = str(
                    getattr(snapshot, "focus_summary", "")
                    or getattr(snapshot, "active_window", "")
                    or getattr(snapshot, "active_app", "")
                    or getattr(snapshot, "active_window_kind", "")
                    or ""
                ).strip()
        return user_action, session_context

    def _build_relational_context(self, state: PersistentInternalState | None = None) -> RelationalContext:
        state = state or self._get_internal_state()
        recent_notes = " ".join(str(item or "") for item in tuple(getattr(state, "recent_notes", ()) or ())).lower()
        mental_processes = getattr(state, "mental_processes", None)
        continuity_process = getattr(mental_processes, "continuity", None)
        session_return = min(1.0, max(0, int(getattr(state, "session_resume_count", 0) or 0)) / 2.0)
        ritual_return = 1.0 if float(getattr(state, "last_session_ritual_at", 0.0) or 0.0) > 0.0 else 0.0
        memory_continuity = max(
            float(getattr(state, "recursive_reactivation_pressure", 0.0) or 0.0),
            float(getattr(state, "memory_replay_pressure", 0.0) or 0.0),
            float(getattr(state, "last_memory_resonance", 0.0) or 0.0),
            float(getattr(continuity_process, "level", 0.0) or 0.0),
        )
        ritual_note = 1.0 if any(
            marker in recent_notes
            for marker in ("session_ritual", "continuity_restored", "long_silence_return", "memory_replay", "recursive")
        ) else 0.0
        recent_channels = tuple(str(item or "") for item in tuple(getattr(state, "recent_channels", ()) or ()))
        long_silence_return = 1.0 if (
            float(getattr(state, "last_elapsed_seconds", 0.0) or 0.0) >= 600.0
            and any(item in {"chat", "force_speak"} for item in recent_channels[-4:])
        ) else 0.0
        sustained_presence = min(
            1.0,
            (
                float(getattr(state, "last_social_presence_confidence", 0.0) or 0.0)
                + float(getattr(state, "last_social_presence_intensity", 0.0) or 0.0)
            )
            * 0.5,
        )
        continuity_score = min(
            1.0,
            session_return * 0.28
            + ritual_return * 0.18
            + memory_continuity * 0.34
            + ritual_note * 0.12
            + long_silence_return * 0.10
            + sustained_presence * 0.08,
        )
        attachment = float(getattr(state, "attachment", 0.0) or 0.0)
        if continuity_score >= 0.66 and attachment >= 0.62:
            stage = "rooted"
        elif continuity_score >= 0.52 and attachment >= 0.50:
            stage = "established"
        elif continuity_score >= 0.38:
            stage = "forming"
        else:
            stage = "low_context"
        return RelationalContext(
            attachment_level=attachment,
            continuity_score=continuity_score,
            social_resonance=float(getattr(state, "social_energy", 0.0) or 0.0),
            recent_presence_density=sustained_presence,
            abandonment_sensitivity=max(
                float(getattr(state, "silence_pressure", 0.0) or 0.0),
                float(getattr(getattr(state, "desire", None), "unresolved_residue", 0.0) or 0.0),
            ),
            trust_stability=max(
                0.0,
                min(1.0, float(getattr(state, "confidence", 0.0) or 0.0) - float(getattr(state, "irritation", 0.0) or 0.0) * 0.35),
            ),
            relationship_stage=stage,
        )


    def _looks_like_light_tutor_research_request(self, text: str) -> bool:
        try:
            from runtime.tutor_research_policy import score_research_need
            return bool(score_research_need(text, intent="world_knowledge", meaning_missing=False).should_delegate)
        except Exception:
            normalized = self._normalize_marker_text(text)
            return any(cue in normalized for cue in self._LIGHT_TUTOR_RESEARCH_CUES)

    def _is_tutor_research_delegation_only(self, text: str) -> bool:
        normalized = self._normalize_marker_text(text)
        if not normalized:
            return False
        try:
            from runtime.tutor_research_policy import is_explicit_research_request
            explicit = is_explicit_research_request(text)
        except Exception:
            explicit = any(cue in normalized for cue in self._LIGHT_TUTOR_RESEARCH_CUES)
        if not explicit:
            return False
        tokens = [tok for tok in normalized.split() if tok not in {"di", "nhe", "nha", "giup", "dum", "cho", "toi", "em", "hay"}]
        content = [tok for tok in tokens if tok not in {"nghien", "cuu", "dao", "sau", "search", "web", "gemini", "tutor", "fix", "elegant", "kiem", "chung"}]
        return len(content) <= 1

    def _strip_light_tutor_command(self, text: str) -> str:
        value = str(text or "").strip()
        normalized = self._normalize_marker_text(value)
        for phrase in ("gemini hãy search web nghiên cứu cho tôi về", "gemini hay search web nghien cuu cho toi ve", "nghiên cứu sâu", "nghien cuu sau", "hỏi sư phụ gemini", "hoi su phu gemini", "hỏi gemini", "hoi gemini"):
            norm_phrase = self._normalize_marker_text(phrase)
            if normalized.startswith(norm_phrase):
                return value[len(phrase):].strip(" :,-–—") or value
        return value

    def _topic_is_referent_only(self, text: str) -> bool:
        normalized = self._normalize_marker_text(text)
        if not normalized:
            return True
        return any(marker in normalized for marker in self._LIGHT_TUTOR_REFERENT_ONLY) and len(normalized.split()) <= 6

    def _build_light_tutor_research_prompt(self, topic: str, *, context: str = "") -> str:
        try:
            from runtime.tutor_research_policy import build_lightweight_research_prompt
            prompt = build_lightweight_research_prompt(topic, context=context)
            if "Hãy tìm hiểu kỹ" not in prompt:
                prompt = prompt.replace("Hãy dùng tìm kiếm web nếu cần để kiểm tra", "Hãy tìm hiểu kỹ và dùng tìm kiếm web nếu cần để kiểm tra", 1)
            if "tối đa 6 ý" not in prompt:
                prompt = prompt.replace("Trả lời tiếng Việt cô đọng,", "Trả lời tiếng Việt cô đọng, tối đa 6 ý,", 1)
            if "Không chain-of-thought" not in prompt:
                prompt = prompt.replace("Câu hỏi:", "Không chain-of-thought. Câu hỏi:", 1)
            return prompt[:395].rstrip()
        except Exception:
            return str(topic or "")[:395]

    def _is_tutor_delegation_only(self, text: str) -> bool:
        normalized = self._normalize_marker_text(text)
        if not normalized:
            return False
        markers = (
            "hoi su phu gemini", "hoi su phu", "hoi gemini", "nho gemini",
            "keu gemini", "tra gemini", "ask gemini", "ask your tutor",
        )
        stripped = normalized
        for token in ("di", "dum", "giup", "cho toi", "cho ban", "thu", "xem"):
            stripped = re.sub(rf"\b{re.escape(token)}\b", " ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return any(stripped == marker or stripped.startswith(marker + " ") for marker in markers) and len(stripped.split()) <= 6

    def _resolve_tutor_research_topic(self, current_text: str) -> str:
        """Resolve follow-up nghiên cứu bằng heuristic rẻ, không gọi thêm model."""

        candidates: list[str] = []
        previous = str(getattr(self, "last_user_text_for_semantics", "") or "").strip()
        if previous:
            candidates.append(previous)
        try:
            turns = self._ensure_session_turn_ledger().user_turns()
            candidates.extend(str(turn.text or "").strip() for turn in turns[-8:])
        except Exception:
            pass
        try:
            from runtime.tutor_research_policy import resolve_research_anchor
            resolution = resolve_research_anchor(current_text, candidates)
            self._last_tutor_anchor_resolution = {
                "topic": str(getattr(resolution, "topic", "") or "")[:900],
                "confidence": float(getattr(resolution, "confidence", 0.0) or 0.0),
                "anchor_text": str(getattr(resolution, "anchor_text", "") or "")[:900],
                "anchor_index": int(getattr(resolution, "anchor_index", -1) or -1),
                "assumption_note": str(getattr(resolution, "assumption_note", "") or ""),
                "misread_risk": str(getattr(resolution, "misread_risk", "") or ""),
            }
            return str(getattr(resolution, "topic", "") or "")
        except Exception:
            # Fallback cũ: ít thông minh hơn nhưng vẫn không ném vào chat hot path.
            current_norm = self._normalize_marker_text(current_text)
            for candidate in reversed(candidates):
                if not candidate or self._normalize_marker_text(candidate) == current_norm:
                    continue
                if self._is_tutor_delegation_only(candidate):
                    continue
                self._last_tutor_anchor_resolution = {
                    "topic": candidate[:900],
                    "confidence": 0.52,
                    "anchor_text": candidate[:900],
                    "anchor_index": -1,
                    "assumption_note": "fallback_recent_context",
                    "misread_risk": "medium",
                }
                return candidate
            self._last_tutor_anchor_resolution = {"topic": "", "confidence": 0.0, "misread_risk": "high"}
            return ""

    def _maybe_tutor_on_unclear_user(self, user_text, frame) -> None:
        """Khi Eris không hiểu/không phân loại nổi tin user → định tuyến.

        NGUYÊN TẮC: mặc định TỰ HỌC (hỏi Gemini âm thầm) — bạn KHÔNG phải giải thích
        kiến thức chung (vd "INTP 538", "Rust", tên phim). Chỉ HỎI LẠI BẠN khi đó là
        tham chiếu CÁ NHÂN mơ hồ mà Gemini không thể biết ("vụ đó hôm qua", "ý m là sao").

        - hỏi Gemini: chạy nền, im lặng, có throttle (Eris vẫn trả lời tự nhiên lượt này,
          học để lần sau hiểu hơn).
        - hỏi lại bạn: câu trả lời lượt này thành câu làm rõ ngắn (giọng Eris).
        No-op khi Master_Switch tắt.
        """

        self._clarify_user_pending = False
        self._research_pending = False
        self._research_topic = ""
        daemon = getattr(self, "tutor_daemon", None)
        if daemon is None:
            return
        try:
            text = str(user_text or "").strip()
            mark_stale = getattr(self, "_mark_active_research_stale_if_user_changed", None)
            if callable(mark_stale):
                mark_stale(text)
            words = text.split()
            meaning = ""
            ml = getattr(frame, "meaning_layer", None)
            if ml is not None:
                meaning = str(getattr(ml, "meaning", "") or "")
            intent = str(getattr(self, "last_user_intent", "") or "").strip().lower()
            unclear = (not meaning) or intent in ("", "unknown", "unclear", "other")

            # Route Tutor nhẹ: explicit research thì đào sâu vừa đủ; explicit search /
            # dữ kiện mới thì search nhanh. Câu kiến thức phổ thông vẫn để Terra trả lời,
            # vì gọi thêm Tutor cho "Pytest là gì" là cách biến điện thành tiếng thở dài.
            try:
                from runtime.tutor_research_policy import score_tutor_delegation
                tutor_decision = score_tutor_delegation(
                    text,
                    intent=intent,
                    meaning_missing=not bool(meaning),
                )
            except Exception:
                tutor_decision = SimpleNamespace(should_delegate=False, score=0.0, reason="policy_error", mode="none")

            if bool(getattr(tutor_decision, "should_delegate", False)) and callable(
                getattr(self, "request_tutor_answer", None)
            ):
                topic = self._resolve_tutor_research_topic(text)
                if topic and self._research_can_start():
                    mode = str(getattr(tutor_decision, "mode", "research") or "research")
                    anchor_meta = dict(getattr(self, "_last_tutor_anchor_resolution", {}) or {})
                    # Low-confidence anchor: hỏi lại trước, đừng search nhầm rồi
                    # đem kết quả đúng của câu sai về khoe. Máy móc cũng nên biết xấu hổ.
                    try:
                        from runtime.tutor_research_policy import anchor_resolution_needs_clarification
                        runtime_float = getattr(self, "_tutor_runtime_float", None)
                        floor = runtime_float("tutor", "low_confidence_clarify_threshold", default=0.55) if callable(runtime_float) else 0.55
                        probe = SimpleNamespace(**anchor_meta)
                        if anchor_resolution_needs_clarification(probe, confidence_floor=floor):
                            self._clarify_user_pending = True
                            self._research_pending = False
                            self._research_topic = ""
                            return
                    except Exception:
                        pass
                    self._research_pending = True
                    self._research_topic = topic
                    anchor_note = (
                        f"anchor_conf={anchor_meta.get('confidence', 0):.2f}; "
                        f"anchor_risk={anchor_meta.get('misread_risk', '')}; "
                        f"assumption={anchor_meta.get('assumption_note', '')}; "
                    ) if anchor_meta else ""
                    if mode == "quick_search":
                        context = (
                            "Search nhanh qua Tutor web; trả lời cô đọng, ưu tiên nguồn/link nếu có. "
                            f"route={getattr(tutor_decision, 'reason', '')}; "
                            f"{anchor_note}"
                            "không dùng Deep Research API hoặc Google grounding"
                        )
                    else:
                        context = (
                            "Tra cứu nhẹ qua Tutor web; trả lời cô đọng, ưu tiên nguồn chính. "
                            f"route={getattr(tutor_decision, 'reason', '')}; "
                            f"{anchor_note}"
                            "không dùng Deep Research API hoặc Google grounding"
                        )
                    try:
                        self._fire_research_followup(topic, context=context, mode=mode)
                    except TypeError:
                        # Test doubles/legacy runtime chưa nhận mode; giữ tương thích.
                        self._fire_research_followup(topic, context=context)
                    return

            # Tin nhắn quá ngắn và không có cue nghiên cứu thì không đáng mở Tutor.
            if len(words) < 3:
                return

            low = text.lower()
            # Tham chiếu cá nhân/mơ hồ — chỉ bạn giải đáp được → hỏi lại bạn.
            personal_markers = (
                "vụ đó", "vụ này", "cái đó", "cái này", "cái kia", "cái nớ", "hôm qua",
                "lúc nãy", "khi nãy", "hồi nãy", "bữa đó", "như thế", "như vậy",
                "ý m là sao", "ý mày là sao", "ý em là sao", "ý là sao", "sao cơ", "hả?",
            )
            is_personal_ambiguous = (len(words) <= 6 and any(m in low for m in personal_markers))

            if is_personal_ambiguous:
                # Không hiểu bạn ám chỉ gì → hỏi lại bạn ngay trong câu trả lời lượt này.
                self._clarify_user_pending = True
                return

            # Mặc định: tự học qua Gemini (âm thầm, throttle). Eris vẫn trả lời tự nhiên.
            if not unclear:
                return
            self._fire_tutor_lookup(text, context="Khái niệm trong tin nhắn Eris chưa rõ")
        except Exception as exc:
            try:
                self.logger.warning("Curiosity Tutor on-unclear error: %s", exc)
            except Exception:
                pass

    def _fire_tutor_lookup(self, topic: str, *, context: str = "") -> None:
        """Bắn một lượt hỏi Gemini ở thread nền (có throttle). Không chặn trả lời chat."""

        daemon = getattr(self, "tutor_daemon", None)
        lookup = getattr(self, "request_tutor_lookup", None)
        if daemon is None or not callable(lookup):
            return
        now = time.time()
        last = float(getattr(self, "_last_unclear_tutor_ts", 0.0) or 0.0)
        cooldown = float(getattr(getattr(daemon, "config", None), "min_seconds_between_episodes", 120.0) or 120.0)
        if now - last < cooldown:
            return
        self._last_unclear_tutor_ts = now

        def _bg():
            try:
                ok = lookup(topic, context=context, kind_hint="ask_gemini", stake=0.7)
                if not ok:
                    self.logger.info("[tutor lookup] no_episode topic=%r context=%r", str(topic)[:120], str(context)[:120])
            except Exception as exc:
                self.logger.warning("[tutor lookup] background error: %s", exc)

        threading.Thread(target=_bg, name="ERIS-TutorOnUnclear", daemon=True).start()

    # Nhãn câu hỏi kiến thức thế giới — bộ đánh dấu thiên về sự thật/khái niệm, cố ý
    # KHÔNG bắt câu xã giao ("dạo này thế nào", "khỏe không") hay câu về chính bạn.
    _KNOWLEDGE_QUESTION_MARKERS = (
        "hỏi gemini", "hoi gemini", "hỏi sư phụ", "hoi su phu", "nhờ gemini",
        "nho gemini", "kêu gemini", "keu gemini", "tra gemini",
        "là gì", "là ai", "là con gì", "là cái gì", "là chất gì", "là nước nào",
        "là bệnh gì", "là môn gì", "là ngôn ngữ gì", "nghĩa là gì", "viết tắt của",
        "tại sao", "vì sao", "do đâu", "nguyên nhân",
        "ở đâu", "khi nào", "năm nào", "thế kỷ", "ai phát minh", "ai sáng",
        "ai là người", "khác nhau", "khác gì", "so với", "có tác dụng gì",
        "hoạt động như thế nào", "hoạt động ra sao", "định nghĩa",
    )

    def _looks_like_knowledge_question(self, low: str) -> bool:
        """Legacy diagnostic only. Tutor user-facing phải gate bằng intent world_knowledge."""

        low = str(low or "")
        return any(marker in low for marker in self._KNOWLEDGE_QUESTION_MARKERS)

    def _tutor_runtime_bool(self, *path: str, default: bool = True) -> bool:
        try:
            from runtime.runtime_settings_store import runtime_bool
            return bool(runtime_bool(*path, default=default))
        except Exception:
            return bool(default)

    def _tutor_runtime_float(self, *path: str, default: float = 0.0) -> float:
        try:
            from runtime.runtime_settings_store import runtime_float
            return float(runtime_float(*path, default=default))
        except Exception:
            return float(default)

    def _mark_active_research_stale_if_user_changed(self, user_text: str) -> None:
        """Nếu user đổi chủ đề trong lúc Tutor chạy, đánh dấu job cũ là stale."""

        if not getattr(self, "_research_in_flight", False):
            return
        if not self._tutor_runtime_bool("tutor", "stale_result_guard_enabled", default=True):
            return
        active = getattr(self, "_active_research_job", None)
        if not isinstance(active, dict):
            return
        topic = str(active.get("topic", "") or "")
        incoming = str(user_text or "").strip()
        if not incoming or not topic:
            return
        try:
            from runtime.tutor_search_jobs import looks_same_topic
            same = looks_same_topic(incoming, topic)
        except Exception:
            same = incoming.lower().strip() in topic.lower() or topic.lower().strip() in incoming.lower()
        if same:
            return
        active["stale"] = True
        active["stale_reason"] = "user_changed_topic"
        active["stale_user_text"] = incoming[:180]
        self._active_research_job = active
        try:
            self.logger.info("[tutor research] marked stale job=%s reason=user_changed_topic topic=%r new=%r", active.get("job_id"), topic[:80], incoming[:80])
        except Exception:
            pass

    def _research_can_start(self) -> bool:
        """Debounce nhịp tra cứu: không tra khi đang có lượt tra chạy, và cách nhau tối thiểu."""

        runtime_bool = getattr(self, "_tutor_runtime_bool", None)
        if callable(runtime_bool) and not runtime_bool("tutor", "enabled", default=True):
            return False
        if getattr(self, "_research_in_flight", False):
            return False
        now = time.time()
        last = float(getattr(self, "_last_research_ts", 0.0) or 0.0)
        if now - last < 6.0:
            return False
        return True

    def _maybe_start_self_declared_tutor_search(self, decision: Decision, *, user_text: str, frame=None) -> Decision:
        """Nếu Eris tự nói "đợi em tra", biến lời hứa đó thành hành động thật.

        Đây là lớp tự do có kiểm soát: pre-detector có thể lọt câu hỏi lái, nhưng
        main brain vẫn được phép tự nhận ra cần search. Khi nó surface lời hứa
        search/kiểm tra, runtime spawn Tutor ở nền và thay câu lượt này bằng
        nhịp chờ ngắn, không để nó vừa hứa tra vừa đoán luôn. Rất tiếc cho thói
        quen bịa tự tin, nó không qua cửa này.
        """

        try:
            if decision is None:
                return decision
            # Nếu prepass đã route Tutor rồi thì không spawn lần hai.
            already_delegated = bool(
                getattr(self, "_research_pending", False)
                or getattr(self, "_research_in_flight", False)
            )
            from runtime.tutor_self_search_bridge import (
                build_self_search_wait_text,
                detect_self_search_request,
            )

            self_search_decision = detect_self_search_request(
                user_text,
                getattr(decision, "text", ""),
                already_delegated=already_delegated,
            )
            if not bool(getattr(self_search_decision, "should_start", False)):
                return decision
            runtime_bool = getattr(self, "_tutor_runtime_bool", None)
            if callable(runtime_bool) and not runtime_bool("tutor", "self_search_enabled", default=True):
                return decision
            if not callable(getattr(self, "request_tutor_answer", None)):
                return decision
            if not self._research_can_start():
                return decision

            topic = self._resolve_tutor_research_topic(user_text)
            if not topic:
                return decision
            anchor_meta = dict(getattr(self, "_last_tutor_anchor_resolution", {}) or {})
            try:
                from runtime.tutor_research_policy import anchor_resolution_needs_clarification
                runtime_float = getattr(self, "_tutor_runtime_float", None)
                floor = runtime_float("tutor", "low_confidence_clarify_threshold", default=0.55) if callable(runtime_float) else 0.55
                if anchor_resolution_needs_clarification(SimpleNamespace(**anchor_meta), confidence_floor=floor):
                    decision.text = "Tôi biết vụ này cần tra, nhưng neo hiện tại hơi mù. Bạn chỉ rõ tôi đang tra phần nào đã, kẻo tôi lại search nhầm như một cái GPS bị xúc phạm."
                    decision.action = "tutor_anchor_clarify"
                    decision.should_speak = True
                    decision.confidence = min(float(getattr(decision, "confidence", 0.72) or 0.72), 0.55)
                    return decision
            except Exception:
                pass
            mode = str(getattr(self_search_decision, "mode", "quick_search") or "quick_search")
            if mode not in {"quick_search", "research"}:
                mode = "quick_search"

            self._research_pending = True
            self._research_topic = topic
            anchor_note = (
                f"anchor_conf={anchor_meta.get('confidence', 0):.2f}; "
                f"anchor_risk={anchor_meta.get('misread_risk', '')}; "
                f"assumption={anchor_meta.get('assumption_note', '')}; "
            ) if anchor_meta else ""
            context = (
                "Eris tự nhận ra câu này cần tra cứu sau khi pre-detector không bắt được; "
                f"route={getattr(self_search_decision, 'reason', '')}; "
                f"{anchor_note}"
                "dùng Tutor/Gemini Web hiện có, trả lời cô đọng, ưu tiên nguồn/link; "
                "không dùng Deep Research API hoặc Google grounding"
            )
            self._fire_research_followup(topic, context=context, mode=mode)

            decision.text = build_self_search_wait_text(mode=mode, topic=topic)
            decision.intent = "world_knowledge"
            decision.action = "tutor_self_search_wait"
            decision.should_speak = True
            decision.confidence = min(float(getattr(decision, "confidence", 0.72) or 0.72), 0.72)
            decision.reasoning_tags = tuple(dict.fromkeys((
                *tuple(getattr(decision, "reasoning_tags", ()) or ()),
                "tutor_self_declared_wait",
                "quick_search" if mode == "quick_search" else "research_followup",
            )))
            decision.debug_trace = self._join_debug_trace(
                getattr(decision, "debug_trace", ""),
                f"self_declared_tutor_search:{mode}:{getattr(self_search_decision, 'reason', '')}",
            )
            try:
                if frame is not None:
                    frame.debug_notes.append(
                        f"self_declared_tutor_search={mode}:{getattr(self_search_decision, 'reason', '')}"
                    )
            except Exception:
                pass
            return decision
        except Exception as exc:
            try:
                self.logger.warning("[tutor self-search] bridge error: %s", exc)
            except Exception:
                pass
            return decision

    def _fire_research_followup(self, topic: str, *, context: str = "", mode: str = "research") -> None:
        """Nhịp 2: thread nền đi hỏi gia sư rồi gửi đáp án về (không chặn trả lời lượt này)."""

        answerer = getattr(self, "request_tutor_answer", None)
        if not callable(answerer):
            return
        self._last_research_ts = time.time()
        self._research_in_flight = True
        try:
            from runtime.tutor_search_jobs import make_tutor_search_job
            seq = int(getattr(self, "_research_job_seq", 0) or 0) + 1
            self._research_job_seq = seq
            job = make_tutor_search_job(topic, mode=mode, seq=seq, user_turn_id=str(getattr(self, "current_user_turn_id", "") or ""))
            self._active_research_job = {**job.to_dict(), "topic": str(topic or ""), "stale": False}
        except Exception:
            job = SimpleNamespace(job_id=f"research_{int(time.time() * 1000)}", topic_hash="", mode=mode)
            self._active_research_job = {"job_id": job.job_id, "topic": str(topic or ""), "stale": False, "mode": str(mode or "research")}

        def _bg():
            answer = None
            try:
                # Để nhịp 1 ("đợi em tra chút") kịp ra trước câu trả lời.
                time.sleep(1.5)
                try:
                    if str(mode or "research") == "quick_search":
                        answer = answerer(topic, context=context, search=True)
                    else:
                        answer = answerer(topic, context=context, research=True)
                except TypeError:
                    # Adapter cũ/test double chưa có cờ research vẫn chạy được.
                    answer = answerer(topic, context=context)
                if not answer:
                    self.logger.info("[tutor research] empty_answer topic=%r context=%r", str(topic)[:120], str(context)[:120])
            except Exception as exc:
                self.logger.warning("[tutor research] background error: %s", exc)
                answer = None
            finally:
                try:
                    self._deliver_research_followup(topic, answer, mode=mode, job_id=str(getattr(job, "job_id", "") or ""))
                except Exception as exc:
                    self.logger.warning("[tutor research] deliver error: %s", exc)
                active = getattr(self, "_active_research_job", None)
                if not isinstance(active, dict) or str(active.get("job_id", "")) == str(getattr(job, "job_id", "")):
                    self._research_in_flight = False
                    self._active_research_job = None

        threading.Thread(target=_bg, name="ERIS-ResearchFollowup", daemon=True).start()

    def _deliver_research_followup(self, topic: str, answer, *, mode: str = "research", job_id: str = "") -> None:
        """Gửi câu trả lời nhịp 2 ra body bằng giọng Eris (qua đường decision chuẩn)."""

        active = getattr(self, "_active_research_job", None)
        runtime_bool = getattr(self, "_tutor_runtime_bool", None)
        stale_guard_enabled = runtime_bool("tutor", "stale_result_guard_enabled", default=True) if callable(runtime_bool) else True
        if stale_guard_enabled and isinstance(active, dict):
            if job_id and str(active.get("job_id", "")) != str(job_id):
                try:
                    self.logger.info("[tutor research] drop stale result job=%s active=%s", job_id, active.get("job_id"))
                except Exception:
                    pass
                return
            if bool(active.get("stale", False)):
                try:
                    self.logger.info("[tutor research] drop stale result job=%s reason=%s", job_id or active.get("job_id"), active.get("stale_reason", "stale"))
                except Exception:
                    pass
                return

        answer = str(answer or "").strip()
        if answer:
            if str(mode or "research") == "quick_search":
                lead = random.choice((
                    "Em search nhanh ra rồi nè. ",
                    "Rồi, em kiểm tra nhanh được thế này. ",
                    "Em vừa tra nhanh xong. ",
                ))
            else:
                lead = random.choice((
                    "Rồi, em tra xong rồi nha. ",
                    "Đây ạ, em vừa tra được: ",
                    "Em tra ra rồi nè. ",
                ))
            text = f"{lead}{answer}"
        else:
            text = random.choice((
                "Em lục một vòng mà chưa ra cái gì chắc chắn về vụ này. Em chưa dám nói bừa đâu.",
                "Hừm, vụ này em tra chưa tới nơi. Để em đào lại sau rồi nói bạn nghe.",
            ))
        artifact = {}
        research_thread = {}
        research_metrics = {}
        memory_decision = {}
        try:
            artifact = dict(getattr(self, "_last_tutor_research_artifact", {}) or {})
            research_thread = dict(getattr(self, "_last_tutor_research_thread", {}) or {})
            research_metrics = dict(getattr(self, "_last_tutor_research_metrics", {}) or {})
            memory_decision = dict(getattr(self, "_last_tutor_research_memory_decision", {}) or {})
        except Exception:
            artifact = {}
            research_thread = {}
            research_metrics = {}
            memory_decision = {}
        verification_status = ""
        try:
            verification_status = str((artifact.get("verification") or {}).get("overall_status") or "")
        except Exception:
            verification_status = ""
        decision = Decision(
            text=text,
            animation="stand",
            intent="world_knowledge",
            action="tutor_search_followup" if str(mode or "research") == "quick_search" else "tutor_followup",
            reasoning_tags=(
                "tutor_grounded",
                "quick_search" if str(mode or "research") == "quick_search" else "research_followup",
                f"verification:{verification_status}" if verification_status else "verification:unknown",
            ),
            should_speak=True,
            confidence=0.78 if answer else 0.35,
            parse_mode="chat",
            debug_trace=f"{str(mode or 'research')}_followup; topic={str(topic)[:120]}; verification={verification_status or 'unknown'}",
        )
        # Tutor follow-up dùng cùng public commit/stage transport. Wording không
        # đi qua legacy style guards; evidence bundle mới là authority.
        try:
            from actions.capability_registry import canonicalize_action_id
            decision.system_action = canonicalize_action_id(decision.system_action)
        except Exception:
            pass
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
            commit_surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(decision.text)
            public_text = commit_surfaces.display_text
            memory_text = commit_surfaces.memory_text
        except Exception:
            public_text = str(decision.text or "").strip()
            memory_text = public_text
        if public_text:
            if memory_text:
                self._append_chat_history("assistant", memory_text, invalid=False)
            ledger_meta = {
                "intent": decision.intent,
                "parse_mode": decision.parse_mode,
                "source": "tutor_followup",
                "research_mode": str(mode or "research"),
                "research_job_id": str(job_id or ""),
            }
            anchor_meta = dict(getattr(self, "_last_tutor_anchor_resolution", {}) or {})
            if anchor_meta:
                ledger_meta["anchor_resolution"] = anchor_meta
            if research_thread:
                ledger_meta["research_thread"] = research_thread
            if artifact:
                ledger_meta["evidence_bundle_id"] = str(artifact.get("bundle_id") or "")
                ledger_meta["verification"] = dict(artifact.get("verification") or {})
            if research_metrics:
                ledger_meta["research_metrics"] = research_metrics
            if memory_decision:
                ledger_meta["research_memory_policy"] = memory_decision
            self._ensure_session_turn_ledger().record_assistant(
                public_text,
                meta=ledger_meta,
            )
            self.last_chat_answer = public_text
        self._send_decision_to_body(decision, channel="chat")

    def stop(self):
        self.running = False
        worker = getattr(self, "screen_text_worker", None)
        if worker is not None:
            try:
                worker.stop()
            except Exception as exc:
                self.logger.warning("[screen text] stop error: %s", exc)
        self._stop_mental_process_loop()
        tutor_daemon = getattr(self, "tutor_daemon", None)
        if tutor_daemon is not None:
            try:
                tutor_daemon.stop()
            except Exception as exc:
                self.logger.warning("Curiosity Tutor stop error: %s", exc)
        if self.subconscious_runtime_enabled:
            try:
                snapshot = self.telemetry_service.capture_snapshot(
                    mood_score=self.mood_score,
                    inferred_pos_x=self.inferred_pos_x,
                )
                self._maybe_tick_subconscious_runtime(
                    channel="reflection",
                    snapshot=snapshot,
                    internal_state=self._get_internal_state(),
                    user_text="",
                    event_text="shutdown_reflection",
                    event_strength=0.22,
                    allow_lane5=True,
                    reflection=True,
                )
            except Exception as exc:
                self.logger.warning("Subconscious reflection tick error: %s", exc)
        self.cognitive_substrate.stop()
        runtime = getattr(self, "subconscious_runtime", None)
        if runtime is not None:
            try:
                runtime.stop()
            except Exception:
                pass
        try:
            from runtime.ai_orchestrated.bootstrap import shutdown_ai_orchestrated_runtime
            shutdown_ai_orchestrated_runtime(self)
        except Exception:
            pass
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
        if self.memory_state is None or getattr(self, "_chat_processing", False):
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
        axes = processes.process_axes()
        # Connection drive: cô độc tích thành thèm-kết-nối, đổ vào thanh "muốn nói".
        # Đây là drive nội sinh — lý do Eris đôi khi tự với ra dù không ai gọi. Mode
        # yan thì cô độc/ham muốn luôn thắng (sàn cao), thanh không bao giờ về 0.
        silence_target = axes["silence_pressure"]
        try:
            drive = getattr(self, "_connection_drive", None)
            if drive is None:
                drive = ConnectionDrive()
                self._connection_drive = drive
            drive_state = getattr(self, "_connection_drive_state", None) or ConnectionDriveState()
            try:
                from cortex.disposition import threat_level
                threat = float(threat_level(current))
            except Exception:
                threat = 0.0
            drive_state, drive_decision = drive.update(
                drive_state,
                now=time.time(),
                idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
                attachment=float(getattr(current, "attachment", 0.0) or 0.0),
                abandonment=float(getattr(current, "abandonment_pressure", 0.0) or 0.0),
                dread=float(getattr(current, "ontological_dread", 0.0) or 0.0),
                threat=threat,
                yan_mode=bool(getattr(self, "_debug_yan_mode", False)),
            )
            self._connection_drive_state = drive_state
            self._last_connection_drive = drive_decision
            silence_target = max(silence_target, drive_decision.pressure)
        except Exception as exc:
            self.logger.warning("ConnectionDrive tick error: %s", exc)
        # Appetite marketplace: các cơn thèm đi săn evidence màn hình/ký ức → chọn
        # LENS + SEED cho câu autonomous. Đây là nguồn random/bịa/khịa/níu "sống".
        try:
            appetites = getattr(self, "_appetite_system", None)
            if appetites is None:
                appetites = AppetiteSystem()
                self._appetite_system = appetites
                self._appetite_states = appetites.new_states()
            content_kind = ""
            try:
                from telemetry.content_metadata import _infer_page_kind
                content_kind = _infer_page_kind(
                    url=str(getattr(snapshot, "browser_url", "") or ""),
                    title=str(getattr(snapshot, "active_window", "") or ""),
                )
            except Exception:
                content_kind = ""
            evidence = build_evidence_buffet(
                content_kind=content_kind,
                content_title=str(getattr(snapshot, "active_window", "") or ""),
                vision_facts=tuple(str(x) for x in (getattr(snapshot, "vision_facts", ()) or ())),
                recent_events=tuple(str(x) for x in (getattr(snapshot, "recent_events", ()) or ())),
                active_window=str(getattr(snapshot, "active_app", "") or getattr(snapshot, "active_window", "") or ""),
                idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
                novelty=0.6,
            )
            lonely_sig = float(getattr(getattr(self, "_last_connection_drive", None), "pressure", 0.0) or 0.0)
            signals = {
                "curiosity": float(getattr(current, "curiosity_pressure", 0.0) or 0.0) or float(getattr(current, "curiosity", 0.0) or 0.0),
                "boredom": float(getattr(current, "boredom", 0.0) or 0.0),
                "loneliness": lonely_sig,
                "mischief": max(0.0, min(1.0, float(getattr(current, "boredom", 0.0) or 0.0) * 0.6 + 0.2)),
                "tenderness": float(getattr(current, "attachment", 0.0) or 0.0) * 0.5,
            }
            try:
                from cortex.disposition import threat_level as _threat_level
                appetite_threat = float(_threat_level(current))
            except Exception:
                appetite_threat = 0.0
            self._appetite_states, reaction = appetites.update(
                getattr(self, "_appetite_states", None) or appetites.new_states(),
                now=time.time(),
                signals=signals,
                evidence=evidence,
                threat=appetite_threat,
                yan_mode=bool(getattr(self, "_debug_yan_mode", False)),
            )
            self._last_appetite_reaction = reaction
        except Exception as exc:
            self.logger.warning("AppetiteSystem tick error: %s", exc)
        updated = replace(
            current,
            mental_processes=processes,
            curiosity=self._mix_axis(current.curiosity, axes["curiosity"], inertia=0.92),
            social_energy=self._mix_axis(current.social_energy, axes["social_energy"], inertia=0.92),
            attachment=self._mix_axis(current.attachment, axes["attachment"], inertia=0.96),
            fatigue=self._mix_axis(current.fatigue, axes["fatigue"], inertia=0.94),
            silence_pressure=self._mix_axis(current.silence_pressure, silence_target, inertia=0.88),
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
        self._maybe_tick_subconscious_background(snapshot=snapshot, internal_state=updated)
        return updated

    def _build_subconscious_runtime(self) -> RuntimeSubconsciousLoop | None:
        try:
            workers = build_phase1234567_workers(
                enable_mutation_commit=bool(
                    get_config(
                        "subconscious_runtime.lanes.lane5_deep_private_life.allow_mutation_commit",
                        default=False,
                    )
                ),
                allow_rupture_surface=bool(
                    get_config(
                        "subconscious_runtime.lanes.lane5_deep_private_life.allow_rupture_surface",
                        default=False,
                    )
                ),
            )
            return RuntimeSubconsciousLoop(workers=workers)
        except Exception as exc:
            self.logger.warning("Khong khoi tao duoc subconscious runtime: %s", exc)
            self.subconscious_runtime_enabled = False
            return None

    def _subconscious_frame_payload(
        self,
        *,
        snapshot,
        user_text: str,
        internal_state,
        channel: str,
        event_text: str = "",
        vision_facts: tuple[str, ...] = (),
    ) -> SimpleNamespace:
        evidence = tuple(str(item) for item in (*tuple(vision_facts or ()), *tuple(getattr(snapshot, "evidence", ()) or ())) if str(item).strip())[:8]
        disturbance = {"content": event_text} if event_text else None
        return SimpleNamespace(
            user_text=user_text,
            text=user_text,
            current_user_text=user_text,
            evidence=evidence,
            disturbance=disturbance,
            idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
            active_goal=str(self.active_conversational_topic or getattr(self, "last_user_intent", "") or ""),
            focus_family=str(getattr(snapshot, "active_window_kind", "") or ""),
            activity_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            outcome_history=tuple(str(item) for item in tuple(getattr(snapshot, "recent_events", ()) or ())[:6]),
            relation_history=tuple(str(item) for item in tuple(getattr(snapshot, "recent_events", ()) or ())[:6]),
            channel=channel,
        )

    def _subconscious_memory_packet(self, *, limit: int = 12) -> dict[str, tuple[str, ...]]:
        buckets: dict[str, list[str]] = {
            "semantic": [],
            "episodic": [],
            "relational": [],
            "affective_residue": [],
            "procedural": [],
            "open_questions": [],
            "repair": [],
        }

        def add(bucket: str, text: object) -> None:
            value = re.sub(r"\s+", " ", str(text or "")).strip()
            if not value:
                return
            store = buckets.setdefault(bucket, [])
            if value not in store:
                store.append(value[:500])

        for packet in self._daydream_packets_from_runtime(limit=limit):
            kind = str(getattr(packet, "kind", "") or "").strip().lower()
            text = getattr(packet, "text", "")
            if kind == "semantic":
                add("semantic", text)
            elif kind == "episodic":
                add("episodic", text)
            elif kind == "relational":
                add("relational", text)
            elif kind == "repair":
                add("repair", text)
            elif kind == "affective":
                add("affective_residue", text)
            elif kind == "procedural":
                add("procedural", text)
            else:
                add("open_questions", text)

        for text in tuple(getattr(self, "long_term_memory", ()) or ())[:limit]:
            add("semantic", text)

        resonance = getattr(self, "active_memory_resonance", None)
        for activation in tuple(getattr(resonance, "activations", ()) or ())[:6]:
            add("semantic", getattr(activation, "text", ""))

        return {key: tuple(values[:limit]) for key, values in buckets.items() if values}

    def _subconscious_pressure_metrics(self, *, internal_state, snapshot, event_strength: float) -> dict[str, float]:
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        idle_norm = max(0.0, min(1.0, idle_seconds / 300.0))
        drift_resonance = max(
            float(getattr(internal_state, "memory_replay_pressure", 0.0) or 0.0),
            float(getattr(internal_state, "association_pressure", 0.0) or 0.0),
            float(getattr(internal_state, "unresolved_prediction_pressure", 0.0) or 0.0),
            float(getattr(internal_state, "recursive_reactivation_pressure", 0.0) or 0.0),
        )
        self_anchor_pressure = max(
            float(getattr(internal_state, "subconscious_pressure", 0.0) or 0.0),
            float(getattr(internal_state, "thought_stream_pressure", 0.0) or 0.0),
            float(getattr(internal_state, "cognitive_tension", 0.0) or 0.0) * 0.85,
        )
        solitude_pressure = max(
            float(getattr(internal_state, "silence_pressure", 0.0) or 0.0),
            idle_norm,
            min(1.0, float(getattr(self, "presence_maintenance_silent_cycles", 0) or 0) / 8.0),
        )
        repair_need = float(getattr(internal_state, "repair_need", 0.0) or 0.0)
        rupture = float(getattr(internal_state, "rupture", 0.0) or 0.0)
        return {
            "event_strength": max(0.0, min(1.0, float(event_strength or 0.0))),
            "drift_resonance": max(0.0, min(1.0, drift_resonance)),
            "self_anchor_pressure": max(0.0, min(1.0, self_anchor_pressure)),
            "solitude_pressure": max(0.0, min(1.0, solitude_pressure)),
            "repair_need": max(0.0, min(1.0, repair_need)),
            "rupture": max(0.0, min(1.0, rupture)),
            "idle_seconds": idle_seconds,
        }

    def _subconscious_blackboard_metrics(self, *, now: float) -> dict[str, float]:
        runtime = getattr(self, "subconscious_runtime", None)
        if runtime is None:
            return {
                "fragment_count": 0.0,
                "coherence": 0.0,
                "pressure": 0.0,
                "recurring_theme_strength": 0.0,
                "unresolved_loop_pressure": 0.0,
                "contradiction_pressure": 0.0,
                "suppressed_recurrence": 0.0,
                "curiosity_gap_pressure": 0.0,
            }
        snapshot = runtime.blackboard.snapshot(now=now)
        fragments = tuple(getattr(snapshot, "fragments", ()) or ())
        if not fragments:
            return {
                "fragment_count": 0.0,
                "coherence": 0.0,
                "pressure": 0.0,
                "recurring_theme_strength": 0.0,
                "unresolved_loop_pressure": 0.0,
                "contradiction_pressure": 0.0,
                "suppressed_recurrence": 0.0,
                "curiosity_gap_pressure": 0.0,
            }

        groups: dict[str, int] = {}
        unique_evidence: set[str] = set()
        unresolved_pressure = 0.0
        contradiction_pressure = 0.0
        curiosity_gap_pressure = 0.0
        suppressed_weight = 0.0
        pressure = 0.0
        for fragment in fragments:
            key = str((fragment.tags[0] if getattr(fragment, "tags", ()) else getattr(fragment, "kind", "")) or getattr(fragment, "kind", "misc"))
            groups[key] = groups.get(key, 0) + 1
            unique_evidence.update(str(item) for item in tuple(getattr(fragment, "evidence_ids", ()) or ()) if str(item).strip())
            local_pressure = max(
                0.0,
                min(
                    1.0,
                    float(getattr(fragment, "urgency", 0.0) or 0.0) * 0.55
                    + float(getattr(fragment, "confidence", 0.0) or 0.0) * 0.20
                    + float(getattr(fragment, "affect_charge", 0.0) or 0.0) * 0.25,
                ),
            )
            pressure = max(pressure, local_pressure)
            tags = tuple(getattr(fragment, "tags", ()) or ())
            kind = str(getattr(fragment, "kind", "") or "")
            if kind in {"unresolved_loop", "suppressed_impulse", "repair_aftershock", "shadow_pressure"} or any(tag in {"shadow", "repair_aftershock", "suppressed_impulse"} for tag in tags):
                unresolved_pressure = max(unresolved_pressure, local_pressure)
            if kind in {"contradiction", "contradiction_warning"} or "contradiction" in tags:
                contradiction_pressure = max(contradiction_pressure, local_pressure)
            if kind in {"knowledge_gap", "curiosity_seed", "ask_later_candidate"} or "curiosity" in tags:
                curiosity_gap_pressure = max(curiosity_gap_pressure, local_pressure)
            if kind in {"suppressed_impulse", "rehearsal_result"} or "suppressed_impulse" in tags:
                suppressed_weight += max(1, len(tuple(getattr(fragment, "evidence_ids", ()) or ())))

        fragment_count = float(len(fragments))
        dominant_count = max(groups.values()) if groups else 0
        dominant_ratio = dominant_count / max(1.0, fragment_count)
        evidence_density = min(1.0, len(unique_evidence) / max(1.0, fragment_count * 2.0))
        coherence = max(0.0, min(1.0, dominant_ratio * 0.55 + evidence_density * 0.20 + pressure * 0.25))
        recurring = max(0.0, min(1.0, dominant_ratio * 0.75 + min(0.25, max(0, dominant_count - 1) * 0.10)))
        return {
            "fragment_count": fragment_count,
            "coherence": coherence,
            "pressure": pressure,
            "recurring_theme_strength": recurring,
            "unresolved_loop_pressure": unresolved_pressure,
            "contradiction_pressure": contradiction_pressure,
            "suppressed_recurrence": max(0.0, min(1.0, suppressed_weight / 6.0)),
            "curiosity_gap_pressure": curiosity_gap_pressure,
        }

    def _schedule_next_subconscious_due(self, lane: str, low: float, high: float, *, now: float) -> None:
        self._subconscious_lane_next_due[lane] = now + random.uniform(low, high)

    def _score_subconscious_surface(
        self,
        *,
        thought,
        snapshot,
        internal_state,
        recurring_theme_strength: float,
    ) -> float:
        if thought is None:
            return 0.0
        topic = str(getattr(thought, "topic_seed", "") or getattr(thought, "dominant_theme", "") or "")
        privacy_level = str(getattr(thought, "privacy_level", "") or "normal").lower()
        route = str(getattr(thought, "recommended_route", "") or "")
        focus = str(getattr(snapshot, "active_window_kind", "") or "").lower()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        usefulness = 0.68 if route == "surface_candidate" else (0.50 if route in {"rehearse", "store"} else 0.28)
        novelty = max(0.0, min(1.0, float(getattr(thought, "novelty", 0.0) or 0.0)))
        continuity_gain = max(0.0, min(1.0, recurring_theme_strength * 0.55 + float(getattr(thought, "momentum_score", 0.0) or 0.0) * 0.45))
        interruption_cost = max(
            0.0,
            min(
                1.0,
                (0.72 if any(term in focus for term in ("code", "coding", "deep_work", "focused")) else 0.28)
                - min(0.18, idle_seconds / 1200.0)
                + float(getattr(internal_state, "silence_pressure", 0.0) or 0.0) * 0.12,
            ),
        )
        privacy_cost = 0.80 if privacy_level in {"private", "sensitive"} else (0.38 if route in {"store", "suppress"} else 0.12)
        repetition_penalty = 0.0
        norm_topic = self._normalize_user_message(topic)
        recent = tuple(getattr(self, "recent_inner_thought_seeds", ()) or ()) + tuple(getattr(self._get_internal_state(), "recent_subconscious_seeds", ()) or ())
        recent_norm = {self._normalize_user_message(str(item)) for item in recent if str(item).strip()}
        if norm_topic and norm_topic in recent_norm:
            repetition_penalty = 0.55
        timing_fit = max(0.0, min(1.0, 0.82 - interruption_cost * 0.70 + min(0.18, idle_seconds / 600.0)))
        return max(
            0.0,
            min(
                1.0,
                float(getattr(thought, "surface_pressure", 0.0) or 0.0) * 0.35
                + usefulness * 0.20
                + novelty * 0.15
                + continuity_gain * 0.15
                + timing_fit * 0.15
                - interruption_cost * 0.35
                - privacy_cost * 0.30
                - repetition_penalty * 0.25,
            ),
        )

    def _surface_from_subconscious_thought(self, thought, *, surface_score: float) -> dict[str, object] | None:
        if thought is None:
            return None
        seed = thought.to_surface_seed()
        if not isinstance(seed, dict):
            return None
        seed = dict(seed)
        seed["surface_score"] = round(float(surface_score), 3)
        seed["root_source"] = str(seed.get("root_source") or "subconscious_synthesizer")
        seed["surface_allowed"] = True
        return seed

    def _maybe_tick_subconscious_runtime(
        self,
        *,
        channel: str,
        snapshot,
        internal_state,
        user_text: str = "",
        event_text: str = "",
        vision_facts: tuple[str, ...] = (),
        event_strength: float = 0.0,
        allow_lane5: bool = True,
        reflection: bool = False,
    ) -> SubconsciousReport | None:
        runtime = getattr(self, "subconscious_runtime", None)
        if runtime is None or not self.subconscious_runtime_enabled:
            self._pending_subconscious_report = None
            self._pending_subconscious_seed = None
            return None

        now = time.time()
        metrics = self._subconscious_pressure_metrics(
            internal_state=internal_state,
            snapshot=snapshot,
            event_strength=event_strength,
        )
        frame_payload = self._subconscious_frame_payload(
            snapshot=snapshot,
            user_text=user_text,
            internal_state=internal_state,
            channel=channel,
            event_text=event_text,
            vision_facts=vision_facts,
        )
        memory_packet = self._subconscious_memory_packet()
        relation = getattr(internal_state, "relationship_dynamics", None)

        lane2_due = now >= float(self._subconscious_lane_next_due.get("lane2", 0.0) or 0.0)
        should_lane2 = (
            metrics["event_strength"] > 0.45
            or metrics["drift_resonance"] > 0.55
            or metrics["self_anchor_pressure"] > 0.50
            or metrics["solitude_pressure"] > 0.60
            or lane2_due
        )
        if should_lane2:
            runtime.tick(
                frame=frame_payload,
                snapshot=snapshot,
                memory_packet=memory_packet,
                relation=relation,
                internal_state=internal_state,
                now=now,
                pre_worker_names=SUBCONSCIOUS_LANE2_WORKERS,
                audit_worker_names=SUBCONSCIOUS_AUDIT_WORKERS,
                run_pre_workers=True,
                run_audit=True,
                run_synthesis=False,
                run_post_workers=False,
                allow_surface_seed=False,
            )
            self._subconscious_lane_last_tick["lane2"] = now
            self._schedule_next_subconscious_due("lane2", 45.0, 120.0, now=now)

        board = self._subconscious_blackboard_metrics(now=now)
        should_lane3 = (
            board["coherence"] > 0.55
            and board["fragment_count"] >= 3.0
            and (
                board["pressure"] > 0.60
                or board["recurring_theme_strength"] > 0.65
                or board["unresolved_loop_pressure"] > 0.60
                or board["contradiction_pressure"] > 0.55
                or board["suppressed_recurrence"] > 0.55
                or board["curiosity_gap_pressure"] > 0.55
                or metrics["event_strength"] > 0.65
            )
        )

        lane3_result = None
        if should_lane3:
            lane3_result = runtime.tick(
                frame=frame_payload,
                snapshot=snapshot,
                memory_packet=memory_packet,
                relation=relation,
                internal_state=internal_state,
                now=now,
                post_worker_names=SUBCONSCIOUS_LANE3_POST_WORKERS,
                audit_worker_names=SUBCONSCIOUS_AUDIT_WORKERS,
                run_pre_workers=False,
                run_audit=True,
                run_synthesis=True,
                run_post_workers=True,
                allow_surface_seed=False,
            )
            self._subconscious_lane_last_tick["lane3"] = now

        lane5_due = now >= float(self._subconscious_lane_next_due.get("lane5", 0.0) or 0.0)
        should_lane5 = allow_lane5 and (
            reflection
            or lane5_due
            or metrics["idle_seconds"] >= 120.0
            or metrics["repair_need"] > 0.45
            or metrics["rupture"] > 0.35
            or board["suppressed_recurrence"] > 0.55
        )
        if should_lane5:
            runtime.tick(
                frame=frame_payload,
                snapshot=snapshot,
                memory_packet=memory_packet,
                relation=relation,
                internal_state=internal_state,
                now=now,
                pre_worker_names=SUBCONSCIOUS_LANE5_PRE_WORKERS,
                post_worker_names=SUBCONSCIOUS_LANE5_POST_WORKERS,
                audit_worker_names=SUBCONSCIOUS_AUDIT_WORKERS,
                run_pre_workers=True,
                run_audit=True,
                run_synthesis=True,
                run_post_workers=True,
                allow_surface_seed=False,
            )
            self._subconscious_lane_last_tick["lane5"] = now
            self._schedule_next_subconscious_due("lane5", 600.0, 1800.0, now=now)

        report = runtime.latest_report()
        seed = None
        if lane3_result is not None and getattr(lane3_result, "thought_object", None) is not None:
            surface_score = self._score_subconscious_surface(
                thought=lane3_result.thought_object,
                snapshot=snapshot,
                internal_state=internal_state,
                recurring_theme_strength=board["recurring_theme_strength"],
            )
            threshold = float(
                get_config(
                    "subconscious_runtime.lanes.lane4_surface_candidate.surface_score_threshold",
                    default=0.68,
                )
                or 0.68
            )
            if surface_score >= threshold:
                seed = self._surface_from_subconscious_thought(
                    lane3_result.thought_object,
                    surface_score=surface_score,
                )
                surface = runtime._surface_from_seed(seed, lane3_result.thought_object) if seed else ThoughtSurface()
                report = replace(
                    report,
                    latest_seed=surface,
                    recent_seeds=(surface,) if surface.mode else (),
                    surface_pressure=max(float(getattr(report, "surface_pressure", 0.0) or 0.0), float(surface.pressure or 0.0)),
                    suppression_reason="",
                )
            else:
                store_range = get_config(
                    "subconscious_runtime.lanes.lane4_surface_candidate.store_private_range",
                    default=(0.45, 0.67),
                )
                if not isinstance(store_range, (list, tuple)) or len(store_range) < 2:
                    store_range = (0.45, 0.67)
                lower = float(store_range[0] or 0.45)
                upper = float(store_range[1] or 0.67)
                if lower <= surface_score <= upper:
                    report = replace(report, suppression_reason=f"store_private(surface_score={surface_score:.2f})")
                else:
                    report = replace(report, suppression_reason=f"suppress(surface_score={surface_score:.2f})")

        self._pending_subconscious_report = report
        self._pending_subconscious_seed = seed
        self._last_subconscious_runtime_tick_at = now
        self._last_subconscious_runtime_reason = channel
        return report

    def _maybe_tick_subconscious_background(self, *, snapshot, internal_state) -> None:
        if not self.subconscious_runtime_enabled or getattr(self, "_chat_processing", False):
            return
        now = time.time()
        ambient_due = now >= float(self._subconscious_lane_next_due.get("lane2", 0.0) or 0.0)
        solitude_due = now >= float(self._subconscious_lane_next_due.get("lane5", 0.0) or 0.0)
        reflection_due = now >= float(self._subconscious_lane_next_due.get("reflection", 0.0) or 0.0)
        if not any((ambient_due, solitude_due, reflection_due)):
            return
        self._maybe_tick_subconscious_runtime(
            channel="background",
            snapshot=snapshot,
            internal_state=internal_state,
            user_text="",
            event_text="ambient_tick" if ambient_due else "",
            event_strength=0.18 if ambient_due else 0.0,
            allow_lane5=solitude_due or reflection_due,
            reflection=reflection_due,
        )
        if reflection_due:
            self._subconscious_lane_last_tick["reflection"] = now
            self._schedule_next_subconscious_due("reflection", 900.0, 1800.0, now=now)

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

    def _build_silent_motion_decision(self, ti_report: TiPolicyReport) -> Decision | None:
        motion_intent = str(getattr(ti_report, "motion_intent_hint", "") or "").strip()
        motion_target_x = float(getattr(ti_report, "motion_target_x_hint", -1.0) or -1.0)
        motion_facing = int(getattr(ti_report, "motion_facing_hint", 0) or 0)
        if not motion_intent:
            return None
        if motion_target_x < 0.0 and motion_facing == 0:
            return None
        return Decision(
            text="",
            animation=str(getattr(ti_report, "animation_hint", "") or "stand"),
            should_speak=False,
            confidence=0.54,
            parse_mode="motion_only",
            debug_trace=f"silent_motion; ti_mode={getattr(ti_report, 'mode', '')}",
            motion_intent=motion_intent,
            motion_target_x=motion_target_x,
            motion_facing=motion_facing,
        )

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
        """Dùng duy nhất smart vision gate của ChatCycleMixin.

        Bản cũ ở coordinator coi mọi lượt chat là lý do chụp màn hình và vô tình
        đè method mới trong mixin. Delegate tường minh để MRO không thể hồi sinh
        logic cũ trong một lần merge sau này.
        """

        return ChatCycleMixin._looks_like_screen_vision_request(self, user_text)

    def _capture_screen_frame_for_chat(self, user_text: str) -> str:
        return ChatCycleMixin._capture_screen_frame_for_chat(self, user_text)

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



    def _handle_force_speak_request(self) -> None:
        """Route force-speak qua cùng autonomous orchestrator, không có pipeline phụ."""
        orchestrator = getattr(self, "ai_autonomous_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error("[architecture C] force_speak unavailable: runtime bootstrap failed")
            return
        orchestrator.run_force_speak()

    def _handle_incoming(self, msg: dict):
        msg_type = msg.get("type", "")
        if getattr(self, "_maintenance_in_progress", False) and msg_type in {"chat", "chat_start", "force_speak"}:
            try:
                self.transport.send_json({
                    "type": "maintenance_busy",
                    "parse_mode": "maintenance_busy",
                    "should_speak": False,
                    "maintenance_busy": {"message": "Brain đang bảo trì; lượt mới chưa được nhận."},
                })
            except Exception:
                pass
            return
        if is_stage_inbound_type(msg_type):
            self._handle_stage_inbound_event(msg)
            return

        if msg_type == "panel_state_ack":
            self._handle_panel_state_ack(msg)
            return

        if msg_type == "phase7_validation_control":
            self._handle_phase7_validation_control(msg)
            return

        if msg_type == "chat_start":
            self._enter_chat_cycle()
            return

        if msg_type == "chat":
            user_text = str(msg.get("message", "") or "").strip()
            user_timestamp = float(msg.get("timestamp") or time.time())
            self._capture_speech_interrupt_for_user(user_text, timestamp=user_timestamp)
            # VoiceManager đã supersede khi có text. Gọi thêm ở đây để cả engine
            # giả/test double và chat không tạo InterruptEvent vẫn thu hồi audio cũ.
            self._supersede_tts_for_new_user_turn("user_chat_supersede")
            self._run_chat_cycle(
                user_text,
                user_timestamp=user_timestamp,
            )
            return

        if msg_type == "force_speak":
            self._supersede_tts_for_new_user_turn("user_force_speak")
            self._handle_force_speak_request()
            return

        if msg_type == "anchor_control":
            self._handle_anchor_control(msg)
            return

        if msg_type == "depth_control":
            self._handle_depth_control(msg)
            return

        if msg_type == "settings_update":
            self._handle_settings_update(msg)
            return

        if msg_type == "settings_health":
            self._handle_settings_health()
            return

        if msg_type == "maintenance_catalog":
            self._handle_maintenance_catalog(msg)
            return

        if msg_type in {"maintenance_request", "maintenance_execute"}:
            self._handle_maintenance_request(msg)
            return

        if msg_type == "debug_command":
            self._handle_debug_command(msg)
            return

        if msg_type == "chat_end":
            self._end_chat_cycle()
            return
        if msg_type:
            self.logger.debug("[incoming] ignored unknown msg_type=%s", msg_type)

    def _handle_panel_state_ack(self, msg: dict) -> None:
        """Nhận receipt từ Body cho lane panel.

        UDP không đảm bảo giao hàng. Trước Phase 7, Brain chỉ biết đã ``sendto``
        chứ không biết C# có parse được hay không, nên panel trống vẫn có thể bị
        ghi thành “gửi thành công”. Receipt này biến visibility thành evidence.
        """

        packet_id = str(msg.get("packet_id", "") or "").strip()
        complete = bool(msg.get("complete", False))
        has_private_mind = bool(msg.get("has_private_mind", False))
        has_emotion = bool(msg.get("has_emotion", False))
        has_depth = bool(msg.get("has_depth", False))
        try:
            sent_at = float(msg.get("sent_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            sent_at = 0.0
        latency_ms = max(0.0, (time.time() - sent_at) * 1000.0) if sent_at > 0 else 0.0
        obs = getattr(self, "observability", None)
        if obs is not None:
            obs.increment(
                "panel_state_ack_total",
                tags={"complete": str(complete).lower()},
                fields={
                    "packet_id": packet_id,
                    "has_private_mind": has_private_mind,
                    "has_emotion": has_emotion,
                    "has_depth": has_depth,
                },
            )
            if complete:
                obs.increment("panel_state_ack_complete_total", fields={"packet_id": packet_id})
            if latency_ms > 0:
                obs.observe("panel_state_ack_latency_ms", latency_ms, fields={"packet_id": packet_id})
        phase7 = getattr(self, "phase7_validation", None)
        if phase7 is not None:
            try:
                phase7.mark_scenario(
                    "panel_delivery",
                    passed=complete,
                    detail=(
                        f"packet={packet_id}; private_mind={has_private_mind}; "
                        f"emotion={has_emotion}; depth={has_depth}; latency_ms={latency_ms:.1f}"
                    ),
                )
            except Exception:
                pass

    def _handle_phase7_validation_control(self, msg: dict) -> None:
        """Control protocol nhỏ để chạy Phase 7 trên máy thật qua UDP 4243."""

        action = str(msg.get("action", "status") or "status").strip().lower()
        manager = getattr(self, "phase7_validation", None)
        result: dict[str, object]
        try:
            manager_disabled = not bool(
                getattr(getattr(manager, "config", None), "production_validation_enabled", False)
            )
            if action == "start" and self.observability is not None and (manager is None or manager_disabled):
                from dataclasses import replace
                from runtime.hardening_config import HardeningConfig
                from runtime.phase7_validation import Phase7ValidationManager

                base_cfg = getattr(self, "hardening_config", None) or HardeningConfig.load()
                cfg = replace(base_cfg, production_validation_enabled=True)
                manager = Phase7ValidationManager(
                    observability=self.observability,
                    provider_health_fn=self.provider_health_snapshot,
                    rollout_status_fn=(
                        self.rollout_controller.status
                        if self.rollout_controller is not None and callable(getattr(self.rollout_controller, "status", None))
                        else (lambda: {})
                    ),
                    config=cfg,
                    release_id=str(msg.get("release_id", "") or os.getenv("ERIS_RELEASE_ID", "") or ""),
                    environment_fn=self._phase7_environment_snapshot,
                )
                self.phase7_validation = manager
            if manager is None:
                raise RuntimeError("phase7_validation_unavailable")

            if action == "start":
                state = manager.start(validation_id=str(msg.get("validation_id", "") or ""))
                result = state.to_dict() if state is not None else manager.status()
            elif action == "mark":
                manager.mark_scenario(
                    str(msg.get("scenario", "") or ""),
                    passed=bool(msg.get("passed", False)),
                    turn_id=str(msg.get("turn_id", "") or ""),
                    detail=str(msg.get("detail", "") or ""),
                )
                result = manager.status()
            elif action == "finalize":
                report = manager.finalize(reason=str(msg.get("reason", "manual") or "manual"))
                result = report.to_dict() if report is not None else manager.status()
            else:
                result = manager.status()
            status = "ok"
        except Exception as exc:
            status = "error"
            result = {"error": type(exc).__name__, "message": str(exc)[:240]}
        try:
            self.transport.send_json({
                "type": "phase7_validation_ack",
                "parse_mode": "phase7_validation_ack",
                "should_speak": False,
                "action": action,
                "status": status,
                "phase7_validation": result,
            })
        except Exception:
            pass

    def _phase7_environment_snapshot(self) -> dict[str, object]:
        import platform
        import sys

        tts = getattr(self, "tts_engine", None)
        signature = ""
        if tts is not None and callable(getattr(tts, "cache_signature", None)):
            try:
                signature = str(tts.cache_signature() or "")
            except Exception:
                signature = ""
        try:
            from runtime.hardening_config import HardeningConfig
            hardening = HardeningConfig.load().to_dict()
        except Exception:
            hardening = {}
        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "runtime_session_id": str(getattr(self, "runtime_session_id", "") or ""),
            "tts_signature": signature,
            "provider_health": self.provider_health_snapshot(),
            "hardening_config": hardening,
        }

    def _handle_maintenance_catalog(self, msg: dict | None = None) -> None:
        """Trả danh sách thao tác Danger Zone và thống kê cache hiện tại."""

        service = getattr(self, "maintenance_service", None)
        try:
            payload = service.catalog() if service is not None else {"actions": [], "error": "maintenance_service_unavailable"}
            self.transport.send_json({
                "type": "maintenance_catalog_ack",
                "parse_mode": "maintenance_catalog_ack",
                "should_speak": False,
                "maintenance_catalog_ack": payload,
            })
        except Exception as exc:
            self.logger.warning("[maintenance] catalog failed: %s", exc)

    def _handle_maintenance_request(self, msg: dict) -> None:
        """Preview hoặc thực thi command Danger Zone.

        Protocol hai bước ngăn một click lệch tay xóa state ngay lập tức:
        ``dry_run=true`` trả manifest + token; Body chỉ execute bằng token đó.
        """

        service = getattr(self, "maintenance_service", None)
        request_id = str(msg.get("request_id", "") or "")
        action = str(msg.get("action", "") or "").strip().lower()
        dry_run = str(msg.get("type", "") or "") != "maintenance_execute" and bool(msg.get("dry_run", True))
        options = msg.get("options") if isinstance(msg.get("options"), dict) else {}
        try:
            if service is None:
                raise RuntimeError("maintenance_service_unavailable")
            if dry_run:
                result = service.preview(action, options=options)
                envelope_type = "maintenance_preview_ack"
                field = "maintenance_preview_ack"
            else:
                token = str(msg.get("confirmation_token", "") or "")
                typed_confirmation = str(msg.get("typed_confirmation", "") or "")
                result = service.execute(
                    action, confirmation_token=token,
                    typed_confirmation=typed_confirmation, options=options,
                )
                envelope_type = "maintenance_execute_ack"
                field = "maintenance_execute_ack"
            self.transport.send_json({
                "type": envelope_type,
                "parse_mode": envelope_type,
                "should_speak": False,
                field: {
                    "request_id": request_id,
                    "protocol_phase": "preview" if dry_run else "execute",
                    **result,
                },
            })
        except Exception as exc:
            self.logger.warning("[maintenance] request action=%s dry_run=%s failed: %s", action, dry_run, exc)
            try:
                self.transport.send_json({
                    "type": "maintenance_execute_ack",
                    "parse_mode": "maintenance_execute_ack",
                    "should_speak": False,
                    "maintenance_execute_ack": {
                        "request_id": request_id,
                        "action": action,
                        "ok": False,
                        "changed": [],
                        "warnings": [],
                        "errors": [str(exc)[:320]],
                        "backup_dir": "",
                    },
                })
            except Exception:
                pass

    def _handle_settings_health(self) -> None:
        """Gửi trạng thái hai key pool cho Settings UI mà không lộ API key.

        Trước đây nút kiểm tra chỉ gửi message nhưng coordinator chưa xử lý.
        Handler này trả snapshot thật gồm key đang dùng, key cooldown và cooldown
        toàn pool để UI hiển thị đúng trạng thái.
        """

        try:
            from llm.key_pool import get_key_pool

            pools = {
                "gemini": get_key_pool("gemini").snapshot(),
                "groq": get_key_pool("groq").snapshot(),
            }
            try:
                from actions.capability_runtime import runtime_capability_snapshot
                capability_health = runtime_capability_snapshot(refresh=True)
            except Exception as capability_exc:
                capability_health = {"error": f"{type(capability_exc).__name__}: {capability_exc}"}
            try:
                from runtime.observability import ensure_observability
                telemetry = ensure_observability(self)
                for provider_name, snapshot in pools.items():
                    telemetry.record_provider_pool(provider=provider_name, snapshot=snapshot, event="settings_health")
            except Exception:
                pass
            tts = getattr(self, "tts_engine", None)
            tts_ready = bool(tts is not None and getattr(tts, "_ok", False))
            ack = {
                "type": "settings_health_ack",
                "parse_mode": "settings_health_ack",
                "should_speak": False,
                "settings_health_ack": {
                    "pools": pools,
                    "tts": {"ready": tts_ready},
                    "capabilities": capability_health,
                },
            }
        except Exception as exc:
            self.logger.warning("[settings] key pool health snapshot failed: %s", exc)
            ack = {
                "type": "settings_health_ack",
                "parse_mode": "settings_health_ack",
                "should_speak": False,
                "settings_health_ack": {
                    "pools": {},
                    "tts": {"ready": False},
                    "error": str(exc)[:240],
                },
            }

        try:
            self.transport.send_json(ack)
        except Exception as exc:
            self.logger.debug("[settings] health ack send failed: %s", exc)

    def _handle_settings_update(self, msg: dict) -> None:
        """Áp dụng settings live qua schema, persist trước rồi mới refresh runtime."""

        scope = str(msg.get("scope", "runtime") or "runtime").strip().lower()
        try:
            from runtime.runtime_settings_store import get_runtime_settings_store
            from runtime.settings_protocol import normalize_settings_message

            store = getattr(self, "runtime_settings_store", None) or get_runtime_settings_store(logger=self.logger)
            normalized = normalize_settings_message(msg)
            if normalized.scope not in {"tts", "advanced", "personality", "runtime"}:
                raise ValueError(f"unsupported settings scope: {normalized.scope}")
            if not normalized.patch:
                raise ValueError("settings payload không có field hợp lệ")

            result = store.apply_patch(
                normalized.patch,
                restart_required_paths=set(normalized.restart_required_paths),
                materialize_env=False,
            )
            self.runtime_settings_store = store
            self.runtime_settings = result.settings
            rejected = list(normalized.rejected_fields) + list(result.rejected)

            refresh_meta = self._refresh_runtime_after_settings(
                scope=normalized.scope,
                applied_paths=set(result.applied),
            )
            ack_payload = result.to_ack(scope=normalized.scope)
            ack_payload["rejected"] = list(dict.fromkeys(rejected))
            ack_payload["legacy_payload"] = bool(normalized.legacy_payload)
            ack_payload.update(refresh_meta)
            if normalized.scope == "tts":
                tts_settings = result.settings.get("tts", {})
                ack_payload.update({
                    "language": tts_settings.get("language", "vi"),
                    "voice": tts_settings.get("voice", "Aoede"),
                    "quality": tts_settings.get("quality", "high"),
                    "volume": tts_settings.get("volume", 1.0),
                    "speed": tts_settings.get("speed", 1.0),
                })

            self.logger.info(
                "[runtime-settings] live scope=%s applied=%d rejected=%d restart=%d",
                normalized.scope, len(result.applied), len(rejected), len(result.restart_required),
            )
            self.transport.send_json({
                "type": "settings_update_ack",
                "parse_mode": "settings_update_ack",
                "should_speak": False,
                "settings_update_ack": ack_payload,
            })
        except Exception as exc:
            self.logger.warning("[runtime-settings] update scope=%s failed: %s", scope, exc)
            try:
                self.transport.send_json({
                    "type": "settings_update_ack",
                    "parse_mode": "settings_update_ack",
                    "should_speak": False,
                    "settings_update_ack": {
                        "scope": scope,
                        "applied": [],
                        "rejected": [str(exc)[:240]],
                        "restart_required": [],
                        "ok": False,
                    },
                })
            except Exception:
                pass

    def _refresh_runtime_after_settings(self, *, scope: str, applied_paths: set[str]) -> dict:
        """Refresh các component có contract live; mục bootstrap vẫn báo restart."""

        meta = {"worker_rebuilt": False, "engine_ready": False, "live_refreshed": []}
        self.stage_frame_builder = None
        meta["live_refreshed"].append("stage_frame_builder")

        if any(path.startswith("tts.") or path.startswith("stage.") for path in applied_paths):
            tts = getattr(self, "tts_engine", None)
            refresh = getattr(tts, "refresh_configuration", None) if tts is not None else None
            if callable(refresh):
                try:
                    meta["worker_rebuilt"] = bool(refresh())
                    meta["live_refreshed"].append("tts_engine")
                except Exception as exc:
                    self.logger.warning("[runtime-settings] TTS refresh failed: %s", exc)
            meta["engine_ready"] = bool(tts is not None and getattr(tts, "_ok", False))

        if "chat.max_concurrency" in applied_paths:
            try:
                from llm.key_pool import reset_concurrency_limits
                reset_concurrency_limits()
                meta["live_refreshed"].append("provider_concurrency")
            except Exception as exc:
                self.logger.debug("[runtime-settings] concurrency refresh failed: %s", exc)

        # Policy modules đọc store mỗi lượt nên không cần reconstruct. Ghi rõ để
        # observability/UI biết live apply không phải một cái nút trang trí.
        if any(path.startswith("chat.") or path.startswith("personality.") for path in applied_paths):
            meta["live_refreshed"].append("conversation_policy")
        if any(path.startswith("prompt.") for path in applied_paths):
            meta["live_refreshed"].append("prompt_budget_policy")
        if any(path.startswith("capabilities.") for path in applied_paths):
            try:
                from actions.capability_runtime import refresh_runtime_capabilities

                refresh_runtime_capabilities(owner=self, settings=self.runtime_settings)
                meta["live_refreshed"].append("capability_runtime_snapshot")
            except Exception as exc:
                self.logger.debug("[capability] live refresh failed: %s", exc)
        if any(path.startswith("tutor.") for path in applied_paths):
            meta["live_refreshed"].append("tutor_search_policy")
        return meta

    def _handle_stage_inbound_event(self, msg: dict) -> None:
        """Nhận event ngược từ frontend/sân khấu.

        Đây là lớp protocol, không thay chat payload cũ. Frontend có thể báo
        `interrupt` ngay khi mic phát hiện user bắt đầu nói, trước khi STT có text.
        """

        bus = getattr(self, "stage_event_bus", None)
        event = None
        try:
            event = bus.remember_inbound(msg) if bus is not None else None
        except Exception as exc:
            self.logger.debug("[stage-protocol] inbound parse failed: %s", exc)
        if event is None:
            return
        self.last_stage_inbound_event = event.to_meta()

        if event.type == "interrupt":
            self._handle_stage_interrupt_event(event)
            return

        if event.type == "avatar_ready":
            self.avatar_ready = True
            self._emit_stage_protocol_state("avatar_ready_ack", data=event.to_meta())
            return

        if event.type in {"audio_playback_started", "audio_playback_done"}:
            self._track_frontend_audio_event(event)
            clock = getattr(self, "interaction_clock", None)
            if clock is not None:
                timestamp = float(getattr(event, "timestamp", time.time()) or time.time())
                if event.type == "audio_playback_started":
                    clock.mark_audio_started(timestamp)
                else:
                    clock.mark_audio_finished(timestamp)
            self._emit_stage_protocol_state(f"{event.type}_ack", data=event.to_meta())
            return

        if event.type == "stage_ack":
            self._emit_stage_protocol_state("stage_ack_received", data=event.to_meta())

    def _handle_stage_interrupt_event(self, event) -> None:
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            clock.mark_interrupt(float(getattr(event, "timestamp", time.time()) or time.time()))
        text = str(getattr(event, "message", "") or "").strip()
        if text:
            self._capture_speech_interrupt_for_user(text, timestamp=float(getattr(event, "timestamp", time.time()) or time.time()))
        else:
            # Voice-start interrupt: chưa có STT text, nhưng sân khấu phải dừng
            # ngay để Eris không đọc đè lên người dùng.
            try:
                self._ensure_voice_manager().interrupt_signal(
                    reason=str(getattr(event, "reason", "") or "frontend_interrupt")
                )
            except Exception as exc:
                self.logger.debug("[stage-protocol] interrupt cancel failed: %s", exc)
        self._emit_stage_protocol_state("interrupt_ack", reason=str(getattr(event, "reason", "") or ""), data=event.to_meta())

    def _track_frontend_audio_event(self, event) -> None:
        """Cho frontend playback event cập nhật ledger nếu frontend là nguồn phát."""

        legacy_type = "audio_start" if event.type == "audio_playback_started" else "audio_done"
        try:
            self._ensure_voice_manager().track_tts_event(
                SimpleNamespace(
                    type=legacy_type,
                    turn_id=str(getattr(event, "turn_id", "") or ""),
                    segment_id=int(getattr(event, "seq", 0) or 0),
                    text=str(getattr(event, "message", "") or ""),
                    turn_segments=(),
                ),
                stage_frame=None,
                timestamp=float(getattr(event, "timestamp", time.time()) or time.time()),
            )
        except Exception as exc:
            self.logger.debug("[stage-protocol] frontend audio track failed: %s", exc)

    def _emit_stage_protocol_state(self, event_type: str, *, reason: str = "", data: dict | None = None) -> None:
        try:
            bus = getattr(self, "stage_event_bus", None)
            if bus is not None:
                bus.emit(stage_state_event(event_type=event_type, reason=reason, data=data or {}))
        except Exception as exc:
            self.logger.debug("[stage-protocol] state emit failed: %s", exc)

    def _handle_debug_command(self, msg: dict) -> None:
        """Chạy lệnh debug (scenario preset) từ panel DEBUG của Godot.

        Panel gửi ``{"type":"debug_command","command":"reset all; stage rooted; ..."}``.
        Lệnh đi qua :class:`DebugConsole`, ép thẳng vào state sống của coordinator
        nên cycle kế tiếp khởi đầu từ trạng thái mới (engine vẫn decay sau đó).
        """
        command = str(msg.get("command") or "").strip()
        if not command:
            self.logger.debug("[debug_command] lệnh rỗng, bỏ qua")
            return
        console = getattr(self, "_debug_console", None)
        if console is None:
            from runtime.debug_console import DebugConsole

            console = DebugConsole(self)
            self._debug_console = console
        ok = True
        result = ""
        try:
            result = console.execute(command)
            self.logger.info("[debug_command] %s -> %s", command, result)
        except Exception as exc:  # pragma: no cover - debug surface không được crash runtime
            ok = False
            result = str(exc)
            self.logger.warning("[debug_command] '%s' lỗi: %s", command, exc)
        try:
            # Gửi ack im lặng để panel DEBUG biết lệnh vừa chạy xong.
            self.transport.send_json(
                {
                    "parse_mode": "debug_command_ack",
                    "should_speak": False,
                    "animation": "",
                    "debug_command_ack": {
                        "command": command[:240],
                        "ok": ok,
                        "result": str(result or "")[:500],
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - ack debug không được làm rơi runtime
            self.logger.debug("[debug_command] không gửi được ack: %s", exc)

    def _handle_anchor_control(self, msg: dict) -> None:
        """Tác_Giả bật/tắt trục tối từ panel Godot (R5.5, R10.4).

        Gọi thẳng AuthorControl trên anchor_system của private mind loop. Đổi xong
        thì digest kế tiếp tự phản ánh trạng thái mới (panel đọc switches live).
        """
        loop = getattr(self, "private_mind_loop", None)
        sysm = getattr(loop, "anchor_system", None)
        author = getattr(sysm, "author", None) if sysm is not None else None
        if author is None:
            self.logger.debug("[anchor_control] no anchor_system available")
            return
        action = str(msg.get("action") or "").strip()
        value = bool(msg.get("value", True))
        try:
            if action == "shadow":
                author.enable_shadow(value)
            elif action == "deception":
                author.enable_deception(value)
            elif action == "strict_grounding":
                author.set_strict_grounding(value)
            elif action == "safe_mode":
                if value:
                    author.disable_dark()
                else:
                    author.set_strict_grounding(False)
            elif action == "reset_all":
                author.reset_all()
            else:
                self.logger.debug("[anchor_control] unknown action=%s", action)
                return
            self.logger.info("[anchor_control] %s -> %s (safe_mode=%s)", action, value, author.is_safe_mode)
        except Exception as exc:
            self.logger.warning("[anchor_control] %s failed: %s", action, exc)

    def _handle_depth_control(self, msg: dict) -> None:
        """Bật/tắt cờ chiều-sâu (N1–N3) từ tab Panel trong context menu Godot.

        Ghi control-file ``memory_core/depth_flags.json`` (qua cortex.depth_flags);
        các helper cờ đọc file đó mỗi lần gọi nên bật/tắt ăn ngay, không restart.
        """
        flag = str(msg.get("flag") or "").strip()
        value = bool(msg.get("value", True))
        try:
            from cortex.depth_flags import KNOWN_FLAGS, set_flags

            if flag not in KNOWN_FLAGS:
                self.logger.debug("[depth_control] unknown flag=%s", flag)
                return
            set_flags({flag: value})
            self.logger.info("[depth_control] %s -> %s", flag, value)
        except Exception as exc:
            self.logger.warning("[depth_control] %s failed: %s", flag, exc)

    def _build_depth_v2_block(self, *, private_mind_digest: dict[str, object] | None = None) -> dict[str, object]:
        """Compact v2 contract for the replacement depth panel.

        Built from private_mind as the primary source, with lightweight live
        supplements for expression, Cortex V2 reading, flags, and a tiny affect history.
        """
        try:
            from cortex.depth_flags import all_states
        except Exception:
            flags = {}
        else:
            flags = all_states()

        try:
            rich = self._cached_panel_state()
        except Exception:
            rich = {}
        identity = rich.get("identity") if isinstance(rich, dict) and isinstance(rich.get("identity"), dict) else {}

        try:
            from runtime.depth_v2_state import build_depth_v2_state

            brief = getattr(self, "last_cognitive_brief", None)
            if brief is not None:
                cognitive_read = (
                    f"posture={getattr(brief, 'user_posture', 'neutral')}; "
                    f"relation={getattr(brief, 'discourse_relation', 'new_topic')}; "
                    f"move={getattr(brief, 'response_move', 'answer')}; "
                    f"~{float(getattr(brief, 'confidence', 0.0) or 0.0):.2f}"
                )
            else:
                cognitive_read = ""
            block = build_depth_v2_state(
                private_mind_digest=private_mind_digest if isinstance(private_mind_digest, dict) else {},
                flags=flags,
                expression_gate=getattr(self, "_last_expression_gate", None),
                tom_read=cognitive_read,
                identity=identity,
                affect_history=getattr(self, "_depth_v2_affect_history", None),
            )
        except Exception:
            block = {
                "version": 2,
                "ts": round(time.time(), 3),
                "identity": identity,
                "status": {"headline": "listening", "subtext": "depth_v2 unavailable", "focus_mode": "attentive"},
                "affect": {"headline": "steady", "subtext": "fallback", "orbit": [], "metrics": {}},
                "tom": {"live": False, "text": "", "confidence": 0.0},
                "expression": {"want": 0.0, "suppress": 0.0, "allowed": 0.0, "stance": ""},
                "priorities": [],
                "interiority": {"sections": []},
                "n2": {"live": False, "axes": [], "sentence": "", "attachment": {"live": False, "value": 0.0}},
                "journal": [],
                "signal_log": [],
                "context": {"tags": [], "focus_mode": "attentive"},
                "flags": flags,
                "affect_history": list(getattr(self, "_depth_v2_affect_history", []) or []),
            }
        self._depth_v2_affect_history = list(block.get("affect_history", []) or [])
        return block

    def _cached_panel_state(self, *, ttl_seconds: float = 1.0) -> dict[str, object]:
        """build_panel_state() có cache ngắn — payload UDP gọi rất dày."""
        now = time.time()
        cache = getattr(self, "_panel_state_cache", None)
        if isinstance(cache, tuple) and (now - cache[0]) < ttl_seconds:
            return cache[1]
        try:
            from runtime.panel_state import build_panel_state

            state = build_panel_state()
        except Exception:
            state = {}
        self._panel_state_cache = (now, state)
        return state


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

        interval_raw = os.environ.get("ERIS_VISION_FACTS_INTERVAL", "10").strip()
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

    def _build_vision_caption_client(self, llm_service):
        """Tầng caption (ảnh → mô tả) chạy REMOTE khi llm_service có vision_client.

        vision_client được dựng ở process_manager.build_vision_client() khi bật
        ERIS_VISION_API_ENABLED (vd shopaikey grok-3-image). Có nó ⇒ thay moondream
        local bằng API; không ⇒ trả None ⇒ compressor caption local như cũ.
        """
        remote = getattr(llm_service, "vision_client", None)
        # Nếu provider chính là multimodal nhưng chưa dựng lane riêng, thử dùng
        # chính main client. Adapter sẽ tự degrade nếu model từ chối image_url.
        # Nhờ vậy gpt-5.6 Terra không bị đứng ngoài cửa trong khi OCR-only giả
        # vờ là toàn bộ thị giác của Eris.
        if remote is None:
            use_main = os.environ.get("ERIS_VISION_USE_MAIN_MODEL", "1").strip().lower() not in {
                "0", "false", "no", "off",
            }
            if use_main:
                candidate = getattr(llm_service, "client", None)
                if candidate is not None and callable(getattr(candidate, "create_chat_completion", None)):
                    remote = candidate
        if remote is None or not callable(getattr(remote, "create_chat_completion", None)):
            return None
        self.logger.info(
            "[vision caption] caption stage chạy REMOTE (%s); bỏ moondream local.",
            getattr(remote, "model_name", "remote"),
        )
        return RemoteCaptionClient(remote, logger=self.logger)

    def _build_vision_structure_client(self, llm_service):
        """Tầng cấu trúc-hoá vision (caption → JSON) chạy REMOTE.

        Ưu tiên fallback_client (glm-4.5-flash trên shopaikey) — ổn định, cùng server
        với grok, tránh gemma 500. ERIS_VISION_STRUCTURE_REMOTE:
          0/off       → tắt (structuring local nếu có)
          gemma/style → dùng style_client (gemma) như cũ
          1/auto/glm  → dùng fallback_client (glm) [mặc định]
        """
        mode = os.environ.get("ERIS_VISION_STRUCTURE_REMOTE", "auto").strip().lower()
        if mode in {"0", "false", "no", "off"}:
            return None
        if mode in {"gemma", "style"}:
            remote = getattr(llm_service, "style_client", None)
        else:
            remote = getattr(llm_service, "fallback_client", None) or getattr(llm_service, "style_client", None)
        if remote is None or not callable(getattr(remote, "create_chat_completion", None)):
            self.logger.warning(
                "[vision structure] bật nhưng không có remote client (fallback/style) — structuring rơi về local."
            )
            return None
        self.logger.info(
            "[vision structure] tầng-2 cấu trúc-hoá REMOTE qua %s (caption→JSON).",
            getattr(remote, "model_name", "remote"),
        )
        return RemoteStructureClient(remote, logger=self.logger)

    def _vision_queue_timeout_seconds(self, channel: str) -> float:
        env_name = "ERIS_VISION_QUEUE_TIMEOUT_CHAT_SEC" if channel == "chat" else "ERIS_VISION_QUEUE_TIMEOUT_SEC"
        default = 30.0 if channel == "chat" else 12.0
        raw = os.environ.get(env_name, "").strip()
        try:
            value = float(raw) if raw else default
        except ValueError:
            value = default
        return max(1.0, min(value, 120.0))

    def _vision_failure_backoff_seconds(self, stage: str, exc: Exception) -> float:
        text = f"{stage}:{exc}".lower()
        if any(marker in text for marker in ("model_queue_timeout", "resource_guard:", "tier_cooldown_active", "active_heavy_lease")):
            raw = os.environ.get("ERIS_VISION_SOFT_RETRY_BACKOFF_SEC", "2").strip()
            try:
                value = float(raw) if raw else 2.0
            except ValueError:
                value = 2.0
            return max(0.0, min(value, 10.0))
        return -1.0

    def _note_vision_failure(self, stage: str, exc: Exception) -> None:
        backoff = self._vision_failure_backoff_seconds(stage, exc)
        if backoff < 0.0:
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

        # Content-free OCR placeholder from the vision compressor fallback
        # ("screen context inferred from OCR; focus=unknown; intent=unknown")
        # carries no real screen content. Drop it so it never leaks as evidence.
        if "screen context inferred from ocr" in normalized:
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

    def _ground_semantic_scene_note(
        self,
        note: SemanticSceneNote | None,
        *,
        requested: bool = False,
        stale: bool = False,
    ) -> tuple[VisionGroundingReport, tuple[str, ...]]:
        """Kiểm từng claim vision trước khi biến thành ``screen_facts``.

        ``SemanticSceneNote`` là output của model, chưa phải bằng chứng đã được
        cấp quyền nói. Policy claim-level ở đây là van một chiều: claim yếu vẫn
        được giữ trong report để debug, nhưng không lọt vào prompt như fact.
        """

        policy = getattr(self, "vision_grounding_policy", None)
        if not isinstance(policy, VisionGroundingPolicy):
            policy = VisionGroundingPolicy()
            self.vision_grounding_policy = policy
        report = policy.evaluate(note, requested=requested, stale=stale)
        rollout = None
        try:
            from runtime.rollout_control import ensure_rollout_controller

            rollout = ensure_rollout_controller(self).decide(
                "vision_abstain",
                session_id=str(getattr(self, "runtime_session_id", "") or getattr(self, "session_id", "") or id(self)),
            )
        except Exception:
            rollout = None

        if rollout is None or rollout.apply:
            facts = self._sanitize_screen_facts(
                report.to_screen_facts(max_items=self.vision_fact_max_items)
            )
        else:
            # Control path cho dark/shadow/canary: giữ hành vi legacy đủ gần để
            # so sánh, trong khi report mới vẫn được log. Không surface relation
            # mềm vì đó chưa từng là tri giác trực tiếp đáng tin.
            legacy = []
            for value in (
                getattr(note, "content_summary", ""),
                getattr(note, "visible_context", ""),
                *tuple(getattr(note, "important_text", ()) or ()),
            ):
                text = str(value or "").strip()
                if text and text not in legacy:
                    legacy.append(text)
                if len(legacy) >= int(self.vision_fact_max_items):
                    break
            facts = self._sanitize_screen_facts(tuple(legacy))
        try:
            from runtime.observability import ensure_observability

            ensure_observability(self).record_vision(report, channel="requested" if requested else "ambient")
        except Exception:
            pass
        return report, facts

    def _semantic_scene_note_to_facts(self, note: SemanticSceneNote | None) -> tuple[str, ...]:
        """API tương thích cho caller cũ; mặc định coi đây là lane ambient."""

        _report, facts = self._ground_semantic_scene_note(note, requested=False, stale=False)
        return facts

    def _vision_trace_from_scene_note(self, note: SemanticSceneNote | None) -> str:
        if note is None:
            return ""
        source = str(getattr(note, "source", "") or "vision")
        family = str(getattr(note, "semantic_family", "") or "unknown")
        affect = str(getattr(note, "content_affect", "") or "").strip()
        has_delta = "1" if str(getattr(note, "delta", "") or "").strip() else "0"
        trace = f"{source}:{family}"
        if affect:
            trace += f":affect={affect}"
        trace += f":delta={has_delta}"
        return trace

    def _should_use_vision_compressor(
        self,
        *,
        observer_frame: ObserverFrame | None,
        force_refresh: bool,
    ) -> bool:
        compressor = getattr(self, "vision_semantic_compressor", None)
        if compressor is None:
            return False
        if force_refresh:
            return True
        if observer_frame is None:
            return False
        should_compress = getattr(compressor, "should_compress", None)
        if not callable(should_compress):
            return False
        try:
            return bool(
                should_compress(
                    observer_frame=observer_frame,
                    signal_diff=getattr(self, "last_signal_diff", None),
                )
            )
        except Exception as exc:
            self.logger.warning("[vision_facts] compressor policy failed: %s", exc)
            return False

    def _refresh_screen_facts_from_data_uri(
        self,
        *,
        data_uri: str,
        snapshot=None,
        channel: str = "autonomous",
        user_text: str = "",
        observer_frame: ObserverFrame | None = None,
        force_refresh: bool = False,
        started_at: float | None = None,
    ) -> tuple[str, ...]:
        requested = bool(
            channel == "chat"
            and callable(getattr(self, "_looks_like_screen_vision_request", None))
            and self._looks_like_screen_vision_request(user_text)
        )
        policy = getattr(self, "vision_grounding_policy", None)
        if not isinstance(policy, VisionGroundingPolicy):
            policy = VisionGroundingPolicy()
            self.vision_grounding_policy = policy

        if not data_uri:
            # Không có frame mới: cache còn hữu ích cho continuity nhưng phải mang
            # nhãn stale. Đừng đổi "lúc nãy" thành "tôi đang thấy" chỉ vì tuple
            # vẫn còn nằm trong RAM.
            self.vision_facts_are_stale = bool(self.vision_facts)
            self.vision_last_trace = ""
            self.vision_facts_novelty_hint = "cached_screen_fact" if self.vision_facts else "none"
            if self.last_semantic_scene_note is not None:
                self.last_vision_grounding_report = policy.evaluate(
                    self.last_semantic_scene_note,
                    requested=requested,
                    stale=True,
                )
            else:
                self.last_vision_grounding_report = policy.empty_report(
                    requested=requested,
                    stale=True,
                    reason="no_fresh_screen_frame",
                )
            return self.vision_facts

        if observer_frame is None and snapshot is not None:
            observer_frame = self._run_background_observer(
                snapshot=snapshot,
                channel=channel,
                user_text=user_text,
                vision_facts=(),
                started_at=started_at,
            )

        note: SemanticSceneNote | None = None
        trace = ""
        compressor = getattr(self, "vision_semantic_compressor", None)
        can_use_compressor = callable(getattr(compressor, "compress", None))

        if can_use_compressor:
            try:
                signal_snapshot = None
                if snapshot is not None:
                    try:
                        signal_snapshot = self._build_signal_snapshot_for_observer(
                            snapshot=snapshot,
                            channel=channel,
                            user_text=user_text,
                            vision_facts=tuple(getattr(snapshot, "vision_facts", ()) or ()),
                            started_at=started_at,
                        )
                    except Exception as exc:
                        self.logger.warning("[vision_facts] signal snapshot fallback: %s", exc)
                note = self.model_budget_policy.run_queued(
                    "vision_compressor",
                    compressor.compress,
                    reason=f"vision_compressor:{channel}",
                    priority=45 if channel == "chat" else 25,
                    timeout_seconds=self._vision_queue_timeout_seconds(channel),
                    image_data_uri=data_uri,
                    ocr_text=str(getattr(signal_snapshot, "ocr_text", "") or "") if signal_snapshot is not None else "",
                    observer_frame=observer_frame,
                    signal_snapshot=signal_snapshot,
                    extra_context=user_text if channel == "chat" else "",
                )
                trace = self._vision_trace_from_scene_note(note)
            except Exception as exc:
                self._note_vision_failure("compressor", exc)
                self.vision_stale_facts = tuple(self.vision_facts)
                self.vision_facts_are_stale = bool(self.vision_facts)
                self.last_vision_grounding_report = policy.empty_report(
                    requested=requested,
                    stale=True,
                    reason=f"vision_compressor_failed:{type(exc).__name__}",
                    unknowns=("fresh_frame_not_interpreted",),
                )
                return self.vision_facts
        else:
            self.logger.info(
                "[vision_facts] source=cached reason=no_compressor channel=%s",
                channel,
            )
            self.vision_stale_facts = tuple(self.vision_facts)
            self.vision_facts_are_stale = bool(self.vision_facts)
            self.last_vision_grounding_report = policy.empty_report(
                requested=requested,
                stale=True,
                reason="vision_compressor_unavailable",
            )
            return self.vision_facts

        report, cleaned = self._ground_semantic_scene_note(
            note,
            requested=requested,
            stale=False,
        )
        self.last_vision_grounding_report = report
        self.vision_failure_count = 0
        self.vision_disabled_until = 0.0
        self.vision_last_capture_at = time.time()
        self.last_semantic_scene_note = note

        previous_facts = tuple(self.vision_facts)
        signature = "\n".join(cleaned)
        self.vision_facts_novelty_hint = (
            "new_screen_fact"
            if cleaned and signature != self.vision_facts_signature
            else ("repeated_screen_fact" if cleaned else "abstained_screen_fact")
        )
        self.vision_facts_signature = signature

        if cleaned:
            self.vision_stale_facts = previous_facts
            self.vision_facts = cleaned
            self.vision_facts_are_stale = False
        else:
            # Frame mới đã được đọc nhưng không có claim nào đủ chắc. Xóa current
            # facts để cache cũ không đội mồ sống dậy thành hiện tại. Vẫn giữ bản
            # cũ trong ``vision_stale_facts`` cho audit, không đưa vào prompt.
            if previous_facts:
                self.vision_stale_facts = previous_facts
            self.vision_facts = ()
            self.vision_facts_are_stale = False

        self.vision_last_trace = (
            f"{trace};grounding={report.recommendation};"
            f"strength={report.evidence_strength:.2f};"
            f"grounded={len(report.grounded_claims)}"
        ).strip(";")
        self.logger.info(
            "[vision_grounding] channel=%s requested=%d recommendation=%s strength=%.2f "
            "claims=%d grounded=%d contradictions=%s unknowns=%s",
            channel,
            int(requested),
            report.recommendation,
            report.evidence_strength,
            len(report.claims),
            len(report.grounded_claims),
            ",".join(report.contradictions) or "none",
            ",".join(report.unknowns) or "none",
        )
        self.logger.info(
            "[vision_facts] source=grounded_claims channel=%s count=%d novelty=%s trace=%s fact=%s",
            channel,
            len(cleaned),
            self.vision_facts_novelty_hint,
            self.vision_last_trace or "<empty>",
            cleaned[0] if cleaned else "<abstained>",
        )
        if snapshot is not None:
            snapshot.vision_facts = tuple(self.vision_facts)
        return self.vision_facts

    def _maybe_update_screen_facts(
        self,
        *,
        snapshot=None,
        channel: str = "autonomous",
        user_text: str = "",
        observer_frame: ObserverFrame | None = None,
        force_refresh: bool = False,
        started_at: float | None = None,
    ) -> tuple[str, ...]:
        if not self.vision_facts_enabled:
            self.vision_facts_novelty_hint = "none"
            return ()

        now = time.time()
        if now < self.vision_disabled_until:
            self.vision_facts_novelty_hint = "cached_screen_fact" if self.vision_facts else "none"
            return self.vision_facts
        if (
            not force_refresh
            and self.vision_last_capture_at
            and (now - self.vision_last_capture_at) < self.vision_interval_sec
        ):
            self.vision_facts_novelty_hint = "cached_screen_fact" if self.vision_facts else "none"
            return self.vision_facts

        try:
            data_uri = self.telemetry_service.capture_screen_frame_data_uri()
        except Exception as exc:
            self._note_vision_failure("capture", exc)
            return self.vision_facts

        return self._refresh_screen_facts_from_data_uri(
            data_uri=data_uri,
            snapshot=snapshot,
            channel=channel,
            user_text=user_text,
            observer_frame=observer_frame,
            force_refresh=force_refresh,
            started_at=started_at or now,
        )

    def _attach_screen_facts(self, snapshot, facts: tuple[str, ...]) -> str:
        if not facts:
            return ""
        snapshot.vision_facts = tuple(facts)
        return VISION_TRACE_MARKER

    # đếm số chu kỳ lặp lại bối cảnh

    #theo dõi “bối cảnh autonomous có đang lặp lại không”.



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







    # Chọn thời gian ngủ ngẫu nhiên giữa các chu kỳ autonomous khi quyết định không nói gì,
    #  để tránh tạo pattern lặp lại quá đều đặn.
    def _choose_autonomous_sleep_duration(self, *, suppressed: bool, ti_mode: str) -> int:
        if suppressed:
            base = random.choice(self.autonomous_suppressed_sleep_seconds)
            silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0)
            # Nếu đã im nhiều vòng, đừng ngủ như thể vừa nói xong. Đây là nhịp tim,
            # không phải nhân viên văn phòng nghỉ sau khi không làm gì.
            if silent_cycles >= 6:
                return max(8, min(base, 12))
            if silent_cycles >= 3:
                return max(10, min(base, 18))
            return base
        return random.choice(self.autonomous_sleep_seconds)



























    def _process_pending_user_input(self) -> bool:
        msg = self.transport.poll_json()
        if not msg:
            return False
        self._handle_incoming(msg)
        return self.chat_mode or not self.running or self._stage_channel_blocked("autonomous")

    def _conversation_went_stale(self) -> bool:
        """True nếu đang chat_mode nhưng lượt user cuối đã hết "tươi".

        chat_mode không còn là công tắc bật/tắt thủ công mà là trạng thái suy ra
        từ độ tươi của hội thoại: bạn ngừng gõ quá ``_chat_fresh_seconds`` thì
        autonomous tự quay lại nhịp ambient, dù panel vẫn mở. Cũng là lưới an
        toàn nếu gói ``chat_end`` rớt trên UDP. Đặt ERIS_CHAT_FRESH_SEC<=0 để tắt.
        """
        if not self.chat_mode:
            return False
        window = float(getattr(self, "_chat_fresh_seconds", 0.0) or 0.0)
        if window <= 0.0:
            return False
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            return bool(clock.stale(window))
        last = float(getattr(self, "_chat_last_activity_at", 0.0) or 0.0)
        if last <= 0.0:
            return False
        return (time.time() - last) >= window

    def _run_loop_iteration(self) -> bool:
        """Đường autonomous production duy nhất: Architecture C + Cortex V2."""
        orchestrator = getattr(self, "ai_autonomous_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error(
                "[architecture C] autonomous unavailable: runtime bootstrap failed; legacy path removed"
            )
            self.stop()
            return False
        return bool(orchestrator.run_iteration())

    def run_loop(self):
        """Chạy runtime production duy nhất: Architecture C + Cortex V2."""
        self.logger.info("--- Architecture C runtime; chat vision theo yêu cầu màn hình ---")
        orchestrator = getattr(self, "ai_autonomous_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error("[architecture C] bootstrap failed; legacy runtime has been removed")
            self.stop()
            return

        startup_failed = False
        try:
            orchestrator.run_startup()
        except Exception as exc:
            startup_failed = True
            self._ai_startup_ran = False
            formatted = " | ".join(
                line.strip() for line in traceback.format_exc().strip().splitlines() if line.strip()
            )
            self.logger.warning(
                "[architecture C startup] failed type=%s message=%s trace=%s",
                type(exc).__name__,
                str(exc)[:300],
                formatted[:1800],
            )

        if not self.running:
            return
        worker = getattr(self, "screen_text_worker", None)
        if worker is not None:
            try:
                worker.start()
            except Exception as exc:
                self.logger.warning("[screen text] start error: %s", exc)
        # Startup là public presence quan trọng, không phải fire-and-forget. Nếu
        # lần đầu vấp do worker/client vừa bootstrap, thử lại đúng một lần sau khi
        # sensory worker đã lên. Không loop vô hạn, con người đã có đủ startup
        # ritual tự sinh rồi.
        if startup_failed and self.running:
            try:
                time.sleep(0.20)
                orchestrator.run_startup()
            except Exception as exc:
                self._ai_startup_ran = False
                formatted = " | ".join(
                    line.strip() for line in traceback.format_exc().strip().splitlines() if line.strip()
                )
                self.logger.error(
                    "[architecture C startup retry] failed type=%s message=%s trace=%s",
                    type(exc).__name__, str(exc)[:300], formatted[:1800],
                )

        while self.running:
            try:
                if not self._run_loop_iteration():
                    break
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                formatted = " | ".join(
                    line.strip()
                    for line in traceback.format_exc().strip().splitlines()
                    if line.strip()
                )
                self.logger.error("Unhandled exception inside run_loop; continuing. %s", formatted)
                time.sleep(0.25)




    

    def _initialize_provider_registry(self) -> None:
        """Bọc component hiện tại vào registry typed, không rewrite nóng toàn repo."""
        from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
        from runtime.provider_adapters import build_provider_registry

        memory_provider = self.memory_kernel or self.memory_core
        self.provider_registry = build_provider_registry(
            action_executor=self.action_executor,
            speech_engine=getattr(self, "tts_engine", None),
            memory=memory_provider,
            budget_governor=GLOBAL_TOKEN_PRESSURE_GOVERNOR,
        )
        self._record_provider_health_snapshot(event="bootstrap")

    def bind_tts_engine(self, tts_engine) -> None:
        """Binding duy nhất khi TTS engine được tạo/hot-reload.

        ``vision.py`` trước đây gán attribute trực tiếp, khiến registry và
        VoiceManager không biết engine đã đổi. Giờ cả ba cùng nhận một instance.
        """
        self.tts_engine = tts_engine
        try:
            self.voice_manager.bind_tts_engine(tts_engine)
        except Exception:
            pass
        try:
            from runtime.provider_adapters import SpeechEngineProvider, register_or_replace
            from runtime.provider_interfaces import ProviderRegistry

            registry = getattr(self, "provider_registry", None)
            if not isinstance(registry, ProviderRegistry):
                self._initialize_provider_registry()
                registry = self.provider_registry
            register_or_replace(registry, "speech", SpeechEngineProvider(tts_engine))
            self._record_provider_health_snapshot(event="speech_bind")
        except Exception as exc:
            self.logger.warning("Không bind được speech provider: %s", exc)

    def _provider_registry_is_strict(self) -> bool:
        config = getattr(self, "hardening_config", None)
        if config is None:
            try:
                from runtime.hardening_config import HardeningConfig

                config = HardeningConfig.load()
                self.hardening_config = config
            except Exception:
                return True
        return bool(getattr(config, "provider_registry_strict", True))

    def _get_runtime_provider(self, kind: str):
        registry = getattr(self, "provider_registry", None)
        if registry is None:
            return None
        try:
            return registry.get_optional(kind)
        except Exception:
            return None

    def _execute_action_provider(self, action_name: str, action_input: str = ""):
        provider = self._get_runtime_provider("action")
        if provider is None:
            raise RuntimeError("action_provider_unavailable")
        return provider.execute(action_name, action_input)

    def query_memory_provider(self, request):
        provider = self._get_runtime_provider("memory")
        if provider is None:
            raise RuntimeError("memory_provider_unavailable")
        return provider.query(request)

    def commit_memory_provider(self, record):
        provider = self._get_runtime_provider("memory")
        if provider is None:
            raise RuntimeError("memory_provider_unavailable")
        return provider.commit(record)

    def plan_budget_provider(self, *, provider: str, lane: str, prompt_tokens: int, output_tokens: int):
        budget = self._get_runtime_provider("budget")
        if budget is None:
            raise RuntimeError("budget_provider_unavailable")
        return budget.plan(
            provider=provider, lane=lane, prompt_tokens=prompt_tokens, output_tokens=output_tokens
        )

    def provider_health_snapshot(self) -> dict[str, dict]:
        registry = getattr(self, "provider_registry", None)
        if registry is None:
            return {}
        output: dict[str, dict] = {}
        try:
            health = registry.health()
        except Exception:
            return output
        for kind, item in health.items():
            output[str(kind)] = {
                "ready": bool(getattr(item, "ready", False)),
                "provider": str(getattr(item, "provider", "") or ""),
                "reason": str(getattr(item, "reason", "") or ""),
                "details": dict(getattr(item, "details", {}) or {}),
            }
        return output

    def _record_provider_health_snapshot(self, *, event: str) -> None:
        snapshot = self.provider_health_snapshot()
        obs = getattr(self, "observability", None)
        if obs is None:
            return
        for kind, item in snapshot.items():
            try:
                obs.gauge(
                    "provider_ready",
                    1.0 if item.get("ready") else 0.0,
                    tags={"kind": kind, "provider": item.get("provider", "unknown")},
                    fields={"event": event, "reason": item.get("reason", "")},
                )
            except Exception:
                pass
        try:
            obs.log(
                "provider_health_snapshot",
                tags={"event": event},
                fields={"providers": snapshot},
                status="ok" if all(item.get("ready") for item in snapshot.values()) else "error",
            )
        except Exception:
            pass


    def _execute_system_action(self, decision: Decision, *, snapshot, frame=None) -> Decision:
        # Phòng thủ tương thích: model/frame cũ có thể còn phát action đã nghỉ hưu.
        # Bỏ action nhưng giữ nguyên câu trả lời, không cho lỗi executor chen vào chat.
        if str(getattr(decision, "system_action", "") or "").strip() == "search_web":
            decision.system_action = ""
            decision.action_input = ""
            decision.debug_trace = self._join_debug_trace(
                getattr(decision, "debug_trace", ""),
                "retired_search_web_suppressed",
            )
            return decision
        if self.action_executor is None or not decision.system_action:
            return decision

        result = self._execute_action_provider(decision.system_action, decision.action_input)
        decision.action_result_meta = result.to_public_meta()
        if frame is not None:
            try:
                frame.tool_execution_result = result
            except Exception:
                pass
        recorder = getattr(self, "_record_tool_grounding", None)
        if callable(recorder):
            recorder(result, action_name=decision.system_action)
        action_trace = f"action={result.action_name}:{'ok' if result.success else 'fail'}:{result.public_mode}"
        if decision.debug_trace:
            decision.debug_trace = f"{decision.debug_trace} | {action_trace}"[:240]
        else:
            decision.debug_trace = action_trace
        result_text = self._action_result_to_text(result)
        # Tool/action là nguồn sự thật cuối. Không được để model giữ câu "đã làm"
        # khi executor fail hoặc action bị alias/sanitize. Báo thành công giả là cách
        # nhanh nhất để biến assistant thành cái đài phát thanh của niềm tin mù quáng.
        action_owns_text = {
            "get_local_time",
            "get_now_playing",
            "get_weather",
            "open_url",
            "focus_window",
            "set_volume",
            "play_pause_media",
            "copy_text",
            "launch_app",
            "review_discourse_claim",
            "inspect_unresolved_questions",
            "inspect_memory_candidates",
            "compare_recent_turns",
            "inspect_social_state",
            "detect_internal_contradictions",
            "summarize_open_loops",
            "inspect_capability_health",
        }
        if (not result.success) or (result.action_name in action_owns_text) or (not decision.text.strip()):
            decision.text = result_text
            decision.should_speak = bool(str(result_text or "").strip())
            if not result.success:
                decision.confidence = min(float(getattr(decision, "confidence", 0.0) or 0.0), 0.45)
                decision.extracted_fact = {}
        if result.action_name == "get_now_playing" and "media session" in decision.text.lower():
            decision.text = self._resolve_now_playing_text(snapshot) or decision.text
        return decision

    def _action_animation_hint(self, action_name: str, fallback: str) -> str:
        if action_name == "get_now_playing":
            return "read"
        if action_name in {
            "review_discourse_claim", "inspect_unresolved_questions",
            "inspect_memory_candidates", "compare_recent_turns",
            "inspect_social_state", "detect_internal_contradictions",
            "summarize_open_loops", "inspect_capability_health",
        }:
            return "read"
        if action_name in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        if action_name in {"copy_text", "set_volume", "play_pause_media"}:
            return "stand"
        return fallback or "stand"

    def _action_result_to_text(self, result) -> str:
        """Public surface chỉ được mạnh bằng execution evidence hiện có."""
        return public_action_text(result)

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
