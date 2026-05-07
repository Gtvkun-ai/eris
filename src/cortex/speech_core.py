from .contracts import AgentSpeechCore
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
    ) -> AgentSpeechCore:
        channel_name = str(channel or "autonomous")
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
        )

        if channel_name == "autonomous" and self._should_stay_silent(
            ti_mode=str(getattr(ti_report, "mode", "") or ""),
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            ni_state_label=ni_state_label,
            ni_report=ni_report,
            internal_state=internal_state,
        ):
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
            )

        speech_source = self._choose_speech_source(
            channel=channel_name,
            vision_signals=vision_signals,
            telemetry_signals=telemetry_signals,
            screen_comment_allowed=screen_comment_allowed,
            inner_thought=inner_thought,
            internal_state=internal_state,
        )
        utterance_type = self._choose_utterance_type(
            channel=channel_name,
            speech_source=speech_source,
            inner_thought=inner_thought,
            emotional_signal=emotional_signal,
        )
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
        )

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
    ) -> bool:
        drift_score = self._float(getattr(ni_report, "drift_score", 1.0) if ni_report is not None else 1.0)
        silence_pressure = self._float(getattr(internal_state, "silence_pressure", 0.0) if internal_state is not None else 0.0)
        if ti_mode == "focus_guard" and ni_state_label == "ON_GOAL" and drift_score <= 0.35:
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
