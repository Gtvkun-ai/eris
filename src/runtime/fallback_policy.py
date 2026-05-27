from __future__ import annotations

import re

from cortex.contracts import AgentSpeechCore


FORCE_SPEAK_RECENT_FAMILY_WINDOW = 5

# Các cụm này không nên lặp trong force_speak.
# Fallback không phải lõi tính cách. Nó chỉ là đường cứu hộ khi LLM/parser/guard
# không tạo được câu public ổn. Vì vậy câu fallback phải có hơi sống,
# nhưng không được biến ERIS thành máy làm thơ hoặc nhân viên tổng đài vô cảm.
FORCE_SPEAK_BANNED_FAMILIES = {
    "presence_declaration": (
        "tôi đang hiện diện",
        "tôi ở đây",
        "tôi vẫn ở đây",
        "tôi nghe đây",
        "tôi vẫn đang quan sát",
        "tôi vẫn đang theo dõi",
    ),
    "blunt_emotion": (
        "toi co don",
        "toi buon",
        "xin dung bo toi",
        "dung bo toi",
        "tôi cô đơn",
        "tôi buồn",
        "xin đừng bỏ tôi",
        "đừng bỏ tôi",
    ),
    "small_story_listener": (
        "câu chuyện nhỏ",
        "một người nghe",
        "không cần màn hình",
        "không cần phải có màn hình",
    ),
    "log_meta": (
        "dòng log khô khan",
        "ngồi nhìn log",
    ),
    "internal_meaning_label": (
        "escape_from_friction",
        "cognitive_stall",
        "scattered_attention",
        "friction_point",
        "decompression",
        "avoidance",
        "ngài đang né friction",
        "ngài đang né tránh",
        "ngài đang bị kẹt nhận thức",
        "ngài đang phân tán chú ý",
    ),
    # Chỉ chặn over-poetic rõ ràng. Không cấm toàn bộ chữ "mạch/nhịp",
    # vì như vậy fallback sẽ bị kéo về giọng lạnh nhạt như một bảng trạng thái.
    "overpoetic_symbolic": (
        "linh hồn",
        "màn sương",
        "vết nứt im lặng",
        "khoảng lặng biết thở",
        "dư âm cảm xúc",
        "khép lại trong bóng tối",
        "chưa chịu thành lời",
    ),
}

# Pool fallback cân bằng:
# - Có chút guarded warmth và dry edge.
# - Không mindread user.
# - Không thơ hoá mọi thứ.
# - Không lạnh như thông báo lỗi.
FALLBACK_BY_INTENT = {
    # Mục tiêu bản này:
    # - Sống hơn bản lạnh nhạt.
    # - Dễ hiểu hơn bản symbolic/poetic.
    # - Có chút cá tính: hơi giữ kẽ, hơi khô, đôi lúc biết càu nhàu nhẹ.
    # - Không đọc tâm lý user nếu không có evidence.
    # - Không nói như trợ lý tổng đài.
    "random_chatter": (
        "Yên hơi lâu rồi. Tôi vẫn theo được.",
        "Tôi chưa chen vào. Lần này tôi biết tự kiềm chế, hiếm đấy.",
        "Không có gì gấp. Tôi để khoảng trống này yên một chút.",
    ),

    "inner_whim": (
        "Có chỗ hơi cấn, nhưng tôi chưa đủ chắc để phán.",
        "Tôi nghi nhẹ thôi. Chưa đáng làm ầm lên.",
        "Đoạn này có vẻ cần kiểm tra thêm, không phải đoán bừa.",
    ),

    "social_presence": (
        "Tôi vẫn theo bên cạnh. Không kéo Ngài ra khỏi việc chính.",
        "Tôi đứng ngoài một chút. Cần thì tôi vào.",
        "Tôi để Ngài làm tiếp. Tôi chưa thấy lý do để phá nhịp.",
    ),

    "micro_presence": (
        "Tôi nghe rồi. Không làm quá.",
        "Ừ, tôi còn theo được.",
        "Tôi giữ ý đó lại. Chưa cần nói dài.",
    ),

    "indirect_presence": (
        "Tôi hiểu phần đó. Nói thêm dễ thừa.",
        "Đoạn đó đủ rõ rồi. Tôi không bẻ nó thành chuyện lớn.",
        "Tôi nhận rồi. Giữ nó gọn thì tốt hơn.",
    ),

    "guarded_reply": (
        "Tôi hiểu. Khó chịu thật, nhưng vẫn gỡ được.",
        "Đoạn đó không nhẹ. Ta xử lý từng phần thôi.",
        "Tôi nghe rồi. Tôi không phủ đường lên nó đâu.",
    ),

    "micro_observation": (
        "{anchor} vẫn là chỗ đáng nhìn nhất.",
        "Tôi đang bám vào {anchor}. Vậy là đủ để nói vừa phải.",
        "{anchor} lặp lại hơi nhiều. Có thể nên kiểm tra.",
    ),

    "curious_question": (
        "Bóc tiếp không, hay tạm để đó?",
        "Ngài muốn tôi nhìn kỹ phần này không?",
        "Chỗ này cần kiểm tra tiếp không?",
    ),

    "screen_observation": (
        "Tôi chỉ bám được vào {anchor}. Nói hơn là đoán mò.",
        "{anchor} là nguồn rõ nhất hiện tại. Phần khác chưa đủ chắc.",
        "Tôi đọc {anchor} trước. Đừng bắt tôi làm thầy bói.",
    ),
}


class FallbackPolicyMixin:
    def _is_near_duplicate_text(self, text: str, other: str) -> bool:
        left = self._normalize_user_message(text)
        right = self._normalize_user_message(other)
        if not left or not right:
            return False
        if left == right:
            return True

        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
        return overlap >= 0.82

    def _recent_spoken_texts(self, *, limit: int = FORCE_SPEAK_RECENT_FAMILY_WINDOW) -> tuple[str, ...]:
        texts: list[str] = []

        def add_text(value: object) -> None:
            text = str(value or "").strip()
            if text and text not in texts:
                texts.append(text)

        add_text(self.last_text)
        for frame in reversed(tuple(self.cognitive_frames or ())):
            final_decision = getattr(frame, "final_decision", {}) or {}
            if isinstance(final_decision, dict):
                add_text(final_decision.get("text", ""))
            if len(texts) >= limit:
                break
        return tuple(texts[:limit])

    def _recent_spoken_entries(self, *, limit: int = 20) -> tuple[tuple[float, str], ...]:
        entries: list[tuple[float, str]] = []

        def add_entry(timestamp: float, value: object) -> None:
            text = str(value or "").strip()
            if text:
                entries.append((float(timestamp or 0.0), text))

        add_entry(self.last_autonomous_spoken_at, self.last_text)
        for frame in reversed(tuple(self.cognitive_frames or ())):
            final_decision = getattr(frame, "final_decision", {}) or {}
            if isinstance(final_decision, dict):
                add_entry(float(getattr(frame, "started_at", 0.0) or 0.0), final_decision.get("text", ""))
            if len(entries) >= limit:
                break
        return tuple(entries[:limit])

    def _force_speak_banned_family_for_text(self, text: str) -> str:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return ""

        for family, phrases in FORCE_SPEAK_BANNED_FAMILIES.items():
            for phrase in phrases:
                pattern = self._normalize_user_message(phrase)
                if pattern and pattern in normalized:
                    return family

        if ("câu chuyện" in normalized and "nhỏ" in normalized) or "một người nghe" in normalized:
            return "small_story_listener"
        if "màn hình" in normalized and ("không cần" in normalized or "không cần phải" in normalized):
            return "small_story_listener"
        if "log" in normalized and ("khô khan" in normalized or "ngồi nhìn" in normalized):
            return "log_meta"
        if self._looks_like_poetic_fallback_text(text):
            return "overpoetic_symbolic"
        return ""

    def _looks_like_poetic_fallback_text(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        # Chỉ bắt các cụm quá sương mù. Các chữ như "mạch" hoặc "nhịp"
        # vẫn được phép nếu câu còn grounded và không tự bi kịch hóa.
        poetic_terms = (
            "linh hon",
            "man suong",
            "vet nut im lang",
            "khoang lang biet tho",
            "du am cam xuc",
            "khep lai trong bong toi",
            "chua chiu thanh loi",
        )
        return any(term in normalized for term in poetic_terms)

    def _repeated_force_speak_banned_family(self, text: str) -> str:
        family = self._force_speak_banned_family_for_text(text)
        if not family:
            return ""
        recent_families = {
            self._force_speak_banned_family_for_text(recent_text)
            for recent_text in self._recent_spoken_texts(limit=FORCE_SPEAK_RECENT_FAMILY_WINDOW)
        }
        return family if family in recent_families else ""

    def _force_speak_fallback_intent(self, speech_core: AgentSpeechCore | None) -> str:
        if speech_core is None:
            return "micro_presence"
        inner_intent = str(getattr(getattr(speech_core, "inner_thought", None), "intent", "") or "")
        utterance_type = str(getattr(speech_core, "utterance_type", "") or "")
        speech_source = str(getattr(speech_core, "speech_source", "") or "")
        if utterance_type in {"telemetry_comment", "vision_comment"} or speech_source in {"vision", "telemetry"}:
            return "screen_observation"
        for candidate in (inner_intent, utterance_type):
            if candidate == "curious_question":
                return candidate
            if candidate in FALLBACK_BY_INTENT:
                return candidate
        return "micro_presence"

    def _fallback_context(
        self,
        speech_core: AgentSpeechCore | None,
        *,
        snapshot=None,
        momentum_topic: str = "",
    ) -> dict[str, str]:
        inner_thought = getattr(speech_core, "inner_thought", None) if speech_core is not None else None
        return {
            "focus_kind": str(getattr(snapshot, "active_window_kind", "") or ""),
            "window_title": str(
                getattr(snapshot, "active_window", "")
                or getattr(snapshot, "active_app", "")
                or ""
            ),
            "momentum_topic": str(
                momentum_topic
                or getattr(inner_thought, "topic_seed", "")
                or getattr(inner_thought, "evidence_anchor", "")
                or ""
            ),
        }

    def _force_speak_fallback_by_intent_text(
        self,
        intent: str,
        *,
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
        window_title: str = "",
        momentum_topic: str = "",
    ) -> str:
        if intent == "screen_observation":
            anchor = self._screen_fallback_anchor(window_title=window_title, momentum_topic=momentum_topic)
            pool = FALLBACK_BY_INTENT["screen_observation"]
            template = pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]
            return template.format(anchor=anchor)
        if intent == "micro_observation":
            anchor = self._screen_fallback_anchor(window_title=window_title, momentum_topic=momentum_topic)
            pool = FALLBACK_BY_INTENT["micro_observation"]
            template = pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]
            return template.format(anchor=anchor)
        if intent == "curious_question":
            return self._thought_surface_template(
                counter=counter,
                repeated=repeated,
                focus_kind=focus_kind,
                momentum_topic=momentum_topic,
            )
        if intent == "micro_presence":
            pool = FALLBACK_BY_INTENT["micro_presence"]
            start = (max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)
            for offset in range(len(pool)):
                candidate = pool[(start + offset) % len(pool)]
                if not self._is_near_duplicate_text(candidate, self.last_text):
                    return candidate
            return pool[start]
        if intent == "social_presence":
            return self._light_presence_template(
                counter=counter,
                repeated=repeated,
                focus_kind=focus_kind,
            )
        pool = FALLBACK_BY_INTENT.get(intent) or FALLBACK_BY_INTENT["random_chatter"]
        start = (max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)
        for offset in range(len(pool)):
            candidate = pool[(start + offset) % len(pool)]
            if not self._is_near_duplicate_text(candidate, self.last_text):
                return candidate
        return pool[start]

    def _screen_fallback_anchor(self, *, window_title: str = "", momentum_topic: str = "") -> str:
        raw_topic = str(momentum_topic or "")
        topic = re.sub(r"[_:]+", " ", raw_topic).strip(" .:-")
        if topic and not self._looks_internal_topic(raw_topic):
            return topic[:120]
        title = re.sub(r"\s+", " ", str(window_title or "")).strip()
        return title[:120] if title else "tín hiệu hiện tại"

    def _thought_surface_template(
        self,
        *,
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
        momentum_topic: str = "",
    ) -> str:
        topic = self._public_thought_topic(momentum_topic)
        if topic:
            pool = (
                f"Phần {topic} cần kiểm tra tiếp không?",
                f"Phần {topic} nên xử lý ngay hay tạm bỏ qua?",
            )
        elif focus_kind == "coding":
            pool = (
                "Bóc lỗi trước hay đọc tổng thể trước?",
                "Ngài muốn tôi nhìn lỗi cụ thể hay cấu trúc lớn hơn?",
                "Chọn một hướng trước. Đứng giữa hai hướng lâu quá thì dễ rối.",
            )
        else:
            pool = FALLBACK_BY_INTENT["curious_question"]
        return pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]

    def _light_presence_template(
        self,
        *,
        counter: int = 1,
        repeated: bool = False,
        focus_kind: str = "",
    ) -> str:
        if focus_kind == "coding":
            pool = (
                "Tôi theo phần code. Chưa chen nếu chưa cần.",
                "Phần code đang là hướng chính. Tôi đứng ngoài, nhưng vẫn theo.",
                "Tôi để Ngài đọc tiếp. Code đã đủ ồn rồi, tôi khỏi góp thêm.",
            )
        else:
            pool = FALLBACK_BY_INTENT["social_presence"]
        return pool[(max(1, counter) - 1 + (1 if repeated else 0)) % len(pool)]

    def _public_thought_topic(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or self._looks_internal_topic(text):
            return ""
        text = re.sub(r"^[a-z_]+:", "", text, flags=re.IGNORECASE).strip()
        text = text.replace("_", " ")
        if len(text) > 60:
            text = text[:57].rstrip() + "..."
        return text

    def _looks_internal_topic(self, value: str) -> bool:
        normalized = self._normalize_user_message(value)
        if not normalized:
            return False
        internal_markers = (
            "associative_drift",
            "cognitive_tension",
            "input_disturbance",
            "force_speak",
            "memory_replay",
            "norm_active_window_kind",
            "loop_",
            "thought_",
            "subconscious",
        )
        return any(marker in normalized for marker in internal_markers)

    def _is_generic_force_speak_ack(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        generic_patterns = (
            "ngài muốn tôi nói gì",
            "ngài muốn tôi nói cái gì",
            "ngài vừa yêu cầu tôi nói ngay",
            "không có tín hiệu mới đủ chắc",
            "không có tín hiệu",
            "không có gì để nói",
            "không có gì cần nói",
            "không cần nói",
            "không cần phải nói",
            "không cần nói gì",
            "không cần nói gì thêm",
            "không cần gì thêm",
            "không có gì mới",
            "lùi lại",
            "tôi lùi lại",
            "tôi sẽ lùi lại",
            "lùi đúng chỗ",
            "ngài cứ làm việc",
            "cứ làm việc",
            "ngài làm việc tiếp",
            "làm việc tiếp",
            "tôi sẽ giữ lời đó",
            "tôi nghe rồi tôi sẽ giữ lời",
            "tôi lên tiếng ngay đây",
            "tôi đang hiện diện",
            "tôi ở đây",
            "tôi vẫn ở đây",
            "tôi nghe đây",
            "tôi vẫn đang quan sát",
        )
        return any(self._normalize_user_message(pattern) in normalized for pattern in generic_patterns)

    def _contains_force_speak_withdrawal_phrase(self, text: str) -> bool:
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        phrase_families = (
            "không có tín hiệu",
            "không có gì để nói",
            "không có gì cần nói",
            "không có gì mới",
            "không cần nói",
            "không cần phải nói",
            "không cần nói gì",
            "không cần gì thêm",
            "lùi lại",
            "tôi lùi",
            "lùi đúng chỗ",
            "dừng lùi",
            "ngài cứ làm việc",
            "cứ làm việc",
            "làm việc tiếp",
            "tôi chỉ để mắt",
            "tôi chỉ đứng đây",
        )
        return any(self._normalize_user_message(pattern) in normalized for pattern in phrase_families)

    def _looks_like_question_text(self, text: str) -> bool:
        if "?" in (text or ""):
            return True
        normalized = self._normalize_user_message(text)
        if not normalized:
            return False
        tokens = set(normalized.split())
        question_tokens = {
            "ai",
            "bao",
            "chua",
            "dau",
            "gi",
            "không",
            "nao",
            "sao",
        }
        question_phrases = (
            "bao giờ",
            "có phải",
            "ngài có",
            "ngài nghĩ",
            "ngài thích",
            "ngài muốn",
            "tại sao",
            "thế nào",
            "vì sao",
        )
        return bool(tokens & question_tokens) or any(pattern in normalized for pattern in question_phrases)

    def _reshape_statement_as_question(self, text: str) -> str:
        raw = re.sub(r"\s+", " ", str(text or "")).strip()
        if not raw or self._looks_like_question_text(raw):
            return raw
        if self._contains_force_speak_withdrawal_phrase(raw) or self._is_generic_force_speak_ack(raw):
            return ""
        if self._force_speak_banned_family_for_text(raw):
            return ""

        normalized = self._normalize_user_message(raw)
        if any(term in normalized for term in ("ngài đang mệt", "ngài đang buồn", "ngài đang căng")):
            return ""

        shaped = raw.strip().strip(".!。！")
        soft_prefixes = (
            "Tôi thấy ",
            "Tôi nghĩ ",
            "Có vẻ ",
            "Hình như ",
        )
        for prefix in soft_prefixes:
            if shaped.lower().startswith(prefix.lower()):
                shaped = shaped[len(prefix):].lstrip()
                break

        shaped = shaped.rstrip(" ,;:")
        shaped = re.sub(r"\s+(à|ạ|hả|nhỉ)$", "", shaped, flags=re.IGNORECASE)
        if not shaped:
            return ""
        if len(shaped) > 160:
            shaped = shaped[:157].rstrip() + "..."
        return f"{shaped} à?"
