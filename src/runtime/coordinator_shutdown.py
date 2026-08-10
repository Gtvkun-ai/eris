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


class CoordinatorShutdownMixin:
    def stop(self):
        self.running = False
        worker = getattr(self, "screen_text_worker", None)
        if worker is not None:
            try:
                worker.stop()
            except Exception as exc:
                self.logger.warning("[screen text] stop error: %s", exc)
        # Dừng producer native trước, rồi mới dừng semantic consumer. Như vậy
        # shutdown không tạo thêm event sau khi worker đã ngừng nhận queue.
        native_broker = getattr(self, "native_environment_event_broker", None)
        if native_broker is not None:
            try:
                native_broker.stop()
            except Exception as exc:
                self.logger.debug("[deep environment] WinEvent stop error: %s", exc)
        for monitor in tuple(getattr(self, "native_environment_monitors", ()) or ()):
            try:
                monitor.stop()
            except Exception as exc:
                self.logger.debug("[deep environment] monitor stop error: %s", exc)
        semantic_worker = getattr(self, "semantic_environment_worker", None)
        if semantic_worker is not None:
            try:
                semantic_worker.stop()
            except Exception as exc:
                self.logger.debug("[deep environment] semantic worker stop error: %s", exc)
        self._stop_mental_process_loop()
        supervisor = getattr(self, "subsystem_supervisor", None)
        if supervisor is not None:
            supervisor.stop("runtime.tutor")
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
        if supervisor is not None:
            supervisor.shutdown_all()
        health_registry = getattr(self, "subsystem_health_registry", None)
        if health_registry is not None:
            health_registry.mark_stopped("runtime.coordinator")
        self.transport.close()
