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

from guard_config import guards_warn_only

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
from runtime.ambient_silence_policy import (
    ambient_silence_cooldown_seconds,
    should_hold_ambient_silence,
)
from runtime.presence_controller import SocialPresenceEvent
from runtime.speech_pipeline import SpeechIntentDecision


VISION_TRACE_MARKER = "vision_facts_attached"


class AutonomousCycleMixin:
    def _choose_autonomous_sleep_duration(self, *, suppressed: bool, ti_mode: str) -> int:
        if suppressed:
            base = random.choice(self.autonomous_suppressed_sleep_seconds)
            silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0)
            # No-speech không reset nhịp. Càng im lâu, vòng sau càng quay lại sớm
            # để metabolism có cơ hội thắng, thay vì ngủ 60s rồi hỏi sao ERIS chết.
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
        return self.chat_mode or not self.running
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
        self.logger.info("[autonomous] bắt đầu chu kỳ nhận thức")
        self.idle_cycles += 1

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
        if self._process_pending_user_input():
            return self.running

        vision_marker = ""
        vision_facts = self._maybe_update_screen_facts()
        if self._process_pending_user_input():
            return self.running

        if vision_facts:
            vision_marker = self._attach_screen_facts(snapshot, vision_facts)
        telemetry_data = self._build_speech_evidence_context(snapshot)
        self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
        memory_resonance = self._recall_memory_resonance(
            snapshot=snapshot,
            channel="autonomous",
            fragments=(
                *tuple(vision_facts or ()),
                *self._thought_stream_resonance_fragments(),
            ),
        )
        memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
        # Nối đuôi hội thoại gần nhất (cùng bộ đệm với chat) để autonomous liền mạch.
        memory_context = self._merge_conversation_context(memory_context)
        internal_state_before = self._get_internal_state()
        ni_report = self.ni_engine.evaluate_autonomous(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            last_text=self.last_text,
            goal_state=getattr(internal_state_before, "goal_persistence", None),
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
        # V3 shadow + promotion trên path autonomous (observe-only khi ERIS_V3_PROMOTE
        # tắt; ghi đè frame cũ cho các path đã bật). Không bao giờ làm chết hot path.
        self._run_shadow_cognitive_pipeline(
            channel="autonomous",
            user_text="",
            snapshot=snapshot,
            vision_facts=tuple(vision_facts or ()),
            old_frame=frame,
        )
        memory_context = self._append_working_memory_context(memory_context, frame)
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
                if self._try_finalize_surface_arbiter_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    social_presence_event=social_presence_event,
                    cycle_start=cycle_start,
                    surface_kind="surface",
                ):
                    return True
            motion_decision = self._build_silent_motion_decision(ti_report)
            if motion_decision is not None:
                self._apply_position_update(motion_decision)
                frame.final_decision = self._decision_to_frame_dict(motion_decision)
                self._set_cognitive_memory_update(frame, decision=motion_decision, notes=("silent_motion",))
                self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
                self._finalize_cognitive_frame(frame)
                self.logger.info(
                    "[motion_only] intent=%s | target=%.2f | facing=%d | mode=%s",
                    motion_decision.motion_intent,
                    motion_decision.motion_target_x,
                    motion_decision.motion_facing,
                    ti_report.mode,
                )
                self._send_decision_to_body(motion_decision)
                elapsed = time.time() - cycle_start
                sleep_duration = self._choose_autonomous_sleep_duration(
                    suppressed=True,
                    ti_mode=ti_report.mode,
                )
                self.logger.info("Hoàn tất chu kỳ motion-only trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
                self._sleep_interruptible(sleep_duration)
                return True
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
                "Hoàn tất chu kỳ no-speech trong %.2fs. Nghỉ %ss để giữ nhịp sống.",
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
                if self._try_finalize_surface_arbiter_cycle(
                    frame=frame,
                    snapshot=snapshot,
                    ti_report=ti_report,
                    fe_plan=fe_plan,
                    social_presence_event=social_presence_event,
                    cycle_start=cycle_start,
                    surface_kind="surface",
                ):
                    return True
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
            cooldown = self._ambient_silence_cooldown_seconds(snapshot, ti_report)
            if self._maybe_emit_ambient_body_only(
                frame=frame,
                snapshot=snapshot,
                ti_report=ti_report,
                fe_plan=fe_plan,
                speech_intent=speech_intent.intent,
                cooldown=cooldown,
                cycle_start=cycle_start,
            ):
                return True
            elapsed = time.time() - cycle_start
            sleep_duration = self._choose_autonomous_sleep_duration(
                suppressed=True,
                ti_mode=ti_report.mode,
            )
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
            if self._process_pending_user_input():
                return self.running

            inner_ti_context = self._merge_v3_prompt_context(
                self._build_speech_core_ti_context(ti_report, frame.action_plan, speech_core.inner_thought, speech_core),
                frame,
            )
            raw = self.llm_service.generate_directive(
                telemetry_data=telemetry_data,
                ni_context="",
                ti_context=inner_ti_context,
                fe_context=fe_plan.style_context,
                appraisal_context=self._build_appraisal_context(frame.appraisal, frame=frame),
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
            decision = self._execute_system_action(decision, snapshot=snapshot, frame=frame)
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
            self._send_decision_to_body(decision)

            elapsed = time.time() - cycle_start
            sleep_duration = self._choose_autonomous_sleep_duration(
                suppressed=False,
                ti_mode=ti_report.mode,
            )
            self.logger.info("Hoàn tất chu kỳ trong %.2fs. Ngủ %ss.", elapsed, sleep_duration)
            self._sleep_interruptible(sleep_duration)
            return True

        planned_ti_context = self._merge_v3_prompt_context(
            self._build_llm_ti_context(ti_report, frame.action_plan),
            frame,
        )
        if self._process_pending_user_input():
            return self.running

        directive_kwargs = {
            "telemetry_data": telemetry_data,
            "ni_context": "",
            "ti_context": planned_ti_context,
            "fe_context": fe_plan.style_context,
            "appraisal_context": self._build_appraisal_context(frame.appraisal, frame=frame),
            "internal_state_context": self._build_internal_state_context(sensed_internal_state, frame.self_state),
            "memory_context": memory_context,
            "avoid_text": self.last_text,
            "speech_intent": frame.action_plan.speech_intent,
            "vision_trace_marker": vision_marker,
        }
        raw = self.llm_service.generate_directive(**directive_kwargs)
        self._log_raw_llm_output("directive", raw)
        self._log_pre_parser("directive", raw)
        decision = self.parser.parse(raw)
        self._log_decision_stage("directive", "after_parser", decision)
        self._log_decision_stage("directive", "pre_ti", decision)
        decision = self.ti_governor.enforce_decision(decision, ti_report, vision_grounded=bool(getattr(self, "vision_facts", None)))
        self._log_decision_stage("directive", "after_ti", decision)
        decision = self._execute_system_action(decision, snapshot=snapshot, frame=frame)

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
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=ti_report.mode,
        )
        self.logger.info("Hoàn tất chu kỳ trong %.2fs. Ngủ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)

        return True

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
    def _maybe_update_screen_facts(self) -> tuple[str, ...]:
        """Cập nhật ambient screen facts từ Screen Text Index trước.

        Autonomous không còn chụp ảnh + gọi VLM theo lịch mặc định. UIA/OCR worker
        đã chạy nền và rẻ hơn nhiều cho laptop chủ yếu code/log/chữ. Vision chỉ còn
        là escalation opt-in qua ERIS_AUTONOMOUS_VISION_ESCALATION=1.
        """
        if not self.vision_facts_enabled:
            self.vision_facts_novelty_hint = "none"
            return ()

        now = time.time()
        store = getattr(self, "screen_evidence_store", None)
        text_facts: tuple[str, ...] = ()
        if store is not None:
            try:
                text_facts = tuple(store.ambient_facts(
                    max_age_seconds=float(os.getenv("ERIS_SCREEN_TEXT_AMBIENT_MAX_AGE_SEC", "8") or 8.0),
                    max_items=self.vision_fact_max_items,
                ))
            except Exception as exc:
                self.logger.debug("[screen text autonomous] query lỗi: %s", exc)

        if text_facts:
            cleaned = self._sanitize_screen_facts(text_facts)
            signature = "\n".join(cleaned)
            self.vision_facts_novelty_hint = (
                "new_screen_text"
                if cleaned and signature != self.vision_facts_signature
                else ("repeated_screen_text" if cleaned else "none")
            )
            self.vision_facts_signature = signature
            self.vision_facts = cleaned
            self.vision_facts_are_stale = False
            self.vision_last_capture_at = now
            self.vision_last_trace = "screen_text_index"
            return self.vision_facts

        allow_vision = os.getenv("ERIS_AUTONOMOUS_VISION_ESCALATION", "0").strip().lower() in {"1", "true", "yes", "on"}
        if not allow_vision:
            # Không có text tươi thì im, không thuê VLM đi đọc terminal.
            if self.vision_last_capture_at and (now - self.vision_last_capture_at) > max(8.0, self.vision_interval_sec):
                self.vision_stale_facts = tuple(self.vision_facts)
                self.vision_facts = ()
                self.vision_facts_are_stale = True
                self.vision_facts_signature = ""
            self.vision_facts_novelty_hint = "none"
            return self.vision_facts

        # Escalation cũ chỉ chạy khi chủ động bật.
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
        self.vision_facts_novelty_hint = "new_screen_fact" if cleaned and signature != self.vision_facts_signature else ("repeated_screen_fact" if cleaned else "none")
        self.vision_facts_signature = signature
        self.vision_facts = cleaned
        self.vision_last_trace = trace or ""
        return self.vision_facts

    def _attach_screen_facts(self, snapshot, facts: tuple[str, ...]) -> str:
        if not facts:
            return ""
        snapshot.vision_facts = tuple(facts)
        return VISION_TRACE_MARKER
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
        quiet_modes = QUIET_MODES
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
            if item.label in concrete_labels and item.score >= self.attention_broadcast_threshold
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
                        reason="AttentionSalience did not broadcast a screen winner.",
                    )
                return SpeechIntentDecision(
                    intent="screen_observation",
                    reason=(
                        "AttentionSalience broadcast screen winner: "
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

        quiet_modes = QUIET_MODES | {"pattern_muse"}
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
        return ambient_silence_cooldown_seconds(snapshot, ti_report)
    def _should_hold_ambient_silence(
        self,
        *,
        snapshot,
        ti_report,
        speech_intent: str = "",
        now: float | None = None,
    ) -> bool:
        held, reason = should_hold_ambient_silence(
            snapshot=snapshot,
            ti_report=ti_report,
            last_text=self.last_text,
            last_autonomous_spoken_at=self.last_autonomous_spoken_at,
            speech_intent=speech_intent,
            now=now,
        )
        # Stash the structured reason for the per-cycle DecisionRecord.
        self._last_ambient_suppression_reason = reason if held else ""
        return held
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
        # warn-only: thôi bỏ phát ngôn autonomous "yếu" — để eris được nói cả khi
        # tín hiệu mỏng (guard quality chỉ cảnh báo, không chặn).
        if guards_warn_only():
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
