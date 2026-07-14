from __future__ import annotations

"""Ephemeral relational permission state cho ERIS.

Permission kiểu "được phép trêu/làm phiền" là state điều khiển hành vi, không phải
semantic fact bền. File này giữ TTL, scope, intensity cap và bypass budget; nó
không tự ghi file và không tự nói ra ngoài.
"""

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.social_act import ChatAct, normalize_vi_ascii


_INTENSITY_ORDER = {"none": 0, "light": 1, "medium": 2}


@dataclass(slots=True)
class RelationalPermissionState:
    active: bool = False
    permission_type: str = "none"
    scope: str = "current_session"
    intensity_cap: str = "light"
    autonomous_bypass: bool = False

    source_turn_id: str | None = None
    session_id: str | None = None
    granted_at: float = 0.0
    expires_at: float = 0.0

    bypass_uses_remaining: int = 0
    revoke_conditions: tuple[str, ...] = (
        "explicit_revoke",
        "session_end",
        "ttl_expired",
        "relationship_repair",
    )
    safety_constraints: tuple[str, ...] = (
        "no_harassment",
        "no_sensitive_topic_teasing",
        "respect_immediate_stop",
    )
    last_event: str = ""
    notes: dict[str, Any] = field(default_factory=dict)

    def is_active(self, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        if not self.active:
            return False
        if self.expires_at <= 0.0 or current >= self.expires_at:
            self.expire(now=current)
            return False
        return True

    def grant(
        self,
        *,
        permission_type: str,
        scope: str = "current_session",
        intensity_cap: str = "light",
        autonomous_bypass: bool = False,
        source_turn_id: str | None = None,
        session_id: str | None = None,
        now: float | None = None,
        ttl_seconds: float = 1200.0,
        bypass_uses: int = 1,
        notes: dict[str, Any] | None = None,
    ) -> "RelationalPermissionState":
        current = time.time() if now is None else float(now)
        cap = intensity_cap if intensity_cap in _INTENSITY_ORDER else "light"
        self.active = True
        self.permission_type = str(permission_type or "allow_playful_intrusion")
        self.scope = str(scope or "current_session")
        self.intensity_cap = cap
        self.autonomous_bypass = bool(autonomous_bypass)
        self.source_turn_id = str(source_turn_id) if source_turn_id else None
        self.session_id = str(session_id) if session_id else self.session_id
        self.granted_at = current
        self.expires_at = current + max(5.0, float(ttl_seconds))
        self.bypass_uses_remaining = max(0, int(bypass_uses)) if autonomous_bypass else 0
        self.last_event = "granted"
        self.notes = dict(notes or {})
        return self

    def revoke(self, *, reason: str = "explicit_revoke", now: float | None = None) -> "RelationalPermissionState":
        current = time.time() if now is None else float(now)
        self.active = False
        self.autonomous_bypass = False
        self.bypass_uses_remaining = 0
        self.expires_at = current
        self.last_event = f"revoked:{reason}"
        self.notes = {**dict(self.notes or {}), "revoke_reason": str(reason or "explicit_revoke")}
        return self

    def expire(self, *, now: float | None = None) -> "RelationalPermissionState":
        current = time.time() if now is None else float(now)
        self.active = False
        self.autonomous_bypass = False
        self.bypass_uses_remaining = 0
        self.expires_at = current
        self.last_event = "expired"
        return self

    def allows_intensity(self, requested: str) -> bool:
        requested_level = _INTENSITY_ORDER.get(str(requested or "light"), 1)
        cap_level = _INTENSITY_ORDER.get(self.intensity_cap, 1)
        return requested_level <= cap_level

    def can_bypass_autonomous(self, *, now: float | None = None, requested_intensity: str = "light") -> bool:
        return bool(
            self.is_active(now=now)
            and self.autonomous_bypass
            and self.bypass_uses_remaining > 0
            and self.allows_intensity(requested_intensity)
        )

    def consume_bypass(self, *, now: float | None = None) -> bool:
        if not self.can_bypass_autonomous(now=now):
            return False
        self.bypass_uses_remaining = max(0, self.bypass_uses_remaining - 1)
        self.last_event = "autonomous_bypass_consumed"
        return True

    def to_dict(self, *, now: float | None = None) -> dict[str, Any]:
        """Serialize state tại cùng mốc thời gian của lượt đang xử lý.

        Nhận ``now`` để test/dark-launch có thể dùng clock giả mà không bị giờ hệ
        thống thật làm state hết hạn oan. Đồng hồ mà tranh quyền với policy thì
        đúng là một loại hài kịch kỹ thuật không ai đặt vé xem.
        """

        payload = asdict(self)
        payload["active_now"] = self.is_active(now=now)
        return payload

    def to_prompt_summary(self, *, now: float | None = None) -> str:
        active = self.is_active(now=now)
        return (
            f"active_permission={'yes' if active else 'no'}; "
            f"permission_type={self.permission_type}; scope={self.scope}; "
            f"intensity_cap={self.intensity_cap}; autonomous_bypass={'yes' if self.autonomous_bypass else 'no'}; "
            f"bypass_uses_remaining={self.bypass_uses_remaining}"
        )


def infer_permission_type(text: str, act: ChatAct | None = None) -> str:
    normalized = normalize_vi_ascii(text)
    if "treu" in normalized or "ca khia" in normalized or "choc" in normalized:
        return "allow_soft_tease"
    if "chu dong" in normalized or "bat chuyen" in normalized:
        return "allow_unprompted_checkin"
    if "lam phien" in normalized:
        return "allow_reengagement"
    if act == ChatAct.INITIATE_INTERACTION:
        return "allow_unprompted_checkin"
    return "allow_playful_intrusion"


def infer_intensity_cap(text: str, *, default: str = "light") -> str:
    normalized = normalize_vi_ascii(text)
    if any(marker in normalized for marker in ("nhe thoi", "nhe", "it thoi", "vua thoi")):
        return "light"
    if any(marker in normalized for marker in ("vua phai", "manh hon", "thoai mai")):
        return "medium"
    # Không tự mở mức cao. Người dùng nói "mạnh" cũng chỉ mở medium cho lane này.
    if "manh" in normalized:
        return "medium"
    return default if default in _INTENSITY_ORDER else "light"


def ensure_relational_permission_state(owner: Any) -> RelationalPermissionState:
    state = getattr(owner, "relational_permission_state", None)
    if not isinstance(state, RelationalPermissionState):
        state = RelationalPermissionState()
        try:
            owner.relational_permission_state = state
        except Exception:
            pass
    return state


__all__ = [
    "RelationalPermissionState",
    "ensure_relational_permission_state",
    "infer_intensity_cap",
    "infer_permission_type",
]
