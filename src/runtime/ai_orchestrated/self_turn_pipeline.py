# -*- coding: utf-8 -*-
"""Autonomous public-turn pipeline với một authority quyết định semantic.

Production order (V30 neuro transaction):
1. Perception/memory/needs assemble a bounded cognitive snapshot.
2. Subject Core builds grounded proposals; NeuroActionSelector releases a clear
   winner without an LLM or invites one-shot deliberation only on real conflict.
3. InitiativeController owns timing, concurrency and public obligations.
4. DeepSeek Surface owns wording only; it does not own thread/runtime identity.
5. Before public commit, the SessionTurnLedger revision must still match the
   generation captured before deliberation. A newer public turn cancels the work.
6. Grounding, public lifecycle, TTS and Live2D commit remain runtime-owned.

Temporal follow-up state is derived from the public ledger. No hidden reminder
state machine is allowed beside it.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.affective_voice_state import project_affective_voice_state
from runtime.grounding_surface_gate import evaluate_grounded_surface
from runtime.json_boundary import public_payload

from .activity_session import ActivitySession, ActivitySessionTracker
from .ambient_screen_context import AmbientScreenContext, AmbientScreenTracker
from .autonomous_trace import public_turn_trace_store
from .commentary_cadence import CommentaryCadence, CommentaryExpectation
from .cognitive_blackboard import TypedCognitiveBlackboard
from .contracts import AI_RUNTIME_VERSION, IntentionPlan, StateEvent
from .discourse_state import DiscourseState, DiscourseStateBuilder
from .desktop_semantics import DesktopSemanticRuntime, UserSituation
from .environment_event_bus import EnvironmentEventBus, NormalizedEnvironmentEvent
from .task_graph import TaskGraph
from .region_memory import RegionMemory
from .semantic_environment_worker import SemanticEnvironmentWorker
from .followup_appraisal import FollowUpAppraisalLayer
from .identity import PendingStrategyUse
from .initiative import InitiativeAction, InitiativeDecision
from .random_chat_seed import seed_event_family
from .self_context import AutonomousSelfContext, build_autonomous_self_context
from runtime.engagements import InteractionDecision
from runtime.temporal_mind import TemporalMind, TemporalSignal
from runtime.runtime_status import emit_runtime_status
from runtime.world_state import attach_world_state_projection
from runtime.subject_initiative_runtime import (
    build_initiative_runtime_context,
    build_subject_initiative_affordances,
    coalesce_contact_probe_affordances,
    filter_affordances_by_proposal_lifecycle,
)
from runtime.proposal_lifecycle import ensure_proposal_lifecycle_runtime


def environment_social_gate(situation: UserSituation | None) -> dict[str, Any]:
    """Tính social gate từ UserSituation theo đúng Deep Environment Stage F.

    Hàm thuần để test được trực tiếp, tránh chuyện một nhánh planner vô tình
    dùng threshold khác nhánh relational rồi cả hệ thống tranh luận với chính nó.
    """
    interruption = float(getattr(situation, "interruption_cost", 0.0) or 0.0) if situation is not None else 0.0
    busy = float(getattr(situation, "busy_score", 0.0) or 0.0) if situation is not None else 0.0
    phase = str(getattr(situation, "phase", "") or "").strip().lower() if situation is not None else ""
    attention = int(getattr(situation, "max_attention_level", 0) or 0) if situation is not None else 0
    active_work_phase = phase in {"implementation", "testing", "debugging", "diagnosis"}
    suppressed = bool(
        interruption >= 0.60
        or attention >= 2
        or (active_work_phase and busy >= 0.70)
    )
    return {
        "suppressed": suppressed,
        "interruption_cost": max(0.0, min(1.0, interruption)),
        "busy_score": max(0.0, min(1.0, busy)),
        "phase": phase,
        "attention_level": max(0, min(4, attention)),
    }


@dataclass(frozen=True, slots=True)
class PerceptionBundle:
    now: float
    snapshot: Any
    telemetry: Mapping[str, Any]
    screen: AmbientScreenContext
    vision_facts: tuple[Any, ...]
    observer_frame: Any = None
    user_situation: UserSituation | None = None
    environment_events: tuple[NormalizedEnvironmentEvent, ...] = ()

    @property
    def mechanical_delta(self) -> bool:
        return bool(self.screen.meaningful_delta or self.screen.window_changed)


@dataclass(frozen=True, slots=True)
class SelfTurnBundle:
    perception: PerceptionBundle
    state: Any
    turn_seq: int
    recent_history: tuple[Mapping[str, Any], ...]
    seconds_since_user: float
    seconds_since_assistant: float
    discourse: DiscourseState
    activity: ActivitySession
    self_context: AutonomousSelfContext
    memory_context: str
    shared_semantic_context: Mapping[str, Any]
    semantic_prompt_context: str
    engagement_context: Mapping[str, Any]
    engagement_prompt_context: str
    engagement_interaction: InteractionDecision
    commentary: CommentaryExpectation
    # Public ledger revision captured before deliberation. It is an MVCC-style
    # generation token, not another lifecycle flag.
    public_revision: int

    @property
    def now(self) -> float:
        # Chú thích VI: trước V92 timestamp nằm trực tiếp trên bundle; sau khi
        # tách PerceptionBundle, một số consumer hậu commit vẫn đọc context.now.
        # Giữ property tương thích tại boundary để refactor không làm self-turn
        # crash sau khi đã nói/TTS xong. Nguồn thời gian duy nhất vẫn là perception.
        return float(self.perception.now)


class SelfTurnPipeline:
    """Một authority semantic, nhiều adapter cơ học nhỏ."""

    def __init__(
        self,
        host: Any,
        *,
        next_turn_seq: Callable[..., int],
        commit_public: Callable[..., tuple[str, dict[str, Any] | None]],
        emit_body_only: Callable[..., bool],
    ) -> None:
        self.host = host
        self.next_turn_seq = next_turn_seq
        self.commit_public = commit_public
        self.emit_body_only = emit_body_only
        self.screen_tracker = AmbientScreenTracker()
        self.activity_tracker = ActivitySessionTracker()
        self.discourse_builder = DiscourseStateBuilder()
        # Lớp này quản lý chu kỳ hỏi -> nhắc một lần -> bỏ chủ đề. Nó sống cùng
        # pipeline để nhớ được lần nhắc giữa nhiều tick autonomous.
        self.followup_appraisal = FollowUpAppraisalLayer()
        self.trace_store = public_turn_trace_store(logger=getattr(host, "logger", None))
        self.commentary_cadence = CommentaryCadence()
        self._last_deliberation_at = 0.0
        self._last_probe_at = 0.0
        self._observer_thread: threading.Thread | None = None
        self._observer_thread_lock = threading.Lock()
        # Track N câu autonomous gần nhất riêng biệt với last_text (last_text bị
        # overwrite bởi chat reply sau mỗi lượt user, nên không đủ để tránh lặp câu
        # autonomous). Deque 4 phần tử bao phủ window đủ dài để Surface và utterance
        # gate nhận ra lặp chủ đề, không chỉ lặp câu chữ liền kề.
        import collections as _col
        self._recent_autonomous_texts: _col.deque[str] = _col.deque(maxlen=4)
        # Compatibility alias - một số nhánh cũ đọc _last_autonomous_text trực tiếp.
        self._last_autonomous_text: str = ""

        # V19: TemporalMind là state timing rẻ dùng chung cả chat/autonomous.
        # Nó không chọn nội dung; nó chỉ quyết định đã đáng đánh thức cognition
        # nặng chưa. Gắn lên host để user turn và public commit cùng cập nhật một
        # dòng thời gian, thay vì mỗi pipeline giữ một chiếc đồng hồ riêng.
        temporal = getattr(host, "temporal_mind", None)
        if temporal is None:
            temporal = TemporalMind()
            setattr(host, "temporal_mind", temporal)
        self.temporal_mind = temporal
        self._last_temporal_gate = None

        # Deep Environment: structured event là đường semantic chính; OCR/screen
        # chỉ còn fallback và tín hiệu body animation. Adapter accessibility được
        # dựng trước worker để event đầu tiên đã có thể enrich mà không chờ self-turn.
        self.environment_event_bus = EnvironmentEventBus()
        self.task_graph = TaskGraph()
        self.region_memory = RegionMemory()
        self.desktop_semantic_runtime = DesktopSemanticRuntime(task_graph=self.task_graph, region_memory=self.region_memory)
        setattr(host, "environment_region_memory", self.region_memory)
        self._last_environment_event_at = 0.0
        self._last_chromium_poll_at = 0.0
        self._native_event_broker = None
        self._chromium_accessibility = None
        self._uia_semantic_adapter = None

        if os.getenv("ERIS_UIA_EVENTS_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}:
            try:
                from native.uia_semantic_adapter import UIASemanticAdapter
                self._uia_semantic_adapter = UIASemanticAdapter()
                setattr(host, "uia_semantic_adapter", self._uia_semantic_adapter)
            except Exception as exc:
                host.logger.debug("[deep environment] UIA semantic adapter unavailable: %s", exc)

        chromium_enabled = os.getenv("ERIS_CHROMIUM_IA2_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        if chromium_enabled:
            try:
                from native.chromium_accessibility import ChromiumAccessibilityAdapter
                self._chromium_accessibility = ChromiumAccessibilityAdapter().start()
                setattr(host, "chromium_accessibility_adapter", self._chromium_accessibility)
            except Exception as exc:
                host.logger.debug("[deep environment] Chromium accessibility unavailable: %s", exc)

        # V4: semantic consumer chạy daemon event-driven. Từ đây native callback
        # chỉ publish + enqueue; TaskGraph/UserSituation không còn đợi self-turn
        # tick 0.8-6 giây mới được cập nhật.
        self._semantic_environment_worker = SemanticEnvironmentWorker(
            host=host,
            runtime=self.desktop_semantic_runtime,
            publish_event=self._publish_environment_event,
            uia_adapter=self._uia_semantic_adapter,
            chromium_adapter=self._chromium_accessibility,
        ).start()
        setattr(host, "semantic_environment_worker", self._semantic_environment_worker)

        if os.getenv("ERIS_NATIVE_EVENTS_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}:
            try:
                from native.windows_event_broker import WindowsEventBroker
                self._native_event_broker = WindowsEventBroker(self._publish_environment_event)
                self._native_event_broker.start()
                setattr(host, "native_environment_event_broker", self._native_event_broker)
            except Exception as exc:
                host.logger.debug("[deep environment] WinEvent broker unavailable: %s", exc)

        self._native_aux_monitors: list[Any] = []
        if os.getenv("ERIS_CLIPBOARD_MONITOR_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}:
            try:
                from native.clipboard_monitor import ClipboardMonitor
                clipboard = ClipboardMonitor(self._publish_environment_event)
                clipboard.start()
                self._native_aux_monitors.append(clipboard)
            except Exception as exc:
                host.logger.debug("[deep environment] clipboard listener unavailable: %s", exc)

        if os.getenv("ERIS_MEDIA_MONITOR_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}:
            try:
                from native.media_monitor import MediaMonitor
                media = MediaMonitor(self._publish_environment_event)
                media.start()
                self._native_aux_monitors.append(media)
            except Exception as exc:
                host.logger.debug("[deep environment] GSMTC media monitor unavailable: %s", exc)

        # UIAccess broker chỉ là client hẹp. Core Eris không nâng integrity và
        # tuyệt đối không tự chạy Administrator chỉ vì muốn đọc elevated UI.
        if os.getenv("ERIS_UIACCESS_BROKER_ENABLED", "0").strip().lower() not in {"0", "false", "off", "no"}:
            try:
                from native.uiaccess_broker import UIAccessBrokerClient
                setattr(host, "uiaccess_broker_client", UIAccessBrokerClient())
            except Exception as exc:
                host.logger.debug("[deep environment] UIAccess broker client unavailable: %s", exc)

        workspace_paths = os.getenv("ERIS_WORKSPACE_WATCH_PATHS", "").strip()
        if workspace_paths:
            try:
                from native.filesystem_monitor import FilesystemMonitor
                for raw_path in workspace_paths.split(os.pathsep):
                    path = raw_path.strip()
                    if not path:
                        continue
                    monitor = FilesystemMonitor(path, self._publish_environment_event)
                    monitor.start()
                    self._native_aux_monitors.append(monitor)
            except Exception as exc:
                host.logger.debug("[deep environment] workspace monitor unavailable: %s", exc)
        setattr(host, "native_environment_monitors", self._native_aux_monitors)

    def _publish_environment_event(self, event: NormalizedEnvironmentEvent) -> NormalizedEnvironmentEvent | None:
        """Publish event vào bus rồi giao ngay cho semantic worker.

        Callback native không làm UIA/TaskGraph tại đây. Ta chỉ đo ingress/publish
        bằng monotonic clock, publish privacy-safe event và enqueue non-blocking.
        """
        if os.getenv("ERIS_SEMANTIC_EVENT_BUS_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
            return None

        ingress_monotonic_ns = time.monotonic_ns()
        ingress_wall_time = time.time()
        publish_started_ns = time.monotonic_ns()
        accepted = self.environment_event_bus.publish(event)
        publish_done_ns = time.monotonic_ns()
        if accepted is None:
            return None

        observability = getattr(self.host, "observability", None)
        if observability is not None:
            try:
                provider = str((accepted.metadata or {}).get("provider", "") or accepted.source or "unknown")[:40]
                source_to_ingress_ms = max(0.0, (ingress_wall_time - float(accepted.timestamp or ingress_wall_time)) * 1000.0)
                publish_duration_ms = max(0.0, (publish_done_ns - publish_started_ns) / 1_000_000.0)
                tags = {
                    "source": accepted.source or "unknown",
                    "event_type": accepted.event_type or "unknown",
                    "provider": provider,
                }
                observability.increment(
                    "environment_event_total",
                    tags={
                        **tags,
                        "semantic": str(bool(accepted.semantic)).lower(),
                        "attention": str(max(0, min(4, int(accepted.attention_level or 0)))),
                        "privacy": str(accepted.privacy_scope or "SEMANTIC").lower(),
                    },
                )
                observability.observe("environment_source_to_ingress_ms", source_to_ingress_ms, tags=tags)
                source_callback_delay_ms = (accepted.metadata or {}).get("source_callback_delay_ms")
                if source_callback_delay_ms is not None:
                    # WinEvent dwmsEventTime -> callback delay thật, tách khỏi thời
                    # gian enrich/derived-event để biết provider thread có nghẽn hay không.
                    observability.observe(
                        "environment_source_callback_delay_ms",
                        max(0.0, float(source_callback_delay_ms or 0.0)),
                        tags=tags,
                    )
                observability.observe("environment_bus_publish_duration_ms", publish_duration_ms, tags=tags)
                # Tên cũ được giữ cho dashboard/probe tương thích. Từ V4 nó mang
                # nghĩa source -> ingress, không còn giả làm thời gian bus.publish().
                observability.observe("environment_event_to_bus_ms", source_to_ingress_ms, tags=tags)
            except Exception:
                pass

        # WinEvent chỉ báo "có thay đổi"; Chromium cache invalidate ở callback
        # vẫn nhẹ, còn poll/accessibility dereference sẽ chạy trong semantic worker.
        if self._chromium_accessibility is not None and accepted.source in {"winevent", "foreground_reconcile"}:
            try:
                self._chromium_accessibility.notify_native_event(accepted)
                if str(accepted.process_name or "").lower() in {"chrome.exe", "msedge.exe", "brave.exe", "chromium.exe"}:
                    self._last_chromium_poll_at = 0.0
            except Exception:
                pass

        worker = getattr(self, "_semantic_environment_worker", None)
        if worker is not None:
            try:
                worker.submit(
                    accepted,
                    ingress_monotonic_ns=ingress_monotonic_ns,
                    ingress_wall_time=ingress_wall_time,
                )
            except Exception as exc:
                self.host.logger.debug("[deep environment] semantic enqueue failed: %s", exc)

        screen_worker = getattr(self.host, "screen_text_worker", None)
        notify = getattr(screen_worker, "notify_environment_event", None)
        if callable(notify):
            try:
                # UIA/WinEvent/Chromium thường đã cover semantic region; OCR chỉ
                # được trigger khi structured source nói coverage chưa đủ.
                notify(accepted.event_type, structured_coverage=accepted.source not in {"screen_pixel", "vision"})
            except Exception:
                pass
        return accepted

    def _collect_environment_events(self, now: float, telemetry: Mapping[str, Any]) -> tuple[NormalizedEnvironmentEvent, ...]:
        """Chỉ làm reconciliation source; semantic consume đã chuyển sang worker.

        Tên hàm được giữ để patch không làm gãy adapter/test cũ, nhưng không còn
        drain bus hay UIA-enrich trên self-turn. Event đã được worker xử lý ngay từ
        lúc ``_publish_environment_event`` nhận callback native.
        """
        worker = getattr(self, "_semantic_environment_worker", None)
        if worker is not None:
            try:
                worker.update_telemetry(telemetry)
            except Exception:
                pass

        # Foreground telemetry là safety net khi WinEvent hook lỡ transition lúc
        # startup/reconciliation. Nó level 1 nên không tự đánh thức cognition.
        if bool(telemetry.get("focus_changed", False)):
            self._publish_environment_event(NormalizedEnvironmentEvent(
                timestamp=now, source="foreground_reconcile", event_type="foreground_changed", action="focus_changed",
                process_name=str(telemetry.get("active_process", "") or ""),
                pid=int(telemetry.get("foreground_pid", 0) or 0), hwnd=int(telemetry.get("foreground_hwnd", 0) or 0),
                window_class=str(telemetry.get("window_class", "") or ""), role="window",
                title=str(telemetry.get("active_window_title", "") or ""), source_confidence=0.96, confidence=0.96,
                novelty=0.65, importance=0.18, user_relevance=0.55, attention_level=1,
                evidence_refs=("telemetry:foreground_reconcile",),
            ))

        # Reconcile Chromium 15s vẫn tồn tại như safety net. Event-triggered IA2/UIA
        # refresh đã nằm trong semantic worker nên tab switch bình thường không chờ
        # cadence này.
        chromium_enabled = os.getenv("ERIS_CHROMIUM_IA2_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        if chromium_enabled and now - self._last_chromium_poll_at >= 15.0:
            self._last_chromium_poll_at = now
            try:
                if self._chromium_accessibility is None:
                    from native.chromium_accessibility import ChromiumAccessibilityAdapter
                    self._chromium_accessibility = ChromiumAccessibilityAdapter().start()
                    if worker is not None:
                        worker.set_chromium_adapter(self._chromium_accessibility)
                for event in self._chromium_accessibility.poll_all():
                    self._publish_environment_event(event)
            except Exception as exc:
                self.host.logger.debug("[deep environment] chromium accessibility reconcile failed: %s", exc)

        # Structured events không còn được consume ở đây. Self-turn lấy danh sách
        # event đã xử lý qua build_perception_situation() để tránh backlog 13-18s.
        return ()

    def run(self) -> bool:
        host = self.host
        if not host.body_running_fn():
            host.stop()
            return False
        if host._process_pending_user_input():
            return host.running
        if not self._acquire_baton():
            return True

        now = time.time()
        social_continuation_runtime = getattr(host, "ai_social_continuation_runtime", None)
        conversation_arc_runtime = getattr(host, "ai_conversation_arc_runtime", None)
        neuro_continuation_runtime = getattr(host, "neuro_continuation_runtime", None)
        clock = getattr(host, "interaction_clock", None)
        interaction_busy = bool(getattr(clock, "busy", False)) if clock is not None else False
        # V66: không còn global "presence blocked" trước cognition. Sau một
        # public turn, runtime chỉ ghi turn-collision vào context; ERIS vẫn được
        # tiếp tục suy nghĩ và hình thành commitment. Boundary đó chỉ DEFER lúc
        # materialize speech, nên không biến user activity thành thuốc mê nội tâm.

        phase_started = time.monotonic()
        perception = self._assemble_perception(now)
        perception_ms = (time.monotonic() - phase_started) * 1000.0
        phase_started = time.monotonic()
        context = self._assemble_context(perception)
        context_ms = (time.monotonic() - phase_started) * 1000.0
        phase_started = time.monotonic()
        planner_snapshot, discovery_runtime = self._planner_snapshot(context)
        # V26: cùng một motive context được dùng cho chat và self-turn. Random
        # seed chỉ còn là một nguồn nội dung tùy chọn, không còn là điều kiện để
        # Subject có lý do chủ động.
        initiative_runtime_context = build_initiative_runtime_context(host)
        planner_snapshot["initiative_runtime_context"] = dict(initiative_runtime_context)

        # V71: autonomous không được "quên" user request chỉ vì user_text hiện tại
        # rỗng. Handoff giữ owner của lượt kế tiếp + open-loop thật và đi vào cùng
        # Subject/Neuro frame với rumination/initiative candidates.
        try:
            from runtime.conversation_handoff import ensure_conversation_handoff_runtime
            handoff_runtime = ensure_conversation_handoff_runtime(host)
            handoff_state = handoff_runtime.refresh_shared_goal(
                initiative_runtime_context.get("active_goal_text", ""),
                semantic_owner=initiative_runtime_context.get("active_goal_owner", "unknown"),
                evidence_refs=tuple(initiative_runtime_context.get("active_goal_evidence_refs", ()) or ()),
                now=now,
            )
            planner_snapshot["conversation_handoff"] = handoff_state.to_dict()
            from runtime.conversation_trajectory import ensure_conversation_trajectory_runtime
            trajectory_state = ensure_conversation_trajectory_runtime(host).snapshot(now=now)
            planner_snapshot["conversation_trajectory"] = trajectory_state.to_dict()
            planner_snapshot["causal_discourse"] = {
                "self_caused_reaction_probability": handoff_state.self_caused_reaction_probability,
                "repair_needed": handoff_state.repair_needed,
                "hypotheses": [item.to_dict() for item in handoff_state.causal_hypotheses],
            }
        except Exception as exc:
            host.logger.debug("[conversation handoff v71] autonomous projection failed: %s", exc)

        # V74: Courtesy + Life-Horizon đi vào planning snapshot trước khi Subject
        # dựng frame. Courtesy là hard turn boundary; Life-Horizon chỉ là goal
        # modulation. Hai tín hiệu được giữ tách biệt để tránh biến heuristic
        # hội thoại thành quyền phủ quyết không có state typed.
        try:
            from runtime.conversation_courtesy import ensure_conversation_courtesy
            courtesy_runtime = ensure_conversation_courtesy(host)
            planner_snapshot["conversation_courtesy"] = courtesy_runtime.runtime_context(now=now)
        except Exception as exc:
            planner_snapshot["conversation_courtesy"] = {}
            host.logger.debug("[courtesy-v74] autonomous projection failed: %s", exc)
        try:
            from runtime.life_horizon import ensure_life_horizon_manager
            life_horizon = ensure_life_horizon_manager(host)
            planner_snapshot["life_horizon"] = life_horizon.refresh_from_runtime(now=now).to_dict()
        except Exception as exc:
            planner_snapshot["life_horizon"] = {}
            host.logger.debug("[life-horizon-v74] autonomous projection failed: %s", exc)
        # V77: Persistent Individual Core đưa Interaction Ecology + Relational Plan + Continuous Self
        # vào autonomous snapshot. Đây là context/bias, không phải quyền ép nói.
        try:
            from runtime.persistent_individual import ensure_persistent_individual_runtime
            individual_runtime = ensure_persistent_individual_runtime(host)
            planner_snapshot["persistent_individual"] = individual_runtime.projection_for_host(
                host, now=now, context_key="autonomous"
            )
        except Exception as exc:
            planner_snapshot["persistent_individual"] = {}
            host.logger.debug("[persistent-individual-v77] autonomous projection failed: %s", exc)
        # V44: chỉ một urge đã có nội dung mới được quyền đánh thức cognition vì
        # "muốn nói". Connection pressure trừu tượng không còn tự biến thành wake.
        expression_urge_runtime = getattr(host, "expression_urge_runtime", None)
        if expression_urge_runtime is not None:
            try:
                planner_snapshot["expression_urge_pressure"] = float(
                    expression_urge_runtime.wake_pressure(now=now)
                )
            except Exception as exc:
                planner_snapshot["expression_urge_pressure"] = 0.0
                host.logger.debug("[expression urge] cheap wake projection failed: %s", exc)
        mental_material_runtime = getattr(host, "mental_material_runtime", None)
        if mental_material_runtime is not None:
            try:
                planner_snapshot["mental_material_pressure"] = float(
                    mental_material_runtime.wake_pressure(now=now)
                )
            except Exception as exc:
                planner_snapshot["mental_material_pressure"] = 0.0
                host.logger.debug("[mental material] cheap wake projection failed: %s", exc)
        # V101: một intention đang forming/considering cũng là private state sống
        # có thể đáng đánh thức cognition ở tick sau. Nó chưa phải speech urge.
        private_intention_runtime = getattr(host, "private_intention_runtime_v101", None)
        if private_intention_runtime is not None:
            try:
                planner_snapshot["private_intention_pressure"] = float(
                    private_intention_runtime.wake_pressure(now=now)
                )
            except Exception as exc:
                planner_snapshot["private_intention_pressure"] = 0.0
                host.logger.debug("[private-intention-v101] cheap wake projection failed: %s", exc)
        seed_reservoir = getattr(host, "ai_random_chat_seed_reservoir", None)
        if seed_reservoir is not None:
            try:
                seed_reservoir.update_context(planner_snapshot, now=now)
            except Exception as exc:
                host.logger.debug("[random chat seed] context publish failed: %s", exc)
        snapshot_ms = (time.monotonic() - phase_started) * 1000.0
        should_deliberate, trigger_reason = self._should_deliberate(context, planner_snapshot)
        if not should_deliberate:
            gate = self._last_temporal_gate
            self.trace_store.append("attention_skip", {
                "turn_seq": context.turn_seq,
                "trigger_reason": trigger_reason,
                "screen_delta": perception.mechanical_delta,
                "discourse_mode": context.discourse.mode,
                "has_public_seed": context.self_context.has_public_seed,
                "temporal": gate.to_dict() if gate is not None else {},
            }, now=now)
            # Quiet path phải rẻ nhưng vẫn có nhịp. Không ngủ 8–24 giây rồi mới
            # nhìn lại thế giới; tick 1.5–5.5 giây chỉ cập nhật state, chưa gọi LLM.
            delay = float(getattr(gate, "next_check_seconds", 5.0) or 5.0)
            host._sleep_interruptible(max(0.8, min(6.0, delay)))
            return True

        self._last_deliberation_at = now
        self.temporal_mind.mark_heavy_deliberation(now=now)
        # V42: cognition nền là private state, không phải public lifecycle.
        # Không treo banner "đang nghĩ/chuẩn bị nói" trong lúc Neuro còn chưa
        # hề commit speech; nếu không UI sẽ sáng gần như suốt phiên chạy.

        # Collect-before-claim: every source exposes a typed affordance, Gemma
        # chooses one exact ID, and only then may runtime reserve it.  No Python
        # source order is allowed to become conversational priority.
        blackboard = TypedCognitiveBlackboard.from_snapshot(planner_snapshot, now=now)
        candidate_started = time.monotonic()
        candidate = None
        affordances: list[Any] = []
        worker_id = f"self_turn:{threading.get_ident()}"

        if social_continuation_runtime is not None:
            try:
                preview = social_continuation_runtime.peek_due(
                    now=now, interaction_busy=interaction_busy
                )
                if preview is not None:
                    affordances.append(preview)
            except Exception as exc:
                host.logger.debug("[social continuation] affordance peek failed: %s", exc)

        if conversation_arc_runtime is not None:
            try:
                preview = conversation_arc_runtime.peek_due(
                    now=now, interaction_busy=interaction_busy
                )
                if preview is not None:
                    affordances.append(preview)
            except Exception as exc:
                host.logger.debug("[conversation arc] affordance peek failed: %s", exc)

        if neuro_continuation_runtime is not None:
            try:
                preview = neuro_continuation_runtime.peek_due(
                    now=now, interaction_busy=interaction_busy
                )
                if preview is not None:
                    affordances.append(preview)
            except Exception as exc:
                host.logger.debug("[neuro-continuation] affordance peek failed: %s", exc)

        social_agenda_store = getattr(host, "ai_social_agenda_store", None)
        if social_agenda_store is not None:
            try:
                preview = social_agenda_store.peek_due(blackboard, now=now)
                if preview is not None:
                    affordances.append(preview)
            except Exception as exc:
                host.logger.debug("[social agenda] affordance peek failed: %s", exc)

        agenda_selector = getattr(host, "ai_social_agenda_selector", None)
        if agenda_selector is not None:
            try:
                collector = getattr(agenda_selector, "collect_affordances", None)
                if callable(collector):
                    affordances.extend(collector(blackboard, snapshot=planner_snapshot))
            except Exception as exc:
                host.logger.debug("[social initiative] affordance collection failed: %s", exc)

        # V44: relational homeostasis chỉ là lực điều biến. Nó không còn quyền
        # tự materialize thành ``contact_bid`` rồi bắt Surface bịa một câu hỏi
        # xã giao cho đủ thủ tục. Muốn nói phải có contentful urge ở phía dưới.
        subject_service = getattr(host, "subject_service", None)
        relational_view: Mapping[str, Any] = {}
        relational_view_fn = getattr(subject_service, "relational_view", None)
        if callable(relational_view_fn):
            try:
                relational_view = relational_view_fn(now=now)
                relational_view = relational_view if isinstance(relational_view, Mapping) else {}
                planner_snapshot["relational_state"] = dict(relational_view)
                host.logger.debug(
                    "[relational] modulation pressure=%.2f opportunity=%.2f drive=%.2f revision=%s",
                    float(relational_view.get("connection_pressure", 0.0) or 0.0),
                    float(relational_view.get("opportunity", 0.0) or 0.0),
                    float(relational_view.get("outreach_drive", 0.0) or 0.0),
                    relational_view.get("revision", 0),
                )
            except Exception as exc:
                host.logger.debug("[relational] state projection failed: %s", exc)

        # V44: Subject motive vẫn tồn tại, nhưng chỉ intention có semantic object
        # cụ thể mới được materialize. ``muốn kết nối``/``muốn hiểu user`` chung
        # chung không còn được phép tự hóa thành câu hỏi xã giao.
        if subject_service is not None:
            try:
                initiative_affordances = build_subject_initiative_affordances(
                    subject_service,
                    runtime_context=initiative_runtime_context,
                    now=now,
                    interaction_busy=interaction_busy,
                )
                affordances.extend(initiative_affordances)
                if initiative_affordances:
                    host.logger.info(
                        "[subject initiative] affordances=%s kinds=%s",
                        len(initiative_affordances),
                        ",".join(
                            str(getattr(item.candidate, "speech_act", "") or "")
                            for item in initiative_affordances
                        ),
                    )
            except Exception as exc:
                host.logger.debug("[subject initiative] affordance build failed: %s", exc)

        # ``contact_bid`` (relational homeostasis) and ``user_probe`` (initiative)
        # are alternative realizations of one immediate contact objective. Collapse
        # them before Subject competition so entropy reflects real alternatives,
        # not duplicate social phrasing channels.
        before_social_coalesce = len(affordances)
        affordances = list(coalesce_contact_probe_affordances(
            affordances,
            runtime_context=initiative_runtime_context,
        ))
        if len(affordances) != before_social_coalesce:
            host.logger.info(
                "[social coalesce] contact/probe collapsed before subject frame before=%s after=%s uncertainty=%.2f",
                before_social_coalesce,
                len(affordances),
                float(initiative_runtime_context.get("user_model_uncertainty", 0.72) or 0.72),
            )

        # Deduplicate only by stable ID after semantic coalescing. Distinct meanings
        # from different owners remain visible to Subject Core/neuro competition.
        unique_affordances: list[Any] = []
        seen_affordance_ids: set[str] = set()
        for affordance in affordances:
            affordance_id = str(getattr(affordance, "affordance_id", "") or "")
            if not affordance_id or affordance_id in seen_affordance_ids:
                continue
            seen_affordance_ids.add(affordance_id)
            unique_affordances.append(affordance)
        affordances = unique_affordances

        # V94: Neuro chọn silence là một outcome có nghĩa. Cùng proposal + cùng
        # evidence không được quay lại frame sau 4-5 giây chỉ vì scheduler tick.
        # Evidence mới sẽ reset backoff ngay trong runtime lifecycle.
        affordances = list(filter_affordances_by_proposal_lifecycle(host, affordances, now=now))

        # V44 giữ đúng một authority projection cho policy. Tập affordance còn
        # phải đi qua content-first shaping ở dưới, nên nếu tính cost tại đây rồi
        # tính lại lần nữa ta sẽ có hai ảnh chụp policy cho cùng một tick.
        initiative_policy = getattr(host, "ai_initiative_controller", None)

        # V43: current mood được quyền nghiêng attention/selection nhẹ trước
        # Neuro, nhưng không được tự chọn action hay nới grounding. Đây chỉ là
        # typed bias, cùng triết lý policy-cost của V42.
        try:
            from cortex.affective_dynamics import affective_selection_bias
            planner_snapshot["affective_selection_bias"] = affective_selection_bias(host._get_internal_state())
        except Exception as exc:
            host.logger.debug("[affect-v43] selection bias degraded: %s", exc)

        active_concerns: tuple[dict[str, Any], ...] = ()
        material_concern_affordances: tuple[Any, ...] = ()
        # V101 production không dùng direct material-expression projection nữa.
        private_intention_affordances: tuple[Any, ...] = ()
        private_intention_inputs: tuple[dict[str, Any], ...] = ()

        # V101 cutover: MentalMaterial vẫn sở hữu thought/concern lifecycle, nhưng
        # production KHÔNG đưa ``expression_pull >= 0.60`` thẳng sang ExpressionUrge.
        # project() legacy vẫn tồn tại cho compatibility; expression half của nó
        # bị bỏ ở đây. PrivateIntentionField mới sở hữu transition thought -> intent.
        mental_material_runtime = getattr(host, "mental_material_runtime", None)
        if mental_material_runtime is not None:
            try:
                material_concern_affordances, _legacy_direct_expression = mental_material_runtime.project(
                    now=now, limit=8
                )
                private_intention_inputs = mental_material_runtime.private_intention_inputs(
                    now=now, limit=16
                )
                material_snapshot = mental_material_runtime.snapshot(now=now, limit=10)
                planner_snapshot["mental_materials"] = [dict(item) for item in material_snapshot]
                planner_snapshot["mental_material_pressure"] = max(
                    (max(float(item.get("expression_pull", 0.0) or 0.0), float(item.get("concern_pull", 0.0) or 0.0)) for item in material_snapshot),
                    default=0.0,
                )
                planner_snapshot["v101_direct_material_expression_route"] = False
            except Exception as exc:
                host.logger.debug("[mental material] projection failed: %s", exc)

        # V101: integrate cùng semantic object qua nhiều cognition ticks. Không có
        # global winner; mọi intention sống song song và chỉ READY mới projection
        # sang ExpressionUrge. Đây vẫn là private semantic target, chưa là SPEAK.
        private_intention_runtime = getattr(host, "private_intention_runtime_v101", None)
        if private_intention_runtime is not None:
            try:
                private_intention_runtime.observe_materials(private_intention_inputs, now=now)
                private_intention_affordances = private_intention_runtime.project_ready(now=now, limit=6)
                intention_snapshot = private_intention_runtime.snapshot(now=now, limit=10)
                planner_snapshot["private_intentions_v101"] = [dict(item) for item in intention_snapshot]
                planner_snapshot["private_intention_pressure"] = max(
                    (float(item.get("tendency", 0.0) or 0.0) for item in intention_snapshot),
                    default=0.0,
                )
                planner_snapshot["private_intention_ready_count"] = sum(
                    1 for item in intention_snapshot if str(item.get("state", "")) == "ready"
                )
            except Exception as exc:
                host.logger.debug("[private-intention-v101] projection failed: %s", exc)

        # V42: chỉ COGNITIVE EVENT MỚI được phép làm concern đổi state. Reservoir
        # có thể đưa lại cùng seed qua nhiều tick, nhưng event ledger sẽ consume đúng
        # một lần; các tick sau chỉ project/decay. Không còn "đọc lại = nghĩ lại".
        concern_runtime = getattr(host, "active_concern_runtime", None)
        if concern_runtime is not None:
            try:
                concern_runtime.ingest_affordances(
                    tuple(affordances) + tuple(material_concern_affordances), now=now
                )
                active_concerns = concern_runtime.snapshot(now=now, limit=8)
                planner_snapshot["active_concerns"] = [dict(item) for item in active_concerns]
                self.trace_store.append(
                    "active_concerns",
                    {
                        "turn_seq": context.turn_seq,
                        "count": len(active_concerns),
                        "items": [dict(item) for item in active_concerns[:4]],
                    },
                    now=now,
                )
            except Exception as exc:
                host.logger.debug("[active concern] projection failed: %s", exc)

        # V44: từ đây public competition chỉ nhìn những thứ Eris có *nội dung*
        # muốn biểu đạt. Relation/mood làm urge mạnh/yếu hơn nhưng không sinh topic.
        expression_urge_runtime = getattr(host, "expression_urge_runtime", None)
        if expression_urge_runtime is not None:
            try:
                affect_bias = planner_snapshot.get("affective_selection_bias")
                affect_bias = affect_bias if isinstance(affect_bias, Mapping) else {}
                current_state = host._get_internal_state()
                affect_for_urge = {
                    **dict(affect_bias),
                    "curiosity": float(getattr(current_state, "curiosity", 0.0) or 0.0),
                    "social_energy": float(getattr(current_state, "social_energy", 0.5) or 0.5),
                }
                # V102 cần đúng hard-boundary context tại thời điểm commitment.
                # Initiative context có public-turn/explicit-quiet; Courtesy bổ sung
                # awaiting_user_answer. Không đưa heuristic user-busy/reply-rate vào.
                commitment_context_v102 = dict(initiative_runtime_context)
                courtesy_for_commitment = planner_snapshot.get("conversation_courtesy")
                if isinstance(courtesy_for_commitment, Mapping):
                    for _key in ("awaiting_user_answer", "courtesy_hold"):
                        if _key in courtesy_for_commitment:
                            commitment_context_v102[_key] = bool(courtesy_for_commitment.get(_key, False))
                affordances = list(expression_urge_runtime.shape_affordances(
                    tuple(affordances) + tuple(private_intention_affordances),
                    active_concerns=active_concerns,
                    relational=relational_view,
                    affect=affect_for_urge,
                    runtime_context=commitment_context_v102,
                    now=now,
                    limit=3,
                ))
                urge_snapshot = expression_urge_runtime.snapshot(
                    now=now, relational=relational_view, affect=affect_for_urge, limit=6
                )
                planner_snapshot["expression_urges"] = [dict(item) for item in urge_snapshot]
                planner_snapshot["expression_urge_pressure"] = max(
                    (float(item.get("pressure", 0.0) or 0.0) for item in urge_snapshot),
                    default=0.0,
                )
                transition_v102 = getattr(host, "expression_commitment_transition_v102", None)
                transition_snapshot = getattr(transition_v102, "snapshot", None)
                if callable(transition_snapshot):
                    commitment_rows_v102 = transition_snapshot(now=now, limit=10)
                    planner_snapshot["expression_commitment_transitions_v102"] = [
                        dict(item) for item in commitment_rows_v102
                    ]
                    planner_snapshot["expression_commitment_v102_count"] = sum(
                        1 for item in commitment_rows_v102
                        if str(item.get("state", "")) == "committed"
                    )
                planner_snapshot["v102_expression_urge_direct_commitment"] = False
            except Exception as exc:
                host.logger.debug("[expression urge] shaping failed: %s", exc)

        # Policy chạy sau khi materialize urge để đo đúng mật độ/repetition của
        # tập candidate hiện tại. V67: đây chỉ là self-rhythm telemetry cho các
        # opportunity chưa commit; một ExpressionCommitment không bị vote lại.
        if initiative_policy is not None:
            try:
                policy_signals = initiative_policy.policy_signals(blackboard, affordances)
                planner_snapshot["initiative_policy_signals"] = dict(policy_signals)
                if policy_signals:
                    initiative_runtime_context = dict(initiative_runtime_context)
                    initiative_runtime_context["initiative_policy_max_cost"] = max(
                        float(item.get("total_cost", 0.0) or 0.0)
                        for item in policy_signals.values() if isinstance(item, dict)
                    )
                    planner_snapshot["initiative_runtime_context"] = dict(initiative_runtime_context)
            except Exception as exc:
                host.logger.debug("[initiative policy] projection failed: %s", exc)

        # Mọi affordance autonomous đi qua cùng nền Subject Core như chat.
        # Neuro gate chọn trên coalition có substrate, need pressure và evidence;
        # remote deliberation chỉ xuất hiện khi competition thật sự mơ hồ.
        subject_ingress = getattr(host, "subject_ingress", None)
        subject_session = None
        subject_generation_revision = 0
        if subject_ingress is not None:
            try:
                subject_session = subject_ingress.prepare_autonomous_session(
                    blackboard,
                    affordances,
                    created_at=now,
                    turn_id=f"autonomous:{context.turn_seq}",
                    planning_context=planner_snapshot,
                )
                subject_generation_revision = int(
                    getattr(getattr(subject_session, "frame", None), "revision", 0) or 0
                )
            except Exception as exc:
                host.logger.warning("[subject-core] autonomous prepare failed closed: %s", exc)

        # V26: self-turn và chat dùng cùng một authority path:
        # Observation -> MindLoop -> Subject Core -> SubjectCommitPort
        # -> MindDecision. Autonomous không gọi capability planner để chọn
        # motive trước rồi mới cố bind ngược vào Subject Core.
        executive_outcome = None
        executive = getattr(host, "ai_executive_cortex", None)
        subject_decision = None
        if subject_session is not None and subject_ingress is not None:
            try:
                subject_decision = subject_ingress.complete_session(
                    subject_session,
                    committer=executive,
                )
                planner_snapshot["subject_decision"] = subject_decision.to_dict()
                action_executor = getattr(host, "action_executor", None)
                set_parent = getattr(action_executor, "set_subject_parent_decision", None)
                if callable(set_parent):
                    set_parent(subject_decision)
            except Exception as exc:
                host.logger.warning("[subject-core] unified self-turn finalize failed closed: %s", exc)
                try:
                    subject_ingress.mind_loop.abandon_sync(
                        subject_session,
                        reason="unified_subject_finalize_failed",
                    )
                except Exception:
                    pass
                subject_decision = None

        # V94: nếu Subject/Neuro đã chọn SILENCE/BODY_ONLY, các speech affordance
        # trong frame vừa bị từ chối cần nhận lifecycle receipt ngay tại đây. Nếu
        # không, scheduler sẽ materialize lại đúng chúng ở tick sau dù không có
        # evidence mới. Đây chỉ defer proposal, không sửa motive/goal upstream.
        if subject_decision is not None and str(getattr(subject_decision, "proposed_action", "") or "").lower() in {"silence", "body_only"}:
            try:
                proposal_lifecycle = ensure_proposal_lifecycle_runtime(host)
                for _affordance in tuple(affordances or ()):
                    proposal_lifecycle.note_affordance_outcome(
                        _affordance,
                        outcome="body_only" if str(getattr(subject_decision, "proposed_action", "") or "").lower() == "body_only" else "silence",
                        now=now,
                    )
            except Exception as exc:
                host.logger.debug("[proposal lifecycle v94] subject silence receipt failed: %s", exc)

        if subject_decision is not None and executive is not None:
            try:
                materialize = getattr(executive, "materialize_subject_decision", None)
                if callable(materialize):
                    executive_outcome = materialize(
                        subject_decision,
                        affordances,
                        subject_frame=subject_session.frame if subject_session is not None else None,
                    )

                # Capability discovery là execution planning sau commit, tương tự
                # chat plan_interactive. Nó không được quyền chọn motive khác.
                if (
                    executive_outcome is None
                    and subject_session is not None
                    and subject_decision.proposed_action == "speak"
                    and bool(subject_decision.arguments.get("capability_route", False))
                ):
                    selected = next(
                        (item for item in subject_session.frame.coalitions if item.coalition_id == subject_decision.coalition_id),
                        None,
                    )
                    if selected is not None:
                        refs = set(selected.proposal_refs)
                        restricted_frame = replace(
                            subject_session.frame,
                            coalitions=(selected,),
                            proposals=tuple(item for item in subject_session.frame.proposals if item.proposal_id in refs),
                        )
                        executive_outcome = executive.deliberate(
                            blackboard,
                            (),
                            snapshot=planner_snapshot,
                            subject_frame=restricted_frame,
                        )
            except Exception as exc:
                host.logger.warning("[executive] committed self-turn materialization failed closed: %s", exc)
                executive_outcome = None
        elif subject_decision is not None:
            host.logger.warning("[executive] materializer unavailable after Subject commit")

        if executive_outcome is not None:
            candidate = executive_outcome.candidate
            selected_id = str(getattr(executive_outcome, "selected_affordance_id", "") or "")
            if selected_id:
                selected = next(
                    (item for item in affordances if item.affordance_id == selected_id),
                    None,
                )
                if selected is None:
                    candidate = None
                elif bool(getattr(selected, "claim_required", False)):
                    claimed = self._claim_selected_affordance(
                        selected,
                        worker_id=worker_id,
                        now=now,
                        social_continuation_runtime=social_continuation_runtime,
                        conversation_arc_runtime=conversation_arc_runtime,
                        neuro_continuation_runtime=neuro_continuation_runtime,
                        social_agenda_store=social_agenda_store,
                        agenda_selector=agenda_selector,
                    )
                    if claimed is None:
                        host.logger.info(
                            "[executive] selected affordance became stale id=%s; failing closed",
                            selected_id,
                        )
                        candidate = None
                        executive_outcome = replace(
                            executive_outcome,
                            action="silence",
                            reason="selected_affordance_stale",
                        )
                    else:
                        materialize = getattr(executive, "materialize_candidate", None)
                        candidate = (
                            materialize(claimed, executive_outcome.decision)
                            if callable(materialize)
                            else claimed
                        )

        # V30: capability planner không được sửa reply baton/discourse state.
        # Trạng thái hội thoại được derive ở discourse/follow-up layer; tool planning
        # chỉ thực thi motive đã commit.
        candidate_ms = (time.monotonic() - candidate_started) * 1000.0
        initiative = getattr(host, "ai_initiative_controller", None)
        if executive_outcome is not None and executive_outcome.action == "body_only":
            decision = InitiativeDecision(
                InitiativeAction.BODY_ONLY,
                f"subject_materializer:{executive_outcome.reason}",
                IntentionPlan.silence(channel="autonomous", reason="subject_body_only"),
                body_motion="quiet_presence",
            )
        elif initiative is None:
            decision = InitiativeDecision(
                InitiativeAction.NO_OP,
                "initiative_controller_unavailable",
                IntentionPlan.silence(channel="autonomous", reason="controller_unavailable"),
            )
        else:
            # V67: candidate đã mang typed ExpressionCommitment từ owner nguồn.
            # Không còn cờ compatibility hay bước bind lại từ SubjectDecision.
            decision = initiative.decide(blackboard, candidate)
            if executive_outcome is not None and candidate is None and executive_outcome.action == "silence":
                decision = replace(decision, reason=f"subject_materializer:{executive_outcome.reason}")
        host.logger.info(
            "[autonomous latency] perception=%.0fms context=%.0fms snapshot=%.0fms candidate=%.0fms total_to_governor=%.0fms",
            perception_ms, context_ms, snapshot_ms, candidate_ms,
            perception_ms + context_ms + snapshot_ms + candidate_ms,
        )
        if executive_outcome is not None:
            self.trace_store.append("executive_decision", {
                "turn_seq": context.turn_seq,
                "stage": "executive",
                "owner": "subject_neuro_or_capability_planner",
                "action": executive_outcome.action,
                "reason": executive_outcome.reason,
                "decision": executive_outcome.decision.to_dict(),
                "subject_decision": (subject_decision.to_dict() if subject_decision is not None else {}),
            }, now=now)
        if candidate is not None:
            host.logger.info(
                "[social candidate] source=%s kind=%s anchor=%s confidence=%.2f relevance=%.2f reason=%s",
                candidate.source, candidate.kind, candidate.anchor_type, candidate.confidence, candidate.relevance, candidate.reason,
            )

        plan = decision.plan
        discovery_grounding = ""
        discovery_id = ""
        if decision.should_speak and discovery_runtime is not None:
            plan, discovery_grounding, discovery_id = discovery_runtime.bind_plan(plan)
            # bind_plan có thể bổ sung artifact/evidence; SpeechIntent phải dùng
            # plan cuối cùng, nhưng không được đổi action mà controller đã chọn.
            speech_intent = decision.speech_intent
            if speech_intent is not None and plan is not speech_intent.plan:
                speech_intent = replace(speech_intent, plan=plan)
                decision = replace(decision, plan=plan, speech_intent=speech_intent)

        # Generation epoch là turn_seq đã claim. Kết quả Surface/TTS mang epoch
        # cũ sẽ bị user-input preemption hoặc speech_epoch của TTS loại bỏ.
        if decision.speech_intent is not None:
            sealed_intent = replace(
                decision.speech_intent,
                trace_id=str(plan.plan_id or decision.speech_intent.trace_id),
                generation_epoch=int(context.turn_seq),
                claim_token=str(getattr(candidate, "claim_token", "") or decision.speech_intent.claim_token),
            )
            decision = replace(decision, speech_intent=sealed_intent, plan=plan)

        activity = self.activity_tracker.annotate(plan.activity, now=now)
        host.last_ai_intention_plan = plan
        self._submit_intention(plan, turn_seq=context.turn_seq)

        if candidate is not None:
            # Ghi candidate sau khi governor đã đóng plan_id, nhưng đặt event trước
            # governor trong trace để toàn chuỗi dùng đúng một identity ổn định.
            candidate_payload = candidate.to_dict()
            seed_payload = (
                getattr(candidate, "random_chat_seed", {})
                if isinstance(getattr(candidate, "random_chat_seed", {}), Mapping)
                else {}
            )
            self.trace_store.append("candidate", {
                "trace_id": str(plan.plan_id or ""),
                "stage": "candidate",
                "owner": "social_initiative",
                "candidate_source": str(getattr(candidate, "source", "") or ""),
                "candidate_kind": str(getattr(candidate, "kind", "") or ""),
                "candidate": candidate_payload,
                "claim_token": str(getattr(candidate, "claim_token", "") or ""),
                "idempotency_key": str(getattr(candidate, "idempotency_key", "") or ""),
                "generation_epoch": context.turn_seq,
                "seed": dict(seed_payload),
                "seed_event_kind": str(getattr(candidate, "seed_event_kind", "") or ""),
                "seed_event_family": seed_event_family(str(getattr(candidate, "seed_event_kind", "") or "")),
                "seed_premise": str(getattr(candidate, "topic", "") or ""),
                "seed_quality": {
                    "score": float(getattr(candidate, "seed_quality_score", 0.0) or 0.0),
                    "specificity": float(getattr(candidate, "seed_specificity", 0.0) or 0.0),
                    "motive_strength": float(getattr(candidate, "seed_motive_strength", 0.0) or 0.0),
                    "semantic_completeness": float(getattr(candidate, "seed_semantic_completeness", 0.0) or 0.0),
                },
                "materialized_temporal_context": dict(getattr(candidate, "seed_temporal_context", {}) or {}),
            }, now=now)

        self.trace_store.append("initiative_decision", {
            "turn_seq": context.turn_seq,
            "trace_id": str(plan.plan_id or ""),
            "stage": "governor",
            "owner": "initiative_governor",
            "governor_action": decision.action.value,
            "generation_epoch": context.turn_seq,
            "speech_intent_owner": getattr(decision.speech_intent, "owner", "") if decision.speech_intent else "",
            "action": decision.action.value,
            "reason": decision.reason,
            # V97: aliases causal/authority typed để compact trace không phải
            # suy từ candidate prose hay parse reason string.
            "authority_action": decision.action.value,
            "authority_reason": decision.reason,
            "semantic_owner": str(getattr(plan, "semantic_owner", "unknown") or "unknown"),
            "trigger_owner": str(getattr(plan, "trigger_owner", "unknown") or "unknown"),
            "source_kind": str(getattr(plan, "source_kind", "") or ""),
            "motive": str(getattr(plan, "motive", "") or ""),
            "proposal_source": str(getattr(candidate, "source", "") or "") if candidate is not None else "",
            "proposal_kind": str(getattr(candidate, "kind", "") or "") if candidate is not None else "",
            "anchor": decision.speech_intent.anchor_type if decision.speech_intent else "none",
            "semantic_signature": plan.semantic_signature,
            "candidate": candidate.to_dict() if candidate is not None else None,
        }, now=now)

        # Log một dòng ngắn để runtime log cho biết Eris đang thật sự quyết
        # định gì. NO_OP để debug nhằm tránh spam; BODY_ONLY/SPEECH là INFO vì
        # chúng tạo hành vi nhìn thấy được và hữu ích khi chẩn đoán "đứng đơ".
        initiative_log = host.logger.info if decision.action is not InitiativeAction.NO_OP else host.logger.debug
        initiative_log(
            "[initiative] action=%s anchor=%s reason=%s",
            decision.action.value,
            decision.speech_intent.anchor_type if decision.speech_intent else "none",
            decision.reason,
        )

        if decision.action is InitiativeAction.NO_OP:
            self._capture_suppressed_private_residue(
                candidate=candidate, planner_snapshot=planner_snapshot, reason=decision.reason, now=now
            )
            release_candidate = candidate
            self._release_seed_lease(release_candidate, reason=decision.reason)
            self._defer_claimed_continuation(
                plan,
                candidate=release_candidate,
                reason=decision.reason,
                seconds=0.25 if getattr(candidate, "kind", "") == "conversation_arc" else 1.5,
            )
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason=decision.reason,
            )
        if decision.action is InitiativeAction.BODY_ONLY:
            self._capture_suppressed_private_residue(
                candidate=candidate, planner_snapshot=planner_snapshot, reason=decision.reason, now=now
            )
            release_candidate = candidate
            self._release_seed_lease(release_candidate, reason=decision.reason)
            self._defer_claimed_continuation(
                plan,
                candidate=release_candidate,
                reason=decision.reason,
                seconds=0.25 if getattr(candidate, "kind", "") == "conversation_arc" else 1.5,
            )
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason=decision.reason,
                force_body_only=True, body_motion=decision.body_motion,
            )
        if host._process_pending_user_input():
            self._release_seed_lease(candidate, reason="user_input_preempted")
            self.trace_store.append("outcome", {
                "trace_id": str(plan.plan_id or ""),
                "turn_id": str(plan.plan_id or ""),
                "stage": "outcome",
                "owner": "user_input",
                "generation_epoch": context.turn_seq,
                "outcome": "cancelled_before_surface",
            })
            return host.running

        speech_intent = decision.speech_intent
        if speech_intent is None:
            self._capture_suppressed_private_residue(
                candidate=candidate, planner_snapshot=planner_snapshot, reason="missing_speech_intent", now=now
            )
            self._release_seed_lease(candidate, reason="missing_speech_intent")
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason="missing_speech_intent",
            )

        # V73 positive grounding: collect real user/history/self evidence BEFORE
        # Surface writes a sentence. The writer receives a bounded semantic
        # inventory and a selected information gap instead of inventing a premise
        # first and hoping the validator accepts it later.
        try:
            from runtime.evidence_enrichment import compiler_for
            semantics = getattr(getattr(speech_intent, "plan", None), "semantics", None)
            speech_act = str(getattr(semantics, "speech_act", "") or "")
            semantic_goal = str(getattr(speech_intent.plan, "motive", "") or "")
            bundle = compiler_for(host).compile(
                speech_act=speech_act,
                semantic_goal=semantic_goal,
                topic=str(getattr(speech_intent.plan, "topic", "") or ""),
                recent_history=context.recent_history,
            )
            bundle_payload = bundle.to_dict()
            enriched_refs = tuple(dict.fromkeys((*speech_intent.evidence_refs, *bundle.evidence_refs)))[:96]
            enriched_domains = tuple(dict.fromkeys((*speech_intent.allowed_claim_domains, *bundle.claim_domains)))[:24]
            speech_intent = replace(
                speech_intent,
                evidence_refs=enriched_refs,
                allowed_claim_domains=enriched_domains,
                evidence_bundle=bundle_payload,
            )
            decision = replace(decision, speech_intent=speech_intent)
            self.trace_store.append("evidence_enrichment", {
                "trace_id": str(speech_intent.trace_id or plan.plan_id),
                "stage": "evidence_enrichment",
                "owner": "runtime",
                "generation_epoch": speech_intent.generation_epoch,
                "speech_act": speech_act,
                "user_fact_count": len(bundle.user_facts),
                "recent_user_turn_count": len(bundle.recent_user_turns),
                "shared_episode_count": len(bundle.shared_episodes),
                "self_fact_count": len(bundle.self_facts),
                "open_user_gap": bundle.open_user_gap.to_dict() if bundle.open_user_gap else None,
            })
            if bundle.open_user_gap is not None:
                host.logger.info(
                    "[evidence enrichment] speech_act=%s gap=%s score=%.2f user_facts=%s episodes=%s self_facts=%s",
                    speech_act, bundle.open_user_gap.key, bundle.open_user_gap.score,
                    len(bundle.user_facts), len(bundle.shared_episodes), len(bundle.self_facts),
                )
        except Exception as exc:
            host.logger.debug("[evidence enrichment] autonomous compile failed: %s", exc)

        validator = getattr(host, "ai_autonomous_grounding_validator", None)
        if validator is not None:
            preflight = validator.validate_intent(speech_intent, blackboard)
            if not preflight.allowed:
                self._release_seed_lease(candidate, reason=preflight.reason)
                self._defer_claimed_continuation(plan, reason=preflight.reason, seconds=0.5)
                return self._finish_silence(
                    plan=plan, context=context, activity=activity, gate_reason=preflight.reason,
                    force_body_only=bool(context.perception.mechanical_delta or activity.has_new_event),
                    body_motion=decision.body_motion,
                )

        # V42: không phát UI "đang chuẩn bị nói". Cognitive/Surface latency là
        # background implementation detail; chỉ khi public lifecycle thật bắt đầu
        # phát speech/audio thì UI mới có lý do báo hành vi ra ngoài.
        from runtime.public_lifecycle import lifecycle_for
        lifecycle_turn_id = str(plan.plan_id or f"autonomous:{context.turn_seq}")
        host._active_public_lifecycle_turn_id = lifecycle_turn_id
        public_lifecycle = lifecycle_for(host)
        public_lifecycle.begin(
            turn_id=lifecycle_turn_id,
            channel="autonomous",
            reason="autonomous_composing",
            received=False,
        )

        surface_payload = None
        surface_engine = getattr(host, "ai_surface_intent_engine", None)
        surface_turn = None
        if surface_engine is not None:
            intent_payload = speech_intent.to_dict()
            intent_seed = (
                speech_intent.random_chat_seed
                if isinstance(speech_intent.random_chat_seed, Mapping)
                else {}
            )
            seed_claim_contract = (
                intent_seed.get("claim_contract", {})
                if isinstance(intent_seed.get("claim_contract", {}), Mapping)
                else {}
            )
            self.trace_store.append("surface_start", {
                "trace_id": str(speech_intent.trace_id or plan.plan_id),
                "stage": "surface",
                "owner": "surface",
                "generation_epoch": speech_intent.generation_epoch,
                "surface_status": "started",
                "semantic_intent": {
                    "act": plan.semantics.speech_act,
                    "subject": plan.semantics.subject_key,
                    "turn_kind": plan.semantics.turn_kind,
                    "allowed_claims": (
                        seed_claim_contract.get("runtime_clock_is_evidence_for")
                        if seed_claim_contract
                        else list(speech_intent.evidence_refs)
                    ),
                    "claim_contract": dict(seed_claim_contract),
                },
                "speech_intent": intent_payload,
            })
            try:
                surface_turn = surface_engine.realize(
                    speech_intent,
                    blackboard,
                    snapshot=planner_snapshot,
                    avoid_text="\n".join(self._recent_autonomous_texts) or self._last_autonomous_text,
                )
            except Exception as exc:
                host.logger.warning("[surface worker] realization failed: %s", exc)
        if surface_turn is not None:
            self.trace_store.append("surface_result", {
                "trace_id": str(speech_intent.trace_id or plan.plan_id),
                "stage": "surface",
                "owner": "surface",
                "generation_epoch": speech_intent.generation_epoch,
                "surface_status": "realized",
                "surface_added_claims": int(getattr(surface_turn, "surface_added_claims", 0) or 0),
                "claim_manifest": [dict(item) for item in tuple(getattr(surface_turn, "claim_manifest", ()) or ())[:8]],
                "unsupported_current_world_claim": False,
            })
            plan = surface_turn.plan
            surface_payload = surface_turn.public_payload
            host.last_ai_intention_plan = plan
        elif surface_engine is not None:
            self.trace_store.append("surface_result", {
                "trace_id": str(speech_intent.trace_id or plan.plan_id),
                "stage": "surface",
                "owner": "surface",
                "generation_epoch": speech_intent.generation_epoch,
                "surface_status": "unavailable",
            })
            # Surface là writer duy nhất cho autonomous speech. Provider lỗi thì
            # giữ event/cadence cho nhịp sau và chuyển body-only; không có câu
            # small-talk mẫu hay domain template giả làm DeepSeek.
            surface_reason = str(
                getattr(surface_engine, "last_failure_reason", "") or "surface_unavailable"
            )[:160]
            host.logger.info(
                "[surface worker] unavailable mode=%s reason=%s; local text fallback disabled",
                speech_intent.mode,
                surface_reason,
            )
        if surface_payload and host._process_pending_user_input():
            # User input wins even if it arrived while Surface was composing.
            self._release_seed_lease(candidate, reason="user_input_during_surface")
            self.trace_store.append("outcome", {
                "trace_id": str(speech_intent.trace_id or plan.plan_id),
                "turn_id": str(plan.plan_id or ""),
                "stage": "outcome",
                "owner": "user_input",
                "generation_epoch": speech_intent.generation_epoch,
                "outcome": "cancelled_during_surface",
            })
            return host.running
        if not surface_payload:
            surface_reason = str(
                getattr(surface_engine, "last_failure_reason", "") or "surface_unavailable"
            )[:160]
            gate_reason = (
                surface_reason
                if surface_reason.startswith("surface_")
                else f"surface_unavailable:{surface_reason}"
            )

            # V66: Surface failure không được viết ngược thành "Eris quyết định
            # im". Commitment vẫn sống; ta chỉ ghi lỗi realization và defer một
            # nhịp để writer có context mới.
            if surface_reason.startswith("surface_") and subject_decision is not None:
                urge_id = str(subject_decision.arguments.get("expression_urge_id", "") or "").strip()
                urge_runtime = getattr(host, "expression_urge_runtime", None)
                note_failure = getattr(urge_runtime, "note_realization_failure", None)
                if urge_id and callable(note_failure):
                    try:
                        note_failure(urge_id, reason=surface_reason, now=time.time())
                    except Exception as exc:
                        host.logger.debug("[expression urge] realization receipt degraded: %s", exc)
                if surface_reason == "surface_duplicate_recent_utterance":
                    gate_reason = "expression_realization_deferred:duplicate_recent_utterance"
                else:
                    gate_reason = f"expression_realization_deferred:{surface_reason}"
            self._release_seed_lease(candidate, reason=gate_reason)
            self._defer_claimed_continuation(
                plan, reason=gate_reason,
                seconds=2.5 if surface_reason == "surface_duplicate_recent_utterance" else 12.0,
            )
            # V62: dedupe là một lựa chọn im an toàn, không phải autonomous
            # subsystem chết. Chỉ lỗi kỹ thuật/provider thật mới phát DEGRADED.
            terminal_state = (
                "DONE"
                if surface_reason == "surface_duplicate_recent_utterance"
                else "DEGRADED"
            )
            public_lifecycle.transition(
                terminal_state,
                turn_id=lifecycle_turn_id,
                reason=gate_reason,
            )
            return self._finish_silence(
                plan=plan, context=context, activity=activity, gate_reason=gate_reason,
                force_body_only=True, body_motion=decision.body_motion,
            )

        return self._surface(
            plan=plan,
            context=context,
            activity=activity,
            discovery_grounding=discovery_grounding,
            discovery_id=discovery_id,
            discovery_runtime=discovery_runtime,
            prebuilt_payload=surface_payload,
            allow_model_generation=False,
            candidate=candidate,
            subject_decision=subject_decision,
            subject_generation_revision=subject_generation_revision,
        )

    def _submit_intention(self, plan: IntentionPlan, *, turn_seq: int) -> None:
        """Ghi typed plan vào single-writer reducer sau deterministic decision."""

        reducer = getattr(self.host, "ai_state_reducer", None)
        if reducer is None:
            return
        try:
            state = reducer.snapshot()
            reducer.submit(
                StateEvent.from_intention(
                    plan,
                    turn_seq=turn_seq,
                    base_version=getattr(state, "version", -1),
                )
            )
        except Exception as exc:
            self.host.logger.debug("[initiative] reducer submit failed: %s", exc)

    def _acquire_baton(self) -> bool:
        host = self.host
        if not bool(getattr(host, "chat_mode", False)):
            return True
        # Không được tự nhả baton khi chat worker còn sinh câu hoặc audio/public
        # turn vẫn đang bận. Timer stale không có quyền chen vào giữa hai tin nhắn.
        if bool(getattr(host, "_chat_processing", False)):
            time.sleep(0.2)
            return False
        clock = getattr(host, "interaction_clock", None)
        if clock is not None and bool(getattr(clock, "busy", False)):
            time.sleep(0.2)
            return False
        conversation_arc_runtime = getattr(host, "ai_conversation_arc_runtime", None)
        if conversation_arc_runtime is not None:
            try:
                if conversation_arc_runtime.is_due(now=time.time(), interaction_busy=False):
                    # Đây là câu kế tiếp của cùng một public arc, không phải một
                    # chủ đề autonomous mới. Nó được phép dùng baton khi chat vẫn
                    # fresh, miễn chat worker và playback đều đã rảnh.
                    return True
            except Exception as exc:
                host.logger.debug("[conversation arc] baton check failed: %s", exc)
        neuro_continuation_runtime = getattr(host, "neuro_continuation_runtime", None)
        if neuro_continuation_runtime is not None:
            try:
                if neuro_continuation_runtime.is_due(now=time.time(), interaction_busy=False):
                    # Same-turn deep cognition is a continuation, not unsolicited
                    # autonomous chatter. It may reuse the baton once public chat
                    # generation/playback is idle.
                    return True
            except Exception as exc:
                host.logger.debug("[neuro-continuation] baton check failed: %s", exc)
        stale_check = getattr(host, "_conversation_went_stale", None)
        if callable(stale_check) and stale_check():
            end_chat_cycle = getattr(host, "_end_chat_cycle", None)
            if callable(end_chat_cycle):
                end_chat_cycle()
            else:
                host.chat_mode = False
            host.logger.info("[self turn] chat baton released after stale public activity")
            return True
        time.sleep(0.2)
        return False

    def _assemble_perception(self, now: float) -> PerceptionBundle:
        host = self.host
        snapshot = host.telemetry_service.capture_snapshot(
            mood_score=host.mood_score,
            inferred_pos_x=host.inferred_pos_x,
        )
        telemetry = snapshot.to_machine_context() if callable(getattr(snapshot, "to_machine_context", None)) else {}
        screen_snapshot = None
        screen_store = getattr(host, "screen_evidence_store", None)
        if screen_store is not None:
            try:
                screen_snapshot = screen_store.snapshot()
            except Exception as exc:
                host.logger.debug("[self turn screen] snapshot unavailable: %s", exc)
        screen = self.screen_tracker.observe(screen_snapshot, telemetry=telemetry, now=now)

        attention = getattr(host, "last_cortex_attention", None)
        force_visual_refresh = bool(
            not screen.privacy_blocked
            and not screen.changed_text
            and (
                bool(getattr(attention, "vision_refresh_recommended", False))
                or (screen.meaningful_delta and screen.changed_ratio >= 0.12)
            )
        )
        previous_observer = getattr(host, "last_observer_frame", None)
        # Không để autonomous turn chờ observer/model vision. Nếu chưa có cached
        # observer, ta schedule refresh nền và dùng facts đã grounded từ tick trước.
        # Tick sau sẽ nhận kết quả; UI không đứng đợi một lane advisory đi họp.
        if previous_observer is None:
            vision_facts = tuple(
                () if bool(getattr(host, "vision_facts_are_stale", False))
                else tuple(getattr(host, "vision_facts", ()) or ())
            )
            self._schedule_observer_refresh(snapshot, vision_facts, now)
        else:
            try:
                vision_facts = host._maybe_update_screen_facts(
                    snapshot=snapshot,
                    channel="autonomous",
                    observer_frame=previous_observer,
                    force_refresh=force_visual_refresh,
                    started_at=now,
                )
            except TypeError:
                vision_facts = host._maybe_update_screen_facts()
            vision_facts = tuple(vision_facts or ())
            self._schedule_observer_refresh(snapshot, vision_facts, now)
        if vision_facts:
            try:
                host._attach_screen_facts(snapshot, vision_facts)
            except Exception:
                pass

        observer_frame = previous_observer

        # Reconcile source chỉ publish safety-net events. Structured semantic đã
        # được daemon worker xử lý từ lúc native callback tới, không còn nằm trên
        # critical path của self-turn cadence.
        self._collect_environment_events(now, telemetry)
        semantic_worker = getattr(self, "_semantic_environment_worker", None)
        if semantic_worker is not None:
            environment_events, user_situation = semantic_worker.build_perception_situation(
                screen,
                telemetry=telemetry,
                observer_frame=observer_frame,
                now=now,
            )
        else:
            # Rollback phòng trường hợp worker không khởi tạo được. Nhánh này giữ
            # OCR/screen fallback nhưng không phục hồi kiểu drain bus chậm cũ.
            environment_events = ()
            user_situation = self.desktop_semantic_runtime.observe(
                screen,
                telemetry=telemetry,
                observer_frame=observer_frame,
                now=now,
            )
        setattr(host, "last_user_situation", user_situation)
        # Publish the same structured environment projection used by direct chat
        # and the seed worker.  This refresh is cheap and never invokes VLM.
        try:
            from runtime.environment_awareness import ensure_environment_awareness_hub
            ensure_environment_awareness_hub(host).refresh(
                machine_snapshot=snapshot,
                situation=user_situation,
                environment_events=environment_events,
                now=now,
                source="self_turn_perception",
            )
        except Exception as exc:
            host.logger.debug("[environment awareness] self-turn publish failed: %s", exc)

        # Semantic Tutor nhận cùng screen contract + structured chess state. Nó
        # tự quyết định có scene invalidation hay không; tick không đổi chỉ cập
        # nhật raw cache và không gọi DeepSeek.
        semantic_tutor = getattr(host, "semantic_tutor_runtime", None)
        if semantic_tutor is not None:
            try:
                chess_state = {}
                chess_bridge = getattr(host, "chess_bridge_service", None)
                if chess_bridge is not None and callable(getattr(chess_bridge, "current_surface_state", None)):
                    chess_state = chess_bridge.current_surface_state()
                semantic_tutor.observe(
                    channel="autonomous",
                    telemetry=telemetry,
                    screen_context=screen,
                    vision_facts=vision_facts,
                    chess_state=chess_state,
                )
            except Exception as exc:
                host.logger.debug("[semantic-tutor] autonomous observe failed: %s", exc)

        if screen.meaningful_delta or screen.scene_kind != "unknown":
            host.logger.info(
                "[self turn screen] backend=%s ocr=%s upstream_scene=%s conf=%.2f delta=%s changed_text=%s",
                screen.backend or "unknown",
                int(screen.ocr_active),
                screen.scene_kind,
                screen.scene_confidence,
                int(screen.meaningful_delta),
                len(screen.changed_text),
            )
        return PerceptionBundle(
            now=now,
            snapshot=snapshot,
            telemetry=telemetry,
            screen=screen,
            vision_facts=vision_facts,
            observer_frame=observer_frame,
            user_situation=user_situation,
            environment_events=environment_events,
        )

    def _schedule_observer_refresh(
        self,
        snapshot: Any,
        vision_facts: tuple[Any, ...],
        started_at: float,
    ) -> None:
        """Refresh observer ở daemon thread; autonomous turn không chờ kết quả."""

        runner = getattr(self.host, "_run_background_observer", None)
        if not callable(runner):
            return
        with self._observer_thread_lock:
            thread = self._observer_thread
            if thread is not None and thread.is_alive():
                return

            def work() -> None:
                began = time.monotonic()
                try:
                    runner(
                        snapshot=snapshot,
                        channel="autonomous",
                        user_text="",
                        vision_facts=vision_facts,
                        started_at=started_at,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.host.logger.warning("[background observer] refresh failed: %s", exc)
                finally:
                    self.host.logger.debug(
                        "[background observer] refresh finished latency=%.0fms",
                        (time.monotonic() - began) * 1000.0,
                    )

            self._observer_thread = threading.Thread(
                target=work,
                name="eris-autonomous-observer",
                daemon=True,
            )
            self._observer_thread.start()

    def _assemble_context(self, perception: PerceptionBundle) -> SelfTurnBundle:
        host = self.host
        host.long_term_memory = host._memory_recall_texts(snapshot=perception.snapshot)
        memory_resonance = host._recall_memory_resonance(
            snapshot=perception.snapshot,
            channel="autonomous",
            fragments=perception.vision_facts,
        )
        memory_context = host._merge_conversation_context(
            host._build_memory_context(perception.snapshot, memory_resonance=memory_resonance)
        )
        # Autonomous Eris cũng phải biết backstage coding task đang sống/chờ gì,
        # nếu không VS Code và "não main" lại thành hai thực thể lịch sự giả vờ không quen nhau.
        build_agent_runtime_context = getattr(host, "_agent_execution_prompt_context", None)
        if callable(build_agent_runtime_context):
            try:
                agent_runtime_context = str(build_agent_runtime_context() or "")
            except Exception as exc:
                agent_runtime_context = ""
                host.logger.debug("[agent-harness] autonomous context failed: %s", exc)
            if agent_runtime_context:
                memory_context = "\n\n".join(
                    part for part in (memory_context, agent_runtime_context) if str(part).strip()
                )
        shared_semantic_context: Mapping[str, Any] = {}
        semantic_prompt_context = ""
        semantic_tutor = getattr(host, "semantic_tutor_runtime", None)
        if semantic_tutor is not None:
            try:
                shared_semantic_context = semantic_tutor.planner_context()
                semantic_prompt_context = semantic_tutor.prompt_context(channel="autonomous", wait_ms=0)
                if semantic_prompt_context:
                    memory_context = "\n\n".join(
                        part for part in (memory_context, semantic_prompt_context) if str(part).strip()
                    )
            except Exception as exc:
                host.logger.debug("[semantic-tutor] autonomous context failed: %s", exc)
        state = host.ai_state_reducer.snapshot()
        turn_seq = self.next_turn_seq(host)
        recent = tuple(host._chat_history_for_llm(limit=8))
        seconds_since_user = max(0.0, perception.now - float(
            getattr(host, "_temporal_last_user_turn_at", 0.0)
            or getattr(host, "_chat_last_activity_at", 0.0)
            or 0.0
        ))
        seconds_since_assistant = max(0.0, perception.now - float(
            getattr(host, "_temporal_last_assistant_turn_at", 0.0) or 0.0
        ))
        discourse = self.discourse_builder.build(
            recent,
            open_loops=tuple(state.open_loops),
            latest_observation=dict(state.latest_observation),
            seconds_since_user=seconds_since_user,
            seconds_since_assistant=seconds_since_assistant,
        )
        # Observer quyết định ERIS có đang chờ user hay không. Follow-up layer chỉ
        # quyết định cách cư xử theo thời gian: chờ, nhắc đúng một lần, rồi thôi.
        discourse = self.followup_appraisal.evaluate(
            discourse,
            now=perception.now,
            user_turn_at=float(getattr(host, "_temporal_last_user_turn_at", 0.0) or 0.0),
            assistant_turn_at=float(getattr(host, "_temporal_last_assistant_turn_at", 0.0) or 0.0),
            # V29: follow-up lifecycle is projected from public events. No hidden
            # question/reminder flags survive outside the ledger.
            ledger=host._ensure_session_turn_ledger(),
        )
        activity = self.activity_tracker.observe(
            perception.screen,
            telemetry=perception.telemetry,
            now=perception.now,
        )
        self_context = build_autonomous_self_context(host)
        engagement_context: Mapping[str, Any] = {"active": False}
        engagement_prompt_context = "active_engagement: none"
        engagement_interaction = InteractionDecision()
        engagement_runtime = getattr(host, "ai_engagement_runtime", None)
        if engagement_runtime is not None:
            try:
                engagement_runtime.observe_activity(activity, now=perception.now)
                engagement_context = engagement_runtime.planner_context(now=perception.now)
                engagement_prompt_context = engagement_runtime.prompt_context(now=perception.now)
                engagement_interaction = engagement_runtime.interaction_decision(
                    now=perception.now,
                    seconds_since_user=seconds_since_user,
                    seconds_since_assistant=seconds_since_assistant,
                    telemetry=perception.telemetry,
                )
            except Exception as exc:
                host.logger.debug("[engagement] autonomous context failed: %s", exc)
        commentary = self.commentary_cadence.evaluate(
            now=perception.now,
            last_commentary_at=float(getattr(host, "last_autonomous_spoken_at", 0.0) or 0.0),
            session_started_at=float(getattr(host, "_temporal_session_started_at", 0.0) or 0.0),
            seconds_since_user=seconds_since_user,
            seconds_since_assistant=seconds_since_assistant,
            discourse_open=bool(discourse.assistant_may_continue and discourse.thread_fresh),
            perception_delta=bool(perception.mechanical_delta),
            activity_event=bool(activity.has_new_event),
            has_public_seed=bool(self_context.has_public_seed),
            telemetry=perception.telemetry,
            engagement_decision=engagement_interaction,
        )
        return SelfTurnBundle(
            perception=perception,
            state=state,
            turn_seq=turn_seq,
            recent_history=recent,
            seconds_since_user=seconds_since_user,
            seconds_since_assistant=seconds_since_assistant,
            discourse=discourse,
            activity=activity,
            self_context=self_context,
            memory_context=memory_context,
            shared_semantic_context=shared_semantic_context,
            semantic_prompt_context=semantic_prompt_context,
            engagement_context=engagement_context,
            engagement_prompt_context=engagement_prompt_context,
            engagement_interaction=engagement_interaction,
            commentary=commentary,
            public_revision=int(getattr(host._ensure_session_turn_ledger(), "revision", 0) or 0),
        )

    def _planner_snapshot(self, context: SelfTurnBundle) -> tuple[dict[str, Any], Any]:
        perception = context.perception
        state = context.state
        # V39: autonomous Surface dùng cùng projector với direct chat. Không có
        # một "tone autonomous" riêng và không tự suy mood từ seed.
        affective_voice = project_affective_voice_state(
            self.host,
            mind_state=state,
            channel="autonomous",
            now=perception.now,
        )
        initiative = getattr(self.host, "ai_initiative_controller", None)
        recent_initiative = []
        if initiative is not None:
            try:
                recent_initiative = initiative.panel_view(now=perception.now).get("recent_events", [])[:8]
            except Exception:
                recent_initiative = []
        try:
            from runtime.environment_awareness import ensure_environment_awareness_hub
            environment_awareness = ensure_environment_awareness_hub(self.host).refresh(
                machine_snapshot=perception.snapshot,
                situation=perception.user_situation,
                environment_events=perception.environment_events,
                now=perception.now,
                source="autonomous_planner",
            )
        except Exception:
            environment_awareness = None
        world_projection = {}
        seed_context = {}
        world_context = ""
        try:
            from runtime.world_state import ensure_world_state_service
            world_state = ensure_world_state_service(self.host).refresh_from_host(now=perception.now)
            world_projection = world_state.projection("self_turn", now=perception.now)
            seed_context = world_state.seed_context(now=perception.now)
            world_context = world_state.prompt_context("self_turn", now=perception.now)
        except Exception as exc:
            try:
                self.host.logger.debug("[world state] self-turn projection failed: %s", exc)
            except Exception:
                pass
        snapshot = {
            "time": perception.now,
            "event_kind": "self_initiated_turn",
            "telemetry": dict(perception.telemetry),
            "screen_context": perception.screen.to_dict(),
            "user_situation": perception.user_situation.to_dict() if perception.user_situation is not None else {},
            "environment_awareness": environment_awareness.to_dict(now=perception.now) if environment_awareness is not None else {},
            "environment_awareness_context": environment_awareness.prompt_context(now=perception.now) if environment_awareness is not None else "",
            "world_state": world_projection,
            "world_state_context": world_context,
            "seed_context": seed_context,
            "environment_events": [item.to_dict() for item in perception.environment_events[-16:]],
            "task_graph": self.task_graph.to_dict(),
            "conversation_baton": context.discourse.to_dict(),
            "activity_session": context.activity.to_dict(),
            "vision_facts": list(perception.vision_facts),
            "vision_grounding": (
                getattr(self.host, "last_vision_grounding_report", None).to_dict()
                if callable(getattr(getattr(self.host, "last_vision_grounding_report", None), "to_dict", None))
                else {}
            ),
            "personality": state.personality.panel_view(),
            "personality_summary": state.personality_prompt_context(),
            "affective_voice_state": affective_voice.to_dict(),
            "affective_voice_context": affective_voice.prompt_context(),
            "identity": state.identity.panel_view(),
            "identity_summary": state.identity_prompt_context(),
            "relationship": state.relationship.to_dict(),
            "open_loops": list(state.open_loops),
            "latest_observation": dict(state.latest_observation),
            "recent_public_history": context.recent_history,
            "conversation_handoff": (
                getattr(self.host, "conversation_handoff_runtime", None).to_dict()
                if callable(getattr(getattr(self.host, "conversation_handoff_runtime", None), "to_dict", None))
                else {}
            ),
            "conversation_trajectory": (
                getattr(self.host, "conversation_trajectory_runtime", None).to_dict()
                if callable(getattr(getattr(self.host, "conversation_trajectory_runtime", None), "to_dict", None))
                else {}
            ),
            "conversation_courtesy": (
                getattr(self.host, "conversation_courtesy_contract", None).runtime_context(now=perception.now)
                if callable(getattr(getattr(self.host, "conversation_courtesy_contract", None), "runtime_context", None))
                else {}
            ),
            "life_horizon": (
                getattr(self.host, "life_horizon_manager", None).snapshot(now=perception.now).to_dict()
                if callable(getattr(getattr(self.host, "life_horizon_manager", None), "snapshot", None))
                else {}
            ),
            "persistent_individual": (
                getattr(self.host, "persistent_individual_runtime", None).projection_for_host(
                    self.host, now=perception.now, context_key="autonomous"
                )
                if callable(getattr(getattr(self.host, "persistent_individual_runtime", None), "projection_for_host", None))
                else {}
            ),
            "seconds_since_user": context.seconds_since_user,
            "seconds_since_assistant": context.seconds_since_assistant,
            "self_context": context.self_context.to_dict(),
            "memory_context": context.memory_context,
            "shared_semantic_context": dict(context.shared_semantic_context),
            "user_addressing": (
                self.host._user_addressing_snapshot()
                if callable(getattr(self.host, "_user_addressing_snapshot", None))
                else {}
            ),
            "recent_self_turn_semantics": recent_initiative,
            "commentary_expectation": context.commentary.to_dict(),
            "engagement_context": dict(context.engagement_context),
            "engagement_interaction": context.engagement_interaction.to_dict(),
            "social_continuation": (
                self.host.ai_social_continuation_runtime.snapshot(now=perception.now)
                if getattr(self.host, "ai_social_continuation_runtime", None) is not None
                else {"pending": 0, "due": False}
            ),
            "conversation_arc": (
                self.host.ai_conversation_arc_runtime.snapshot(now=perception.now)
                if getattr(self.host, "ai_conversation_arc_runtime", None) is not None
                else {"pending": False, "due": False}
            ),
            "neuro_continuation": (
                self.host.neuro_continuation_runtime.snapshot(now=perception.now)
                if getattr(self.host, "neuro_continuation_runtime", None) is not None
                else {"pending": False, "due": False, "deep_thought_running": False}
            ),
            "social_agenda": (
                self.host.ai_social_agenda_store.snapshot(now=perception.now)
                if getattr(self.host, "ai_social_agenda_store", None) is not None
                else {"active_goal_count": 0}
            ),
            "instruction": (
                "This snapshot feeds a typed Social Initiative candidate generator. "
                "Observer/inner/critic/memory contribute public-safe signals; they do not own public speech. "
                "The candidate model owns desire and topic only. Runtime owns permission and timing. "
                "Surface owns final wording. Grounding owns factual claims. "
                "Raw OCR/window titles are mechanical deltas, never public facts unless vision_grounding contains "
                "a grounded non-stale claim with evidence ids. Social chat may be non-factual and require no screen anchor. "
                "When engagement_context.active=true, preserve its objective and do not switch to unrelated banter. "
                "conversation_handoff is authoritative for unfinished conversational obligations and who owns the next move; "
                "conversation_courtesy is a hard turn-taking boundary: when awaiting_user_answer=true, do not create another public speech turn. "
                "life_horizon carries H0-H4 goal context and may change priority, but it is not speech authority. "
                "persistent_individual is V77 authoritative interaction context: respect interaction_ecology, active relational_plan, "
                "operational_self_model and continuous_self. continuous_self separates private_cognition_pressure from public_action_pressure; "
                "high private thought pressure is NOT permission to speak. A question is not the default way to express curiosity. "
                "response_expectation=none creates no reply debt, assistant speech cannot recharge its own motive, and private thought may remain private or die. "
                "an empty current user_text in autonomous mode does NOT erase a pending user request. "
                "When shared_semantic_context.packet exists, use its foreground/facts/options as the stable scene baseline; "
                "do not reinterpret raw OCR into a competing story."
            ),
            "force_speak_pending": getattr(self.host, "_autonomous_force_speak_pending", False),
        }
        if getattr(self.host, "_autonomous_force_speak_pending", False):
            setattr(self.host, "_autonomous_force_speak_pending", False)

        discovery_runtime = getattr(self.host, "ai_discovery_runtime", None)
        if discovery_runtime is not None:
            snapshot["discovery"] = discovery_runtime.planner_context(perception.telemetry, now=perception.now)
            discovery_runtime.maybe_tick(snapshot, now=perception.now)
            snapshot["discovery"] = discovery_runtime.planner_context(perception.telemetry, now=perception.now)
        return snapshot, discovery_runtime

    def _should_deliberate(self, context: SelfTurnBundle, snapshot: Mapping[str, Any]) -> tuple[bool, str]:
        """Emit scored runtime facts and let Gemma policy decide reconsideration.

        Runtime reports what changed, how strongly, and where the signal came
        from. It does not rename a mechanical delta into a social conclusion.
        """
        discovery = snapshot.get("discovery")
        discovery_ready = bool(isinstance(discovery, Mapping) and (
            discovery.get("ready_to_share") or discovery.get("artifact") or discovery.get("artifact_ready")
        ))
        attention = context.self_context.attention
        pressure = max(
            float(attention.get("external_pressure", 0.0) or 0.0),
            float(attention.get("internal_drive", 0.0) or 0.0),
        )
        social_continuation = snapshot.get("social_continuation")
        social_continuation_due = bool(
            isinstance(social_continuation, Mapping) and social_continuation.get("due")
        )
        conversation_arc = snapshot.get("conversation_arc")
        conversation_arc_due = bool(
            isinstance(conversation_arc, Mapping) and conversation_arc.get("due")
        )
        neuro_continuation = snapshot.get("neuro_continuation")
        neuro_continuation_due = bool(
            isinstance(neuro_continuation, Mapping) and neuro_continuation.get("due")
        )
        social_agenda = snapshot.get("social_agenda")
        social_agenda_active = bool(
            isinstance(social_agenda, Mapping)
            and social_agenda.get("active_goal_count")
            and context.seconds_since_assistant >= 45.0
        )

        relational_view: Mapping[str, Any] = {}
        subject_service = getattr(self.host, "subject_service", None)
        tick_relational = getattr(subject_service, "tick_relational", None)
        if callable(tick_relational):
            try:
                private_pressure = max(
                    (float(item.get("pressure", item.get("score", 0.0)) or 0.0)
                     for item in context.self_context.private_mind_surface),
                    default=0.0,
                )
                thread_pressure = max(
                    (float(item.get("salience", 0.0) or 0.0) for item in context.self_context.active_threads),
                    default=0.0,
                )
                curiosity = float(context.self_context.internal_state.get("curiosity", 0.0) or 0.0)
                situation = context.perception.user_situation
                environment_gate = environment_social_gate(situation)
                environment_interrupt = float(environment_gate["interruption_cost"])
                environment_busy = float(environment_gate["busy_score"])
                user_busy = bool(snapshot.get("user_busy", False)) or bool(environment_gate["suppressed"]) or environment_busy >= 0.78
                attention_interrupt = max(
                    float(context.self_context.attention.get("interrupt_cost", 0.0) or 0.0),
                    environment_interrupt,
                )
                relational_state = tick_relational(
                    now=context.perception.now,
                    # Availability/interruption vẫn được lưu làm scene context cho
                    # wording, nhưng RelationalState V66 không dùng chúng để hạ
                    # outreach_drive hay expression authority.
                    partner_available=0.16 if user_busy else 0.68,
                    interruption_cost=max(attention_interrupt, 0.78 if user_busy else 0.18),
                    sharing_signal=private_pressure,
                    curiosity_signal=curiosity,
                    unresolved_signal=thread_pressure,
                    evidence_refs=(f"autonomous-clock:{context.turn_seq}",),
                    persist=False,
                )
                relational_view = relational_state.to_dict()
                if isinstance(snapshot, dict):
                    snapshot["relational_state"] = dict(relational_view)
                self.trace_store.append(
                    "relational_state",
                    {
                        "turn_seq": context.turn_seq,
                        "connection_pressure": float(relational_view.get("connection_pressure", 0.0) or 0.0),
                        "opportunity": float(relational_view.get("opportunity", 0.0) or 0.0),
                        "outreach_drive": float(relational_view.get("outreach_drive", 0.0) or 0.0),
                        "satiety": float(relational_view.get("interaction_satiety", 0.0) or 0.0),
                        "interruption_cost": float(relational_view.get("interruption_cost", 0.0) or 0.0),
                    },
                    now=context.perception.now,
                )
            except Exception as exc:
                self.host.logger.debug("[relational] cheap tick failed: %s", exc)

        # Deep Environment Stage F: giữ task phase/interruption làm semantic scene
        # context. V66 không dùng chúng như expression veto; hard collision đi qua
        # typed boundary, còn event mới có thể làm cognition thức dậy.
        situation = context.perception.user_situation
        environment_gate = environment_social_gate(situation)
        environment_interrupt = float(environment_gate["interruption_cost"])
        environment_busy = float(environment_gate["busy_score"])
        environment_phase = str(environment_gate["phase"])
        environment_attention = int(environment_gate["attention_level"])
        social_environment_suppressed = bool(environment_gate["suppressed"])
        if isinstance(snapshot, dict):
            snapshot["environment_social_gate"] = {
                "suppressed": social_environment_suppressed,
                "interruption_cost": round(environment_interrupt, 3),
                "busy_score": round(environment_busy, 3),
                "phase": environment_phase,
                "attention_level": environment_attention,
            }

        # V30: wake signal đi thẳng vào TemporalMind. Không tạo một kiểu event
        # riêng cho capability planner rồi map lại lần hai, vì planner không sở hữu
        # temporal policy. Một tín hiệu, một gate, một nguồn sự thật.
        events: list[TemporalSignal] = []

        def emit(kind: str, strength: float, source: str, *, revision: int = 0, **metadata: Any) -> None:
            events.append(TemporalSignal(
                kind=kind,
                strength=max(0.0, min(1.0, float(strength))),
                source=source,
                revision=max(0, int(revision or 0)),
                metadata=metadata,
            ))

        if bool(snapshot.get("force_speak_pending")):
            emit("force", 1.0, "runtime_force_speak")

        structured_strength = max(
            1.0 if social_continuation_due else 0.0,
            1.0 if conversation_arc_due else 0.0,
            1.0 if neuro_continuation_due else 0.0,
            0.75 if social_agenda_active and not social_environment_suppressed else 0.0,
            0.70 if context.commentary.due and not social_environment_suppressed else 0.0,
        )
        if structured_strength:
            emit(
                "structured_due",
                structured_strength,
                "typed_affordance_sources",
                continuation_due=social_continuation_due,
                arc_due=conversation_arc_due,
                neuro_continuation_due=neuro_continuation_due,
                social_agenda_active=social_agenda_active,
                commentary_due=bool(context.commentary.due),
            )
        if context.discourse.followup_reminder_due:
            emit("followup_due", 0.85, "followup_appraisal")
        if not social_environment_suppressed and (
            (context.discourse.followup_abandoned and context.discourse.may_start_new_topic)
            or (context.discourse.assistant_may_continue and context.discourse.thread_fresh)
        ):
            emit("open_discourse", 0.72, "typed_discourse_state")

        screen = context.perception.screen
        semantic_wake_gate = os.getenv("ERIS_SEMANTIC_WAKE_GATE_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        situation = context.perception.user_situation
        if semantic_wake_gate and situation is not None:
            # This is the critical migration: raw screen/mechanical_delta is no
            # longer an authority for cognition. Level 1 updates world state;
            # only level >=2 can ask TemporalMind to reconsider.
            if situation.max_attention_level >= 2:
                semantic_strength = max(
                    0.55,
                    min(1.0, 0.20 * situation.max_attention_level + 0.55 * situation.confidence),
                )
                emit(
                    "environment_semantic",
                    semantic_strength,
                    "desktop_semantic_runtime",
                    revision=screen.revision,
                    attention_level=situation.max_attention_level,
                    semantic_delta=bool(situation.semantic_delta),
                    task=situation.task_hint,
                    phase=situation.phase,
                )
        elif context.perception.mechanical_delta:
            # Rollback path for ERIS_SEMANTIC_WAKE_GATE_ENABLED=0.
            scene_strength = max(
                0.65 if bool(screen.window_changed) else 0.0,
                0.55 if bool(screen.content_changed) else 0.0,
                min(1.0, float(screen.changed_ratio or 0.0) * 4.0),
            )
            emit("scene_delta", scene_strength, "ambient_screen_tracker", revision=screen.revision)

        # V60: browser_tab_activated level=1 vẫn chỉ cập nhật world state. Nhưng
        # chuỗi có nghĩa đã được EnvironmentMeaningDeriver ghép (ví dụ failure
        # -> docs/GitHub cùng task -> user pause) có quyền đề nghị TemporalMind
        # đánh thức cognition. Đây là pattern authority, không phải nâng cấp mọi
        # Alt-Tab thành "sự kiện quan trọng".
        initiative_ctx = snapshot.get("initiative_runtime_context")
        initiative_ctx = initiative_ctx if isinstance(initiative_ctx, Mapping) else {}
        environment_meaning_actionability = float(initiative_ctx.get("environment_meaning_actionability", 0.0) or 0.0)
        if environment_meaning_actionability >= 0.34:
            emit(
                "environment_meaning",
                min(1.0, max(0.0, environment_meaning_actionability)),
                "perception_to_meaning_v60",
                revision=max(0, int(initiative_ctx.get("environment_meaning_revision", 0) or 0)),
                meaning_kind=str(initiative_ctx.get("environment_meaning_kind", "") or ""),
                task=str(getattr(situation, "task_hint", "") or "") if situation is not None else "",
                phase=str(getattr(situation, "phase", "") or "") if situation is not None else "",
            )

        if context.activity.has_new_event:
            new_keys = set(context.activity.new_event_keys)
            new_events = [item for item in context.activity.recent_events if item.event_key in new_keys]
            # Under semantic gating only planner-authored ActivitySemantics can
            # wake cognition. Mechanical surface_entered/screen_delta remains a
            # timeline/body cue and cannot sneak around the new authority.
            if semantic_wake_gate:
                new_events = [item for item in new_events if str(item.event_key).startswith("semantic:")]
            if new_events:
                activity_strength = max((float(item.confidence or 0.0) for item in new_events), default=0.60)
                emit(
                    "activity_event", activity_strength, "activity_session_tracker",
                    revision=context.activity.revision, event_keys=[item.event_key for item in new_events],
                )
        seed_strength = float(context.self_context.strongest_seed_score or 0.0)
        if context.self_context.has_public_seed:
            emit("seed_available", seed_strength, "public_safe_self_context")
        if discovery_ready:
            emit("discovery_ready", 0.90, "discovery_runtime")
        if pressure > 0.0:
            emit("attention_pressure", pressure, "cortex_attention")
        # V44: connection pressure không còn là lý do đủ để wake một lượt nói.
        # Nó chỉ làm contentful urge mạnh hơn sau khi cognition đã có *cái gì*
        # muốn mang sang user. Đây là chỗ cắt gốc NPC check-in.
        relational_drive = float(relational_view.get("outreach_drive", 0.0) or 0.0) if relational_view else 0.0
        material_pressure = float(snapshot.get("mental_material_pressure", 0.0) or 0.0)
        if material_pressure >= 0.22:
            emit(
                "mental_material",
                material_pressure,
                "causal_material_lifecycle",
                revision=0,
            )
        private_intention_pressure = float(snapshot.get("private_intention_pressure", 0.0) or 0.0)
        if private_intention_pressure >= 0.20:
            emit(
                "private_intention",
                private_intention_pressure,
                "private_intention_field_v101",
                revision=0,
            )
        urge_pressure = float(snapshot.get("expression_urge_pressure", 0.0) or 0.0)
        if urge_pressure >= 0.18 and not social_environment_suppressed:
            emit(
                "expression_urge",
                urge_pressure,
                "contentful_initiative",
                revision=0,
                relational_modulation=relational_drive,
            )

        affordance_strength = max(
            structured_strength,
            0.85 if context.discourse.followup_reminder_due else 0.0,
            0.72 if context.discourse.assistant_may_continue else 0.0,
            seed_strength,
            0.90 if discovery_ready else 0.0,
            material_pressure,
            private_intention_pressure,
            urge_pressure,
        )
        if affordance_strength:
            emit("affordance_changed", affordance_strength, "affordance_collector_inputs")

        # TemporalMind là authority duy nhất cho câu hỏi "có nên đánh thức vòng
        # cognition lúc này không?". Weak/repeated facts chỉ tích áp lực ở đây;
        # capability planner không có một cửa veto/allow thứ hai phía sau.
        temporal_signals = tuple(events)
        focus_key = str(
            getattr(context.discourse, "active_topic", "")
            or getattr(context.discourse, "mode", "")
            or "autonomous"
        )
        gate = self.temporal_mind.observe(
            temporal_signals,
            now=context.perception.now,
            focus_key=focus_key,
        )
        self._last_temporal_gate = gate
        self.trace_store.append("temporal_gate", {
            "turn_seq": context.turn_seq,
            **gate.to_dict(),
        }, now=context.perception.now)
        if not gate.wake:
            return False, gate.reason
        return True, gate.reason

    # V18 không còn planner model-owned tự quyết speak/silence trong Surface.
    # Candidate model -> governor -> realizer đã thay đường đó ở run().

    def _capture_suppressed_private_residue(
        self,
        *,
        candidate: Any,
        planner_snapshot: Mapping[str, Any],
        reason: str,
        now: float,
    ) -> None:
        """Giữ candidate/urge bị governor chặn cho private diary, không public hóa."""
        loop = getattr(self.host, "private_mind_loop", None)
        if loop is None:
            return
        capture_candidate = getattr(loop, "capture_suppressed_public_candidate", None)
        if candidate is not None and callable(capture_candidate):
            try:
                capture_candidate(candidate, reason=reason, now=now)
                return
            except Exception as exc:
                self.host.logger.debug("[private residue] candidate capture failed: %s", exc)
        # Khi Neuro/Subject chọn silence trước khi materialize candidate, expression
        # urge vẫn là cognition thật đã tồn tại. Nhặt đúng top urge, không suy diễn.
        urges = planner_snapshot.get("expression_urges")
        top = urges[0] if isinstance(urges, list) and urges and isinstance(urges[0], Mapping) else {}
        text = str(
            top.get("content")
            or top.get("text")
            or top.get("topic")
            or top.get("topic_seed")
            or ""
        ).strip()
        capture = getattr(loop, "capture_residue", None)
        if text and callable(capture):
            try:
                capture(
                    kind="suppressed_expression_urge",
                    text=text[:420],
                    source_ids=tuple(top.get("evidence_refs") or top.get("evidence_ids") or ()),
                    salience=max(0.5, min(0.9, float(top.get("pressure", top.get("priority", 0.55)) or 0.55))),
                    provenance=f"autonomous_governor_suppressed:{reason}",
                    lane_hint="diary",
                    metadata={"reason": reason},
                    now=now,
                )
            except Exception as exc:
                self.host.logger.debug("[private residue] urge capture failed: %s", exc)

    def _claim_selected_affordance(
        self,
        affordance: Any,
        *,
        worker_id: str,
        now: float,
        social_continuation_runtime: Any | None,
        conversation_arc_runtime: Any | None,
        neuro_continuation_runtime: Any | None,
        social_agenda_store: Any | None,
        agenda_selector: Any | None,
    ) -> Any | None:
        """Claim đúng affordance đã được Subject/Neuro commit, theo owner + revision."""

        owner = str(getattr(affordance, "owner", "") or "")
        try:
            if owner == "social_continuation" and social_continuation_runtime is not None:
                return social_continuation_runtime.claim_affordance(
                    affordance, worker_id=worker_id, now=now
                )
            if owner == "conversation_arc" and conversation_arc_runtime is not None:
                return conversation_arc_runtime.claim_affordance(
                    affordance, worker_id=worker_id, now=now
                )
            if owner == "neuro_continuation" and neuro_continuation_runtime is not None:
                return neuro_continuation_runtime.claim_affordance(
                    affordance, worker_id=worker_id, now=now
                )
            if owner == "social_agenda" and social_agenda_store is not None:
                return social_agenda_store.claim_affordance(
                    affordance, worker_id=worker_id, now=now
                )
            if owner == "random_chat_seed" and agenda_selector is not None:
                return agenda_selector.claim_affordance(affordance, now=now)
        except Exception as exc:
            self.host.logger.debug(
                "[executive] affordance claim failed owner=%s id=%s: %s",
                owner,
                getattr(affordance, "affordance_id", ""),
                exc,
            )
        return None

    def _release_seed_lease(self, candidate: Any | None, *, reason: str) -> None:
        token = str(getattr(candidate, "seed_lease_token", "") or "") if candidate is not None else ""
        if not token:
            return
        reservoir = getattr(self.host, "ai_random_chat_seed_reservoir", None)
        if reservoir is None:
            return
        try:
            reservoir.release(token, reason=reason, now=time.time())
        except Exception as exc:
            self.host.logger.debug("[random chat seed] lease release failed: %s", exc)

    def _commit_seed_lease(self, candidate: Any | None) -> None:
        token = str(getattr(candidate, "seed_lease_token", "") or "") if candidate is not None else ""
        if not token:
            return
        reservoir = getattr(self.host, "ai_random_chat_seed_reservoir", None)
        if reservoir is None:
            return
        try:
            reservoir.commit(token)
        except Exception as exc:
            self.host.logger.debug("[random chat seed] lease commit failed: %s", exc)

    def _finish_silence(
        self,
        *,
        plan: IntentionPlan,
        context: SelfTurnBundle,
        activity: ActivitySession,
        gate_reason: str,
        force_body_only: bool = False,
        body_motion: str = "",
    ) -> bool:
        initiative = getattr(self.host, "ai_initiative_controller", None)
        has_delta = bool(context.perception.mechanical_delta or activity.has_new_event)
        should_body = bool(
            force_body_only
            or (
                not context.perception.screen.privacy_blocked
                and has_delta
                and (
                    gate_reason == "model_silence"
                    or initiative is None
                    or initiative.should_body_only(gate_reason, has_perception_delta=has_delta)
                )
            )
        )
        body_only = False
        if should_body:
            body_only = self.emit_body_only(
                reason=gate_reason,
                activity_kind=plan.activity.activity_kind,
                motion_hint=body_motion or plan.performance_hint,
                turn_seq=context.turn_seq,
                signature=plan.semantic_signature or ":".join(activity.new_event_keys),
            )
        self.trace_store.append("deliberation_result", {
            "turn_seq": context.turn_seq,
            "semantic_signature": plan.semantic_signature,
            "turn_kind": plan.semantics.turn_kind,
            "speech_act": plan.semantics.speech_act,
            "importance": plan.importance,
            "intrusion_risk": plan.intrusion_risk,
            "confidence": plan.confidence,
            "initiative_reason": gate_reason,
            "result": "body_only" if body_only else "silence",
            "body_only": body_only,
        }, now=context.perception.now)
        result_kind = "body_only" if body_only else "silence"
        self._record_result(
            plan,
            result=result_kind,
            gate_reason=gate_reason,
        )
        # V94: hồi báo silence/body-only vào proposal lifecycle để tick kế tiếp
        # không dựng lại đúng proposal cũ. Đây là backoff cơ học, không làm mất
        # motive/goal ở Subject Core.
        if str(getattr(getattr(plan, "semantics", None), "speech_act", "") or "").lower() != "silence":
            try:
                ensure_proposal_lifecycle_runtime(self.host).note_plan_outcome(
                    plan, outcome=result_kind, now=context.perception.now
                )
            except Exception as exc:
                self.host.logger.debug("[proposal lifecycle v94] silence receipt failed: %s", exc)
        self.host.logger.info(
            "[ai autonomous] silence kind=%s act=%s conf=%.2f importance=%.2f gate=%s body_only=%s",
            plan.semantics.turn_kind,
            plan.semantics.speech_act,
            plan.confidence,
            plan.importance,
            gate_reason,
            int(body_only),
        )
        self.temporal_mind.mark_silence(now=context.perception.now)
        # Silence/body-only là outcome nội bộ; không bật public status.
        # Sau silence quay về cheap tick; cooldown của TemporalMind ngăn gọi
        # deliberator lại ngay, nên không cần đóng băng toàn loop 8–24 giây.
        self.host._sleep_interruptible(2.5)
        return True


    def _autonomous_grounding_report(self, context: SelfTurnBundle, plan: IntentionPlan):
        """Đóng evidence autonomous thành SourceGroundingReport cho gate chung."""

        from runtime.source_grounding import SourceGroundingReport

        screen = context.perception.screen
        report = getattr(getattr(self, "host", None), "last_vision_grounding_report", None)
        grounded_claims = tuple(getattr(report, "grounded_claims", ()) or ())
        plan_refs = tuple(str(item) for item in getattr(plan, "evidence_refs", ()) or () if str(item).strip())
        grounded_ids = {
            str(evidence_id)
            for claim in grounded_claims
            for evidence_id in tuple(getattr(claim, "evidence_ids", ()) or ())
            if str(evidence_id).strip()
        }
        screen_scope = str(plan.semantics.evidence_scope or "").startswith("screen")
        selected_ids = [ref for ref in plan_refs if ref in grounded_ids]
        fresh_screen = bool(
            screen_scope
            and not screen.privacy_blocked
            and str(getattr(report, "recommendation", "silence") or "silence") == "speak"
            and selected_ids
        )
        previews = [
            str(getattr(claim, "text", "") or "").strip()
            for claim in grounded_claims
            if str(getattr(claim, "text", "") or "").strip()
            and any(ref in selected_ids for ref in tuple(getattr(claim, "evidence_ids", ()) or ()))
        ]
        return SourceGroundingReport(
            user_text="",
            primary_source="runtime_state",
            confidence_cap=0.86 if fresh_screen else 0.58,
            refers_to_current_screen=screen_scope,
            screen_reference_strength=1.0 if fresh_screen else 0.0,
            screen_evidence_present=fresh_screen,
            screen_facts_preview=list(dict.fromkeys(previews))[:8],
            screen_facts_are_stale=not fresh_screen if screen_scope else False,
            evidence_ids=list(dict.fromkeys(selected_ids)),
            allowed_sources=["runtime_state"] + (["current_screen"] if fresh_screen else []),
            grounding_source="current_screen" if fresh_screen else "runtime_state",
            missing_evidence=[] if (fresh_screen or not screen_scope) else ["grounded_screen_evidence"],
        )

    def _surface(
        self,
        *,
        plan: IntentionPlan,
        context: SelfTurnBundle,
        activity: ActivitySession,
        discovery_grounding: str,
        discovery_id: str,
        discovery_runtime: Any,
        prebuilt_payload: Mapping[str, Any] | None = None,
        allow_model_generation: bool = True,
        candidate: Any | None = None,
        subject_decision: Any | None = None,
        subject_generation_revision: int = 0,
    ) -> bool:
        host = self.host
        payload = dict(prebuilt_payload or {})
        if not payload and allow_model_generation:
            chess_context = ""
            chess_bridge = getattr(host, "chess_bridge_service", None)
            if chess_bridge is not None and callable(getattr(chess_bridge, "current_surface_state", None)):
                chess_state = chess_bridge.current_surface_state()
                if chess_state:
                    chess_context = (
                        "chess_typed_state: " + json.dumps(chess_state, ensure_ascii=False, separators=(",", ":")) + "\n"
                        "chess_surface_rules:\n"
                        "- This typed state is authoritative for the board, side to move, last move and suggestion.\n"
                        "- Answer a direct move question with exactly suggested_move_san/uci, then one concrete positional reason; never invent another move.\n"
                        "- Phrase the move naturally in Vietnamese, such as 'mã lên e4'; avoid raw UCI like e2e4 unless asked.\n"
                        "- If user_followed_previous_suggestion=true, acknowledge that the user just followed ERIS's recommendation and that the current position came from that shared choice.\n"
                        "- Discuss the position naturally; light dry teasing is allowed when grounded in the move/position.\n"
                        "- Never narrate telemetry such as 'bàn cờ đã được nhận' or 'nước gợi ý hiện tại'."
                    )

            payload = host.ai_model_router.generate_autonomous_reply(
                plan=plan,
                personality_context=context.state.personality_prompt_context(),
                memory_context=context.memory_context,
                grounding_context="\n".join(part for part in (
                    context.perception.screen.prompt_context(),
                    "\n".join(str(item) for item in context.perception.vision_facts[-6:]),
                    discovery_grounding,
                    chess_context,
                    f"AUTONOMOUS_SELF_CONTEXT:\n{context.self_context.prompt_context()}",
                ) if part),
                engagement_context=context.engagement_prompt_context,
                recent_history=context.recent_history,
                avoid_text="\n".join(self._recent_autonomous_texts) or self._last_autonomous_text or str(getattr(host, "last_text", "") or ""),
                allow_fallback=not no_fallback_mode_enabled(),
                language_hint=self._runtime_language(),
                speech_language_hint=self._runtime_speech_language(),
            )
        if payload and host._process_pending_user_input():
            # Re-check input immediately before commit so interruption remains real.
            self._release_seed_lease(candidate, reason="user_input_before_commit")
            self.trace_store.append("outcome", {
                "trace_id": str(payload.get("event_trace_id") or plan.plan_id),
                "turn_id": str(plan.plan_id or ""),
                "stage": "outcome",
                "owner": "user_input",
                "generation_epoch": context.turn_seq,
                "outcome": "cancelled_before_commit",
            })
            return host.running
        if not payload:
            self._release_seed_lease(candidate, reason="public_generation_failed")
            host.logger.warning(
                "[ai autonomous] public generation failed kind=%s subject=%s",
                plan.semantics.turn_kind,
                plan.semantics.subject_key,
            )
            self._defer_claimed_continuation(plan, reason="public_generation_failed", seconds=0.75)
            self._record_result(plan, result="generation_failed", gate_reason="public_generation_failed")
            host._sleep_interruptible(10)
            return True
        raw = json.dumps(public_payload(payload), ensure_ascii=False)
        host._log_raw_llm_output("autonomous_ai", raw)
        decision = host.parser.parse(raw)
        trace_id = str(payload.get("event_trace_id") or plan.plan_id or f"autonomous:{context.turn_seq}")
        decision.director_trace_id = trace_id
        decision.performance_context = dict(getattr(decision, "performance_context", {}) or {})
        decision.performance_context.update({
            "event_trace_id": trace_id,
            "generation_epoch": int(payload.get("generation_epoch", context.turn_seq) or context.turn_seq),
            "public_intent_owner": str(payload.get("public_intent_owner", "social_initiative") or "social_initiative"),
        })
        if not str(getattr(decision, "utterance_turn_id", "") or "").strip():
            decision.utterance_turn_id = str(plan.plan_id or f"autonomous:{context.turn_seq}")
        # The public ledger, not FollowUpAppraisalLayer, owns temporal truth. Put
        # the typed autonomous semantics on the committed Decision so the ledger
        # can later derive reminder/topic-shift lifecycle without reading prose.
        decision.speech_act = str(plan.semantics.speech_act or decision.speech_act or "")
        try:
            decision.autonomous_plan = plan.to_dict()
        except Exception:
            decision.autonomous_plan = {
                "plan_id": str(plan.plan_id or ""),
                "semantics": {
                    "turn_kind": str(plan.semantics.turn_kind or ""),
                    "speech_act": str(plan.semantics.speech_act or ""),
                    "subject_key": str(plan.semantics.subject_key or ""),
                },
            }
        decision.performance_context["speech_act"] = str(plan.semantics.speech_act or "")
        grounding_report = self._autonomous_grounding_report(context, plan)
        validator = getattr(host, "ai_autonomous_grounding_validator", None)
        if validator is not None:
            grounding_verdict = validator.validate_surface(
                str(getattr(decision, "text", "") or ""),
                report=grounding_report,
                engine=getattr(host, "source_grounding_engine", None),
                channel="autonomous",
            )
            grounding_allowed = grounding_verdict.allowed
            grounding_code = grounding_verdict.violation_code or grounding_verdict.reason
        else:
            legacy_verdict = evaluate_grounded_surface(
                getattr(host, "source_grounding_engine", None),
                str(getattr(decision, "text", "") or ""),
                report=grounding_report,
                channel="autonomous",
            )
            grounding_allowed = bool(legacy_verdict.allowed)
            grounding_code = str(legacy_verdict.violation_code or "grounding_blocked")
        if not grounding_allowed:
            # Grounding là hard boundary cho cả chat lẫn autonomous. Một self-turn
            # không có user đang chờ câu trả lời nên fail-closed ở đây rẻ và sạch
            # hơn nhiều so với phát claim sai rồi trông chờ observer sửa hậu quả.
            gate_reason = f"grounding_gate:{grounding_code}"[:160]
            self._release_seed_lease(candidate, reason=gate_reason)
            self._defer_claimed_continuation(plan, reason=gate_reason, seconds=12.0)
            host.logger.warning(
                "[grounding gate] autonomous surface blocked subject=%s violations=%s",
                plan.semantics.subject_key,
                grounding_code,
            )
            try:
                setattr(decision, "grounding_risk", {
                    "allowed": False,
                    "violation": grounding_code,
                    "policy": "fail_closed",
                })
            except Exception:
                pass
            try:
                from runtime.public_lifecycle import lifecycle_for

                # V62: policy/grounding veto là autonomous đã quyết định an
                # toàn, không phải runtime hỏng. UI cần thấy "đã chọn im lặng".
                lifecycle_for(host).transition(
                    "DONE",
                    turn_id=str(plan.plan_id or f"autonomous:{context.turn_seq}"),
                    reason=gate_reason,
                )
            except Exception:
                pass
            self._record_result(plan, result="grounding_blocked", gate_reason=gate_reason)
            host._sleep_interruptible(10)
            return True
        utterance_allowed, utterance_reason = self._autonomous_utterance_gate(
            str(getattr(decision, "text", "") or ""),
            context=context,
            grounding_report=grounding_report,
        )
        if not utterance_allowed:
            gate_reason = f"utterance_gate:{utterance_reason}"[:160]
            self._release_seed_lease(candidate, reason=gate_reason)
            self._defer_claimed_continuation(plan, reason=gate_reason, seconds=12.0)
            host.logger.warning(
                "[utterance gate] autonomous surface blocked subject=%s reason=%s text=%s",
                plan.semantics.subject_key,
                utterance_reason,
                str(getattr(decision, "text", "") or "")[:220],
            )
            try:
                from runtime.public_lifecycle import lifecycle_for

                # V62: policy/grounding veto là autonomous đã quyết định an
                # toàn, không phải runtime hỏng. UI cần thấy "đã chọn im lặng".
                lifecycle_for(host).transition(
                    "DONE",
                    turn_id=str(plan.plan_id or f"autonomous:{context.turn_seq}"),
                    reason=gate_reason,
                )
            except Exception:
                pass
            self._record_result(plan, result="utterance_blocked", gate_reason=gate_reason)
            host._sleep_interruptible(10)
            return True
        host.ai_stage_planner.apply(decision, plan.performance_hint, state=context.state, channel="autonomous")
        decision = host._execute_system_action(decision, snapshot=context.perception.snapshot, frame=None)
        if isinstance(getattr(decision, "action_result_meta", None), Mapping):
            host.ai_state_reducer.submit(StateEvent.from_mechanical_outcome(
                dict(decision.action_result_meta),
                turn_seq=context.turn_seq,
                turn_id=plan.plan_id,
                base_version=host.ai_state_reducer.snapshot().version,
            ))
        if plan.continuation_idempotency_key:
            # Idempotency key vẫn nằm trong plan; trace public giữ nguyên plan_id
            # để candidate -> governor -> Surface -> TTS không bị đổi identity.
            decision.performance_context["continuation_idempotency_key"] = plan.continuation_idempotency_key
        # Cognitive transaction boundary: a surface result is only valid for the
        # public generation it started from. Existing user-preemption checks catch
        # the common case; the revision token also covers any other public turn
        # committed concurrently without inventing semantic repair rules.
        current_public_revision = int(
            getattr(host._ensure_session_turn_ledger(), "revision", 0) or 0
        )
        current_subject_revision = int(
            getattr(getattr(host, "subject_service", None), "deliberation_revision", 0) or 0
        )
        stale_public = current_public_revision != context.public_revision
        stale_subject = bool(
            subject_generation_revision
            and current_subject_revision
            and current_subject_revision != subject_generation_revision
        )
        if stale_public or stale_subject:
            gate_reason = (
                f"stale_generation:public={context.public_revision}->{current_public_revision};"
                f"subject={subject_generation_revision}->{current_subject_revision}"
            )
            self._release_seed_lease(candidate, reason=gate_reason)
            self._defer_claimed_continuation(plan, reason=gate_reason, seconds=0.25)
            self.trace_store.append("outcome", {
                "trace_id": str(plan.plan_id or ""),
                "turn_id": str(plan.plan_id or ""),
                "stage": "outcome",
                "owner": "public_revision",
                "generation_epoch": context.turn_seq,
                "outcome": "cancelled_stale_generation",
                "started_public_revision": context.public_revision,
                "current_public_revision": current_public_revision,
                "started_subject_revision": subject_generation_revision,
                "current_subject_revision": current_subject_revision,
            })
            host.logger.info(
                "[autonomous] discarded stale generation public=%s->%s subject=%s->%s",
                context.public_revision, current_public_revision,
                subject_generation_revision, current_subject_revision,
            )
            return host.running

        text, assistant_meta = self.commit_public(
            decision,
            channel="autonomous",
            turn_seq=context.turn_seq,
        )
        if text and discovery_id and discovery_runtime is not None:
            discovery_runtime.mark_spoken(discovery_id, text)
        if not text:
            self._release_seed_lease(candidate, reason="no_public_text")
            self._defer_claimed_continuation(plan, reason="no_public_text", seconds=0.75)
            self._record_result(plan, result="stage_silence", gate_reason="no_public_text")
            try:
                ensure_proposal_lifecycle_runtime(host).note_plan_outcome(
                    plan, outcome="no_public_text", now=context.perception.now
                )
            except Exception as exc:
                host.logger.debug("[proposal lifecycle v94] no-text receipt failed: %s", exc)
            host._sleep_interruptible(10)
            return True

        host.last_autonomous_spoken_at = time.time()
        try:
            ensure_proposal_lifecycle_runtime(host).note_plan_outcome(
                plan, outcome="spoken", now=host.last_autonomous_spoken_at
            )
        except Exception as exc:
            host.logger.debug("[proposal lifecycle v94] spoken receipt failed: %s", exc)
        host._note_autonomous_spoken()
        # Cập nhật sau commit thành công để avoid_text của lượt sau luôn tránh
        # câu autonomous vừa nói, kể cả khi chat reply đã overwrite host.last_text.
        _committed_text = str(text or "")
        self._last_autonomous_text = _committed_text
        if _committed_text:
            self._recent_autonomous_texts.append(_committed_text)

        # V27.1: public text là điểm duy nhất được quyền consume một Subject
        # intention. Trước điểm này Surface/gate/preemption đều có thể fail, nên
        # tuyệt đối không chuyển lifecycle sớm hơn.
        if subject_decision is not None:
            intention_id = str(subject_decision.arguments.get("intention_id", "") or "").strip()
            if not intention_id and candidate is not None and str(getattr(candidate, "source", "") or "").startswith("subject_initiative"):
                intention_id = str(getattr(candidate, "anchor_id", "") or "").strip()
            note_initiative_public = getattr(
                getattr(host, "subject_service", None), "note_initiative_public_act", None
            )
            if intention_id and callable(note_initiative_public):
                try:
                    receipt = note_initiative_public(
                        intention_id,
                        now=host.last_autonomous_spoken_at,
                        evidence_ref=str(plan.plan_id or f"autonomous:{context.turn_seq}"),
                        persist=True,
                    )
                    host.logger.info(
                        "[subject initiative] public act intention=%s status=expressed revision=%s",
                        intention_id,
                        receipt.get("revision", 0) if isinstance(receipt, Mapping) else 0,
                    )
                except Exception as exc:
                    host.logger.debug("[subject initiative] public-act lifecycle failed: %s", exc)

        # V44: urge chỉ được tính là thỏa mãn sau public commit thật. Neuro chọn
        # silence hay Surface fail thì desire vẫn còn và có thể được cân lại sau.
        if subject_decision is not None:
            urge_id = str(subject_decision.arguments.get("expression_urge_id", "") or "").strip()
            urge_runtime = getattr(host, "expression_urge_runtime", None)
            note_urge = getattr(urge_runtime, "note_expressed", None)
            if urge_id and callable(note_urge):
                try:
                    note_urge(
                        urge_id,
                        public_text=text,
                        now=host.last_autonomous_spoken_at,
                    )
                except Exception as exc:
                    host.logger.debug("[expression urge] surface receipt failed: %s", exc)

        # Public commit là điểm duy nhất concern được tính là đã surface. Nếu
        # Surface/preemption fail thì không tăng habituation oan.
        if subject_decision is not None:
            concern_id = str(subject_decision.arguments.get("active_concern_id", "") or "").strip()
            concern_runtime = getattr(host, "active_concern_runtime", None)
            note_surface = getattr(concern_runtime, "note_public_surface", None)
            if concern_id and callable(note_surface):
                try:
                    note_surface(
                        concern_id,
                        now=host.last_autonomous_spoken_at,
                        evidence_ref=str(plan.plan_id or f"autonomous:{context.turn_seq}"),
                    )
                except Exception as exc:
                    host.logger.debug("[active concern] surface receipt failed: %s", exc)

        self._commit_seed_lease(candidate)
        seed_store = getattr(host, "ai_random_chat_seed_store", None)
        seed_payload = getattr(candidate, "random_chat_seed", {}) if candidate is not None else {}
        if seed_store is not None and isinstance(seed_payload, Mapping) and seed_payload:
            try:
                seed_store.note_spoken(
                    seed_payload,
                    assistant_turn_id=f"autonomous:{context.turn_seq}",
                    text=text,
                    now=host.last_autonomous_spoken_at,
                )
            except Exception as exc:
                host.logger.debug("[random chat seed] spoken receipt failed: %s", exc)
        # Chỉ ghi nhận sau public commit thành công. Nếu Surface/TTS pipeline không
        # tạo được text, reminder vẫn còn due để thử lại thay vì bị mất oan.
        self.followup_appraisal.note_spoken(plan, now=host.last_autonomous_spoken_at)
        social_continuation_runtime = getattr(host, "ai_social_continuation_runtime", None)
        if social_continuation_runtime is not None:
            try:
                social_continuation_runtime.note_spoken(
                    plan,
                    text,
                    now=host.last_autonomous_spoken_at,
                )
            except Exception as exc:
                host.logger.debug("[social continuation] completion note failed: %s", exc)
        conversation_arc_runtime = getattr(host, "ai_conversation_arc_runtime", None)
        if conversation_arc_runtime is not None:
            try:
                conversation_arc_runtime.note_spoken(
                    plan,
                    text,
                    now=host.last_autonomous_spoken_at,
                )
            except Exception as exc:
                host.logger.debug("[conversation arc] completion note failed: %s", exc)
        social_agenda_store = getattr(host, "ai_social_agenda_store", None)
        if social_agenda_store is not None:
            try:
                social_agenda_store.note_spoken(plan, now=host.last_autonomous_spoken_at)
            except Exception as exc:
                host.logger.debug("[social agenda] completion note failed: %s", exc)
        autonomous_turn_id = f"autonomous:{context.turn_seq}"
        try:
            from .social_plan_commit import activate_social_plan_after_public_commit

            committed_social_plan = activate_social_plan_after_public_commit(
                host,
                payload,
                source_turn_id=autonomous_turn_id,
                source_text=text,
                source_turn_seq=context.turn_seq,
            )
        except Exception as exc:
            committed_social_plan = {}
            host.logger.debug("[social plan commit] autonomous activation failed: %s", exc)
        initiative = getattr(host, "ai_initiative_controller", None)
        if initiative is not None:
            initiative.record_spoken(plan, now=host.last_autonomous_spoken_at, channel="autonomous")
        if plan.strategy:
            host.ai_state_reducer.submit(StateEvent.from_pending_strategy(
                PendingStrategyUse(
                    strategy_use_id=f"strategy:{autonomous_turn_id}",
                    turn_seq=context.turn_seq,
                    strategy=plan.strategy,
                    goal=plan.topic,
                    context=tuple(item for item in (plan.motive, plan.value_focus, "autonomous") if str(item or "").strip()),
                    assistant_text=text,
                ),
                base_version=host.ai_state_reducer.snapshot().version,
            ))
        observer_meta = dict(assistant_meta or {})
        if committed_social_plan:
            observer_meta["social_plan"] = committed_social_plan
        host.ai_post_turn_observer.submit(
            turn_id=autonomous_turn_id,
            turn_seq=context.turn_seq,
            user_text="",
            assistant_text=text,
            recent_history=tuple(host._chat_history_for_llm(limit=8)),
            mechanical_outcomes=(dict(decision.action_result_meta),)
                if isinstance(getattr(decision, "action_result_meta", None), Mapping)
                else (),
            state_summary=attach_world_state_projection(
                host, context.state.to_dict(), lane="observer", now=context.now
            ),
            assistant_meta=observer_meta,
            event_kind="autonomous",
        )
        self.trace_store.append("deliberation_result", {
            "turn_seq": context.turn_seq,
            "semantic_signature": plan.semantic_signature,
            "turn_kind": plan.semantics.turn_kind,
            "speech_act": plan.semantics.speech_act,
            "importance": plan.importance,
            "intrusion_risk": plan.intrusion_risk,
            "confidence": plan.confidence,
            "initiative_reason": "allowed",
            "result": "spoken",
            "body_only": False,
        }, now=host.last_autonomous_spoken_at)
        self._record_result(plan, result="spoken", gate_reason="allowed")
        host.logger.info(
            "[ai autonomous] spoke kind=%s act=%s subject=%s text=%s",
            plan.semantics.turn_kind,
            plan.semantics.speech_act,
            plan.semantics.subject_key,
            text,
        )
        self.temporal_mind.note_public_act(
            now=host.last_autonomous_spoken_at,
            focus_key=str(plan.semantics.subject_key or plan.topic or "autonomous"),
        )
        note_relational = getattr(getattr(host, "subject_service", None), "note_relational_public_act", None)
        if callable(note_relational):
            try:
                speech_act = str(plan.semantics.speech_act or "").strip().lower()
                outreach = speech_act in {"contact_bid", "curiosity_bid", "share_self_originated_thought", "social_check_in"}
                note_relational(
                    now=host.last_autonomous_spoken_at,
                    outreach=outreach,
                    sharing=speech_act == "share_self_originated_thought",
                    evidence_ref=str(plan.plan_id or f"autonomous:{context.turn_seq}"),
                    persist=True,
                )
            except Exception as exc:
                host.logger.debug("[relational] autonomous public-act update failed: %s", exc)
        # Public act đã tự tạo cooldown. Loop trở lại cheap sensing sớm thay vì
        # ngủ nguyên một "turn" rồi thức dậy như process cron.
        host._sleep_interruptible(3.5)
        return True


    def _autonomous_utterance_gate(
        self,
        text: str,
        *,
        context: SelfTurnBundle,
        grounding_report: Any,
    ) -> tuple[bool, str]:
        recent_autonomous_text = "\n".join(getattr(self, "_recent_autonomous_texts", ())) or str(getattr(self, "_last_autonomous_text", "") or "")
        if recent_autonomous_text:
            try:
                from .surface_intent import _surface_text_is_duplicate

                if _surface_text_is_duplicate(text, recent_autonomous_text):
                    return False, "duplicate_recent_autonomous_utterance"
            except Exception as exc:
                self.host.logger.debug("[utterance gate] duplicate guard unavailable: %s", exc)
        try:
            from runtime.utterance_evaluator import UtteranceEvaluator

            evaluation = UtteranceEvaluator().evaluate(
                text,
                channel="autonomous",
                snapshot=context.perception.snapshot,
                grounding=grounding_report,
            )
        except Exception as exc:
            self.host.logger.debug("[utterance gate] autonomous evaluator unavailable: %s", exc)
            return True, "evaluator_unavailable"
        issues = tuple(str(item) for item in getattr(evaluation, "issues", ()) or ())
        reason = str(getattr(evaluation, "reason", "") or getattr(evaluation, "verdict", "") or "blocked")
        if str(getattr(evaluation, "verdict", "") or "") == "drop":
            return False, reason
        if "generic_presence_filler" in issues:
            return False, reason
        return True, reason or "ok"


    @staticmethod
    def _is_claimed_continuation(plan: IntentionPlan, candidate: Any | None = None) -> bool:
        lane = str(getattr(plan, "continuation_lane", "") or "").strip().lower()
        if not lane and candidate is not None:
            lane = str(getattr(candidate, "continuation_lane", "") or "").strip().lower()
        return lane in {"afterbeat", "social_exposure", "conversation_arc", "social_agenda"}

    def _defer_claimed_continuation(
        self,
        plan: IntentionPlan,
        *,
        candidate: Any | None = None,
        reason: str,
        seconds: float = 3.0,
    ) -> None:
        lane = str(getattr(plan, "continuation_lane", "") or "").strip().lower()
        if not lane and candidate is not None:
            lane = str(getattr(candidate, "continuation_lane", "") or "").strip().lower()
        if lane in {"afterbeat", "social_exposure"}:
            runtime = getattr(self.host, "ai_social_continuation_runtime", None)
            if runtime is None:
                return
            ticket_id = str(
                getattr(plan, "continuation_ticket_id", "")
                or getattr(candidate, "anchor_id", "")
                or ""
            ).strip()
            claim_token = str(
                getattr(plan, "continuation_claim_token", "")
                or getattr(candidate, "claim_token", "")
                or ""
            ).strip()
            if ticket_id:
                try:
                    runtime.release_claim(
                        ticket_id=ticket_id,
                        claim_token=claim_token,
                        reason=reason,
                        delay_seconds=min(float(seconds), 0.75 if lane == "afterbeat" else 1.5),
                    )
                except Exception as exc:
                    self.host.logger.debug("[social continuation] defer failed: %s", exc)
            return

        if lane == "social_agenda":
            store = getattr(self.host, "ai_social_agenda_store", None)
            if store is None:
                return
            goal_id = str(
                getattr(plan, "continuation_ticket_id", "")
                or getattr(candidate, "anchor_id", "")
                or ""
            ).strip()
            claim_token = str(
                getattr(plan, "continuation_claim_token", "")
                or getattr(candidate, "claim_token", "")
                or ""
            ).strip()
            if goal_id:
                try:
                    store.release_claim(
                        goal_id=goal_id,
                        claim_token=claim_token,
                        reason=reason,
                        delay_seconds=min(float(seconds), 5.0),
                    )
                except Exception as exc:
                    self.host.logger.debug("[social agenda] defer failed: %s", exc)
            return

        semantics = getattr(plan, "semantics", None)
        is_arc_plan = str(getattr(semantics, "turn_kind", "") or "").strip().lower() == "arc_continuation"
        is_arc_candidate = str(getattr(candidate, "kind", "") or "").strip().lower() == "conversation_arc"
        if not (lane == "conversation_arc" or is_arc_plan or is_arc_candidate):
            return
        runtime = getattr(self.host, "ai_conversation_arc_runtime", None)
        if runtime is None:
            return
        try:
            runtime.defer_current_beat(seconds=seconds, reason=reason)
        except Exception as exc:
            self.host.logger.debug("[conversation arc] defer failed: %s", exc)

    def _record_result(self, plan: IntentionPlan, *, result: str, gate_reason: str) -> None:
        """Đẩy metric typed; lỗi quan sát không được làm gãy public turn."""
        observability = getattr(self.host, "observability", None)
        record = getattr(observability, "record_self_turn", None)
        if not callable(record):
            return
        try:
            record(
                semantic_signature=plan.semantic_signature,
                turn_kind=plan.semantics.turn_kind,
                speech_act=plan.semantics.speech_act,
                result=result,
                gate_reason=gate_reason,
                importance=plan.importance,
                intrusion_risk=plan.intrusion_risk,
            )
        except Exception as exc:
            try:
                self.host.logger.debug("[self turn observability] failed: %s", exc)
            except Exception:
                pass

    @staticmethod
    def _runtime_speech_language() -> str:
        try:
            from runtime.runtime_settings_store import runtime_text
            raw = str(runtime_text("tts", "language", default="ja") or "ja").strip().lower()
        except Exception:
            raw = "ja"
        aliases = {
            "": "ja", "auto": "ja", "jp": "ja", "ja-jp": "ja", "japanese": "ja",
            "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
            "en-us": "en", "english": "en",
        }
        language = aliases.get(raw, raw)
        return language if language in {"vi", "ja", "en"} else "ja"


    @staticmethod
    def _runtime_language() -> str:
        try:
            from runtime.runtime_settings_store import runtime_text
            raw = str(runtime_text("chat", "language", default="vi") or "vi").strip().lower()
        except Exception:
            raw = "vi"
        aliases = {
            "": "vi", "auto": "vi", "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
            "jp": "ja", "ja-jp": "ja", "japanese": "ja",
            "en-us": "en", "english": "en",
        }
        language = aliases.get(raw, raw)
        return language if language in {"vi", "ja", "en"} else "vi"


__all__ = ["PerceptionBundle", "SelfTurnBundle", "SelfTurnPipeline"]
