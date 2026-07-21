# -*- coding: utf-8 -*-
"""Deterministic current-turn anchor dùng chung cho pre-response và observer.

Đây không phải semantic model thứ hai. Nó chỉ neo một số move vận hành quan
trọng khi model phụ lỗi/429, và tái dùng DiscourseCortex thay vì duy trì một bộ
phrase list khác trong model router.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .frame_builder import CognitiveFrameBuilder
from .normalization import normalize_vi
from .specialists.discourse import DiscourseCortex


_RELATION_HINTS = {
    "continue_assistant_move": "continuation_bid",
    "challenge_assistant_relevance": "challenge_relevance",
    "clarify_assistant_reference": "reference_clarification",
    "clarify_assistant_phrase": "reference_clarification",
    "clarify_assistant_statement": "reference_clarification",
    "challenge_assistant_assumption": "correction",
    "style_feedback": "style_criticism",
    "close_topic": "close_topic",
}


def previous_assistant_from_history(
    recent_history: Sequence[Mapping[str, Any] | str],
    *,
    current_assistant_text: str = "",
) -> str:
    current = " ".join(str(current_assistant_text or "").split()).strip()
    for item in reversed(tuple(recent_history or ())):
        if not isinstance(item, Mapping):
            continue
        if str(item.get("role", "") or "").strip().lower() != "assistant":
            continue
        text = " ".join(str(item.get("content", "") or "").split()).strip()
        if text and text != current:
            return text
    return ""


def infer_current_turn_anchor(user_text: str, *, previous_assistant_text: str = "") -> str:
    text = " ".join(str(user_text or "").casefold().split())
    normalized = normalize_vi(user_text)
    if not text:
        return "none"

    if previous_assistant_text:
        frame = CognitiveFrameBuilder().build(
            user_text=user_text,
            recent_history=({"role": "assistant", "content": previous_assistant_text},),
            turn_id="turn-anchor",
            turn_seq=0,
        )
        relation = DiscourseCortex().project(frame).relation
        hint = _RELATION_HINTS.get(relation)
        if hint:
            return hint

    # Không có history vẫn cần một anchor mỏng cho observer fallback.
    continuation = {
        "roi sao", "the roi sao", "xong", "xong roi sao", "tiep di", "noi tiep",
        "ke tiep", "nua", "nua di", "thi sao", "ehm roi sao a", "um roi sao",
        "om roi sao", "continue",
    }
    stripped = normalized.strip(" ?.!…")
    if stripped in continuation:
        return "continuation_bid"
    if any(
        marker in normalized
        for marker in (
            "la ban a", "la em a", "la ban ha", "la em ha", "co phai ban", "co phai em",
            "y em la gi", "y ban la gi", "cai do la gi", "cai nay la gi", "tuc la sao", "sao co",
        )
    ):
        return "reference_clarification"
    if any(
        marker in normalized
        for marker in (
            "la em nghi toi se", "la ban nghi toi se", "y em la toi", "y ban la toi",
            "em dang nghi toi", "ban dang nghi toi", "sao em lai nghi toi", "sao ban lai nghi toi",
        )
    ):
        return "correction"
    technical = (
        "code", "repo", "log", "bug", "loi", "file", "tts", "api", "runtime",
        "godot", "fix", "sua", "debug", "panel", "model",
    )
    if any(token in normalized for token in technical):
        return "technical_request"
    if any(token in normalized for token in ("khong phai", "y toi la", "toi noi la", "sai roi", "hieu sai", "doc lai")):
        return "correction"
    if any(
        token in normalized
        for token in (
            "chan", "te", "may qua", "cung qua", "nhat", "phen", "khong hay", "generic",
            "chung chung", "vo hon", "nhu bot", "support bot", "cham soc khach hang",
            "coc loc", "lanh voi", "noi lanh", "lam mau", "khong tu nhien",
        )
    ):
        return "style_criticism"
    if any(token in normalized for token in ("sen", "tinh cam", "ngot", "diu", "coc loc", "noi gon", "noi thang")):
        return "style_request"
    if any(token in normalized for token in ("muon tui quen", "muon toi quen", "thich tui", "thich toi", "yeu tui", "yeu toi")):
        return "request_reciprocity"
    if any(token in normalized for token in ("ha", "hong", "khong")) and any(
        token in normalized for token in ("ban muon", "em muon", "ban thich", "em thich", "ban nho", "em nho")
    ):
        return "request_reciprocity"
    if any(token in text for token in ("haha", "lmao", ":))", "=))", "khịa", "trêu")):
        return "play_bid"
    return "unknown"


__all__ = ["infer_current_turn_anchor", "previous_assistant_from_history"]
