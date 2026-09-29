# -*- coding: utf-8 -*-
"""Ước lượng thời lượng speech cho public voice turn.

Quan trọng: module này **không có quyền biên tập public text**. Từ V6, mọi
word/second budget chỉ là telemetry hoặc guidance trước writer. Sau khi public
writer đã sinh câu, runtime chỉ được đo/ghi log; không được cắt, rút gọn, nối
hoặc thay token vì pacing.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .contracts import DialogueBeat, TurnSpeechBudget

_WORD_RE = re.compile(r"[A-Za-zÀ-ỹ0-9_]+", re.UNICODE)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|(?<=[。！？])")


@dataclass(frozen=True, slots=True)
class SpeechEstimate:
    words: int
    cjk_chars: int
    punctuation_pauses: int
    seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "words": self.words,
            "cjk_chars": self.cjk_chars,
            "punctuation_pauses": self.punctuation_pauses,
            "seconds": round(self.seconds, 2),
        }


@dataclass(frozen=True, slots=True)
class SpeechGuardResult:
    text: str
    estimate: SpeechEstimate
    clipped: bool
    reason: str = ""


def estimate_speech(text: str, *, speed: float = 1.0) -> SpeechEstimate:
    """Ước lượng thời gian đọc theo cả Latin-word và CJK/Japanese characters.

    TTS của Eris thường localize sang tiếng Nhật. Vì vậy chỉ đếm ``split()`` sẽ
    sai với Japanese text, còn chỉ đếm ký tự lại sai với Vietnamese/English.
    Ta lấy mô hình hỗn hợp bảo thủ rồi cộng pause punctuation.
    """
    raw = str(text or "").strip()
    if not raw:
        return SpeechEstimate(0, 0, 0, 0.0)
    speed = max(0.85, min(1.15, float(speed or 1.0)))
    words = len(_WORD_RE.findall(raw))
    cjk_chars = len(_CJK_RE.findall(raw))

    # ~145 wpm cho lời giải thích tự nhiên; Japanese ~310 char/min ở nhịp vừa.
    latin_seconds = (words / (145.0 * speed)) * 60.0
    cjk_seconds = (cjk_chars / (310.0 * speed)) * 60.0

    # Text mixed-language không nên cộng toàn bộ hai estimate vì romaji/số có thể
    # cùng xuất hiện với CJK. Lấy phần lớn hơn + 20% phần nhỏ hơn là đủ bảo thủ.
    body_seconds = max(latin_seconds, cjk_seconds) + 0.20 * min(latin_seconds, cjk_seconds)
    punctuation = sum(raw.count(mark) for mark in (".", "!", "?", "。", "！", "？", ";", ":", ",", "、"))
    pause_seconds = min(5.0, punctuation * 0.11 / speed)
    return SpeechEstimate(words, cjk_chars, punctuation, body_seconds + pause_seconds)


def estimate_beat(beat: DialogueBeat, *, speed: float = 1.0) -> SpeechEstimate:
    """Ước lượng public expansion từ semantic proposition của một DialogueBeat."""
    base = estimate_speech(beat.proposition, speed=speed)
    factor = {"brief": 1.15, "normal": 1.55, "deep": 2.05}.get(beat.detail_level, 1.55)
    if beat.needs_example:
        factor += 0.45
    return SpeechEstimate(
        words=max(base.words, int(round(base.words * factor))),
        cjk_chars=max(base.cjk_chars, int(round(base.cjk_chars * factor))),
        punctuation_pauses=base.punctuation_pauses,
        seconds=base.seconds * factor,
    )


def words_for_seconds(seconds: float, *, speed: float = 1.0) -> int:
    speed = max(0.85, min(1.15, float(speed or 1.0)))
    return max(12, int((max(1.0, float(seconds)) / 60.0) * 145.0 * speed))


def enforce_public_speech_budget(
    text: str,
    budget: TurnSpeechBudget,
    *,
    speed: float = 1.0,
) -> SpeechGuardResult:
    """Đo public speech nhưng **không được sửa lời của writer**.

    Từ V6, runtime không còn quyền cắt, rút gọn hay chèn dấu ``…`` vào câu
    mà LLM public writer đã sinh. ``TurnSpeechBudget`` chỉ còn là metadata/pacing
    guidance dùng *trước* writer để ConversationDirector chọn beat nào nên nói.

    Hàm này được giữ tên cũ để các caller/test/extension cũ không vỡ API. Tuy
    nhiên nó cố ý là observer thuần: output ``text`` luôn giống input đã chuẩn
    hóa whitespace đầu/cuối, ``clipped`` luôn False. Nếu output dài, telemetry
    có thể ghi nhận để cải thiện prompt/DiscoursePlan ở lượt sau; runtime tuyệt
    đối không tự biên tập câu chữ sau writer.
    """
    raw = str(text or "").strip()
    estimate = estimate_speech(raw, speed=speed)
    return SpeechGuardResult(raw, estimate, False, "observe_only_no_runtime_mutation")


__all__ = [
    "SpeechEstimate",
    "SpeechGuardResult",
    "enforce_public_speech_budget",
    "estimate_beat",
    "estimate_speech",
    "words_for_seconds",
]
