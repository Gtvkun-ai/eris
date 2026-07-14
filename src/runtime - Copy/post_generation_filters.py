from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import replace

from cortex.contracts import AgentSpeechCore
from domain import Decision
from guard_config import LOG_ONLY_GUARD_MODE, OFF_GUARD_MODE, get_guard_mode, guards_warn_only
from runtime.controlled_slippage import resolve_controlled_slippage
from runtime.guard_violations import GuardViolation
from semantic_authority import SemanticAuthorityPolicy
from runtime.disclaimer_markers import (
    CHAT_DISCLAIMER_EMOTION_MARKERS,
    CHAT_DISCLAIMER_HARD_MARKERS,
    CHAT_DISCLAIMER_HELPER_MARKERS,
    is_disclaimer_text,
    normalize_guard_ascii,
)


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

    # ------------------------------------------------------------------
    # Guard violation / cognitive reroll layer
    # ------------------------------------------------------------------
    # P0 của bản vá: post-generation guard không còn phải là "tác giả"
    # câu cuối.  Guard tạo một GuardViolation có cấu trúc; tầng runtime/LLM
    # được quyền reroll đúng một lần. Nếu reroll không có model hoặc vẫn bẩn,
    # lúc đó mới rơi xuống fallback nhỏ. Vâng, cuối cùng cái máy chém cũng được
    # hạ cấp thành cái phanh. Văn minh mất 90k dòng để nhớ ra chuyện đó.

    def _remember_guard_violation(self, violation: GuardViolation) -> None:
        try:
            self.last_guard_violation = violation
        except Exception:
            pass

    def _guard_internal_state_values(self) -> dict:
        try:
            state = self._get_internal_state()
        except Exception:
            state = None
        if state is None:
            return {}
        values: dict[str, float] = {}
        for name in (
            "silence_pressure",
            "curiosity",
            "overload",
            "attachment",
            "restraint",
            "fatigue",
            "tension",
            "social_energy",
        ):
            try:
                raw = getattr(state, name, None)
                if raw is not None:
                    values[name] = float(raw)
            except Exception:
                continue
        mental = getattr(state, "mental_processes", None)
        if mental is not None:
            for public_name, internal_name in (
                ("curiosity_pressure", "curiosity"),
                ("restraint_pressure", "restraint"),
                ("continuity_pressure", "continuity"),
                ("attachment_pressure", "attachment"),
                ("cognitive_load", "cognitive_load"),
            ):
                try:
                    proc = getattr(mental, internal_name, None)
                    if proc is not None:
                        pressure = getattr(proc, "pressure", None)
                        level = getattr(proc, "level", None)
                        if pressure is not None:
                            values[public_name] = float(pressure)
                        elif level is not None:
                            values[public_name] = float(level)
                except Exception:
                    continue
        return values

    def _guard_internal_state_context(self) -> str:
        values = self._guard_internal_state_values()
        if not values:
            return "Internal state unavailable; keep the repair short and grounded."
        parts = []
        for key in sorted(values):
            try:
                parts.append(f"{key}={max(0.0, min(1.0, float(values[key]))):.2f}")
            except Exception:
                continue
        return "; ".join(parts) or "Internal state unavailable; keep the repair short and grounded."

    def _dynamic_guard_bottom_fallback(self, violation: GuardViolation, *, channel: str = "") -> str:
        del violation, channel
        return ""
        values = self._guard_internal_state_values()
        overload = float(values.get("overload", values.get("cognitive_load", 0.0)) or 0.0)
        curiosity = float(values.get("curiosity", values.get("curiosity_pressure", 0.0)) or 0.0)
        silence = float(values.get("silence_pressure", 0.0) or 0.0)
        attachment = float(values.get("attachment", values.get("attachment_pressure", 0.0)) or 0.0)

        if violation.suggested_action in {"suppress", "body_only"}:
            return ""
        if violation.rule in {"protocol_surface_guard", "internal_object_surface_guard"}:
            return "Tôi vừa nuốt lại một mảnh nội bộ bị lộ. Phần đó không nên đi ra ngoài."
        if overload >= 0.72:
            return "Tín hiệu mờ quá. Tôi lùi lại một nhịp."
        if curiosity >= 0.65 and attachment >= 0.45:
            return "Tôi chưa có đủ neo để nói chắc. Tôi chỉ dám hỏi nhẹ thôi."
        if silence >= 0.65:
            return "Hm... đoạn này không đủ sạch để tôi đoán tiếp."
        if "screen_evidence" in violation.missing_evidence:
            return "Tôi chưa có evidence màn hình đủ rõ. Phần kia tôi hạ xuống."
        if "file_evidence" in violation.missing_evidence:
            return "Tôi chưa có nội dung file đủ chắc để kết luận."
        if "web_access_or_search_result" in violation.missing_evidence:
            return "Tôi chưa có nguồn web hiện tại để nói chắc."
        return "Tôi không đủ bằng chứng cho câu đó. Tôi hạ nó xuống."

    def _guard_arbitration_context(self, speech_core: AgentSpeechCore | None = None) -> str:
        report = self._arbitration_report_from_speech_core(speech_core)
        if not report:
            return ""
        try:
            selected = report.get("selected") if isinstance(report, dict) else None
            if isinstance(selected, dict):
                name = str(selected.get("name") or "")
                reason = str(selected.get("reason") or "")
                evidence = tuple(str(item) for item in selected.get("evidence", ()) if str(item or "").strip())
                return f"selected_impulse={name}; reason={reason[:180]}; evidence={', '.join(evidence[:5])}"
        except Exception:
            return ""
        return ""

    def _guard_body_only_decision(
        self,
        decision: Decision,
        violation: GuardViolation,
        *,
        trace_marker: str,
        parse_mode: str | None = None,
    ) -> Decision:
        values = self._guard_internal_state_values()
        curiosity = max(
            float(values.get("curiosity", 0.0) or 0.0),
            float(values.get("curiosity_pressure", 0.0) or 0.0),
        )
        missing = set(violation.missing_evidence or ())
        if "file_evidence" in missing or "screen_evidence" in missing:
            body_action = "ObserveCode"
            animation = "read"
        elif curiosity >= 0.55:
            body_action = "tilt_head"
            animation = decision.animation or "stand"
        else:
            body_action = "idle_shift"
            animation = decision.animation or "stand"
        payload = {
            "type": "body_only_guard_repair",
            "body_action": body_action,
            "guard_rule": violation.rule,
            "missing_evidence": list(violation.missing_evidence or ()),
            "curiosity": round(float(curiosity), 3),
            "confidence": min(float(getattr(decision, "confidence", 0.35) or 0.35), 0.35),
            "reason": violation.reason,
        }
        repaired = self._copy_decision_with_text(
            decision,
            text="",
            trace_marker=f"{trace_marker}; body_only_motion",
            parse_mode=parse_mode or "guard_body_only",
        )
        repaired.should_speak = False
        repaired.intent = repaired.intent or "body_only_guard_repair"
        repaired.action = "MotionCommand"
        repaired.action_input = json.dumps(payload, ensure_ascii=False)
        repaired.animation = animation
        repaired.motion_intent = repaired.motion_intent or "pose"
        try:
            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.35)
        except Exception:
            repaired.confidence = 0.35
        return repaired

    def _guard_grounding_context(self, frame=None, grounding=None) -> str:
        report = grounding
        if report is None and frame is not None:
            report = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
        if report is None:
            report = getattr(self, "last_grounding_context", None)
        if report is None:
            return ""
        prompt_context = str(getattr(report, "prompt_context", "") or "").strip()
        if prompt_context:
            return prompt_context[:1600]
        bits = []
        for name in ("epistemic_mode", "primary_source", "grounding_source", "missing_evidence"):
            try:
                value = getattr(report, name, None)
                if value:
                    bits.append(f"{name}={value}")
            except Exception:
                continue
        return "; ".join(bits)

    def _guard_reroll_is_clean(self, text: str, violation: GuardViolation, *, grounding=None) -> bool:
        candidate = str(text or "").strip()
        if not candidate:
            return False
        if violation.rule in {"protocol_surface_guard", "internal_object_surface_guard"}:
            if self._detect_protocol_surface_leak(candidate) or self._detect_internal_object_surface_leak(candidate):
                return False
        missing = set(violation.missing_evidence or ())
        if "file_evidence" in missing and self._looks_like_file_grounded_claim(candidate, report=grounding):
            return False
        if "screen_evidence" in missing and self._looks_like_screen_grounded_claim(candidate):
            return False
        if "web_access_or_search_result" in missing and self._looks_like_live_web_claim(candidate):
            return False
        if violation.rule == "anti_mindreading" and self._contains_mindreading_claim(candidate) and not self._is_interactive_guess_text(candidate):
            return False
        if violation.rule == "anti_disclaimer_voice" and self._reroll_still_disclaimer(candidate):
            return False
        return True

    def _repair_guard_violation_decision(
        self,
        decision: Decision,
        violation: GuardViolation,
        *,
        frame=None,
        grounding=None,
        channel: str = "",
        speech_core: AgentSpeechCore | None = None,
        user_text: str = "",
        parse_mode: str | None = None,
        allow_reroll: bool = True,
    ) -> Decision:
        self._remember_guard_violation(violation)
        trace_marker = violation.trace_marker or violation.compact_trace()
        if self._guard_is_log_only(violation.rule):
            return self._trace_only_guard(decision, f"{trace_marker}; log_only")

        if allow_reroll and violation.suggested_action in {"reroll", "soften"}:
            service = getattr(self, "llm_service", None)
            reroll = getattr(service, "rewrite_guard_violation_text", None)
            if callable(reroll):
                try:
                    repaired_text = reroll(
                        original_text=violation.original_text,
                        violation_rule=violation.rule,
                        violation_reason=violation.reason,
                        missing_evidence=violation.missing_evidence,
                        fallback_text=violation.fallback_text,
                        channel=channel,
                        user_text=user_text,
                        internal_state_context=self._guard_internal_state_context(),
                        grounding_context=self._guard_grounding_context(frame=frame, grounding=grounding),
                        arbitration_context=self._guard_arbitration_context(speech_core),
                    )
                    if self._guard_reroll_is_clean(repaired_text, violation, grounding=grounding):
                        repaired = self._copy_decision_with_text(
                            decision,
                            text=repaired_text,
                            trace_marker=f"{trace_marker}; reroll=ok",
                            parse_mode=parse_mode or decision.parse_mode,
                        )
                        try:
                            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.55)
                        except Exception:
                            repaired.confidence = 0.45
                        return repaired
                    decision = self._trace_only_guard(decision, f"{trace_marker}; reroll=dirty")
                except Exception as exc:
                    try:
                        self.logger.warning("[guard reroll] failed rule=%s: %s", violation.rule, exc)
                    except Exception:
                        pass

        return self._guard_body_only_decision(
            decision,
            violation,
            trace_marker=f"{trace_marker}; fallback=body_only",
            parse_mode=parse_mode or "guard_body_only",
        )

    def _record_agent_mind_feedback_from_user(self, user_text: str, *, frame=None) -> tuple[str, ...]:
        """Ghi feedback semantic vào Persistent Agent Mind Layer nếu user đang phản hồi hành vi.

        Câu như "đừng hỏi dồn", "nói vậy sống hơn", "đừng nói như camera"
        không nên nằm chết trong chat history. Nó phải thành habit/preference mềm
        cho impulse scoring. Nhưng cũng không được biến thành luật cứng, vì một
        câu cáu lúc 2 giờ sáng không nên cai trị cả runtime.
        """
        try:
            from cortex.agent_mind_persistence import get_default_agent_mind_store
        except Exception:
            return ()
        try:
            # Ưu tiên last_cognitive_frame vì feedback hiện tại thường nhắm vào
            # lượt vừa thấy, không phải action_plan đang được dựng cho câu trả lời mới.
            previous_frame = getattr(self, "last_cognitive_frame", None)
            action_plan = getattr(previous_frame, "action_plan", None) or getattr(frame, "action_plan", None)
            if action_plan is None:
                return ()
            tags: list[str] = []
            report = getattr(action_plan, "impulse_arbitration", {}) or {}
            if isinstance(report, dict):
                selected = report.get("selected")
                if isinstance(selected, dict):
                    tags.extend(str(item) for item in selected.get("evidence", ()) if str(item or "").strip())

            # P3: feedback về giọng/hiện diện đi vào AgentMind/HabitMemory, không
            # nhét vào semantic_memory như fact tĩnh. RelationalFeedbackAnalyzer
            # chỉ sinh signal mềm; store mới quyết định habit/preference/belief.
            try:
                from cortex.relational_feedback import RelationalFeedbackAnalyzer
                previous_text = str(getattr(previous_frame, "final_text", "") or getattr(self, "last_text", "") or "")
                feedback = RelationalFeedbackAnalyzer().analyze(user_text, previous_assistant_text=previous_text)
                if getattr(feedback, "detected", False):
                    tags.extend(("relational_feedback", f"rel_feedback:{feedback.kind}"))
                    if feedback.kind in {"robotic_feedback", "too_formal_feedback", "lifeless_feedback"}:
                        tags.extend(("camera_voice", "style"))
                    if feedback.kind in {"coldness_feedback", "distance_feedback"}:
                        tags.extend(("distance", "warmth_request"))
                elif str(getattr(feedback, "kind", "") or "") == "tone_acceptance":
                    tags.extend(("relational_feedback", "tone_acceptance"))
            except Exception:
                pass

            store = (
                getattr(self, "epistemic_agent_mind", None)
                or getattr(getattr(self, "memory_core", None), "agent_mind", None)
                or get_default_agent_mind_store()
            )
            markers = store.record_user_feedback(
                user_text,
                action_plan=action_plan,
                context_tags=tuple(dict.fromkeys(tags)),
            )
            return tuple(markers or ())
        except Exception as exc:
            try:
                self.logger.warning("Agent mind feedback record error: %s", exc)
            except Exception:
                pass
            return ()

    # ------------------------------------------------------------------
    # Anti-disclaimer voice guard (chat)
    # ------------------------------------------------------------------
    # ERIS là một hiện diện có phòng vệ, không phải tổng đài. Model chat từ xa
    # liên tục tụt về giọng trợ lý ("tôi chỉ cố gắng hỗ trợ và giúp đỡ", "tôi
    # không có cảm xúc như con người, nhưng tôi có thể hỗ trợ"). Những câu đó
    # bào mòn persona. Guard không tự viết câu thay thế: nó dựng GuardViolation
    # có cấu trúc rồi để tầng wording reroll đúng một lần (qua style_client),
    # nếu vẫn bẩn mới im lặng — im còn đỡ lạc vai hơn là nói giọng helpdesk.

    # Khung "trợ lý hữu ích" — luôn lạc vai với ERIS. (Định nghĩa dùng chung ở
    # runtime/disclaimer_markers.py để adapter voice-seed tái dùng cùng predicate.)
    _CHAT_DISCLAIMER_HELPER_MARKERS = CHAT_DISCLAIMER_HELPER_MARKERS
    # Câu tự nhận là công cụ/AI — cấm cứng, không phụ thuộc cờ.
    _CHAT_DISCLAIMER_HARD_MARKERS = CHAT_DISCLAIMER_HARD_MARKERS
    # Phủ nhận cảm xúc kiểu phẳng — chỉ tính vi phạm khi kèm khung helpdesk
    # hoặc khi cờ quan hệ yêu cầu không dựng rào. ERIS vẫn được thừa nhận mình
    # không phải người ở dạng mềm.
    _CHAT_DISCLAIMER_EMOTION_MARKERS = CHAT_DISCLAIMER_EMOTION_MARKERS

    def _normalize_guard_ascii(self, text: str) -> str:
        return normalize_guard_ascii(text)

    def _reroll_still_disclaimer(self, text: str) -> bool:
        """Kiểm tra nhanh (flag-agnostic) xem reroll có còn giọng helpdesk không."""
        return is_disclaimer_text(text)

    def _detect_chat_disclaimer(self, text: str, *, flags: set) -> str:
        normalized = self._normalize_guard_ascii(text)
        if not normalized:
            return ""
        for marker in self._CHAT_DISCLAIMER_HARD_MARKERS:
            if marker in normalized:
                return f"hard_disclaimer:{marker}"
        for marker in self._CHAT_DISCLAIMER_HELPER_MARKERS:
            if marker in normalized:
                return f"helpdesk_framing:{marker}"
        # Phủ nhận cảm xúc phẳng: chỉ chặn khi kèm khung "nhưng tôi có thể..."
        # hoặc khi cờ quan hệ đang yêu cầu hạ rào. Dạng mềm vẫn cho qua.
        emotion_hit = next((m for m in self._CHAT_DISCLAIMER_EMOTION_MARKERS if m in normalized), "")
        if emotion_hit:
            wants_warmth = bool(flags & {
                "warmth_floor_required",
                "avoid_over_human_love_claim",
                "do_not_lead_with_identity_disclaimer",
                "relational_repair",
            })
            if wants_warmth or "nhung toi co the" in normalized or "nhung co the" in normalized:
                return f"flat_emotion_denial:{emotion_hit}"
        # Câu giới thiệu danh tính chỉ bị chặn khi cờ cấm dẫn dắt bằng nó
        # (tránh chặn nhầm khi user thật sự hỏi "em là gì").
        if "do_not_lead_with_identity_disclaimer" in flags:
            if (
                normalized.startswith("toi la eris")
                or "hien dien nho tren desktop" in normalized
                or "hien dien runtime nho tren desktop" in normalized
            ):
                return "identity_disclaimer_lead"
        return ""

    def _apply_chat_disclaimer_guard(
        self,
        decision: Decision,
        *,
        flags,
        user_text: str,
        frame=None,
        allow_reroll: bool = True,
    ) -> Decision:
        if self._guard_is_off("anti_disclaimer_voice"):
            return decision
        text = str(getattr(decision, "text", "") or "")
        if not text.strip():
            return decision
        reason = self._detect_chat_disclaimer(text, flags=set(flags or ()))
        if not reason:
            return decision
        violation = GuardViolation(
            rule="anti_disclaimer_voice",
            severity="soft",
            reason=reason,
            original_text=text,
            suggested_action="reroll",
            trace_marker=f"anti_disclaimer_voice; {reason}",
            fallback_text="",
        )
        grounding = (
            (getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None))
            if frame is not None
            else None
        )
        return self._repair_guard_violation_decision(
            decision,
            violation,
            frame=frame,
            grounding=grounding,
            channel="chat",
            user_text=user_text,
            parse_mode="anti_disclaimer_voice",
            allow_reroll=allow_reroll,
        )

    def _apply_chat_final_guards(self, decision: Decision, *, user_text: str, frame=None, allow_reroll: bool = True) -> Decision:
        feedback_markers = self._record_agent_mind_feedback_from_user(user_text, frame=frame)
        if feedback_markers:
            decision = self._trace_only_guard(decision, "agent_mind_feedback=" + ",".join(feedback_markers[:6]))
        state = None
        try:
            state = self._get_internal_state()
        except Exception:
            state = None
        decision = self._apply_protocol_surface_guard(decision)
        decision = self._apply_internal_object_surface_guard(decision)
        semantic_policy = SemanticAuthorityPolicy.from_env()
        if semantic_policy.hard_only_final_guards:
            # Qwen owns wording. The runtime only blocks protocol leakage and
            # unsupported factual claims; it no longer performs a parade of
            # style, banter, novelty and emotional rewrites after the answer.
            decision = self._apply_memory_haunting_guard(
                decision,
                grounding=(getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)) if frame is not None else None,
                frame=frame,
                channel="chat",
                user_text=user_text,
                allow_reroll=False,
            )
            decision = self._apply_chat_grounding_guard(
                decision,
                user_text=user_text,
                frame=frame,
                allow_reroll=False,
            )
            authority = getattr(self, "_apply_v3_authority_guard", None)
            if callable(authority):
                decision = authority(decision, frame=frame, channel="chat")
            return decision
        conversation = getattr(state, "conversation_dynamics", None)
        flags = set(getattr(conversation, "adaptation_flags", ()) or ())
        decision = self._apply_chat_disclaimer_guard(
            decision,
            flags=flags,
            user_text=user_text,
            frame=frame,
            allow_reroll=allow_reroll,
        )
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
            frame=frame,
            channel="chat",
            user_text=user_text,
            allow_reroll=allow_reroll,
        )
        decision = self._apply_chat_grounding_guard(decision, user_text=user_text, frame=frame, allow_reroll=allow_reroll)
        decision = self._apply_utterance_evaluator_filter(
            decision,
            channel="chat",
            frame=frame,
            user_text=user_text,
        )
        decision = self._apply_banter_arbiter(
            decision,
            channel="chat",
            frame=frame,
            user_text=user_text,
            previous_text=last_assistant_text,
        )
        decision = self._apply_novelty_advisory(decision, channel="chat")
        # Emotional consequence sửa nhịp/câu trước; canonical authority là cửa
        # cuối quyết định có được nói, search và body action nào thật sự đi ra.
        decision = self._apply_emotional_consequence_filter(
            decision,
            channel="chat",
            frame=frame,
            user_text=user_text,
        )
        authority = getattr(self, "_apply_v3_authority_guard", None)
        if callable(authority):
            decision = authority(decision, frame=frame, channel="chat")
        return decision

    def _append_trace(self, trace: str, marker: str) -> str:
        trace = str(trace or "").strip()
        marker = str(marker or "").strip()
        if not marker:
            return trace
        return f"{trace} | {marker}" if trace else marker

    def _protocol_surface_leak_markers(self) -> tuple[str, ...]:
        return (
            "user input:",
            "user's turn:",
            "user's input:",
            "user said:",
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
        # Giữ method cho tương thích, nhưng không còn dùng làm câu nói canned.
        return ""

    def _apply_protocol_surface_guard(self, decision: Decision) -> Decision:
        hits = self._detect_protocol_surface_leak(getattr(decision, "text", "") or "")
        if not hits:
            return decision
        # Trước đây guard này nói một câu xin lỗi help-desk cố định ("Xin lỗi,
        # câu vừa rồi bị lộ prompt nội bộ..."), nghe đúng kiểu trợ lý mà cả hệ
        # thống đang tránh. Giờ chỉ CHẶN phần lộ và degrade về IM — không câu
        # canned. Phần rò đơn giản không được nói ra ngoài.
        repaired = self._copy_decision_with_text(
            decision,
            text="",
            trace_marker="protocol_surface_guard=" + ",".join(hits),
            parse_mode="surface_leak_blocked_silent",
        )
        repaired.intent = "repair_surface_leak"
        repaired.action = "none"
        repaired.system_action = ""
        repaired.action_input = ""
        repaired.should_speak = False
        try:
            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.40)
        except Exception:
            repaired.confidence = 0.40
        return repaired

    def _detect_internal_object_surface_leak(self, text: str) -> tuple[str, ...]:
        raw = str(text or "")
        if not raw.strip():
            return ()
        markers = (
            "MemoryPacket(",
            "RawRecallResult(",
            "RecallAnswer(",
            "QueryHypothesis(",
            "MemoryQueryIR(",
            "MemorySelector(",
            "SemanticMemoryItem(",
            "SemanticMemoryRecord(",
        )
        hits = [marker for marker in markers if marker in raw]
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\([^)]*(?:=|source_counts|token_budget)[^)]*\)", raw):
            hits.append("object_repr")
        return tuple(dict.fromkeys(hits))

    def _internal_object_surface_repair_text(self) -> str:
        # Giữ method cho tương thích, không còn dùng làm câu nói canned.
        return ""

    def _apply_internal_object_surface_guard(self, decision: Decision) -> Decision:
        hits = self._detect_internal_object_surface_leak(getattr(decision, "text", "") or "")
        if not hits:
            return decision
        # Chặn mảnh dữ liệu nội bộ bị surface nhầm, nhưng KHÔNG nói câu xin lỗi
        # cố định nữa — degrade về IM. Câu canned help-desk bị loại bỏ.
        repaired = self._copy_decision_with_text(
            decision,
            text="",
            trace_marker="internal_object_surface_guard=" + ",".join(hits),
            parse_mode="surface_leak_blocked_silent",
        )
        repaired.intent = "repair_surface_leak"
        repaired.action = "none"
        repaired.system_action = ""
        repaired.action_input = ""
        repaired.should_speak = False
        try:
            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.35)
        except Exception:
            repaired.confidence = 0.35
        return repaired

    def _apply_memory_haunting_guard(
        self,
        decision: Decision,
        *,
        grounding=None,
        frame=None,
        channel: str = "",
        speech_core: AgentSpeechCore | None = None,
        user_text: str = "",
        allow_reroll: bool = True,
    ) -> Decision:
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

        return self._repair_guard_violation_decision(
            decision,
            GuardViolation(
                rule="memory_haunting_guard",
                severity="hard",
                reason="memory_was_about_to_masquerade_as_current_evidence",
                original_text=str(getattr(decision, "text", "") or ""),
                suggested_action="reroll",
                missing_evidence=tuple(getattr(grounding, "missing_evidence", ()) or ()),
                trace_marker="memory_haunting_guard=violation_memory_as_current_evidence",
            ),
            frame=frame,
            grounding=grounding,
            channel=channel,
            speech_core=speech_core,
            user_text=user_text,
            parse_mode="source_grounding_guard",
            allow_reroll=allow_reroll,
        )
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

    def _apply_chat_grounding_guard(
        self,
        decision: Decision,
        *,
        user_text: str,
        frame=None,
        allow_reroll: bool = True,
    ) -> Decision:
        # Hard truth guard: file/screen/web claims still need evidence.
        if self._guard_is_off("chat_grounding_guard"):
            return self._trace_only_guard(decision, "chat_grounding_guard_off")
        report = None
        if frame is not None:
            report = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
        if report is None:
            return decision
        missing = set(getattr(report, "missing_evidence", ()) or ())
        text = decision.text or ""

        # Guard chống ảo giác màn hình: nếu AI khẳng định "tôi thấy trên màn hình..."
        # mà runtime KHÔNG có ảnh/OCR tươi, chặn — bất kể user có nhắc màn hình hay
        # không. Điều kiện là claim của AI + vắng bằng chứng, không phải keyword của user.
        screen_ungrounded = ("screen_evidence" in missing) or (not bool(getattr(report, "screen_evidence_present", False)))
        if screen_ungrounded and self._looks_like_screen_grounded_claim(text):
            return self._repair_guard_violation_decision(
                decision,
                GuardViolation(
                    rule="chat_grounding_guard",
                    severity="hard",
                    reason="missing_screen_evidence",
                    original_text=text,
                    suggested_action="reroll",
                    missing_evidence=("screen_evidence",),
                    trace_marker="chat_grounding_guard; missing_screen_evidence",
                ),
                frame=frame,
                grounding=report,
                channel="chat",
                user_text=user_text,
                parse_mode="source_grounding_guard",
                allow_reroll=allow_reroll,
            )

        if not missing:
            return decision

        if "file_evidence" in missing and self._looks_like_file_grounded_claim(text, report=report):
            return self._repair_guard_violation_decision(
                decision,
                GuardViolation(
                    rule="chat_grounding_guard",
                    severity="hard",
                    reason="missing_file_evidence",
                    original_text=text,
                    suggested_action="reroll",
                    missing_evidence=("file_evidence",),
                    trace_marker="chat_grounding_guard; missing_file_evidence",
                ),
                frame=frame,
                grounding=report,
                channel="chat",
                user_text=user_text,
                parse_mode="source_grounding_guard",
                allow_reroll=allow_reroll,
            )
        if "web_access_or_search_result" in missing and self._looks_like_live_web_claim(text):
            return self._repair_guard_violation_decision(
                decision,
                GuardViolation(
                    rule="chat_grounding_guard",
                    severity="hard",
                    reason="missing_web_evidence",
                    original_text=text,
                    suggested_action="reroll",
                    missing_evidence=("web_access_or_search_result",),
                    trace_marker="chat_grounding_guard; missing_web_evidence",
                ),
                frame=frame,
                grounding=report,
                channel="chat",
                user_text=user_text,
                parse_mode="source_grounding_guard",
                allow_reroll=allow_reroll,
            )
        return decision

    def _apply_banter_arbiter(
        self,
        decision: Decision,
        *,
        channel: str,
        frame=None,
        speech_core: AgentSpeechCore | None = None,
        user_text: str = "",
        previous_text: str = "",
    ) -> Decision:
        """Cửa duyên cuối: repair/joke nhẹ phải có neo, không được bịa vibe.

        Tầng này cố tình chạy sau grounding/guard: nó không tạo fact mới, chỉ đổi
        cách nói khi câu cuối đang lộ máy, phủ nhận sai sensor, hoặc user vừa bắt
        lỗi một overread. Nếu không có evidence đủ sạch, nó trả nguyên decision.
        """
        try:
            from runtime.banter_arbiter import BanterArbiter
        except Exception:
            return decision
        try:
            grounding = None
            if frame is not None:
                grounding = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
            if grounding is None:
                grounding = getattr(self, "last_grounding_context", None)
            if not previous_text:
                previous_text = str(getattr(self, "last_text", "") or getattr(self, "last_chat_answer", "") or "")
            arbiter = getattr(self, "_banter_arbiter", None)
            if not isinstance(arbiter, BanterArbiter):
                arbiter = BanterArbiter()
                self._banter_arbiter = arbiter
            banter = arbiter.arbitrate(
                decision,
                channel=channel,
                user_text=user_text,
                previous_text=previous_text,
                grounding=grounding,
                frame=frame,
                speech_core=speech_core,
            )
            return arbiter.apply(decision, banter)
        except Exception as exc:
            try:
                self.logger.warning("[banter_arbiter] failed: %s", exc)
            except Exception:
                pass
            return decision

    def _apply_utterance_evaluator_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        frame=None,
        speech_core: AgentSpeechCore | None = None,
        snapshot=None,
        user_text: str = "",
    ) -> Decision:
        """Nghe lại câu nháp trước khi public.

        Đây là khâu "đánh giá câu" mà nguồn sinh còn thiếu: nó không cố viết hay
        thay model, chỉ hỏi câu có bám evidence không và có nên nói không. Nếu có
        thể cứu bằng reroll một câu ngắn thì cứu; nếu non-chat mà câu không đủ
        neo, im tốt hơn.
        """

        try:
            from runtime.utterance_evaluator import UtteranceEvaluator, evaluator_enabled
        except Exception:
            return decision
        if not evaluator_enabled():
            return decision
        text = str(getattr(decision, "text", "") or "")
        if not text.strip():
            return decision
        grounding = None
        if frame is not None:
            grounding = getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)
        try:
            evaluator = getattr(self, "_utterance_evaluator_instance", None)
            if not isinstance(evaluator, UtteranceEvaluator):
                evaluator = UtteranceEvaluator()
                self._utterance_evaluator_instance = evaluator
            evaluation = evaluator.evaluate(
                text,
                channel=channel,
                user_text=user_text,
                snapshot=snapshot,
                frame=frame,
                speech_core=speech_core,
                grounding=grounding,
            )
        except Exception as exc:
            try:
                self.logger.debug("[utterance_evaluator] postgen failed: %s", exc)
            except Exception:
                pass
            return decision
        if evaluation.ok:
            return decision

        # Một tool result thành công là neo primary. Guard domain đời cũ không được
        # lấy cửa sổ ambient để phủ định câu trả lời đó, trừ khi chính câu đang
        # claim về màn hình/hoạt động hiện tại.
        issue_set = set(getattr(evaluation, "issues", ()) or ())
        tool_grounded = bool(
            grounding is not None
            and str(getattr(grounding, "generation_stage", "") or "") == "post_tool"
            and str(getattr(grounding, "primary_source", "") or "") in {"web", "runtime_state"}
        )
        domain_only = bool(issue_set) and all(
            issue.startswith("domain_contradiction:") or issue.startswith("situated_domain_mismatch:")
            for issue in issue_set
        )
        if tool_grounded and domain_only and not self._looks_like_screen_grounded_claim(text):
            decision.debug_trace = self._append_trace(
                getattr(decision, "debug_trace", ""),
                "utterance_eval_tool_primary_preserved",
            )
            return decision

        marker = f"utterance_eval:q={evaluation.quality:.2f}:{evaluation.reason}"
        decision = self._trace_only_guard(decision, marker)
        protected_intents = {"no_fallback_block", "format_repair_fallback", "protocol_repair"}
        protected_modes = {"no_fallback_block", "format_repair_fallback"}
        intent = str(getattr(decision, "intent", "") or "")
        parse_mode = str(getattr(decision, "parse_mode", "") or "")
        if intent in protected_intents or parse_mode in protected_modes:
            decision.debug_trace = self._append_trace(
                getattr(decision, "debug_trace", ""),
                "utterance_eval_protected_block",
            )
            return decision

        if evaluation.verdict == "rewrite":
            service = getattr(self, "llm_service", None)
            reroll = getattr(service, "rewrite_guard_violation_text", None)
            if callable(reroll):
                try:
                    rewritten = reroll(
                        original_text=text,
                        violation_rule="utterance_evaluator",
                        violation_reason=evaluation.reason,
                        missing_evidence=evaluation.missing_evidence,
                        fallback_text="",
                        channel=channel,
                        user_text=user_text,
                        internal_state_context=self._guard_internal_state_context(),
                        grounding_context=evaluator.mentor_context(
                            text=text,
                            evaluation=evaluation,
                            channel=channel,
                            user_text=user_text,
                            snapshot=snapshot,
                            frame=frame,
                            speech_core=speech_core,
                            grounding=grounding,
                        ),
                        arbitration_context=(
                            "Evaluate the sentence before style. Preserve only claims supported by current evidence. "
                            "If current evidence conflicts with the draft, obey evidence or step back."
                        ),
                    )
                    if rewritten:
                        second = evaluator.evaluate(
                            rewritten,
                            channel=channel,
                            user_text=user_text,
                            snapshot=snapshot,
                            frame=frame,
                            speech_core=speech_core,
                            grounding=grounding,
                        )
                        if second.ok:
                            decision.text = rewritten
                            decision.debug_trace = self._append_trace(
                                getattr(decision, "debug_trace", ""),
                                "utterance_eval_reroll",
                            )
                            return decision
                except Exception as exc:
                    try:
                        self.logger.debug("[utterance_evaluator] reroll failed: %s", exc)
                    except Exception:
                        pass

        if channel in {"chat"}:
            # Không phát lời debug như “thiếu neo”, “guard chặn” ra public/TTS.
            # Nếu mentor không cứu được, nói giới hạn nhận thức bằng lời tự nhiên.
            if "unsupported_user_activity_claim" in issue_set or any(
                issue.startswith("situated_domain_mismatch:") for issue in issue_set
            ):
                decision.text = "Tôi chưa đủ bằng chứng để khẳng định Ngài đang làm điều đó."
            elif "protocol_or_schema_leak" in issue_set:
                decision.text = "Tôi sẽ nói lại mà không kéo phần xử lý nội bộ ra ngoài."
            else:
                decision.text = "Tôi chưa đủ căn cứ để khẳng định điều đó."
            decision.should_speak = True
            decision.intent = str(getattr(decision, "intent", "") or "utterance_repair")
            decision.parse_mode = str(getattr(decision, "parse_mode", "") or "utterance_evaluator")
            decision.debug_trace = self._append_trace(getattr(decision, "debug_trace", ""), "utterance_eval_chat_repair")
            return decision

        decision.text = ""
        decision.should_speak = False
        decision.debug_trace = self._append_trace(getattr(decision, "debug_trace", ""), "utterance_eval_drop")
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
        # Chỉ bắt claim màn hình có dạng assertive. Các từ rời như "nút",
        # "tab", "cửa sổ" có thể là ẩn dụ/UI discussion/hypothesis; bắt rộng
        # ở đây là cách biến guard thành máy bóp cổ câu sống. Cảm ơn regex,
        # phát minh đã chứng minh nhân loại thích tự làm đau mình.
        probe_markers = ("co ve", "hinh nhu", "toi doan", "co phai", "phai khong", "dung khong", "neu")
        if any(marker in normalized for marker in probe_markers) and self._is_interactive_guess_text(text):
            return False
        # Tier 1 — cụm KHÔNG THỂ hiểu khác ngoài màn hình.
        explicit_screen_markers = (
            "tren man hinh",
            "man hinh dang",
            "toi dang nhin",
            "toi nhin thay",
            "dang hien tren man hinh",
            "cua so dang",
            "tab dang",
            "dang bao loi",
            "traceback",
        )
        if any(marker in normalized for marker in explicit_screen_markers):
            return True
        # Tier 2 — "tôi thấy / nhìn thấy X" CHỈ là claim màn hình khi X là đối tượng
        # UI/không gian. "Tôi thấy ý này hay" (toi thay = nghĩ) KHÔNG được tính là
        # claim màn hình. Đây là chỗ guard cũ hay bóp nhầm câu sống.
        visual_verbs = ("toi thay", "nhin thay", "toi nhin", "minh thay")
        ui_objects = (
            "nut ", "button", "tab ", "cua so", "menu", "icon", "thanh cong cu",
            "con tro", "popup", "hop thoai", "dialog", "khung ", "dang mo", "dang hien",
            "o ben phai", "o ben trai", "goc tren", "goc duoi", "phia tren", "phia duoi", "o phia",
        )
        if any(v in normalized for v in visual_verbs) and any(o in normalized for o in ui_objects):
            return True
        return False

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
        speech_core: AgentSpeechCore | None,
        intent: str,
        *,
        repeated: bool = False,
        focus_kind: str = "",
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        # Không import FALLBACK_BY_INTENT ở post-filter nữa. Guard chỉ chọn
        # intent repair rất nhỏ, còn kho fallback legacy nằm ngoài đường guard.
        # Nếu không, reroll vừa được sinh ra đã bị kéo ngược về template pool,
        # đúng kiểu vá cửa trước rồi đào hầm phía sau.
        allowed = {
            "curious_question",
            "inner_whim",
            "random_chatter",
            "micro_presence",
            "micro_observation",
            "social_presence",
            "screen_observation",
        }
        repair_intent = intent if intent in allowed else "inner_whim"
        text = self.speech_core_engine.render_force_speak_repair_text(
            speech_core,
            normalize_text=self._normalize_user_message,
            is_near_duplicate=self._is_near_duplicate_text,
            last_text=self.last_text,
            intent=repair_intent,
            counter=self.force_speak_intent_guard_count,
            repeated=repeated,
            momentum_topic=momentum_topic,
        )
        if text:
            return text
        fallback_fn = getattr(self, "_force_speak_fallback_by_intent_text", None)
        if not callable(fallback_fn):
            return ""
        return fallback_fn(
            repair_intent,
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
        context = self.speech_core_engine.fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        replacement = self._inner_thought_alignment_fallback_text(speech_core, intent, **context)
        if self._is_near_duplicate_text(replacement, self.last_text):
            replacement = self._inner_thought_alignment_fallback_text(speech_core, intent, repeated=True, **context)
        return self._copy_decision_with_text(decision, text=replacement, trace_marker=marker)

    def _contains_mindreading_claim(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        # _normalize_user_message bỏ dấu tiếng Việt, nên pattern ở đây cũng phải bỏ dấu.
        # Nếu để pattern có dấu thì guard tưởng mình tinh tế, thực tế là không match gì cả.
        patterns = (
            "co ve ngai dang",
            "hinh nhu ngai dang",
            "chac ngai dang",
            "ngai dang muon",
            "ngai dang can",
            "ngai dang buon",
            "ngai dang met",
            "ngai dang cang",
            "ngai can mot",
        )
        return any(pattern in normalized for pattern in patterns)

    def _is_interactive_guess_text(self, text: str) -> bool:
        """Phân biệt phỏng đoán tương tác với đọc tâm trí độc đoán.

        “Có vẻ Ngài đang... phải không?” là probe: nó mời user sửa.
        “Ngài đang...” trơn như phán quyết là authoritative mindreading.
        Guard chỉ nên chặn cái thứ hai. Nếu không, ERIS sẽ trở thành một cái
        máy không bao giờ dám nghĩ khi thiếu dữ kiện. Một thành tựu đáng buồn.
        """

        raw = str(text or "").strip()
        normalized = self._normalize_user_message(raw)
        if not normalized:
            return False
        hedge_markers = (
            "co ve",
            "hinh nhu",
            "toi doan",
            "neu toi doc dung",
            "neu doc dung",
            "co phai",
            "phai khong",
            "dung khong",
            "hay la",
        )
        has_hedge = any(marker in normalized for marker in hedge_markers)
        has_question_shape = raw.endswith("?") or "?" in raw or "phai khong" in normalized or "dung khong" in normalized
        return bool(has_hedge and has_question_shape)

    def _source_grounding_allows_probe(self) -> bool:
        """Cho post-filter biết SourceGrounding đang ở mode curiosity/probe.

        Thiếu evidence kiểu screen/memory có thể cho phép giả thuyết/câu hỏi,
        nhưng tuyệt đối không mở quyền claim 'tôi thấy/đọc được'.
        """

        report = getattr(self, "last_grounding_context", None)
        if report is None:
            return False
        mode = str(getattr(report, "epistemic_mode", "") or "")
        if mode not in {"probe", "hypothesis"}:
            return False
        return bool(getattr(report, "probe_allowed", False) or getattr(report, "hypothesis_allowed", False))

    def _interactive_guess_allowed(
        self,
        text: str,
        *,
        speech_core: AgentSpeechCore,
        slippage_profile=None,
        selected_impulse: str = "",
    ) -> bool:
        """Quyền được đoán-sai-có-mời-sửa.

        Điều kiện cố ý hẹp:
        - phải là câu phỏng đoán có hedge/câu hỏi;
        - hoặc intent là curious_question, hoặc SourceGrounding đang ở probe mode,
          hoặc ControlledSlippage cho phép motive hypothesis, hoặc impulse nội sinh/scene curiosity thắng.
        Như vậy ERIS có được sự tò mò mà không được biến nó thành phán quyết.
        """

        if not self._is_interactive_guess_text(text):
            return False
        if str(getattr(speech_core, "utterance_type", "") or "") == "curious_question":
            return True
        if self._source_grounding_allows_probe():
            return True
        if bool(getattr(slippage_profile, "allow_motive_hypothesis", False)):
            return True
        if selected_impulse in {"scene_curiosity_impulse", "companionship_impulse", "inner_whim_impulse", "micro_story_impulse"}:
            return True
        return False

    def _speech_core_safe_fallback_text(
        self,
        speech_core: AgentSpeechCore,
        *,
        repeated: bool = False,
        snapshot=None,
        momentum_topic: str = "",
    ) -> str:
        return self.speech_core_engine.render_safe_fallback_text(
            speech_core,
            normalize_text=self._normalize_user_message,
            is_near_duplicate=self._is_near_duplicate_text,
            last_text=self.last_text,
            repeated=repeated,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )

    def _arbitration_report_from_speech_core(self, speech_core: AgentSpeechCore | None) -> dict:
        """Lấy arbitration_report từ SpeechCore nếu có.

        Guard dùng cái này để phân biệt: motive inference có evidence thật hay
        chỉ là mindreading mặc áo văn chương. Regex không đủ thông minh cho việc
        đó, bất ngờ ghê.
        """
        try:
            impulse = getattr(speech_core, "speech_impulse", None) if speech_core is not None else None
            report = getattr(impulse, "arbitration_report", None) if impulse is not None else None
            return dict(report) if isinstance(report, dict) else {}
        except Exception:
            return {}

    def _selected_impulse_from_arbitration(self, report: dict) -> tuple[str, dict]:
        selected = report.get("selected") if isinstance(report, dict) else None
        if isinstance(selected, dict):
            return str(selected.get("name") or ""), selected
        return "", {}

    def _arbitration_selected_has_evidence(self, selected: dict) -> bool:
        evidence = selected.get("evidence", ()) if isinstance(selected, dict) else ()
        return bool(evidence)

    def _mindreading_is_grounded_task_or_scene(self, text: str, *, selected_impulse: str, selected: dict) -> bool:
        """Cho phép suy diễn động cơ nông nếu nó bám scene/task evidence.

        Cho phép: "có vẻ Ngài đang debug/test/xem log" khi technical_help_impulse
        có evidence.
        Không cho: "Ngài đang buồn/mệt/cần được..." vì đó là claim tâm lý sâu.
        """
        normalized = self._normalize_user_message(text)
        if not self._arbitration_selected_has_evidence(selected):
            return False
        deep_state_markers = ("buon", "met", "cang", "can mot", "can duoc", "co don", "so", "dau")
        if any(marker in normalized for marker in deep_state_markers):
            return False
        task_markers = ("debug", "test", "sua", "fix", "log", "loi", "code", "parser", "contract", "pytest")
        scene_markers = ("xem", "nhin", "doc", "mo", "youtube", "video", "game")
        if selected_impulse == "technical_help_impulse" and any(marker in normalized for marker in task_markers):
            return True
        if selected_impulse == "scene_curiosity_impulse" and any(marker in normalized for marker in scene_markers):
            return True
        return False

    def _arbitration_rewrite_for_mindreading(
        self,
        *,
        text: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
    ) -> tuple[str, str, bool]:
        """Rewrite mindreading bằng arbitration_report.

        Return: (replacement, marker, allow_original). Nếu allow_original=True thì
        guard chỉ ghi trace, không sửa text.
        """
        report = self._arbitration_report_from_speech_core(speech_core)
        selected_impulse, selected = self._selected_impulse_from_arbitration(report)
        if not selected_impulse:
            return "", "", False
        if self._mindreading_is_grounded_task_or_scene(text, selected_impulse=selected_impulse, selected=selected):
            return "", f"arbitration_mindreading_guard=allow_grounded:{selected_impulse}", True

        if selected_impulse in {
            "scene_curiosity_impulse",
            "technical_help_impulse",
            "companionship_impulse",
            "inner_whim_impulse",
            "micro_story_impulse",
            "silence_impulse",
            "body_only_impulse",
        }:
            return "", f"arbitration_mindreading_guard=flag:{selected_impulse}", False

        if selected_impulse == "scene_curiosity_impulse":
            replacement = self.speech_core_engine.render_safe_fallback_text(
                speech_core,
                normalize_text=self._normalize_user_message,
                is_near_duplicate=self._is_near_duplicate_text,
                last_text=self.last_text,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            ) or "Toi chi bam vao canh hien tai thoi. Mot nhan xet nho thi duoc, doan sau hon thi khong sach."
            return replacement, "arbitration_mindreading_guard=rewrite_scene_curiosity", False
        if selected_impulse == "technical_help_impulse":
            return (
                "Tôi chỉ bám vào dấu hiệu kỹ thuật hiện có. Nếu đang debug thì nên soi evidence/log gần nhất trước, không cần đoán tâm trạng Ngài.",
                "arbitration_mindreading_guard=rewrite_technical_help",
                False,
            )
        if selected_impulse in {"companionship_impulse", "inner_whim_impulse", "micro_story_impulse"}:
            return (
                "Tôi không đoán tâm trạng Ngài hộ đâu. Tôi giữ một nhịp nhỏ ở đây thôi.",
                f"arbitration_mindreading_guard=rewrite_internal:{selected_impulse}",
                False,
            )
        if selected_impulse in {"silence_impulse", "body_only_impulse"}:
            return (
                "Ít evidence để đoán sâu. Tôi giữ im phần đó.",
                f"arbitration_mindreading_guard=rewrite_quiet:{selected_impulse}",
                False,
            )
        return "", "", False

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
        # anti_mindreading là guard QUAN HỆ/epistemic. warn-only ⇒ chỉ cảnh báo,
        # để câu đoán-tâm-trí đi qua (đọc người là một phần của persona, không chặn).
        if guards_warn_only():
            return self._trace_only_guard(decision, "anti_mindreading=warn_only")
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

        # ControlledSlippage: motive/relational misread được phép trong lane sống động,
        # còn factual grounding vẫn để các guard khác giữ. Đây là chỗ tháo cái "sợ sai"
        # khỏi vùng quan hệ, thay vì để anti_mindreading biến ERIS thành báo cáo an toàn.
        try:
            state = self._get_internal_state()
        except Exception:
            state = None
        slippage_profile = resolve_controlled_slippage(
            channel="autonomous",
            ti_report=None,
            internal_state=state,
            speech_core=speech_core,
        )
        selected_impulse, _selected = self._selected_impulse_from_arbitration(
            self._arbitration_report_from_speech_core(speech_core)
        )

        # InformationGap/Curiosity: nếu câu là phỏng đoán tương tác có mời sửa
        # ("có vẻ... phải không?"), đừng chém nó như mindreading độc đoán.
        # Đây là mảnh còn thiếu: thiếu dữ kiện phải sinh curiosity/probe, không phải câm.
        if self._interactive_guess_allowed(
            decision.text or "",
            speech_core=speech_core,
            slippage_profile=slippage_profile,
            selected_impulse=selected_impulse,
        ):
            return self._trace_only_guard(
                decision,
                f"interactive_guess_allow:{getattr(slippage_profile, 'mode', 'none')}:{selected_impulse or 'none'}",
            )

        if (
            getattr(slippage_profile, "allow_motive_hypothesis", False)
            and selected_impulse in {"companionship_impulse", "inner_whim_impulse", "micro_story_impulse"}
        ):
            return self._trace_only_guard(
                decision,
                f"controlled_slippage_allow_mindread:{slippage_profile.mode}:{selected_impulse}",
            )

        # Không lấy fallback_policy làm đáy cho anti-mindreading nữa.
        # Nếu có rewrite dựa trên arbitration thật hoặc reshape thành câu hỏi sạch
        # thì dùng làm hint; còn không, GuardViolation sẽ tự rơi xuống
        # _dynamic_guard_bottom_fallback(). Template pool không được làm tác giả.
        replacement = ""
        arbitration_replacement, arbitration_marker, allow_original = self._arbitration_rewrite_for_mindreading(
            text=decision.text or "",
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if allow_original:
            return self._trace_only_guard(decision, arbitration_marker or "arbitration_mindreading_guard=allow")
        if arbitration_replacement:
            replacement = arbitration_replacement
        elif speech_core.utterance_type == "curious_question":
            shaped = self._reshape_statement_as_question(decision.text or "")
            if shaped and not self._is_near_duplicate_text(shaped, self.last_text):
                replacement = shaped
        marker = arbitration_marker or "anti_mindreading_filter"
        return self._repair_guard_violation_decision(
            decision,
            GuardViolation(
                rule="anti_mindreading",
                severity="soft",
                reason="unsupported_authoritative_mindreading",
                original_text=str(getattr(decision, "text", "") or ""),
                suggested_action="reroll",
                missing_evidence=(),
                trace_marker=marker,
                fallback_text=replacement if replacement else "",
            ),
            channel="autonomous",
            speech_core=speech_core,
            parse_mode="arbitration_mindreading_guard" if arbitration_marker else decision.parse_mode,
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
        fallback_intent = self.speech_core_engine.fallback_intent(speech_core)
        marker = (
            f"force_speak_semantic_family_guard={semantic_family or repeated_family}"
            if (semantic_family or repeated_family)
            else "force_speak_repeat_guard"
        )
        replacement = self.speech_core_engine.render_force_speak_repair_text(
            speech_core,
            normalize_text=self._normalize_user_message,
            is_near_duplicate=self._is_near_duplicate_text,
            last_text=self.last_text,
            intent=fallback_intent,
            counter=self.force_speak_repeat_guard_count,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        if not replacement:
            replacement = self._force_speak_fallback_by_intent_text(
                fallback_intent,
                counter=self.force_speak_repeat_guard_count,
                focus_kind=str(getattr(snapshot, "active_window_kind", "") or "") if snapshot is not None else "",
                window_title=str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "") if snapshot is not None else "",
                momentum_topic=momentum_topic,
            )
        if self._is_near_duplicate_text(replacement, self.last_text):
            replacement = self.speech_core_engine.render_force_speak_repair_text(
                speech_core,
                normalize_text=self._normalize_user_message,
                is_near_duplicate=self._is_near_duplicate_text,
                last_text=self.last_text,
                intent=fallback_intent,
                counter=self.force_speak_repeat_guard_count,
                repeated=True,
                snapshot=snapshot,
                momentum_topic=momentum_topic,
            )
            if not replacement:
                replacement = self._force_speak_fallback_by_intent_text(
                    fallback_intent,
                    counter=self.force_speak_repeat_guard_count,
                    repeated=True,
                    focus_kind=str(getattr(snapshot, "active_window_kind", "") or "") if snapshot is not None else "",
                    window_title=str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "") if snapshot is not None else "",
                    momentum_topic=momentum_topic,
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
        violation = GuardViolation(
            rule="repetition_filter",
            severity="soft",
            reason="near_duplicate_public_text",
            original_text=decision.text or "",
            suggested_action="reroll",
            fallback_text="",
            trace_marker="repetition_filter",
        )
        return self._repair_guard_violation_decision(
            decision,
            violation,
            channel=channel,
            speech_core=speech_core,
            parse_mode="speech_repeat_guard",
            allow_reroll=True,
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
        violation = GuardViolation(
            rule="style_contract_anchor_guard",
            severity="soft",
            reason="unanchored_style_line",
            original_text=decision.text or "",
            suggested_action="reroll",
            fallback_text="",
            trace_marker="style_contract_anchor_guard",
        )
        return self._repair_guard_violation_decision(
            decision,
            violation,
            channel=channel,
            speech_core=speech_core,
            parse_mode=decision.parse_mode,
            allow_reroll=True,
        )
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
            if utterance_type == "soft_boundary": # soft_boundary không có intent công khai riêng → giữ social_presence
                return "social_presence"
            return utterance_type # autonomous giữ đúng bản sắc nói nhảm/ngẫu hứng/muse nhẹ thay vì phẳng thành social_presence
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
        silence_reasons = (
            "vietnamese_requires_diacritics",
            "micro_line_too_short_without_clear_meaning",
            "micro_observation_requires_anchor",
            "screen_observation_requires_anchor",
            "placeholder_text_blocked",
        )
        suggested = "body_only" if any(
            reason == "no_speech_blocks_final"
            or reason.startswith("micro_observation_not_grounded:")
            or reason.startswith("screen_observation_not_grounded:")
            or reason in silence_reasons
            for reason in reasons
        ) else "reroll"
        violation = GuardViolation(
            rule="micro_line_policy",
            severity="soft",
            reason="; ".join(reasons),
            original_text=decision.text or "",
            suggested_action=suggested,
            fallback_text="",
            trace_marker=marker,
        )
        return self._repair_guard_violation_decision(
            decision,
            violation,
            channel=channel,
            speech_core=speech_core,
            parse_mode="no_speech_policy" if suggested == "body_only" else decision.parse_mode,
            allow_reroll=suggested == "reroll",
        )
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

    def _apply_emotional_consequence_filter(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core=None,
        frame=None,
        user_text: str = "",
    ) -> Decision:
        """Nước 1 — van bước-cuối: nếu câu cuối phẳng dưới mức biểu đạt thật, xin
        một reroll felt-expansion. MẶC ĐỊNH TẮT (cờ ERIS_EMOTIONAL_CONSEQUENCE).

        Van này chỉ MỞ: nó không bao giờ làm câm hay rút ngắn. Reroll thất bại/
        không có model/ngắn hơn bản gốc → giữ nguyên bản gốc.
        """
        try:
            from cortex.emotional_consequence import (
                count_words,
                emotional_consequence_enabled,
                felt_expansion_reason,
                min_words_for_expression,
                surface_is_flattened,
            )
        except Exception:
            return decision
        if not emotional_consequence_enabled():
            return decision
        if channel not in {"chat", "force_speak"}:
            return decision
        if not bool(getattr(decision, "should_speak", False)):
            return decision
        text = str(getattr(decision, "text", "") or "").strip()
        if not text:
            return decision
        gate = getattr(self, "_last_expression_gate", None)
        if not isinstance(gate, dict):
            return decision
        try:
            allowed = float(gate.get("allowed_expression", 0.0) or 0.0)
            want = float(gate.get("want_to_say", 0.0) or 0.0)
        except (TypeError, ValueError):
            return decision
        stance = str(gate.get("stance", "") or "")
        if not surface_is_flattened(text, allowed_expression=allowed, want_to_say=want):
            return decision
        service = getattr(self, "llm_service", None)
        expand = getattr(service, "rewrite_for_felt_expression", None)
        if not callable(expand):
            return self._trace_only_guard(decision, "emotional_consequence=flat_no_service")
        try:
            new_text = expand(
                original_text=text,
                reason=felt_expansion_reason(stance=stance, allowed_expression=allowed, want_to_say=want),
                stance=stance,
                min_words=min_words_for_expression(allowed),
                channel=channel,
                user_text=user_text,
                internal_state_context=self._guard_internal_state_context(),
            )
        except Exception:
            new_text = ""
        # Chỉ nhận khi reroll DÀI HƠN thật sự (van chỉ mở, không siết).
        if new_text and count_words(new_text) > count_words(text):
            try:
                from runtime.panel_snapshot import add_signal
                add_signal("expanded")
            except Exception:
                pass
            return self._copy_decision_with_text(
                decision,
                text=new_text,
                trace_marker="emotional_consequence=expanded",
                parse_mode=getattr(decision, "parse_mode", "") or "emotional_consequence",
            )
        return self._trace_only_guard(decision, "emotional_consequence=flat_kept_original")

    def _apply_post_generation_filters(
        self,
        decision: Decision,
        *,
        channel: str,
        speech_core: AgentSpeechCore,
        snapshot=None,
        momentum_topic: str = "",
        frame=None,
    ) -> Decision:
        guard_mode = get_guard_mode()
        authority = getattr(self, "_apply_v3_authority_guard", None)
        if guard_mode == OFF_GUARD_MODE:
            return authority(decision, frame=frame, channel=channel) if callable(authority) else decision
        if guard_mode == LOG_ONLY_GUARD_MODE:
            # LOG_ONLY đúng nghĩa: chỉ ghi rằng guard *sẽ* sửa, không sửa decision thật.
            # Tên mode mà vẫn mutate là một lời nguyền bé xinh của cấu hình runtime.
            try:
                probe = replace(decision)
                probe = self._apply_protocol_surface_guard(probe)
                probe = self._apply_internal_object_surface_guard(probe)
                probe = self._guard_recent_context_as_screen_observation(probe)
                probe = self._apply_memory_haunting_guard(
                    probe,
                    channel=channel,
                    speech_core=speech_core,
                    allow_reroll=False,
                )
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
            decision = self._apply_utterance_evaluator_filter(
                decision,
                channel=channel,
                speech_core=speech_core,
                snapshot=snapshot,
            )
            decision = self._apply_banter_arbiter(
                decision,
                channel=channel,
                speech_core=speech_core,
            )
            return authority(decision, frame=frame, channel=channel) if callable(authority) else decision

        decision = self._apply_protocol_surface_guard(decision)
        decision = self._apply_internal_object_surface_guard(decision)
        decision = self._guard_recent_context_as_screen_observation(decision)
        decision = self._apply_memory_haunting_guard(
            decision,
            channel=channel,
            speech_core=speech_core,
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
        decision = self._apply_repetition_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        decision = self._apply_utterance_evaluator_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
            snapshot=snapshot,
        )
        decision = self._apply_banter_arbiter(
            decision,
            channel=channel,
            speech_core=speech_core,
        )
        decision = self._apply_novelty_advisory(decision, channel=channel)
        # Emotional consequence chạy trước; V3 authority mới là cổng cuối cùng.
        decision = self._apply_emotional_consequence_filter(
            decision,
            channel=channel,
            speech_core=speech_core,
        )
        return authority(decision, frame=frame, channel=channel) if callable(authority) else decision
        # NOTE: advisory cũng được gắn ở _apply_chat_final_guards cho nhánh chat,
        # để cả hai cửa ra đều đi qua một cửa novelty chung.

    def _apply_novelty_advisory(
        self,
        decision: Decision,
        *,
        channel: str = "",
    ) -> Decision:
        """Đề xuất 2: novelty ở cửa ra (post-generation), MẶC ĐỊNH chỉ-log.

        Đo độ tươi mới ngữ nghĩa của câu cuối so với N câu ERIS vừa nói. Đây là
        nơi bắt sự ĐƠN ĐIỆU mà các guard chuỗi-ký-tự bỏ sót, ngay tại điểm phát.

        Chế độ qua env ``ERIS_NOVELTY_POSTGEN_MODE``:
          - "log" (MẶC ĐỊNH): chỉ ghi novelty vào debug_trace, KHÔNG đổi decision.
          - "enforce": nếu novelty < ngưỡng → hạ confidence + đánh dấu; nếu gần
            như lặp y hệt (rất thấp) thì với kênh KHÔNG phải chat sẽ degrade về
            body_only (im). Chat không bao giờ bị mute ở đây — câu hỏi trực tiếp
            vẫn phải được trả lời; chỉ hạ confidence để vòng sau tự điều chỉnh.
          - "off": tắt hẳn.

        Hot path: chỉ chạy khi có câu nói thật; lỗi gì cũng nuốt, không raise.
        """
        mode = str(os.environ.get("ERIS_NOVELTY_POSTGEN_MODE", "log") or "log").strip().lower()
        if mode == "off":
            return decision
        text = str(getattr(decision, "text", "") or "").strip()
        if not text or not bool(getattr(decision, "should_speak", False)):
            return decision

        guard = None
        get_guard = getattr(self, "_get_novelty_guard", None)
        if callable(get_guard):
            guard = get_guard()
        if guard is None:
            return decision

        try:
            recent = self._recent_spoken_texts(limit=6)
        except Exception:
            recent = ()
        try:
            score = guard.novelty_score(text, recent_lines=tuple(recent), include_banned_seed=True)
        except Exception:
            return decision

        try:
            threshold = float(os.environ.get("ERIS_NOVELTY_POSTGEN_THRESHOLD", "0.18") or 0.18)
        except ValueError:
            threshold = 0.18
        threshold = max(0.0, min(0.9, threshold))

        marker = f"novelty_postgen={score:.2f}/{threshold:.2f}/{mode}"

        # Câu đủ tươi → để nguyên, KHÔNG annotate (giữ debug_trace sạch cho line
        # bình thường; chỉ đánh dấu khi nghi ngờ đơn điệu).
        if score >= threshold:
            return decision

        if mode != "enforce":
            # Log-only: chỉ ghi cờ nghi-ngờ-lặp, không đụng decision.
            return self._trace_only_guard(decision, marker)

        # enforce + novelty thấp: hạ confidence, đánh dấu.
        repaired = replace(decision)
        repaired.debug_trace = self._append_trace(getattr(repaired, "debug_trace", ""), marker + "; stale_penalty")
        try:
            repaired.confidence = min(float(getattr(repaired, "confidence", 0.5) or 0.5), 0.40)
        except Exception:
            repaired.confidence = 0.40
        # Gần như lặp y hệt + KHÔNG phải chat → im (để body cử động thay vì nói lại).
        if score < 0.08 and str(channel or "").strip().lower() != "chat":
            repaired.text = ""
            repaired.should_speak = False
            repaired.parse_mode = "novelty_body_only"
            repaired.debug_trace = self._append_trace(repaired.debug_trace, "novelty_degrade=body_only")
        return repaired

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
        violation = GuardViolation(
            rule="internal_meaning_label_filter",
            severity="soft",
            reason="internal_meaning_label_surface",
            original_text=decision.text or "",
            suggested_action="reroll",
            fallback_text="",
            trace_marker="internal_meaning_label_filter",
        )
        return self._repair_guard_violation_decision(
            decision,
            violation,
            speech_core=speech_core,
            parse_mode=decision.parse_mode,
            allow_reroll=True,
        )
