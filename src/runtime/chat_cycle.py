from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import replace

from cortex.ni import NiStateMachine
from cortex.relationship_dynamics import RelationshipTurnEvent
from domain import Decision


class ChatCycleMixin:
    def _enter_chat_cycle(self) -> None:
        if not self.chat_mode:
            self.chat_mode = True
            self.chat_ni_state = NiStateMachine()
            self.repeated_user_count = 0
            self.last_user_signature = ""
            self.logger.info("Entered chat mode; autonomous is paused for user messages.")

    def _end_chat_cycle(self) -> None:
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
        self.logger.info("Exited chat mode; autonomous can resume.")

    def _run_chat_cycle(self, user_text: str) -> None:
        cycle_start = time.time()
        if not user_text:
            return
        if not self.chat_mode:
            self.chat_ni_state = NiStateMachine() # reset trạng thái Ni khi bắt đầu chat mới, để tránh mang theo drift state từ autonomous mode.

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
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
        fe_plan = self.fe_renderer.evaluate_chat(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=self.fe_style_memory,
            internal_state=internal_state_before,
            user_text=user_text,
            affect_signal=affect_signal,
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
        )
        relationship_event = RelationshipTurnEvent.from_affect(
            user_text=user_text,
            affect=affect_signal,
            turn_index=max(1, int(getattr(sensed_internal_state, "chat_ticks", 0) or 0) + 1),
            assistant_overread=bool(conversation_report.correction_detected),
            repeated_project_context=self.active_conversational_topic in {"technical_support", "goal_guard"},
        )
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
            "[relationship dynamics] event=%s | trust=%.2f | rupture=%.2f | distance=%.2f | notes=%s",
            relationship_report.state.last_event,
            relationship_report.state.trust,
            relationship_report.state.rupture,
            relationship_report.state.preferred_distance,
            ",".join(relationship_report.notes) or "none",
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
            speech_intent=self._speech_intent_from_core(speech_core, channel="chat"),
            speech_act=speech_core.utterance_type if speech_core.should_speak else "",
            reason=speech_core.reason or ti_report.reason,
            snapshot=snapshot,
            user_text=user_text,
            concrete_signals=self._concrete_screen_signals(snapshot),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("chat_reply",),
            inner_thought=speech_core.inner_thought,
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
        llm_chat_history = self._chat_history_for_llm(limit=16)[:-1]
        self.logger.info("[LLM CHAT HISTORY] %s", llm_chat_history[-8:])
        raw = self.llm_service.generate_chat_reply(
            chat_history=llm_chat_history,
            user_message=chat_user_message,
            raw_user_text=user_text,
            ni_context=ni_report.prompt_context,
            ti_context=planned_ti_context,
            fe_context=fe_plan.style_context,
            appraisal_context=self._build_appraisal_context(frame.appraisal),
            internal_state_context=self._build_internal_state_context(sensed_internal_state, frame.self_state),
            conversation_context=conversation_report.prompt_context,
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
        decision = self._apply_chat_final_guards(decision, user_text=user_text)
        self._commit_chat_decision(decision, fe_plan, frame=frame)
        return

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
