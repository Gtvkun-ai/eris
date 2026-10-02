# -*- coding: utf-8 -*-
"""Extracted coordinator runtime boundary.

The methods remain owner-oriented for backward compatibility while the main
coordinator becomes a small composition surface. New behavior should prefer
typed services over adding more methods to these compatibility mixins.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
from collections.abc import Mapping
from types import SimpleNamespace

from actions.confirmation import public_action_text
from cortex.background_observer import BackgroundObserver, BackgroundObserverConfig
from cortex.daydream_consolidation import DaydreamConsolidator, DaydreamPacket
from cortex.endogenous_drive import EndogenousDriveEngine, RollingInternalState
from cortex.epistemic import EpistemicAgentMindProjection, EpistemicKernel, EpistemicKernelConfig, EpistemicStore, set_default_kernel
from cortex.internal_agenda import InternalAgendaStack
from cortex.observer_contracts import ObserverFrame, SemanticSceneNote, SignalSnapshot, stable_hash
from cortex.appetite_system import AppetiteSystem, build_evidence_buffet
from cortex.connection_drive import ConnectionDrive, ConnectionDriveState
from cortex.contracts import CognitiveDisturbance, PerceptEvent, SocialPresenceEvent, SubconsciousReport, ThoughtSurface, ThoughtStreamReport, TiPolicyReport
from cortex.internal_state import InternalStateEngine, PersistentInternalState
from cortex.micro_policy import MicroLinePolicy, RelationalContext, SemanticRepeatGuard
from cortex.subconscious import build_phase1234567_workers
from cortex.self_observation import SelfObservationEngine
from cortex.self_model import SelfModelEngine
from cortex.thought_stream import ThoughtStream
from cortex.user_context_stream import RollingUserContext, UserContextStream
from cortex.vision_semantic_compressor import RemoteCaptionClient, RemoteStructureClient, VisionCompressorConfig, VisionSemanticCompressor
from domain import Decision
from eris_secrets import get_config
from failure_meta import is_technical_failure_meta
from memory.memory_kernel import MemoryKernel
from runtime.ai_orchestrated.cortex import CortexAttentionSignal, CortexRuntime
from runtime.body_bias import BodyBiasProjector
from runtime.chat_cycle import ChatCycleMixin
from runtime.failure_taxonomy import FailureContext
from runtime.inner_diary_persistence import InnerDiaryPersister
from runtime.interrupt_ledger import InterruptLedger
from runtime.loop_guard import RuntimeLoopGuard
from runtime.model_budget_policy import ModelBudgetPolicy
from runtime.outcome_observer import OutcomeObserver
from runtime.policy_settings import RuntimePolicySettings
from runtime.private_life_daemon import PrivateLifeDaemon
from runtime.private_mind_daemon import PrivateMindDaemon
from runtime.public_payload_policy import sanitize_body_payload
from runtime.public_turn_ledger import PublicTurnLedger
from runtime.public_turn_runtime import PublicTurnRuntime
from runtime.runtime_status import emit_runtime_status
from runtime.repair_state import RepairStateController
from runtime.signal_buffer import SignalBuffer, SignalBufferConfig
from runtime.source_grounding import SourceGroundingEngine
from runtime.stage_contracts import StageFrameBuilder
from runtime.stage_dispatcher import StageDispatcher
from runtime.stage_event_bus import StageEventBus
from runtime.stage_output import StageOutputPipeline
from runtime.stage_protocol_adapter import playback_event, show_plan_event, stage_segment_event, stage_state_event
from runtime.subconscious_loop import SubconsciousLoop as RuntimeSubconsciousLoop
from runtime.subsystem_health import FailureKind, SubsystemHealthRegistry
from runtime.subsystem_supervisor import SubsystemSupervisor
from runtime.thought_model_adapter import RuntimeThoughtModelAdapter
from runtime.transport_boundary import RuntimeTransportBoundary
from runtime.tts_sync_policy import sync_text_with_tts_enabled, text_sync_timeout_seconds, tts_event_releases_deferred_text
from runtime.vision_grounding import VisionGroundingPolicy, VisionGroundingReport
from runtime.voice_manager import VoiceManager
from runtime.vtuber_stage_version import VTUBER_STAGE_PHASES, VTUBER_STAGE_STATUS, VTUBER_STAGE_VERSION
from screen import build_screen_text_runtime


def _vscode_service_mode() -> bool:
    return os.environ.get("ERIS_VSCODE_SERVICE_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


class AutonomousLoopRuntimeMixin:
    def _wake_autonomous_loop(self, reason: str = "external_event") -> None:
        """Đánh thức vòng self-turn mà không phát ngôn từ thread nguồn event."""

        self._autonomous_wakeup_reason = str(reason or "external_event")[:180]
        wake_event = getattr(self, "_autonomous_wakeup_event", None)
        if wake_event is None:
            wake_event = threading.Event()
            self._autonomous_wakeup_event = wake_event
        wake_event.set()
        logger = getattr(self, "logger", None)
        if logger is not None:
            try:
                logger.info("[autonomous wake] reason=%s", self._autonomous_wakeup_reason)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass

    def _sleep_interruptible(self, seconds: float):
        end_at = time.time() + max(0.0, float(seconds))
        wake_event = getattr(self, "_autonomous_wakeup_event", None)
        # Event.wait thay cho sleep thuần để bridge cờ có thể đánh thức planner
        # ngay. Callback chỉ mở mắt vòng loop; quyền nói vẫn thuộc governor.
        while self.running and time.time() < end_at:
            remaining = max(0.0, end_at - time.time())
            interval = min(0.2, remaining)
            if wake_event is not None and wake_event.wait(interval):
                wake_event.clear()
                return
            if wake_event is None:
                time.sleep(interval)
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
        """Đường autonomous production duy nhất: Architecture C + semantic_frame.v1."""
        orchestrator = getattr(self, "ai_autonomous_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error(
                "[architecture C] autonomous unavailable: runtime bootstrap failed; legacy path removed"
            )
            self.stop()
            return False
        return bool(orchestrator.run_iteration())

    def run_loop(self):
        """Chạy runtime production duy nhất: Architecture C + semantic_frame.v1."""
        self.logger.info("--- Architecture C runtime; chat vision theo yêu cầu màn hình ---")
        if _vscode_service_mode():
            service = getattr(self, "agent_ws_service", None)
            if service is None:
                self.logger.error("[vscode-service] agent service is unavailable; cannot run IDE bridge")
                self.stop()
                return
            self.logger.info("[vscode-service] headless IDE bridge mode; autonomous startup and speech loop disabled.")
            while self.running:
                time.sleep(0.5)
            return

        orchestrator = getattr(self, "ai_autonomous_orchestrator", None)
        if not bool(getattr(self, "ai_runtime_enabled", False)) or orchestrator is None:
            self.logger.error("[architecture C] bootstrap failed; legacy runtime has been removed")
            self.stop()
            return

        startup_failed = False
        try:
            orchestrator.run_startup()
            health = getattr(self, "subsystem_health_registry", None)
            if callable(getattr(health, "record_success", None)):
                health.record_success("ai_orchestrated.startup")
        except Exception as exc:
            startup_failed = True
            # V61: process còn sống không có nghĩa startup cognition còn khỏe.
            # Ghi lỗi vào health registry để diagnostics/readiness nhìn thấy ngay,
            # thay vì operator phải đoán từ một WARNING giữa hàng nghìn dòng log.
            health = getattr(self, "subsystem_health_registry", None)
            if callable(getattr(health, "record_failure", None)):
                failure_kind = (
                    FailureKind.PROGRAMMER_ERROR
                    if isinstance(exc, (NameError, AttributeError, TypeError, UnboundLocalError))
                    else FailureKind.UNKNOWN
                )
                try:
                    health.record_failure(
                        "ai_orchestrated.startup",
                        exc,
                        kind=failure_kind,
                        degraded=True,
                        reason="startup autonomous failed before public presence",
                    )
                except Exception:
                    pass
            self._ai_startup_ran = False
            emit_runtime_status(
                self,
                activity="startup",
                phase="retry_wait",
                label="Khởi động lỗi, đang thử lại…",
                active=True,
                tone="warning",
                priority=95,
                notice_ms=0,
                detail=type(exc).__name__,
            )
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
        # Startup now submits an opening opportunity to ConversationKernel. Retry
        # bootstrap failures once, but NoReply is a valid successful decision.
        if startup_failed and self.running:
            try:
                time.sleep(self.runtime_policy_settings.run_loop.startup_retry_delay_seconds)
                orchestrator.run_startup()
                health = getattr(self, "subsystem_health_registry", None)
                if callable(getattr(health, "record_success", None)):
                    health.record_success("ai_orchestrated.startup", details={"recovered_after_retry": True})
            except Exception as exc:
                health = getattr(self, "subsystem_health_registry", None)
                if callable(getattr(health, "record_failure", None)):
                    failure_kind = (
                        FailureKind.PROGRAMMER_ERROR
                        if isinstance(exc, (NameError, AttributeError, TypeError, UnboundLocalError))
                        else FailureKind.UNKNOWN
                    )
                    try:
                        health.record_failure(
                            "ai_orchestrated.startup", exc, kind=failure_kind, degraded=False,
                            reason="startup retry failed; startup presence unavailable",
                        )
                    except Exception:
                        pass
                self._ai_startup_ran = False
                emit_runtime_status(
                    self,
                    activity="startup",
                    phase="failed",
                    label="Không khởi động được",
                    active=True,
                    tone="error",
                    priority=100,
                    notice_ms=0,
                    detail=type(exc).__name__,
                )
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
                self.loop_guard.record_success()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                formatted = " | ".join(
                    line.strip()
                    for line in traceback.format_exc().strip().splitlines()
                    if line.strip()
                )
                delay = self.loop_guard.record_failure(exc)
                self.logger.error(
                    "Unhandled exception inside run_loop; consecutive=%s backoff=%.2fs trace=%s",
                    self.loop_guard.consecutive_errors, delay, formatted,
                )
                if self.loop_guard.should_stop():
                    self.logger.critical(
                        "Autonomous loop circuit opened after %s consecutive failures",
                        self.loop_guard.consecutive_errors,
                    )
                    self.stop()
                    break
                time.sleep(delay)
