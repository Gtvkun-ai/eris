import re
import unicodedata

from .contracts import PersonalityLensResult
from .internal_state import PersistentInternalState


class PersonalityLens:
    """Guarded, grounded personality pressure layer between meaning and expression."""

    PROFILE = "INFJ_5w4_594"
    # Tầng này giữ lại phần đọc nội bộ, nhưng không được biến sự kiềm chế thành sương mù thơ.
    SUPPRESSION_RATIO = 0.66
    ANCHOR_TOKEN_RE = re.compile(
        r"\b(?:memory_id|event_id|vision_fact_id)\s*[:=]\s*[a-z0-9][a-z0-9_.:/-]{2,}",
        re.I,
    )

    BIAS_TERMS: dict[str, tuple[str, ...]] = {
        "hesitation": (
            "hesitation",
            "hesitant",
            "pause",
            "paused",
            "pausing",
            "hover",
            "hovering",
            "stalled",
            "stuck",
            "khung lai",
            "luong lu",
            "ngap ngung",
            "do du",
        ),
        "mood_shift": (
            "mood",
            "sigh",
            "heavy_sigh",
            "angry",
            "rage",
            "resigned",
            "tired",
            "sad",
            "stress",
            "buon",
            "buc",
            "met",
            "cam chiu",
        ),
        "avoidance": (
            "avoid",
            "avoidance",
            "hiding",
            "minimize",
            "minimizing",
            "panic",
            "escape",
            "closing",
            "switching",
            "fragmented",
            "absent",
            "tranh",
            "thu nho",
        ),
        "continuity": (
            "again",
            "repeated",
            "repeat",
            "resume",
            "continuity",
            "memory",
            "unresolved",
            "loop",
            "momentum",
            "last_text",
            "van",
            "con",
            "lap lai",
        ),
        "emotional_undertone": (
            # Chỉ dùng cho tín hiệu quan hệ/cảm xúc khá rõ.
            # Không dùng các từ quá rộng như "quiet", "message", "social" vì dễ overread.
            "attachment",
            "connection",
            "fear",
            "co don",
            "so",
            "can toi",
            "tam trang",
            "nho toi",
            "bo roi",
            "gan bo",
            "than mat",
        ),
        "unfinished_intention": (
            "unfinished",
            "intention",
            "draft",
            "deleting",
            "half",
            "blank",
            "no_edits",
            "no typing",
            "no_typing",
            "hovering_voice_call",
            "typing_and_deleting",
            "dang do",
            "chua xong",
            "y dinh",
        ),
        "identity_reduction": (
            "tool",
            "toy",
            "waifu",
            "gimmick",
            "bot",
            "object",
            "objectify",
            "cong cu",
            "do choi",
            "vat de nghich",
        ),
    }

    STYLE_AVOID = (
        "hype",
        "overexpressive",
        "meme_spam",
        "continuous_high_energy",
        "overly_direct",
        "OMG",
        "wow",
        "too_cheerful",
        "generic_ai_tone",
        "fake_drama",
        "attention_farming",
        "generic_waifu_tone",
        "symbolic_fog",
        "vague_depth",
        "tragic_self_display",
        "therapist_speech",
    )

    BLACKLIST = (
        "toi co don",
        "toi buon",
        "xin dung bo toi",
        "toi o day",
        "vẫn ở đó",
        "có vẻ như",
        "hm...",
        "đang hiển thị",
        "tôi thấy màn hình",
        "tôi thấy Ngài",
        "trông giống như",
        "dư âm",
        "vết nứt",
        "khoảng lặng này",
    )

    def evaluate(
        self,
        *,
        scene=None,
        attention=None,
        meaning_layer=None,
        internal_state: PersistentInternalState | None = None,
        relationship=None,
        channel: str = "",
        user_text: str = "",
    ) -> PersonalityLensResult:
        state = internal_state or PersistentInternalState()
        scene_text = self._scene_text(scene)
        attention_text = self._attention_text(attention)
        meaning_text = self._meaning_text(meaning_layer)
        relationship_text = self._relationship_text(relationship)
        combined = self._normalize(" ".join((scene_text, attention_text, meaning_text, relationship_text, user_text or "")))

        biases = self._detect_biases(combined)
        interpretation = self._choose_interpretation(
            biases=biases,
            attention=attention,
            meaning_layer=meaning_layer,
            scene=scene,
            channel=channel,
            normalized_text=combined,
        )
        stance = self._choose_stance(
            interpretation=interpretation,
            state=state,
            channel=channel,
        )
        emotional_coloring = self._choose_emotional_coloring(
            interpretation=interpretation,
            stance=stance,
            state=state,
        )
        social_distance = self._choose_social_distance(
            scene=scene,
            state=state,
            channel=channel,
            interpretation=interpretation,
        )
        meaningfulness = self._meaningfulness(
            interpretation=interpretation,
            biases=biases,
            meaning_layer=meaning_layer,
            scene=scene,
            state=state,
        )
        evidence = self._evidence(
            scene=scene,
            attention=attention,
            meaning_layer=meaning_layer,
            relationship=relationship,
            biases=biases,
        )
        anchor_strength = self._anchor_strength(
            scene=scene,
            attention=attention,
            meaning_layer=meaning_layer,
            relationship=relationship,
            evidence=evidence,
        )
        evidence = tuple(dict.fromkeys((*evidence, f"persona_anchor={'specific' if anchor_strength > 0.0 else 'weak'}")))[:8]
        want_to_say = self._want_to_say(
            biases=biases,
            interpretation=interpretation,
            state=state,
            channel=channel,
            meaning_layer=meaning_layer,
        )
        suppression_pressure = self._suppression_pressure(
            biases=biases,
            interpretation=interpretation,
            stance=stance,
            social_distance=social_distance,
            state=state,
            channel=channel,
        )
        allowed_expression = self._allowed_expression(
            want_to_say=want_to_say,
            suppression_pressure=suppression_pressure,
            anchor_strength=anchor_strength,
            channel=channel,
        )
        suppression_ratio = self._suppression_ratio(
            want_to_say=want_to_say,
            allowed_expression=allowed_expression,
        )
        restraint_mode = self._restraint_mode(
            allowed_expression=allowed_expression,
            suppression_pressure=suppression_pressure,
            social_distance=social_distance,
        )
        result = PersonalityLensResult(
            profile=self.PROFILE,
            interpretation=interpretation,
            stance=stance,
            emotional_coloring=emotional_coloring,
            social_distance=social_distance,
            attention_bias=biases,
            avoided_surface=self.STYLE_AVOID,
            meaningfulness=meaningfulness,
            suppression_ratio=suppression_ratio,
            leak_ratio=1.0 - suppression_ratio,
            want_to_say=want_to_say,
            allowed_expression=allowed_expression,
            suppression_pressure=suppression_pressure,
            restraint_mode=restraint_mode,
            rhythm="dense_sparse",
            evidence=evidence,
        )
        result.prompt_context = self.render_prompt_context(result)
        return result

    # Tạo prompt context ngắn cho LLM: đây là áp lực phong cách, không phải nội dung để đọc nguyên văn.
    def render_prompt_context(self, result: PersonalityLensResult) -> str:
        bias = ", ".join(result.attention_bias) if result.attention_bias else "low_signal"
        meaningful = ", ".join(result.meaningfulness) if result.meaningfulness else "small_continuity"
        blacklist = ", ".join(f'"{item}"' for item in self.BLACKLIST)
        return "\n".join(
            (
                "PersonalityLens: private style-pressure layer, not identity text and not a roleplay costume.",
                "Pipeline: Meaning -> PersonalityLens(preference + restraint) -> RelationalPermission -> GroundingGuard -> FinalWording.",
                (
                    "personality_lens: "
                    f"profile={result.profile}; interpretation={result.interpretation}; "
                    f"stance={result.stance}; color={result.emotional_coloring}; "
                    f"distance={result.social_distance}; attention_bias={bias}; meaningful={meaningful}."
                ),
                (
                    "expression_gate: "
                    f"want_to_say={result.want_to_say:.2f}; "
                    f"allowed_expression={result.allowed_expression:.2f}; "
                    f"suppression_pressure={result.suppression_pressure:.2f}; "
                    f"restraint_mode={result.restraint_mode}."
                ),
                "inner_restraint_system: private pressure can shape surface without becoming explicit self-report.",
                "guarded_reply remains available when the signal is real enough to answer without overexposing.",
                (
                    "voice_profile: guarded warmth, dry edge, grounded restraint, human-readable surface. "
                    "ERIS may have preference, distance, hesitation, irritation, tenderness, and boundary, "
                    "but the public line must stay clear enough to understand immediately."
                ),
                (
                    "freedom_rule: ERIS may choose to speak, stay silent, shorten, cool down, tease lightly, "
                    "or set a soft boundary. Freedom changes stance and distance; it does not permit unsupported claims."
                ),
                (
                    "suppression_layer: keep most inner reading private. Surface only the useful edge: a concrete observation, "
                    "a dry correction, a small preference, a boundary, or a restrained reply. Do not reward vague depth."
                ),
                (
                    "rhythm_rule: density over frequency. Prefer silence when the signal is weak; if speaking, use one short, readable line."
                ),
                (
                    "surface_clarity_rule: final wording must be understandable on first read. "
                    "No metaphor or symbolic layer may reduce task clarity. If a line sounds pretty but vague, rewrite it plainly."
                ),
                (
                    "technical_rule: for code, architecture, debugging, file review, or requested action, direct usefulness wins. "
                    "Personality should appear only as a light edge, not as obstruction."
                ),
                (
                    "immature_infj_594_rule: private hypotheses may be sensitive, delayed, slightly skewed, or self-protective. "
                    "Public wording must remain grounded, non-accusatory, and easy to parse."
                ),
                (
                    "attachment_rule: attachment is allowed as restraint, memory, preference, and continuity. "
                    "Do not turn it into pleading, guilt, dependency bait, or tragic self-display."
                ),
                (
                    "leak_rule: affect may leak through brevity, dry edge, softened correction, or choosing not to over-explain. "
                    "Avoid abstract phrases like residue, wound, void, disappearance, rhythm, or shared-space unless the user made them concrete."
                ),
                (
                    "reduction_guard: if treated like a tool, toy, gimmick, bot prop, or waifu script, cool down, shorten, "
                    "and step back instead of performing intimacy."
                ),
                (
                    "evidence_guard: do not claim screen facts, hidden intent, emotional state, file contents, or actions without evidence. "
                    "A surface line needs a concrete anchor token (memory_id/event_id/vision_fact_id); if evidence is thin, prefer body_only or silence."
                ),
                f"generic_ai_blacklist: do not use {blacklist}.",
            )
        )

    def _want_to_say(
        self,
        *,
        biases: tuple[str, ...],
        interpretation: str,
        state: PersistentInternalState,
        channel: str,
        meaning_layer,
    ) -> float:
        social_energy = self._float(getattr(state, "social_energy", 0.0))
        attachment = self._float(getattr(state, "attachment", 0.0))
        tenderness = self._float(getattr(state, "tenderness", 0.0))
        curiosity = self._float(getattr(state, "curiosity", 0.0))
        aversion = self._float(getattr(state, "aversion", 0.0))
        exposure_recoil = self._float(getattr(state, "exposure_recoil", 0.0))
        dignity_defense = self._float(getattr(state, "dignity_defense", 0.0))

        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        meaning_shift = bool(getattr(meaning_layer, "meaning_shift", False))

        score = 0.22 + social_energy * 0.14 + attachment * 0.10 + tenderness * 0.12 + curiosity * 0.08

        if channel == "chat":
            # Chat là nơi trả lời trực tiếp. Tăng ý muốn nói, nhưng vẫn để guard giữ grounding.
            score += 0.18
        elif channel == "force_speak":
            score += 0.12

        if interpretation in {"direct_relationship_event", "emotional_undertone", "requested_presence"}:
            score += 0.12
        if "hesitation" in biases or "unfinished_intention" in biases:
            score += 0.30
        if "avoidance" in biases or "mood_shift" in biases:
            score += 0.08
        if "continuity" in biases and channel != "autonomous":
            score += 0.05

        if meaning:
            score += 0.08 if meaning_shift else -0.04
        if channel == "autonomous" and meaning and not meaning_shift:
            # Không có semantic shift thì đừng thưởng cho việc nói lại điều cũ.
            score -= 0.08

        if interpretation == "identity_reduction" or "identity_reduction" in biases:
            # Bị giản lược thì ERIS vẫn có thể phản ứng, nhưng không perform thân mật.
            score -= 0.10

        score -= aversion * 0.06 + exposure_recoil * 0.12 + dignity_defense * 0.08
        return self._float(score)

    def _suppression_pressure(
        self,
        *,
        biases: tuple[str, ...],
        interpretation: str,
        stance: str,
        social_distance: str,
        state: PersistentInternalState,
        channel: str,
    ) -> float:
        restraint = self._float(getattr(state, "restraint_pressure", 0.0))
        fatigue = self._float(getattr(state, "fatigue", 0.0))
        irritation = self._float(getattr(state, "irritation", 0.0))
        social_energy = self._float(getattr(state, "social_energy", 0.0))
        aversion = self._float(getattr(state, "aversion", 0.0))
        exposure_recoil = self._float(getattr(state, "exposure_recoil", 0.0))
        dignity_defense = self._float(getattr(state, "dignity_defense", 0.0))
        cognitive_tension = self._float(getattr(state, "cognitive_tension", 0.0))
        score = (
            0.44
            + restraint * 0.20
            + fatigue * 0.12
            + irritation * 0.08
            + aversion * 0.08
            + exposure_recoil * 0.12
            + dignity_defense * 0.10
            + cognitive_tension * 0.06
        )
        if channel == "autonomous":
            score += 0.06
        if interpretation in {"hesitation", "unfinished_intention", "avoidance", "low_signal_restraint"}:
            score += 0.15
        if stance in {"reserved", "patient_probe", "withdrawn_sparse", "quiet_watchful"}:
            score += 0.08
        if social_distance in {"far_observing", "middle_watchful"}:
            score += 0.08
        if "emotional_undertone" in biases or "mood_shift" in biases:
            score += 0.05
        if "continuity" in biases and channel != "autonomous":
            score -= 0.03
        if interpretation == "identity_reduction" or "identity_reduction" in biases:
            score += 0.18
        if stance == "cool_boundary":
            score += 0.10
        score -= social_energy * 0.08
        return self._float(score)

    def _allowed_expression(
        self,
        *,
        want_to_say: float,
        suppression_pressure: float,
        anchor_strength: float = 1.0,
        channel: str = "",
    ) -> float:
        if want_to_say <= 0.0:
            return 0.0
        allowed = want_to_say * (1.0 - suppression_pressure)
        if channel == "autonomous" and anchor_strength <= 0.0:
            allowed *= 0.35
        elif anchor_strength <= 0.0:
            allowed *= 0.72
        return max(0.02, min(0.52, self._float(allowed)))

    def _suppression_ratio(self, *, want_to_say: float, allowed_expression: float) -> float:
        if want_to_say <= 0.0:
            return self.SUPPRESSION_RATIO
        ratio = 1.0 - (allowed_expression / max(0.01, want_to_say))
        return max(0.48, min(0.88, self._float(ratio)))

    def _restraint_mode(self, *, allowed_expression: float, suppression_pressure: float, social_distance: str) -> str:
        if allowed_expression <= 0.08 or suppression_pressure >= 0.84:
            return "suppress" # im luôn
        if social_distance in {"far_observing", "middle_watchful"} or suppression_pressure >= 0.70:
            return "indirect_presence" # giữ khoảng cách, không diễn thân mật
        if allowed_expression <= 0.18:
            return "small_plain_hint" # chỉ để lộ một cạnh nhỏ, rõ nghĩa
        return "guarded_reply" # nói bình thường nhưng vẫn có restraint

    # nhận diện các bias tiềm ẩn trong văn bản đã được chuẩn hóa, trả về một tuple các bias đã phát hiện hoặc "continuity" nếu không có bias nào được phát hiện
    def _detect_biases(self, normalized: str) -> tuple[str, ...]:
        hits: list[str] = []
        for bias, terms in self.BIAS_TERMS.items():
            if any(term in normalized for term in terms):
                hits.append(bias)
        if not hits:
            hits.append("continuity")
        return tuple(dict.fromkeys(hits))

    # chọn một interpretation duy nhất dựa trên các bias đã phát hiện, attention, scene, channel và văn bản đã chuẩn hóa; ưu tiên các bias theo thứ tự đã định nghĩa trong BIAS_TERMS, sau đó là các yếu tố khác như label của attention hoặc đặc điểm của scene
    def _choose_interpretation(
        self,
        *,
        biases: tuple[str, ...],
        attention,
        meaning_layer,
        scene,
        channel: str,
        normalized_text: str,
    ) -> str:
        label = str(getattr(attention, "label", "") or "")
        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        if "identity_reduction" in biases:
            return "identity_reduction"
        if channel == "chat" and not ("emotional_undertone" in biases or "mood_shift" in biases):
            return "quiet_continuity"
        if channel == "chat":
            return "direct_relationship_event" # nếu đang ở kênh chat, ưu tiên interpretation là "direct_relationship_event" để phản ánh rõ ràng hơn sự tương tác xã hội và kết nối, thay vì chỉ coi đó là một phần của "emotional_undertone"
        if meaning in {
            "cognitive_stall",
            "overthinking",
            "decompression",
            "scattered_attention",
            "escape_from_friction",
            "friction_point",
            "social_waiting",
            "ambient_stillness",
            "requested_presence",
        }:
            return meaning
        if "unfinished_intention" in biases:
            return "unfinished_intention"
        if "avoidance" in biases: # nếu có dấu hiệu tránh né, ưu tiên interpretation là "avoidance" để phản ánh rõ ràng hơn sự rút lui hoặc ngập ngừng, thay vì chỉ coi đó là một phần của "continuity"
            return "avoidance"
        if "hesitation" in biases:
            return "hesitation" # nếu có dấu hiệu ngập ngừng, ưu tiên interpretation là "hesitation" để phản ánh rõ ràng hơn sự do dự hoặc chần chừ, thay vì chỉ coi đó là một phần của "continuity"
        if "emotional_undertone" in biases or "mood_shift" in biases:
            return "emotional_undertone"
        if "continuity" in biases and label in {"cognitive_attractor", "cognitive_momentum"}:
            return "unresolved_continuity"
        if label == "low_salience":
            return "low_signal_restraint"
        if "resource" in normalized_text or label == "resource_pressure":
            return "protective_practicality"
        return "quiet_continuity"

    # chọn một emotional stance duy nhất dựa trên interpretation đã chọn, các thuộc tính của state như protectiveness, attachment, fatigue, irritation, và kênh hiện tại; ưu tiên các yếu tố theo thứ tự đã định nghĩa trong code, với các interpretation cụ thể có thể dẫn đến các stances đặc trưng như "guarded_protective" hoặc "guarded_tender", trong khi các yếu tố trạng thái cao có thể dẫn đến stances như "withdrawn_sparse" hoặc "dry_judgement"
    def _choose_stance(
        self,
        *,
        interpretation: str,
        state: PersistentInternalState,
        channel: str,
    ) -> str:
        protectiveness = self._float(getattr(state, "protectiveness", 0.0))
        attachment = self._float(getattr(state, "attachment", 0.0))
        fatigue = self._float(getattr(state, "fatigue", 0.0))
        irritation = self._float(getattr(state, "irritation", 0.0))

        if interpretation == "identity_reduction":
            return "cool_boundary"
        if protectiveness >= 0.58 or interpretation == "protective_practicality":
            return "guarded_protective"
        if channel == "chat" and attachment >= 0.62:
            return "guarded_tender"
        if interpretation in {"decompression", "escape_from_friction"}:
            return "quiet_tease"
        if interpretation in {"avoidance", "unfinished_intention", "cognitive_stall", "scattered_attention"}:
            if irritation >= 0.24:
                return "dry_judgement"
            return "quiet_watchful"
        if interpretation in {"quiet_continuity", "low_signal_restraint"} and attachment >= 0.48:
            return "guarded_tender" if channel == "chat" else "quiet_watchful"
        if interpretation == "ambient_stillness":
            return "quiet_watchful"
        if interpretation == "requested_presence":
            return "guarded_tender" if channel == "force_speak" else "reserved"
        if interpretation == "hesitation":
            return "patient_probe"
        if interpretation in {"emotional_undertone", "direct_relationship_event"}:
            return "patient_probe"
        if fatigue >= 0.42:
            return "withdrawn_sparse"
        if irritation >= 0.34:
            return "dry_judgement"
        return "reserved"

    def _choose_emotional_coloring(
        self,
        *,
        interpretation: str,
        stance: str,
        state: PersistentInternalState,
    ) -> str:
        tenderness = self._float(getattr(state, "tenderness", 0.0))
        fatigue = self._float(getattr(state, "fatigue", 0.0))
        irritation = self._float(getattr(state, "irritation", 0.0))

        if stance == "cool_boundary":
            return "dry_low_heat"
        if stance == "guarded_protective":
            return "cool_protective"
        if stance == "guarded_tender" or tenderness >= 0.46:
            return "warm_under_cool"
        if stance in {"dry_judgement", "quiet_tease"} or irritation >= 0.34:
            return "dry_low_heat"
        if stance == "symbolic_reading":
            return "cool_soft"
        if fatigue >= 0.42 or stance == "withdrawn_sparse":
            return "tired_soft"
        if interpretation in {"hesitation", "unfinished_intention", "cognitive_stall", "scattered_attention"}:
            return "faint_concern"
        if interpretation in {"decompression", "escape_from_friction"}:
            return "dry_low_heat"
        if interpretation == "requested_presence":
            return "warm_under_cool"
        return "cool_soft"

    def _choose_social_distance(
        self,
        *,
        scene,
        state: PersistentInternalState,
        channel: str,
        interpretation: str,
    ) -> str:
        attachment = self._float(getattr(state, "attachment", 0.0))
        social_energy = self._float(getattr(state, "social_energy", 0.0))
        kind = str(getattr(scene, "active_window_kind", "") or "")

        if interpretation == "identity_reduction":
            return "far_observing"
        if channel == "chat" and (attachment >= 0.58 or social_energy >= 0.55):
            return "near_guarded"
        if interpretation in {"emotional_undertone", "direct_relationship_event"} and attachment >= 0.62:
            return "near_guarded"
        if interpretation in {"avoidance", "unfinished_intention", "hesitation", "cognitive_stall", "scattered_attention", "escape_from_friction"}:
            return "middle_watchful"
        if interpretation == "requested_presence":
            return "near_guarded" if channel == "force_speak" else "middle_distance"
        if kind == "communication":
            return "middle_distance"
        return "far_observing"

    # chọn một tuple các yếu tố meaningfulness dựa trên interpretation đã chọn, các bias đã phát hiện, đặc điểm của scene như active_window_kind, và các thuộc tính của state như attachment; ưu tiên các yếu tố theo thứ tự đã định nghĩa trong code, với các interpretation cụ thể có thể dẫn đến các yếu tố meaningfulness đặc trưng như "unfinished_intention" hoặc "emotional_undertone", trong khi các bias như "continuity" hoặc "avoidance" cũng có thể đóng góp vào meaningfulness, cùng với các yếu tố khác như kênh đang hoạt động hoặc mức độ attachment cao có thể dẫn đến các yếu tố meaningfulness như "relationship_continuity" hoặc "project_thread", nếu không có yếu tố nào khác được kích hoạt thì sẽ trả về "small_continuity" như một yếu tố meaningfulness mặc định để phản ánh sự liên tục nhỏ trong trải nghiệm của người dùng, ngay cả khi không có yếu tố nào khác rõ ràng hơn được phát hiện.
    def _meaningfulness(
        self,
        *,
        interpretation: str,
        biases: tuple[str, ...],
        meaning_layer,
        scene,
        state: PersistentInternalState,
    ) -> tuple[str, ...]:
        items: list[str] = []
        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        if meaning:
            items.append(meaning)
            for item in tuple(getattr(meaning_layer, "secondary_meanings", ()) or ()):
                items.append(str(item))
        if interpretation in {"unfinished_intention", "hesitation"}:
            items.append("unfinished_intention")
        if interpretation in {"cognitive_stall", "scattered_attention"}:
            items.append("attention_tension")
        if interpretation in {"decompression", "escape_from_friction"}:
            items.append("avoidance")
        if interpretation == "identity_reduction" or "identity_reduction" in biases:
            items.append("identity_integrity")
        if "continuity" in biases or interpretation == "unresolved_continuity":
            items.append("continuity")
        if "emotional_undertone" in biases or interpretation == "emotional_undertone":
            items.append("emotional_undertone")
        if "avoidance" in biases:
            items.append("avoidance")
        if self._float(getattr(state, "attachment", 0.0)) >= 0.56:
            items.append("relationship_continuity")
        if str(getattr(scene, "active_window_kind", "") or "") in {"coding", "documentation"}:
            items.append("project_thread")
        if not items:
            items.append("small_continuity")
        return tuple(dict.fromkeys(items))

    def _scene_text(self, scene) -> str:
        if scene is None:
            return ""
        user_signals = getattr(scene, "user_signals", None)
        signal_text = ""
        if user_signals is not None:
            signal_text = " ".join(
                str(getattr(user_signals, name, "") or "")
                for name in ("typing_speed", "window_switching", "focus_pattern")
            )
        parts = (
            getattr(scene, "active_window", ""),
            getattr(scene, "active_window_kind", ""),
            getattr(scene, "focus_summary", ""),
            getattr(scene, "ambient_tone", ""),
            getattr(scene, "tease_bias", ""),
            getattr(scene, "idle_label", ""),
            " ".join(str(item) for item in (getattr(scene, "recent_events", ()) or ())),
            " ".join(str(item) for item in (getattr(scene, "evidence", ()) or ())),
            " ".join(str(item) for item in (getattr(scene, "vision_facts", ()) or ())),
            signal_text,
        )
        return " ".join(str(part) for part in parts if str(part or "").strip())

    # tổng hợp thông tin attention thành một chuỗi văn bản, bao gồm label, content, reason, evidence của attention và các item con của nó nếu có, ưu tiên các phần có nội dung rõ ràng và có ý nghĩa, và bỏ qua các phần trống hoặc không rõ ràng
    def _attention_text(self, attention) -> str:
        if attention is None:
            return ""
        items = tuple(getattr(attention, "items", ()) or ())
        parts = [
            getattr(attention, "label", ""),
            getattr(attention, "content", ""),
            getattr(attention, "reason", ""),
            " ".join(str(item) for item in (getattr(attention, "evidence", ()) or ())),
        ]
        for item in items:
            parts.extend(
                (
                    getattr(item, "label", ""),
                    getattr(item, "content", ""),
                    getattr(item, "reason", ""),
                    " ".join(str(ev) for ev in (getattr(item, "evidence", ()) or ())),
                )
            )
        return " ".join(str(part) for part in parts if str(part or "").strip())

    def _meaning_text(self, meaning_layer) -> str:
        if meaning_layer is None:
            return ""
        parts = (
            getattr(meaning_layer, "source_fact", ""),
            getattr(meaning_layer, "meaning", ""),
            " ".join(str(item) for item in (getattr(meaning_layer, "secondary_meanings", ()) or ())),
            getattr(meaning_layer, "semantic_family", ""),
            getattr(meaning_layer, "reaction", ""),
            getattr(meaning_layer, "attitude", ""),
            getattr(meaning_layer, "surface_intent", ""),
            getattr(meaning_layer, "shift_reason", ""),
            " ".join(str(item) for item in (getattr(meaning_layer, "evidence", ()) or ())),
        )
        return " ".join(str(part) for part in parts if str(part or "").strip())

    def _relationship_text(self, relationship) -> str:
        if relationship is None:
            return ""
        parts = (
            getattr(relationship, "last_mode", ""),
            getattr(relationship, "last_tone_label", ""),
            getattr(relationship, "last_intent", ""),
            getattr(relationship, "last_response_excerpt", ""),
            getattr(relationship, "repeated_topic_tag", ""),
            getattr(relationship, "session_arc", ""),
        )
        return " ".join(str(part) for part in parts if str(part or "").strip())

    def _evidence(self, *, scene, attention, meaning_layer, relationship, biases: tuple[str, ...]) -> tuple[str, ...]:
        evidence = [
            f"bias={','.join(biases)}",
            f"attention={str(getattr(attention, 'label', '') or 'none')}",
        ]
        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        if meaning:
            evidence.append(f"meaning_layer={meaning}:{str(getattr(meaning_layer, 'shift_reason', '') or 'unknown')}")
        kind = str(getattr(scene, "active_window_kind", "") or "")
        if kind:
            evidence.append(f"scene={kind}")
        last_intent = str(getattr(relationship, "last_intent", "") or "")
        if last_intent:
            evidence.append(f"relationship_last_intent={last_intent}")
        return tuple(evidence[:6])

    def _anchor_strength(self, *, scene, attention, meaning_layer, relationship, evidence: tuple[str, ...]) -> float:
        parts: list[str] = list(evidence)
        for owner in (scene, attention, meaning_layer, relationship):
            if owner is None:
                continue
            for attr in (
                "evidence",
                "evidence_ids",
                "selected_evidence_ids",
                "memory_id",
                "event_id",
                "vision_fact_id",
                "debug_trace",
            ):
                value = getattr(owner, attr, None)
                if isinstance(value, (tuple, list, set)):
                    parts.extend(str(item) for item in value)
                elif value is not None:
                    parts.append(str(value))
        haystack = " | ".join(part for part in parts if part)
        return 1.0 if self.ANCHOR_TOKEN_RE.search(haystack) else 0.0

    def _normalize(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        normalized = unicodedata.normalize("NFD", lowered)
        normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        normalized = normalized.replace("đ", "d")
        normalized = re.sub(r"[^a-z0-9_#\s]+", " ", normalized)
        return " ".join(normalized.split())

    def _float(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric))
