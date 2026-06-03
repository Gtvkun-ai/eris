from __future__ import annotations


FORCE_SPEAK_RECENT_FAMILY_WINDOW = 5

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


class TextRepeatGuardMixin:
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
