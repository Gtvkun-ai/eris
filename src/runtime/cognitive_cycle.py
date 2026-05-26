from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass, replace

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
from cortex.internal_state import PersistentInternalState
from cortex.relationship_dynamics import RelationshipTurnEvent
from core.evidence import EvidenceItem, RawSignal
from cortex.modes import QUIET_MODES
from cortex.ni import NiStateMachine
from domain import Decision
from runtime.body_bias import BodyBiasProjector
from runtime.presence_controller import SocialPresenceEvent
from runtime.speech_pipeline import SpeechIntentDecision


class CognitiveCycleMixin:
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
        # Chỉ evolve từ snapshot state đã đọc. Ghi lại vẫn qua _set_internal_state dưới lock.
        # Nếu sau này state có version field, nên compare-and-swap để tránh overwrite chat commit.
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


    def run_loop(self):
        self.logger.info("--- Overseer telemetry mode; chat vision bật theo yêu cầu màn hình ---")
        self._start_mental_process_loop()
        self.cognitive_substrate.start()
        if self.memory_state is not None:
            self.logger.info("[session_ritual] startup restore begin")
            try:
                report = self._restore_session_ritual_once()
                if report.should_greet:
                    self.logger.info("[session_ritual] sent greeting")
                else:
                    self.logger.info("[session_ritual] startup restore finished without greeting")
            except Exception:
                log_exception = getattr(self.logger, "exception", None)
                if callable(log_exception):
                    log_exception("[session_ritual] failed; continuing")
                else:
                    self.logger.warning("[session_ritual] failed; continuing. %s", traceback.format_exc().strip())
                try:
                    self._send_session_ritual_fallback_greeting()
                    self.logger.info("[session_ritual] sent fallback greeting")
                except Exception:
                    log_exception = getattr(self.logger, "exception", None)
                    if callable(log_exception):
                        log_exception("[session_ritual] fallback greeting failed")
                    else:
                        self.logger.warning("[session_ritual] fallback greeting failed. %s", traceback.format_exc().strip())
        else:
            self.logger.info("[session_ritual] skipped: memory_state unavailable")
        self.logger.info("[autonomous] entering main loop")
        while self.running:
            try:
                should_continue = self._run_loop_iteration()
                if not should_continue:
                    break
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                formatted = traceback.format_exc()
                formatted_single = " | ".join(
                    line.strip() for line in formatted.strip().splitlines() if line.strip()
                )
                log_error = getattr(self.logger, "error", None)
                if callable(log_error):
                    log_error("Unhandled exception inside run_loop; continuing. %s", formatted_single)
                else:
                    self.logger.warning("Unhandled exception inside run_loop; continuing. %s", formatted_single)
                try:
                    traceback.print_exc()
                except Exception:
                    pass
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
