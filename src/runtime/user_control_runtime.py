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
from cortex.epistemic import EpistemicAgentMindProjection, EpistemicKernel, EpistemicKernelConfig, EpistemicStore, archive_v1_cognition, set_default_kernel
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


class UserControlRuntimeMixin:
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

    def _looks_like_screen_vision_request(
        self,
        user_text: str,
        *,
        previous_assistant_text: str = "",
    ) -> bool:
        """Dùng duy nhất smart vision gate của ChatCycleMixin.

        Bản cũ ở coordinator coi mọi lượt chat là lý do chụp màn hình và vô tình
        đè method mới trong mixin. Delegate tường minh để MRO không thể hồi sinh
        logic cũ trong một lần merge sau này.
        """

        return ChatCycleMixin._looks_like_screen_vision_request(
            self,
            user_text,
            previous_assistant_text=previous_assistant_text,
        )

    def _capture_screen_frame_for_chat(self, user_text: str, *, previous_public_turn=None) -> str:
        return ChatCycleMixin._capture_screen_frame_for_chat(
            self,
            user_text,
            previous_public_turn=previous_public_turn,
        )

    def _build_user_message_signature(self, user_text: str) -> str:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return ""

        # Repetition identity is textual only. A regex action router must not
        # reinterpret the user's meaning before the model-owned semantic planner.
        return normalized

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
        """Route force-speak qua autonomous orchestrator bằng cờ force, kích hoạt lượt bình thường ngay lập tức."""
        if not bool(getattr(self, "ai_runtime_enabled", False)):
            self.logger.error("[architecture C] force_speak unavailable: runtime bootstrap failed")
            return
        setattr(self, "_autonomous_force_speak_pending", True)
        setattr(self, "autonomous_presence_blocked_until", 0.0)
        wake = getattr(self, "_wake_autonomous_loop", None)
        if callable(wake):
            wake(reason="force_speak_command")

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

        if event.type in {"vad_start", "partial_asr", "final_asr", "laugh", "backchannel"}:
            self._handle_voice_observation_event(event)
            return

        if event.type == "avatar_ready":
            self.avatar_ready = True
            self._emit_stage_protocol_state("avatar_ready_ack", data=event.to_meta())
            return

        if event.type == "audio_playback_aborted":
            self._handle_audio_playback_aborted(event)
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
                    social_continuation_runtime = getattr(self, "ai_social_continuation_runtime", None)
                    if social_continuation_runtime is not None:
                        try:
                            social_continuation_runtime.notify_audio_finished(
                                timestamp,
                                source_turn_id=str(getattr(event, "turn_id", "") or ""),
                            )
                        except Exception as exc:
                            logger = getattr(self, "logger", None)
                            if logger is not None:
                                logger.debug("[social continuation] audio anchor failed: %s", exc)
                    conversation_arc_runtime = getattr(self, "ai_conversation_arc_runtime", None)
                    if conversation_arc_runtime is not None:
                        try:
                            conversation_arc_runtime.notify_audio_finished(timestamp)
                        except Exception as exc:
                            logger = getattr(self, "logger", None)
                            if logger is not None:
                                logger.debug("[conversation arc] audio anchor failed: %s", exc)
            self._emit_stage_protocol_state(f"{event.type}_ack", data=event.to_meta())
            return

        if event.type == "stage_ack":
            self._emit_stage_protocol_state("stage_ack_received", data=event.to_meta())

    def _handle_voice_observation_event(self, event) -> None:
        """Route VAD/ASR/laughter/backchannel into continuation invalidation.

        These signals arrive before a normal chat turn exists. They therefore do
        not synthesize user messages; they only settle floor ownership and the
        reaction window. Final ASR continues through the ordinary inbound chat
        path, while this early edge prevents a stale afterbeat from escaping.
        """

        signal = str(getattr(event, "type", "") or "").strip().lower()
        text = str(getattr(event, "message", "") or "").strip()
        observed_at = float(getattr(event, "timestamp", time.time()) or time.time())
        speech_signal = signal in {"vad_start", "partial_asr", "final_asr"}
        if speech_signal:
            clock = getattr(self, "interaction_clock", None)
            if clock is not None:
                try:
                    clock.mark_interrupt(observed_at)
                except Exception:
                    pass
            try:
                self._ensure_voice_manager().interrupt_signal(reason=signal)
            except Exception as exc:
                self.logger.debug("[voice-event] playback interrupt failed: %s", exc)

        continuation = getattr(self, "ai_social_continuation_runtime", None)
        if continuation is not None:
            try:
                continuation.observe_user_signal(signal=signal, text=text, now=observed_at)
            except Exception as exc:
                self.logger.debug("[social continuation] voice signal failed: %s", exc)

        if speech_signal:
            arc = getattr(self, "ai_conversation_arc_runtime", None)
            if arc is not None:
                try:
                    arc.cancel_active(reason=f"user_{signal}", now=observed_at)
                except Exception as exc:
                    self.logger.debug("[conversation arc] voice signal cancel failed: %s", exc)

        try:
            from runtime.observability import GLOBAL_OBSERVABILITY
            GLOBAL_OBSERVABILITY.increment(
                "eris_voice_floor_signals_total",
                tags={"signal": signal},
                fields={"has_text": bool(text), "turn_id": str(getattr(event, "turn_id", "") or "")},
            )
        except Exception:
            pass
        self._emit_stage_protocol_state(f"{signal}_ack", data=event.to_meta())

    def _handle_audio_playback_aborted(self, event) -> None:
        aborted_at = float(getattr(event, "timestamp", time.time()) or time.time())
        reason = str(getattr(event, "reason", "") or "frontend_playback_aborted")
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            try:
                clock.mark_interrupt(aborted_at)
            except Exception:
                pass
        continuation = getattr(self, "ai_social_continuation_runtime", None)
        if continuation is not None:
            try:
                continuation.cancel_all(reason=reason, now=aborted_at)
            except Exception as exc:
                self.logger.debug("[social continuation] playback abort cancel failed: %s", exc)
        arc = getattr(self, "ai_conversation_arc_runtime", None)
        if arc is not None:
            try:
                arc.cancel_active(reason=reason, now=aborted_at)
            except Exception as exc:
                self.logger.debug("[conversation arc] playback abort cancel failed: %s", exc)
        self._emit_stage_protocol_state("audio_playback_aborted_ack", reason=reason, data=event.to_meta())

    def _handle_stage_interrupt_event(self, event) -> None:
        clock = getattr(self, "interaction_clock", None)
        if clock is not None:
            clock.mark_interrupt(float(getattr(event, "timestamp", time.time()) or time.time()))
        text = str(getattr(event, "message", "") or "").strip()
        interrupt_at = float(getattr(event, "timestamp", time.time()) or time.time())
        social_continuation_runtime = getattr(self, "ai_social_continuation_runtime", None)
        if social_continuation_runtime is not None:
            try:
                social_continuation_runtime.observe_user_signal(
                    signal="interrupt" if text else "vad_start",
                    text=text,
                    now=interrupt_at,
                )
            except Exception as exc:
                self.logger.debug("[social continuation] interrupt cancel failed: %s", exc)
        if text:
            self._capture_speech_interrupt_for_user(text, timestamp=float(getattr(event, "timestamp", time.time()) or time.time()))
        else:
            # Voice-start interrupt: chưa có STT text, nhưng sân khấu phải dừng
            # ngay để Eris không đọc đè lên người dùng. Setup chưa phát trọn thì
            # callback sau đó cũng mất nghĩa, nên hủy arc thay vì để punchline mồ côi.
            conversation_arc_runtime = getattr(self, "ai_conversation_arc_runtime", None)
            if conversation_arc_runtime is not None:
                try:
                    conversation_arc_runtime.cancel_active(
                        reason="setup_audio_interrupted",
                        now=float(getattr(event, "timestamp", time.time()) or time.time()),
                    )
                except Exception as exc:
                    self.logger.debug("[conversation arc] interrupt cancel failed: %s", exc)
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

    def _handle_identity_control(self, msg: dict) -> None:
        """Typed administration surface for the Identity panel.

        This replaces the old habit of routing normal panel buttons through the
        free-form debug console.  The Emotion panel may keep its debug terminal,
        but Identity controls now have a small, explicit protocol and an ACK.
        """
        action = str(msg.get("action") or "").strip().lower()
        request_id = str(msg.get("request_id") or "")[:120]
        ok = True
        result = ""
        data: dict[str, object] = {}
        try:
            reducer = getattr(self, "ai_state_reducer", None)
            if action == "set_learning":
                if reducer is None:
                    raise RuntimeError("identity reducer chưa sẵn sàng")
                from runtime.ai_orchestrated.contracts import StateEvent

                enabled = bool(msg.get("enabled", True))
                snapshot = reducer.snapshot()
                event = StateEvent(
                    kind="admin_control",
                    turn_seq=snapshot.last_applied_turn_seq,
                    turn_id=f"identity-control-learning-{int(time.time() * 1000)}",
                    payload={"action": "set_learning", "enabled": enabled},
                    base_version=snapshot.version,
                    source="identity_panel",
                )
                reducer.apply_now(event)
                result = "learning=normal" if enabled else "learning=observe_only"
                data = {"enabled": enabled}
            elif action == "snapshot":
                if reducer is None:
                    raise RuntimeError("identity reducer chưa sẵn sàng")
                consolidator = getattr(self, "ai_identity_consolidator", None)
                if consolidator is None:
                    raise RuntimeError("identity consolidator chưa sẵn sàng")
                write_result = consolidator.write(reducer.snapshot(), reason="identity_panel")
                ok = bool(write_result.get("ok"))
                result = str(write_result.get("path") or write_result.get("error") or "snapshot failed")
                data = {"path": str(write_result.get("path") or "")}
            elif action == "reset_discovery":
                runtime = getattr(self, "ai_discovery_runtime", None)
                if runtime is None:
                    raise RuntimeError("discovery runtime chưa sẵn sàng")
                runtime.reset()
                result = "discovery archive đã reset"
            elif action in {"reset_mood", "reset_relationship"}:
                if reducer is None:
                    raise RuntimeError("identity reducer chưa sẵn sàng")
                from runtime.ai_orchestrated.contracts import StateEvent

                snapshot = reducer.snapshot()
                event = StateEvent(
                    kind="admin_control",
                    turn_seq=snapshot.last_applied_turn_seq,
                    turn_id=f"identity-control-{action}-{int(time.time() * 1000)}",
                    payload={"action": action},
                    base_version=snapshot.version,
                    source="identity_panel",
                )
                reducer.apply_now(event)
                result = action
            else:
                raise ValueError(f"identity_control action không hợp lệ: {action or '(rỗng)'}")
        except Exception as exc:
            ok = False
            result = str(exc)
            self.logger.warning("[identity_control] action=%s failed: %s", action, exc)

        try:
            self.transport.send_json(
                {
                    "type": "identity_control_ack",
                    "parse_mode": "identity_control_ack",
                    "should_speak": False,
                    "identity_control_ack": {
                        "request_id": request_id,
                        "action": action,
                        "ok": ok,
                        "result": str(result or "")[:500],
                        "data": data,
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - ACK không được làm rơi runtime
            self.logger.debug("[identity_control] không gửi được ack: %s", exc)

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
        supplements for expression, semantic-frame reading, flags, and a tiny affect history.
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

            semantic_frame = dict(getattr(self, "last_semantic_frame", {}) or {})
            if semantic_frame:
                cognitive_read = (
                    f"act={semantic_frame.get('user_act', 'unknown')}; "
                    f"relation={semantic_frame.get('discourse_relation', 'unknown')}; "
                    f"target={semantic_frame.get('target', 'unknown')}; "
                    f"owner={semantic_frame.get('ambiguity_owner', 'unknown')}"
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
