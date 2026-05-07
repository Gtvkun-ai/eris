import unicodedata

from .contracts import CognitiveAppraisal
from .internal_state import PersistentInternalState


class AppraisalEngine:
    """Builds ERIS' pre-verbal expressive/appraisal state from continuity state."""

    state_type = "expressive_appraisal_state"

    def evaluate(
        self,
        *,
        internal_state: PersistentInternalState,
        ni_report,
        ti_report,
        fe_plan,
        broadcast,
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
    ) -> CognitiveAppraisal:
        state = internal_state or PersistentInternalState()
        drift = self._clamp01(getattr(ni_report, "drift_score", 0.0) or 0.0)
        ni_confidence = self._clamp01(getattr(ni_report, "confidence", 0.0) or 0.0) or 0.55
        warmth = self._clamp01(getattr(fe_plan, "warmth_level", 0.0) or 0.0)
        sarcasm = self._clamp01(getattr(fe_plan, "sarcasm_level", 0.0) or 0.0)
        fe_intent = str(getattr(fe_plan, "intent_label", "") or "")
        session_arc = str(getattr(fe_plan, "session_arc", "") or "")
        mode = str(getattr(ti_report, "mode", "") or "")
        kind = str(getattr(state, "last_focus_kind", "") or "")
        broadcast_score = self._clamp01(getattr(broadcast, "score", 0.0) or 0.0)
        broadcast_label = str(getattr(broadcast, "label", "") or "")

        normalized_user_text = self._normalize_text(user_text)
        direct_user = bool(normalized_user_text) or channel == "chat" or force_speak
        attachment_cue = self._has_attachment_cue(normalized_user_text)
        social_scene = kind == "communication" or mode == "social_watch" or fe_intent == "social_watch"

        state_valence = self._clamp(getattr(state, "valence", 0.0), minimum=-1.0, maximum=1.0)
        state_arousal = self._clamp01(getattr(state, "arousal", 0.0))
        state_attachment = self._clamp01(getattr(state, "attachment", 0.0))
        state_social_energy = self._clamp01(getattr(state, "social_energy", 0.0))
        state_irritation = self._clamp01(getattr(state, "irritation", 0.0))
        state_protectiveness = self._clamp01(getattr(state, "protectiveness", 0.0))
        state_confidence = self._clamp01(getattr(state, "confidence", 0.0))
        state_fatigue = self._clamp01(getattr(state, "fatigue", 0.0))
        state_tenderness = self._clamp01(getattr(state, "tenderness", 0.0))
        state_silence_pressure = self._clamp01(getattr(state, "silence_pressure", 0.0))
        state_curiosity = self._clamp01(getattr(state, "curiosity", 0.0))

        threat = self._estimate_threat(
            state_protectiveness=state_protectiveness,
            state_irritation=state_irritation,
            drift=drift,
            mode=mode,
            broadcast_score=broadcast_score,
            ni_guard=bool(getattr(ni_report, "should_raise_guard", False)),
        )
        arousal = self._clamp01(
            max(
                state_arousal,
                broadcast_score,
                threat,
                drift * 0.74,
                0.32 if direct_user else 0.0,
                state_silence_pressure * 0.42,
            )
        )
        certainty = self._estimate_certainty(
            broadcast_score=broadcast_score,
            ni_confidence=ni_confidence,
            state_confidence=state_confidence,
            direct_user=direct_user,
        )
        agency = self._estimate_agency(
            mode=mode,
            kind=kind,
            direct_user=direct_user,
            broadcast_score=broadcast_score,
            threat=threat,
            social_energy=state_social_energy,
        )
        controllability = self._estimate_controllability(
            mode=mode,
            kind=kind,
            direct_user=direct_user,
            threat=threat,
            confidence=certainty,
        )
        intimacy = self._estimate_intimacy(
            direct_user=direct_user,
            social_scene=social_scene,
            attachment_cue=attachment_cue,
            mode=mode,
            fe_intent=fe_intent,
            session_arc=session_arc,
            warmth=warmth,
            attachment=state_attachment,
            social_energy=state_social_energy,
        )
        protectiveness = self._estimate_protectiveness(
            mode=mode,
            threat=threat,
            intimacy=intimacy,
            state_protectiveness=state_protectiveness,
        )
        jealousy_lite = self._estimate_jealousy_lite(
            mode=mode,
            social_scene=social_scene,
            intimacy=intimacy,
            threat=threat,
        )
        amusement = self._clamp01(
            sarcasm * 0.72
            + state_curiosity * 0.16
            + (0.18 if mode == "pattern_muse" else 0.0)
            + (0.07 if mode == "social_watch" else 0.0)
            - threat * 0.18
        )
        fatigue = self._estimate_fatigue(
            state_fatigue=state_fatigue,
            silence_pressure=state_silence_pressure,
        )
        tenderness = self._clamp01(
            state_tenderness * 0.72
            + warmth * 0.22
            + intimacy * 0.36
            + (0.10 if attachment_cue else 0.0)
            + (0.08 if social_scene else 0.0)
            - threat * 0.10
        )
        valence = self._clamp(
            state_valence * 0.64
            + warmth * 0.16
            + amusement * 0.14
            + tenderness * 0.14
            - threat * 0.36
            - fatigue * 0.18,
            minimum=-1.0,
            maximum=1.0,
        )

        stance = self._choose_stance(
            certainty=certainty,
            threat=threat,
            protectiveness=protectiveness,
            jealousy_lite=jealousy_lite,
            amusement=amusement,
            fatigue=fatigue,
            tenderness=tenderness,
            intimacy=intimacy,
            broadcast_score=broadcast_score,
        )
        evidence = (
            f"state_type={self.state_type}",
            f"ni_drift={drift:.2f}",
            f"ti_mode={mode or 'unknown'}",
            f"fe_intent={fe_intent or 'unknown'}",
            f"broadcast={broadcast_label or 'none'}:{broadcast_score:.2f}",
            f"internal_state_focus={kind or 'unknown'}",
            f"internal_attachment={state_attachment:.2f}",
        )
        summary = (
            f"{self.state_type}; stance={stance}; "
            f"valence={valence:.2f}; arousal={arousal:.2f}; certainty={certainty:.2f}; "
            f"threat={threat:.2f}; tenderness={tenderness:.2f}"
        )
        return CognitiveAppraisal(
            state_type=self.state_type,
            stance=stance,
            valence=valence,
            arousal=arousal,
            certainty=certainty,
            agency=agency,
            controllability=controllability,
            intimacy=intimacy,
            threat=threat,
            protectiveness=protectiveness,
            jealousy_lite=jealousy_lite,
            amusement=amusement,
            fatigue=fatigue,
            tenderness=tenderness,
            summary=summary,
            evidence=evidence,
        )

    def render_prompt_context(self, appraisal: CognitiveAppraisal) -> str:
        axes = (
            f"valence={appraisal.valence:.2f}, "
            f"arousal={appraisal.arousal:.2f}, "
            f"certainty={appraisal.certainty:.2f}, "
            f"agency={appraisal.agency:.2f}, "
            f"controllability={appraisal.controllability:.2f}, "
            f"intimacy={appraisal.intimacy:.2f}, "
            f"threat={appraisal.threat:.2f}, "
            f"protectiveness={appraisal.protectiveness:.2f}, "
            f"jealousy_lite={appraisal.jealousy_lite:.2f}, "
            f"amusement={appraisal.amusement:.2f}, "
            f"fatigue={appraisal.fatigue:.2f}, "
            f"tenderness={appraisal.tenderness:.2f}"
        )
        return "\n".join(
            (
                "expressive/appraisal state: pre-verbal attitude only, not an inner feeling claim.",
                f"appraisal_stance: {appraisal.stance}.",
                f"appraisal_axes: {axes}.",
                f"appraisal_bias: {self._stance_guidance(appraisal)}",
            )
        )

    def _estimate_threat(
        self,
        *,
        state_protectiveness: float,
        state_irritation: float,
        drift: float,
        mode: str,
        broadcast_score: float,
        ni_guard: bool,
    ) -> float:
        mode_threat = {
            "resource_guard": 0.86,
            "goal_drift_alert": 0.58,
            "goal_realign": 0.46,
            "discipline_nudge": 0.38,
            "focus_guard": 0.32,
            "system_warning": 0.60,
        }.get(mode, 0.0)
        guard_threat = 0.18 if ni_guard else 0.0
        return self._clamp01(
            max(mode_threat, state_protectiveness * 0.84, state_irritation * 0.60, drift * 0.66, broadcast_score * 0.44)
            + guard_threat
        )

    def _estimate_certainty(
        self,
        *,
        broadcast_score: float,
        ni_confidence: float,
        state_confidence: float,
        direct_user: bool,
    ) -> float:
        certainty = max(0.20, state_confidence * 0.70, broadcast_score * 0.44, ni_confidence * 0.66)
        if direct_user:
            certainty = max(certainty, 0.48)
        return self._clamp01(certainty)

    def _estimate_agency(
        self,
        *,
        mode: str,
        kind: str,
        direct_user: bool,
        broadcast_score: float,
        threat: float,
        social_energy: float,
    ) -> float:
        agency = 0.18 + social_energy * 0.30 + broadcast_score * 0.14
        if direct_user:
            agency += 0.42
        if mode in {"chat_code", "resource_guard", "focus_guard", "goal_realign"}:
            agency += 0.22
        elif mode in {"steady_observe", "pattern_muse", "social_watch"}:
            agency += 0.08
        if kind in {"coding", "system", "documentation"}:
            agency += 0.10
        if threat >= 0.70:
            agency += 0.08
        return self._clamp01(agency)

    def _estimate_controllability(
        self,
        *,
        mode: str,
        kind: str,
        direct_user: bool,
        threat: float,
        confidence: float,
    ) -> float:
        controllability = 0.34
        if direct_user:
            controllability += 0.20
        if kind in {"coding", "documentation", "system"}:
            controllability += 0.14
        if mode in {"chat_code", "resource_guard", "focus_guard", "goal_realign"}:
            controllability += 0.18
        if kind == "communication":
            controllability -= 0.08
        if confidence <= 0.32:
            controllability -= 0.08
        if threat >= 0.78 and mode not in {"resource_guard", "chat_code"}:
            controllability -= 0.06
        return self._clamp01(controllability)

    def _estimate_intimacy(
        self,
        *,
        direct_user: bool,
        social_scene: bool,
        attachment_cue: bool,
        mode: str,
        fe_intent: str,
        session_arc: str,
        warmth: float,
        attachment: float,
        social_energy: float,
    ) -> float:
        intimacy = 0.08 + attachment * 0.42 + social_energy * 0.18 + warmth * 0.10
        if direct_user:
            intimacy += 0.18
        if social_scene:
            intimacy += 0.12
        if attachment_cue:
            intimacy += 0.34
        if mode == "chat_emotional" or fe_intent == "attachment_dialogue":
            intimacy += 0.34
        if session_arc == "guarded_attachment":
            intimacy += 0.18
        return self._clamp01(intimacy)

    def _estimate_protectiveness(
        self,
        *,
        mode: str,
        threat: float,
        intimacy: float,
        state_protectiveness: float,
    ) -> float:
        protectiveness = state_protectiveness * 0.64 + threat * 0.36 + intimacy * 0.14
        if mode == "resource_guard":
            protectiveness = max(protectiveness, 0.82)
        elif mode in {"goal_drift_alert", "goal_realign", "focus_guard"}:
            protectiveness = max(protectiveness, 0.46)
        return self._clamp01(protectiveness)

    def _estimate_jealousy_lite(
        self,
        *,
        mode: str,
        social_scene: bool,
        intimacy: float,
        threat: float,
    ) -> float:
        if not social_scene:
            return 0.0
        jealousy_lite = 0.18 + intimacy * 0.18 + threat * 0.08
        if mode == "social_watch":
            jealousy_lite += 0.12
        return self._clamp(jealousy_lite, minimum=0.0, maximum=0.48)

    def _estimate_fatigue(
        self,
        *,
        state_fatigue: float,
        silence_pressure: float,
    ) -> float:
        return self._clamp01(state_fatigue * 0.82 + silence_pressure * 0.12)

    def _choose_stance(
        self,
        *,
        certainty: float,
        threat: float,
        protectiveness: float,
        jealousy_lite: float,
        amusement: float,
        fatigue: float,
        tenderness: float,
        intimacy: float,
        broadcast_score: float,
    ) -> str:
        if threat >= 0.66 or protectiveness >= 0.72:
            return "protective"
        if jealousy_lite >= 0.32:
            return "watchful"
        if tenderness >= 0.52 or intimacy >= 0.58:
            return "tender_under_cold"
        if fatigue >= 0.42:
            return "tired"
        if amusement >= 0.34:
            return "dry_playful"
        if certainty <= 0.30 and broadcast_score <= 0.32:
            return "soft_uncertain"
        return "grounded"

    def _stance_guidance(self, appraisal: CognitiveAppraisal) -> str:
        stance = appraisal.stance
        if stance == "protective":
            return "speak briefly, concrete first, with guarded care; avoid theatrical alarm."
        if stance == "watchful":
            return "let the line carry mild possessive watchfulness, kept light and non-accusatory."
        if stance == "tender_under_cold":
            return "make the surface restrained while letting warmth show through the wording."
        if stance == "tired":
            return "slow the rhythm and keep the sentence spare."
        if stance == "dry_playful":
            return "allow a small dry aside, but keep it grounded in the scene."
        if stance == "soft_uncertain":
            return "soften claims and avoid inventing motives or details."
        return "stay grounded, reserved, and responsive to the strongest cue."

    def _has_attachment_cue(self, normalized_text: str) -> bool:
        if not normalized_text:
            return False
        cues = (
            "met",
            "buon",
            "co don",
            "nho",
            "yeu",
            "tam trang",
            "lo lang",
            "so",
            "dau",
            "thuong",
            "gan toi",
            "o ben",
            "om",
        )
        return any(cue in normalized_text for cue in cues)

    def _normalize_text(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        normalized = unicodedata.normalize("NFD", lowered)
        normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        normalized = normalized.replace("đ", "d")
        return " ".join(normalized.split())

    def _clamp01(self, value) -> float:
        return self._clamp(value, minimum=0.0, maximum=1.0)

    def _clamp(self, value, *, minimum: float, maximum: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return minimum
        if numeric != numeric:
            return minimum
        return max(minimum, min(maximum, numeric))
