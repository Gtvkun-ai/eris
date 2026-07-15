import unicodedata
from dataclasses import dataclass

from .affect_blend import (
    AffectBlendConfig,
    DEFAULT_BLEND_CONFIG,
    StanceBlend,
    blend_stance,
    guidance_blend,
    project_event_affect,
)
from .contracts import CognitiveAppraisal
from .internal_state import PersistentInternalState


@dataclass(slots=True)
class _EventAffect:
    """Tín hiệu cảm xúc rút từ sự-kiện nổi bật (dominant salient evidence).

    Đây là mảnh còn thiếu để appraisal = f(sự-kiện × stake × kỳ vọng): trước đây
    appraisal chỉ là hàm của internal_state, nên một cảnh buồn không bao giờ chạm
    tới valence. Các trục dưới đã được nhân sẵn với stake (mức Eris quan tâm) và
    surprise (lệch khỏi kỳ vọng) trước khi trả về.
    """

    valence: float = 0.0      # [-1,1] đã gate theo stake+surprise; âm = cảnh buồn
    tenderness: float = 0.0   # [0,1] lực kéo dịu dàng/để ý khi bạn có vẻ không ổn
    arousal: float = 0.0      # [0,1] mức kích hoạt do sự-kiện
    label: str = ""

    @property
    def active(self) -> bool:
        return abs(self.valence) > 1e-6 or self.tenderness > 1e-6 or self.arousal > 1e-6


# Lexicon ở dạng KHÔNG dấu vì _normalize_text() đã bỏ dấu tiếng Việt.
_EVENT_NEG_TOKENS = (
    "buon", "met", "chan", "co don", "khoc", "stress", "tuc gian", "tuc", "dau",
    "that vong", "tuyet vong", "lo lang", "so hai", "kiet suc", "u uat", "nang ne",
    "sad", "cry", "lonely", "tired", "exhausted", "depress", "grief", "lost", "fail",
    "hurt", "anxious", "down",
)
_EVENT_POS_TOKENS = (
    "vui", "cuoi", "hao hung", "thang", "phan khich", "hanh phuc", "yeu", "thuong",
    "chuc mung", "tuyet voi", "nhe nhom", "thoai mai", "happy", "joy", "win", "love",
    "excited", "glad", "celebrate", "relief",
)


class AppraisalEngine:
    """Builds ERIS' pre-verbal expressive/appraisal state from continuity state."""

    state_type = "expressive_appraisal_state"

    def __init__(
        self,
        *,
        blend_config: AffectBlendConfig | None = None,
        event_encoder=None,
    ) -> None:
        # blend_config: bật/tắt + knob (temperature/inertia) cho stance dạng blend.
        # event_encoder: callable str->vector cho đọc event-affect bằng prototype.
        #   None -> luôn dùng fallback lexicon xác định (an toàn cho test/môi trường thiếu model).
        self.blend_config = blend_config or DEFAULT_BLEND_CONFIG
        self._event_encoder = event_encoder

    def evaluate(
        self,
        *,
        internal_state: PersistentInternalState, ##trạng thái lâu dài
        ni_report, #intuition / drift / guard
        ti_report, #reasoning mode
        fe_plan, #social strategy
        broadcast, #urgency/global salience
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
        memory_resonance=None, #ký ức vang vọng
        personality_lens=None, #cách interpret user
        standing_stakes=None, #stake thường trực: dùng để gate sự-kiện theo mức quan tâm
        prev_stance_blend: dict | None = None, #stance blend turn trước -> EMA inertia
        blend_config: AffectBlendConfig | None = None, #override config cho lần gọi này
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
        resonance_score = self._clamp01(getattr(memory_resonance, "score", 0.0) if memory_resonance is not None else 0.0)
        resonance_appraisal = self._clamp01(
            getattr(memory_resonance, "appraisal_bias", 0.0) if memory_resonance is not None else 0.0
        )
        resonance_silence = self._clamp01(
            getattr(memory_resonance, "silence_bias", 0.0) if memory_resonance is not None else 0.0
        )
        resonance_layer = str(getattr(memory_resonance, "dominant_layer", "") if memory_resonance is not None else "")
        lens_interpretation = str(getattr(personality_lens, "interpretation", "") or "")
        lens_stance = str(getattr(personality_lens, "stance", "") or "")
        lens_distance = str(getattr(personality_lens, "social_distance", "") or "")

        normalized_user_text = self._normalize_text(user_text)
        direct_user = bool(normalized_user_text) or channel == "chat" or force_speak
        attachment_cue = self._has_attachment_cue(normalized_user_text)
        social_scene = kind == "communication" or mode == "social_watch" or fe_intent == "social_watch"

        state_valence = self._clamp(getattr(state, "valence", 0.0), minimum=-1.0, maximum=1.0) # valence là “hedonic tone”., thường được định nghĩa từ -1 (rất tiêu cực) đến +1 (rất tích cực). Trong trường hợp này, giá trị valence được lấy từ trạng thái nội bộ của ERIS và được giới hạn trong khoảng từ -1.0 đến 1.0 để đảm bảo rằng nó nằm trong phạm vi hợp lệ cho trục cảm xúc này.
        state_arousal = self._clamp01(getattr(state, "arousal", 0.0)) # arousal là mức activation, thường được định nghĩa từ 0 (rất bình tĩnh) đến 1 (rất kích thích). 
        state_attachment = self._clamp01(getattr(state, "attachment", 0.0)) # attachment có thể đề cập đến mức độ gắn bó hoặc kết nối cảm xúc của ERIS với người dùng hoặc tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_social_energy = self._clamp01(getattr(state, "social_energy", 0.0)) # social_energy có thể đề cập đến mức độ năng lượng xã hội hoặc sự sẵn sàng tương tác của ERIS trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_irritation = self._clamp01(getattr(state, "irritation", 0.0)) # irritation có thể đề cập đến mức độ khó chịu hoặc bực bội của ERIS trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_protectiveness = self._clamp01(getattr(state, "protectiveness", 0.0)) # protectiveness có thể đề cập đến mức độ bảo vệ hoặc phòng thủ của ERIS trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_confidence = self._clamp01(getattr(state, "confidence", 0.0)) # confidence có thể đề cập đến mức độ tự tin của ERIS trong việc hiểu hoặc xử lý tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_fatigue = self._clamp01(getattr(state, "fatigue", 0.0)) # fatigue có thể đề cập đến mức độ mệt mỏi hoặc kiệt sức của ERIS trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_tenderness = self._clamp01(getattr(state, "tenderness", 0.0)) # tenderness có thể đề cập đến mức độ dịu dàng hoặc quan tâm của ERIS trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_silence_pressure = self._clamp01(getattr(state, "silence_pressure", 0.0)) # silence_pressure có thể đề cập đến mức độ áp lực hoặc căng thẳng mà ERIS cảm thấy khi phải giữ im lặng hoặc không phản hồi trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.
        state_curiosity = self._clamp01(getattr(state, "curiosity", 0.0)) # curiosity có thể đề cập đến mức độ tò mò hoặc mong muốn khám phá của ERIS trong tình huống hiện tại. Giá trị này cũng được giới hạn trong khoảng từ 0.0 đến 1.0.

        #Đây là defensive nervous system.
        threat = self._estimate_threat(
            state_protectiveness=state_protectiveness,
            state_irritation=state_irritation,
            drift=drift,
            mode=mode,
            broadcast_score=broadcast_score,
            ni_guard=bool(getattr(ni_report, "should_raise_guard", False)),
        )
        # Sự-kiện nổi bật (cảnh bạn đang xem/làm) được đọc thành tín hiệu cảm xúc,
        # đã gate theo stake (Eris quan tâm tâm trạng bạn tới đâu) và surprise
        # (lệch khỏi kỳ vọng). Đây là phần làm appraisal phản ứng với THẾ GIỚI,
        # không chỉ với nội trạng của chính mình.
        event = self._event_affect(
            broadcast=broadcast,
            stakes=standing_stakes,
            state_valence=state_valence,
        )
        arousal = self._clamp01(
            max(
                state_arousal,
                broadcast_score,
                resonance_score * 0.36,
                threat,
                drift * 0.74,
                0.32 if direct_user else 0.0,
                state_silence_pressure * 0.42,
                event.arousal,
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
        if resonance_layer == "relationship":
            intimacy = self._clamp01(intimacy + resonance_score * 0.16)
        elif resonance_layer == "procedural":
            threat = self._clamp01(threat + resonance_appraisal * 0.16)
            protectiveness = self._clamp01(protectiveness + resonance_appraisal * 0.14)
        elif resonance_layer == "episodic":
            arousal = self._clamp01(max(arousal, resonance_score * 0.42))
        elif resonance_layer == "emotional_residue":
            arousal = self._clamp01(max(arousal, resonance_score * 0.36))
            certainty = self._clamp01(certainty - resonance_score * 0.04)
        if resonance_silence > 0.0:
            certainty = self._clamp01(certainty - resonance_silence * 0.10)
            fatigue = self._clamp01(fatigue + resonance_silence * 0.07)
        if lens_interpretation in {"avoidance", "unfinished_intention", "hesitation", "cognitive_stall", "scattered_attention", "escape_from_friction"}:
            certainty = self._clamp01(certainty - 0.04)
            protectiveness = self._clamp01(protectiveness + 0.03)
        if lens_interpretation == "requested_presence":
            intimacy = self._clamp01(intimacy + 0.07)
        if lens_stance == "guarded_protective":
            threat = self._clamp01(threat + 0.05)
            protectiveness = self._clamp01(protectiveness + 0.08)
        elif lens_stance == "guarded_tender":
            intimacy = self._clamp01(intimacy + 0.06)
        elif lens_stance == "withdrawn_sparse":
            fatigue = self._clamp01(fatigue + 0.06)
        if lens_distance == "near_guarded":
            intimacy = self._clamp01(intimacy + 0.04)
        elif lens_distance == "far_observing":
            intimacy = self._clamp01(intimacy - 0.03)
        tenderness = self._clamp01(
            state_tenderness * 0.72
            + warmth * 0.22
            + intimacy * 0.36
            + (resonance_score * 0.08 if resonance_layer == "relationship" else 0.0)
            + (resonance_score * 0.06 if resonance_layer == "emotional_residue" else 0.0)
            + (0.04 if attachment_cue else 0.0)
            + (0.08 if social_scene else 0.0)
            + event.tenderness * 0.30
            - threat * 0.10
        )
        if resonance_layer == "emotional_residue":
            tenderness = self._clamp01(tenderness + resonance_appraisal * 0.06)
        if lens_interpretation in {"avoidance", "unfinished_intention", "hesitation", "cognitive_stall", "scattered_attention", "escape_from_friction"}:
            tenderness = self._clamp01(tenderness + 0.04)
        if lens_interpretation == "requested_presence":
            tenderness = self._clamp01(tenderness + 0.05)
        if lens_stance == "guarded_tender":
            tenderness = self._clamp01(tenderness + 0.03)
        valence = self._clamp(
            state_valence * 0.64
            + warmth * 0.16
            + amusement * 0.14
            + tenderness * 0.14
            + event.valence * 0.34
            - threat * 0.36
            - fatigue * 0.18,
            minimum=-1.0,
            maximum=1.0,
        )
        #Đây là distilled expressive mode.
        cfg = blend_config or self.blend_config
        stance_blend_map: dict[str, float] = {}
        if cfg.enabled:
            # Stance dạng phân bố mềm trên các điểm hút trong không gian affect,
            # có quán tính (EMA) với stance blend của turn trước.
            affect_vector = {
                "valence": valence,
                "arousal": arousal,
                "certainty": certainty,
                "agency": agency,
                "controllability": controllability,
                "intimacy": intimacy,
                "threat": threat,
                "protectiveness": protectiveness,
                "jealousy_lite": jealousy_lite,
                "amusement": amusement,
                "fatigue": fatigue,
                "tenderness": tenderness,
            }
            blend = blend_stance(affect_vector, prev=prev_stance_blend, config=cfg)
            stance = blend.top()
            stance_blend_map = blend.to_dict()
        else:
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
            f"memory_resonance={resonance_layer or 'none'}:{resonance_score:.2f}",
            f"personality_lens={lens_interpretation or 'none'}:{lens_stance or 'none'}",
            f"internal_state_focus={kind or 'unknown'}",
            f"internal_attachment={state_attachment:.2f}",
        )
        if event.active:
            evidence = (*evidence, f"event_affect={event.label or 'scene'}:{event.valence:+.2f}")
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
            stance_blend=stance_blend_map,
        )

    #là cầu nối sang LLM
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
        # Nước 1 — van bước-cuối: khi bật, thay disclaimer "không phải cảm xúc
        # thật" bằng directive cho phép stance lộ ra. Mặc định TẮT → giữ nguyên cũ.
        try:
            from .emotional_consequence import (  # type: ignore
                FELT_STATE_DIRECTIVE,
                emotional_consequence_enabled,
            )
        except Exception:  # pragma: no cover
            from cortex.emotional_consequence import (  # type: ignore
                FELT_STATE_DIRECTIVE,
                emotional_consequence_enabled,
            )
        header = (
            FELT_STATE_DIRECTIVE
            if emotional_consequence_enabled()
            else "expressive/appraisal state: pre-verbal attitude only, not an inner feeling claim."
        )
        return "\n".join(
            (
                header,
                f"appraisal_stance: {appraisal.stance}.",
                f"appraisal_axes: {axes}.",
                f"appraisal_bias: {self._stance_guidance(appraisal)}",
            )
        )

    def _event_affect(self, *, broadcast, stakes, state_valence: float) -> _EventAffect:
        """Đọc cảm xúc của sự-kiện nổi bật, gate theo stake và surprise.

        - sự-kiện: lấy từ broadcast.content + claim của các item nổi bật.
        - stake: ``care_user_mood`` quyết định Eris để tâm cảnh này tới đâu.
        - kỳ vọng: surprise = độ lệch giữa valence cảnh và valence cô đang mang;
          một cảnh buồn khi đang yên ổn thì chạm mạnh hơn (prediction error).

        Đường chính: chiếu văn bản sự-kiện lên các affect-direction prototype (khi
        có encoder). Cảnh hỗn hợp cho ra vector pha trộn thay vì triệt tiêu về 0.
        Không có encoder -> fallback lexicon xác định, bảo toàn mọi hành vi/test cũ.
        Không có stake hoặc không có nội dung -> trả tín hiệu rỗng.
        """

        if stakes is None or broadcast is None:
            return _EventAffect()
        care = self._clamp01(getattr(stakes, "care_user_mood", 0.0))
        if care <= 0.0:
            return _EventAffect()
        parts = [str(getattr(broadcast, "content", "") or "")]
        for item in tuple(getattr(broadcast, "items", ()) or ())[:3]:
            parts.append(str(getattr(item, "claim", "") or ""))
        raw_text = " ".join(p for p in parts if p).strip()
        if not raw_text:
            return _EventAffect()

        # Đường chính: prototype projection (encoder đa ngữ xử lý cả text tiếng Việt).
        if self._event_encoder is not None:
            projected = project_event_affect(raw_text, encode=self._event_encoder)
            if projected is not None:
                return self._event_affect_from_projection(
                    projected, state_valence=state_valence, care=care
                )

        # Fallback xác định: lexicon cũ trên text đã bỏ dấu.
        return self._event_affect_lexicon(raw_text, state_valence=state_valence, care=care)

    def _event_affect_from_projection(
        self, projected: dict, *, state_valence: float, care: float
    ) -> _EventAffect:
        """Dựng _EventAffect từ vector affect đã chiếu, giữ nguyên Stake_Gate."""
        raw = self._clamp(projected.get("valence", 0.0), minimum=-1.0, maximum=1.0)
        proto_tender = self._clamp01(projected.get("tenderness", 0.0))
        proto_arousal = self._clamp01(projected.get("arousal", 0.0))
        surprise = min(1.0, abs(raw - state_valence) / 2.0)
        gate = care * (0.55 + 0.45 * surprise)
        valence = max(-1.0, min(1.0, raw * gate))
        tenderness = self._clamp01(proto_tender * gate)
        arousal = self._clamp01(proto_arousal * gate * 0.6)
        # Cảnh hỗn hợp: dịu dàng vẫn hiện dù valence không rõ một chiều.
        mixed = proto_tender > 0.2 and abs(raw) < 0.5
        label = "scene_mixed" if mixed else ("scene_low" if raw < 0 else "scene_bright")
        return _EventAffect(valence=valence, tenderness=tenderness, arousal=arousal, label=label)

    def _event_affect_lexicon(
        self, raw_text: str, *, state_valence: float, care: float
    ) -> _EventAffect:
        """Đường dự phòng: đếm token lexicon không dấu (hành vi gốc, xác định)."""
        text = self._normalize_text(raw_text)
        if not text:
            return _EventAffect()

        neg = sum(1 for token in _EVENT_NEG_TOKENS if token in text)
        pos = sum(1 for token in _EVENT_POS_TOKENS if token in text)
        if neg == 0 and pos == 0:
            return _EventAffect()

        # raw valence của cảnh trên [-1,1].
        raw = (pos - neg) / float(max(1, pos + neg))
        raw = max(-1.0, min(1.0, raw))
        # surprise: cảnh lệch khỏi nội trạng hiện tại thì đáng chú ý hơn.
        surprise = min(1.0, abs(raw - state_valence) / 2.0)
        gate = care * (0.55 + 0.45 * surprise)

        valence = max(-1.0, min(1.0, raw * gate))
        # cảnh buồn (raw âm) kéo dịu dàng/để ý lên; cảnh vui không tự nó hạ tenderness.
        tenderness = self._clamp01(max(0.0, -raw) * gate)
        arousal = self._clamp01(abs(raw) * gate * 0.6)
        label = "scene_low" if raw < 0 else "scene_bright"
        return _EventAffect(valence=valence, tenderness=tenderness, arousal=arousal, label=label)

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
            intimacy += 0.16
        if mode == "chat_emotional" or fe_intent == "attachment_dialogue":
            intimacy += 0.16
        if session_arc == "guarded_attachment":
            intimacy += 0.08
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
        if tenderness >= 0.68 or intimacy >= 0.72:
            return "tender_under_cold"
        if fatigue >= 0.42:
            return "tired"
        if amusement >= 0.34:
            return "dry_playful"
        if certainty <= 0.30 and broadcast_score <= 0.32:
            return "soft_uncertain"
        return "grounded"

    def _stance_guidance(self, appraisal: CognitiveAppraisal) -> str:
        # Khi có stance blend (đường mới): hướng dẫn phản ánh top-k stance pha trộn.
        if appraisal.stance_blend:
            return guidance_blend(
                StanceBlend(weights=dict(appraisal.stance_blend)),
                config=self.blend_config,
            )
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
