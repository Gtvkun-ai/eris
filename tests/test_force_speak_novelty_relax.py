# -*- coding: utf-8 -*-
"""Layer 7: family-repeat veto defers to semantic novelty (chỉ nới, không chặn thêm)."""

import re
import unicodedata

from runtime.text_repeat_guard import TextRepeatGuardMixin


def _normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFD", str(text or "").lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


class _Host(TextRepeatGuardMixin):
    def __init__(self, recent):
        self._recent = tuple(recent)

    def _normalize_user_message(self, text: str) -> str:
        return _normalize(text)

    def _recent_spoken_texts(self, *, limit: int = 5):
        return self._recent[:limit]


def test_near_identical_family_repeat_still_blocked():
    host = _Host(recent=("Tôi vẫn ở đây.",))
    # Cùng họ presence_declaration, gần như trùng nghĩa → vẫn bị chặn.
    assert host._repeated_force_speak_banned_family("Tôi ở đây.") == "presence_declaration"


def test_novel_line_in_same_family_is_allowed():
    host = _Host(recent=("Tôi ở đây.",))
    # Vẫn thuộc presence_declaration nhưng nội dung tươi/cụ thể, khác hẳn câu cũ
    # → novelty cao → cho phép (trả "").
    novel = "Tôi vẫn đang theo dõi cái build Godot chạy tới bước biên dịch shader rồi đó."
    assert host._repeated_force_speak_banned_family(novel) == ""


def test_no_family_returns_empty():
    host = _Host(recent=("Tôi ở đây.",))
    assert host._repeated_force_speak_banned_family("Cái hàm parser này thiếu return.") == ""


def test_family_not_in_recent_returns_empty():
    # Family hiện tại không xuất hiện trong các câu gần đây → không phải lặp.
    host = _Host(recent=("Cái build vừa xong.",))
    assert host._repeated_force_speak_banned_family("Tôi ở đây.") == ""
