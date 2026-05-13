from .contracts import CognitiveActionPlan, SelfState


ACTION_SPACE = (
    "no_speech",
    "observe",
    "tease",
    "protect",
    "withdraw",
    "ask",
    "reassure",
    "react",
    "hesitate",
    "suppress",
    "indirect_presence",
    "guarded_reply",
    "refuse",
    "mirror",
    "meta_reply",
    "telemetry_comment",
    "vision_comment",
    "micro_observation",
    "micro_presence",
    "reengagement",
    "random_chatter",
    "inner_whim",
    "curious_question",
    "relational_checkin",
    "light_muse",
    "soft_boundary",
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
        self_state: SelfState | None = None,
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
            channel=channel,
            force_speak=force_speak,
            self_state=self_state,
        )
        style_anchor = self._style_anchor(
            channel=channel,
            snapshot=snapshot,
            broadcast=broadcast,
            user_text=user_text,
            force_speak=force_speak,
            speech_act=speech_act,
            concrete_signals=concrete_signals,
        )
        style_attitude = self._style_attitude(
            channel=channel,
            speech_act=speech_act,
            appraisal=appraisal,
            force_speak=force_speak,
        )
        style_limit = self._style_limit(channel=channel, speech_act=speech_act)
        return CognitiveActionPlan(
            should_speak=should_speak,
            speech_intent=speech_intent,
            speech_act=speech_act,
            reason_to_speak=reason_to_speak,
            reason=reason_to_speak,
            animation_hint=animation_hint,
            system_action=system_action,
            risk_flags=risk_flags,
            notes=self._append_self_state_notes(notes, self_state),
            style_anchor=style_anchor,
            style_attitude=style_attitude,
            style_limit=style_limit,
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
                return "guarded_reply"
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
        if speech_act in {"telemetry_comment", "vision_comment"}:
            return "screen_observation"
        if speech_act == "micro_observation":
            return "micro_observation"
        if speech_act == "micro_presence" and channel == "force_speak":
            return "micro_presence"
        if speech_act == "micro_presence":
            return "presence_maintenance"
        if speech_act == "reengagement":
            return "re_engagement"
        if speech_act == "tease":
            return "playful_aside"
        if intent in {"curious_question", "social_presence"} and speech_act in {
            "random_chatter",
            "inner_whim",
            "curious_question",
            "light_muse",
            "soft_boundary",
        }:
            return intent
        if speech_act in {
            "mirror",
            "withdraw",
            "ask",
            "reassure",
            "react",
            "hesitate",
            "suppress",
            "indirect_presence",
            "guarded_reply",
            "refuse",
            "meta_reply",
            "random_chatter",
            "micro_presence",
            "reengagement",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
        }:
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
        if any(str(note).startswith("inner_thought=") for note in notes):
            flags.append("inner_thought_surface")
        if speech_act in {
            "meta_reply",
            "random_chatter",
            "micro_presence",
            "reengagement",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
            "indirect_presence",
            "guarded_reply",
            "react",
            "hesitate",
        }:
            flags.append("no_screen_claim")
        if speech_act in {"observe", "tease", "telemetry_comment", "vision_comment", "micro_observation"} and not concrete_signals and not self._broadcast_has_signal(broadcast):
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
        if speech_act in {
            "meta_reply",
            "random_chatter",
            "micro_presence",
            "reengagement",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
            "indirect_presence",
            "guarded_reply",
            "react",
            "hesitate",
        }:
            return proposed_reason or (
                "InnerThought selected a social initiative without screen claims."
            )
        if concrete_signals and speech_act in {"observe", "telemetry_comment", "vision_comment", "micro_observation"}:
            return "Concrete signal is available before LLM: " + ", ".join(concrete_signals[:2])
        if risk_flags:
            return proposed_reason or "Planner selected action with risk flags: " + ", ".join(risk_flags)
        return proposed_reason or f"Planner selected {speech_act}."

    def _animation_hint(
        self,
        *,
        speech_act: str,
        ti_report,
        system_action: str,
        channel: str,
        force_speak: bool,
        self_state: SelfState | None,
    ) -> str:
        fallback = str(getattr(ti_report, "animation_hint", "") or "stand")
        if system_action == "get_now_playing":
            return "read"
        if system_action in {"open_url", "focus_window", "launch_app"}:
            return "stand_walk"
        state_label = str(getattr(self_state, "state_label", "") or "")
        embodiment = str(getattr(self_state, "embodiment_bias", "") or "")
        explicit = channel in {"chat", "force_speak"} or force_speak
        expressive_acts = {
            "tease",
            "random_chatter",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "reassure",
        }
        if state_label == "overloaded" and not explicit:
            if speech_act in expressive_acts:
                return "stand"
            if speech_act in {"observe", "telemetry_comment", "vision_comment", "protect", "soft_boundary"}:
                return "read" if fallback == "read" else "stand"
        if speech_act == "protect":
            return fallback or "read"
        if speech_act == "withdraw":
            return "stand"
        if state_label == "engaged" or embodiment == "expressive":
            if speech_act in {"relational_checkin", "reassure"}:
                return "affection"
            if speech_act in {"inner_whim", "random_chatter", "curious_question", "light_muse", "tease"}:
                return fallback if fallback != "stand" else "hop"
        return fallback

    def _append_self_state_notes(self, notes: tuple[str, ...], self_state: SelfState | None) -> tuple[str, ...]:
        merged = list(notes or ())
        if self_state is not None and getattr(self_state, "state_label", ""):
            merged.append(f"self_state={self_state.state_label}")
            merged.append(f"self_initiative_bias={float(self_state.initiative_bias):.2f}")
            if self_state.brevity_bias:
                merged.append(f"self_brevity={self_state.brevity_bias}")
            if self_state.embodiment_bias:
                merged.append(f"self_embodiment={self_state.embodiment_bias}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))

    def _style_anchor(
        self,
        *,
        channel: str,
        snapshot,
        broadcast,
        user_text: str,
        force_speak: bool,
        speech_act: str,
        concrete_signals: tuple[str, ...],
    ) -> str:
        if concrete_signals:
            return self._compact(str(concrete_signals[0]), fallback="current concrete signal")
        if channel == "force_speak" or force_speak:
            return "Ngai vua goi ERIS len tieng"
        if user_text and channel == "chat":
            return "Ngai vua noi: " + self._compact(user_text, fallback="tin nhan hien tai", limit=90)

        broadcast_text = self._broadcast_anchor_text(broadcast)
        if broadcast_text:
            return broadcast_text

        focus = self._compact(
            str(getattr(snapshot, "focus_summary", "") if snapshot is not None else ""),
            fallback="",
            limit=90,
        )
        if focus:
            return focus
        idle_seconds = self._float(getattr(snapshot, "idle_seconds", 0.0) if snapshot is not None else 0.0)
        if channel == "autonomous" and idle_seconds >= 90:
            return f"man hinh yen khoang {int(idle_seconds)}s"
        if speech_act == "no_speech":
            return "khong co tin hieu du dang de noi"
        return "nhip hien tai dang yen"

    def _style_attitude(
        self,
        *,
        channel: str,
        speech_act: str,
        appraisal,
        force_speak: bool,
    ) -> str:
        if speech_act in {"reassure", "relational_checkin"}:
            return "quan tam kin"
        if speech_act in {"guarded_reply", "indirect_presence", "hesitate", "suppress"}:
            return "giu lai, dap ung gian tiep"
        if speech_act in {"tease", "random_chatter", "light_muse"}:
            return "mia nhe"
        if speech_act in {"protect", "refuse", "soft_boundary", "withdraw", "system_action"}:
            return "lanh nhe"
        if channel == "force_speak" or force_speak:
            return "mia nhe"
        if self._appraisal_value(appraisal, "tenderness") >= 0.52:
            return "quan tam kin"
        return "lanh nhe"

    def _style_limit(self, *, channel: str, speech_act: str) -> str:
        if speech_act == "no_speech":
            return "im lang; khong chen them cau trang tri"
        if speech_act == "curious_question":
            return "dung mot cau hoi ngan; khong triet ly; khong giai thich dai"
        if channel == "chat":
            return "tra loi gon theo viec Ngai hoi; khong triet ly neu khong can"
        return "toi da hai cau ngan; khong triet ly; khong dung anchor gia"

    def _broadcast_anchor_text(self, broadcast) -> str:
        if broadcast is None:
            return ""
        for candidate in (
            str(getattr(broadcast, "content", "") or ""),
            str(getattr(broadcast, "label", "") or ""),
            str(getattr(broadcast, "reason", "") or ""),
        ):
            text = self._compact(candidate, fallback="", limit=100)
            if text:
                return text
        return ""

    def _compact(self, value: str, *, fallback: str, limit: int = 120) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return fallback
        return text[:limit]

    def _broadcast_has_signal(self, broadcast) -> bool:
        if broadcast is None:
            return False
        if str(getattr(broadcast, "label", "") or "") in {
            "low_salience",
            "cycle_channel",
            "user_force_speak",
            "substrate_disturbance",
            "resource_pressure",
            "active_window",
            "focus_context",
            "social_presence_event",
            "session_ritual",
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
