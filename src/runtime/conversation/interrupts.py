# -*- coding: utf-8 -*-
"""Phân loại interrupt tối thiểu, ưu tiên an toàn và khả năng chen ngang thật."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import InterruptKind

_BACKCHANNELS = {"ừ", "uh", "uhm", "ừm", "à", "ờ", "đúng", "đúng rồi", "ok", "oke", "mhm", "hm"}
_STOP = re.compile(r"^(dừng|stop|khoan|đợi|thôi|im|đừng nói|ngưng)\b", re.I)


@dataclass(frozen=True, slots=True)
class InterruptDecision:
    kind: InterruptKind
    cancel_generation: bool
    cancel_audio: bool
    preserve_continuation: bool


def classify_interrupt(text: str, *, final: bool = True) -> InterruptDecision:
    normalized = " ".join(str(text or "").lower().strip().split())
    if normalized in _BACKCHANNELS:
        return InterruptDecision(InterruptKind.BACKCHANNEL, False, False, True)
    if _STOP.search(normalized):
        return InterruptDecision(InterruptKind.STOP, True, True, False)
    if normalized and (final or len(normalized) >= 4):
        return InterruptDecision(InterruptKind.STEERING, True, True, False)
    return InterruptDecision(InterruptKind.UNKNOWN, False, False, True)


__all__ = ["InterruptDecision", "classify_interrupt"]
