from __future__ import annotations

import os
import time
import traceback

from cortex.action_planner import ACTION_SPACE
from cortex.contracts import (
    AgentSpeechCore,
    CognitiveActionPlan,
    CognitiveAppraisal,
    InnerThought,
    SessionRitualReport,
    ThoughtStreamReport,
)
from cortex.internal_state import PersistentInternalState
from domain import Decision


class PromptContextBuilderMixin:
    def _log_exception(self, message: str, *args) -> None:
        log_exception = getattr(self.logger, "exception", None)
        if callable(log_exception):
            log_exception(message, *args)
            return
        rendered = message % args if args else message
        self.logger.warning("%s %s", rendered, traceback.format_exc().strip())

    def _session_ritual_fallback_decision(self, *, source: str, tone: str = "quiet_background") -> Decision:
        return Decision(
            text="Ngài quay lại rồi.",
            animation="stand",
            intent="session_ritual",
            reasoning_tags=("session_ritual", "startup_greeting", "fallback_greeting"),
            should_speak=True,
            confidence=0.64,
            parse_mode="session_ritual",
            debug_trace=f"session_ritual_layer; source={source}; tone={tone}",
        )

    def _send_session_ritual_fallback_greeting(
        self,
        *,
        source: str = "fallback_after_session_ritual_error",
        tone: str = "quiet_background",
    ) -> Decision:
        decision = self._session_ritual_fallback_decision(source=source, tone=tone)
        self.last_text = decision.text
        self._note_autonomous_spoken(now=time.time())
        self._send_decision_to_body(decision)
        return decision

    def _session_ritual_llm_timeout(self) -> float:
        raw = os.environ.get("ERIS_SESSION_RITUAL_LLM_TIMEOUT_SEC", "8").strip()
        try:
            return max(1.0, float(raw))
        except ValueError:
            return 8.0

    def _build_internal_state_context(self, state: PersistentInternalState | None = None, self_state=None) -> str:
        #Chuyển internal state thành text
        state_context = self.internal_state_engine.render_prompt_context(state or self._get_internal_state())
        #Nếu self_state có prompt_context, lấy thêm.
        #self_state thường là mô hình tự nhận thức của agent: “mình đang ở mode nào”, “nên giữ phong cách nào”.
        prompt_context = str(getattr(self_state, "prompt_context", "") or "").strip()
        #Nếu có, nối vào.
        if prompt_context:
            return f"{state_context}\n{prompt_context}"
        return state_context

    #Hàm này dựng context cho ThoughtStream.
    def _build_thought_stream_context(self) -> dict[str, object]:
        #Nó lấy snapshot hệ thống + memory + trạng thái gần đây.
        with self._state_lock:
            mood_score = self.mood_score #trạng thái mood hiện tại
            inferred_pos_x = self.inferred_pos_x #vị trí
            internal_state = self._get_internal_state() # pose suy luận
            long_term_memory = tuple(self.long_term_memory or ()) #memory dài hạn
            last_text = self.last_text #câu vừa nói gần nhất
            recent_inner_seeds = tuple(self.recent_inner_thought_seeds or ()) #các seed suy nghĩ gần đây
            recent_thought_seeds = tuple(getattr(internal_state, "recent_thought_seeds", ()) or ()) #các seed suy nghĩ gần đây được lưu trong internal state
            recent_subconscious = tuple(getattr(internal_state, "recent_subconscious_seeds", ()) or ()) #subconscious seed gần đây
        #Lấy snapshot từ telemetry.
        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
        return {
            "snapshot": snapshot,
            "internal_state": internal_state,
            "long_term_memory": long_term_memory,
            "last_text": last_text,
            "recent_inner_seeds": recent_inner_seeds,
            "recent_thought_seeds": recent_thought_seeds,
            "recent_subconscious_seeds": recent_subconscious,
        }

    def _build_subconscious_context(self) -> dict[str, object]:
        return self._build_thought_stream_context()

    def _build_memory_context(self, snapshot=None, memory_resonance=None) -> str:
        renderer = getattr(getattr(self, "memory_core", None), "render_context", None)
        context = ""
        if callable(renderer):
            try:
                context = renderer(self._memory_query_from_snapshot(snapshot), snapshot=snapshot)
            except Exception as exc:
                self.logger.warning("Memory context render error: %s", exc)
        report = memory_resonance if memory_resonance is not None else getattr(self, "active_memory_resonance", None)
        render_resonance = getattr(report, "render_prompt_context", None)
        if callable(render_resonance):
            try:
                resonance_context = render_resonance()
                if resonance_context:
                    return f"{context}\n\n{resonance_context}".strip()
            except Exception as exc:
                self.logger.warning("Memory resonance context render error: %s", exc)
        return context

    #So sánh snapshot hiện tại với chuẩn đã xây dựng trong bộ nhớ, trả về các điểm khác biệt đáng chú ý để làm tín hiệu cho tầng đánh giá và quyết định.

    def _filter_memory_context_for_grounding(self, memory_context: str) -> str:
        """Giữ procedural guard, bỏ memory có hình dạng câu trả lời.

        Bản cũ giữ mọi dòng có chữ "source" hoặc "confidence". Memory render thường có
        `semantic ... source=... confidence=...`, thế là semantic/episodic lọt qua cổng cách ly.
        Một cái lưới bắt cá nhưng lỗ to bằng con cá, rất nhân loại.
        """
        fallback = (
            "PROCEDURAL MEMORY ONLY:\n"
            "- Memory may remind ERIS to stay grounded.\n"
            "- Memory must not answer current-screen or specific-file questions without evidence.\n"
            "- Do not surface semantic/episodic/relational memory as present evidence.\n"
        )
        if not memory_context:
            return fallback

        allowed: list[str] = []
        current_block: list[str] = []
        current_layer = "unknown"

        def flush() -> None:
            nonlocal current_block, current_layer
            if current_layer == "procedural" and current_block:
                allowed.extend(current_block)
            current_block = []
            current_layer = "unknown"

        for line in memory_context.splitlines():
            raw = line.rstrip()
            low = raw.strip().lower()
            if not low:
                current_block.append(raw)
                continue

            starts_procedural = low.startswith(("procedural", "[procedural", "- procedural", "procedural memory"))
            starts_blocked = low.startswith((
                "semantic", "[semantic", "- semantic",
                "episodic", "[episodic", "- episodic",
                "relational", "[relational", "- relational",
                "affective", "[affective", "- affective",
                "repair", "[repair", "- repair",
            ))
            if starts_procedural or starts_blocked:
                flush()
                current_layer = "procedural" if starts_procedural else "blocked"
                current_block = [raw]
                continue

            # Chỉ giữ các dòng rule grounding độc lập, không giữ dòng semantic chỉ vì có source/confidence.
            if current_layer == "unknown" and any(k in low for k in (
                "no_screen_evidence",
                "grounded_speech",
                "post_generation_guard",
                "không thấy thì không nói",
                "khong thay thi khong noi",
                "memory must not answer",
                "file content",
                "screen evidence",
            )):
                current_layer = "procedural"
            current_block.append(raw)

        flush()
        cleaned = "\n".join(line for line in allowed if str(line).strip())
        return cleaned if cleaned.strip() else fallback

    def _build_action_plan_context(self, action_plan: CognitiveActionPlan) -> str:
        flags = ", ".join(action_plan.risk_flags) if action_plan.risk_flags else "none"
        notes = " | ".join(action_plan.notes) if action_plan.notes else "none"
        reason = action_plan.reason_to_speak or action_plan.reason or "none"
        style_anchor = str(getattr(action_plan, "style_anchor", "") or "current event")
        style_attitude = str(getattr(action_plan, "style_attitude", "") or "lạnh nhẹ")
        style_limit = str(getattr(action_plan, "style_limit", "") or "một câu ngắn")
        style_voice = str(
            getattr(action_plan, "style_voice", "")
            or "Voice: controlled, precise, emotionally low-temperature."
        )
        utility_scores = getattr(action_plan, "utility_scores", {}) or {}
        top_scores = sorted(utility_scores.items(), key=lambda item: item[1], reverse=True)[:5]
        utility_line = ", ".join(f"{name}={score:.2f}" for name, score in top_scores) or "none"
        rhythm_phase = str(getattr(action_plan, "rhythm_phase", "") or "settled")
        transition_reason = str(getattr(action_plan, "transition_reason", "") or "none")
        memory_pressure = " | ".join(getattr(action_plan, "memory_pressure", ()) or ()) or "none"
        style_block = (
            "Reason to speak:\n"
            f"{reason}\n\n"
            "Character voice constraint:\n"
            f"{style_voice}\n\n"
            "INFJ 5w4 594 constraint:\n"
            "- perceptive, not bubbly\n"
            "- emotionally restrained, not dead\n"
            "- symbolic only when useful\n"
            "- warmth is indirect\n"
            "- no needy attachment\n"
            "- no invented intimacy\n"
            "- no corporate assistant tone"
        )
        return (
            "ActionPlanner decision before LLM:\n"
            f"- action_space={', '.join(ACTION_SPACE)}\n"
            f"- should_speak={str(action_plan.should_speak).lower()}\n"
            f"- speech_act={action_plan.speech_act}\n"
            f"- utterance_type={action_plan.speech_act}\n"
            f"- reason_to_speak={reason}\n"
            f"- utility_top={utility_line}\n"
            f"- rhythm_phase={rhythm_phase}\n"
            f"- transition_reason={transition_reason}\n"
            f"- memory_pressure={memory_pressure}\n"
            f"- risk_flags={flags}\n"
            f"- notes={notes}\n"
            f"{style_block}\n"
            "Style contract before wording:\n"
            f"- anchor={style_anchor}\n"
            f"- attitude={style_attitude}\n"
            f"- limit={style_limit}\n"
            f"- voice={style_voice}\n"
            "- reject_line_if=no concrete anchor, too long, or abstract philosophy\n"
            "Honor this plan. Do not upgrade withdraw/no_speech into observation, teasing, or reassurance."
        )

    def _build_llm_ti_context(self, ti_report, action_plan: CognitiveActionPlan) -> str:
        mode = str(getattr(ti_report, "mode", "") or "steady_observe")
        animation = str(getattr(ti_report, "animation_hint", "") or "stand")
        return (
            f"Mode: {mode}. Animation hint: {animation}.\n"
            f"{self._build_action_plan_context(action_plan)}\n"
            "Telemetry is internal routing data only. Do not mention window, focus, CPU, RAM, idle, tabs, or app names "
            "unless they appear in speech_evidence."
        )

    def _build_speech_evidence_context(self, snapshot, *, limit: int = 2) -> str:
        signals = self._concrete_screen_signals(snapshot)[:limit]
        if not signals:
            return "speech_evidence=<none>"
        return "speech_evidence=" + " | ".join(str(item) for item in signals)

    def _build_current_focus_context(self, snapshot) -> str:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus = str(getattr(snapshot, "focus_summary", "") or "").strip() or focus_kind
        return f"current_focus_kind={focus_kind}; current_focus={focus}"


    def _build_session_ritual_ti_context(self, report: SessionRitualReport, snapshot) -> str:
        seed = str(getattr(report, "greeting_text", "") or "").strip() or "fresh_start"
        focus = self._build_current_focus_context(snapshot)
        evidence = ", ".join(str(item) for item in tuple(getattr(report, "evidence", ()) or ())[:5]) or "none"
        return (
            "Mode: session_ritual_startup_greeting. Animation hint: stand.\n"
            "Action plan: greet the user once because ERIS has just started.\n"
            f"Ritual seed for continuity, not final wording: {seed}\n"
            f"Ritual evidence: {evidence}\n"
            f"{focus}\n"
            "Write exactly one short greeting line in Vietnamese, addressed to Ngài. "
            "Let the LLM choose the wording from current mood/style, relationship memory, and any safe continuity seed. "
            "This is a greeting, not a report: do not mention telemetry, windows, tabs, idle, CPU, RAM, parse_mode, or session_ritual. "
            "Do not use fixed continuity slogans like 'Tôi vẫn giữ mạch' or 'mạch đã nối lại'."
        )

    def _restore_session_ritual_once(self) -> SessionRitualReport:
        if getattr(self, "_session_ritual_ran", False):
            return SessionRitualReport(restored=False, session_resumed=False, should_greet=False)
        self._session_ritual_ran = True

        try:
            self._ensure_internal_state()
            internal_state = self._get_internal_state()

            snapshot = self.telemetry_service.capture_snapshot(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )
            thought_stream_report = (
                self.cognitive_substrate.latest_report()
                if callable(getattr(self.cognitive_substrate, "latest_report", None))
                else ThoughtStreamReport()
            )
            social_presence_event = self._detect_social_presence_event(
                channel="autonomous",
                snapshot=snapshot,
                internal_state=internal_state,
                started_at=time.time(),
            )
            report = self.session_ritual_engine.evaluate(
                snapshot=snapshot,
                internal_state=internal_state,
                thought_stream_report=thought_stream_report,
                social_presence_event=social_presence_event,
            )
            self.logger.info(
                "[session_ritual] report restored=%s | presence=%s | continuity=%s | greet=%s | tone=%s",
                int(bool(report.restored)),
                int(bool(report.presence_restored)),
                int(bool(report.continuity_restored)),
                int(bool(report.should_greet)),
                report.tone,
            )
        except Exception:
            self._log_exception("[session_ritual] restore failed")
            self._send_session_ritual_fallback_greeting()
            return SessionRitualReport(
                restored=False,
                session_resumed=False,
                should_greet=True,
                tone="quiet_background",
                evidence=("session_ritual_error",),
            )

        if report.should_greet:
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._recall_memory_resonance(
                snapshot=snapshot,
                channel="session_ritual",
                fragments=tuple(
                    item
                    for item in (
                        report.active_goal,
                        report.current_attractor,
                        report.recent_cognition_direction,
                        report.self_continuity,
                        *tuple(report.unresolved_loops or ()),
                    )
                    if str(item or "").strip()
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
            ni_report = self.ni_engine.evaluate_autonomous(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                last_text=self.last_text,
                goal_state=getattr(internal_state, "goal_persistence", None),
            )
            ti_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
            ti_report = self.ti_governor.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ni_state_label=ti_view["discrete_state"],
                ni_state_streak=ti_view["streak_length"],
                idle_cycles=self.idle_cycles,
                last_text=self.last_text,
            )
            fe_plan = self.fe_renderer.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                internal_state=internal_state,
                last_text=self.last_text,
            )
            greeting_source = "llm"
            try:
                raw = self.llm_service.generate_directive(
                    telemetry_data=self._build_speech_evidence_context(snapshot),
                    ni_context=str(getattr(ni_report, "prompt_context", "") or ""),
                    ti_context=self._build_session_ritual_ti_context(report, snapshot),
                    fe_context=fe_plan.style_context,
                    appraisal_context="session_ritual: startup greeting; express current attitude without reporting telemetry.",
                    internal_state_context=self._build_internal_state_context(internal_state),
                    memory_context=memory_context,
                    avoid_text=self.last_text,
                    speech_intent="session_ritual",
                    vision_trace_marker="session_ritual",
                    request_timeout=self._session_ritual_llm_timeout(),
                )
                if "service_error" in raw or "exception_fallback" in raw:
                    raise RuntimeError("session_ritual_llm_service_error")
                self._log_raw_llm_output("session_ritual", raw)
                decision = self.parser.parse(raw)
            except Exception:
                self._log_exception("[session_ritual] LLM greeting failed")
                greeting_source = "fallback_after_llm_error"
                decision = self._session_ritual_fallback_decision(source=greeting_source, tone=report.tone)
            if not decision.text.strip():
                greeting_source = "fallback_after_empty_llm"
                decision = self._session_ritual_fallback_decision(source=greeting_source, tone=report.tone)
            if decision.text.strip():
                decision.intent = decision.intent or "session_ritual"
                decision.reasoning_tags = tuple(dict.fromkeys((*decision.reasoning_tags, "session_ritual", "startup_greeting")))
                decision.should_speak = True
                decision.confidence = decision.confidence or 0.72
                decision.parse_mode = "session_ritual"
                decision.debug_trace = (
                    f"{decision.debug_trace} | session_ritual_layer; source={greeting_source}; tone={report.tone}"
                    if decision.debug_trace
                    else f"session_ritual_layer; source={greeting_source}; tone={report.tone}"
                )
                self.fe_style_memory = self.fe_renderer.remember_style(
                    self.fe_style_memory,
                    plan=fe_plan,
                    rendered_text=decision.text,
                )
                self.last_text = decision.text
                self._note_autonomous_spoken(now=time.time())
                self.logger.info('[session_ritual] sent LLM greeting text="%s"', decision.text)
                self._send_decision_to_body(decision)

        updated_state = self.internal_state_engine.commit_session_ritual(
            internal_state,
            session_ritual=report,
        )
        self._set_internal_state(updated_state)
        if self.memory_state is not None:
            self._save_memory_state()

        return report


    def _build_speech_core_ti_context(
        self,
        ti_report,
        action_plan: CognitiveActionPlan,
        inner_thought: InnerThought,
        speech_core: AgentSpeechCore | None = None,
    ) -> str:
        topic_seed = str(getattr(inner_thought, "topic_seed", "") or "open_presence")
        inner_intent = inner_thought.intent or action_plan.speech_act
        impulse = getattr(speech_core, "speech_impulse", None)
        impulse_context = ""
        if impulse is not None:
            impulse_context = (
                "Speech impulse before wording: "
                f"internal_family={str(getattr(impulse, 'meaning', '') or 'none')}; "
                f"reaction={str(getattr(impulse, 'reaction', '') or 'no_reaction')}; "
                f"attitude={str(getattr(impulse, 'attitude', '') or 'light')}; "
                f"mood_residue={str(getattr(impulse, 'mood_residue', '') or 'none')}; "
                f"emotional_pressure={float(getattr(impulse, 'emotional_pressure', 0.0) or 0.0):.2f}; "
                f"attention_bias={','.join(str(item) for item in (getattr(impulse, 'attention_bias', ()) or ())) or 'none'}; "
                f"reaction_impulse={str(getattr(impulse, 'reaction_impulse', '') or 'brief_indirect_reaction')}.\n"
                "SpeechCore contract: internal_family is forbidden wording. Use speech_evidence plus mood_residue/reaction_impulse. "
                "Do not say labels like escape_from_friction, cognitive_stall, avoidance, scattered_attention, decompression, or friction_point.\n"
            )
        risk_level = str(getattr(speech_core, "speech_risk_level", "") or "texture") if speech_core is not None else "texture"
        return (
            f"{self._build_llm_ti_context(ti_report, action_plan)}\n"
            f"{impulse_context}"
            f"Speech risk level: {risk_level}. "
            "hard_claim needs clear evidence; soft_read uses words like co ve/hinh nhu/lai thay; "
            "micro_presence and texture stay tiny, low-claim, under 12 words when possible. "
            "Weak evidence should look around the current atmosphere and produce only a tiny presence line when speech is required. "
            "Allowed personality leak: a little dry judgement, quiet texture, or attachment; "
            "never claim Ngai's mind or a fact not present in speech_evidence.\n"
            "SpeechCore mode: pick a freeform line from current_focus, environmental rhythm, recent interaction rhythm, "
            "or a tiny safe curiosity. The topic_seed is abstract, not wording to copy.\n"
            f"- inner_intent={inner_intent}\n"
            f"- inner_motive={inner_thought.motive or 'social_initiative'}\n"
            f"- topic_seed={topic_seed}\n"
            f"- evidence_anchor={inner_thought.evidence_anchor or 'none'}\n"
            "Thought stream contract: speech is only the visible tip; do not pretend the spoken line is the whole thought. "
            "If inner_motive starts with thought_stream or notes include cognitive_tension, the line may name continuity between internal states, "
            "for example: 'Ta vẫn thấy các tầng kia đang hơi rời nhau...' Keep it concise and do not turn it into a screen claim. "
            "Intent contract: curious_question must ask one small real question; "
            "if a useful curious_question draft begins as a statement, keep its semantic content and bend only its shape into a question. "
            "inner_whim must be one short thought, not refusal/no-signal/silence wording; "
            "random_chatter must be a mundane, playful, concrete one-liner, not meta explanation. "
            "Bounded thought surface: allowed shapes are observational irony, tiny curiosity, or ambient commentary. "
            "Forbidden shapes are surreal nonsense, abstract philosophy, or random absurdism without a concrete anchor. "
            "For random_chatter: do not be poetic; do not mention stories, listening, silence, screen, or logs; "
            "keep it concrete and not emotional or dramatic. "
            "Every candidate line must pass atmosphere + rhythm + limit before wording: anchor one concrete current detail "
            "such as current_focus, a visible speech_evidence item, a named topic_seed, or the immediate interaction rhythm; attitude stays light; limit stays short. "
            "Write a fresh line; do not use canned phrases or reusable templates. "
            "Treat force_speak as the trigger, not the topic; do not make the user request itself into entertainment. "
            "Only say Ngài called ERIS if this is a real chat or force_speak request and no better atmosphere/current_focus anchor exists; autonomous inner_whim must not invent a call. "
            "Do not mention force_speak, context menu, telemetry, window, tab, idle, CPU, RAM, or vision facts unless speech_evidence contains them. "
            "If speech_evidence=<none>, do not claim to see the screen and do not open a social-filler topic; "
            "look at current_focus/atmosphere/rhythm, then make one concise presence remark. "
            "Do not ask 'Ngài muốn tôi nói gì' or answer that there is no signal; do not perform, banter, or entertain from thin evidence. "
            "Banned force_speak phrase families: lùi lại, không cần nói gì, không có gì để nói, Ngài cứ làm việc, "
            "câu chuyện nhỏ, một người nghe, không cần màn hình, dòng log khô khan, ngồi nhìn log. "
            "Avoid repeating the last sentence, its main nouns, and its structure."
        )


    def _build_ni_telemetry_summary(self, snapshot) -> str:
        """Tóm tắt telemetry gọn cho Ni meta-critic mà không phụ thuộc TelemetryService.

        Dùng được cả trong unit test (dummy snapshot chỉ cần vài trường cơ bản).
        """

        focus = getattr(snapshot, "focus_summary", "") or ""
        window = getattr(snapshot, "active_window", "") or ""
        kind = getattr(snapshot, "active_window_kind", "") or ""
        url = getattr(snapshot, "browser_url", "") or ""
        idle = getattr(snapshot, "idle_seconds", 0.0) or 0.0
        mood_score = getattr(snapshot, "mood_score", 50)
        mood_label = getattr(snapshot, "mood_label", "") or ""
        idle_label = getattr(snapshot, "idle_label", "") or ""
        recent_events = getattr(snapshot, "recent_events", ()) or ()
        user_signals = getattr(snapshot, "user_signals", None)
        vision_facts = getattr(snapshot, "vision_facts", ()) or ()
        evidence = getattr(snapshot, "evidence", ()) or ()
        claim_style = getattr(snapshot, "claim_style", "") or ""
        parts = [
            f"focus={focus}",
            f"window={window}",
            f"kind={kind}",
        ]
        if url:
            parts.append(f"url={url}")
        parts.append(f"idle={idle:.0f}s({idle_label})")
        parts.append(f"mood={mood_score}({mood_label})")
        if recent_events:
            parts.append("recent_events=" + ",".join(str(item) for item in recent_events[:3]))
        if user_signals is not None:
            typing_speed = getattr(user_signals, "typing_speed", "") or ""
            window_switching = getattr(user_signals, "window_switching", "") or ""
            focus_pattern = getattr(user_signals, "focus_pattern", "") or ""
            if any((typing_speed, window_switching, focus_pattern)):
                parts.append(
                    "user_signals="
                    f"{typing_speed or 'unknown'}/{window_switching or 'unknown'}/{focus_pattern or 'unknown'}"
                )
        if evidence:
            parts.append("evidence=" + " | ".join(str(item) for item in evidence[:2]))
        if vision_facts:
            parts.append("vision_facts=" + " | ".join(str(item) for item in vision_facts[:2]))
        if claim_style:
            parts.append(f"claim_style={claim_style}")
        return " | ".join(parts)

    def _label_drift_score(self, drift_score: float) -> str:
        if drift_score >= 0.75:
            return "nghiêm trọng"
        if drift_score >= 0.55:
            return "cao"
        if drift_score >= 0.35:
            return "vừa"
        return "thấp"

    def _is_low_signal_chat_message(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return True

        low_signal_phrases = {
            "xin chao",
            "chao",
            "hello",
            "hi",
            "hey",
            "ok",
            "okay",
            "oke",
            "alo",
            "yes",
            "no",
            "uh",
            "um",
        }
        if normalized in low_signal_phrases:
            return True

        tokens = normalized.split()
        if len(tokens) <= 2 and all(token in low_signal_phrases for token in tokens):
            return True
        return False

    def _chat_history_for_llm(self, *, limit: int = 16) -> list[dict]:
        valid_entries = [
            {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
            for item in self.chat_history
            if not bool(item.get("invalid")) and str(item.get("role", "")) in {"system", "user", "assistant"}
        ]
        return valid_entries[-limit:]

    def _append_chat_history(self, role: str, content: str, *, invalid: bool = False) -> None:
        entry = {"role": role, "content": content}
        if invalid:
            entry["invalid"] = True
        self.chat_history.append(entry)

    def _user_denies_last_assistant_assumption(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized or not self.last_chat_answer.strip():
            return False
        denial_prefixes = (
            "khong phai",
            "sai",
            "sai roi",
            "y toi khong phai",
            "y minh khong phai",
            "ban hieu sai",
            "cau do sai",
            "khong dung",
        )
        denial_exact = {"khong", "dau"}
        denial_phrases = (
            "khong phai y toi",
            "khong phai y minh",
            "toi khong noi vay",
            "toi dau co noi vay",
            "ban doan sai roi",
            "ban hieu lech roi",
        )
        if normalized in denial_exact:
            return True
        if any(normalized.startswith(prefix) for prefix in denial_prefixes):
            return True
        return any(phrase in normalized for phrase in denial_phrases)

    def _invalidate_last_assistant_history(self, *, note: str) -> None:
        for item in reversed(self.chat_history):
            if str(item.get("role", "")) == "assistant" and not bool(item.get("invalid")):
                item["invalid"] = True
                break
        self._append_chat_history("system", note)

    def _maybe_invalidate_last_assistant_history(self, user_text: str) -> None:
        if not self._user_denies_last_assistant_assumption(user_text):
            return
        note = "Previous assistant inference was wrong. Do not build on it."
        self._invalidate_last_assistant_history(note=note)
        self.logger.info("[CHAT HISTORY] invalidated last assistant turn after user denial.")

    def _looks_like_no_evidence_style(self, claim_style: str) -> bool:
        lowered = (claim_style or "").strip().lower()
        markers = (
            "no_evidence",
            "refusal",
            "uncertainty",
            "soft_claim",
            "grounded",
            "weak_impression",
        )
        return any(marker in lowered for marker in markers)

    def _build_ni_structured_context(
        self,
        *,
        drift_score: float,
        drift_level: str,
        confidence: float,
        should_raise_guard: bool,
        reason_span: str,
        evidence: tuple[str, ...],
    ) -> str:
        guard = 1 if should_raise_guard else 0
        lines = [f"Ni: drift={drift_score:.2f}({drift_level}) conf={confidence:.2f} guard={guard}."]
        if reason_span:
            lines.append(f"Reason: {reason_span}.")
        if evidence:
            lines.append(f"Bám vào: {' | '.join(evidence[:3])}.")
        return "\n".join(lines)

