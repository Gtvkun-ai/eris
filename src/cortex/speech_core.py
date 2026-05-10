from .contracts import AgentSpeechCore, MotivationalPressureReport, MotivationalUrge, SelfState
from .internal_state import PersistentInternalState
from .inner_thought import InnerThoughtEngine


class SpeechCoreEngine:
    """Shared chooser for when to speak, what grounds the line, and its utterance type."""

    QUIET_MODES = {
        "resource_guard",
        "steady_observe",
        "focus_guard",
        "system_watch",
        "pattern_watch",
        "reengage",
    }

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

    def __init__(self, *, inner_thought_engine: InnerThoughtEngine | None = None):
        self.inner_thought_engine = inner_thought_engine or InnerThoughtEngine()

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
    ) -> AgentSpeechCore:
        channel_name = str(channel or "autonomous")
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

        if channel_name == "autonomous" and self._should_stay_silent(
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
            return AgentSpeechCore(
                perception=tuple(concrete_signals or ()),
                mood=self._resolve_mood(snapshot=snapshot, appraisal=appraisal, fe_plan=fe_plan),
                impulse="silent",
                utterance_type="no_speech",
                grounding="none",
                speech_source="none",
                reason="SpeechCore held silence because the autonomous context is repeating or quiet.",
                should_speak=False,
                safety_flags=("repeat_guard",) if repeat_count >= 2 or repeated_topic_streak >= 2 else (),
                delivery="silence",
                inner_thought=inner_thought,
                motivation_pressure=pressure_report,
            )

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
                utterance_type = "random_chatter"

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
        return AgentSpeechCore(
            perception=perception,
            mood=self._resolve_mood(snapshot=snapshot, appraisal=appraisal, fe_plan=fe_plan),
            impulse="must_speak" if channel_name == "force_speak" else ("speak" if should_speak else "silent"),
            utterance_type=utterance_type if should_speak else "no_speech",
            grounding=self._grounding_for_source(speech_source),
            speech_source=speech_source if should_speak else "none",
            reason=self._build_reason(
                channel=channel_name,
                speech_source=speech_source,
                utterance_type=utterance_type,
                inner_thought=inner_thought,
                emotional_signal=emotional_signal,
            ),
            should_speak=should_speak,
            safety_flags=safety_flags,
            delivery="speak" if should_speak else "silence",
            inner_thought=inner_thought,
            motivation_pressure=pressure_report,
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
        )
        candidates = self._apply_self_state_to_candidates(candidates, channel=channel, self_state=self_state)
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
    ) -> tuple[MotivationalUrge, ...]:
        state = internal_state or PersistentInternalState()
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

        candidates: list[MotivationalUrge] = []
        candidates.append(
            MotivationalUrge(
                label="screen_vision",
                score=1.18 if screen_comment_allowed and vision_signals else 0.0,
                utterance_type="vision_comment",
                speech_source="vision",
                grounding="screen_vision",
                reason="Visual evidence is concrete enough to speak from.",
                evidence=tuple(vision_signals[:2]),
                safety_flags=("grounded_screen_comment",),
                blocked=not (screen_comment_allowed and vision_signals),
            )
        )
        candidates.append(
            MotivationalUrge(
                label="screen_telemetry",
                score=1.10 if screen_comment_allowed and telemetry_signals else 0.0,
                utterance_type="telemetry_comment",
                speech_source="telemetry",
                grounding="screen_telemetry",
                reason="Runtime telemetry evidence is concrete enough to speak from.",
                evidence=tuple(telemetry_signals[:2]),
                safety_flags=("grounded_screen_comment",),
                blocked=not (screen_comment_allowed and telemetry_signals),
            )
        )

        user_requested_score = (
            0.92
            + self._pressure(state, "social_pressure") * 0.20
            + self._pressure(state, "tender_pressure") * 0.08
            - fatigue * 0.08
        )
        candidates.append(
            MotivationalUrge(
                label="user_requested_presence",
                score=user_requested_score if channel == "force_speak" else 0.0,
                utterance_type=self._inner_utterance(inner_intent, fallback="inner_whim"),
                speech_source="freeform",
                grounding="ungrounded",
                reason="User explicitly requested presence.",
                evidence=(self._inner_anchor(inner_thought) or "force_speak requested",),
                safety_flags=("force_speak_required", "no_screen_claim", "anti_mindreading"),
                blocked=channel != "force_speak",
            )
        )

        protective_score = max(protectiveness, threat, self._pressure(state, "protective_pressure")) + (0.12 if mode == "resource_guard" else 0.0)
        candidates.append(
            MotivationalUrge(
                label="protective_guard",
                score=protective_score,
                utterance_type="soft_boundary",
                speech_source="freeform",
                grounding="ungrounded",
                reason="Protective pressure is high enough to prefer a guarded boundary.",
                evidence=(f"protectiveness={protectiveness:.2f}; threat={threat:.2f}",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=protective_score < 0.64 or bool(concrete_signals),
            )
        )

        tender_score = max(tenderness, intimacy * 0.90, self._pressure(state, "tender_pressure"))
        if emotional_signal:
            tender_score = max(tender_score, 1.04)
        candidates.append(
            MotivationalUrge(
                label="tender_checkin",
                score=tender_score,
                utterance_type="relational_checkin",
                speech_source="freeform",
                grounding="ungrounded",
                reason="Explicit emotional signal or tender pressure asks for a check-in.",
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
        if surface_novelty < 0.35:
            thought_surface_score *= 0.72
        candidates.append(
            MotivationalUrge(
                label="thought_stream_surface",
                score=min(1.0, thought_surface_score),
                utterance_type=self._inner_utterance(inner_intent, fallback="inner_whim"),
                speech_source="freeform",
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
            0.62 if inner_surface else 0.0,
        )
        if idle_seconds >= 420:
            social_score += 0.10
        candidates.append(
            MotivationalUrge(
                label="social_presence",
                score=min(1.0, social_score),
                utterance_type=self._inner_utterance(inner_intent, fallback="inner_whim"),
                speech_source="freeform",
                grounding="ungrounded",
                reason="Social presence pressure wants a small ungrounded line.",
                evidence=(self._inner_anchor(inner_thought) or f"idle={int(idle_seconds)}s",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or (not inner_surface and social_score < 0.54),
            )
        )

        curiosity_score = max(
            self._pressure(state, "curiosity_pressure"),
            self._float(getattr(state, "curiosity", 0.0)) * 0.72,
            0.64 if inner_intent == "curious_question" else 0.0,
        )
        candidates.append(
            MotivationalUrge(
                label="curiosity",
                score=curiosity_score,
                utterance_type="curious_question",
                speech_source="freeform",
                grounding="ungrounded",
                reason="Curiosity pressure wants a small question.",
                evidence=(inner_seed or self._inner_anchor(inner_thought) or "curiosity_pressure",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or curiosity_score < 0.50,
            )
        )

        playful_score = max(self._pressure(state, "playful_pressure"), amusement)
        candidates.append(
            MotivationalUrge(
                label="playful_aside",
                score=playful_score,
                utterance_type="light_muse",
                speech_source="freeform",
                grounding="ungrounded",
                reason="Playful pressure is present but stays low priority.",
                evidence=(f"amusement={amusement:.2f}",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or playful_score < 0.56,
            )
        )

        watchful_score = max(self._pressure(state, "watchful_pressure"), jealousy_lite, threat * 0.72)
        candidates.append(
            MotivationalUrge(
                label="watchful_boundary",
                score=watchful_score,
                utterance_type="soft_boundary",
                speech_source="freeform",
                grounding="ungrounded",
                reason="Watchful pressure wants restraint with a boundary.",
                evidence=(f"watchful={watchful_score:.2f}",),
                safety_flags=("no_screen_claim", "anti_mindreading"),
                blocked=bool(concrete_signals) or watchful_score < 0.58,
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
                    if candidate.speech_source in {"freeform", "none"}:
                        score *= max(0.58, 1.0 - overload * 0.34)
                    elif candidate.speech_source in {"vision", "telemetry"}:
                        score *= max(0.82, 1.0 - overload * 0.12)
                if label == "engaged" and candidate.label in {"social_presence", "curiosity", "thought_stream_surface", "subconscious_seed"}:
                    score += engagement * 0.12
            elif channel == "force_speak" and label == "overloaded" and candidate.speech_source in {"freeform", "random"}:
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
                    grounding=candidate.grounding,
                    reason=candidate.reason,
                    evidence=evidence,
                    safety_flags=candidate.safety_flags,
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
            grounding="none",
            reason=reason,
            evidence=evidence,
            safety_flags=("quiet_guard",) if not blocked else (),
            blocked=blocked,
        )

    def _threshold_for_channel(self, channel: str, *, self_state: SelfState | None = None) -> float:
        if channel == "autonomous":
            overload = self._clamp01(getattr(self_state, "overload", 0.0) if self_state is not None else 0.0)
            engagement = self._clamp01(getattr(self_state, "engagement", 0.0) if self_state is not None else 0.0)
            return self._clamp01(0.55 + overload * 0.16 - engagement * 0.08)
        if channel == "force_speak":
            return 0.0
        return 0.45

    def _score_restraint(self, *, internal_state: PersistentInternalState | None, ti_report, self_state: SelfState | None = None) -> float:
        state = internal_state or PersistentInternalState()
        mode = str(getattr(ti_report, "mode", "") or "")
        score = (
            0.20
            + self._pressure(state, "restraint_pressure") * 0.54
            + self._float(getattr(state, "fatigue", 0.0)) * 0.16
            - self._float(getattr(state, "silence_pressure", 0.0)) * 0.18
        )
        if mode in self.QUIET_MODES or mode == "social_watch":
            score += 0.18
        if mode == "focus_guard":
            score += 0.16
        if self_state is not None:
            score += self._clamp01(getattr(self_state, "overload", 0.0)) * 0.18
            score -= self._clamp01(getattr(self_state, "engagement", 0.0)) * 0.06
        return self._clamp01(score)

    def _pressure(self, state: PersistentInternalState, name: str) -> float:
        return self._float(getattr(state, name, 0.0))

    def _inner_utterance(self, inner_intent: str, *, fallback: str) -> str:
        if inner_intent in {"random_chatter", "inner_whim", "curious_question"}:
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
        if repeat_count >= 2 and ti_mode in self.QUIET_MODES:
            return True
        if repeat_count >= 3:
            return True
        if repeated_topic_tag and repeated_topic_streak >= 2 and ti_mode in self.QUIET_MODES:
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
            return "relational_checkin"

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
        if speech_source in {"vision", "telemetry"}:
            flags.append("grounded_screen_comment")
        if emotional_signal:
            flags.append("explicit_emotional_signal")
        if utterance_type == "relational_checkin" and not emotional_signal:
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
        if speech_source == "freeform":
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
        mood = str(getattr(snapshot, "mood_label", "") or "")
        return tone or stance or mood or "neutral"

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
