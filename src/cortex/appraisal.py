import unicodedata

from .contracts import CognitiveAppraisal


class AppraisalEngine:
    """Builds ERIS' pre-verbal expressive/appraisal state for a scene."""

    state_type = "expressive_appraisal_state"

    def evaluate(
        self,
        *,
        snapshot, # ảnh chụp trạng thái hiện tại của hệ thống/người dùng
        ni_report,
        ti_report,
        fe_plan, #kế hoạch biểu đạt/FE
        broadcast, #: tín hiệu phát sóng/cảnh báo
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
    ) -> CognitiveAppraisal:
        drift = self._clamp01(getattr(ni_report, "drift_score", 0.0) or 0.0)
        ni_confidence = self._clamp01(getattr(ni_report, "confidence", 0.0) or 0.0)
        if ni_confidence <= 0.0:
            ni_confidence = 0.55

        warmth = self._clamp01(getattr(fe_plan, "warmth_level", 0.0) or 0.0)
        sarcasm = self._clamp01(getattr(fe_plan, "sarcasm_level", 0.0) or 0.0)
        fe_intent = str(getattr(fe_plan, "intent_label", "") or "")
        session_arc = str(getattr(fe_plan, "session_arc", "") or "")

        mode = str(getattr(ti_report, "mode", "") or "")
        kind = str(getattr(snapshot, "active_window_kind", "") or "")
        idle_seconds = self._nonnegative_float(getattr(snapshot, "idle_seconds", 0.0) or 0.0) #thời gian nhàn rỗi của người dùng
        resource_pressure = 0.0

        user_signals = getattr(snapshot, "user_signals", None) #tín hiệu về trạng thái tập trung và chuyển đổi cửa sổ của người dùng
        focus_pattern = str(getattr(user_signals, "focus_pattern", "") or "")
        switching = str(getattr(user_signals, "window_switching", "") or "")
        claim_style = str(getattr(snapshot, "claim_style", "") or "")
        broadcast_score = self._clamp01(getattr(broadcast, "score", 0.0) or 0.0)
        broadcast_label = str(getattr(broadcast, "label", "") or "")

        normalized_user_text = self._normalize_text(user_text)
        direct_user = bool(normalized_user_text) or channel == "chat" or force_speak
        attachment_cue = self._has_attachment_cue(normalized_user_text)
        social_scene = kind == "communication" or mode == "social_watch" or fe_intent == "social_watch"
        # CPU/RAM are telemetry only; they must not steer mode, speech intent, or appraisal.
        threat = self._estimate_threat(
            drift=drift,
            mode=mode,
            kind=kind,
            resource_pressure=resource_pressure,
            broadcast_score=broadcast_score,
            ni_guard=bool(getattr(ni_report, "should_raise_guard", False)),
        )
        # Tính arousal từ broadcast, threat, drift, direct_user, focus_pattern, và switching.
        arousal = self._clamp01(
            max(
                broadcast_score,
                threat,
                drift * 0.78, # drift là tín hiệu về sự lệch khỏi mục tiêu hoặc trạng thái
                0.34 if direct_user else 0.0,
                0.30 if focus_pattern in {"fragmented", "stuck", "absent"} else 0.0,
                0.28 if switching == "high" else 0.0,
            )
        )
        certainty = self._estimate_certainty(
            broadcast_score=broadcast_score,
            ni_confidence=ni_confidence,
            claim_style=claim_style,
            direct_user=direct_user,
        )
        agency = self._estimate_agency(
            mode=mode,
            kind=kind,
            direct_user=direct_user,
            broadcast_score=broadcast_score,
            threat=threat,
        )
        controllability = self._estimate_controllability(
            mode=mode,
            kind=kind,
            direct_user=direct_user,
            resource_pressure=resource_pressure,
            threat=threat,
            idle_seconds=idle_seconds,
        )
        intimacy = self._estimate_intimacy(
            direct_user=direct_user,
            social_scene=social_scene,
            attachment_cue=attachment_cue,
            mode=mode,
            fe_intent=fe_intent,
            session_arc=session_arc,
            warmth=warmth,
        )
        protectiveness = self._estimate_protectiveness(
            mode=mode,
            kind=kind,
            threat=threat,
            resource_pressure=resource_pressure,
            intimacy=intimacy,
        )
        jealousy_lite = self._estimate_jealousy_lite(
            mode=mode,
            social_scene=social_scene,
            intimacy=intimacy,
            threat=threat,
        )
        amusement = self._clamp01(
            sarcasm * 0.82
            + (0.18 if mode == "pattern_muse" else 0.0)
            + (0.07 if mode == "social_watch" else 0.0)
            - threat * 0.18
        )
        fatigue = self._estimate_fatigue(
            idle_seconds=idle_seconds,
            resource_pressure=resource_pressure,
            focus_pattern=focus_pattern,
        )
        tenderness = self._clamp01(
            warmth
            + intimacy * 0.36
            + (0.10 if attachment_cue else 0.0)
            + (0.08 if social_scene else 0.0)
            - threat * 0.10
        )
        valence = self._clamp(
            0.12 + warmth * 0.32 + amusement * 0.16 + tenderness * 0.18 - threat * 0.44 - fatigue * 0.22,
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
            f"resource_pressure={resource_pressure:.2f}",
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

    # Hàm render_prompt_context chuyển appraisal thành text cho prompt downstream
    def render_prompt_context(self, appraisal: CognitiveAppraisal) -> str:
        #giải thích đây là trạng thái tiền-ngôn-ngữ, không phải “cảm xúc nội tâm”
        #stance hiện tại
        #các axes chính
        #appraisal_bias, tức hướng dẫn cách nói theo stance
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

    #Hàm này tính mức đe dọa tổng hợp.
    def _estimate_threat(
        self,
        *,
        drift: float,
        mode: str, #mode như resource_guard, goal_drift_alert, system_warning
        kind: str, # kind là system
        resource_pressure: float,
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
        kind_threat = 0.22 if kind == "system" else 0.0
        guard_threat = 0.18 if ni_guard else 0.0
        return self._clamp01(
            max(mode_threat, kind_threat, drift * 0.66, broadcast_score * 0.44)
            + guard_threat
        )

    def _estimate_certainty(
        self,
        *,
        broadcast_score: float,
        ni_confidence: float,
        claim_style: str,
        direct_user: bool,
    ) -> float:
        certainty = max(0.20, broadcast_score * 0.84, ni_confidence * 0.70)
        if direct_user: #nếu direct_user, certainty tối thiểu được đẩy lên 0.48
            certainty = max(certainty, 0.48)
        lowered = claim_style.strip().lower()
        if any(marker in lowered for marker in ("no_evidence", "uncertainty", "soft_claim")):
            certainty -= 0.12 #nếu claim_style chứa no_evidence, uncertainty, soft_claim thì certainty bị trừ 0.12
        return self._clamp01(certainty) # trực tiếp với người dùng thì phải dám nói rõ hơn, nhưng nếu claim style báo mơ hồ thì phải hạ độ chắc chắn.

    #Agency là cảm giác “mình đang có quyền điều khiển tình huống”.
    def _estimate_agency(
        self,
        *,
        mode: str,
        kind: str,
        direct_user: bool,
        broadcast_score: float,
        threat: float,
    ) -> float:
        agency = 0.22 + broadcast_score * 0.20
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

    # Controllability là “mình kiểm soát được việc này không”.
    def _estimate_controllability(
        self,
        *,
        mode: str,
        kind: str,
        direct_user: bool,
        resource_pressure: float,
        threat: float,
        idle_seconds: float,
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
        if idle_seconds >= 600:
            controllability -= 0.08
        if threat >= 0.78 and mode not in {"resource_guard", "chat_code"}:
            controllability -= 0.06
        return self._clamp01(controllability)

    # Đây là phần đẩy hệ thống sang giọng gần gũi, đặc biệt khi text người dùng có sắc thái tình cảm hoặc gắn bó.
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
    ) -> float:
        intimacy = 0.10 + warmth * 0.26
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

    #Protectiveness gần như là threat + intimacy được trộn lại.
    # 0.16 + threat * 0.58 + intimacy * 0.18
    def _estimate_protectiveness(
        self,
        *,
        mode: str,
        kind: str,
        threat: float,
        resource_pressure: float,
        intimacy: float,
    ) -> float:
        protectiveness = 0.16 + threat * 0.58 + intimacy * 0.18
        if mode == "resource_guard":
            protectiveness = max(protectiveness, 0.82)
        elif mode in {"goal_drift_alert", "goal_realign", "focus_guard"}:
            protectiveness = max(protectiveness, 0.46)
        elif kind in {"system", "coding"}:
            protectiveness = max(protectiveness, 0.38)
        return self._clamp01(protectiveness) #càng thấy nguy cơ hoặc càng gắn bó thì càng muốn “giữ”

    #Đây là một sắc thái xã hội nhẹ, không phải ghen mạnh.
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

    #Đây là chỉ báo cho trạng thái “chậm lại, cạn pin, ít hoạt động”.
    def _estimate_fatigue(
        self,
        *,
        idle_seconds: float,
        resource_pressure: float,
        focus_pattern: str,
    ) -> float:
        fatigue = 0.0
        if idle_seconds >= 600:
            fatigue += 0.32
        elif idle_seconds >= 180:
            fatigue += 0.16
        if focus_pattern in {"stuck", "absent", "passive_consumption"}:
            fatigue += 0.12
        return self._clamp01(fatigue)

    # Sau khi có các trục, hệ thống chọn stance biểu cảm.
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
    #nếu threat cao, nó sẽ chặn mọi thứ khác và chọn protective
    #nếu không nguy hiểm nhưng có độ gần gũi, nó sẽ chuyển sang tender_under_cold
    #nếu ít dữ kiện, nó sẽ thận trọng với soft_uncertain


    def _stance_guidance(self, appraisal: CognitiveAppraisal) -> str:
        #Đây là phần map stance sang chỉ dẫn hành vi:
        stance = appraisal.stance
        if stance == "protective":#protective: nói ngắn, cụ thể, cẩn trọng
            return "speak briefly, concrete first, with guarded care; avoid theatrical alarm."
        if stance == "watchful":#watchful: hơi sở hữu nhẹ, nhưng không cáo buộc
            return "let the line carry mild possessive watchfulness, kept light and non-accusatory."
        if stance == "tender_under_cold": #tender_under_cold: bề mặt tiết chế, bên dưới có ấm
            return "make the surface restrained while letting warmth show through the wording."
        if stance == "tired": #tired: chậm lại, ít hoạt động, cạn pin
            return "slow the rhythm and keep the sentence spare."
        if stance == "dry_playful": #dry_playful: có một chút khô khan dí dỏm
            return "allow a small dry aside, but keep it grounded in the scene."
        if stance == "soft_uncertain": #soft_uncertain: mềm hoá, không bịa
            return "soften claims and avoid inventing motives or details."
        #grounded: giữ trung tính, đáp lại cue mạnh nhất
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

    def _nonnegative_float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, numeric)

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
