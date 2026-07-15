from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


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
        "bạn đang né friction",
        "bạn đang né tránh",
        "bạn đang bị kẹt nhận thức",
        "bạn đang phân tán chú ý",
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


@dataclass(frozen=True, slots=True)
class SemanticRepeatFingerprint:
    normalized_text: str
    intent: str = ""
    action_schema: str = ""


def repeat_fingerprint(normalizer, text: str, *, intent: str = "", action_schema: str = "") -> SemanticRepeatFingerprint:
    return SemanticRepeatFingerprint(
        normalized_text=str(normalizer(text) or ""),
        intent=str(intent or "").strip().lower(),
        action_schema=str(action_schema or "").strip().lower(),
    )



class TextRepeatGuardMixin:
    def _semantic_repeat_match(
        self,
        text: str,
        other: str,
        *,
        intent: str = "",
        other_intent: str = "",
        action_schema: str = "",
        other_action_schema: str = "",
        repair: bool = False,
        follow_up_after_failure: bool = False,
        new_evidence: bool = False,
    ) -> bool:
        # Hỏi lại để sửa một câu sai không phải spam. Exact-string guard từng
        # quên điều hiển nhiên này, vì máy rất thích luật gọn hơn thực tế.
        if repair or follow_up_after_failure or new_evidence:
            return False
        left = repeat_fingerprint(self._normalize_user_message, text, intent=intent, action_schema=action_schema)
        right = repeat_fingerprint(self._normalize_user_message, other, intent=other_intent, action_schema=other_action_schema)
        if not left.normalized_text or not right.normalized_text:
            return False
        if left.intent and right.intent and left.intent != right.intent:
            return False
        if left.action_schema and right.action_schema and left.action_schema != right.action_schema:
            return False
        if left.normalized_text == right.normalized_text:
            return True
        left_tokens = set(left.normalized_text.split())
        right_tokens = set(right.normalized_text.split())
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
        sequence = SequenceMatcher(None, left.normalized_text, right.normalized_text).ratio()
        return overlap >= 0.82 and sequence >= 0.72

    def _is_near_duplicate_text(self, text: str, other: str) -> bool:
        return self._semantic_repeat_match(text, other)

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

    def _autonomous_avoid_text(self, *, limit: int = 6) -> str:
        """Gộp các câu autonomous gần đây thành chuỗi nhiều dòng cho prompt.

        Trước đây directive chỉ nhận `avoid_text=self.last_text` (đúng MỘT câu),
        nên ERIS dễ xoay vòng lại 3-4 câu hỏi cũ mà vẫn "hợp lệ". Đưa cả lịch sử
        gần nhất vào để LLM biết mình vừa nói gì và tiến triển sang ý mới thay vì
        hỏi lại. Mỗi dòng một câu; generate_directive sẽ tự render thành danh sách.
        """
        try:
            recent = self._recent_spoken_texts(limit=limit)
        except Exception:
            recent = ()
        if not recent:
            return str(getattr(self, "last_text", "") or "")
        return "\n".join(recent)

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
        recent = self._recent_spoken_texts(limit=FORCE_SPEAK_RECENT_FAMILY_WINDOW)
        recent_families = {
            self._force_speak_banned_family_for_text(recent_text)
            for recent_text in recent
        }
        if family not in recent_families:
            return ""
        # Layer 7 (veto → penalty): family lặp KHÔNG còn là veto cứng. Nếu câu
        # hiện tại đủ TƯƠI MỚI về nghĩa so với các câu vừa nói (novelty cao), thì
        # đây là một biến thể sống động trong cùng họ, không phải lặp đơn điệu —
        # cho phép. Điều này chỉ nới (không bao giờ chặn thêm), giúp ERIS bớt đơ.
        if self._force_speak_line_is_novel(text, recent):
            return ""
        return family

    def _force_speak_line_is_novel(self, text: str, recent: tuple[str, ...]) -> bool:
        guard = self._get_novelty_guard()
        if guard is None:
            return False
        try:
            # So với câu gần đây thật sự ĐÃ NÓI (không nạp banned seed, vì ở đây
            # ta đang đo độ lặp với chính mình, không phải với kho filler tĩnh).
            score = guard.novelty_score(text, recent_lines=tuple(recent), include_banned_seed=False)
        except Exception:
            return False
        return score >= 0.62

    def _get_novelty_guard(self):
        guard = getattr(self, "_novelty_guard_cache", None)
        if guard is not None:
            return guard
        try:
            from cortex.micro_repeat_guard import SemanticRepeatGuard

            guard = SemanticRepeatGuard()
        except Exception:
            guard = None
        self._novelty_guard_cache = guard
        return guard
