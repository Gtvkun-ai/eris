# -*- coding: utf-8 -*-
"""Một quyết định chen ngang cho cả Chat, ASR và VoiceManager.

Không coi mọi câu ngắn là backchannel: chỉ những tiếng phụ họa *được biết rõ*
được giữ lại, để không nuốt câu hỏi/correction ngắn của người dùng.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .contracts import InterruptKind

_BACKCHANNELS = frozenset({
    "ừ", "uh", "uhm", "ừm", "à", "ờ", "ô", "ồ", "đúng", "đúng rồi",
    "ok", "oke", "mhm", "hm", "hmm", "được", "rồi", "yeah", "yep",
})
_STOP = re.compile(r"^(?:dừng|stop|khoan|đợi|thôi|im|đừng nói|ngưng)\b", re.I)
# Chỉ bỏ dấu câu ở rìa; không biến câu như 'ô, thế à?' thành phụ họa.
_EDGE_PUNCT = " \t\r\n.!…。、！？"


@dataclass(frozen=True, slots=True)
class InterruptDecision:
    kind: InterruptKind
    cancel_generation: bool
    cancel_audio: bool
    preserve_continuation: bool


def classify_interrupt(text: str, *, final: bool = True) -> InterruptDecision:
    normalized = unicodedata.normalize("NFC", str(text or "")).casefold()
    normalized = " ".join(normalized.strip().split())
    if normalized.strip(_EDGE_PUNCT) in _BACKCHANNELS:
        return InterruptDecision(InterruptKind.BACKCHANNEL, False, False, True)
    if _STOP.search(normalized):
        return InterruptDecision(InterruptKind.STOP, True, True, False)
    if normalized and (final or len(normalized) >= 4):
        return InterruptDecision(InterruptKind.STEERING, True, True, False)
    return InterruptDecision(InterruptKind.UNKNOWN, False, False, True)


__all__ = ["InterruptDecision", "classify_interrupt"]
