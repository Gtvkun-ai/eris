# -*- coding: utf-8 -*-
"""tts_markup.py — render ProsodyPlan thành transcript cho Gemini TTS.

Gemini TTS nhận chỉ dẫn tự nhiên và audio tags bằng tiếng Anh.  Ta chỉ render
tag ở tầng TTS, không đưa tag vào UI/memory.  Các pause ở đây cố ý nhẹ: dấu
"…" dễ được TTS đọc như khoảng dừng hơn là chữ "short pause".
"""

from __future__ import annotations

import re

from runtime.prosody_director import ProsodyPlan


_LEADING_TAG_RE = re.compile(r"^\s*\[[^\]]+\]\s*")


def render_tts_markup(text: str, plan: ProsodyPlan) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""

    marked = _apply_pause(clean, plan)
    if plan.opening_tag and not _LEADING_TAG_RE.match(marked):
        marked = f"{plan.opening_tag} {marked}".strip()
    return marked


def _apply_pause(text: str, plan: ProsodyPlan) -> str:
    if plan.pause_level == "none":
        return text
    if len(text) < 12:
        return text

    # Ưu tiên pause sau dấu phẩy/dấu câu tự nhiên. Nếu không có, chèn sau cụm mở
    # đầu ngắn. Không cố chia từng chữ: nhấn quá nhiều làm giọng thành kịch.
    for sep in ("、", "，", ",", "。", ".", "？", "?", "！", "!"):
        idx = text.find(sep)
        if 2 <= idx <= min(32, len(text) - 4):
            return text[: idx + len(sep)] + "…" + text[idx + len(sep) :].lstrip()

    parts = text.split(" ", 1)
    if len(parts) == 2 and 2 <= len(parts[0]) <= 12:
        return f"{parts[0]}… {parts[1]}"
    return text


__all__ = ["render_tts_markup"]
