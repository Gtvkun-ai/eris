# -*- coding: utf-8 -*-
"""Public reply obligation enforcement for direct user turns.

A model may choose silence for an autonomous lane. It may not silently convert a
direct user message into an ambient meditation. This module is deliberately
small: semantic authority decides the obligation; runtime only enforces it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from runtime.degraded_chat_fastpath import build_degraded_reply
from runtime.semantic_frame import SemanticFrame, validate_semantic_frame
from runtime.utterance_spec import degrade_surface_payload


class ReplyRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class ReplyObligationResult:
    payload: dict[str, Any]
    requirement: ReplyRequirement
    repaired: bool = False
    reason: str = ""


def requirement_from_frame(frame: SemanticFrame | Mapping[str, Any] | None, *, direct_user_turn: bool = True) -> ReplyRequirement:
    if isinstance(frame, SemanticFrame):
        typed = frame
    elif isinstance(frame, Mapping):
        typed = validate_semantic_frame(frame).frame
    else:
        typed = None

    boundary = str(getattr(typed, "boundary_action", "") or "").strip().lower() if typed else ""
    if boundary in {"silence", "do_not_reply", "forbidden"}:
        return ReplyRequirement.FORBIDDEN
    if typed is not None and bool(typed.reply_obligation.must_answer):
        return ReplyRequirement.REQUIRED
    return ReplyRequirement.REQUIRED if direct_user_turn else ReplyRequirement.OPTIONAL


def _minimal_text(frame: SemanticFrame | None, *, language_hint: str) -> tuple[str, str]:
    language = str(language_hint or "vi").strip().lower()
    act = str(getattr(frame, "user_act", "") or "").strip().lower() if frame else ""
    if act == "greeting":
        return {
            "en": ("Hi. I'm here.", "social"),
            "ja": ("こんにちは。ここにいるよ。", "social"),
            "vi": ("Chào bạn. Tôi đây.", "social"),
        }.get(language, ("Chào bạn. Tôi đây.", "social"))
    if act == "acknowledgement":
        return {
            "en": ("Got it.", "acknowledgement"),
            "ja": ("わかった。", "acknowledgement"),
            "vi": ("Ừ, tôi hiểu rồi.", "acknowledgement"),
        }.get(language, ("Ừ, tôi hiểu rồi.", "acknowledgement"))
    if act == "repair_request":
        return {
            "en": ("You're right, I failed to answer directly. Please send that exact line once more.", "repair"),
            "ja": ("その通り。直接答えられていなかった。同じ文をもう一度送って。", "repair"),
            "vi": ("Đúng, lượt trước tôi đã không trả lời trực tiếp. Bạn gửi lại đúng câu đó một lần nhé.", "repair"),
        }.get(language, ("Đúng, lượt trước tôi đã không trả lời trực tiếp. Bạn gửi lại đúng câu đó một lần nhé.", "repair"))
    # Chỉ dùng khi provider thật sự không trả được bất kỳ public text nào. Không
    # dùng văn mẫu “hụt nhịp/bám mạch” vì nó vừa vô nghĩa vừa che mất lỗi thật.
    return {
        "en": ("I received that message, but the reply generator returned no usable text.", "repair"),
        "ja": ("そのメッセージは受け取ったが、返答生成から使える文が返らなかった。", "repair"),
        "vi": ("Tôi đã nhận câu này, nhưng bộ sinh lời không trả về câu dùng được.", "repair"),
    }.get(language, ("Tôi đã nhận câu này, nhưng bộ sinh lời không trả về câu dùng được.", "repair"))


def enforce_reply_obligation(
    payload: Mapping[str, Any] | None,
    *,
    user_text: str,
    frame: SemanticFrame | Mapping[str, Any] | None = None,
    language_hint: str = "vi",
    direct_user_turn: bool = True,
) -> ReplyObligationResult:
    data = dict(payload or {})
    typed = frame if isinstance(frame, SemanticFrame) else (
        validate_semantic_frame(frame).frame if isinstance(frame, Mapping) else None
    )
    requirement = requirement_from_frame(typed, direct_user_turn=direct_user_turn)

    if requirement is ReplyRequirement.FORBIDDEN:
        data = degrade_surface_payload(
            data,
            text="",
            language=language_hint,
            reason="reply_forbidden",
            should_speak=False,
        )
        return ReplyObligationResult(data, requirement, repaired=True, reason="reply_forbidden")

    text = str(data.get("text", "") or "").strip()
    should_speak = bool(data.get("should_speak", True))
    if requirement is not ReplyRequirement.REQUIRED or (text and should_speak):
        return ReplyObligationResult(data, requirement)

    if text and not should_speak:
        if typed is not None:
            data["semantic_frame"] = typed.to_dict()
            data["_typed_semantic_frame"] = typed
        data["should_speak"] = True
        data["reply_obligation_repair"] = True
        return ReplyObligationResult(data, requirement, repaired=True, reason="required_reply_should_speak")

    # Exact local forms are preferable because they preserve a correct typed
    # semantic frame and avoid inventing content during provider degradation.
    local = build_degraded_reply(user_text, language_hint=language_hint)
    if local:
        if typed is not None:
            local["semantic_frame"] = typed.to_dict()
            local["_typed_semantic_frame"] = typed
        local = degrade_surface_payload(
            local,
            text=str(local.get("text", "") or ""),
            language=language_hint,
            reason="exact_local_required_reply",
            performance_preset=str(local.get("performance_hint", "neutral") or "neutral"),
            should_speak=True,
        )
        return ReplyObligationResult(local, requirement, repaired=True, reason="exact_local_required_reply")

    text, act_kind = _minimal_text(typed, language_hint=language_hint)
    if typed is not None:
        data["semantic_frame"] = typed.to_dict()
        data["_typed_semantic_frame"] = typed
    data.update({
        "assistant_act": {
            "kind": act_kind,
            "proposition_mode": "continue" if act_kind == "repair" else "none",
            "confidence": 1.0,
        },
        "reply_obligation_repair": True,
    })
    data = degrade_surface_payload(
        data,
        text=text,
        language=language_hint,
        reason="required_reply_repair",
        performance_preset="repair" if act_kind == "repair" else "neutral",
        should_speak=True,
    )
    return ReplyObligationResult(data, requirement, repaired=True, reason="required_reply_repair")


__all__ = [
    "ReplyObligationResult",
    "ReplyRequirement",
    "enforce_reply_obligation",
    "requirement_from_frame",
]
