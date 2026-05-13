import unicodedata

from .internal_state import PersistentInternalState
from .contracts import (
    FeStyleMemory,
    FeStylePlan,
    GoalDriftReport,
    PersonalityLensResult,
    TelemetrySnapshot,
    TiPolicyReport,
)


class FeRenderer:
    def create_memory(self) -> FeStyleMemory:
        return FeStyleMemory()

    def apply_personality_lens(self, plan: FeStylePlan, lens: PersonalityLensResult | None) -> FeStylePlan:
        if lens is None:
            return plan

        prompt_context = str(getattr(lens, "prompt_context", "") or "").strip()
        if prompt_context and prompt_context not in (plan.style_context or ""):
            plan.style_context = f"{plan.style_context}\n{prompt_context}" if plan.style_context else prompt_context

        evidence = list(tuple(getattr(plan, "evidence", ()) or ()))
        interpretation = str(getattr(lens, "interpretation", "") or "")
        stance = str(getattr(lens, "stance", "") or "")
        if interpretation:
            evidence.append(f"personality_lens={interpretation}")
        if stance:
            evidence.append(f"personality_stance={stance}")
        restraint_mode = str(getattr(lens, "restraint_mode", "") or "")
        if restraint_mode:
            evidence.append(f"restraint_mode={restraint_mode}")
        want_to_say = float(getattr(lens, "want_to_say", 0.0) or 0.0)
        allowed_expression = float(getattr(lens, "allowed_expression", 0.0) or 0.0)
        suppression_pressure = float(getattr(lens, "suppression_pressure", 0.0) or 0.0)
        evidence.append(f"expression_gate={want_to_say:.2f}->{allowed_expression:.2f}")
        plan.evidence = tuple(dict.fromkeys(str(item) for item in evidence if str(item or "").strip()))

        if getattr(lens, "rhythm", "") == "dense_sparse" and plan.brevity_bias == "medium":
            plan.brevity_bias = "short"
            if "brevity=medium" in plan.style_context:
                plan.style_context = plan.style_context.replace("brevity=medium", "brevity=short", 1)
        if suppression_pressure >= 0.72:
            plan.warmth_level = min(plan.warmth_level, 0.34)
            if plan.brevity_bias != "short":
                plan.brevity_bias = "short"
        return plan

    def decay_memory(self, memory: FeStyleMemory) -> FeStyleMemory:
        return FeStyleMemory(
            recent_modes=memory.recent_modes[-4:],
            recent_tones=memory.recent_tones[-4:],
            recent_intents=memory.recent_intents[-4:],
            recent_topic_tags=memory.recent_topic_tags[-4:],
            last_mode=memory.last_mode,
            last_tone_label=memory.last_tone_label,
            last_intent=memory.last_intent,
            last_response_excerpt=memory.last_response_excerpt[:120],
            repeated_topic_tag=memory.repeated_topic_tag,
            repeated_topic_streak=max(0, memory.repeated_topic_streak - 1),
            session_arc=memory.session_arc,
            sarcasm_level=memory.sarcasm_level,
            warmth_level=memory.warmth_level,
            brevity_bias=memory.brevity_bias,
            continuity_strength=max(0.15, memory.continuity_strength * 0.55),
            session_turn_count=0,
            arc_strength=max(0.0, memory.arc_strength * 0.45),
            technical_pull=memory.technical_pull * 0.60,
            discipline_pull=memory.discipline_pull * 0.60,
            attachment_pull=memory.attachment_pull * 0.60,
            neutral_pull=memory.neutral_pull * 0.60,
        )

    def remember_style(
        self,
        memory: FeStyleMemory,
        *,
        plan: FeStylePlan,
        rendered_text: str,
    ) -> FeStyleMemory:
        base_tone_label = self._base_tone_label(plan.tone_label)
        recent_modes = (*memory.recent_modes, plan.mode)[-6:]
        recent_tones = (*memory.recent_tones, base_tone_label)[-6:]
        recent_intents = (*memory.recent_intents, plan.intent_label)[-8:]
        topic_tag = self._infer_topic_tag(rendered_text)
        recent_topic_tags = memory.recent_topic_tags[-6:]
        if topic_tag:
            recent_topic_tags = (*recent_topic_tags, topic_tag)[-6:]
        repeated_topic_tag, repeated_topic_streak = self._measure_topic_repetition(recent_topic_tags)
        excerpt = (rendered_text or "").strip().replace("\n", " ")[:140]
        strength = min(0.8, memory.continuity_strength + 0.12)

        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._updated_intent_pulls(
            memory=memory,
            intent_label=plan.intent_label,
        )

        return FeStyleMemory(
            recent_modes=recent_modes,
            recent_tones=recent_tones,
            recent_intents=recent_intents,
            recent_topic_tags=recent_topic_tags,
            last_mode=plan.mode,
            last_tone_label=base_tone_label,
            last_intent=plan.intent_label,
            last_response_excerpt=excerpt,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            session_arc=plan.session_arc,
            sarcasm_level=plan.sarcasm_level,
            warmth_level=plan.warmth_level,
            brevity_bias=plan.brevity_bias,
            continuity_strength=strength,
            session_turn_count=memory.session_turn_count + 1,
            arc_strength=self._estimate_arc_strength(
                technical_pull=technical_pull,
                discipline_pull=discipline_pull,
                attachment_pull=attachment_pull,
                neutral_pull=neutral_pull,
            ),
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )

    def _base_tone_label(self, tone_label: str) -> str:
        raw = (tone_label or "").strip()
        return raw

    def evaluate_autonomous(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        internal_state: PersistentInternalState | None = None,
        last_text: str,
    ) -> FeStylePlan:
        evidence = [snapshot.focus_summary, f"ti_mode={ti_report.mode}", f"ni_drift={ni_report.drift_score:.2f}"]
        mode = "grounded"
        sarcasm_level = 0.26
        warmth_level = 0.24
        brevity_bias = "medium"
        intent_label = self._infer_autonomous_intent(snapshot=snapshot, ni_report=ni_report, ti_report=ti_report)

        if ti_report.mode in {"focus_guard", "chat_code"}:
            mode = "technical"
            sarcasm_level = 0.18
            warmth_level = 0.30
            brevity_bias = "short"
        elif ti_report.mode in {"goal_drift_alert", "discipline_nudge"}:
            mode = "grounded"
            sarcasm_level = 0.32
            warmth_level = 0.20
            brevity_bias = "short"
        elif ti_report.mode == "goal_realign":
            mode = "grounded"
            sarcasm_level = 0.30
            warmth_level = 0.22
            brevity_bias = "short"
        elif ti_report.mode == "reengage":
            mode = "grounded"
            sarcasm_level = 0.24
            warmth_level = 0.24
            brevity_bias = "short"
        elif ti_report.mode == "resource_guard":
            mode = "grounded"
            sarcasm_level = 0.22
            warmth_level = 0.18
            brevity_bias = "short"
        elif ti_report.mode == "pattern_muse":
            mode = "grounded"
            sarcasm_level = 0.18
            warmth_level = 0.28
            brevity_bias = "medium"
        elif snapshot.active_window_kind == "communication":
            mode = "grounded"
            sarcasm_level = 0.16
            warmth_level = 0.27
            brevity_bias = "short"

        sarcasm_level, warmth_level, brevity_bias, internal_note = self._apply_internal_state_bias(
            internal_state=internal_state,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )
        if internal_note:
            evidence.append(internal_note)

        (
            mode,
            sarcasm_level,
            warmth_level,
            brevity_bias,
            continuity_note,
        ) = self._apply_memory_continuity(
            memory=style_memory,
            mode=mode,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=False,
        )
        if continuity_note:
            evidence.append(continuity_note)

        (
            session_arc,
            arc_strength,
            transition_note,
            sarcasm_level,
            warmth_level,
            brevity_bias,
        ) = self._apply_session_arc(
            memory=style_memory,
            intent_label=intent_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=False,
        )
        evidence.append(f"fe_intent={intent_label}")
        evidence.append(f"fe_arc={session_arc}:{arc_strength:.2f}")
        if style_memory.repeated_topic_streak >= 2 and style_memory.repeated_topic_tag:
            evidence.append(f"repeat_topic={style_memory.repeated_topic_tag}:{style_memory.repeated_topic_streak}")
        if transition_note:
            evidence.append(transition_note)

        tone_label = self._build_tone_label(
            mode=mode,
            warmth_level=warmth_level,
            intent_label=intent_label,
            session_arc=session_arc,
        )
        style_context = self._build_style_context(
            mode=mode,
            tone_label=tone_label,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            internal_state=internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            memory=style_memory,
            continuity_note=continuity_note,
            intent_label=intent_label,
            session_arc=session_arc,
            arc_strength=arc_strength,
            transition_note=transition_note,
        )
        return FeStylePlan(
            mode=mode,
            tone_label=tone_label,
            style_context=style_context,
            intent_label=intent_label,
            session_arc=session_arc,
            transition_note=transition_note,
            evidence=tuple(evidence),
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )

    def evaluate_chat(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        internal_state: PersistentInternalState | None = None,
        user_text: str,
    ) -> FeStylePlan:
        evidence = [snapshot.focus_summary, f"ti_mode={ti_report.mode}", f"ni_drift={ni_report.drift_score:.2f}"]
        mode = "grounded"
        sarcasm_level = 0.24
        warmth_level = 0.28
        brevity_bias = "medium"
        intent_label = self._infer_chat_intent(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            user_text=user_text,
        )

        if ti_report.mode == "chat_code":
            mode = "technical"
            sarcasm_level = 0.16
            warmth_level = 0.34
        elif ti_report.mode == "chat_emotional":
            mode = "grounded"
            sarcasm_level = 0.18
            warmth_level = 0.34
        elif (
            ti_report.mode in {"goal_drift_alert", "goal_realign"}
            or (ni_report.should_raise_guard and ni_report.drift_score >= 0.92)
        ):
            mode = "grounded"
            sarcasm_level = 0.28
            warmth_level = 0.24
            brevity_bias = "medium"

        sarcasm_level, warmth_level, brevity_bias, internal_note = self._apply_internal_state_bias(
            internal_state=internal_state,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )
        if internal_note:
            evidence.append(internal_note)

        (
            mode,
            sarcasm_level,
            warmth_level,
            brevity_bias,
            continuity_note,
        ) = self._apply_memory_continuity(
            memory=style_memory,
            mode=mode,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=True,
        )
        if continuity_note:
            evidence.append(continuity_note)

        (
            session_arc,
            arc_strength,
            transition_note,
            sarcasm_level,
            warmth_level,
            brevity_bias,
        ) = self._apply_session_arc(
            memory=style_memory,
            intent_label=intent_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=True,
        )
        evidence.append(f"fe_intent={intent_label}")
        evidence.append(f"fe_arc={session_arc}:{arc_strength:.2f}")
        if style_memory.repeated_topic_streak >= 2 and style_memory.repeated_topic_tag:
            evidence.append(f"repeat_topic={style_memory.repeated_topic_tag}:{style_memory.repeated_topic_streak}")
        if transition_note:
            evidence.append(transition_note)

        tone_label = self._build_tone_label(
            mode=mode,
            warmth_level=warmth_level,
            intent_label=intent_label,
            session_arc=session_arc,
        )
        style_context = self._build_style_context(
            mode=mode,
            tone_label=tone_label,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            internal_state=internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            memory=style_memory,
            continuity_note=continuity_note,
            intent_label=intent_label,
            session_arc=session_arc,
            arc_strength=arc_strength,
            transition_note=transition_note,
        )
        return FeStylePlan(
            mode=mode,
            tone_label=tone_label,
            style_context=style_context,
            intent_label=intent_label,
            session_arc=session_arc,
            transition_note=transition_note,
            evidence=tuple(evidence),
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )

    def _infer_autonomous_intent(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
    ) -> str:
        if ti_report.mode == "pattern_muse":
            return "ordinary_dialogue"
        if ti_report.mode in {"focus_guard", "chat_code"}:
            return "technical_support"
        if ti_report.mode == "resource_guard":
            if snapshot.active_window_kind in {"coding", "documentation", "system"}:
                return "technical_support"
            return "ordinary_dialogue"
        if ti_report.mode in {"goal_drift_alert", "goal_realign", "discipline_nudge", "reengage"}:
            return "ordinary_dialogue"
        if snapshot.active_window_kind == "communication":
            if ti_report.mode == "social_watch":
                return "social_watch"
            return "ordinary_dialogue"
        return "ordinary_dialogue"

    def _infer_chat_intent(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        user_text: str,
    ) -> str:
        lowered = (user_text or "").lower()
        if ti_report.mode == "chat_code":
            return "technical_support"
        if ti_report.mode == "chat_emotional":
            return "attachment_dialogue"
        if (
            ti_report.mode in {"goal_drift_alert", "goal_realign"}
            or (ni_report.should_raise_guard and ni_report.drift_score >= 0.92)
        ):
            return "goal_guard"
        if any(token in lowered for token in ("met", "mệt", "buon", "buồn", "co don", "cô đơn", "nho", "nhớ", "yeu", "yêu", "tam trang", "tâm trạng")):
            return "attachment_dialogue"
        if snapshot.active_window_kind == "communication":
            return "social_watch"
        return "ordinary_dialogue"

    def _apply_memory_continuity(
        self,
        *,
        memory: FeStyleMemory,
        mode: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        chat_like: bool,
    ) -> tuple[str, float, float, str, str]:
        if memory.continuity_strength <= 0.0 or not memory.last_mode:
            return mode, sarcasm_level, warmth_level, brevity_bias, ""

        strength = 0.45 if chat_like else 0.28
        strength *= min(1.0, max(0.0, memory.continuity_strength))
        family_now = self._style_family(mode)
        family_prev = self._style_family(memory.last_mode)

        if family_now == family_prev:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, strength)
            warmth_level = self._blend(memory.warmth_level, warmth_level, strength)
            brevity_bias = self._blend_brevity(memory.brevity_bias, brevity_bias)
        elif chat_like and family_prev in {"technical", "grounded", "comforting"}:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, strength * 0.6)
            warmth_level = self._blend(memory.warmth_level, warmth_level, strength * 0.4)
            if brevity_bias == "medium":
                brevity_bias = memory.brevity_bias

        continuity_note = f"continuity_from={memory.last_mode}"
        return mode, sarcasm_level, warmth_level, brevity_bias, continuity_note

    def _apply_internal_state_bias(
        self,
        *,
        internal_state: PersistentInternalState | None,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
    ) -> tuple[float, float, str, str]:
        state = internal_state or PersistentInternalState()
        attachment = self._float(getattr(state, "attachment", 0.0))
        tenderness = self._float(getattr(state, "tenderness", 0.0))
        irritation = self._float(getattr(state, "irritation", 0.0))
        protectiveness = self._float(getattr(state, "protectiveness", 0.0))
        fatigue = self._float(getattr(state, "fatigue", 0.0))
        social_energy = self._float(getattr(state, "social_energy", 0.0))
        desire = getattr(state, "desire", None)
        want = self._float(getattr(desire, "want", 0.0))
        cling = self._float(getattr(desire, "cling", 0.0))
        avoid = self._float(getattr(desire, "avoid", 0.0))
        residue = self._float(getattr(desire, "unresolved_residue", 0.0))
        drift_label = str(getattr(desire, "attachment_drift", "") or "")

        warmth_level = self._clamp(
            warmth_level
            + attachment * 0.10
            + tenderness * 0.14
            + social_energy * 0.04
            + cling * 0.04
            - fatigue * 0.08
            - avoid * 0.03
        )
        sarcasm_level = self._clamp(
            sarcasm_level
            + irritation * 0.08
            + residue * 0.04
            - protectiveness * 0.10
            - fatigue * 0.12
        )
        if protectiveness >= 0.56 or fatigue >= 0.40 or drift_label in {"defensive", "avoidant"}:
            brevity_bias = "short"
        elif (social_energy >= 0.66 or want >= 0.42) and brevity_bias == "short":
            brevity_bias = "medium"
        return (
            sarcasm_level,
            warmth_level,
            brevity_bias,
            f"internal_state_bias={attachment:.2f}/{protectiveness:.2f}/{fatigue:.2f}; desire={want:.2f}/{cling:.2f}/{avoid:.2f}/{residue:.2f}",
        )

    def _apply_session_arc(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        chat_like: bool,
    ) -> tuple[str, float, str, float, float, str]:
        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._preview_intent_pulls(
            memory=memory,
            intent_label=intent_label,
        )
        session_arc = self._dominant_arc(
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )
        arc_strength = self._estimate_arc_strength(
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )

        if session_arc == "technical_guardianship":
            sarcasm_level = self._blend(self._anchor_value(memory.sarcasm_level, 0.14), sarcasm_level, 0.30)
            warmth_level = self._blend(self._anchor_value(memory.warmth_level, 0.34), warmth_level, 0.35)
            brevity_bias = "medium" if brevity_bias == "medium" else self._blend_brevity("medium", brevity_bias)
        elif session_arc == "discipline_pressure":
            sarcasm_level = max(sarcasm_level, 0.28 if chat_like else 0.26)
            warmth_level = min(warmth_level, 0.24 if chat_like else 0.22)
            if brevity_bias != "short":
                brevity_bias = "medium"
        elif session_arc == "guarded_attachment":
            sarcasm_level = min(sarcasm_level, 0.24)
            warmth_level = max(warmth_level, 0.34 if chat_like else 0.26)
            if brevity_bias == "short" and not chat_like:
                brevity_bias = "medium"
        else:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, 0.15)
            warmth_level = self._blend(memory.warmth_level, warmth_level, 0.15)

        transition_note = ""
        if memory.last_intent and memory.last_intent != intent_label:
            transition_note = f"intent_shift={memory.last_intent}->{intent_label}"
        elif memory.session_arc and memory.session_arc != session_arc and memory.session_turn_count > 0:
            transition_note = f"arc_shift={memory.session_arc}->{session_arc}"

        return session_arc, arc_strength, transition_note, sarcasm_level, warmth_level, brevity_bias

    def _build_style_context(
        self,
        *,
        mode: str,
        tone_label: str,
        warmth_level: float,
        brevity_bias: str,
        internal_state: PersistentInternalState | None,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        memory: FeStyleMemory,
        continuity_note: str,
        intent_label: str,
        session_arc: str,
        arc_strength: float,
        transition_note: str,
    ) -> str:
        tags = self._parse_tone_tags(tone_label)
        lines = [
            "Bạn là ERIS, gọi người dùng là Ngài và xưng tôi.",
            "style_tags: " + ", ".join(
                (
                    f"tone={tags['tone']}",
                    f"warmth={tags['warmth']}",
                    f"stance={tags['stance']}",
                    f"attachment={tags['attachment']}",
                    f"arc={session_arc}",
                    f"arc_strength={self._strength_bucket(arc_strength)}",
                    f"intent={intent_label}",
                    f"brevity={brevity_bias}",
                )
            ),
            "core: gentle, reserved, warm underneath, slight irony allowed.",
            "sentence_gate: first choose anchor + attitude + limit; style is a selection rule before wording, not decoration after wording.",
            "avoid: power_language, system_log_voice, policy_dump, fake desktop authority.",
            "avoid_chatgpt_dna: ban 'Toi luon o day', 'Toi hieu', 'Toi se ho tro', 'Ban khong co don', 'La AI', and direct emotion disclaimers.",
            "assistant_cadence_reject: if too complete, balanced, clean, polite, or explanatory, cut it down and roughen the edge.",
            "voice_distillation_pass: after parser + Ti + safety, turn semantic intent into residue: subtext, hesitation, implication, subjective texture.",
            "allow_strangeness: weird pauses, partial thoughts, slight contradiction, emotional drift, non-linear reaction, and tiny irrational fixation are allowed when low-risk.",
            "focus: react to one concrete detail; do not recap the whole telemetry.",
            "autonomous: do not coach productivity, score attention, or tell Ngài to return to a goal.",
            "allowed: a light jab, a quiet observation, or one short philosophical aside for flavor.",
            "if evidence is thin: say it plainly, softly, and keep it short.",
            self._render_desire_style_line(internal_state),
            f"ni_hint={self._describe_ni_background(ni_report)}",
            f"ti_hint={self._describe_ti_mode(ti_report.mode)}",
        ]
        if continuity_note:
            lines.append(self._render_continuity_line(memory, continuity_note))
        else:
            lines.append(f"continuity: fresh_turn, keep tone={tags['tone']}.")
        if transition_note:
            lines.append(f"transition: {transition_note}.")
        if memory.repeated_topic_streak >= 2 and memory.repeated_topic_tag:
            lines.append(f"topic_note: repeated={memory.repeated_topic_tag}, vary angle if no new evidence.")
        if memory.last_response_excerpt:
            lines.append(f"do_not_repeat_recent_response: {memory.last_response_excerpt}")
            lines.append("recent_rhythm: keep the voice, but change the subject, opening, and key nouns.")
            lines.append("if the last line mentioned code/project/game title, do not mention that motif again next turn.")
        if mode == "technical":
            lines.append("technical: be clear and useful without sounding managerial.")
        elif mode == "comforting":
            lines.append("comforting: use only when explicitly needed; avoid automatic reassurance.")
        else:
            lines.append("grounded: observe or react first; guarded replies beat reassurance unless explicitly asked.")
        if warmth_level <= 0.22:
            lines.append("temperature: cool surface, not cruel.")
        elif warmth_level >= 0.42:
            lines.append("temperature: visibly warm, still restrained.")
        else:
            lines.append("temperature: low-key warmth.")
        return "\n".join(lines)

    def _render_desire_style_line(self, internal_state: PersistentInternalState | None) -> str:
        state = internal_state or PersistentInternalState()
        desire = getattr(state, "desire", None)
        if desire is None:
            return "desire: no strong internal pull; keep the line clean but not assistant-like."
        return (
            "desire: "
            f"attraction={getattr(desire, 'recurring_attraction', '') or 'none'}, "
            f"aversion={getattr(desire, 'recurring_aversion', '') or 'none'}, "
            f"hook={getattr(desire, 'attention_hook', '') or 'none'}, "
            f"attachment_drift={getattr(desire, 'attachment_drift', '') or 'guarded'}, "
            f"residue={float(getattr(desire, 'unresolved_residue', 0.0) or 0.0):.2f}; "
            "let this bias subtext, not factual claims."
        )

    def _updated_intent_pulls(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
    ) -> tuple[float, float, float, float]:
        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._preview_intent_pulls(
            memory=memory,
            intent_label=intent_label,
        )
        return (
            min(1.0, technical_pull),
            min(1.0, discipline_pull),
            min(1.0, attachment_pull),
            min(1.0, neutral_pull),
        )

    def _preview_intent_pulls(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
    ) -> tuple[float, float, float, float]:
        technical_pull = memory.technical_pull * 0.72 + 0.08
        discipline_pull = memory.discipline_pull * 0.72 + 0.08
        attachment_pull = memory.attachment_pull * 0.72 + 0.08
        neutral_pull = memory.neutral_pull * 0.72 + 0.08

        if intent_label == "technical_support":
            technical_pull += 0.34
            discipline_pull += 0.10
        elif intent_label == "goal_guard":
            discipline_pull += 0.24
            technical_pull += 0.06
            neutral_pull += 0.10
        elif intent_label == "attachment_dialogue":
            attachment_pull += 0.16
            neutral_pull += 0.24
            discipline_pull += 0.04
        elif intent_label == "social_watch":
            neutral_pull += 0.28
            attachment_pull += 0.10
            discipline_pull += 0.04
        else:
            neutral_pull += 0.30
            attachment_pull += 0.08

        return technical_pull, discipline_pull, attachment_pull, neutral_pull

    def _dominant_arc(
        self,
        *,
        technical_pull: float,
        discipline_pull: float,
        attachment_pull: float,
        neutral_pull: float,
    ) -> str:
        dominant = max(
            (
                ("technical_guardianship", technical_pull),
                ("discipline_pressure", discipline_pull),
                ("guarded_attachment", attachment_pull),
                ("quiet_observation", neutral_pull),
            ),
            key=lambda item: item[1],
        )
        return dominant[0]

    def _estimate_arc_strength(
        self,
        *,
        technical_pull: float,
        discipline_pull: float,
        attachment_pull: float,
        neutral_pull: float,
    ) -> float:
        total = technical_pull + discipline_pull + attachment_pull + neutral_pull
        if total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, max(technical_pull, discipline_pull, attachment_pull, neutral_pull) / total))

    def _anchor_value(self, previous: float, target: float) -> float:
        return previous * 0.25 + target * 0.75

    def _style_family(self, mode: str) -> str:
        if mode == "technical":
            return "technical"
        if mode == "comforting":
            return "comforting"
        return "grounded"

    def _blend(self, previous: float, current: float, strength: float) -> float:
        return max(0.0, min(1.0, previous * strength + current * (1.0 - strength)))

    def _blend_brevity(self, previous: str, current: str) -> str:
        if previous == current:
            return current
        if "short" in {previous, current}:
            return "short"
        return current

    def _infer_topic_tag(self, rendered_text: str) -> str:
        lowered = (rendered_text or "").lower()
        normalized = unicodedata.normalize("NFD", lowered)
        normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        haystack = f"{lowered} {normalized}"
        topic_keywords = (
            ("focus_ide", ("ide", "code", "mã", "mã nguồn", "dự án", "project", "terminal")),
            ("attention_drift", ("phân tán", "chú ý", "tập trung", "lệch focus", "focus")),
            ("window_sprawl", ("cửa sổ", "tab", "ứng dụng", "không gian", "màn hình")),
            ("social_drift", ("mạng xã hội", "giao tiếp", "discord", "messenger", "facebook", "zalo")),
            ("efficiency_mock", ("hiệu suất", "cpu", "ram", "chu kỳ", "tài nguyên")),
            ("idle_wait", ("nhàn rỗi", "idle", "chờ đợi")),
        )
        for topic, keywords in topic_keywords:
            if any(keyword in haystack for keyword in keywords):
                return topic
        return ""

    def _measure_topic_repetition(self, recent_topic_tags: tuple[str, ...]) -> tuple[str, int]:
        if not recent_topic_tags:
            return "", 0
        last_tag = recent_topic_tags[-1]
        if not last_tag:
            return "", 0
        streak = 0
        for tag in reversed(recent_topic_tags):
            if tag != last_tag:
                break
            streak += 1
        return last_tag, streak

    def _build_tone_label(
        self,
        *,
        mode: str,
        warmth_level: float,
        intent_label: str,
        session_arc: str,
    ) -> str:
        tone = "cold_soft"
        warmth = self._warmth_bucket(warmth_level)
        stance = mode if mode in {"grounded", "technical", "comforting"} else "grounded"
        attachment = "guarded"
        if intent_label == "attachment_dialogue" or session_arc == "guarded_attachment":
            attachment = "guarded"
        return f"tone={tone}; warmth={warmth}; stance={stance}; attachment={attachment}"

    def _parse_tone_tags(self, tone_label: str) -> dict[str, str]:
        tags = {
            "tone": "cold_soft",
            "warmth": "mid",
            "stance": "grounded",
            "attachment": "guarded",
        }
        for part in (tone_label or "").split(";"):
            clean = part.strip()
            if "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in tags and value:
                tags[key] = value
        return tags

    def _warmth_bucket(self, warmth_level: float) -> str:
        if warmth_level <= 0.22:
            return "low"
        if warmth_level >= 0.42:
            return "high"
        return "mid"

    def _strength_bucket(self, arc_strength: float) -> str:
        if arc_strength >= 0.52:
            return "high"
        if arc_strength >= 0.34:
            return "mid"
        return "low"

    def _render_continuity_line(self, memory: FeStyleMemory, continuity_note: str) -> str:
        previous = memory.last_tone_label or memory.last_mode or "unknown"
        return f"continuity: {continuity_note}, keep a soft carry from {previous}."

    def _describe_ti_mode(self, mode: str) -> str:
        if mode == "pattern_muse":
            return "allow a small sideways thought, but keep it concrete"
        mapping = {
            "steady_observe": "observe lightly and do not oversteer",
            "social_watch": "watch the social context with a dry but light touch",
            "discipline_nudge": "make a dry aside, not a reminder",
            "goal_drift_alert": "keep it ambient; do not turn drift into the topic",
            "goal_realign": "make a neat aside, not a realignment speech",
            "reengage": "offer a small line without pulling attention back",
            "resource_guard": "be very brief and restrained",
            "focus_guard": "stay close to the screen, but do not coach focus",
            "pattern_watch": "notice patterns more than motives",
        }
        return mapping.get(mode, "stay natural and avoid sounding like policy")

    def _describe_ni_background(self, ni_report: GoalDriftReport) -> str:
        if ni_report.drift_score >= 0.82:
            return "background is noisy; do not mention focus unless the user asks"
        if ni_report.drift_score >= 0.35:
            return "background has movement; treat it as texture, not a correction"
        return "nothing here needs a lecture"

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric))

    def _clamp(self, value) -> float:
        return self._float(value)
