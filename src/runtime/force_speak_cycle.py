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
from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.presence_controller import SocialPresenceEvent
from runtime.speech_pipeline import SpeechIntentDecision


class ForceSpeakCycleMixin:
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
        memory_resonance = self._recall_memory_resonance(
            snapshot=snapshot,
            channel="force_speak",
            fragments=(
                *tuple(vision_facts or ()),
                *self._thought_stream_resonance_fragments(),
            ),
        )
        memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
        internal_state_before = self._get_internal_state()
        ni_report = self.ni_engine.evaluate_autonomous(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            last_text=self.last_text,
            goal_state=getattr(internal_state_before, "goal_persistence", None),
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
        # V3 shadow + promotion trên path force_speak (observe-only khi ERIS_V3_PROMOTE
        # tắt; ghi đè frame cũ cho các path đã bật). Không bao giờ làm chết hot path.
        self._run_shadow_cognitive_pipeline(
            channel="force_speak",
            user_text="",
            snapshot=snapshot,
            vision_facts=tuple(vision_facts or ()),
            old_frame=frame,
        )
        memory_context = self._append_working_memory_context(memory_context, frame)
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
            self._send_decision_to_body(decision)
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
            if no_fallback_mode_enabled():
                local_fallback = ""
            # force_speak is an explicit user pull for presence; it must never fall
            # silent just because the ambient signal score is low. Always run the LLM
            # wording layer (force_llm=True triggers the require_non_empty retry) so a
            # low-signal click still produces a short line instead of an empty fallback.
            text, source = self._hybrid_micro_presence_text(
                kind=synthesis.kind,
                snapshot=snapshot,
                fallback_text=local_fallback,
                seeds=synthesis.seeds,
                micro_context=synthesis.context or {},
                force_llm=True,
                signal_score=max(signal_score, 0.62),
            )
            decision = Decision(
                text=text if synthesis.should_verbalize else "",
                animation=frame.action_plan.animation_hint or "stand",
                intent="micro_presence",
                reasoning_tags=("force_speak", "micro_presence", synthesis.kind),
                should_speak=bool(synthesis.should_verbalize and str(text or "").strip()),
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
            self._send_decision_to_body(decision)
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
            self._send_decision_to_body(decision)
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
        decision = self._maybe_escalate_directive_decision(
            decision,
            channel="force_speak",
            snapshot=snapshot,
            ti_report=ti_report,
            directive_kwargs={
                "telemetry_data": telemetry_data,
                "ni_context": "",
                "ti_context": forced_ti_context,
                "fe_context": fe_plan.style_context,
                "appraisal_context": self._build_appraisal_context(frame.appraisal),
                "internal_state_context": self._build_internal_state_context(sensed_internal_state, frame.self_state),
                "memory_context": memory_context,
                "avoid_text": self.last_text,
                "speech_intent": frame.action_plan.speech_intent,
                "vision_trace_marker": vision_marker,
            },
            vision_grounded=bool(getattr(self, "vision_facts", None)),
        )
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
        self._send_decision_to_body(decision)

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
