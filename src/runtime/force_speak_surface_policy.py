from __future__ import annotations

import re


class ForceSpeakSurfacePolicyMixin:
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
            "bạn muốn tôi nói gì",
            "bạn muốn tôi nói cái gì",
            "bạn vừa yêu cầu tôi nói ngay",
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
            "bạn cứ làm việc",
            "cứ làm việc",
            "bạn làm việc tiếp",
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
            "dừng lại",
            "bạn cứ làm việc",
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
            "bạn có",
            "bạn nghĩ",
            "bạn thích",
            "bạn muốn",
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
        if any(term in normalized for term in ("bạn đang mệt", "bạn đang buồn", "bạn đang căng")):
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
