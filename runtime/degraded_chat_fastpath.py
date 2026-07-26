# -*- coding: utf-8 -*-
"""Tiny offline/degraded replies for exact, semantically closed turns.

PDF annotation, pages 15-16 and 20
----------------------------------
Fast-path is an emergency escape hatch, not a Vietnamese-understanding engine.
This module therefore accepts only a deliberately small set of exact normalized
forms and is consulted only after the remote semantic authority has failed. It
must never intercept normal healthy chat or grow into another phrase taxonomy.
"""

from __future__ import annotations

import os
from typing import Any

from runtime.cognition.normalization import normalize_vi
from runtime.semantic_frame import validate_semantic_frame


_GREETING_FORMS = frozenset({
    "chao", "xin chao", "hello", "hi", "hey", "chao eris", "xin chao eris",
})
_ACK_FORMS = frozenset({
    "ok", "okay", "duoc", "duoc roi", "hieu roi", "cam on", "cam on em",
})


def _enabled() -> bool:
    raw = str(os.getenv("ERIS_DEGRADED_CHAT_FASTPATH", "1") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def build_degraded_reply(user_text: str, *, language_hint: str = "vi") -> dict[str, Any]:
    """Return a local reply for exact greeting/acknowledgement, otherwise ``{}``."""

    if not _enabled():
        return {}
    cue = normalize_vi(str(user_text or "")).strip(" ?.!,")
    language = str(language_hint or "vi").strip().lower()

    if cue in _GREETING_FORMS:
        text = {
            "en": "Hi. I'm here.",
            "ja": "こんにちは。ここにいるよ。",
            "vi": "Chào bạn. Tôi đây.",
        }.get(language, "Chào bạn. Tôi đây.")
        frame = {
            "turn_kind": "chat_response",
            "discourse_relation": "new_or_direct_turn",
            "user_act": "greeting",
            "target": "assistant",
            "literal_question": False,
            "ambiguity_owner": "none",
            "boundary_action": "none",
            "continuation_key": "none",
            "evidence_scope": "exact_local_syntax",
            "tool_intent": "none",
            "missing_evidence": [],
            "reply_obligation": {
                "must_answer": True,
                "must_not_broad_clarify": True,
                "must_not_call_tool": True,
            },
        }
    elif cue in _ACK_FORMS:
        text = {
            "en": "Got it.",
            "ja": "わかった。",
            "vi": "Ừ, tôi hiểu rồi.",
        }.get(language, "Ừ, tôi hiểu rồi.")
        frame = {
            "turn_kind": "chat_response",
            "discourse_relation": "acknowledgement",
            "user_act": "acknowledgement",
            "target": "assistant",
            "literal_question": False,
            "ambiguity_owner": "none",
            "boundary_action": "none",
            "continuation_key": "recent_assistant_thread",
            "evidence_scope": "exact_local_syntax",
            "tool_intent": "none",
            "missing_evidence": [],
            "reply_obligation": {
                "must_answer": True,
                "must_not_broad_clarify": True,
                "must_not_call_tool": True,
            },
        }
    else:
        return {}

    validated = validate_semantic_frame(frame).frame
    return {
        "semantic_frame": validated,
        "text": text,
        "should_speak": True,
        "performance_hint": "neutral",
        "degraded_fastpath": True,
    }


__all__ = ["build_degraded_reply"]
