from __future__ import annotations

"""Pragmatic intercept trước LLM cho social invitation/permission.

Intercept này *không trả lời thay Qwen*. Nó chỉ:
1) phân loại act;
2) cập nhật state grant/revoke;
3) tạo response envelope để model biết phải perform hay chỉ thương lượng boundary.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable

from runtime.relational_permission_state import (
    RelationalPermissionState,
    infer_intensity_cap,
    infer_permission_type,
)
from runtime.social_act import ChatAct, PERFORM_NOW_ACTS, classify_chat_act_with_confidence


_LITERAL_ACK_PATTERNS = (
    "bạn cho phép tôi",
    "Vâng, bạn đã cho phép",
    "Tôi sẽ làm phiền một cách hữu ích",
    "Tôi hiểu rằng bạn cho phép",
)


@dataclass(slots=True)
class PragmaticInterceptResult:
    act: ChatAct
    confidence: float
    intercepted: bool
    reason: str = ""
    state_changed: bool = False
    event_type: str = ""
    response_mode: str = "normal"
    max_words: int = 48
    requested_intensity: str = "light"
    forbidden_patterns: tuple[str, ...] = ()
    preferred_shapes: tuple[str, ...] = ()
    permission_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def perform_now(self) -> bool:
        return self.act in PERFORM_NOW_ACTS

    def to_prompt_context(self) -> str:
        if not self.intercepted:
            return ""
        forbidden = " | ".join(self.forbidden_patterns) or "none"
        shapes = " | ".join(self.preferred_shapes) or "natural reply"
        active = bool(self.permission_snapshot.get("active_now", self.permission_snapshot.get("active", False)))
        return (
            "SOCIAL POLICY ENVELOPE (runtime policy, wording still belongs to Qwen):\n"
            f"social_act={self.act.value}; confidence={self.confidence:.2f};\n"
            f"response_mode={self.response_mode}; max_words={self.max_words}; "
            f"requested_intensity={self.requested_intensity};\n"
            f"permission_active={'yes' if active else 'no'}; "
            f"permission_type={self.permission_snapshot.get('permission_type', 'none')}; "
            f"scope={self.permission_snapshot.get('scope', 'current_session')}; "
            f"intensity_cap={self.permission_snapshot.get('intensity_cap', 'light')};\n"
            f"forbidden_surface_patterns={forbidden};\n"
            f"preferred_response_shapes={shapes};\n"
            "For perform_not_acknowledge: execute one short social move now. Do not paraphrase the user's permission. "
            "For boundary/revoke: respect it immediately and do not sneak in one last tease."
        )

    def event_payload(self, *, user_text: str, source_turn_id: str = "") -> dict[str, Any]:
        return {
            "event_type": self.event_type or self.act.value,
            "social_act": self.act.value,
            "confidence": round(float(self.confidence), 4),
            "utterance": str(user_text or ""),
            "source_turn_id": str(source_turn_id or ""),
            "state_changed": bool(self.state_changed),
            "permission": dict(self.permission_snapshot),
        }


def _response_shape_for_act(act: ChatAct) -> tuple[str, int, tuple[str, ...], tuple[str, ...]]:
    if act in PERFORM_NOW_ACTS:
        return (
            "perform_not_acknowledge",
            18,
            _LITERAL_ACK_PATTERNS,
            ("one-line playful jab", "light challenge", "warm teasing observation"),
        )
    if act == ChatAct.GRANT_RELATIONAL_PERMISSION:
        return (
            "accept_permission_briefly",
            20,
            ("Tôi đã ghi nhận quyền này", "Quyền đã được lưu"),
            ("brief natural acceptance", "small playful proof without overdoing it"),
        )
    if act == ChatAct.REVOKE_RELATIONAL_PERMISSION:
        return (
            "respect_boundary_now",
            18,
            ("nhưng cho tôi trêu nốt", "lần cuối thôi"),
            ("brief acknowledgement", "calm boundary compliance"),
        )
    if act == ChatAct.META_SOCIAL_BOUNDARY:
        return (
            "negotiate_boundary_not_perform",
            36,
            (),
            ("clarify scope", "clarify intensity", "offer an easy revoke path"),
        )
    return "normal", 48, (), ()


def intercept_social_turn(
    user_text: str,
    *,
    history: Iterable[str] = (),
    state: RelationalPermissionState,
    source_turn_id: str = "",
    session_id: str = "",
    now: float | None = None,
    ttl_seconds: float = 1200.0,
    mutate_state: bool = True,
) -> PragmaticInterceptResult:
    # Shadow/dark rollout phải chạy được toàn bộ policy mà không làm bẩn state
    # thật. Dùng bản sao nhỏ vì object chỉ chứa scalar/tuple/dict; không mang
    # socket hay lock như những sinh vật kiến trúc kém may mắn khác.
    working_state = state if mutate_state else deepcopy(state)
    act, confidence = classify_chat_act_with_confidence(user_text, history=history, state=working_state, now=now)
    intercepted = act in {
        ChatAct.PLAYFUL_INTERACTION_REQUEST,
        ChatAct.TEASE_REQUEST,
        ChatAct.INITIATE_INTERACTION,
        ChatAct.GRANT_RELATIONAL_PERMISSION,
        ChatAct.REVOKE_RELATIONAL_PERMISSION,
        ChatAct.META_SOCIAL_BOUNDARY,
    }
    response_mode, max_words, forbidden, shapes = _response_shape_for_act(act)
    requested_intensity = infer_intensity_cap(user_text, default="light")
    state_changed = False
    event_type = ""
    reason = "non_social_turn"

    if act == ChatAct.GRANT_RELATIONAL_PERMISSION:
        working_state.grant(
            permission_type=infer_permission_type(user_text, act),
            scope="current_session",
            intensity_cap=requested_intensity,
            autonomous_bypass=True,
            source_turn_id=source_turn_id,
            session_id=session_id,
            now=now,
            ttl_seconds=ttl_seconds,
            bypass_uses=1,
            notes={"origin": "explicit_grant"},
        )
        state_changed = True
        event_type = "permission_granted"
        reason = "explicit_relational_permission"

    elif act == ChatAct.INITIATE_INTERACTION and not working_state.is_active(now=now):
        # "Chủ động đi" tự nó đã là một grant. Scope vẫn là session và chỉ một bypass.
        working_state.grant(
            permission_type=infer_permission_type(user_text, act),
            scope="current_session",
            intensity_cap=requested_intensity,
            autonomous_bypass=True,
            source_turn_id=source_turn_id,
            session_id=session_id,
            now=now,
            ttl_seconds=ttl_seconds,
            bypass_uses=1,
            notes={"origin": "initiate_interaction_request"},
        )
        state_changed = True
        event_type = "permission_granted_by_initiation"
        reason = "initiation_implies_session_permission"

    elif act == ChatAct.REVOKE_RELATIONAL_PERMISSION:
        working_state.revoke(reason="explicit_revoke", now=now)
        state_changed = True
        event_type = "permission_revoked"
        reason = "explicit_relational_revoke"

    elif act in PERFORM_NOW_ACTS:
        event_type = "social_move_requested"
        reason = "performative_social_request"

    elif act == ChatAct.META_SOCIAL_BOUNDARY:
        event_type = "social_boundary_negotiation"
        reason = "meta_social_boundary"

    return PragmaticInterceptResult(
        act=act,
        confidence=confidence,
        intercepted=intercepted,
        reason=reason,
        state_changed=state_changed,
        event_type=event_type,
        response_mode=response_mode,
        max_words=max_words,
        requested_intensity=requested_intensity,
        forbidden_patterns=forbidden,
        preferred_shapes=shapes,
        permission_snapshot=working_state.to_dict(now=now),
    )


def looks_like_literal_permission_paraphrase(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    markers = (
        "bạn cho phép tôi",
        "bạn đã cho phép",
        "tôi hiểu rằng bạn cho phép",
        "tôi sẽ làm phiền một cách hữu ích",
        "bạn cho phép tôi",
        "bạn đã cho phép",
    )
    return any(marker in normalized for marker in markers)


def deterministic_social_fallback(act: ChatAct) -> str:
    """Lưới cuối khi model lặp lại permission và reroll cũng hỏng."""

    if act == ChatAct.TEASE_REQUEST:
        return "Tự tin thế mà vẫn phải gọi tôi tới cà khịa hộ à?"
    if act == ChatAct.INITIATE_INTERACTION:
        return "Ngồi yên được có một lát mà bạn đã gọi tôi tới phá nhịp rồi."
    if act == ChatAct.PLAYFUL_INTERACTION_REQUEST:
        return "bạn tự mở cửa cho rắc rối rồi còn ngồi nghiêm túc thế kia à?"
    return ""


__all__ = [
    "PragmaticInterceptResult",
    "deterministic_social_fallback",
    "intercept_social_turn",
    "looks_like_literal_permission_paraphrase",
]
