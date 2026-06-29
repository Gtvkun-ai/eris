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
    lines = _normalize_lines(text)
    if not lines:
        return ""

    # Giữ line break như "beat" diễn xuất. Trước đây ta flatten thành một dòng,
    # khiến Gemini mất dấu chỗ nào cần nghỉ ngắn/chỗ nào là nhịp châm chọc.
    marked_lines = [_apply_pause(line, plan) for line in lines]
    marked = "\n".join(marked_lines).strip()
    if plan.opening_tag and not _LEADING_TAG_RE.match(marked):
        marked = f"{plan.opening_tag} {marked}".strip()
    return marked


def _normalize_lines(text: str) -> list[str]:
    """Chuẩn hoá transcript nhưng không xoá nhịp dòng.

    TTS Gemini hiểu prompt tự nhiên tốt hơn khi transcript có line break rõ.
    Mỗi dòng nên là một breath group ngắn, không phải đoạn văn dài.
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for line in raw.split("\n"):
        clean = " ".join(line.split()).strip()
        if clean:
            out.append(clean)
    return out


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
