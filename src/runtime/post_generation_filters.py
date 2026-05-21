from __future__ import annotations

import re

from cortex.contracts import AgentSpeechCore
from domain import Decision
from guard_config import LOG_ONLY_GUARD_MODE, OFF_GUARD_MODE, get_guard_mode
from runtime.fallback_policy import FALLBACK_BY_INTENT


class PostGenerationFiltersMixin:
    def _apply_chat_final_guards(self, decision: Decision, *, user_text: str) -> Decision:
        return decision

    def _copy_decision_with_text(
        self,
        decision: Decision,
        *,
        text: str,
        trace_marker: str,
        parse_mode: str | None = None,
    ) -> Decision:
        trace = decision.debug_trace or ""
        debug_trace = f"{trace} | {trace_marker}" if trace else trace_marker
        return Decision(
            text=text,
            animation=decision.animation or "stand",
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
        if any(reason == "no_speech_blocks_final" or reason.startswith("micro_observation_not_grounded:") or reason in silence_reasons for reason in reasons):
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
            return self._apply_force_speak_no_evidence_topic_filter(
                decision,
                channel=channel,
                speech_core=speech_core,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )

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


