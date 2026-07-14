# -*- coding: utf-8 -*-
"""stage_protocol.py — hợp đồng event mỏng giữa backend và frontend.

Tầng này không biết TTS, không biết LLM, cũng không biết Godot/Live2D. Nó chỉ
định nghĩa các message "sân khấu" ổn định để frontend/backend không phải đoán
ý nhau qua payload text cũ.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping


STAGE_PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class StageProtocolEvent:
    """Một event outbound gửi từ runtime ra sân khấu/frontend."""

    type: str
    turn_id: str = ""
    seq: int = 0
    display_text: str = ""
    tts_text: str = ""
    emotion: str = ""
    motion: str = ""
    interruptible: bool = True
    reason: str = ""
    source: str = ""
    timestamp: float = 0.0
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "protocol": "eris.stage",
            "version": STAGE_PROTOCOL_VERSION,
            "type": str(self.type or ""),
            "turn_id": str(self.turn_id or ""),
            "seq": int(self.seq),
            "timestamp": float(self.timestamp or time.time()),
            "interruptible": bool(self.interruptible),
        }
        optional = {
            "display_text": self.display_text,
            "tts_text": self.tts_text,
            "emotion": self.emotion,
            "motion": self.motion,
            "reason": self.reason,
            "source": self.source,
        }
        for key, value in optional.items():
            if value not in ("", None):
                payload[key] = value
        if self.data:
            payload["data"] = dict(self.data)
        return payload


@dataclass(frozen=True, slots=True)
class StageInboundEvent:
    """Một event inbound từ frontend/sân khấu gửi về runtime."""

    type: str
    turn_id: str = ""
    seq: int = 0
    reason: str = ""
    message: str = ""
    timestamp: float = 0.0
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StageInboundEvent":
        try:
            seq = int(payload.get("seq", payload.get("segment_id", 0)) or 0)
        except (TypeError, ValueError):
            seq = 0
        try:
            timestamp = float(payload.get("timestamp") or time.time())
        except (TypeError, ValueError):
            timestamp = time.time()
        return cls(
            type=str(payload.get("type", "") or ""),
            turn_id=str(payload.get("turn_id", "") or ""),
            seq=seq,
            reason=str(payload.get("reason", "") or ""),
            message=str(payload.get("message", payload.get("text", "")) or ""),
            timestamp=timestamp,
            data=dict(payload.get("data") or {}) if isinstance(payload.get("data"), Mapping) else {},
        )

    def to_meta(self) -> dict[str, Any]:
        meta = {
            "type": self.type,
            "turn_id": self.turn_id,
            "seq": self.seq,
            "reason": self.reason,
            "message": self.message,
            "timestamp": self.timestamp,
        }
        if self.data:
            meta["data"] = dict(self.data)
        return meta


def is_stage_inbound_type(event_type: str) -> bool:
    return str(event_type or "") in {
        "interrupt",
        "avatar_ready",
        "audio_playback_started",
        "audio_playback_done",
        "stage_ack",
    }


__all__ = [
    "STAGE_PROTOCOL_VERSION",
    "StageInboundEvent",
    "StageProtocolEvent",
    "is_stage_inbound_type",
]
