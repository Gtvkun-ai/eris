from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from dataclasses import replace

from cortex.ni import NiStateMachine
from cortex.conversation_dynamics import ConversationFailure
from cortex.relationship_dynamics import RelationshipTurnEvent
from cortex.relational_feedback import RelationalFeedbackAnalyzer, merge_affect_with_relational_feedback
from cortex.turn_semantics import TurnSemanticsEngine, TurnSemanticsReport
from domain import Decision
from failure_meta import build_failure_meta
from llm import FormatViolationException
from runtime.no_fallback_policy import build_no_fallback_payload, no_fallback_mode_enabled
from runtime.source_grounding import SourceGroundingEngine
from runtime.controlled_slippage import (
    apply_slippage_to_personality_lens,
    apply_slippage_to_ti_report,
    derive_repair_suppression,
    resolve_controlled_slippage,
)


# Khi ERIS không sinh được phản hồi đủ chắc, nó vẫn phải nói như ERIS, không
# như một tờ báo lỗi. Không lộ "lỗi định dạng" / parse_mode ra ngoài (đúng với
# Data bans trong RUNTIME_RULES_PROMPT). Trung thực ở chỗ thừa nhận chưa đủ chắc
# để trả lời, nhưng giữ giọng và xoay câu để không thành canned response.
_FORMAT_REPAIR_FALLBACK_LINES = (
    "Tôi chưa chốt được câu trả lời cho cái này, và tôi không muốn nói bừa. Ngài nói lại ý chính giúp tôi một chút.",
    "Cái này tôi chưa nắm đủ chắc để trả cho gọn. Để khỏi đoán mò, Ngài thử hỏi lại theo hướng khác xem.",
    "Tôi đang hơi kẹt ở câu này, chưa đủ dữ liệu để trả lời cho an toàn. Tôi dừng ở đây thay vì bịa cho có.",
    "Tôi không muốn đưa Ngài một câu nửa vời. Cho tôi thêm một góc nữa rồi tôi trả lại cho tử tế.",
)


class ChatCycleMixin:
    def _enter_chat_cycle(self) -> None:
        self._chat_last_activity_at = time.time()
        if not self.chat_mode:
            self.chat_mode = True
            self.chat_ni_state = NiStateMachine()
            self.repeated_user_count = 0
            self.last_user_signature = ""
            self.last_user_text_for_semantics = ""
            self.logger.info("Entered chat mode; autonomous is paused for user messages.")

    def _end_chat_cycle(self) -> None:
        # Hội thoại là một dòng liên tục: KHÔNG xoá chat_history khi rời chat.
        # Bộ đệm tự phai theo TTL (ERIS_CONVERSATION_TTL_SEC) lúc render, nên
        # autonomous vẫn đọc được đuôi hội thoại gần nhất để nối mạch.
        self.chat_mode = False
        self.last_chat_answer = ""
        self.last_system_action = ""
        self.last_user_signature = ""
        self.last_user_text_for_semantics = ""
        self.last_user_intent = ""
        self.active_conversational_topic = ""
        self.repeated_user_count = 0
        self.chat_ni_state = NiStateMachine()
        self.fe_style_memory = self.fe_renderer.decay_memory(self.fe_style_memory)

        # Post-chat grace period: autonomous phải đợi trước khi được phép nói.
        # Tránh "chen ngang" ngay sau khi hội thoại kết thúc — cảm giác đang nói
        # chuyện xong mà Eris đã bắt đầu lẩm bẩm ngay, rất kỳ.
        # Mặc định 45s — đủ dài để user "nghỉ" sau chat, ngắn hơn reengagement_cooldown.
        block_fn = getattr(self, "_block_autonomous_presence_after_public_turn", None)
        if callable(block_fn):
            try:
                raw_grace = str(os.environ.get("ERIS_POST_CHAT_GRACE_SEC", "45") or "45").strip()
                grace = max(15.0, float(raw_grace) if raw_grace else 45.0)
                now = time.time()
                # Dùng max với block hiện tại — nếu block đang cao hơn thì giữ.
                current_block = float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0)
                self.autonomous_presence_blocked_until = max(current_block, now + grace)
                self.logger.info(
                    "Exited chat mode; autonomous blocked for %.0fs (post-chat grace).",
                    grace,
                )
            except Exception:
                self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")
        else:
            self.logger.info("Exited chat mode; autonomous can resume (conversation buffer kept).")


    def _build_relational_voice_stance(
        self,
        user_text: str,
        *,
        frame,
        fe_plan,
        ti_report,
        conversation_report,
        relationship_report,
    ):
        """Project the already-computed cognition reports into a CognitionStance.

        Register is derived only from existing cheap signals (ti_report.mode +
        classify_chat_act + a local code heuristic) — no extra model call.
        """
        from runtime.relational_voice_seed_adapter import (
            CognitionStance,
            classify_chat_register,
            detect_relational_act,
        )

        try:
            from llm.service import classify_chat_act
            chat_act_name = classify_chat_act(user_text).value
        except Exception:
            chat_act_name = ""

        adapter = self._ensure_relational_voice_seed_adapter()
        scope = adapter.config.scope
        ti_mode = str(getattr(ti_report, "mode", "") or "")
        register = classify_chat_register(user_text, ti_mode=ti_mode, chat_act_name=chat_act_name)
        act = detect_relational_act(user_text)

        conv_state = getattr(conversation_report, "state", None)
        rel_state = getattr(relationship_report, "state", None)
        flags: tuple[str, ...] = ()
        flag_imperatives: tuple[str, ...] = ()
        conv_ctx = ""
        if conv_state is not None:
            flags = tuple(getattr(conv_state, "adaptation_flags", ()) or ())
            try:
                flag_imperatives = tuple(conv_state._flag_imperatives())
            except Exception:
                flag_imperatives = ()
            try:
                conv_ctx = conv_state.to_prompt_context()
            except Exception:
                conv_ctx = ""
        try:
            appraisal_ctx = self._build_appraisal_context(frame.appraisal, frame=frame)
        except Exception:
            appraisal_ctx = ""

        return CognitionStance(
            register=register,
            scope=scope,
            act=act,
            fe_tone=str(getattr(fe_plan, "tone_label", "") or ""),
            fe_intent=str(getattr(fe_plan, "intent_label", "") or ""),
            appraisal_context=appraisal_ctx,
            adaptation_flags=flags,
            flag_imperatives=flag_imperatives,
            preferred_distance=float(getattr(rel_state, "preferred_distance", 0.0) or 0.0),
            attachment_visibility=float(getattr(rel_state, "attachment_visibility", 0.0) or 0.0),
            trust=float(getattr(rel_state, "trust", 0.0) or 0.0),
            conversation_prompt_context=conv_ctx,
        )

    def _build_relational_voice_seed_decision(
        self,
        user_text: str,
        *,
        frame,
        fe_plan,
        ti_report,
        conversation_report,
        relationship_report,
    ):
        # An optional pre-LLM path must never break the chat cycle. Any failure
        # here falls through to the legacy generate_chat_reply path.
        try:
            from runtime.relational_voice_seed_adapter import should_use_voice_seed

            stance = self._build_relational_voice_stance(
                user_text,
                frame=frame,
                fe_plan=fe_plan,
                ti_report=ti_report,
                conversation_report=conversation_report,
                relationship_report=relationship_report,
            )
            if not should_use_voice_seed(stance.register, stance.scope, stance.act):
                return None
            return self._ensure_relational_voice_seed_adapter().try_answer(user_text, stance=stance)
        except Exception as exc:
            try:
                self.logger.warning("relational_voice_seed hook failed; using legacy path: %s", exc)
            except Exception:
                pass
            return None

    def _run_chat_cycle(self, user_text: str, *, user_timestamp: float | None = None) -> None:
        cycle_start = time.time() if user_timestamp is None else float(user_timestamp)
        if not user_text:
            return
        if getattr(self, "_chat_processing", False):
            self._queue_chat_burst_event(user_text, cycle_start)
            return

        self._chat_processing = True
        try:
            user_text = self._merge_rapid_chat_burst(user_text, first_timestamp=cycle_start)
            if not user_text:
                return
            # Stage runtime cần biết câu user hiện tại để nhận ra các yêu cầu
            # "diễn" như cười/nổi giận/dỗi. Không đưa field này vào LLM schema;
            # chỉ giữ tạm trong coordinator cho lượt output đang commit.
            self.current_stage_user_text = user_text
            previous_public_turn = self._link_previous_public_turn_for_chat(cycle_start)
            previous_public_context = self._previous_public_turn_context(previous_public_turn)
            return self._run_chat_cycle_inner(
                user_text,
                cycle_start=cycle_start,
                previous_public_context=previous_public_context,
                previous_public_turn=previous_public_turn,
            )
        finally:
            self.current_stage_user_text = ""
            self._chat_processing = False

    def _run_chat_cycle_inner(
        self,
        user_text: str,
        *,
        cycle_start: float,
        previous_public_context: str = "",
        previous_public_turn=None,
    ) -> None:
        if not self.chat_mode:
            self.chat_ni_state = NiStateMachine() # reset trạng thái Ni khi bắt đầu chat mới, để tránh mang theo drift state từ autonomous mode.

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )

        # Outcome của lượt trước chỉ thật sự biết khi user phản hồi ở lượt này.
        # Nếu chờ finalize ngay trong turn trước thì OutcomeObserver chỉ đang đoán trong chân không,
        # mà đoán trong chân không là thú vui nguy hiểm của chatbot.
        self._observe_previous_turn_feedback(user_text)
        user_turn = self._ensure_session_turn_ledger().record_user(
            user_text,
            timestamp=cycle_start,
            meta={"channel": "chat"},
        )

        # PRE-GROUNDING phải chạy TRƯỚC memory recall/resonance.
        # Lý do: với câu "xem đi", "đoạn đang mở", hoặc hỏi file cụ thể, memory chỉ được phép
        # làm procedural guard, không được trở thành evidence hiện tại. Nếu recall memory trước,
        # speech_core/attention/action_plan đã bị ký ức ám rồi mới dựng report, quá muộn.
        pre_grounding = self._build_chat_source_grounding_report(
            user_text=user_text,
            frame=None,
            snapshot=snapshot,
            memory_resonance=None,
            screen_image_data_uri="",
        )
        self.last_grounding_context = pre_grounding

        if pre_grounding is not None and not bool(getattr(pre_grounding, "memory_answer_allowed", True)):
            self.long_term_memory = []
            memory_resonance = None
            memory_context = self._filter_memory_context_for_grounding("")
            self.active_memory_resonance = None
            self.logger.info(
                "[source grounding] memory quarantine before recall | source=%s | preempt=%s | missing=%s",
                getattr(pre_grounding, "grounding_source", "unknown"),
                getattr(pre_grounding, "preempt_mode", "") or "none",
                ",".join(getattr(pre_grounding, "missing_evidence", ()) or ()) or "none",
            )
        else:
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._recall_memory_resonance(
                snapshot=snapshot,
                user_text=user_text,
                channel="chat",
                fragments=(
                    *(tuple(self._chat_history_for_llm(limit=2)) if self.chat_history else ()),
                    *self._thought_stream_resonance_fragments(),
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)

        internal_state_before = self._get_internal_state()
        ni_report = self.ni_engine.evaluate_chat(
            snapshot=snapshot,
            long_term_memory=self.long_term_memory,
            user_text=user_text,
            goal_state=getattr(internal_state_before, "goal_persistence", None),
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
        affect_signal = self.affect_semantics.analyze(
            user_text,
            ti_mode=str(getattr(ti_report, "mode", "") or ""),
            active_window_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            previous_assistant_text=self.last_chat_answer,
        )
        relational_analyzer = getattr(self, "relational_feedback_analyzer", None)
        if relational_analyzer is None:
            relational_analyzer = RelationalFeedbackAnalyzer()
            self.relational_feedback_analyzer = relational_analyzer
        relational_feedback = relational_analyzer.analyze(
            user_text,
            previous_assistant_text=self.last_chat_answer,
        )
        fe_affect_signal = merge_affect_with_relational_feedback(affect_signal, relational_feedback)
        fe_plan = self.fe_renderer.evaluate_chat(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=self.fe_style_memory,
            internal_state=internal_state_before,
            user_text=user_text,
            affect_signal=fe_affect_signal,
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
            affect_signal=affect_signal,
        )
        # V3 CognitivePipeline chạy shadow trên CÙNG input (observe-only, env-gated
        # ERIS_SHADOW_PIPELINE). Không đổi quyết định của frame cũ, không ném ra hot
        # path. Đây là bước tích lũy bằng chứng focus/budget trước khi chuyển tải V3
        # thành xương sống cho path chat.
        self._run_shadow_cognitive_pipeline(
            channel="chat",
            user_text=user_text,
            snapshot=snapshot,
            vision_facts=tuple(getattr(snapshot, "vision_facts", ()) or ()),
            old_frame=frame,
        )
        memory_turn_id = f"session_turn:{user_turn.index}"
        # Ném bản phân rã sâu qua background worker. Hot path vẫn commit rule/fact rõ
        # bằng policy rẻ, còn model semantic parser được dùng khi remote API đang pending.
        self._enqueue_background_memory_digest(
            user_text,
            turn_id=memory_turn_id,
            source="chat_turn",
            priority="normal",
            context={
                "channel": "chat",
                "active_topic": str(self.active_conversational_topic or ""),
                "ti_mode": str(getattr(ti_report, "mode", "") or ""),
                "fe_intent": str(getattr(fe_plan, "intent_label", "") or ""),
            },
        )
        self._add_user_turn_memory_commit_requests(
            frame,
            user_text,
            turn_id=memory_turn_id,
        )

        self.chat_mode = True
        self._chat_last_activity_at = time.time()
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
        # Curiosity Tutor: nếu Eris không hiểu/không phân loại nổi tin user → đi hỏi Gemini
        # (chạy nền, không chặn trả lời). Chỉ chạy khi Master_Switch bật.
        self._maybe_tutor_on_unclear_user(user_text, frame)
        repeat_count = self._track_repeated_user_message(user_text)
        previous_user_text_for_semantics = getattr(self, "last_user_text_for_semantics", "")
        correction_detected = self._user_denies_last_assistant_assumption(user_text)
        conversation_report = self.conversation_dynamics_engine.evaluate_chat(
            getattr(sensed_internal_state, "conversation_dynamics", None),
            user_text=user_text,
            last_assistant_text=self.last_chat_answer,
            last_user_intent=self.last_user_intent,
            active_topic=self.active_conversational_topic,
            repeat_count=repeat_count,
            correction_detected=correction_detected,
            affect_signal=affect_signal,
            relational_feedback=relational_feedback,
        )
        relationship_event = self.relationship_dynamics_engine.infer_event(
            user_text=user_text,
            ti_mode=str(getattr(ti_report, "mode", "") or ""),
            active_window_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            turn_index=max(1, int(getattr(sensed_internal_state, "chat_ticks", 0) or 0) + 1),
            assistant_overread=bool(conversation_report.correction_detected),
            previous_assistant_text=self.last_chat_answer,
            goal_state=getattr(sensed_internal_state, "goal_persistence", None),
            conversation_state=getattr(sensed_internal_state, "conversation_dynamics", None),
            recent_user_topics=tuple(getattr(self._ensure_session_turn_ledger(), "gist_recent_user_topics", lambda: tuple())() or ()),
            explicit_repeated_project_context=0.58 if self.active_conversational_topic in {"technical_support", "goal_guard"} else None,
            relational_feedback=relational_feedback,
        )
        epistemic_kernel = getattr(self, "epistemic_kernel", None)
        if epistemic_kernel is not None and getattr(epistemic_kernel, "authoritative", False):
            from .epistemic_bridge import update_relationship_projection
            relationship_report = update_relationship_projection(
                epistemic_kernel,
                self.relationship_dynamics_engine,
                relationship_event,
                fallback_state=getattr(sensed_internal_state, "relationship_dynamics", None),
            )
        else:
            relationship_report = self.relationship_dynamics_engine.update(
                getattr(sensed_internal_state, "relationship_dynamics", None),
                relationship_event,
            )
        sensed_internal_state = replace(
            sensed_internal_state,
            conversation_dynamics=conversation_report.state,
            relationship_dynamics=relationship_report.state,
        )
        frame.internal_state_after = sensed_internal_state
        self.logger.info(
            "[conversation dynamics] mode=%s | tension=%.2f | pressure=%.2f | flags=%s",
            conversation_report.state.mode,
            conversation_report.state.semantic_tension,
            conversation_report.state.conversation_pressure,
            ",".join(conversation_report.state.adaptation_flags) or "none",
        )
        self.logger.info(
            "[relationship dynamics] event=%s | trust=%.2f | familiarity=%.2f | attachment_vis=%.2f | rupture=%.2f | distance=%.2f | notes=%s",
            relationship_report.state.last_event,
            relationship_report.state.trust,
            relationship_report.state.familiarity,
            relationship_report.state.attachment_visibility,
            relationship_report.state.rupture,
            relationship_report.state.preferred_distance,
            ",".join(relationship_report.notes) or "none",
        )

        # ControlledSlippage: mở quyền "liều" trong vùng quan hệ mà không tắt truth guard.
        # Ở đây chưa có SourceGrounding cuối cùng, nên đây là profile sớm để lens/Fe/Ti
        # bớt bóp giọng ngay từ planning. Sau khi có grounding + speech_core, profile sẽ được
        # resolve lại một lần nữa để LLM prompt biết rõ thiếu evidence nào.
        repair_suppression = self._recall_repair_suppression(user_text)
        slippage_profile = resolve_controlled_slippage(
            user_text=user_text,
            channel="chat",
            ti_report=ti_report,
            affect_signal=affect_signal,
            conversation_state=conversation_report.state,
            relationship_state=relationship_report.state,
            internal_state=sensed_internal_state,
            repair_suppression=repair_suppression,
        )
        ti_report = apply_slippage_to_ti_report(ti_report, slippage_profile)
        frame.personality_lens = apply_slippage_to_personality_lens(frame.personality_lens, slippage_profile)
        frame.controlled_slippage_profile = slippage_profile
        frame.debug_notes.append(f"controlled_slippage={slippage_profile.mode}:{slippage_profile.lane}")
        fe_plan = self._apply_personality_lens_to_fe_plan(fe_plan, frame.personality_lens)
        self.logger.info(
            "[controlled slippage] mode=%s | lane=%s | intuition=%.2f | misread=%.2f | notes=%s",
            slippage_profile.mode,
            slippage_profile.lane,
            slippage_profile.intuition_allowance,
            slippage_profile.misread_budget,
            ",".join(slippage_profile.notes) or "none",
        )
        # Repeat không được quyết bằng exact string một mình. Tầng này phân biệt:
        # spam rỗng, hỏi lại vì câu trước chưa đủ, correction/repair, live-evidence refresh,
        # và identity/relational probe. Nói cách khác: một câu giống nhau có thể có nghĩa khác
        # nếu nó xuất hiện sau một câu trả lời sai. Thật phiền, nhưng ngôn ngữ con người là vậy.
        turn_semantics_report = self._build_turn_semantics_report(
            user_text=user_text,
            repeat_count=repeat_count,
            previous_user_text=previous_user_text_for_semantics,
            affect_signal=affect_signal,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
            grounding_report=None,
        )
        self.last_turn_semantics_report = turn_semantics_report
        self.logger.info(
            "[turn semantics/pre-grounding] repeated=%s | count=%d | intent=%s | action=%s | spam=%.2f | identity=%.2f | correction=%.2f",
            turn_semantics_report.repeated,
            turn_semantics_report.repeat_count,
            turn_semantics_report.intent,
            turn_semantics_report.action,
            turn_semantics_report.spam_pressure,
            turn_semantics_report.identity_pressure,
            turn_semantics_report.correction_pressure,
        )
        self._maybe_invalidate_last_assistant_history(user_text)
        self._append_chat_history("user", user_text)
        self.logger.info("[CHAT HISTORY] %s", self._chat_history_for_llm(limit=8))
        self.logger.info("[LAST USER INTENT] %s", self.last_user_intent or "<empty>")
        self.logger.info("[ACTIVE_TOPIC] %s", self.active_conversational_topic or "<empty>")
        speech_core = self._build_speech_core(
            channel="chat",
            snapshot=snapshot,
            internal_state=sensed_internal_state,
            frame=frame,
            ti_report=ti_report,
            fe_plan=fe_plan,
            ni_report=ni_report,
            ni_state_label=ni_state_label,
            repeat_count=repeat_count,
            thought_surface=getattr(thought_stream_report, "latest_seed", None),
        )
        self._chat_snapshot_for_vision = snapshot
        try:
            screen_image_data_uri = self._capture_screen_frame_for_chat(user_text)
        finally:
            self._chat_snapshot_for_vision = None
        grounding_report = self._build_chat_source_grounding_report(
            user_text=user_text,
            frame=frame,
            snapshot=snapshot,
            memory_resonance=memory_resonance,
            screen_image_data_uri=screen_image_data_uri,
        )
        self.last_grounding_context = grounding_report
        if grounding_report is not None and not bool(getattr(grounding_report, "memory_answer_allowed", True)):
            memory_context = self._filter_memory_context_for_grounding(memory_context)
        self._log_chat_source_grounding(grounding_report)

        # Resolve lại ControlledSlippage sau khi đã biết grounding và speech_core.
        # Nếu thiếu screen/file/web evidence, profile vẫn cho phép cọ sát quan hệ, nhưng prompt
        # sẽ ghi rõ: không được biến sự liều đó thành claim về thế giới. Cái này là ranh giới
        # giữa "người hơn" và "bịa hơn".
        slippage_profile = resolve_controlled_slippage(
            user_text=user_text,
            channel="chat",
            ti_report=ti_report,
            affect_signal=affect_signal,
            conversation_state=conversation_report.state,
            relationship_state=relationship_report.state,
            internal_state=sensed_internal_state,
            grounding_report=grounding_report,
            speech_core=speech_core,
            repair_suppression=repair_suppression,
        )
        ti_report = apply_slippage_to_ti_report(ti_report, slippage_profile)
        frame.personality_lens = apply_slippage_to_personality_lens(frame.personality_lens, slippage_profile)
        frame.controlled_slippage_profile = slippage_profile
        frame.debug_notes.append(f"controlled_slippage_final={slippage_profile.mode}:{slippage_profile.lane}")
        fe_plan = self._apply_personality_lens_to_fe_plan(fe_plan, frame.personality_lens)

        # Sau khi có grounding thật, chạy lại turn semantics để live screen/file/code evidence
        # có quyền thắng exact-repeat. Nếu không, câu "xem lại đi" lặp lần 2 vẫn bị chặn
        # dù turn này vừa có screenshot mới. Một kiểu tự bắn vào mắt runtime khá cổ điển.
        turn_semantics_report = self._build_turn_semantics_report(
            user_text=user_text,
            repeat_count=repeat_count,
            previous_user_text=previous_user_text_for_semantics,
            affect_signal=affect_signal,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
            grounding_report=grounding_report,
        )
        self.last_turn_semantics_report = turn_semantics_report
        self.logger.info(
            "[turn semantics] repeated=%s | count=%d | intent=%s | action=%s | spam=%.2f | live=%.2f | prior_failure=%.2f",
            turn_semantics_report.repeated,
            turn_semantics_report.repeat_count,
            turn_semantics_report.intent,
            turn_semantics_report.action,
            turn_semantics_report.spam_pressure,
            turn_semantics_report.live_evidence_pressure,
            turn_semantics_report.prior_failure_pressure,
        )

        previous_public_repair = self._build_previous_public_turn_repair_decision(
            user_text=user_text,
            previous_public_turn=previous_public_turn,
            ti_report=ti_report,
            grounding_report=grounding_report,
            frame=frame,
            speech_core=speech_core,
        )
        if previous_public_repair is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act="repair",
                reason="User reacted to a broken previous public turn; repair before LLM chat.",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("previous_public_turn_repair",),
            )
            self._commit_chat_decision(previous_public_repair, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return

        direct_decision = self._build_direct_action_decision(user_text, ti_report, snapshot, repeat_count=repeat_count)
        if direct_decision is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act=speech_core.utterance_type if speech_core.should_speak else "system_action",
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
            self.last_user_text_for_semantics = user_text
            return

        grounding_preempt = self._build_grounding_preempt_decision(
            grounding_report,
            ti_report,
            user_text=user_text,
        )
        if grounding_preempt is not None:
            # Nếu SourceGrounding chuyển thiếu dữ kiện sang epistemic_curiosity,
            # action plan cũng phải mang shape probe/curious_question. Nếu vẫn đánh dấu
            # guarded_reply thì các guard sau lại hiểu đây là câu tự vệ chết khô.
            epistemic_mode = str(getattr(grounding_report, "epistemic_mode", "") or "")
            preempt_speech_act = "curious_question" if epistemic_mode in {"probe", "hypothesis"} else "guarded_reply"
            preempt_intent = "epistemic_probe" if epistemic_mode in {"probe", "hypothesis"} else "user_requested"
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent=preempt_intent,
                speech_act=preempt_speech_act,
                reason=f"Source grounding preempted chat turn ({grounding_report.preempt_mode}).",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("source_grounding_preempt", grounding_report.preempt_mode or "unknown", epistemic_mode or "unknown"),
            )
            self._commit_chat_decision(grounding_preempt, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return

        repeat_decision = self._build_repeat_guard_decision(
            user_text,
            ti_report,
            repeat_count,
            grounding_report=grounding_report,
            turn_semantics_report=turn_semantics_report,
        )
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
            self.last_user_text_for_semantics = user_text
            return

        memory_answer_profile = getattr(grounding_report, "memory_answer_profile", None)
        if getattr(memory_answer_profile, "active", False):
            planned_speech_intent = (
                str(getattr(memory_answer_profile, "speech_intent", "") or "")
                or self._speech_intent_from_core(speech_core, channel="chat")
            )
            planned_speech_act = (
                str(getattr(memory_answer_profile, "speech_act", "") or "")
                or (speech_core.utterance_type if speech_core.should_speak else "")
            )
            plan_notes = (
                "chat_reply",
                "semantic_answer_profile",
                f"memory_answer={getattr(memory_answer_profile, 'mode', 'unknown')}",
                f"memory_stance={getattr(memory_answer_profile, 'epistemic_stance', 'none')}",
            )
            plan_reason = (
                str(getattr(memory_answer_profile, "reason", "") or "")
                or speech_core.reason
                or ti_report.reason
            )
        else:
            planned_speech_intent = self._speech_intent_from_core(speech_core, channel="chat")
            planned_speech_act = speech_core.utterance_type if speech_core.should_speak else ""
            plan_notes = ("chat_reply",)
            plan_reason = speech_core.reason or ti_report.reason

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent=planned_speech_intent,
            speech_act=planned_speech_act,
            reason=plan_reason,
            snapshot=snapshot,
            user_text=user_text,
            concrete_signals=self._concrete_screen_signals(snapshot),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=plan_notes,
            inner_thought=speech_core.inner_thought,
        )
        chat_user_message = self.parser.build_chat_user_message(
            user_message=user_text,
            last_chat_answer=self.last_chat_answer,
        )
        turn_semantics_context = str(getattr(turn_semantics_report, "prompt_context", "") or "")
        planned_ti_context = (
            f"{ti_report.prompt_context}\n{self._build_action_plan_context(frame.action_plan)}\n{turn_semantics_context}"
        )
        if previous_public_context:
            planned_ti_context = f"{planned_ti_context}\n\n{previous_public_context}"
        # Curiosity Tutor: Eris không hiểu ý Ngài → câu trả lời lượt này thành câu hỏi
        # làm rõ (thay vì đoán bừa hay lén tra Gemini). Giữ giọng Eris.
        if getattr(self, "_clarify_user_pending", False):
            planned_ti_context = (
                f"{planned_ti_context}\n\nLÀM RÕ: Em chưa chắc hiểu ý Ngài vừa nói. "
                "Thay vì đoán hay bịa, hãy hỏi lại Ngài MỘT câu ngắn, tự nhiên, đúng giọng "
                "của em để làm rõ ý; đừng xin lỗi dài dòng."
            )
        # Nhịp 1 của tra cứu: Eris chưa biết câu kiến thức Ngài vừa hỏi → báo "đợi em tra
        # chút" rồi sẽ trả lời sau (nhịp 2 chạy ở thread nền). TUYỆT ĐỐI không đoán đáp án.
        if getattr(self, "_research_pending", False):
            planned_ti_context = (
                f"{planned_ti_context}\n\nĐANG TRA CỨU: Em chưa chắc câu trả lời cho câu Ngài "
                "vừa hỏi và KHÔNG được bịa. Hãy nói ngắn gọn, tự nhiên, đúng giọng em rằng em "
                "chưa chắc nên đang đi tra cứu và sẽ trả lời ngay khi xong. Đừng đưa ra bất kỳ "
                "đáp án phỏng đoán nào ở câu này."
            )
        # The current user message is sent as the final user message below.
        # Passing it inside chat_history as well wastes one short-term slot
        # and can push out the previous turn during context shrink.
        llm_chat_history = self._chat_history_for_llm(limit=16)[:-1]
        self.logger.info("[LLM CHAT HISTORY] %s", llm_chat_history[-8:])
        memory_recall_decision = self._build_memory_recall_decision(user_text)
        if memory_recall_decision is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act="answer",
                reason="Memory recall adapter answered before LLM chat.",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("memory_recall",),
            )
            memory_recall_decision = self._apply_chat_final_guards(
                memory_recall_decision,
                user_text=user_text,
                frame=frame,
            )
            self._commit_chat_decision(memory_recall_decision, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return
        relational_seed_decision = self._build_relational_voice_seed_decision(
            user_text,
            frame=frame,
            fe_plan=fe_plan,
            ti_report=ti_report,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
        )
        if relational_seed_decision is not None:
            self._set_cognitive_action_plan(
                frame,
                should_speak=True,
                speech_intent="user_requested",
                speech_act="answer",
                reason="Relational voice-seed path answered before LLM chat.",
                snapshot=snapshot,
                user_text=user_text,
                concrete_signals=self._concrete_screen_signals(snapshot),
                ti_report=ti_report,
                fe_plan=fe_plan,
                notes=("relational_voice_seed",),
            )
            relational_seed_decision = self._apply_chat_final_guards(
                relational_seed_decision,
                user_text=user_text,
                frame=frame,
            )
            self._commit_chat_decision(relational_seed_decision, fe_plan, frame=frame)
            self.last_user_text_for_semantics = user_text
            return
        difficulty = self._classify_query_difficulty(user_text)
        use_escalation = False
        reasoning_effort = None
        if difficulty != "none":
            use_escalation = True
            reasoning_effort = difficulty

        chat_generation_kwargs = {
            "chat_history": llm_chat_history,
            "user_message": chat_user_message,
            "raw_user_text": user_text,
            "ni_context": ni_report.prompt_context,
            "ti_context": planned_ti_context,
            "fe_context": fe_plan.style_context,
            "appraisal_context": self._build_appraisal_context(frame.appraisal, frame=frame),
            "internal_state_context": self._build_internal_state_context(
                sensed_internal_state, frame.self_state, user_text=user_text
            ),
            "conversation_context": f"{conversation_report.prompt_context}\n{relational_feedback.to_prompt_context()}",
            "memory_context": memory_context,
            "grounding_context": grounding_report.prompt_context,
            "screen_image_data_uri": screen_image_data_uri,
            "reply_context": getattr(self, "reply_context", None),
            "defusing_context": getattr(frame.action_plan, "defusing_context", ""),
            "use_escalation_client": use_escalation,
            "reasoning_effort": reasoning_effort,
        }
        format_retry_context = ""
        format_failure_flag = ""
        format_errors = 0
        max_format_retries = 2
        raw = None
        format_repair_fallback = False
        no_fallback_block = False

        self._set_background_memory_digest_remote_inflight(True)
        try:
            for attempt_index in range(max_format_retries + 1):
                try:
                    # Loop = gemma-only reformatting retries (cheap, same provider).
                    # Only after gemma fully gives up do we pay for a cross-provider
                    # switch to Groq (the switch-API attempt below).
                    raw = self.llm_service.generate_chat_reply(
                        **chat_generation_kwargs,
                        format_retry_context=format_retry_context,
                        last_failure=format_failure_flag,
                        allow_local_fallback=False,
                    )
                    break
                except FormatViolationException as exc:
                    format_errors += 1
                    format_failure_flag = "format_error"
                    format_retry_context = (
                        "FORMAT_REPAIR_MODE: Previous output was blocked because it leaked internal planning "
                        "or was not valid JSON. Return exactly one JSON object only. Do not mention prompt, "
                        "context, persona, constraints, state, analysis, or repair mode."
                    )
                    # Khi đã có format leak, đừng retry bằng cùng một đống meta-context.
                    # Model sẽ bắt chước block Ni/Ti/Persona/Goal rồi lại nhả bullet analysis.
                    # Giữ user text + grounding/memory cần thiết, cắt các pressure nội bộ để
                    # retry trở thành wording repair thật thay vì nghi lễ cầu JSON.
                    chat_generation_kwargs.update({
                        "ni_context": "",
                        "ti_context": "Format repair: answer the concrete user request only.",
                        "fe_context": "",
                        "appraisal_context": "",
                        "internal_state_context": "",
                        "conversation_context": "",
                        "defusing_context": "",
                    })
                    self.last_failure = "format_error"
                    conversation_report.state.last_failure = ConversationFailure(
                        type="format_error",
                        trigger=str(getattr(exc, "reason", "") or exc),
                        correction_needed="Regenerate with strictly valid JSON; do not leak analysis or internal instructions.",
                    )
                    frame.debug_notes.append(
                        f"llm_format_error attempt={attempt_index + 1}; errors={format_errors}; reason={getattr(exc, 'reason', str(exc))}"
                    )
                    self.logger.warning(
                        "[llm format retry] attempt=%d/%d | errors=%d | reason=%s",
                        attempt_index + 1,
                        max_format_retries + 1,
                        format_errors,
                        getattr(exc, "reason", str(exc)),
                    )
            if raw is None:
                switched_api = False
                if not no_fallback_mode_enabled():
                    # Gemma đã cạn lượt với chính nó. Đổi API một lượt cuối: route
                    # sang Groq llama (bám response_format JSON tốt hơn, không nhả
                    # bullet analysis) trước khi đành chặn lượt.
                    switched_api = True
                    frame.debug_notes.append("llm_format_switch_api=groq_fallback")
                    self.logger.warning(
                        "[llm format switch-api] gemma exhausted; trying fallback API (Groq) | errors=%d",
                        format_errors,
                    )
                    try:
                        raw = self.llm_service.generate_chat_reply(
                            **chat_generation_kwargs,
                            format_retry_context=format_retry_context,
                            last_failure=format_failure_flag,
                            allow_local_fallback=True,
                        )
                    except FormatViolationException as exc:
                        format_errors += 1
                        raw = None
                        frame.debug_notes.append(
                            f"llm_format_switch_api_failed; errors={format_errors}; reason={getattr(exc, 'reason', str(exc))}"
                        )
                        self.logger.warning(
                            "[llm format switch-api] fallback API also broke format | errors=%d | reason=%s",
                            format_errors,
                            getattr(exc, "reason", str(exc)),
                        )
                if raw is None:
                    # Cạn cả gemma lẫn API đổi (hoặc no-fallback mode): chặn lượt,
                    # không bịa câu trấn an.
                    no_fallback_block = True
                    frame.debug_notes.append(
                        f"llm_format_errors={format_errors}; switch_api={switched_api}; route=no_fallback_block"
                    )
                    self.logger.warning(
                        "[llm format block] all providers exhausted | errors=%d | switch_api=%s",
                        format_errors,
                        switched_api,
                    )
                    raw = self._build_chat_format_block_raw(
                        FormatViolationException(
                            "chat_format_contract_exhausted",
                            channel="chat",
                            raw_text="",
                        ),
                        switched_api=switched_api,
                    )
        finally:
            self._set_background_memory_digest_remote_inflight(False)
        self._log_raw_llm_output("chat", raw)
        self._log_pre_parser("chat", raw)
        decision = self.parser.parse(raw, user_hint=user_text)
        if format_repair_fallback:
            decision.intent = "format_repair_fallback"
            decision.action = "guarded_reply"
            decision.reasoning_tags = ("format_repair", "deterministic_fallback")
            decision.should_speak = True
            decision.confidence = 0.45
            decision.parse_mode = "format_repair_fallback"
            decision.failure_meta = build_failure_meta(
                kind="format_violation",
                stage="chat_cycle_format_recovery",
                origin="chat_cycle",
                public_surface="service_fallback",
                recoverable=True,
            )
            decision.debug_trace = self._join_debug_trace(
                decision.debug_trace,
                "format_violation_recovered",
            )
        if no_fallback_block:
            decision.intent = "no_fallback_block"
            decision.action = "none"
            decision.reasoning_tags = ("no_fallback_mode", "format_error")
            decision.should_speak = True
            decision.confidence = 0.0
            decision.parse_mode = "no_fallback_block"
            decision.failure_meta = build_failure_meta(
                kind="format_violation",
                stage="chat_cycle_format_block",
                origin="chat_cycle",
                public_surface="blocked",
                recoverable=False,
            )
        self._log_decision_stage("chat", "after_parser", decision)
        self._log_decision_stage("chat", "pre_ti", decision)
        decision = self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text, vision_grounded=bool(screen_image_data_uri) or bool(getattr(self, "vision_facts", None)))
        self._log_decision_stage("chat", "after_ti", decision)
        decision = self._maybe_escalate_chat_decision(
            decision,
            user_text=user_text,
            snapshot=snapshot,
            chat_generation_kwargs=chat_generation_kwargs,
            ti_report=ti_report,
        )
        self._log_decision_stage("chat", "after_escalation", decision)
        decision = self._execute_system_action(decision, snapshot=snapshot)
        decision = self._apply_chat_final_guards(decision, user_text=user_text, frame=frame)
        self._commit_chat_decision(decision, fe_plan, frame=frame)
        self.last_user_text_for_semantics = user_text
        return

    def _recall_repair_suppression(self, user_text: str):
        """Recall ký ức sửa lỗi quan hệ/tâm lý và rút ra tín hiệu siết cho lượt này.

        Đây là cạnh recall đóng vòng Outcome -> SelfObservation -> RepairMemory ->
        Future suppression: lỗi từng bị user sửa sẽ chủ động bóp lại chính hành vi
        đó. Hoàn toàn defensive — mọi lỗi đều bị nuốt và trả None, không bao giờ
        làm chết hot path chat.
        """
        try:
            store = getattr(self.memory_core, "repair", None)
            if store is None:
                core = getattr(self.memory_kernel, "core", None)
                store = getattr(core, "repair", None)
            recall = getattr(store, "recall", None)
            if not callable(recall):
                return None
            items = recall(user_text or "", limit=8)
            if not items:
                return None
            return derive_repair_suppression(items)
        except Exception as exc:  # pragma: no cover - recall không bao giờ giết turn
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("[repair suppression] recall lỗi (nuốt): %r", exc)
            return None

    def _build_chat_format_block_raw(self, exc: FormatViolationException, *, switched_api: bool = False) -> str:
        """Block payload when every provider (gemma retries + Groq switch-API)
        breaks the format contract. We refuse to fabricate a reassurance line and
        surface an honest block instead.
        """
        reason = str(getattr(exc, "reason", "") or exc)
        if no_fallback_mode_enabled():
            return build_no_fallback_payload(
                channel="chat",
                reason=reason,
                should_speak=True,
                confidence=0.0,
                reasoning_tags=("format_block",),
            )
        payload = {
            "text": (
                "Tôi chặn lượt này vì câu vừa rồi lệch khỏi đường nói sạch."
            ),
            "intent": "no_fallback_block",
            "action": "none",
            "reasoning_tags": [
                "format_block",
                "switch_api_exhausted" if switched_api else "format_error",
            ],
            "should_speak": True,
            "confidence": 0.0,
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": f"format_violation_blocked: {reason[:180]}",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
            "parse_mode": "no_fallback_block",
            "failure_meta": build_failure_meta(
                kind="format_violation",
                stage="chat_format_block",
                origin="chat_cycle",
                public_surface="blocked",
                recoverable=False,
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _build_chat_format_repair_fallback_raw(self, exc: FormatViolationException) -> str:
        reason = str(getattr(exc, "reason", "") or exc)
        if no_fallback_mode_enabled():
            return build_no_fallback_payload(
                channel="chat",
                reason=reason,
                should_speak=True,
                confidence=0.0,
                reasoning_tags=("format_block",),
            )
        payload = {
            "text": random.choice(_FORMAT_REPAIR_FALLBACK_LINES),
            "intent": "format_repair_fallback",
            "action": "guarded_reply",
            "animation": "stand",
            "reasoning_tags": ["format_repair", "deterministic_fallback"],
            "should_speak": True,
            "confidence": 0.45,
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": f"format_violation_recovered: {reason[:180]}",
            "next_animation": "stand",
            "system_action": "",
            "action_input": "",
            "parse_mode": "format_repair_fallback",
            "failure_meta": build_failure_meta(
                kind="format_violation",
                stage="chat_format_repair",
                origin="chat_cycle",
                public_surface="service_fallback",
                recoverable=True,
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _join_debug_trace(*parts: str) -> str:
        return " | ".join(str(part or "").strip() for part in parts if str(part or "").strip())

    def _queue_chat_burst_event(self, user_text: str, timestamp: float | None = None) -> None:
        text = str(user_text or "").strip()
        if not text:
            return
        lock = getattr(self, "_chat_burst_lock", None)
        if lock is None:
            self._chat_burst_queue = [(time.time() if timestamp is None else float(timestamp), text)]
            return
        with lock:
            self._chat_burst_queue.append((time.time() if timestamp is None else float(timestamp), text))

    def _merge_rapid_chat_burst(self, first_text: str, *, first_timestamp: float) -> str:
        collected: list[tuple[float, str]] = [(first_timestamp, str(first_text or "").strip())]
        collected.extend(self._pop_queued_chat_events())
        collected.extend(self._poll_ready_chat_events())
        if len(collected) <= 1:
            return collected[0][1]

        window = float(getattr(self, "rapid_burst_window", 1.2) or 0.0)
        quiet_until = time.time() + window
        while window > 0.0 and time.time() < quiet_until:
            time.sleep(0.05)
            new_events = self._pop_queued_chat_events()
            new_events.extend(self._poll_ready_chat_events())
            if new_events:
                collected.extend(new_events)
                quiet_until = time.time() + window

        collected.sort(key=lambda item: item[0])
        return "\n".join(text for _, text in collected if text)

    def _pop_queued_chat_events(self) -> list[tuple[float, str]]:
        lock = getattr(self, "_chat_burst_lock", None)
        if lock is None:
            return []
        with lock:
            queued = list(getattr(self, "_chat_burst_queue", []) or [])
            self._chat_burst_queue = []
        return [(float(ts), str(text or "").strip()) for ts, text in queued if str(text or "").strip()]

    def _poll_ready_chat_events(self) -> list[tuple[float, str]]:
        events: list[tuple[float, str]] = []
        poll = getattr(getattr(self, "transport", None), "poll_json", None)
        if not callable(poll):
            return events
        while True:
            msg = poll()
            if not msg:
                return events
            if msg.get("type") == "chat":
                text = str(msg.get("message", "") or "").strip()
                if text:
                    events.append((float(msg.get("timestamp") or time.time()), text))
                continue
            self._handle_incoming(msg)

    def _observe_previous_turn_feedback(self, user_text: str) -> None:
        """Gắn feedback của user hiện tại vào frame trước nếu có.

        OutcomeObserver trong PDF nằm sau Execution, nhưng các tín hiệu như "sai rồi",
        "đúng", "khó hiểu" thường xuất hiện ở turn kế tiếp. Hàm này cập nhật nhẹ
        `last_cognitive_frame.outcome` để SelfObservation/RepairMemory có dữ kiện thật hơn.
        Nó không commit trực tiếp; commit vẫn đi qua StateCommitter ở các frame sau.
        """
        # Báo SnubTracker biết user vừa phản hồi → có thể reset snub counter
        snub_tracker = getattr(self, "snub_tracker", None)
        if snub_tracker is not None:
            try:
                snub_tracker.on_user_responded(user_text)
            except Exception:
                pass

        previous = getattr(self, "last_cognitive_frame", None)
        if previous is None:
            return
        observer = getattr(self, "outcome_observer", None)
        if observer is None or not callable(getattr(observer, "observe", None)):
            return
        try:
            outcome = observer.observe(previous, user_feedback_text=user_text, attach_to_frame=True)
            kernel = getattr(self, "epistemic_kernel", None)
            episode = getattr(previous, "epistemic_episode", None)
            if kernel is not None and episode is not None:
                from .epistemic_bridge import feedback_from_outcome
                updates = kernel.close_episode(feedback_from_outcome(outcome), episode_id=str(getattr(episode, "id", "") or ""))
                if updates:
                    previous.debug_notes.append(f"epistemic_v2_learning={len(updates)}")
        except Exception as exc:
            self.logger.warning("Outcome feedback observation failed: %s", exc)

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
        tokens = lowered.split()
        while tokens and tokens[-1] in filler_suffixes:
            tokens.pop()
        return " ".join(tokens)

    def _normalize_marker_text(self, user_text: str) -> str:
        """Normalize để detect lệnh nhìn màn hình, KHÔNG strip hậu tố "đi".

        `_normalize_user_message()` dùng cho repeat signature nên nó bỏ các từ cuối như "đi".
        Nếu dùng nó cho screen command, "xem đi" thành "xem" và mọi câu "xem lại logic"
        cũng có thể bị hiểu là cần screenshot. Một bug nhỏ mà rất thích đốt token.
        """
        lowered = (user_text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        return " ".join(lowered.split())
    def _looks_like_screen_vision_request(self, user_text: str) -> bool:
        normalized = self._normalize_marker_text(user_text)
        if not normalized:
            return False

        # Chỉ các marker thật sự trỏ màn hình mới được capture screenshot.
        # Không dùng marker rộng như "web/chrome/browser" ở đây, vì "xem lại web logic"
        # không đồng nghĩa "hãy nhìn màn hình". Mắt runtime không nên bật vì keyword rẻ tiền.
        direct_terms = {
            self._normalize_marker_text(item)
            for item in (
                "màn hình",
                "trên màn hình",
                "screenshot",
                "screen",
                "nhìn màn hình",
                "xem màn hình",
                "look at this",
                "this screen",
                "xem đi",
                "bạn xem đi",
                "tôi đang code gì",
                "đang code gì",
                "đoạn đang mở",
                "file đang mở",
                "đang hiện gì",
                "lỗi này trên màn hình",
            )
        }
        if any(term and term in normalized for term in direct_terms):
            return True

        visual_verbs = {"nhin", "thay", "xem"}
        visual_objects = {"tren man hinh", "gi tren do", "dang hien", "doan dang mo", "file dang mo"}
        return any(term in normalized for term in visual_verbs) and any(
            term in normalized for term in visual_objects
        )
    def _capture_screen_frame_for_chat(self, user_text: str) -> str:
        # Smart gate: ưu tiên vision_facts đã có từ autonomous cycle.
        # Chỉ chụp màn hình mới khi:
        #   1. User hỏi trực tiếp về màn hình (keyword marker), HOẶC
        #   2. Cache autonomous vision đã cũ hơn ERIS_CHAT_VISION_STALE_SEC (mặc định 90s)
        #
        # Tránh VLM call nặng mỗi lượt chat — trước đây "bỏ gate" gây mỗi chat
        # phải OCR lại toàn màn hình, dẫn đến 2 LLM call nối tiếp.

        # Nếu user hỏi về màn hình → luôn chụp mới
        user_wants_screen = self._looks_like_screen_vision_request(user_text)

        # Kiểm tra cache autonomous còn tươi không
        stale_threshold = float(
            (lambda r: max(30.0, float(r)) if r.strip() else 90.0)(
                str(os.environ.get("ERIS_CHAT_VISION_STALE_SEC", "90") or "90")
            )
        )
        last_capture = float(getattr(self, "vision_last_capture_at", 0.0) or 0.0)
        cache_age = time.time() - last_capture if last_capture > 0.0 else float("inf")
        cache_is_fresh = cache_age < stale_threshold
        has_cached_facts = bool(tuple(getattr(self, "vision_facts", ()) or ()))

        if not user_wants_screen and cache_is_fresh and has_cached_facts:
            self.logger.debug(
                "[vision chat] Dùng vision_facts cache (age=%.0fs < stale=%.0fs, %d facts).",
                cache_age,
                stale_threshold,
                len(tuple(getattr(self, "vision_facts", ()) or ())),
            )
            return ""  # Không cần data_uri — grounding context sẽ dùng vision_facts có sẵn

        capture_fn = getattr(self.telemetry_service, "capture_screen_frame_data_uri", None)
        if not callable(capture_fn):
            self.logger.info("[vision chat] telemetry service không hỗ trợ chụp màn hình.")
            return ""

        try:
            data_uri = capture_fn()
        except Exception as exc:
            self.logger.warning("[vision chat] không chụp được màn hình: %s", exc)
            return ""

        reason = "user_screen_request" if user_wants_screen else f"cache_stale_{cache_age:.0f}s"
        self.logger.info("[vision chat] Chụp màn hình mới (%s).", reason)
        snapshot = getattr(self, "_chat_snapshot_for_vision", None)
        if snapshot is not None:
            try:
                self._refresh_screen_facts_from_data_uri(
                    data_uri=data_uri,
                    snapshot=snapshot,
                    channel="chat",
                    user_text=user_text,
                    force_refresh=True,
                )
            except Exception as exc:
                self.logger.warning("[vision chat] không nén được screenshot: %s", exc)
        return data_uri

    
    def _chat_source_grounding_screen_facts(self, snapshot, *, screen_image_data_uri: str = "") -> tuple[object, ...]:
        facts: list[object] = []
        # Luôn dùng vision_facts gần nhất từ coordinator (autonomous OCR đã bắt được)
        # — không cần kiểm tra window 10s vì facts đó vẫn là thật, chỉ hơi cũ.
        # Ưu tiên snapshot (mới nhất), fallback về self.vision_facts của coordinator.
        coordinator_facts = tuple(getattr(self, "vision_facts", ()) or ())
        snapshot_facts = tuple(getattr(snapshot, "vision_facts", ()) or ())
        merged = snapshot_facts or coordinator_facts
        if merged:
            facts.extend(merged)
        if screen_image_data_uri:
            facts.append(
                {
                    "id": "chat_screen_frame",
                    "source": "screen_capture",
                    "claim": "live screenshot attached for current chat turn",
                    "confidence": 0.93,
                    "tags": ["vision", "screen", "chat"],
                }
            )
        elif not merged:
            # Không chụp tươi lượt này VÀ chưa có facts nào: nếu runtime VẪN có màn hình
            # (vừa chụp lượt trước, hoặc telemetry chụp được) thì cho ERIS hiểu nó có màn
            # hình — chỉ là chưa đọc được nội dung lượt này. Tránh thú nhận sai "tôi chưa
            # từng thấy màn hình". Marker này được coi là stale ở tầng grounding.
            captured_before = float(getattr(self, "vision_last_capture_at", 0.0) or 0.0) > 0.0
            # "tôi CÓ THỂ nhìn" != "tôi ĐÃ nhìn": chỉ phát marker stale khi ERIS THỰC SỰ
            # đã chụp frame trước đó. Bỏ điều kiện "telemetry có hàm chụp" (can_capture)
            # vì nó gần như luôn True và khiến ERIS bịa "màn hình từng hiện lượt trước"
            # dù chưa hề thấy gì → nói dối tri giác (#2). Khi chưa từng chụp: không phát
            # marker nào -> grounding để ERIS thú nhận thật rằng nó chưa nhìn màn hình.
            if captured_before:
                facts.append(
                    {
                        "id": "screen_prev_turn",
                        "source": "screen_capture_prev_turn",
                        "claim": "screen was visible on a previous turn (no fresh capture this turn)",
                        "confidence": 0.5,
                        "tags": ["vision", "screen", "stale"],
                    }
                )
        return tuple(facts)

    def _build_chat_source_grounding_report(
        self,
        *,
        user_text: str,
        frame,
        snapshot,
        memory_resonance=None,
        screen_image_data_uri: str = "",
    ):
        engine = getattr(self, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            engine = SourceGroundingEngine()
            self.source_grounding_engine = engine
        return engine.analyze(
            user_text,
            frame=frame,
            screen_facts=self._chat_source_grounding_screen_facts(
                snapshot,
                screen_image_data_uri=screen_image_data_uri,
            ),
            # Không chụp tươi lượt này -> mọi facts màn hình (nếu có) là từ lượt trước.
            screen_facts_stale=not bool(screen_image_data_uri),
            memory_packet=memory_resonance,
            runtime_state=snapshot,
            allow_web=False,
            attach_to_frame=True,
        )

    def _log_chat_source_grounding(self, report) -> None:
        if report is None:
            return
        self.logger.info(
            "[source grounding] grounding_source=%s | preempt_mode=%s | missing=%s | allowed=%s | cap=%.2f | memory_answer=%s | warnings=%s",
            getattr(report, "grounding_source", "unknown"),
            getattr(report, "preempt_mode", "") or "none",
            ",".join(getattr(report, "missing_evidence", ()) or ()) or "none",
            ",".join(getattr(report, "allowed_sources", ()) or ()) or "none",
            float(getattr(report, "confidence_cap", 0.0) or 0.0),
            int(bool(getattr(report, "memory_answer_allowed", True))),
            ",".join(getattr(report, "warnings", ()) or ()) or "none",
        )

    def _normalize_public_reaction_text(self, text: str) -> str:
        lowered = (text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d")
        lowered = re.sub(r"[^a-z0-9_\s]+", " ", lowered)
        return " ".join(lowered.split())

    def _previous_public_turn_has_protocol_leak(self, public_turn) -> str:
        if public_turn is None:
            return ""
        text = str(getattr(public_turn, "text", "") or "")
        detector = getattr(self, "_detect_protocol_surface_leak", None)
        if callable(detector) and detector(text):
            return "prompt_leak"
        normalized = self._normalize_public_reaction_text(text)
        raw_lower = text.lower()
        prompt_markers = (
            "speech intent",
            "speech evidence",
            "persona",
            "constraints",
            "return only",
            "valid json object",
            "ghi chu nen",
            "goi y dieu phoi",
            "llm final prompt",
            "critical output contract",
        )
        prompt_hits = sum(1 for marker in prompt_markers if marker in normalized or marker in raw_lower)
        if prompt_hits >= 2 or (prompt_hits >= 1 and ("*" in text or "`" in text)):
            return "prompt_leak"
        metadata_markers = (
            '\", \"intent\"',
            '\", \"action\"',
            "reasoning_tags",
            "should_speak",
            "debug_trace",
            "system_action",
        )
        if any(marker in text for marker in metadata_markers) or any(marker in normalized for marker in ("intent action", "debug trace")):
            return "metadata_leak"
        return ""

    def _user_is_challenging_previous_public_turn(self, user_text: str) -> bool:
        normalized = self._normalize_public_reaction_text(user_text)
        if not normalized:
            return False
        markers = (
            "ban vua biet ban noi cai gi khong",
            "vua biet ban noi cai gi khong",
            "ban vua noi cai gi",
            "vua noi cai gi",
            "khong thay no te",
            "khong thay te",
            "no te a",
            "te a",
            "te qua",
            "loi gi",
            "bi loi",
            "prompt",
            "json",
            "metadata",
            "debug",
            "raw",
            "parser",
            "format",
        )
        return any(marker in normalized for marker in markers)

    def _build_previous_public_turn_repair_decision(
        self,
        *,
        user_text: str,
        previous_public_turn,
        ti_report,
        grounding_report=None,
        frame=None,
        speech_core=None,
    ) -> Decision | None:
        leak_kind = self._previous_public_turn_has_protocol_leak(previous_public_turn)
        text = ""
        repair_kind = leak_kind
        if leak_kind and self._user_is_challenging_previous_public_turn(user_text):
            if leak_kind == "prompt_leak":
                text = (
                    "Có. Câu vừa rồi lỗi thật. Tôi để phần hậu trường lọt ra ngoài "
                    "thay vì nói một câu bình thường."
                )
            else:
                text = (
                    "Có. Câu vừa rồi lỗi thật. Nó dính phần hậu trường vào lời nói; "
                    "đáng lẽ tôi phải nuốt lại trước khi gửi ra ngoài."
                )
        elif previous_public_turn is not None:
            # Misread repair tổng quát: user phủ định câu public trước ("tôi có code đâu",
            # "hả", "tôi chỉ nghe nhạc...") thì không thả qua LLM hỏi vòng. Sửa frame sai
            # trước, vì đó là nhịp người hơn: bị bắt lỗi -> nhận lỗi -> bỏ giả định cũ.
            try:
                from runtime.banter_arbiter import BanterArbiter
                arbiter = getattr(self, "_banter_arbiter", None)
                if not isinstance(arbiter, BanterArbiter):
                    arbiter = BanterArbiter()
                    self._banter_arbiter = arbiter
                banter = arbiter.repair_correction(
                    user_text=user_text,
                    previous_text=str(getattr(previous_public_turn, "text", "") or ""),
                    grounding=grounding_report,
                    frame=frame,
                    speech_core=speech_core,
                )
                if banter.changed:
                    text = banter.text
                    repair_kind = banter.mode
            except Exception as exc:
                try:
                    self.logger.warning("[previous_public_turn_repair] banter repair failed: %s", exc)
                except Exception:
                    pass
        if not text:
            return None
        decision = Decision(
            text=text,
            intent="repair_previous_public_turn",
            action="none",
            animation="stand",
            should_speak=True,
            confidence=0.86,
            parse_mode="public_turn_repair",
            debug_trace=f"previous_public_turn_repair;kind={repair_kind or 'unknown'};turn_id={getattr(previous_public_turn, 'turn_id', '')}",
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _build_grounding_preempt_decision(self, report, ti_report, *, user_text: str) -> Decision | None:
        engine = getattr(self, "source_grounding_engine", None)
        if not isinstance(engine, SourceGroundingEngine):
            return None
        if not engine.should_preempt(report):
            return None
        text = engine.build_preemptive_reply(report)
        if not text:
            text = self._generate_grounding_preempt_text(report, user_text=user_text)
        if not text:
            # No Python-authored sentence here. If local wording is unavailable,
            # let the normal chat LLM path continue with source_grounding context
            # and let post-generation guards catch any overclaim. Apparently even
            # a machine needs due process now.
            return None
        warnings = ",".join(getattr(report, "warnings", ()) or ())
        debug_trace = (
            "source_grounding_preempt;"
            f"source={getattr(report, 'primary_source', 'unknown')};"
            f"preempt={getattr(report, 'preempt_mode', '') or 'unknown'};"
            f"warnings={warnings}"
        )
        epistemic_mode = str(getattr(report, "epistemic_mode", "") or "")
        is_probe = epistemic_mode in {"probe", "hypothesis"}
        decision = Decision(
            text=text,
            intent="epistemic_probe" if is_probe else "grounding_clarification",
            action="none",
            animation="stand",
            should_speak=True,
            confidence=float(getattr(report, "max_confidence", 0.30) or 0.30),
            parse_mode="source_grounding_probe" if is_probe else "source_grounding_preempt",
            debug_trace=debug_trace + (f";epistemic_mode={epistemic_mode};llm_generated=1" if epistemic_mode else ";llm_generated=1"),
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _generate_grounding_preempt_text(self, report, *, user_text: str) -> str:
        service = getattr(self, "llm_service", None)
        reroll = getattr(service, "rewrite_guard_violation_text", None)
        if not callable(reroll):
            return self._local_grounding_preempt_text(report, user_text=user_text)
        fallback_decision = getattr(report, "fallback_decision", None)
        missing = tuple(str(item) for item in (getattr(report, "missing_evidence", ()) or ()) if str(item or "").strip())
        reason = (
            str(getattr(fallback_decision, "reason", "") or "")
            or str(getattr(report, "preempt_mode", "") or "")
            or "source_grounding_preempt"
        )
        try:
            internal_context_fn = getattr(self, "_guard_internal_state_context", None)
            internal_context = internal_context_fn() if callable(internal_context_fn) else ""
        except Exception:
            internal_context = ""
        try:
            text = reroll(
                original_text="",
                violation_rule="source_grounding_preempt",
                violation_reason=reason,
                missing_evidence=missing,
                fallback_text="",
                channel="chat",
                user_text=user_text,
                internal_state_context=internal_context,
                grounding_context=str(getattr(report, "prompt_context", "") or ""),
                arbitration_context=(
                    "SourceGrounding is a flag emitter only. Generate a short public line "
                    "that respects missing evidence without using a static Python fallback."
                ),
            )
        except Exception as exc:
            try:
                self.logger.warning("[source grounding] preempt llm repair failed: %s", exc)
            except Exception:
                pass
            return self._local_grounding_preempt_text(report, user_text=user_text)
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return self._local_grounding_preempt_text(report, user_text=user_text)
        missing_set = set(missing)
        try:
            if "file_evidence" in missing_set and self._looks_like_file_grounded_claim(text, report=report):
                return self._local_grounding_preempt_text(report, user_text=user_text)
            if "screen_evidence" in missing_set and self._looks_like_screen_grounded_claim(text):
                return self._local_grounding_preempt_text(report, user_text=user_text)
            if "web_access_or_search_result" in missing_set and self._looks_like_live_web_claim(text):
                return self._local_grounding_preempt_text(report, user_text=user_text)
        except Exception:
            return self._local_grounding_preempt_text(report, user_text=user_text)
        return text

    def _local_grounding_preempt_text(self, report, *, user_text: str = "") -> str:
        del user_text
        mode = str(getattr(report, "preempt_mode", "") or "")
        file_mentions = tuple(str(item) for item in (getattr(report, "file_mentions", ()) or ()) if str(item or "").strip())
        if mode == "filename_only":
            label = file_mentions[0] if file_mentions else "file đó"
            return f"Tôi mới chỉ có tên file {label}, chưa có nội dung file để kết luận."
        if mode == "deictic_without_vision":
            return "Tôi chưa có evidence màn hình đủ mới để nói câu này chắc được."
        missing = set(str(item) for item in (getattr(report, "missing_evidence", ()) or ()) if str(item or "").strip())
        if "file_evidence" in missing:
            label = file_mentions[0] if file_mentions else "file đó"
            return f"Tôi chưa có nội dung {label} để trả lời chắc tay."
        if "screen_evidence" in missing:
            return "Tôi chưa có evidence màn hình đủ rõ cho câu hỏi này."
        return ""

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
    def _get_turn_semantics_engine(self) -> TurnSemanticsEngine:
        engine = getattr(self, "turn_semantics_engine", None)
        if engine is None:
            engine = TurnSemanticsEngine()
            self.turn_semantics_engine = engine
        return engine

    def _build_turn_semantics_report(
        self,
        *,
        user_text: str,
        repeat_count: int,
        previous_user_text: str = "",
        affect_signal=None,
        conversation_report=None,
        relationship_report=None,
        grounding_report=None,
    ) -> TurnSemanticsReport:
        engine = self._get_turn_semantics_engine()
        return engine.analyze_repeat(
            user_text=user_text,
            repeat_count=repeat_count,
            last_user_text=previous_user_text,
            last_assistant_text=getattr(self, "last_chat_answer", ""),
            affect_signal=affect_signal,
            conversation_report=conversation_report,
            relationship_report=relationship_report,
            grounding_report=grounding_report,
        )

    def _build_repeat_guard_decision(
        self,
        user_text: str,
        ti_report,
        repeat_count: int,
        *,
        grounding_report=None,
        turn_semantics_report: TurnSemanticsReport | None = None,
    ) -> Decision | None:
        if repeat_count < 2:
            return None

        report = turn_semantics_report or self._build_turn_semantics_report(
            user_text=user_text,
            repeat_count=repeat_count,
            previous_user_text=getattr(self, "last_user_text_for_semantics", ""),
            grounding_report=grounding_report,
        )

        # Legacy bypass chỉ còn là dây an toàn cho live observation; quyền quyết định chính
        # thuộc về TurnSemanticsEngine. Exact repeat không được đứng trên meaning.
        if self._should_bypass_repeat_guard_for_live_observation(user_text, grounding_report=grounding_report):
            return None
        if not report.should_guard_repeat:
            return None

        text = self._get_turn_semantics_engine().build_repeat_guard_text(report)
        if "lặp lại" not in text.lower():
            text = f"{text} Tôi đang giữ nhịp lặp lại này lại."
        decision = Decision(
            text=text,
            intent="low_value_repeat",
            action="none",
            animation="read" if repeat_count == 2 else "sad",
            should_speak=True,
            confidence=min(0.78, max(0.42, report.confidence)),
            parse_mode="repeat_guard",
            debug_trace=(
                f"repeat_guard=count={repeat_count};"
                f"intent={report.intent};spam={report.spam_pressure:.2f};"
                f"reasons={','.join(report.reasons) or 'none'}"
            ),
        )
        return self.ti_governor.enforce_decision(decision, ti_report, user_hint=user_text)

    def _should_bypass_repeat_guard_for_live_observation(self, user_text: str, *, grounding_report=None) -> bool:
        if grounding_report is not None:
            if str(getattr(grounding_report, "preempt_mode", "") or "") == "deictic_without_vision":
                return False
            missing = set(getattr(grounding_report, "missing_evidence", ()) or ())
            if bool(getattr(grounding_report, "refers_to_current_screen", False)) and "screen_evidence" not in missing:
                return True
        return self._looks_like_screen_vision_request(user_text)
