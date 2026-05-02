from .contracts import CognitiveActionPlan


ACTION_SPACE = (
    "no_speech",
    "observe",
    "tease",
    "protect",
    "withdraw",
    "ask",
    "reassure",
    "refuse",
    "mirror",
    "system_action",
)


class ActionPlanner:
    """Chooses the runtime action before any LLM wording step."""

    def plan(
        self,
        *,
        channel: str,
        snapshot=None,
        ti_report=None,
        fe_plan=None,
        appraisal=None,
        broadcast=None,
        user_text: str = "",
        force_speak: bool = False,
        proposed_intent: str = "",
        proposed_reason: str = "",
        proposed_speech_act: str = "",
        system_action: str = "",
        notes: tuple[str, ...] = (),
        concrete_signals: tuple[str, ...] = (),
    ) -> CognitiveActionPlan:
        speech_act = self._choose_speech_act(
            channel=channel,
            snapshot=snapshot,
            ti_report=ti_report,
            fe_plan=fe_plan,
            appraisal=appraisal,
            broadcast=broadcast,
            user_text=user_text,
            force_speak=force_speak,
            proposed_intent=proposed_intent,
            proposed_speech_act=proposed_speech_act,
            system_action=system_action,
            concrete_signals=concrete_signals,
        )
        should_speak = speech_act != "no_speech"
        speech_intent = self._legacy_speech_intent(
            speech_act,
            channel=channel,
            proposed_intent=proposed_intent,
            system_action=system_action,
        )
        risk_flags = self._risk_flags(
            channel=channel,
            snapshot=snapshot,
            appraisal=appraisal,
            broadcast=broadcast,
            force_speak=force_speak,
            speech_act=speech_act,
            system_action=system_action,
            concrete_signals=concrete_signals,
            notes=notes,
        )
        reason_to_speak = self._reason_to_speak(
            speech_act=speech_act,
            proposed_reason=proposed_reason,
            force_speak=force_speak,
            concrete_signals=concrete_signals,
            risk_flags=risk_flags,
        )
        animation_hint = self._animation_hint(
            speech_act=speech_act,
            ti_report=ti_report,
            system_action=system_action,
        )
        return CognitiveActionPlan(
            should_speak=should_speak,
            speech_intent=speech_intent,
            speech_act=speech_act,
            reason_to_speak=reason_to_speak,
            reason=reason_to_speak,
            animation_hint=animation_hint,
            system_action=system_action,
            risk_flags=risk_flags,
            notes=tuple(notes),
        )

    def _choose_speech_act(
        self,
        *,
        channel: str,
        snapshot,
        ti_report,
        fe_plan,
        appraisal,
        broadcast,
        user_text: str,
        force_speak: bool,
        proposed_intent: str,
        proposed_speech_act: str,
        system_action: str,
        concrete_signals: tuple[str, ...],
    ) -> str:
        if system_action:
            return "system_action"

        proposed = (proposed_speech_act or "").strip().lower()
        if proposed in ACTION_SPACE:
            return proposed

        intent = (proposed_intent or "").strip().lower()
        if intent == "no_speech":
            return "no_speech"
        if intent == "system_warning":
            return "protect"
        if intent == "screen_observation":
            return "observe"
        if intent == "playful_aside":
            return "tease"
        if intent == "brief_ack":
            return "mirror"

        if channel == "force_speak" or force_speak:
            if concrete_signals or self._broadcast_has_signal(broadcast):
                return "observe"
            return "withdraw"

        if channel == "chat":
            if self._looks_like_question(user_text):
                return "ask" if self._is_empty_or_vague(user_text) else "mirror"
            if self._is_attachment_dialogue(ti_report=ti_report, fe_plan=fe_plan, appraisal=appraisal):
                return "reassure"
            return "mirror"

        if self._appraisal_value(appraisal, "protectiveness") >= 0.72:
            return "protect"
        return "observe"

    def _legacy_speech_intent(
        self,
        speech_act: str,
        *,
        channel: str,
        proposed_intent: str,
        system_action: str,
    ) -> str:
        intent = (proposed_intent or "").strip()
        if speech_act == "no_speech":
            return "no_speech"
        if system_action or speech_act == "system_action":
            return "user_requested"
        if speech_act == "protect":
            return "system_warning"
        if speech_act == "observe":
            return "screen_observation"
        if speech_act == "tease":
            return "playful_aside"
        if speech_act in {"mirror", "withdraw", "ask", "reassure", "refuse"}:
            return "user_requested" if channel in {"chat", "force_speak"} else "brief_ack"
        if intent:
            return intent
        return "brief_ack"

    def _risk_flags(
        self,
        *,
        channel: str,
        snapshot,
        appraisal,
        broadcast,
        force_speak: bool,
        speech_act: str,
        system_action: str,
        concrete_signals: tuple[str, ...],
        notes: tuple[str, ...],
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if force_speak or channel == "force_speak":
            flags.append("force_speak_percept")
            if speech_act in {"withdraw", "no_speech"} and not concrete_signals and not self._broadcast_has_signal(broadcast):
                flags.append("force_speak_low_signal")
        if self._appraisal_value(appraisal, "threat") >= 0.66:
            flags.append("high_threat")
        if self._appraisal_value(appraisal, "certainty") <= 0.30:
            flags.append("low_certainty")
        if system_action:
            flags.append("system_action_requested")
        if "ambient_silence" in notes:
            flags.append("cooldown_suppression")
        if speech_act in {"observe", "tease"} and not concrete_signals and not self._broadcast_has_signal(broadcast):
            flags.append("avoid_fabrication")
        return tuple(dict.fromkeys(flags))

    def _reason_to_speak(
        self,
        *,
        speech_act: str,
        proposed_reason: str,
        force_speak: bool,
        concrete_signals: tuple[str, ...],
        risk_flags: tuple[str, ...],
    ) -> str:
        if speech_act == "no_speech":
            return proposed_reason or "Planner chose no_speech."
        if speech_act == "withdraw" and force_speak:
            return (
                "force_speak is a strong user percept, but there is no new concrete signal; "
                "acknowledge the request without inventing context."
            )
        if concrete_signals and speech_act == "observe":
            return "Concrete signal is available before LLM: " + ", ".join(concrete_signals[:2])
        if risk_flags:
            return proposed_reason or "Planner selected action with risk flags: " + ", ".join(risk_flags)
        return proposed_reason or f"Planner selected {speech_act}."

    def _animation_hint(self, *, speech_act: str, ti_report, system_action: str) -> str:
        fallback = str(getattr(ti_report, "animation_hint", "") or "stand")
        if system_action == "get_now_playing":
            return "read"
        if system_action in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        if speech_act == "protect":
            return fallback or "read"
        if speech_act == "withdraw":
            return "stand"
        return fallback

    def _broadcast_has_signal(self, broadcast) -> bool:
        if broadcast is None:
            return False
        if str(getattr(broadcast, "label", "") or "") in {
            "low_salience",
            "cycle_channel",
            "user_force_speak",
            "resource_pressure",
            "active_window",
            "focus_context",
        }:
            return False
        return bool(str(getattr(broadcast, "content", "") or "").strip())

    def _appraisal_value(self, appraisal, name: str) -> float:
        return self._float(getattr(appraisal, name, 0.0) if appraisal is not None else 0.0)

    def _is_attachment_dialogue(self, *, ti_report, fe_plan, appraisal) -> bool:
        return (
            str(getattr(ti_report, "mode", "") or "") == "chat_emotional"
            or str(getattr(fe_plan, "intent_label", "") or "") == "attachment_dialogue"
            or self._appraisal_value(appraisal, "tenderness") >= 0.52
        )

    def _looks_like_question(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        question_terms = (
            "?",
            "khong",
            "khong?",
            "sao",
            "gi",
            "nao",
            "ai",
            "why",
            "what",
            "how",
            "where",
            "when",
        )
        return any(term in lowered for term in question_terms)

    def _is_empty_or_vague(self, text: str) -> bool:
        tokens = [token for token in (text or "").strip().split() if token]
        return len(tokens) <= 2

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return numeric
