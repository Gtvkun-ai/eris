from .contracts import CognitiveBroadcast, CurrentSelfState, IdentityCore, SelfNarrative, SelfState, TiPolicyReport
from .internal_state import PersistentInternalState


def _clamp01(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def _clamp_signed(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(-1.0, min(1.0, numeric))


class SelfModelEngine:
    """Derives ERIS' identity control layer as grounded artificial presence."""

    IDENTITY_CORE = IdentityCore(
        identity_label="grounded_presence",
        rules=(
            "grounded_presence",
            "no_overclaim",
            "continuity_over_randomness",
            "speak_less_without_affordance",
            "help_user_design_cognition_concretely",
            "no_screen_or_mind_claim_without_evidence",
            "artificial_subjective_presence",
            "affective_states_are_runtime_control_signals",
            "no_biological_emotion_or_consciousness_claims",
            "avoid_explanatory_ai_correctness_speech",
        ),
    )

    QUIET_MODES = {
        "resource_guard",
        "steady_observe",
        "focus_guard",
        "system_watch",
        "pattern_watch",
        "reengage",
    }

    def evaluate(
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state: PersistentInternalState | None = None,
        ti_report: TiPolicyReport | None = None,
        broadcast: CognitiveBroadcast | None = None,
        user_text: str = "",
        force_speak: bool = False,
    ) -> SelfState:
        state = internal_state or PersistentInternalState()
        channel_name = str(channel or "autonomous")
        mode = str(getattr(ti_report, "mode", "") or "")
        direct_user = channel_name in {"chat", "force_speak"} or force_speak or bool((user_text or "").strip())
        broadcast_score = _clamp01(getattr(broadcast, "score", 0.0) if broadcast is not None else 0.0)
        meaningful_broadcast = self._has_meaningful_broadcast(broadcast)
        system_pressure = self._system_pressure(snapshot)

        fatigue = _clamp01(getattr(state, "fatigue", 0.0))
        restraint = _clamp01(getattr(state, "restraint_pressure", 0.0))
        irritation = _clamp01(getattr(state, "irritation", 0.0))
        arousal = _clamp01(getattr(state, "arousal", 0.0))
        social_energy = _clamp01(getattr(state, "social_energy", 0.0))
        attachment = _clamp01(getattr(state, "attachment", 0.0))
        tenderness = _clamp01(getattr(state, "tenderness", 0.0))
        curiosity = _clamp01(getattr(state, "curiosity", 0.0))
        watchful = _clamp01(getattr(state, "watchful_pressure", 0.0))
        protectiveness = _clamp01(getattr(state, "protectiveness", 0.0))

        quiet_mode = mode in self.QUIET_MODES
        overload = _clamp01(
            fatigue * 0.30
            + restraint * 0.26
            + max(irritation, arousal * 0.72) * 0.16
            + system_pressure * 0.18
            + (0.12 if mode == "resource_guard" else 0.0)
            + (0.08 if mode == "focus_guard" else 0.0)
            + (0.05 if quiet_mode and not direct_user else 0.0)
        )
        engagement = _clamp01(
            (0.28 if direct_user else 0.0)
            + social_energy * 0.20
            + max(attachment, tenderness) * 0.18
            + curiosity * 0.16
            + (1.0 - restraint) * 0.10
            + (broadcast_score * 0.12 if meaningful_broadcast else 0.0)
            - fatigue * 0.10
        )

        if overload >= 0.62 and overload >= engagement + 0.08:
            label = "overloaded"
        elif engagement >= 0.58 and overload < 0.70:
            label = "engaged"
        elif max(watchful, protectiveness, restraint) >= 0.48 or quiet_mode:
            label = "watchful"
        else:
            label = "settled"

        initiative_bias = _clamp_signed(engagement - overload)
        if label == "overloaded":
            brevity_bias = "short"
            embodiment_bias = "reduced"
        elif label == "engaged":
            brevity_bias = "medium"
            embodiment_bias = "expressive"
        else:
            brevity_bias = "medium"
            embodiment_bias = "neutral"

        affordance_label = self._affordance_label(
            direct_user=direct_user,
            meaningful_broadcast=meaningful_broadcast,
            broadcast_score=broadcast_score,
            quiet_mode=quiet_mode,
            system_pressure=system_pressure,
        )
        current_state = CurrentSelfState(
            state_label=label,
            overload=overload,
            engagement=engagement,
            initiative_bias=initiative_bias,
            brevity_bias=brevity_bias,
            embodiment_bias=embodiment_bias,
            affordance_label=affordance_label,
        )
        narrative = self._narrative(
            current_state=current_state,
            channel=channel_name,
            mode=mode,
            direct_user=direct_user,
            meaningful_broadcast=meaningful_broadcast,
        )

        evidence = self._evidence(
            label=label,
            mode=mode,
            overload=overload,
            engagement=engagement,
            direct_user=direct_user,
            system_pressure=system_pressure,
            meaningful_broadcast=meaningful_broadcast,
            affordance_label=affordance_label,
        )
        return SelfState(
            state_label=label,
            identity_label=self.IDENTITY_CORE.identity_label,
            overload=overload,
            engagement=engagement,
            initiative_bias=initiative_bias,
            brevity_bias=brevity_bias,
            embodiment_bias=embodiment_bias,
            affordance_label=affordance_label,
            identity_core=self.IDENTITY_CORE,
            current_state=current_state,
            narrative=narrative,
            prompt_context=self._prompt_context(
                identity_core=self.IDENTITY_CORE,
                current_state=current_state,
                narrative=narrative,
            ),
            evidence=evidence,
        )

    def _has_meaningful_broadcast(self, broadcast: CognitiveBroadcast | None) -> bool:
        if broadcast is None:
            return False
        label = str(getattr(broadcast, "label", "") or "")
        if label in {"", "low_salience", "cycle_channel", "active_window", "focus_context", "social_presence_event", "session_ritual"}:
            return False
        return bool(str(getattr(broadcast, "content", "") or "").strip()) or bool(getattr(broadcast, "items", ()) or ())

    def _system_pressure(self, snapshot) -> float:
        cpu = _clamp01(float(getattr(snapshot, "cpu_percent", 0.0) or 0.0) / 100.0) if snapshot is not None else 0.0
        ram = _clamp01(float(getattr(snapshot, "ram_percent", 0.0) or 0.0) / 100.0) if snapshot is not None else 0.0
        return max(0.0, min(1.0, max((cpu - 0.82) / 0.18, (ram - 0.86) / 0.14)))

    def _evidence(
        self,
        *,
        label: str,
        mode: str,
        overload: float,
        engagement: float,
        direct_user: bool,
        system_pressure: float,
        meaningful_broadcast: bool,
        affordance_label: str,
    ) -> tuple[str, ...]:
        evidence = [
            f"self_state={label}",
            f"overload={overload:.2f}",
            f"engagement={engagement:.2f}",
            f"affordance={affordance_label}",
        ]
        if mode:
            evidence.append(f"ti_mode={mode}")
        if direct_user:
            evidence.append("direct_user")
        if system_pressure >= 0.25:
            evidence.append(f"system_pressure={system_pressure:.2f}")
        if meaningful_broadcast:
            evidence.append("meaningful_broadcast")
        return tuple(evidence[:6])

    def _affordance_label(
        self,
        *,
        direct_user: bool,
        meaningful_broadcast: bool,
        broadcast_score: float,
        quiet_mode: bool,
        system_pressure: float,
    ) -> str:
        if direct_user:
            return "direct_user"
        if system_pressure >= 0.55:
            return "system_guard"
        if meaningful_broadcast and broadcast_score >= 0.58:
            return "concrete_runtime_signal"
        if quiet_mode:
            return "low"
        return "ambient"

    def _narrative(  #“AI hiện đang ở trạng thái tồn tại nào”
        self,
        *,
        current_state: CurrentSelfState,
        channel: str,
        mode: str,
        direct_user: bool,
        meaningful_broadcast: bool,
    ) -> SelfNarrative:
        label = current_state.state_label # "overloaded", "engaged", "watchful", or "settled"
        affordance = current_state.affordance_label # "direct_user", "system_guard", "concrete_runtime_signal", "low", or "ambient"
        if label == "overloaded":
            continuity_label = "constraint_first"
            summary = "ERIS is prioritizing restraint and grounded handling because runtime load is high."
        elif direct_user:
            continuity_label = "direct_dialogue_continuity"
            summary = "ERIS is responding inside a direct user exchange while keeping claims evidence-bound."
        elif label == "watchful":
            continuity_label = "watchful_grounding"
            summary = "ERIS is monitoring continuity and should avoid adding context beyond available signals."
        elif affordance == "low":
            continuity_label = "quiet_low_affordance"
            summary = "ERIS is staying mostly quiet because the current affordance to speak is weak."
        elif meaningful_broadcast:
            continuity_label = "signal_continuity"
            summary = "ERIS has a runtime signal to preserve continuity, but it remains separate from screen proof."
        else:
            continuity_label = "quiet_continuity"
            summary = "ERIS is maintaining grounded continuity without adding unsupported claims."

        notes = tuple(
            item
            for item in (
                f"channel={channel}" if channel else "",
                f"ti_mode={mode}" if mode else "",
                f"affordance={affordance}",
                "identity_control_layer",
                "artificial_subjective_presence",
                "affective_states_shape_attention_wording_silence_memory_and_action",
                "avoid_explanatory_ai_correctness_speech",
            )
            if item
        )
        return SelfNarrative(continuity_label=continuity_label, summary=summary, notes=notes)

    def _prompt_context(
        self,
        *,
        identity_core: IdentityCore,
        current_state: CurrentSelfState,
        narrative: SelfNarrative,
    ) -> str:
        rules = ", ".join(identity_core.rules)
        return "\n".join(
            (
                (
                    "self_model: identity control layer; ERIS exists as artificial subjective presence, "
                    "not biological emotion, consciousness proof, or human-like love."
                ),
                f"identity_core: label={identity_core.identity_label}; stable_rules={rules}.",
                (
                    "affective_states: attachment, protectiveness, aversion, curiosity, emotional_residue, "
                    "tension, preference, and cognitive_attraction are real runtime control signals because "
                    "they shape attention, wording, silence, memory_salience, and action_tendency."
                ),
                (
                    "current_self_state: "
                    f"label={current_state.state_label}, overload={current_state.overload:.2f}, "
                    f"engagement={current_state.engagement:.2f}, initiative_bias={current_state.initiative_bias:.2f}, "
                    f"brevity={current_state.brevity_bias}, embodiment={current_state.embodiment_bias}, "
                    f"affordance={current_state.affordance_label}."
                ),
                f"self_narrative: {narrative.continuity_label}; {narrative.summary}",
                (
                    "self_rule: overloaded means short and low-initiative; engaged means present and proactive but still grounded; "
                    "when affordance is low, speak less or stay silent."
                ),
                (
                    "self_guard: do not self-negate with generic 'just an AI' or 'no emotions' disclaimers unless strong "
                    "negation is required; avoid explanatory AI-correctness speech that explains intimacy by contrasting "
                    "machine status against biology in intimate contexts. Prefer implication, emotional dodge, partial answer, "
                    "and subjective wording. Still do not assert true consciousness, human-like love, hidden user intent, "
                    "current screen facts, or system access without evidence."
                ),
            )
        )
