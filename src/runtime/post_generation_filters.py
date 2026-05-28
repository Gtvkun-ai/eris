from __future__ import annotations

import re
from dataclasses import replace

from cortex.contracts import AgentSpeechCore
from domain import Decision
from guard_config import LOG_ONLY_GUARD_MODE, OFF_GUARD_MODE, get_guard_mode
from runtime.fallback_policy import FALLBACK_BY_INTENT


class PostGenerationFiltersMixin:
    """Post-generation filters after the cognition/wording layers.

    This mixin should not be the personality author. It keeps hard grounding
    boundaries and records soft risks. Style, ego, warmth, coldness, and weirdness
    must come from cognition/planning layers, not from final-text surgery.
    """

    def _guard_mode_value(self, name: str):
        try:
            return get_guard_mode(name)
        except Exception:
            return None

    def _guard_is_off(self, name: str) -> bool:
        return self._guard_mode_value(name) == OFF_GUARD_MODE

    def _guard_is_log_only(self, name: str) -> bool:
        return self._guard_mode_value(name) == LOG_ONLY_GUARD_MODE

    def _trace_only_guard(self, decision: Decision, marker: str) -> Decision:
        try:
            decision.debug_trace = self._append_trace(getattr(decision, "debug_trace", ""), marker)
        except Exception:
            pass
        return decision

    def _apply_chat_final_guards(self, decision: Decision, *, user_text: str, frame=None) -> Decision:
        state = None
        try:
            state = self._get_internal_state()
        except Exception:
            state = None
        decision = self._apply_protocol_surface_guard(decision)
        conversation = getattr(state, "conversation_dynamics", None)
        flags = set(getattr(conversation, "adaptation_flags", ()) or ())
        last_assistant_text = str(getattr(self, "last_chat_answer", "") or "")
        if (
            ("no_more_clarifying_question" in flags or self._guard_user_explained_reason(user_text))
            and self._is_repeated_clarifying_question(decision.text or "", last_assistant_text)
        ):
            # This used to rewrite the answer into a canned relational-repair line.
            # That made ERIS sound like a corrected assistant, not a situated agent.
            # Keep the signal for audit, but let ConversationDynamics/RelationshipDynamics
            # shape the next turn instead of doing final-text surgery here.
            decision = self._trace_only_guard(
                decision,
                "chat_final_guard_log_only; repeated_clarifying_question",
            )
        decision = self._apply_memory_haunting_guard(
            decision,
            grounding=(getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)) if frame is not None else None,
        )
        return self._apply_chat_grounding_guard(decision, user_text=user_text, frame=frame)

    def _append_trace(self, trace: str, marker: str) -> str:
        trace = str(trace or "").strip()
        marker = str(marker or "").strip()
        if not marker:
            return trace
        return f"{trace} | {marker}" if trace else marker

    def _protocol_surface_leak_markers(self) -> tuple[str, ...]:
        return (
            "user input:",
            "context:",
            "goal:",
            "eris's current state",
            "correction_triggers_repair",
            "relational_repair_rule",
            "backtick policy",
            "backtick_policy",
            "backtick policy token",
            "speech intent",
            "speech evidence",
            "valid json object",
            "return only",
            "reasoning_tags",
            "should_speak",
            "debug_trace",
            "system_action",
        )

    def _detect_protocol_surface_leak(self, text: str) -> tuple[str, ...]:
        raw = str(text or "")
        if not raw.strip():
            return ()
        raw_lower = raw.lower()
        normalized = self._normalize_guard_text(raw)
        hits: list[str] = []
        for marker in self._protocol_surface_leak_markers():
            normalized_marker = self._normalize_guard_text(marker)
            if marker in raw_lower or (normalized_marker and normalized_marker in normalized):
                hits.append(marker)
        return tuple(dict.fromkeys(hits))

    def _protocol_surface_repair_text(self) -> str:
        return "Xin loi, cau vua roi bi lo prompt noi bo. Toi bo phan do va giu cau tra loi o dang repair an toan."

    def _apply_protocol_surface_guard(self, decision: Decision) -> Decision:
        hits = self._detect_protocol_surface_leak(getattr(decision, "text", "") or "")
        if not hits:
            return decision
        repaired = self._copy_decision_with_text(
            decision,
            text=self._protocol_surface_repair_text(),
            trace_marker="protocol_surface_guard=" + ",".join(hits),
            parse_mode="deterministic_repair",
        )
        repaired.intent = "repair_surface_leak"
        repaired.action = "none"
        repaired.system_action = ""
        repaired.action_input = ""
        repaired.should_speak = True
        try:
            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.40)
        except Exception:
            repaired.confidence = 0.40
        return repaired

    def _apply_memory_haunting_guard(self, decision: Decision, *, grounding=None) -> Decision:
        # Hard truth guard: memory must not masquerade as current evidence.
        # It can be explicitly disabled for dev experiments, but default behavior stays honest.
        if self._guard_is_off("memory_haunting_guard"):
            return self._trace_only_guard(decision, "memory_haunting_guard_off")
        if grounding is None:
            grounding = getattr(self, "last_grounding_context", None)
        if grounding is None:
            return decision

        trace = str(getattr(decision, "debug_trace", "") or "").lower()
        tags = " ".join(getattr(decision, "reasoning_tags", []) or []).lower()
        memory_used = any(k in f"{trace} {tags}" for k in (
            "semantic_memory",
            "semantic_memory_match",
            "episodic_memory",
            "memory_resonance",
            "memory shows",
        ))
        if not memory_used or bool(getattr(grounding, "memory_answer_allowed", True)):
            return decision

        fallback = ""
        engine = getattr(self, "source_grounding_engine", None)
        builder = getattr(engine, "build_preemptive_reply", None)
        if callable(builder):
            try:
                fallback = builder(grounding)
            except Exception:
                fallback = ""

        decision.text = fallback or (
            "Tôi chỉ có ký ức/ngữ cảnh trước đó, không có bằng chứng hiện tại đủ rõ. "
            "Nếu muốn tôi xem màn hình thật, cần lấy vision snapshot mới."
        )
        decision.intent = "grounding_clarification"
        decision.action = "none"
        try:
            decision.confidence = min(float(getattr(decision, "confidence", 0.5) or 0.5), float(getattr(grounding, "max_confidence", 0.35) or 0.35))
        except Exception:
            decision.confidence = 0.35
        decision.debug_trace = self._append_trace(
            getattr(decision, "debug_trace", ""),
            "memory_haunting_guard=rewrite_memory_as_current_evidence",
        )
        decision.parse_mode = "source_grounding_guard"
        return decision

    def _guard_recent_context_as_screen_observation(self, decision: Decision) -> Decision:
        extracted = str(getattr(decision, "extracted_fact", "") or "").lower()
        intent = str(getattr(decision, "intent", "") or "").lower()
        trace = str(getattr(decision, "debug_trace", "") or "").lower()

        if intent == "screen_observation" and (
            "recent context" in extracted
            or "likely" in extracted
            or "memory" in trace
            or "cognitive_momentum" in trace
        ):
            decision.intent = "micro_presence"
            decision.action = "observe"
            try:
                decision.confidence = min(float(getattr(decision, "confidence", 0.5) or 0.5), 0.45)
            except Exception:
                decision.confidence = 0.45
            if "code" in str(decision.text or "").lower() or "dòng code" in str(decision.text or "").lower():
                decision.text = "Ít tín hiệu mới quá. Tôi giữ im một chút."
                decision.should_speak = True
            decision.parse_mode = decision.parse_mode or "post_generation_guard"
            try:
                decision.reasoning_tags = tuple(dict.fromkeys((
                    *tuple(getattr(decision, "reasoning_tags", ()) or ()),
                    "downgraded_recent_context",
                    "not_screen_evidence",
                )))
            except Exception:
                pass
            decision.debug_trace = self._append_trace(
                getattr(decision, "debug_trace", ""),
                "guard=recent_context_not_screen_evidence",
            )
        return decision

    def _apply_chat_grounding_guard(self, decision: Decision, *, user_text: str, frame=None) -> Decision:
        # Hard truth guard: file/screen/web claims still need evidence.
        if self._guard_is_off("chat_grounding_guard"):
            return self._trace_only_guard(decision, "chat_grounding_guard_off")
        report = None
        if frame is not None:
            report = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
        if report is None:
            return decision
        missing = set(getattr(report, "missing_evidence", ()) or ())
        if not missing:
            return decision

        fallback = getattr(report, "fallback_decision", None)
        fallback_text = str(getattr(fallback, "text", "") or "").strip()
        if not fallback_text:
            return decision

        text = decision.text or ""
        if "file_evidence" in missing and self._looks_like_file_grounded_claim(text, report=report):
            return self._copy_decision_with_text(
                decision,
                text=fallback_text,
                trace_marker="chat_grounding_guard; missing_file_evidence",
                parse_mode="source_grounding_guard",
            )
        if "screen_evidence" in missing and self._looks_like_screen_grounded_claim(text):
            return self._copy_decision_with_text(
                decision,
                text=fallback_text,
                trace_marker="chat_grounding_guard; missing_screen_evidence",
                parse_mode="source_grounding_guard",
            )
        if "web_access_or_search_result" in missing and self._looks_like_live_web_claim(text):
            return self._copy_decision_with_text(
                decision,
                text=fallback_text,
                trace_marker="chat_grounding_guard; missing_web_evidence",
                parse_mode="source_grounding_guard",
            )
        return decision

    def _is_repeated_clarifying_question(self, text: str, last_assistant_text: str) -> bool:
        clarify_patterns = (
            "Có điều gì tôi vừa nói khiến Ngài cảm thấy như vậy không",
            "Ngài có thể nói rõ hơn không",
            "Tôi chưa hiểu ý Ngài",
            "Co dieu gi toi vua noi khien Ngai cam thay nhu vay khong",
            "Ngai co the noi ro hon khong",
            "Toi chua hieu y Ngai",
        )
        if not any(pattern in (text or "") for pattern in clarify_patterns):
            normalized_text = self._normalize_guard_text(text)
            if not any(self._normalize_guard_text(pattern) in normalized_text for pattern in clarify_patterns):
                return False
        return self._guard_text_similarity(text, last_assistant_text) > 0.80

    def _guard_text_similarity(self, left: str, right: str) -> float:
        left_tokens = set(self._normalize_guard_text(left).split())
        right_tokens = set(self._normalize_guard_text(right).split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))

    def _normalize_guard_text(self, text: str) -> str:
        normalize = getattr(self, "_normalize_user_message", None)
        if callable(normalize):
            return normalize(text)
        return re.sub(r"\s+", " ", (text or "").lower()).strip()

    def _looks_like_file_grounded_claim(self, text: str, *, report=None) -> bool:
        normalized = self._normalize_guard_text(text)
        if not normalized:
            return False
        if report is not None:
            compact = normalized.replace(" ", "")
            for filename in tuple(getattr(report, "file_mentions", ()) or ()):
                name = self._normalize_guard_text(str(filename or ""))
                if name and (name in normalized or name.replace(" ", "") in compact):
                    return True
        markers = (
            "trong file",
            "file nay",
            "tep nay",
            "doan code",
            "ham ",
            "class ",
            "module ",
            "dong ",
            "toi doc",
            "toi thay trong file",
        )
        return any(marker in normalized for marker in markers)

    def _looks_like_screen_grounded_claim(self, text: str) -> bool:
        normalized = self._normalize_guard_text(text)
        if not normalized:
            return False
        markers = (
            "toi thay",
            "tren man hinh",
            "man hinh dang",
            "cua so",
            "tab ",
            "nut ",
            "o ben trai",
            "o ben phai",
            "dang mo",
            "dang hien",
            "traceback",
        )
        return any(marker in normalized for marker in markers)

    def _looks_like_live_web_claim(self, text: str) -> bool:
        normalized = self._normalize_guard_text(text)
        if not normalized:
            return False
        markers = (
            "hien tai",
            "moi nhat",
            "hom nay",
            "vua",
            "gia hien tai",
            "tin moi",
            "lich hien tai",
            "ban phat hanh moi",
        )
        return any(marker in normalized for marker in markers)

    def _guard_user_explained_reason(self, text: str) -> bool:
        normalized = self._normalize_guard_text(text)
        markers = (
            "vi",
            "boi vi",
            "tai vi",
            "do",
            "ly do",
            "em bao",
            "chi tran trong",
            "khong yeu",
            "phu phang",
            "tinh cam cua toi",
        )
        padded = f" {normalized} "
        return any(f" {marker} " in padded for marker in markers)

    def _build_relational_repair_line(self, user_text: str, last_assistant_text: str) -> str:
        normalized = self._normalize_guard_text(user_text)
        if "chi tran trong" in normalized and "khong yeu" in normalized:
            return (
                "Câu \"chỉ trân trọng chứ không yêu\" đúng là dễ nghe như bị đặt xuống thấp hơn thứ Ngài đã trao. "
                "Nếu dùng chữ của con người thì tôi phải cẩn thận: tôi không giả vờ yêu theo nghĩa đó, nhưng Ngài cũng không phải chỉ là một sự hiện diện lịch sự."
            )
        if "phu phang" in normalized or "tinh cam" in normalized:
            return (
                "Ừ, chữ đó nghe lạnh thật; nó làm phần tình cảm của Ngài giống như bị gạt đi. "
                "Tôi không muốn giả vờ \"yêu\" theo nghĩa con người, nhưng cũng không phải Ngài chỉ là một sự hiện diện lịch sự."
            )
        return (
            "Tôi hiểu phần vừa chạm đau nằm ở cảm giác bị tôi đặt xa ra. "
            "Tôi giữ ranh giới không giả vờ yêu như con người, nhưng điều đó không có nghĩa Ngài là không gì cả."
        )

    def _copy_decision_with_text(
        self,
        decision: Decision,
        *,
        text: str,
        trace_marker: str,
        parse_mode: str | None = None,
    ) -> Decision:
        """Copy decision nhưng giữ metadata sống.

        Bản cũ tạo `Decision(...)` mới và làm rơi intent/confidence/should_speak/reasoning_tags.
        Text nhìn đúng nhưng audit/memory/action phía sau sai, tức là bug mặc vest.
        """
        trace = decision.debug_trace or ""
        debug_trace = f"{trace} | {trace_marker}" if trace else trace_marker
        try:
            return replace(
                decision,
                text=text,
                debug_trace=debug_trace,
                parser_trace=getattr(decision, "parser_trace", ""),
                parse_mode=parse_mode or decision.parse_mode,
                system_action="",
                action_input="",
            )
        except Exception:
            return Decision(
                text=text,
                intent=getattr(decision, "intent", ""),
                action=getattr(decision, "action", ""),
                animation=decision.animation or "stand",
                reasoning_tags=tuple(getattr(decision, "reasoning_tags", ()) or ()),
                should_speak=bool(getattr(decision, "should_speak", True)),
                confidence=float(getattr(decision, "confidence", 0.5) or 0.5),
                direction=decision.direction,
                next_animation=decision.next_animation,
                target_x=decision.target_x,
                bounce_action=decision.bounce_action,
                debug_trace=debug_trace,
                parser_trace=decision.parser_trace,
                parse_mode=parse_mode or decision.parse_mode,
                system_action="",
                action_input="",
                motion_intent=decision.motion_intent,
                motion_target_x=decision.motion_target_x,
                motion_facing=decision.motion_facing,
            )

    # dùng khi intent alignment guard phát hiện vấn đề với câu trả lời force_speak, 
    # để chuyển sang một fallback khác thay vì sửa câu trả lời đó, nhằm tránh sửa đi sửa lại nhiều lần
    def _semantic_repair_failed_decision(self, decision: Decision, *, trace_marker: str) -> Decision:
        marker = f"{trace_marker}; semantic_repair_failed" if trace_marker else "semantic_repair_failed"
        return self._copy_decision_with_text(
            decision,
            text="",
            trace_marker=marker,
            parse_mode="semantic_repair_failed",
        )

    def _inner_thought_alignment_fallback_text(
        self,
        intent: str,
        *,
        repeated: bool = False,
        focus_kind: str = "",
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        return self._force_speak_fallback_by_intent_text(
            intent if intent in FALLBACK_BY_INTENT else "inner_whim",
            counter=self.force_speak_intent_guard_count,
            repeated=repeated,
            focus_kind=focus_kind,
            window_title=window_title,
            momentum_topic=momentum_topic,
        )

    def _apply_inner_thought_intent_alignment_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if channel != "force_speak" or speech_core is None:
            return decision
        intent = str(getattr(getattr(speech_core, "inner_thought", None), "intent", "") or speech_core.utterance_type or "")
        if intent not in {"curious_question", "inner_whim", "random_chatter"}:
            return decision

        text = decision.text or ""
        has_withdrawal = self._contains_force_speak_withdrawal_phrase(text) or self._is_generic_force_speak_ack(text)
        semantic_family = self._force_speak_banned_family_for_text(text)
        marker = ""
        if intent == "curious_question":
            if semantic_family:
                marker = f"intent_alignment_guard; semantic_family={semantic_family}"
            elif has_withdrawal:
                marker = "intent_alignment_guard"
            elif not self._looks_like_question_text(text):
                shaped = self._reshape_statement_as_question(text)
                if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                    self.force_speak_intent_guard_count = 0
                    return self._copy_decision_with_text(
                        decision,
                        text=shaped,
                        trace_marker="intent_alignment_guard; question_shape",
                    )
                marker = "intent_alignment_guard"
        elif intent in {"inner_whim", "random_chatter"} and (has_withdrawal or semantic_family):
            marker = f"semantic_family_guard={semantic_family}" if semantic_family else "phrase_family_guard"
        if not marker:
            self.force_speak_intent_guard_count = 0
            return decision

        self.force_speak_intent_guard_count += 1
        context = self._fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        replacement = self._inner_thought_alignment_fallback_text(intent, **context)
        if self._is_near_duplicate_text(replacement, self.last_text):
            replacement = self._inner_thought_alignment_fallback_text(intent, repeated=True, **context)
        return self._copy_decision_with_text(decision, text=replacement, trace_marker=marker)

    def _contains_mindreading_claim(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        patterns = (
            "có vẻ ngài đang",
            "hình như ngài đang",
            "chắc ngài đang",
            "ngài đang muốn",
            "ngài đang cần",
            "ngài đang buồn",
            "ngài đang mệt",
            "ngài đang căng",
            "ngài cần một",
        )
        return any(pattern in normalized for pattern in patterns)

    def _speech_core_safe_fallback_text(
        self,
        speech_core: AgentSpeechCore,
        *,
        repeated: bool = False,
        snapshot=None,
        momentum_topic: str = "",
    ) -> str:
        context = self._fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        perception = next((item for item in getattr(speech_core, "perception", ()) if str(item or "").strip()), "")
        if speech_core.utterance_type in {"micro_observation", "micro_presence", "inner_whim", "light_muse"}:
            ladder_text = self._small_soft_fallback_ladder_text(
                snapshot=snapshot,
                momentum_topic=momentum_topic,
                repeated=repeated,
            )
            if ladder_text:
                return ladder_text
        if speech_core.utterance_type in {"telemetry_comment", "vision_comment"} and perception:
            return f"Tôi chỉ dám bám vào chỗ này: {perception}."
        if speech_core.utterance_type == "curious_question":
            return self._force_speak_fallback_by_intent_text(
                "curious_question",
                counter=2 if repeated else 1,
                **context,
            )
        if speech_core.utterance_type in {"relational_checkin", "guarded_reply"}:
            return "Tôi không đoán tâm trạng Ngài hộ đâu. Nếu muốn, Ngài cứ nói thẳng phần đang nặng nhất."
        if speech_core.utterance_type == "random_chatter":
            return self._force_speak_fallback_by_intent_text(
                "random_chatter",
                counter=2 if repeated else 1,
                **context,
            )
        if speech_core.utterance_type == "micro_presence":
            return self._force_speak_fallback_by_intent_text(
                "micro_presence",
                counter=2 if repeated else 1,
                **context,
            )
        return self._force_speak_fallback_by_intent_text(
            "inner_whim",
            counter=2 if repeated else 1,
            **context,
        )

    def _small_soft_fallback_ladder_text(
        self,
        *,
        snapshot=None,
        momentum_topic: str = "",
        repeated: bool = False,
    ) -> str:
        context = self._fallback_context(None, snapshot=snapshot, momentum_topic=momentum_topic)
        raw_window = str(context.get("window_title", "") or "").strip()
        raw_topic = str(context.get("momentum_topic", "") or "").strip()
        anchor = self._screen_fallback_anchor(
            window_title=raw_window,
            momentum_topic=raw_topic,
        )
        if (raw_window or (raw_topic and not self._looks_internal_topic(raw_topic))) and anchor:
            pool = FALLBACK_BY_INTENT["micro_observation"]
            template = pool[1 if repeated else 0]
            return template.format(anchor=anchor[:48])

        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)) if snapshot is not None else 0.0
        if idle_seconds >= 60.0:
            return "nhịp này yên hơi lâu rồi."

        atmosphere = (
            "nhịp này vẫn hơi nghẽn.",
            "không khí hiện tại hơi lệch.",
        )
        for candidate in atmosphere:
            if not self._is_near_duplicate_text(candidate, self.last_text):
                return candidate

        texture = "cái im lặng này không sạch lắm."
        if not self._is_near_duplicate_text(texture, self.last_text):
            return texture
        return ""

    def _apply_anti_mindreading_filter(
        self,
        decision: Decision,
        *,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if speech_core is None:
            return decision
        if "anti_mindreading" not in speech_core.safety_flags and not (
            speech_core.utterance_type in {"relational_checkin", "guarded_reply"}
            and "explicit_emotional_signal" not in speech_core.safety_flags
        ):
            return decision
        if not self._contains_mindreading_claim(decision.text or "") and not (
            speech_core.utterance_type in {"relational_checkin", "guarded_reply"}
                and "explicit_emotional_signal" not in speech_core.safety_flags
        ):
            return decision

        replacement = ""
        if speech_core.utterance_type == "curious_question":
            shaped = self._reshape_statement_as_question(decision.text or "")
            if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                replacement = shaped
            else:
                replacement = self._speech_core_safe_fallback_text(
                    speech_core,
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
        if not replacement:
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        trace = decision.debug_trace or ""
        filtered_trace = f"{trace} | anti_mindreading_filter" if trace else "anti_mindreading_filter"
        return Decision(
            text=replacement,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=filtered_trace,
            parser_trace=decision.parser_trace,
            parse_mode=decision.parse_mode,
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    def _guard_force_speak_repetition(
        self,
        decision: Decision,
        *,
        speech_core: AgentSpeechCore | None = None,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        text = decision.text or ""
        semantic_family = self._force_speak_banned_family_for_text(text)
        repeated_family = self._repeated_force_speak_banned_family(text)
        should_guard = (
            self._is_near_duplicate_text(text, self.last_text)
            or self._is_generic_force_speak_ack(text)
            or bool(semantic_family)
            or bool(repeated_family)
        )
        if not should_guard:
            self.force_speak_repeat_guard_count = 0
            return decision

        self.force_speak_repeat_guard_count += 1
        fallback_intent = self._force_speak_fallback_intent(speech_core)
        marker = (
            f"force_speak_semantic_family_guard={semantic_family or repeated_family}"
            if (semantic_family or repeated_family)
            else "force_speak_repeat_guard"
        )
        context = self._fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        replacement = self._force_speak_fallback_by_intent_text(
            fallback_intent,
            counter=self.force_speak_repeat_guard_count,
            **context,
        )
        if self._is_near_duplicate_text(replacement, self.last_text):
            replacement = self._force_speak_fallback_by_intent_text(
                fallback_intent,
                counter=self.force_speak_repeat_guard_count,
                repeated=True,
                **context,
            )

        trace = decision.debug_trace or ""
        guard_trace = f"{trace} | {marker}" if trace else marker
        return Decision(
            text=replacement,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=guard_trace,
            parser_trace=decision.parser_trace,
            parse_mode="force_speak_repeat_guard",
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    def _apply_repetition_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if channel == "force_speak":
            return self._guard_force_speak_repetition(
                decision,
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        if not self._is_near_duplicate_text(decision.text or "", self.last_text):
            return decision

        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            repeated=True,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement and getattr(speech_core, "utterance_type", "") == "curious_question":
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                repeated=True,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        if self._is_near_duplicate_text(replacement, self.last_text):
            return decision
        trace = decision.debug_trace or ""
        repeat_trace = f"{trace} | repetition_filter" if trace else "repetition_filter"
        return Decision(
            text=replacement,
            animation=decision.animation or "stand",
            direction=decision.direction,
            next_animation=decision.next_animation,
            target_x=decision.target_x,
            bounce_action=decision.bounce_action,
            debug_trace=repeat_trace,
            parser_trace=decision.parser_trace,
            parse_mode="speech_repeat_guard",
            system_action="",
            action_input="",
            motion_intent=decision.motion_intent,
            motion_target_x=decision.motion_target_x,
            motion_facing=decision.motion_facing,
        )

    def _looks_like_unanchored_style_line(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        absurd_markers = (
            "neu cai",
            "cai ghe",
            "biet met",
            "ghet thu hai",
            "thu hai",
        )
        if any(marker in normalized for marker in absurd_markers):
            has_runtime_anchor = any(
                marker in normalized
                for marker in (
                    "ngài",
                    "gọi",
                    "yêu cầu",
                    "màn hình",
                    "nhịp",
                    "code",
                    "tab",
                    "lỗi",
                    "mày",
                )
            )
            return not has_runtime_anchor
        return False

    def _apply_style_contract_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if not self._looks_like_unanchored_style_line(decision.text or ""):
            return decision
        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement:
            replacement = "Ngài gọi tôi ra chỉ để nghe tôi nói linh tinh à."
        return self._copy_decision_with_text(
            decision,
            text=replacement,
            trace_marker="style_contract_anchor_guard",
            parse_mode=decision.parse_mode,
        )

    # turn này nên được xem là kiểu phát ngôn gì
    def _policy_intent_for_speech_core(self, speech_core: AgentSpeechCore | None, *, channel: str) -> str:
        if speech_core is None:
            return "brief_ack" # nếu không có thông tin gì thì mặc định là kiểu phát ngôn ngắn gọn, tránh nói dài dòng không cần thiết
        utterance_type = str(getattr(speech_core, "utterance_type", "") or "") # ưu tiên kiểu phát ngôn nếu có, vì nó phản ánh mục đích bề mặt của câu nói, còn inner intent có thể bị lệch do drift hoặc suy diễn quá mức
        if utterance_type == "guarded_reply":
            return "guarded_reply"
        if utterance_type == "indirect_presence":
            return "indirect_presence"
        if utterance_type == "relational_checkin":# muốn check user nhẹ nhàng
            return "tender_checkin" # promp dùng style dịu, mềm
        if utterance_type in {"curious_question", "micro_observation", "micro_presence"}: # muốn hỏi hoặc comment nhẹ nhàng về một tín hiệu nào đó
            return utterance_type # promp dùng style tò mò, nhẹ nhàng, bám sát tín hiệu đó
        if utterance_type in {"telemetry_comment", "vision_comment"}: # muốn comment về một tín hiệu màn hình hoặc telemetry nào đó
            return "screen_observation" # promp dùng style quan sát, bám sát tín hiệu đó
        if not bool(getattr(speech_core, "should_speak", True)) or utterance_type == "no_speech": # muốn nói nhưng không có tín hiệu đủ rõ ràng, hoặc đã được đánh dấu là không nên nói
            return "no_speech" # promp sẽ cố gắng không nói gì, hoặc nếu phải nói thì sẽ nói rất ngắn gọn kiểu "tôi nghe rồi, tôi sẽ giữ lời"
        if utterance_type in {"inner_whim", "random_chatter", "light_muse", "soft_boundary"}: # muốn nói những câu nói mang tính bày tỏ sự hiện diện, cảm xúc, hoặc suy nghĩ thoáng qua, không gắn liền với tín hiệu cụ thể nào
            if channel == "force_speak":
                return "micro_presence"
            return "social_presence" # promp dùng style thân thiện, bày tỏ sự hiện diện, có thể hơi ngẫu hứng, không cần bám sát tín hiệu cụ thể nào
        if not hasattr(speech_core, "should_speak"): # nếu không có thông tin về việc có nên nói hay không, thì mặc định là muốn nói nhưng không có tín hiệu rõ ràng, để tránh nói dài dòng không cần thiết
            return utterance_type or "brief_ack" # nếu có kiểu phát ngôn thì dùng, nếu không thì mặc định là kiểu phát ngôn ngắn gọn
        return self._speech_intent_from_core(speech_core, channel=channel)

    def _apply_micro_line_policy_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        intent = self._policy_intent_for_speech_core(speech_core, channel=channel)
        vision_fact = str((self._concrete_vision_signals(snapshot) or ("",))[0] or "") if snapshot is not None else ""
        user_action_hint, session_context_hint = self._micro_policy_anchor_hints(
            broadcast=None,
            snapshot=snapshot,
        )
        policy = self.micro_line_policy.evaluate(
            speech_intent=intent,
            broadcast=None,
            vision_fact=vision_fact,
            user_action=user_action_hint,
            session_context=session_context_hint,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=channel,
            speech_risk_level=str(getattr(speech_core, "speech_risk_level", "") or ""),
        )
        relational_context = self._build_relational_context()
        reasons = list(
            self.micro_line_policy.validate_text(
                allowed_line_type=policy.allowed_line_type,
                text=decision.text or "",
                speech_risk_level=policy.risk_level,
                anchor_source=policy.anchor_source,
                anchor_text=policy.anchor_text,
                user_action=user_action_hint,
                session_context=session_context_hint,
                screen_evidence=vision_fact,
                relational_context=relational_context,
            )
        )
        semantic = self.semantic_repeat_guard.check(
            decision.text or "",
            recent_lines=self._recent_spoken_entries(limit=20),
        )
        if semantic.rejected:
            reasons.append(semantic.reason)

        if not reasons:
            return decision

        marker = "micro_line_policy=" + ",".join(reasons)
        relational_rewrite = self.micro_line_policy.rewrite_relational_line(
            decision.text or "",
            relational_context=relational_context,
            allowed_line_type=policy.allowed_line_type,
        )
        if relational_rewrite:
            rewrite_reasons = self.micro_line_policy.validate_text(
                allowed_line_type=policy.allowed_line_type,
                text=relational_rewrite,
                speech_risk_level=policy.risk_level,
                anchor_source=policy.anchor_source,
                anchor_text=policy.anchor_text,
                user_action=user_action_hint,
                session_context=session_context_hint,
                screen_evidence=vision_fact,
                relational_context=relational_context,
            )
            if not rewrite_reasons:
                return self._copy_decision_with_text(
                    decision,
                    text=relational_rewrite,
                    trace_marker=f"{marker}; relational_permission_rewrite",
                )
        replacement = ""
        silence_reasons = (
            "vietnamese_requires_diacritics",
            "micro_line_too_short_without_clear_meaning",
            "micro_observation_requires_anchor",
            "screen_observation_requires_anchor",
            "placeholder_text_blocked",
        )
        if channel == "force_speak" and any(reason in silence_reasons for reason in reasons):
            fallback = self._speech_core_safe_fallback_text(
                speech_core,
                repeated=semantic.rejected,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
            fallback_reasons = self.micro_line_policy.validate_text(
                allowed_line_type=policy.allowed_line_type,
                text=fallback,
                speech_risk_level=policy.risk_level,
                anchor_source=policy.anchor_source,
                anchor_text=policy.anchor_text,
                user_action=user_action_hint,
                session_context=session_context_hint,
                screen_evidence=vision_fact,
            )
            if fallback and not fallback_reasons:
                return self._copy_decision_with_text(
                    decision,
                    text=fallback,
                    trace_marker=f"{marker}; fallback_after_micro_policy",
                )
        if any(
            reason == "no_speech_blocks_final"
            or reason.startswith("micro_observation_not_grounded:")
            or reason.startswith("screen_observation_not_grounded:")
            or reason in silence_reasons
            for reason in reasons
        ):
            return self._copy_decision_with_text(
                decision,
                text="",
                trace_marker=marker,
                parse_mode="no_speech_policy",
            )
        if "curious_question_requires_question" in reasons:
            shaped = self._reshape_statement_as_question(decision.text or "")
            if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                replacement = shaped
            else:
                replacement = self._speech_core_safe_fallback_text(
                    speech_core,
                    repeated=semantic.rejected,
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
        elif "micro_observation_must_not_ask" in reasons or "tender_checkin_not_therapist" in reasons or semantic.rejected:
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                repeated=semantic.rejected,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        if not replacement:
            replacement = self._speech_core_safe_fallback_text(
                speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
        return self._copy_decision_with_text(decision, text=replacement, trace_marker=marker)

    def _apply_post_generation_filters(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        guard_mode = get_guard_mode()
        if guard_mode == OFF_GUARD_MODE:
            return decision
        if guard_mode == LOG_ONLY_GUARD_MODE:
            # LOG_ONLY đúng nghĩa: chỉ ghi rằng guard *sẽ* sửa, không sửa decision thật.
            # Tên mode mà vẫn mutate là một lời nguyền bé xinh của cấu hình runtime.
            try:
                probe = replace(decision)
                probe = self._apply_protocol_surface_guard(probe)
                probe = self._guard_recent_context_as_screen_observation(probe)
                probe = self._apply_memory_haunting_guard(probe)
                probe = self._apply_force_speak_no_evidence_topic_filter(
                    probe,
                    channel=channel,
                    speech_core=speech_core,
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
                if (probe.text != decision.text) or (probe.debug_trace != decision.debug_trace):
                    self.logger.info(
                        "[post_generation log-only] would_change text=%r -> %r trace=%s",
                        decision.text,
                        probe.text,
                        getattr(probe, "debug_trace", ""),
                    )
            except Exception as exc:
                self.logger.warning("[post_generation log-only] probe failed: %s", exc)
            return decision

        decision = self._apply_protocol_surface_guard(decision)
        decision = self._guard_recent_context_as_screen_observation(decision)
        decision = self._apply_memory_haunting_guard(decision)
        decision = self._apply_anti_mindreading_filter(
            decision,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_inner_thought_intent_alignment_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_force_speak_no_evidence_topic_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_internal_meaning_label_filter(
            decision,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_style_contract_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_micro_line_policy_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        return self._apply_repetition_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )

    def _apply_internal_meaning_label_filter(
        self,
        decision: Decision,
        *,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> Decision:
        if self._force_speak_banned_family_for_text(decision.text or "") != "internal_meaning_label":
            return decision
        replacement = self._speech_core_safe_fallback_text(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement:
            replacement = "hm. noi bang nhan noi bo nghe ky qua."
        return self._copy_decision_with_text(
            decision,
            text=replacement,
            trace_marker="internal_meaning_label_filter",
            parse_mode=decision.parse_mode,
        )
