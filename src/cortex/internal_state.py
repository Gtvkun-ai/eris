from dataclasses import dataclass


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = minimum
    if numeric != numeric:
        numeric = minimum
    return max(minimum, min(maximum, numeric))


def _clamp_signed(value: float) -> float:
    return _clamp(value, minimum=-1.0, maximum=1.0)


def _smooth(previous: float, signal: float, *, inertia: float = 0.84) -> float:
    inertia = _clamp(inertia, minimum=0.0, maximum=1.0)
    return previous * inertia + signal * (1.0 - inertia)


def _clean_label(value: object, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _append_recent(items: tuple[str, ...], value: str, *, limit: int = 8) -> tuple[str, ...]:
    text = _clean_label(value)
    if not text:
        return tuple(items[-limit:])
    return (*items, text)[-limit:]


@dataclass(slots=True)
class PersistentInternalState:
    """Runtime continuity state, not a claim about real emotion."""

    valence: float = 0.05
    arousal: float = 0.18
    curiosity: float = 0.34
    boredom: float = 0.0
    social_energy: float = 0.56
    attachment: float = 0.34
    irritation: float = 0.08
    protectiveness: float = 0.10
    confidence: float = 0.50
    fatigue: float = 0.10
    tenderness: float = 0.18
    silence_pressure: float = 0.0

    last_channel: str = ""
    last_focus_kind: str = ""
    last_ti_mode: str = ""
    last_stance: str = ""
    last_speech_act: str = ""
    last_utterance_type: str = ""
    last_inner_intent: str = ""

    silence_ticks: int = 0
    spoken_ticks: int = 0
    chat_ticks: int = 0
    force_speak_ticks: int = 0
    cycle_count: int = 0

    recent_channels: tuple[str, ...] = ()
    recent_focus_kinds: tuple[str, ...] = ()
    recent_stances: tuple[str, ...] = ()
    recent_speech_acts: tuple[str, ...] = ()
    recent_inner_intents: tuple[str, ...] = ()
    recent_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "valence": round(float(self.valence), 3),
            "arousal": round(float(self.arousal), 3),
            "curiosity": round(float(self.curiosity), 3),
            "boredom": round(float(self.boredom), 3),
            "social_energy": round(float(self.social_energy), 3),
            "attachment": round(float(self.attachment), 3),
            "irritation": round(float(self.irritation), 3),
            "protectiveness": round(float(self.protectiveness), 3),
            "confidence": round(float(self.confidence), 3),
            "fatigue": round(float(self.fatigue), 3),
            "tenderness": round(float(self.tenderness), 3),
            "silence_pressure": round(float(self.silence_pressure), 3),
            "last_channel": self.last_channel,
            "last_focus_kind": self.last_focus_kind,
            "last_ti_mode": self.last_ti_mode,
            "last_stance": self.last_stance,
            "last_speech_act": self.last_speech_act,
            "last_utterance_type": self.last_utterance_type,
            "last_inner_intent": self.last_inner_intent,
            "silence_ticks": int(self.silence_ticks),
            "spoken_ticks": int(self.spoken_ticks),
            "chat_ticks": int(self.chat_ticks),
            "force_speak_ticks": int(self.force_speak_ticks),
            "cycle_count": int(self.cycle_count),
            "recent_channels": list(self.recent_channels),
            "recent_focus_kinds": list(self.recent_focus_kinds),
            "recent_stances": list(self.recent_stances),
            "recent_speech_acts": list(self.recent_speech_acts),
            "recent_inner_intents": list(self.recent_inner_intents),
            "recent_notes": list(self.recent_notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PersistentInternalState":
        if not isinstance(data, dict):
            return cls()
        return cls(
            valence=_clamp_signed(data.get("valence", 0.05)),
            arousal=_clamp(data.get("arousal", 0.18)),
            curiosity=_clamp(data.get("curiosity", 0.34)),
            boredom=_clamp(data.get("boredom", 0.0)),
            social_energy=_clamp(data.get("social_energy", 0.56)),
            attachment=_clamp(data.get("attachment", 0.34)),
            irritation=_clamp(data.get("irritation", 0.08)),
            protectiveness=_clamp(data.get("protectiveness", 0.10)),
            confidence=_clamp(data.get("confidence", 0.50)),
            fatigue=_clamp(data.get("fatigue", 0.10)),
            tenderness=_clamp(data.get("tenderness", 0.18)),
            silence_pressure=_clamp(data.get("silence_pressure", 0.0)),
            last_channel=_clean_label(data.get("last_channel")),
            last_focus_kind=_clean_label(data.get("last_focus_kind")),
            last_ti_mode=_clean_label(data.get("last_ti_mode")),
            last_stance=_clean_label(data.get("last_stance")),
            last_speech_act=_clean_label(data.get("last_speech_act")),
            last_utterance_type=_clean_label(data.get("last_utterance_type")),
            last_inner_intent=_clean_label(data.get("last_inner_intent")),
            silence_ticks=max(0, int(data.get("silence_ticks", 0) or 0)),
            spoken_ticks=max(0, int(data.get("spoken_ticks", 0) or 0)),
            chat_ticks=max(0, int(data.get("chat_ticks", 0) or 0)),
            force_speak_ticks=max(0, int(data.get("force_speak_ticks", 0) or 0)),
            cycle_count=max(0, int(data.get("cycle_count", 0) or 0)),
            recent_channels=tuple(str(item) for item in (data.get("recent_channels") or ()) if str(item or "").strip())[-8:],
            recent_focus_kinds=tuple(str(item) for item in (data.get("recent_focus_kinds") or ()) if str(item or "").strip())[-8:],
            recent_stances=tuple(str(item) for item in (data.get("recent_stances") or ()) if str(item or "").strip())[-8:],
            recent_speech_acts=tuple(str(item) for item in (data.get("recent_speech_acts") or ()) if str(item or "").strip())[-8:],
            recent_inner_intents=tuple(str(item) for item in (data.get("recent_inner_intents") or ()) if str(item or "").strip())[-8:],
            recent_notes=tuple(str(item) for item in (data.get("recent_notes") or ()) if str(item or "").strip())[-8:],
        )

    def to_prompt_context(self) -> str:
        recent_acts = ", ".join(self.recent_speech_acts[-4:]) or "none"
        recent_notes = "; ".join(self.recent_notes[-3:]) or "none"
        return "\n".join(
            (
                "persistent_internal_state: runtime continuity only, not current screen evidence.",
                (
                    "state_axes: "
                    f"valence={self.valence:.2f}, arousal={self.arousal:.2f}, "
                    f"curiosity={self.curiosity:.2f}, boredom={self.boredom:.2f}, "
                    f"social_energy={self.social_energy:.2f}, attachment={self.attachment:.2f}, "
                    f"irritation={self.irritation:.2f}, protectiveness={self.protectiveness:.2f}, "
                    f"confidence={self.confidence:.2f}, fatigue={self.fatigue:.2f}, "
                    f"tenderness={self.tenderness:.2f}, silence_pressure={self.silence_pressure:.2f}."
                ),
                (
                    "state_labels: "
                    f"last_focus={self.last_focus_kind or 'unknown'}, "
                    f"last_ti_mode={self.last_ti_mode or 'unknown'}, "
                    f"last_stance={self.last_stance or 'unknown'}, "
                    f"last_channel={self.last_channel or 'unknown'}."
                ),
                f"recent_speech_acts: {recent_acts}.",
                f"continuity_notes: {recent_notes}.",
                "use_state_rule: preserve rhythm and continuity only; never treat this as proof of the user's current screen or hidden feelings.",
            )
        )


class InternalStateEngine:
    """Maintains a low-gain continuity state across cognitive frames."""

    def sense_update(
        self,
        state: PersistentInternalState,
        *,
        channel: str,
        snapshot=None,
        ni_report=None,
        ti_report=None,
        fe_plan=None,
        broadcast=None,
        user_text: str = "",
        force_speak: bool = False,
    ) -> PersistentInternalState:
        channel_name = _clean_label(channel, fallback="autonomous")
        focus_kind = _clean_label(getattr(snapshot, "active_window_kind", ""), fallback=state.last_focus_kind or "unknown")
        ti_mode = _clean_label(getattr(ti_report, "mode", ""), fallback=state.last_ti_mode or "unknown")
        direct_user = channel_name in {"chat", "force_speak"} or force_speak or bool((user_text or "").strip())
        drift = _clamp(getattr(ni_report, "drift_score", 0.0))
        ni_confidence = _clamp(getattr(ni_report, "confidence", state.confidence))
        warmth = _clamp(getattr(fe_plan, "warmth_level", 0.0))
        sarcasm = _clamp(getattr(fe_plan, "sarcasm_level", 0.0))
        broadcast_score = _clamp(getattr(broadcast, "score", 0.0))
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))

        user_signals = getattr(snapshot, "user_signals", None)
        focus_pattern = _clean_label(getattr(user_signals, "focus_pattern", ""))
        switching = _clean_label(getattr(user_signals, "window_switching", ""))

        boredom_signal = 0.0
        if channel_name == "autonomous":
            boredom_signal += min(0.44, idle_seconds / 1800.0)
        if focus_kind in {"general", "entertainment"} and idle_seconds >= 240:
            boredom_signal += 0.12
        if focus_pattern in {"passive_consumption", "absent"}:
            boredom_signal += 0.10
        boredom_signal = _clamp(boredom_signal)

        curiosity_signal = _clamp(
            0.18
            + drift * 0.20
            + broadcast_score * 0.18
            + (0.14 if focus_kind in {"coding", "documentation"} else 0.0)
            + (0.08 if ti_mode == "pattern_muse" else 0.0)
            - boredom_signal * 0.12
        )
        social_energy_signal = _clamp(
            0.40
            + (0.22 if direct_user else 0.0)
            + warmth * 0.20
            - boredom_signal * 0.10
            - (0.10 if focus_pattern in {"stuck", "absent"} else 0.0)
        )
        attachment_signal = _clamp(
            state.attachment
            + (0.10 if direct_user else -0.01)
            + warmth * 0.12
            + (0.05 if force_speak else 0.0)
        )
        irritation_signal = _clamp(
            state.irritation * 0.72
            + sarcasm * 0.22
            + drift * 0.12
            + (0.08 if switching == "high" else 0.0)
            - warmth * 0.08
        )
        protectiveness_signal = _clamp(
            state.protectiveness * 0.70
            + (0.34 if ti_mode == "resource_guard" else 0.0)
            + (0.18 if getattr(ni_report, "should_raise_guard", False) else 0.0)
            + broadcast_score * 0.16
        )
        fatigue_signal = _clamp(
            0.06
            + (0.18 if idle_seconds >= 180 else 0.0)
            + (0.16 if idle_seconds >= 600 else 0.0)
            + (0.10 if focus_pattern in {"stuck", "absent", "passive_consumption"} else 0.0)
            - (0.04 if direct_user else 0.0)
        )
        tenderness_signal = _clamp(
            0.08
            + warmth * 0.50
            + attachment_signal * 0.26
            + (0.08 if channel_name in {"chat", "force_speak"} else 0.0)
            - irritation_signal * 0.12
        )
        silence_signal = _clamp(
            state.silence_pressure
            + (0.10 if channel_name == "autonomous" and idle_seconds >= 240 else 0.0)
            + (0.08 if force_speak else 0.0)
            - (0.06 if direct_user else 0.0)
        )
        valence_signal = _clamp_signed(
            0.10
            + warmth * 0.18
            + tenderness_signal * 0.18
            + curiosity_signal * 0.08
            - irritation_signal * 0.24
            - fatigue_signal * 0.18
        )
        arousal_signal = _clamp(
            0.16
            + drift * 0.20
            + broadcast_score * 0.24
            + (0.16 if direct_user else 0.0)
            + (0.10 if switching == "high" else 0.0)
        )

        sensed = PersistentInternalState(
            valence=_clamp_signed(_smooth(state.valence, valence_signal, inertia=0.86)),
            arousal=_clamp(_smooth(state.arousal, arousal_signal, inertia=0.82)),
            curiosity=_clamp(_smooth(state.curiosity, curiosity_signal, inertia=0.84)),
            boredom=_clamp(_smooth(state.boredom, boredom_signal, inertia=0.80)),
            social_energy=_clamp(_smooth(state.social_energy, social_energy_signal, inertia=0.86)),
            attachment=_clamp(_smooth(state.attachment, attachment_signal, inertia=0.90)),
            irritation=_clamp(_smooth(state.irritation, irritation_signal, inertia=0.88)),
            protectiveness=_clamp(_smooth(state.protectiveness, protectiveness_signal, inertia=0.82)),
            confidence=_clamp(_smooth(state.confidence, ni_confidence, inertia=0.84)),
            fatigue=_clamp(_smooth(state.fatigue, fatigue_signal, inertia=0.82)),
            tenderness=_clamp(_smooth(state.tenderness, tenderness_signal, inertia=0.86)),
            silence_pressure=_clamp(_smooth(state.silence_pressure, silence_signal, inertia=0.78)),
            last_channel=channel_name,
            last_focus_kind=focus_kind,
            last_ti_mode=ti_mode,
            last_stance=state.last_stance,
            last_speech_act=state.last_speech_act,
            last_utterance_type=state.last_utterance_type,
            last_inner_intent=state.last_inner_intent,
            silence_ticks=state.silence_ticks,
            spoken_ticks=state.spoken_ticks,
            chat_ticks=state.chat_ticks,
            force_speak_ticks=state.force_speak_ticks,
            cycle_count=state.cycle_count,
            recent_channels=state.recent_channels,
            recent_focus_kinds=state.recent_focus_kinds,
            recent_stances=state.recent_stances,
            recent_speech_acts=state.recent_speech_acts,
            recent_inner_intents=state.recent_inner_intents,
            recent_notes=state.recent_notes,
        )
        return sensed

    def commit_turn(
        self,
        state: PersistentInternalState,
        *,
        channel: str,
        snapshot=None,
        ti_report=None,
        appraisal=None,
        speech_core=None,
        action_plan=None,
        inner_thought=None,
        was_spoken: bool = False,
    ) -> PersistentInternalState:
        channel_name = _clean_label(channel, fallback="autonomous")
        focus_kind = _clean_label(getattr(snapshot, "active_window_kind", ""), fallback=state.last_focus_kind or "unknown")
        ti_mode = _clean_label(getattr(ti_report, "mode", ""), fallback=state.last_ti_mode or "unknown")
        stance = _clean_label(getattr(appraisal, "stance", ""), fallback=state.last_stance or "grounded")
        speech_act = _clean_label(getattr(action_plan, "speech_act", "") or getattr(speech_core, "utterance_type", ""))
        utterance_type = _clean_label(getattr(speech_core, "utterance_type", ""))
        inner_intent = _clean_label(
            getattr(inner_thought, "intent", "") or getattr(getattr(speech_core, "inner_thought", None), "intent", "")
        )

        no_speech = not was_spoken or speech_act == "no_speech" or utterance_type == "no_speech"
        silence_ticks = state.silence_ticks + 1 if no_speech else 0
        spoken_ticks = state.spoken_ticks + 1 if was_spoken else 0
        chat_ticks = state.chat_ticks + 1 if channel_name == "chat" else max(0, state.chat_ticks - 1)
        force_speak_ticks = state.force_speak_ticks + 1 if channel_name == "force_speak" else max(0, state.force_speak_ticks - 1)

        silence_pressure = _clamp(
            _smooth(
                state.silence_pressure,
                min(1.0, silence_ticks / 9.0) - (0.34 if was_spoken else 0.0),
                inertia=0.68,
            )
        )
        boredom = _clamp(_smooth(state.boredom, min(1.0, silence_ticks / 14.0), inertia=0.84)) if no_speech else _clamp(state.boredom * 0.82)
        social_energy = _clamp(state.social_energy + (0.05 if channel_name in {"chat", "force_speak"} else 0.0) - (0.04 if no_speech and channel_name == "autonomous" else 0.0))
        attachment = _clamp(state.attachment + (0.04 if channel_name in {"chat", "force_speak"} else 0.0))

        notes = self._derive_notes(
            focus_kind=focus_kind,
            stance=stance,
            speech_act=speech_act,
            inner_intent=inner_intent,
            silence_ticks=silence_ticks,
            silence_pressure=silence_pressure,
            boredom=boredom,
            protectiveness=state.protectiveness,
            was_spoken=was_spoken,
        )

        return PersistentInternalState(
            valence=state.valence,
            arousal=state.arousal,
            curiosity=state.curiosity,
            boredom=boredom,
            social_energy=social_energy,
            attachment=attachment,
            irritation=state.irritation,
            protectiveness=state.protectiveness,
            confidence=state.confidence,
            fatigue=state.fatigue,
            tenderness=state.tenderness,
            silence_pressure=silence_pressure,
            last_channel=channel_name,
            last_focus_kind=focus_kind,
            last_ti_mode=ti_mode,
            last_stance=stance,
            last_speech_act=speech_act,
            last_utterance_type=utterance_type,
            last_inner_intent=inner_intent,
            silence_ticks=silence_ticks,
            spoken_ticks=spoken_ticks,
            chat_ticks=chat_ticks,
            force_speak_ticks=force_speak_ticks,
            cycle_count=state.cycle_count + 1,
            recent_channels=_append_recent(state.recent_channels, channel_name),
            recent_focus_kinds=_append_recent(state.recent_focus_kinds, focus_kind),
            recent_stances=_append_recent(state.recent_stances, stance),
            recent_speech_acts=_append_recent(state.recent_speech_acts, speech_act or utterance_type),
            recent_inner_intents=_append_recent(state.recent_inner_intents, inner_intent),
            recent_notes=notes,
        )

    def render_prompt_context(self, state: PersistentInternalState) -> str:
        return state.to_prompt_context()

    def _derive_notes(
        self,
        *,
        focus_kind: str,
        stance: str,
        speech_act: str,
        inner_intent: str,
        silence_ticks: int,
        silence_pressure: float,
        boredom: float,
        protectiveness: float,
        was_spoken: bool,
    ) -> tuple[str, ...]:
        notes: list[str] = []
        if silence_ticks >= 4:
            notes.append(f"silence_streak={silence_ticks}: small presence only if speech_core permits")
        if silence_pressure >= 0.56:
            notes.append("silence_pressure_high: continuity wants presence, not screen invention")
        if boredom >= 0.46:
            notes.append("boredom_rising: avoid repeating the same observation")
        if protectiveness >= 0.58:
            notes.append("protective_bias: concise and grounded")
        if was_spoken:
            notes.append("spoken_this_turn: reset cold-restart feeling")
        if speech_act:
            notes.append(f"last_act={speech_act}")
        if inner_intent:
            notes.append(f"inner_intent={inner_intent}")
        if focus_kind:
            notes.append(f"focus_continuity={focus_kind}")
        if stance:
            notes.append(f"stance_continuity={stance}")
        return tuple(notes[-8:])
