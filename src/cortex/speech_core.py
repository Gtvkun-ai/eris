import re
from typing import Mapping

from .contracts import AgentSpeechCore, MotivationalPressureReport, MotivationalUrge, SelfState, SilenceState, SpeechImpulse
from .internal_state import PersistentInternalState
from .inner_thought import InnerThoughtEngine
from .modes import QUIET_MODES as SHARED_QUIET_MODES
from .spontaneous_life import SpontaneousLifeEngine
from .agent_mind_persistence import PersistentAgentMindStore


class SpeechCoreEngine:
    """Bộ chọn chung về thời điểm nói, căn cứ của dòng và kiểu phát âm của nó."""

    QUIET_MODES = SHARED_QUIET_MODES

    EMOTIONAL_TERMS = (
        "buon",
        "cang",
        "can toi",
        "co don",
        "khoc",
        "lo lang",
        "met",
        "sad",
        "stress",
        "tired",
        "upset",
        "worried",
    )

    DYNAMIC_FALLBACK_INTENTS = frozenset({
        "random_chatter",
        "inner_whim",
        "social_presence",
        "micro_presence",
        "indirect_presence",
        "guarded_reply",
        "micro_observation",
        "curious_question",
        "screen_observation",
        "light_muse",
        "telemetry_comment",
        "vision_comment",
    })

    def __init__(
        self,
        *,
        inner_thought_engine: InnerThoughtEngine | None = None,
        spontaneous_life_engine: SpontaneousLifeEngine | None = None,
    ):
        self.inner_thought_engine = inner_thought_engine or InnerThoughtEngine()
        self.spontaneous_life_engine = spontaneous_life_engine or SpontaneousLifeEngine()

    def fallback_intent(self, speech_core: AgentSpeechCore | None) -> str:
        if speech_core is None:
            return "micro_presence"
        inner_intent = str(getattr(getattr(speech_core, "inner_thought", None), "intent", "") or "")
        utterance_type = str(getattr(speech_core, "utterance_type", "") or "")
        speech_source = str(getattr(speech_core, "speech_source", "") or "")
        if utterance_type in {"telemetry_comment", "vision_comment"} or speech_source in {"vision", "telemetry"}:
            return "screen_observation"
        for candidate in (inner_intent, utterance_type):
            if candidate == "curious_question":
                return candidate
            if candidate in self.DYNAMIC_FALLBACK_INTENTS:
                return candidate
        return "micro_presence"

    def fallback_context(
        self,
        speech_core: AgentSpeechCore | None,
        *,
        snapshot=None,
        momentum_topic: str = "",
    ) -> dict[str, str]:
        inner_thought = getattr(speech_core, "inner_thought", None) if speech_core is not None else None
        return {
            "focus_kind": str(getattr(snapshot, "active_window_kind", "") or ""),
            "window_title": str(
                getattr(snapshot, "active_window", "")
                or getattr(snapshot, "active_app", "")
                or ""
            ),
            "momentum_topic": str(
                momentum_topic
                or getattr(inner_thought, "topic_seed", "")
                or getattr(inner_thought, "evidence_anchor", "")
                or ""
            ),
        }

    def render_force_speak_repair_text(
        self,
        speech_core: AgentSpeechCore | None,
        *,
        normalize_text,
        is_near_duplicate,
        last_text: str = "",
        counter: int = 1,
        repeated: bool = False,
        snapshot=None,
        momentum_topic: str = "",
        intent: str = "",
    ) -> str:
        """Compatibility hook: request dynamic wording, never emit template text.

        SpeechCore is allowed to decide that a tiny fallback line is needed, but
        it is not allowed to own the public wording.  Older post-generation
        guards still call this method; instead of returning a canned sentence,
        we stamp the request onto AgentSpeechCore and let the wording layer
        reroll from the current pressure/context.
        """
        resolved_intent = intent or self.fallback_intent(speech_core)
        self._mark_dynamic_fallback_request(
            speech_core,
            intent=resolved_intent,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
            repeated=repeated,
            counter=counter,
        )
        return ""

    def render_safe_fallback_text(
        self,
        speech_core: AgentSpeechCore,
        *,
        normalize_text,
        is_near_duplicate,
        last_text: str = "",
        repeated: bool = False,
        snapshot=None,
        momentum_topic: str = "",
    ) -> str:
        """Compatibility hook: ask downstream wording layer for dynamic fallback.

        Returning a string here would reintroduce the old choke point.  The
        post-generation layer should see an empty string and call the local
        micro-wording/reroll service, or keep silence/body-only if no generator
        is available.
        """
        self._mark_dynamic_fallback_request(
            speech_core,
            intent=self.fallback_intent(speech_core),
            snapshot=snapshot,
            momentum_topic=momentum_topic,
            repeated=repeated,
        )
        return ""

    def _mark_dynamic_fallback_request(
        self,
        speech_core: AgentSpeechCore | None,
        *,
        intent: str,
        snapshot=None,
        momentum_topic: str = "",
        repeated: bool = False,
        counter: int = 1,
    ) -> dict[str, str]:
        context = self.fallback_context(
            speech_core,
            snapshot=snapshot,
            momentum_topic=momentum_topic,
        )
        context.update({
            "fallback_intent": str(intent or "micro_presence"),
            "fallback_repeated": "1" if repeated else "0",
            "fallback_counter": str(max(1, int(counter or 1))),
        })
        if speech_core is not None:
            try:
                speech_core.requires_dynamic_fallback = True
                speech_core.fallback_intent = str(intent or "micro_presence")
                speech_core.fallback_context = dict(context)
            except Exception:
                pass
        return context

    def _force_speak_fallback_by_intent_text(
        self,
        intent: str,
        *,
        normalize_text,
        is_near_duplicate,
        last_text: str = "",
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        # Legacy private API kept for callers that have not been migrated yet.
        # It intentionally returns no wording; public text must be generated by
        # LLM wording / local micro-presence layer.
        return ""

    def _screen_fallback_anchor(
        self,
        *,
        normalize_text,
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        raw_topic = str(momentum_topic or "")
        topic = re.sub(r"[_:]+", " ", raw_topic).strip(" .:-")
        if topic and not self._looks_internal_topic(raw_topic, normalize_text=normalize_text):
            return topic[:120]
        title = re.sub(r"\s+", " ", str(window_title or "")).strip()
        return title[:120] if title else "tín hiệu hiện tại"

    def _thought_surface_template(self, *args, **kwargs) -> str:
        return ""

    def _light_presence_template(self, *args, **kwargs) -> str:
        return ""

    def _public_thought_topic(self, value: str, *, normalize_text) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or self._looks_internal_topic(text, normalize_text=normalize_text):
            return ""
        text = re.sub(r"^[a-z_]+:", "", text, flags=re.IGNORECASE).strip()
        text = text.replace("_", " ")
        if len(text) > 60:
            text = text[:57].rstrip() + "..."
        return text

    def _looks_internal_topic(self, value: str, *, normalize_text) -> bool:
        normalized = str(normalize_text(value) or "")
        if not normalized:
            return False
        internal_markers = (
            "associative_drift",
            "cognitive_tension",
            "input_disturbance",
            "force_speak",
            "memory_replay",
            "norm_active_window_kind",
            "loop_",
            "thought_",
            "subconscious",
        )
        return any(marker in normalized for marker in internal_markers)

    def _small_soft_fallback_ladder_text(self, *args, **kwargs) -> str:
        return ""

    def evaluate(
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state: PersistentInternalState | None = None,
        appraisal=None,
        broadcast=None,
        ti_report=None,
        fe_plan=None,
        style_memory=None,
        concrete_signals: tuple[str, ...] = (),
        vision_signals: tuple[str, ...] = (),
        telemetry_signals: tuple[str, ...] = (),
        screen_comment_allowed: bool = True,
        repeat_count: int = 1,
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
        recent_inner_intents: tuple[str, ...] = (),
        recent_inner_seeds: tuple[str, ...] = (),
        ni_state_label: str = "",
        ni_report=None,
        subconscious_seed=None,
        thought_surface=None,
        self_state: SelfState | None = None,
        meaning_layer=None,
        personality_lens=None,
        safe_small_talk_allowed: bool = False,
        spontaneous_impulse: SpeechImpulse | None = None,
        agent_mind: PersistentAgentMindStore | None = None,
        private_mind_speech_bias: Mapping[str, object] | None = None,
        conversation_context: str = "",
    ) -> AgentSpeechCore:
        channel_name = str(channel or "autonomous")
        private_bias_active = bool(private_mind_speech_bias)
        spontaneous_explicit = spontaneous_impulse is not None
        surface = thought_surface if thought_surface is not None else subconscious_seed
        emotional_signal = self._has_emotional_signal(
            concrete_signals=concrete_signals,
            broadcast=broadcast,
        )
        inner_thought = self.inner_thought_engine.evaluate(
            channel=channel_name,
            snapshot=snapshot,
            internal_state=internal_state,
            appraisal=appraisal,
            broadcast=broadcast,
            style_memory=style_memory,
            concrete_signals=tuple(concrete_signals or ()),
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            recent_inner_intents=recent_inner_intents,
            recent_inner_seeds=recent_inner_seeds,
            thought_surface=surface,
        )

        if spontaneous_impulse is None:
            # FIX #4: Truyền conversation_context để impulses có thể tham chiếu hội thoại.
            spontaneous_impulse = self.spontaneous_life_engine.evaluate(
                channel=channel_name,
                snapshot=snapshot,
                internal_state=internal_state,
                thought_surface=surface,
                personality_lens=personality_lens,
                relationship_state=getattr(internal_state, "relationship_dynamics", None) if internal_state is not None else None,
                concrete_signals=tuple(concrete_signals or ()),
                recent_speech_acts=tuple(getattr(internal_state, "recent_speech_acts", ()) or ()) if internal_state is not None else (),
                agent_mind=agent_mind,
                conversation_context=conversation_context,
            )
        spontaneous_ready = self._spontaneous_ready(spontaneous_impulse, channel=channel_name)

        extreme_internal_pressure = self._extreme_internal_speech_pressure(
            spontaneous_impulse=spontaneous_impulse,
            internal_state=internal_state,
            thought_surface=surface,
        )
        if ( #ERIS autonomous KHÔNG được nói chỉ vì telemetry thay đổi. Chỉ nói khi MeaningLayer báo có sự thay đổi về meaning, và nếu có meaning shift thì sẽ phải nói dù có signal nào đi nữa, còn nếu không có meaning shift thì sẽ chỉ nói khi có signal mạnh về meaning như weak_meaning, ambient_meaning hoặc vibe_signal, còn nếu không có signal mạnh về meaning thì sẽ không nói mà chỉ tạo một soft impression với lý do là MeaningLayer chỉ có tín hiệu yếu/ambient/vibe, nên nói như một ấn tượng mềm thay vì một quan sát cứng nhắc.
            channel_name == "autonomous"
            and meaning_layer is not None
            and not bool(getattr(meaning_layer, "meaning_shift", False))
            and not spontaneous_ready
            and not extreme_internal_pressure
            and self._meaning_shift_required_for_layer(meaning_layer)
            and not self._allows_soft_non_shift_speech(
                meaning_layer=meaning_layer,
                snapshot=snapshot,
                internal_state=internal_state,
            )
        ):
            pressure_report = self._build_suppressed_pressure_report(
                reason="meaning_shift_gate",
                threshold=self._threshold_for_channel(channel_name, self_state=self_state),
                concrete_signals=concrete_signals,
            )
            speech_impulse = self._build_speech_impulse(
                channel=channel_name,
                meaning_layer=meaning_layer,
                winner=pressure_report.winner,
                should_speak=False,
                spontaneous_impulse=spontaneous_impulse,
            )
            safety_flags = ("meaning_shift_gate",)
            return AgentSpeechCore(
                perception=tuple(concrete_signals or ()),
                mood=self._resolve_mood(snapshot=snapshot, appraisal=appraisal, fe_plan=fe_plan),
                impulse="silent",
                utterance_type="no_speech",
                grounding="none",
                speech_source="none",
                speech_risk_level="texture",
                reason=(
                    "MeaningLayer held silence because this speech shape needs a meaning shift: "
                    f"{str(getattr(meaning_layer, 'shift_reason', '') or 'no_meaning_shift')}."
                ),
                should_speak=False,
                safety_flags=safety_flags,
                delivery="silence",
                inner_thought=inner_thought,
                speech_impulse=speech_impulse,
                motivation_pressure=pressure_report,
                silence_state=self._build_silence_state(
                    reason="meaning_shift_gate",
                    inner_thought=inner_thought,
                    pressure_report=pressure_report,
                    speech_impulse=speech_impulse,
                    personality_lens=personality_lens,
                    safety_flags=safety_flags,
                ),
            )
        # Nếu user đang tập trung thật sự, ERIS phải câm.
        # Ngoại lệ dài hạn: áp lực nội sinh cực mạnh được quyền đi tiếp vào arbitration,
        # nhưng vẫn chỉ được tạo câu low-claim/no-screen-claim. Nếu không có ngoại lệ này,
        # quiet_guard sẽ chặn inner_whim trước khi SurfaceArbiter kịp cho nó tranh với micro_presence.
        if channel_name == "autonomous" and not extreme_internal_pressure and self._should_stay_silent(
            ti_mode=str(getattr(ti_report, "mode", "") or ""),
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
                ni_state_label=ni_state_label,
                ni_report=ni_report,
                internal_state=internal_state,
                self_state=self_state,
            ):
            pressure_report = self._build_suppressed_pressure_report(
                reason="quiet_guard",
                threshold=self._threshold_for_channel(channel_name, self_state=self_state),
                concrete_signals=concrete_signals,
            )
            speech_impulse = self._build_speech_impulse(
                channel=channel_name,
                meaning_layer=meaning_layer,
                winner=pressure_report.winner,
                should_speak=False,
                spontaneous_impulse=spontaneous_impulse,
            )
            safety_flags = ("repeat_guard",) if repeat_count >= 2 or repeated_topic_streak >= 2 else ()
            return AgentSpeechCore(
                perception=tuple(concrete_signals or ()),
                mood=self._resolve_mood(snapshot=snapshot, appraisal=appraisal, fe_plan=fe_plan),
                impulse="silent",
                utterance_type="no_speech",
                grounding="none",
                speech_source="none",
                speech_risk_level="texture",
                reason="SpeechCore held silence because the autonomous context is repeating or quiet.",
                should_speak=False,
                safety_flags=safety_flags,
                delivery="silence",
                inner_thought=inner_thought, # inner_thought vẫn được đánh giá và truyền vào AgentSpeechCore ngay cả khi giữ im lặng, vì inner_thought có thể chứa thông tin quan trọng cho các phần khác của hệ thống hoặc để giải thích lý do giữ im lặng
                speech_impulse=speech_impulse,
                motivation_pressure=pressure_report, # trả về pressure_report để giải thích lý do giữ im lặng
                silence_state=self._build_silence_state(
                    reason="quiet_guard",
                    inner_thought=inner_thought,
                    pressure_report=pressure_report,
                    speech_impulse=speech_impulse,
                    personality_lens=personality_lens,
                    safety_flags=safety_flags,
                ),
            )

        # đánh giá áp lực động lực bằng cách gọi _evaluate_motivational_pressure với các tham số phù hợp, sau đó xác định winner, speech_source, utterance_type, should_speak dựa trên winner, và nếu channel_name là force_speak thì sẽ ép should_speak là True và điều chỉnh speech_source và utterance_type nếu cần thiết
        #Đây gần như là “động lực tiền-ngôn-ngữ”.
        pressure_report = self._evaluate_motivational_pressure( 
            channel=channel_name,
            snapshot=snapshot,
            vision_signals=vision_signals,
            telemetry_signals=telemetry_signals,
            concrete_signals=concrete_signals,
            screen_comment_allowed=screen_comment_allowed,
            inner_thought=inner_thought,
            internal_state=internal_state,
            appraisal=appraisal,
            ti_report=ti_report,
            emotional_signal=emotional_signal,
            thought_surface=surface,
            self_state=self_state,
            meaning_layer=meaning_layer,
            personality_lens=personality_lens,
            safe_small_talk_allowed=safe_small_talk_allowed,
            spontaneous_impulse=spontaneous_impulse,
            spontaneous_explicit=spontaneous_explicit,
        )
        winner = pressure_report.winner
        speech_source = winner.speech_source or "none"
        utterance_type = winner.utterance_type or "no_speech"
        should_speak = speech_source != "none" and utterance_type != "no_speech"
        if channel_name == "force_speak":
            should_speak = True
            if speech_source == "none":
                speech_source = "random"
            if utterance_type == "no_speech":
                # P0: force_speak là explicit pull. Nếu impulse arbitration đã chọn
                # một xung nội sinh hợp lệ, đừng ép nó xuống micro_presence.
                # Micro-presence chỉ là đáy an toàn cuối cùng, không phải cửa chính.
                spontaneous_act = str(getattr(spontaneous_impulse, "suggested_speech_act", "") or "").strip()
                spontaneous_pressure = self._clamp01(getattr(spontaneous_impulse, "surface_pressure", 0.0))
                if spontaneous_explicit and spontaneous_ready and spontaneous_act and spontaneous_act != "no_speech" and spontaneous_pressure >= 0.22:
                    utterance_type = spontaneous_act
                    winner = MotivationalUrge(
                        label="force_speak_endogenous_fallback",
                        score=max(0.82, spontaneous_pressure),
                        utterance_type=utterance_type,
                        speech_source="freeform",
                        risk_level=str(getattr(spontaneous_impulse, "risk", "texture") or "texture"),
                        grounding="endogenous_anchor",
                        reason="Force speak recovered through endogenous impulse arbitration instead of micro-presence.",
                        evidence=tuple(str(item) for item in (getattr(spontaneous_impulse, "evidence", ()) or ()))[:6] or ("force_speak requested",),
                        safety_flags=("force_speak_required", "endogenous_anchor", "no_screen_claim"),
                    )
                    speech_source = "freeform"
                else:
                    utterance_type = "micro_presence"
                    winner = MotivationalUrge(
                        label="force_speak_fallback_presence",
                        score=1.0,
                        utterance_type=utterance_type,
                        speech_source=speech_source,
                        risk_level="micro_presence",
                        grounding="situated_residue",
                        reason="Force speak fell back to a tiny situated presence line.",
                        evidence=("force_speak requested",),
                        safety_flags=("force_speak_required", "situated_residue", "micro_presence"),
                    )
        speech_risk_level = self._risk_level_for_winner(
            winner=winner,
            speech_source=speech_source,
            utterance_type=utterance_type,
        )

        perception = self._resolve_perception(
            speech_source=speech_source,
            vision_signals=vision_signals,
            telemetry_signals=telemetry_signals,
            concrete_signals=concrete_signals,
            inner_thought=inner_thought,
        )
        safety_flags = self._build_safety_flags(
            channel=channel_name,
            speech_source=speech_source,
            utterance_type=utterance_type,
            emotional_signal=emotional_signal,
            inner_thought=inner_thought,
        )
        safety_flags = tuple(dict.fromkeys((*safety_flags, *tuple(winner.safety_flags or ()))))
        if private_bias_active:
            safety_flags = tuple(dict.fromkeys((*safety_flags, "private_mind_speech_bias")))
        speech_impulse = self._build_speech_impulse(
            channel=channel_name,
            meaning_layer=meaning_layer,
            winner=winner,
            should_speak=should_speak,
            spontaneous_impulse=spontaneous_impulse,
        )
        dynamic_fallback_context = self.fallback_context(
            None,
            snapshot=snapshot,
            momentum_topic=(
                str(getattr(inner_thought, "topic_seed", "") or "")
                or str(getattr(inner_thought, "evidence_anchor", "") or "")
            ),
        )
        dynamic_fallback_intent = self.fallback_intent(
            AgentSpeechCore(utterance_type=utterance_type, speech_source=speech_source, inner_thought=inner_thought)
        )
        requires_dynamic_fallback = bool(
            should_speak
            and speech_source in {"freeform", "random"}
            and (
                channel_name == "force_speak"
                or utterance_type in self.DYNAMIC_FALLBACK_INTENTS
                or "endogenous_anchor" in set(safety_flags)
            )
        )

        reason = self._build_reason(
            channel=channel_name,
            speech_source=speech_source,
            utterance_type=utterance_type,
            inner_thought=inner_thought,
            emotional_signal=emotional_signal,
        )
        if private_bias_active:
            reason = (
                f"{reason} PrivateMind speech bias is active as a soft wording/style pressure; "
                "it must not add facts or expose private reasoning."
            )

        return AgentSpeechCore(
            perception=perception,
            mood=self._resolve_mood(snapshot=snapshot, appraisal=appraisal, fe_plan=fe_plan),
            impulse="must_speak" if channel_name == "force_speak" else ("speak" if should_speak else "silent"),
            utterance_type=utterance_type if should_speak else "no_speech",
            grounding=(winner.grounding or self._grounding_for_source(speech_source)),
            speech_source=speech_source if should_speak else "none",
            speech_risk_level=speech_risk_level if should_speak else "texture",
            reason=reason,
            should_speak=should_speak,
            safety_flags=safety_flags,
            delivery="speak" if should_speak else "silence",
            inner_thought=inner_thought,
            speech_impulse=speech_impulse,
            motivation_pressure=pressure_report,
            silence_state=(
                SilenceState()
                if should_speak
                else self._build_silence_state(
                    reason=pressure_report.suppressed_by or "below_threshold",
                    inner_thought=inner_thought,
                    pressure_report=pressure_report,
                    speech_impulse=speech_impulse,
                    personality_lens=personality_lens,
                    safety_flags=safety_flags,
                )
            ),
            requires_dynamic_fallback=requires_dynamic_fallback,
            fallback_intent=dynamic_fallback_intent if requires_dynamic_fallback else "",
            fallback_context=dynamic_fallback_context if requires_dynamic_fallback else {},
        )

    def _evaluate_motivational_pressure(
        self,
        *,
        channel: str,
        snapshot,
        vision_signals: tuple[str, ...],
        telemetry_signals: tuple[str, ...],
        concrete_signals: tuple[str, ...],
        screen_comment_allowed: bool,
        inner_thought,
        internal_state: PersistentInternalState | None,
        appraisal,
        ti_report,
        emotional_signal: bool,
        thought_surface,
        self_state: SelfState | None,
        meaning_layer,
        personality_lens,
        safe_small_talk_allowed: bool,
        spontaneous_impulse: SpeechImpulse | None = None,
        spontaneous_explicit: bool = False,
    ) -> MotivationalPressureReport:
        threshold = self._threshold_for_channel(channel, self_state=self_state)
        candidates = self._build_urge_candidates(
            channel=channel,
            snapshot=snapshot,
            vision_signals=vision_signals,
            telemetry_signals=telemetry_signals,
            concrete_signals=concrete_signals,
            screen_comment_allowed=screen_comment_allowed,
            inner_thought=inner_thought,
            internal_state=internal_state,
            appraisal=appraisal,
            ti_report=ti_report,
            emotional_signal=emotional_signal,
            thought_surface=thought_surface,
            self_state=self_state,
            meaning_layer=meaning_layer,
            safe_small_talk_allowed=safe_small_talk_allowed,
            spontaneous_impulse=spontaneous_impulse,
            spontaneous_explicit=spontaneous_explicit,
        )
        candidates = self._apply_self_state_to_candidates(candidates, channel=channel, self_state=self_state)
        candidates = self._apply_personality_restraint_to_candidates(
            candidates,
            channel=channel,
            personality_lens=personality_lens,
        )
        ranked = tuple(sorted(candidates, key=lambda item: item.score, reverse=True))
        winner = next((item for item in ranked if not item.blocked), MotivationalUrge(label="silence_restraint", blocked=True))
        suppressed_by = ""
        if channel == "autonomous" and (winner.label == "silence_restraint" or winner.score < threshold):
            suppressed_by = "silence_restraint" if winner.label == "silence_restraint" else "below_threshold"
            winner = self._silence_urge(
                score=max(winner.score, self._score_restraint(internal_state=internal_state, ti_report=ti_report, self_state=self_state)),
                reason="MotivationalPressure kept silence because speaking pressure did not clear threshold.",
            )
        return MotivationalPressureReport(
            winner=winner,
            threshold=threshold,
            candidates=ranked,
            suppressed_by=suppressed_by,
        )

    def _build_urge_candidates(
        self,
        *,
        channel: str,
        snapshot,
        vision_signals: tuple[str, ...],
        telemetry_signals: tuple[str, ...],
        concrete_signals: tuple[str, ...],
        screen_comment_allowed: bool,
        inner_thought,
        internal_state: PersistentInternalState | None,
        appraisal,
        ti_report,
        emotional_signal: bool,
        thought_surface,
        self_state: SelfState | None,
        meaning_layer,
        safe_small_talk_allowed: bool,
        spontaneous_impulse: SpeechImpulse | None = None,
        spontaneous_explicit: bool = False,
    ) -> tuple[MotivationalUrge, ...]:
        state = internal_state or PersistentInternalState()
        desire = getattr(state, "desire", None)
        desire_want = self._float(getattr(desire, "want", 0.0))
        desire_cling = self._float(getattr(desire, "cling", 0.0))
        desire_avoid = self._float(getattr(desire, "avoid", 0.0))
        desire_anticipation = self._float(getattr(desire, "anticipation", 0.0))
        desire_residue = self._float(getattr(desire, "unresolved_residue", 0.0))
        threat = self._float(getattr(appraisal, "threat", 0.0) if appraisal is not None else 0.0)
        protectiveness = self._float(getattr(appraisal, "protectiveness", 0.0) if appraisal is not None else 0.0)
        tenderness = self._float(getattr(appraisal, "tenderness", 0.0) if appraisal is not None else 0.0)
        intimacy = self._float(getattr(appraisal, "intimacy", 0.0) if appraisal is not None else 0.0)
        amusement = self._float(getattr(appraisal, "amusement", 0.0) if appraisal is not None else 0.0)
        jealousy_lite = self._float(getattr(appraisal, "jealousy_lite", 0.0) if appraisal is not None else 0.0)
        fatigue = self._float(getattr(appraisal, "fatigue", 0.0) if appraisal is not None else getattr(state, "fatigue", 0.0))
        idle_seconds = max(0.0, self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0))
        mode = str(getattr(ti_report, "mode", "") or "")
        inner_intent = str(getattr(inner_thought, "intent", "") or "")
        inner_seed = str(getattr(inner_thought, "topic_seed", "") or "")
        inner_surface = bool(getattr(inner_thought, "should_surface", False))
        surface_mode = str(getattr(thought_surface, "mode", "") or "")
        surface_pressure = self._float(getattr(thought_surface, "pressure", 0.0) if thought_surface is not None else 0.0)
        surface_novelty = self._float(getattr(thought_surface, "novelty", 0.0) if thought_surface is not None else 0.0)
        surface_affordance = str(getattr(thought_surface, "affordance", "") or "")
        surface_momentum = self._float(getattr(thought_surface, "momentum_score", 0.0) if thought_surface is not None else 0.0)
        meaning_ready = (
            channel == "autonomous"
            and bool(str(getattr(meaning_layer, "meaning", "") or ""))
            and bool(getattr(meaning_layer, "meaning_shift", False))
        )

        candidates: list[MotivationalUrge] = []
        candidates.append(
            MotivationalUrge(
                label="screen_vision",
                score=0.0 if meaning_ready else (1.18 if screen_comment_allowed and vision_signals else 0.0),
                utterance_type="vision_comment",
                speech_source="vision",
                risk_level="hard_claim",
                grounding="screen_vision",
                reason="Visual evidence is concrete enough to speak from.",
                evidence=tuple(vision_signals[:2]),
                safety_flags=("grounded_screen_comment",),
                blocked=meaning_ready or not (screen_comment_allowed and vision_signals),
            )
        )
        candidates.append(
            MotivationalUrge(
                label="screen_telemetry",
                score=0.0 if meaning_ready else (1.10 if screen_comment_allowed and telemetry_signals else 0.0),
                utterance_type="telemetry_comment",
                speech_source="telemetry",
                risk_level="hard_claim",
                grounding="screen_telemetry",
                reason="Runtime telemetry evidence is concrete enough to speak from.",
                evidence=tuple(telemetry_signals[:2]),
                safety_flags=("grounded_screen_comment",),
                blocked=meaning_ready or not (screen_comment_allowed and telemetry_signals),
            )
        )

        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        meaning_shift = bool(getattr(meaning_layer, "meaning_shift", False))
        meaning_signal = str(getattr(meaning_layer, "meaning_signal", "") or "")
        meaning_reaction = str(getattr(meaning_layer, "reaction", "") or "")
        meaning_score = self._meaning_reaction_score(
            channel=channel,
            meaning_layer=meaning_layer,
            concrete_signals=concrete_signals,
        )
        candidates.append(
            MotivationalUrge(
                label="meaning_reaction",
                score=meaning_score,
                utterance_type=(
                    self._utterance_for_reaction(meaning_reaction, channel=channel, meaning=meaning)
                    if meaning_shift
                    else "micro_presence"
                ),
                speech_source="meaning",
                risk_level="soft_read",
                grounding="meaning_layer",
                reason="MeaningLayer found a semantic shift; SpeechCore should choose a reaction, not an observation.",
                evidence=tuple(str(item) for item in (getattr(meaning_layer, "evidence", ()) or ()))[:3],
                safety_flags=("meaning_layer_reaction", "meaning_not_speech", "react_to_residue_not_label"),
                blocked=channel != "autonomous" or not meaning_shift or not meaning or meaning_score <= 0.0,
            )
        )

        soft_meaning_score = self._soft_meaning_presence_score(
            channel=channel,
            meaning_layer=meaning_layer,
            snapshot=snapshot,
            internal_state=state,
        )
        candidates.append(
            MotivationalUrge(
                #    #Nó cho phép:weak meaning, ambient meaning,vibe signal được leak thành micro presence nhẹ.
                label="soft_meaning_presence",
                score=soft_meaning_score,
                utterance_type="micro_presence",
                speech_source="freeform",
                risk_level="micro_presence",
                grounding="subjective_vibe",
                reason="MeaningLayer only has weak/ambient/vibe signal, so speak as a soft impression rather than a hard observation.",
                evidence=tuple(str(item) for item in (getattr(meaning_layer, "evidence", ()) or ()))[:3],
                safety_flags=("soft_impression", "no_hard_fact_claim", meaning_signal or "weak_meaning"),
                blocked=channel != "autonomous"
                or meaning_shift
                or soft_meaning_score <= 0.0
                or meaning_signal not in {"weak_meaning", "ambient_meaning", "vibe_signal"},
            )
        )

        residual_score = self._residual_continuity_score(
            channel=channel,
            meaning_layer=meaning_layer,
            snapshot=snapshot,
            internal_state=state,
            thought_surface=thought_surface,
        )
        candidates.append(
            MotivationalUrge(
                label="residual_continuity_pull", #Đây là “dư âm chưa tan”.
                score=residual_score,
                utterance_type="micro_presence",
                speech_source="freeform",
                risk_level="micro_presence",
                grounding="situated_residue",
                reason=(
                    "No semantic novelty, but continuity/resonance has enough pull for a low-energy "
                    "residue fragment."
                ),
                evidence=tuple(
                    str(item)
                    for item in (
                        f"meaning_signal={meaning_signal or 'none'}",
                        f"shift={meaning_shift}",
                        *(getattr(meaning_layer, "attention_bias", ()) or ()),
                    )
                    if str(item or "").strip()
                )[:5],
                safety_flags=(
                    "residual_continuity",
                    "low_energy_fragment",
                    "no_hard_fact_claim",
                    "meaning_not_speech",
                ),
                blocked=channel != "autonomous" or meaning_shift or not meaning or residual_score <= 0.0,
            )
        )

        candidates.append(
            MotivationalUrge(
                label="chat_reply",
                score=1.30 if channel == "chat" else 0.0,
                utterance_type="mirror",
                speech_source="freeform",
                risk_level="texture",
                grounding="conversation_turn",
                reason="The user opened an explicit chat turn; reply through the full speech pipeline.",
                evidence=("chat message",),
                safety_flags=("user_requested_chat", "conversation_grounded"),
                blocked=channel != "chat",
            )
        )

        # Tính spontaneous trước micro_presence để force_speak có thể nhường lượt
        # cho nội sinh trước khi rơi xuống câu presence máy móc.
        spontaneous = spontaneous_impulse or SpeechImpulse()
        spontaneous_pressure = self._clamp01(getattr(spontaneous, "surface_pressure", 0.0))
        spontaneous_act = str(getattr(spontaneous, "suggested_speech_act", "") or "").strip() or "inner_whim"
        force_speak_no_screen_internal_ready = (
            channel == "force_speak"
            and spontaneous_explicit
            and not concrete_signals
            and spontaneous_pressure >= 0.24
            and spontaneous_act != "no_speech"
            and not bool(getattr(spontaneous, "needs_external_evidence", False))
        )
        user_requested_score = (
            0.92
            + self._pressure(state, "social_pressure") * 0.20
            + self._pressure(state, "tender_pressure") * 0.08
            - fatigue * 0.08
        )
        if force_speak_no_screen_internal_ready:
            # Đạp micro_presence xuống khi có xung nội sinh đủ sạch. Nếu không làm
            # vậy, force_speak cứ rơi vào câu presence nhỏ, còn thought stream thì
            # đứng ngoài cửa nhìn vào như intern không có thẻ ra vào.
            user_requested_score = min(user_requested_score, 0.34)
        candidates.append(
            MotivationalUrge(
                label="micro_presence",
                score=user_requested_score if channel == "force_speak" else 0.0,
                utterance_type=self._inner_utterance(inner_intent, fallback="micro_presence"),
                speech_source="freeform",
                risk_level="micro_presence",
                grounding="situated_residue",
                reason="User explicitly requested a small situated residue, not a presence declaration.",
                evidence=(self._inner_anchor(inner_thought) or "force_speak requested",),
                safety_flags=("force_speak_required", "situated_residue", "micro_presence", "anti_presence_declaration"),
                blocked=channel != "force_speak" or force_speak_no_screen_internal_ready,
            )
        )

        protective_score = max(protectiveness, threat, self._pressure(state, "protective_pressure")) + (0.12 if mode == "resource_guard" else 0.0)
        candidates.append(
            MotivationalUrge(
                label="protective_guard",
                score=protective_score,
                utterance_type="soft_boundary",
                speech_source="freeform",
                risk_level="soft_read",
                grounding="ungrounded",
                reason="Protective pressure is high enough to prefer a guarded boundary.",
                evidence=(f"protectiveness={protectiveness:.2f}; threat={threat:.2f}",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=protective_score < 0.64 or bool(concrete_signals),
            )
        )

        tender_score = max(tenderness, intimacy * 0.90, self._pressure(state, "tender_pressure"))
        if emotional_signal:
            tender_score = max(tender_score, 0.96)
        candidates.append(
            MotivationalUrge(
                label="guarded_reply",
                score=tender_score,
                utterance_type="guarded_reply",
                speech_source="freeform",
                risk_level="soft_read",
                grounding="ungrounded",
                reason="Explicit emotional signal asks for a guarded reply, not automatic reassurance.",
                evidence=(self._inner_anchor(inner_thought) or "emotional_signal",),
                safety_flags=("no_screen_claim", "anti_mindreading", "explicit_emotional_signal") if emotional_signal else ("no_screen_claim", "anti_mindreading", "relational_checkin_blocked"),
                blocked=not emotional_signal,
            )
        )

        thought_surface_score = max(
            surface_pressure,
            surface_momentum,
            0.68 if inner_surface and surface_mode else 0.0,
        )
        if surface_novelty < 0.20:
            thought_surface_score *= 0.88
        candidates.append(
            MotivationalUrge(
                label="thought_stream_surface",
                score=min(1.0, thought_surface_score),
                utterance_type=self._inner_utterance(inner_intent, fallback="inner_whim"),
                speech_source="freeform",
                risk_level="texture",
                grounding="ungrounded",
                reason="A thought stream surface has enough cognitive tension to become freeform speech.",
                evidence=(inner_seed or self._inner_anchor(inner_thought) or surface_mode,),
                safety_flags=tuple(
                    flag
                    for flag in (
                        "no_screen_claim",
                        "anti_mindreading",
                        "thought_stream_surface",
                        "subconscious_seed",
                        "momentum_affordance" if surface_affordance else "",
                    )
                    if flag
                ),
                blocked=bool(concrete_signals)
                or not (inner_surface and surface_mode)
                or (surface_affordance not in {"", "speech"})
                or thought_surface_score < 0.52,
            )
        )

        social_score = max(
            self._pressure(state, "social_pressure"),
            self._float(getattr(state, "silence_pressure", 0.0)),
            self._float(getattr(state, "boredom", 0.0)) * 0.90,
            desire_cling * 0.88,
            desire_residue * 0.62,
            0.62 if inner_surface else 0.0,
        )
        if not inner_surface and idle_seconds >= 20:
            social_score += 0.10
        if not inner_surface and idle_seconds >= 40:
            social_score += 0.08
        if not inner_surface and idle_seconds >= 90:
            social_score += 0.12
        candidates.append(
            MotivationalUrge(
                label="social_presence",
                score=min(1.0, social_score),
                utterance_type=self._inner_utterance(inner_intent, fallback="inner_whim"),
                speech_source="freeform",
                risk_level="micro_presence" if inner_intent == "micro_presence" else "texture",
                grounding="ungrounded",
                reason="Social presence pressure wants a small ungrounded line.",
                evidence=(self._inner_anchor(inner_thought) or f"idle={int(idle_seconds)}s",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or (not inner_surface and social_score < 0.38),
            )
        )

        curiosity_score = max(
            self._pressure(state, "curiosity_pressure"),
            self._float(getattr(state, "curiosity", 0.0)) * 0.72,
            desire_want * 0.64,
            desire_anticipation * 0.52,
            0.64 if inner_intent == "curious_question" else 0.0,
        )
        candidates.append(
            MotivationalUrge(
                label="curiosity",
                score=curiosity_score,
                utterance_type="curious_question",
                speech_source="freeform",
                risk_level="texture",
                grounding="ungrounded",
                reason="Curiosity pressure wants a small question.",
                evidence=(inner_seed or self._inner_anchor(inner_thought) or "curiosity_pressure",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or curiosity_score < 0.44,
            )
        )

        playful_score = max(self._pressure(state, "playful_pressure"), amusement, desire_want * 0.36 - desire_avoid * 0.10)
        candidates.append(
            MotivationalUrge(
                label="playful_aside",
                score=playful_score,
                utterance_type="light_muse",
                speech_source="freeform",
                risk_level="texture",
                grounding="ungrounded",
                reason="Playful pressure is present but stays low priority.",
                evidence=(f"amusement={amusement:.2f}",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or playful_score < 0.50,
            )
        )

        watchful_score = max(self._pressure(state, "watchful_pressure"), jealousy_lite, threat * 0.72)
        candidates.append(
            MotivationalUrge(
                label="watchful_boundary",
                score=watchful_score,
                utterance_type="soft_boundary",
                speech_source="freeform",
                risk_level="soft_read",
                grounding="ungrounded",
                reason="Watchful pressure wants restraint with a boundary.",
                evidence=(f"watchful={watchful_score:.2f}",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or watchful_score < 0.58,
            )
        )

        current_window = str(
            getattr(snapshot, "active_window", "")
            or getattr(snapshot, "active_app", "")
            or getattr(snapshot, "focus_summary", "")
            or ""
        ).strip()
        small_talk_anchor = current_window[:80] if current_window else f"idle={int(idle_seconds)}s"
        candidates.append(
            MotivationalUrge(
                label="safe_small_talk_budget",
                score=0.62 if safe_small_talk_allowed else 0.0,
                utterance_type="micro_presence",
                speech_source="freeform",
                risk_level="micro_presence",
                grounding="small_talk_budget",
                reason="Safe small-talk budget permits one tiny low-claim line.",
                evidence=(small_talk_anchor,),
                safety_flags=(
                    "safe_small_talk_budget",
                    "no_screen_claim",
                    "anti_mindreading",
                    "no_hard_fact_claim",
                    "under_12_words",
                ),
                blocked=channel != "autonomous" or not safe_small_talk_allowed or bool(concrete_signals),
            )
        )

        spontaneous = spontaneous_impulse or SpeechImpulse()
        spontaneous_pressure = self._clamp01(getattr(spontaneous, "surface_pressure", 0.0))
        spontaneous_act = str(getattr(spontaneous, "suggested_speech_act", "") or "").strip() or "inner_whim"
        if spontaneous_act == "companionship_ping":
            spontaneous_act = "micro_presence"
        spontaneous_family = str(getattr(spontaneous, "family", "") or getattr(spontaneous, "semantic_family", "") or "spontaneous_life")
        spontaneous_blocked = (
            channel not in {"autonomous", "force_speak"}
            or bool(concrete_signals)
            or bool(getattr(spontaneous, "needs_external_evidence", False))
            or spontaneous_act == "no_speech"
            or spontaneous_pressure <= 0.0
            or (channel == "force_speak" and not spontaneous_explicit)
        )
        spontaneous_evidence = tuple(str(item) for item in (getattr(spontaneous, "evidence", ()) or ()))[:8]
        spontaneous_source_fact = str(getattr(spontaneous, "source_fact", "") or "")
        spontaneous_has_scene_grounding = (
            "scene_evidence" in spontaneous_source_fact
            or any("ev.active_window" in item or "ev.active_app" in item or "ev.ocr" in item for item in spontaneous_evidence)
        )
        spontaneous_flags = [
            "spontaneous_life",
            "endogenous_anchor",
            "anti_mindreading",
            f"family={spontaneous_family}",
        ]
        if spontaneous_has_scene_grounding:
            spontaneous_flags.append("grounded_scene_impulse")
        else:
            spontaneous_flags.append("no_screen_claim")
        spontaneous_score = spontaneous_pressure
        if channel == "autonomous":
            # SpontaneousLife is a pressure source, not a monarchy.  It should not
            # drown out MeaningLayer or explicit thought-stream surfaces every time
            # silence/boredom rises. Keep it speakable, but let ranked semantic
            # candidates win when they explain the frame better.
            spontaneous_score = min(spontaneous_pressure * 0.55, 0.60)
        candidates.append(
            MotivationalUrge(
                label="spontaneous_life",
                score=spontaneous_score,
                utterance_type=spontaneous_act,
                speech_source="freeform",
                risk_level=str(getattr(spontaneous, "risk", "texture") or "texture"),
                grounding="scene_evidence" if spontaneous_has_scene_grounding else "endogenous_anchor",
                reason=str(getattr(spontaneous, "reason", "") or "Internal life produced a low-claim speech impulse."),
                evidence=spontaneous_evidence[:6],
                safety_flags=tuple(dict.fromkeys(spontaneous_flags)),
                blocked=spontaneous_blocked,
            )
        )

        restraint_score = self._score_restraint(internal_state=state, ti_report=ti_report, self_state=self_state)
        if channel == "force_speak":
            restraint_score = min(restraint_score, 0.22)
        candidates.append(
            self._silence_urge(
                score=restraint_score,
                reason="Silence/restraint pressure is competing against speech.",
                blocked=channel == "force_speak",
            )
        )
        return tuple(candidates)

    def _apply_self_state_to_candidates(
        self,
        candidates: tuple[MotivationalUrge, ...],
        *,
        channel: str,
        self_state: SelfState | None,
    ) -> tuple[MotivationalUrge, ...]:
        if self_state is None:
            return candidates
        overload = self._clamp01(getattr(self_state, "overload", 0.0))
        engagement = self._clamp01(getattr(self_state, "engagement", 0.0))
        label = str(getattr(self_state, "state_label", "") or "")
        adjusted: list[MotivationalUrge] = []
        for candidate in candidates:
            score = candidate.score
            evidence = tuple(candidate.evidence or ())
            if channel == "autonomous":
                if label == "overloaded" and candidate.label != "silence_restraint": 
                    if candidate.speech_source in {"freeform", "meaning", "none"}:
                        score *= max(0.58, 1.0 - overload * 0.34)
                    elif candidate.speech_source in {"vision", "telemetry"}:
                        score *= max(0.82, 1.0 - overload * 0.12)
                if label == "engaged" and candidate.label in {"social_presence", "curiosity", "thought_stream_surface", "subconscious_seed"}:
                    score += engagement * 0.12
            elif channel == "force_speak" and label == "overloaded" and candidate.speech_source in {"freeform", "meaning", "random"}:
                score *= max(0.82, 1.0 - overload * 0.12)

            if candidate.label == "silence_restraint" and label == "overloaded":
                score += overload * (0.22 if channel == "autonomous" else 0.08)
            if label in {"overloaded", "engaged"}:
                evidence = (*evidence, f"self_state={label}")

            adjusted.append(
                MotivationalUrge(
                    label=candidate.label,
                    score=self._clamp01(score),
                    utterance_type=candidate.utterance_type,
                    speech_source=candidate.speech_source,
                    risk_level=candidate.risk_level,
                    grounding=candidate.grounding,
                    reason=candidate.reason,
                    evidence=evidence,
                    safety_flags=candidate.safety_flags,
                    blocked=candidate.blocked,
                )
            )
        return tuple(adjusted)

    def _apply_personality_restraint_to_candidates(
        self,
        candidates: tuple[MotivationalUrge, ...],
        *,
        channel: str,
        personality_lens,
    ) -> tuple[MotivationalUrge, ...]:
        if personality_lens is None or channel != "autonomous":
            return candidates

        suppression = self._clamp01(getattr(personality_lens, "suppression_pressure", 0.0))
        allowed = self._clamp01(getattr(personality_lens, "allowed_expression", 1.0))
        want = self._clamp01(getattr(personality_lens, "want_to_say", 0.0))
        mode = str(getattr(personality_lens, "restraint_mode", "") or "")
        if suppression <= 0.0 and not mode:
            return candidates

        expression_factor = max(0.44, min(1.08, 0.66 + allowed * 0.92 - suppression * 0.22))
        adjusted: list[MotivationalUrge] = []
        for candidate in candidates:
            score = candidate.score
            evidence = tuple(candidate.evidence or ())
            flags = tuple(candidate.safety_flags or ())
            if candidate.label == "silence_restraint":
                score += suppression * 0.12
                if mode:
                    evidence = (*evidence, f"restraint_mode={mode}")
            elif candidate.label == "meaning_reaction":
                score += allowed * 0.14
                evidence = (*evidence, f"expression_gate={want:.2f}->{allowed:.2f}")
                flags = (*flags, "personality_restraint")
            elif candidate.label == "residual_continuity_pull":
                score += allowed * 0.18 + want * 0.06
                evidence = (*evidence, f"expression_gate={want:.2f}->{allowed:.2f}")
                flags = (*flags, "personality_restraint")
            elif candidate.speech_source == "freeform":
                score *= expression_factor
                evidence = (*evidence, f"expression_gate={want:.2f}->{allowed:.2f}")
                flags = (*flags, "personality_restraint")
            adjusted.append(
                MotivationalUrge(
                    label=candidate.label,
                    score=self._clamp01(score),
                    utterance_type=candidate.utterance_type,
                    speech_source=candidate.speech_source,
                    risk_level=candidate.risk_level,
                    grounding=candidate.grounding,
                    reason=candidate.reason,
                    evidence=evidence,
                    safety_flags=tuple(dict.fromkeys(flags)),
                    blocked=candidate.blocked,
                )
            )
        return tuple(adjusted)

    def _build_suppressed_pressure_report(
        self,
        *,
        reason: str,
        threshold: float,
        concrete_signals: tuple[str, ...],
    ) -> MotivationalPressureReport:
        winner = self._silence_urge(
            score=1.0,
            reason="MotivationalPressure was suppressed before competition by a hard quiet guard.",
            evidence=tuple(concrete_signals[:2]),
        )
        return MotivationalPressureReport(
            winner=winner,
            threshold=threshold,
            candidates=(winner,),
            suppressed_by=reason,
        )

    def _silence_urge(
        self,
        *,
        score: float,
        reason: str,
        evidence: tuple[str, ...] = (),
        blocked: bool = False,
    ) -> MotivationalUrge:
        return MotivationalUrge(
            label="silence_restraint",
            score=self._clamp01(score),
            utterance_type="no_speech",
            speech_source="none",
            risk_level="texture",
            grounding="none",
            reason=reason,
            evidence=evidence,
            safety_flags=("quiet_guard",) if not blocked else (),
            blocked=blocked,
        )

    def _silence_body_bias_hint(
        self,
        *,
        reason: str,
        inner_thought,
        pressure_report: MotivationalPressureReport,
        speech_impulse: SpeechImpulse,
    ) -> dict[str, object]:
        """Project suppressed speech into body-only bias.

        Silence should still leave a body affordance for Godot: observe, idle
        shift, or stillness.  No text is generated here.
        """
        hint: dict[str, object] = {}
        raw_hint = getattr(speech_impulse, "body_bias_hint", {}) or {}
        if isinstance(raw_hint, dict):
            hint.update(raw_hint)
        candidates = tuple(getattr(pressure_report, "candidates", ()) or ())
        best = next((item for item in candidates if not getattr(item, "blocked", False)), None)
        label = str(getattr(best, "label", "") or getattr(getattr(pressure_report, "winner", None), "label", "") or "")
        score = self._clamp01(getattr(best, "score", 0.0) if best is not None else 0.0)
        inner_intent = str(getattr(inner_thought, "intent", "") or "")
        reason_name = str(reason or "")
        if label in {"curiosity", "spontaneous_life", "thought_stream_surface", "soft_meaning_presence"} or inner_intent == "curious_question":
            hint.setdefault("body_action_bias", "ObserveCode")
            hint.setdefault("curiosity_delta", round(max(0.08, min(0.24, score * 0.22)), 3))
        elif "quiet_guard" in reason_name or "meaning_shift_gate" in reason_name:
            hint.setdefault("body_action_bias", "idle_shift")
            hint.setdefault("solitude_delta", 0.06)
        if reason_name:
            hint.setdefault("silence_reason", reason_name)
        if label:
            hint.setdefault("suppressed_impulse", label)
        return hint

    def _build_silence_state(
        self,
        *,
        reason: str,
        inner_thought,
        pressure_report: MotivationalPressureReport,
        speech_impulse: SpeechImpulse,
        personality_lens,
        safety_flags: tuple[str, ...] = (),
    ) -> SilenceState: #Im lặng cũng là hành vi
        candidates = tuple(getattr(pressure_report, "candidates", ()) or ())
        spoken_candidate = next(
            (
                item
                for item in candidates
                if not getattr(item, "blocked", False)
                and getattr(item, "speech_source", "") != "none"
                and getattr(item, "utterance_type", "") != "no_speech"
            ),
            None,
        )
        suppressed_thought = (
            str(getattr(speech_impulse, "surface_intent", "") or "")
            or str(getattr(inner_thought, "topic_seed", "") or "")
            or str(getattr(inner_thought, "motive", "") or "")
        )
        almost_spoke = ""
        if spoken_candidate is not None:
            almost_spoke = str(getattr(spoken_candidate, "utterance_type", "") or getattr(spoken_candidate, "label", "") or "")
        elif bool(getattr(inner_thought, "should_surface", False)):
            almost_spoke = str(getattr(inner_thought, "intent", "") or "inner_thought")

        unfinished_impulse = (
            str(getattr(speech_impulse, "reaction_impulse", "") or "")
            or str(getattr(speech_impulse, "surface_intent", "") or "")
            or str(getattr(inner_thought, "intent", "") or "")
        )
        biases = tuple(str(item) for item in (getattr(speech_impulse, "attention_bias", ()) or ()))
        lens_biases = tuple(str(item) for item in (getattr(personality_lens, "attention_bias", ()) or ())) if personality_lens is not None else ()
        hesitation_terms = {"hesitation", "unfinished_intention", "cognitive_stall"}
        internal_hesitation = next((item for item in (*biases, *lens_biases) if item in hesitation_terms), "")
        if not internal_hesitation and (
            "hesitat" in str(getattr(pressure_report, "suppressed_by", "") or "")
            or "repeat_guard" in set(str(item) for item in safety_flags)
        ):
            internal_hesitation = "internal_hesitation"

        evidence = tuple(
            dict.fromkeys(
                item
                for item in (
                    reason,
                    str(getattr(pressure_report, "suppressed_by", "") or ""),
                    str(getattr(inner_thought, "evidence_anchor", "") or ""),
                    *(str(item) for item in (getattr(getattr(pressure_report, "winner", None), "evidence", ()) or ())),
                    *safety_flags,
                )
                if str(item or "").strip()
            )
        )
        body_bias_hint = self._silence_body_bias_hint(
            reason=reason,
            inner_thought=inner_thought,
            pressure_report=pressure_report,
            speech_impulse=speech_impulse,
        )
        return SilenceState(
            mode="intentional_withholding",
            intentional_withholding=True,
            suppressed_thought=suppressed_thought,
            almost_spoke=almost_spoke,
            unfinished_impulse=unfinished_impulse,
            internal_hesitation=internal_hesitation,
            reason=reason or "speech_withheld",
            evidence=evidence,
            generation_failure=False,
            body_bias_hint=body_bias_hint,
        )

    def _meaning_reaction_score(
        self,
        *,
        channel: str,
        meaning_layer,
        concrete_signals: tuple[str, ...],
    ) -> float:
        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        if not meaning:
            return 0.0
        confidence = self._clamp01(getattr(meaning_layer, "confidence", 0.0))
        if channel != "autonomous":
            return 0.0
        meaning_shift = bool(getattr(meaning_layer, "meaning_shift", False))
        signal = str(getattr(meaning_layer, "meaning_signal", "") or "")
        score = max(0.46, confidence * 0.68)
        if meaning_shift:
            score += 0.12
        elif signal in {"weak_meaning", "ambient_meaning", "vibe_signal"}:
            score += 0.08
        if concrete_signals:
            score += 0.12
        if meaning in {"cognitive_stall", "escape_from_friction", "scattered_attention", "friction_point"}:
            score += 0.05
        return self._clamp01(score)

    # cho phép nói những tín hiệu mềm như weak_meaning, ambient_meaning, vibe_signal mà không cần meaning_shift nếu đã im lặng đủ lâu hoặc có đủ áp lực im lặng hoặc chán nản, để tránh việc giữ im lặng quá mức khi không có tín hiệu mạnh nào có thể kích hoạt speech
    def _allows_soft_non_shift_speech(self, *, meaning_layer, snapshot, internal_state: PersistentInternalState | None) -> bool:
        signal = str(getattr(meaning_layer, "meaning_signal", "") or "")
        if signal in {"weak_meaning", "ambient_meaning", "vibe_signal"}:
            return True
        idle_seconds = max(0.0, self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0))
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        boredom = self._float(getattr(internal_state, "boredom", 0.0) if internal_state is not None else 0.0)
        attachment = self._float(getattr(internal_state, "attachment", 0.0) if internal_state is not None else 0.0)
        tenderness = self._float(getattr(internal_state, "tenderness", 0.0) if internal_state is not None else 0.0)
        attention_bias = set(str(item) for item in (getattr(meaning_layer, "attention_bias", ()) or ()))
        continuity_pull = bool(attention_bias & {"continuity", "friction_residue", "unfinished_intention", "indirect_presence"})
        return (
            idle_seconds >= 20
            or silence_pressure >= 0.35
            or boredom >= 0.32
            or (continuity_pull and (attachment >= 0.42 or tenderness >= 0.28 or idle_seconds >= 20))
        )

    def _meaning_shift_required_for_layer(self, meaning_layer) -> bool:
        signal = str(getattr(meaning_layer, "meaning_signal", "") or "")
        if signal in {"", "none", "weak_meaning", "ambient_meaning", "vibe_signal"}:
            return False
        reaction = str(getattr(meaning_layer, "reaction", "") or "")
        intent = str(getattr(meaning_layer, "surface_intent", "") or "").lower()
        hard_shapes = (
            "observation",
            "advice",
            "advise",
            "goal",
            "interpret",
            "realign",
            "recommend",
        )
        soft_reactions = {"quiet_tease", "soft_tease", "dry_marker", "relationship_ack"}
        if reaction in soft_reactions:
            return False
        return any(shape in intent for shape in hard_shapes)

    def _risk_level_for_winner(self, *, winner: MotivationalUrge, speech_source: str, utterance_type: str) -> str:
        risk = str(getattr(winner, "risk_level", "") or "").strip()
        if risk in {"hard_claim", "soft_read", "micro_presence", "texture"}:
            return risk
        if speech_source in {"vision", "telemetry"}:
            return "hard_claim"
        if speech_source == "meaning":
            return "soft_read"
        if utterance_type == "micro_presence":
            return "micro_presence"
        if utterance_type in {"relational_checkin", "guarded_reply", "soft_boundary"}:
            return "soft_read"
        return "texture"

    # đánh giá điểm số cho việc nói những tín hiệu mềm từ meaning_layer dựa trên confidence, thời gian im lặng, áp lực im lặng và mức độ chán nản, để quyết định xem có nên phản ứng với những tín hiệu này hay không
    def _soft_meaning_presence_score(
        self,
        *,
        channel: str,
        meaning_layer,
        snapshot,
        internal_state: PersistentInternalState | None,
    ) -> float:
        if channel != "autonomous" or meaning_layer is None:
            return 0.0
        if bool(getattr(meaning_layer, "meaning_shift", False)):
            return 0.0
        signal = str(getattr(meaning_layer, "meaning_signal", "") or "")
        if signal not in {"weak_meaning", "ambient_meaning", "vibe_signal"}:
            return 0.0
        idle_seconds = max(0.0, self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0))
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        boredom = self._float(getattr(internal_state, "boredom", 0.0) if internal_state is not None else 0.0)
        confidence = self._clamp01(getattr(meaning_layer, "confidence", 0.0))
        score = max(0.50, confidence * 0.64)
        if idle_seconds >= 20:
            score += 0.10
        if idle_seconds >= 40:
            score += 0.10
        if idle_seconds >= 60:
            score += 0.08
        if silence_pressure >= 0.35 or boredom >= 0.32:
            score += 0.18
        return self._clamp01(score)

    def _residual_continuity_score(
        self,
        *,
        channel: str,
        meaning_layer,
        snapshot,
        internal_state: PersistentInternalState | None,
        thought_surface,
    ) -> float:
        if channel != "autonomous" or meaning_layer is None:
            return 0.0
        if bool(getattr(meaning_layer, "meaning_shift", False)):
            return 0.0
        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        if not meaning:
            return 0.0

        idle_seconds = max(0.0, self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0))
        state = internal_state or PersistentInternalState()
        attention_bias = set(str(item) for item in (getattr(meaning_layer, "attention_bias", ()) or ()))
        signal = str(getattr(meaning_layer, "meaning_signal", "") or "")
        surface_pressure = self._float(getattr(thought_surface, "pressure", 0.0) if thought_surface is not None else 0.0)
        surface_momentum = self._float(getattr(thought_surface, "momentum_score", 0.0) if thought_surface is not None else 0.0)

        score = 0.22
        if signal in {"weak_meaning", "ambient_meaning", "vibe_signal"}:
            score += 0.16
        if attention_bias & {"continuity", "friction_residue", "unfinished_intention", "indirect_presence"}:
            score += 0.14
        if idle_seconds >= 18:
            score += 0.08
        if idle_seconds >= 45:
            score += 0.08
        score += self._float(getattr(state, "silence_pressure", 0.0)) * 0.20
        score += self._float(getattr(state, "boredom", 0.0)) * 0.10
        score += self._float(getattr(state, "attachment", 0.0)) * 0.10
        score += self._float(getattr(state, "tenderness", 0.0)) * 0.08
        score += max(surface_pressure, surface_momentum) * 0.12
        return self._clamp01(score)

    def _utterance_for_reaction(self, reaction: str, *, channel: str, meaning: str) -> str:
        if channel == "force_speak" or meaning == "requested_presence":
            return "micro_presence"
        if reaction in {"quiet_tease", "soft_tease", "dry_marker"}:
            return "inner_whim"
        if reaction == "focused_concern":
            return "soft_boundary"
        if reaction == "relationship_ack":
            return "indirect_presence"
        return "inner_whim"

    def _build_speech_impulse(
        self,
        *,
        channel: str,
        meaning_layer,
        winner: MotivationalUrge,
        should_speak: bool,
        spontaneous_impulse: SpeechImpulse | None = None,
    ) -> SpeechImpulse:
        spontaneous = spontaneous_impulse or SpeechImpulse()
        if str(getattr(winner, "label", "") or "") in {"spontaneous_life", "force_speak_endogenous_fallback"} and getattr(spontaneous, "active", False):
            return spontaneous

        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        if meaning:
            reaction = str(getattr(meaning_layer, "reaction", "") or "")
            return SpeechImpulse(
                meaning=meaning,
                reaction=reaction or ("relationship_ack" if channel == "force_speak" else "quiet_reaction"),
                attitude=str(getattr(meaning_layer, "attitude", "") or ""),
                surface_intent=str(getattr(meaning_layer, "surface_intent", "") or ""),
                mood_residue=str(getattr(meaning_layer, "mood_residue", "") or ""),
                emotional_pressure=self._clamp01(getattr(meaning_layer, "emotional_pressure", 0.0)),
                attention_bias=tuple(str(item) for item in (getattr(meaning_layer, "attention_bias", ()) or ()))[:4],
                reaction_impulse=str(getattr(meaning_layer, "reaction_impulse", "") or ""),
                semantic_family=str(getattr(meaning_layer, "semantic_family", "") or meaning),
                source_fact=str(getattr(meaning_layer, "source_fact", "") or ""),
                evidence=tuple(str(item) for item in (getattr(meaning_layer, "evidence", ()) or ()))[:4],
            )
        if not should_speak:
            return SpeechImpulse(reaction="no_reaction", surface_intent="stay silent")
        return SpeechImpulse(
            meaning=str(getattr(winner, "label", "") or ""),
            reaction=str(getattr(winner, "utterance_type", "") or "brief_reaction"),
            attitude="light",
            surface_intent=str(getattr(winner, "reason", "") or "speak briefly"),
            evidence=tuple(str(item) for item in (getattr(winner, "evidence", ()) or ()))[:4],
        )
    def _extreme_internal_speech_pressure(
        self,
        *,
        spontaneous_impulse: SpeechImpulse | None,
        internal_state: PersistentInternalState | None,
        thought_surface=None,
    ) -> bool:
        """Allow bounded endogenous leakage to bypass meaning_shift_gate.

        This is not permission to make screen claims. It only lets a low-claim,
        internally anchored utterance compete in motivation arbitration when the
        system has been silent too long or an endogenous impulse is very strong.
        """
        state = internal_state or PersistentInternalState()
        spontaneous_pressure = self._clamp01(getattr(spontaneous_impulse, "surface_pressure", 0.0))
        vital_pressure = self._clamp01(getattr(spontaneous_impulse, "vital_pressure", 0.0))
        spontaneous_act = str(getattr(spontaneous_impulse, "suggested_speech_act", "") or "")
        if (
            (spontaneous_pressure >= 0.78 or vital_pressure >= 0.60)
            and spontaneous_act
            and spontaneous_act != "no_speech"
            and not bool(getattr(spontaneous_impulse, "needs_external_evidence", False))
        ):
            return True
        silence_pressure = self._float(getattr(state, "silence_pressure", 0.0))
        boredom = self._float(getattr(state, "boredom", 0.0))
        curiosity_pressure = max(
            self._pressure(state, "curiosity_pressure"),
            self._float(getattr(state, "curiosity", 0.0)),
        )
        surface_pressure = self._float(getattr(thought_surface, "pressure", 0.0) if thought_surface is not None else 0.0)
        surface_momentum = self._float(getattr(thought_surface, "momentum_score", 0.0) if thought_surface is not None else 0.0)
        return bool(
            vital_pressure >= 0.60
            or silence_pressure >= 0.70
            or (silence_pressure >= 0.58 and max(boredom, curiosity_pressure, surface_pressure, surface_momentum) >= 0.52)
        )

    def _spontaneous_ready(self, impulse: SpeechImpulse | None, *, channel: str) -> bool:
        if impulse is None:
            return False
        if channel not in {"autonomous", "force_speak"}:
            return False
        if bool(getattr(impulse, "needs_external_evidence", False)):
            return False
        act = str(getattr(impulse, "suggested_speech_act", "") or "")
        if not act or act == "no_speech":
            return False
        vital = self._clamp01(getattr(impulse, "vital_pressure", 0.0))
        threshold = 0.30 if channel == "force_speak" else 0.50
        threshold = max(0.22 if channel == "force_speak" else 0.36, threshold - vital * 0.16)
        act = str(getattr(impulse, "suggested_speech_act", "") or "")
        if channel == "autonomous" and act in {"inner_whim", "random_chatter", "curious_question", "thought_stream_surface"}:
            # Nội sinh không cần màn hình làm neo. Nó chỉ cần đủ áp lực và cam kết không claim screen.
            # Đây là cửa chống starvation, không phải hũ câu mẫu thứ hai.
            threshold = max(0.30, threshold - max(vital * 0.18, 0.08))
        return max(self._clamp01(getattr(impulse, "surface_pressure", 0.0)), vital * 0.82) >= threshold

    #Autonomous cần vượt threshold mới được nói. ERIS overloaded sẽ tự ít nói hơn. 
    def _threshold_for_channel(self, channel: str, *, self_state: SelfState | None = None) -> float:
        if channel == "autonomous":
            overload = self._clamp01(getattr(self_state, "overload", 0.0) if self_state is not None else 0.0)
            engagement = self._clamp01(getattr(self_state, "engagement", 0.0) if self_state is not None else 0.0)
            return self._clamp01(0.40 + overload * 0.12 - engagement * 0.12)
        if channel == "force_speak":
            return 0.0
        return 0.45

    def _score_restraint(self, *, internal_state: PersistentInternalState | None, ti_report, self_state: SelfState | None = None) -> float:
        state = internal_state or PersistentInternalState()
        mode = str(getattr(ti_report, "mode", "") or "")
        score = (
            0.20
            + self._pressure(state, "restraint_pressure") * 0.44
            + self._float(getattr(state, "fatigue", 0.0)) * 0.16
            - self._float(getattr(state, "silence_pressure", 0.0)) * 0.30
            - self._float(getattr(state, "vital_pressure", 0.0)) * 0.18
        )
        if mode in self.QUIET_MODES or mode == "social_watch":
            score += 0.12
        if mode == "focus_guard":
            score += 0.12
        if self_state is not None:
            score += self._clamp01(getattr(self_state, "overload", 0.0)) * 0.18
            score -= self._clamp01(getattr(self_state, "engagement", 0.0)) * 0.06
        return self._clamp01(score)

    def _pressure(self, state: PersistentInternalState, name: str) -> float:
        return self._float(getattr(state, name, 0.0))

    def _inner_utterance(self, inner_intent: str, *, fallback: str) -> str:
        if inner_intent in {"random_chatter", "inner_whim", "curious_question", "micro_presence"}:
            return inner_intent
        return fallback

    def _inner_anchor(self, inner_thought) -> str:
        return str(getattr(inner_thought, "evidence_anchor", "") or "")

    def _should_stay_silent(
        self,
        *,
        ti_mode: str,
        repeat_count: int,
        repeated_topic_tag: str,
        repeated_topic_streak: int,
        ni_state_label: str,
        ni_report,
        internal_state: PersistentInternalState | None,
        self_state: SelfState | None = None,
    ) -> bool:
        drift_score = self._float(getattr(ni_report, "drift_score", 1.0) if ni_report is not None else 1.0)
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        if ti_mode == "focus_guard" and ni_state_label == "ON_GOAL" and drift_score <= 0.35:
            return True
        if str(getattr(self_state, "state_label", "") or "") == "overloaded" and ti_mode in self.QUIET_MODES:
            if self._float(getattr(self_state, "overload", 0.0)) >= 0.72:
                return True
        if silence_pressure >= 0.58 and repeat_count <= 1:
            return False
        if repeat_count >= 3 and ti_mode in self.QUIET_MODES:
            return True
        if repeat_count >= 4:
            return True
        if repeated_topic_tag and repeated_topic_streak >= 3 and ti_mode in self.QUIET_MODES:
            return True
        return False

    def _choose_speech_source(
        self,
        *,
        channel: str,
        vision_signals: tuple[str, ...],
        telemetry_signals: tuple[str, ...],
        screen_comment_allowed: bool,
        inner_thought,
        internal_state: PersistentInternalState | None,
    ) -> str:
        if screen_comment_allowed and vision_signals:
            return "vision"
        if screen_comment_allowed and telemetry_signals:
            return "telemetry"
        if inner_thought.should_surface:
            return "freeform"
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        attachment = self._float(getattr(internal_state, "attachment", 0.0) if internal_state is not None else 0.0)
        social_energy = self._float(getattr(internal_state, "social_energy", 0.0) if internal_state is not None else 0.0)
        boredom = self._float(getattr(internal_state, "boredom", 0.0) if internal_state is not None else 0.0)
        if channel == "autonomous" and (silence_pressure >= 0.54 or boredom >= 0.46):
            return "freeform"
        if channel == "force_speak" and (attachment >= 0.36 or social_energy >= 0.34):
            return "freeform"
        if channel == "force_speak":
            return "random"
        return "none"

    def _choose_utterance_type(
        self,
        *,
        channel: str,
        speech_source: str,
        inner_thought,
        emotional_signal: bool,
    ) -> str:
        if speech_source == "vision":
            return "vision_comment"
        if speech_source == "telemetry":
            return "telemetry_comment"
        if emotional_signal and speech_source in {"freeform", "random"}:
            return "guarded_reply"

        inner_intent = str(getattr(inner_thought, "intent", "") or "")
        if inner_intent in {"random_chatter", "inner_whim", "curious_question"}:
            return inner_intent
        if speech_source == "random" and channel == "force_speak":
            return "random_chatter"
        if speech_source == "freeform":
            return "inner_whim"
        return "no_speech"

    def _resolve_perception(
        self,
        *,
        speech_source: str,
        vision_signals: tuple[str, ...],
        telemetry_signals: tuple[str, ...],
        concrete_signals: tuple[str, ...],
        inner_thought,
    ) -> tuple[str, ...]:
        if speech_source == "vision":
            return tuple(vision_signals[:2])
        if speech_source == "telemetry":
            return tuple(telemetry_signals[:2])
        if speech_source == "meaning":
            if concrete_signals:
                return tuple(concrete_signals[:2])
            if getattr(inner_thought, "evidence_anchor", ""):
                return (str(inner_thought.evidence_anchor),)
        if speech_source in {"freeform", "random"} and getattr(inner_thought, "evidence_anchor", ""):
            return (str(inner_thought.evidence_anchor),)
        return tuple(concrete_signals[:2])

    def _build_safety_flags(
        self,
        *,
        channel: str,
        speech_source: str,
        utterance_type: str,
        emotional_signal: bool,
        inner_thought,
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if channel == "force_speak":
            flags.append("force_speak_required")
        if speech_source in {"freeform", "random"}:
            flags.append("no_screen_claim")
            flags.append("anti_mindreading")
            if utterance_type == "micro_presence":
                flags.append("situated_residue")
                flags.append("anti_presence_declaration")
        if speech_source in {"vision", "telemetry"}:
            flags.append("grounded_screen_comment")
        if speech_source == "meaning":
            flags.append("meaning_layer_reaction")
            flags.append("meaning_not_speech")
            flags.append("react_to_residue_not_label")
        if emotional_signal:
            flags.append("explicit_emotional_signal")
        if utterance_type in {"relational_checkin", "guarded_reply"} and not emotional_signal:
            flags.append("relational_checkin_blocked")
        if getattr(inner_thought, "risk_flags", ()):
            flags.extend(str(item) for item in inner_thought.risk_flags)
        return tuple(dict.fromkeys(flag for flag in flags if flag))

    def _build_reason(
        self,
        *,
        channel: str,
        speech_source: str,
        utterance_type: str,
        inner_thought,
        emotional_signal: bool,
    ) -> str:
        if speech_source == "vision":
            return "SpeechCore chose a screen-grounded line from visual evidence."
        if speech_source == "telemetry":
            return "SpeechCore chose a screen-grounded line from runtime telemetry."
        if speech_source == "meaning":
            return "SpeechCore chose a wording impulse from MeaningLayer residue, not the internal meaning label."
        if speech_source == "freeform":
            if utterance_type == "micro_presence":
                return "SpeechCore chose micro-presence as situated cognition residue."
            return (
                "SpeechCore chose a freeform line from inner initiative: "
                f"{utterance_type or getattr(inner_thought, 'intent', '')}."
            )
        if speech_source == "random":
            return (
                "SpeechCore kept presence without screen grounding because force_speak still needs a line."
                if channel == "force_speak"
                else "SpeechCore chose a light ungrounded line."
            )
        if emotional_signal:
            return "SpeechCore found an explicit emotional cue worth checking in on."
        return "SpeechCore kept silence."

    def _grounding_for_source(self, speech_source: str) -> str:
        if speech_source == "vision":
            return "screen_vision"
        if speech_source == "telemetry":
            return "screen_telemetry"
        if speech_source == "meaning":
            return "meaning_layer"
        if speech_source in {"freeform", "random"}:
            return "ungrounded"
        return "none"

    def _has_emotional_signal(self, *, concrete_signals: tuple[str, ...], broadcast) -> bool:
        text_parts = list(concrete_signals or ())
        if broadcast is not None:
            label = str(getattr(broadcast, "label", "") or "")
            content = str(getattr(broadcast, "content", "") or "")
            if label:
                text_parts.append(label)
            if content:
                text_parts.append(content)
        lowered = " ".join(part.lower() for part in text_parts if str(part).strip())
        return any(term in lowered for term in self.EMOTIONAL_TERMS)

    def _resolve_mood(self, *, snapshot, appraisal, fe_plan) -> str:
        tone = str(getattr(fe_plan, "tone_label", "") or "")
        stance = str(getattr(appraisal, "stance", "") or "")
        ambient_tone = str(getattr(snapshot, "ambient_tone", "") or "")
        tease_bias = str(getattr(snapshot, "tease_bias", "") or "")
        return tone or stance or ambient_tone or tease_bias or "neutral"

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric)) if numeric <= 1.0 else numeric

    def _clamp01(self, value) -> float:
        numeric = self._float(value)
        return max(0.0, min(1.0, numeric))
