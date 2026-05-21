from __future__ import annotations

import re

from cortex.contracts import AgentSpeechCore


FORCE_SPEAK_RECENT_FAMILY_WINDOW = 5
#Đây là blacklist các kiểu câu không muốn lặp khi force_speak
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
        "ngài đang né tranh",
        "ngài đang bị kết nhận thức",
        "ngài đang phân tán chú ý",
    ),
}
FALLBACK_BY_INTENT = {
    "random_chatter": (
        "Yên quá. Tôi tưởng Ngài bỏ dở luôn rồi.",
        "Không khí này bắt đầu đứng lại rồi đấy.",
        "Ngài im hơi lâu hơn mọi hôm.",
    ),

    "inner_whim": (
        "Có gì đó vẫn chưa chịu thành lời.",
        "Mạch này còn vướng nhẹ ở đâu đó.",
        "Tôi thấy đoạn nghĩ đó vẫn chưa khép lại.",
    ),

    "social_presence": (
        "Tôi vẫn giữ chỗ này.",
        "Khoảng yên này vẫn chưa dứt.",
        "Tôi để nhịp này nằm lại một chút.",
    ),

    "micro_presence": (
        "Nhịp này vừa chậm lại một chút.",
        "Có một mạch vẫn chưa khép.",
        "Chỗ này vẫn còn dư âm.",
    ),

    "indirect_presence": (
        "Tôi nghe phần đó rồi.",
        "Cứ để nó nằm yên thêm chút nữa đi.",
        "Có vài thứ chưa cần gọi tên ngay.",
    ),

    "guarded_reply": (
        "Tôi hiểu. Phần đó không nhẹ đâu.",
        "Có gì đó nặng thật, nhưng chưa cần ép nó thành lời.",
        "Tôi nghe rồi. Không cần làm nó mềm đi vội.",
    ),

    "micro_observation": (
        "{anchor} vẫn còn mở đó à.",
        "Ngài cứ quay lại chỗ {anchor} mãi.",
        "Hôm nay {anchor} xuất hiện hơi nhiều đấy.",
    ),

    "curious_question": (
        "Ngài muốn giữ nhịp này yên thêm chút nữa không?",
        "Có đoạn nào trong đó làm Ngài dừng lại không?",
        "Ngài đang quan sát nó, hay đang tránh nó?",
    ),

    "screen_observation": (
        "Điểm rõ nhất hiện tại vẫn là {anchor}.",
        "Tôi chỉ thật sự bám được vào {anchor}.",
        "{anchor} là thứ đọng lại rõ nhất lúc này.",
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
        return ""

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
        return title[:120] if title else "một tín hiệu màn hình vừa đủ rõ"

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
                f"Tôi tò mò một chút: phần {topic} đang cần được nhìn kỹ hơn không?",
                f"Cái mạch {topic} này Ngài muốn giữ yên hay bóc tiếp?",
            )
        elif focus_kind == "coding":
            pool = (
                "Tôi tò mò một chút: Ngài muốn bóc lỗi trước hay giữ nhịp đọc code?",
                "Phần này nên được nhìn như lỗi nhỏ, hay như một nhịp lệch lớn hơn?",
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
                "Tôi giữ chỗ cho mạch code này.",
                "Phần code này tôi để nó liền mạch.",
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

