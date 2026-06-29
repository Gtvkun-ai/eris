# -*- coding: utf-8 -*-
"""stage_protocol_adapter.py — đổi object runtime hiện có thành event sân khấu.

Adapter này giữ protocol mới là lớp mỏng: không ép TTS trả audio bytes, không
đổi payload legacy, chỉ chuẩn hóa các mốc frontend cần nghe.
"""

from __future__ import annotations

from typing import Any

from runtime.stage_protocol import StageProtocolEvent


_AUDIO_EVENT_MAP = {
    "audio_prepare": "stage_segment_prepare",
    "audio_queued": "stage_segment_queued",
    "audio_buffer_ready": "tts_audio_ready",
    "audio_start": "audio_playback_started",
    "audio_done": "audio_playback_done",
    "audio_cancelled": "stage_segment_cancelled",
    "audio_failed": "stage_segment_failed",
    "emotion_change": "stage_state",
}


def stage_segment_event(stage_frame: Any, *, segment_count: int = 1) -> StageProtocolEvent:
    """Dựng event `stage_segment` từ StageFrame.

    `display_text` là thứ UI nên hiện; `tts_text` để frontend debug/sync nếu cần,
    không phải bắt buộc dùng làm audio.
    """

    data = {
        "segment_count": int(segment_count),
        "actions": list(tuple(getattr(stage_frame, "actions", ()) or ())),
        "prosody_style": str(getattr(stage_frame, "prosody_style", "") or ""),
        "delivery": dict(getattr(stage_frame, "delivery", {}) or {}),
        "memory_text": str(getattr(stage_frame, "memory_text", "") or ""),
    }
    return StageProtocolEvent(
        type="stage_segment",
        turn_id=str(getattr(stage_frame, "turn_id", "") or ""),
        seq=_seq(stage_frame),
        display_text=str(getattr(stage_frame, "display_text", "") or ""),
        tts_text=str(getattr(stage_frame, "tts_text", "") or ""),
        emotion=str(getattr(stage_frame, "emotion", "") or ""),
        motion=str(getattr(stage_frame, "motion", "") or ""),
        interruptible=bool(getattr(stage_frame, "interruptible", True)),
        source=str(getattr(stage_frame, "source", "") or ""),
        data={key: value for key, value in data.items() if value not in ("", [], {}, None)},
    )


def playback_event(event: Any, *, stage_frame: Any = None) -> StageProtocolEvent:
    """Dựng event protocol từ lifecycle event của TTS."""

    legacy_type = str(getattr(event, "type", "") or "")
    protocol_type = _AUDIO_EVENT_MAP.get(legacy_type, legacy_type or "stage_event")
    frame = stage_frame
    data = {
        "legacy_type": legacy_type,
        "segment_id": _event_seq(event, frame),
        "prosody_style": str(getattr(event, "prosody_style", "") or getattr(frame, "prosody_style", "") or ""),
        "error": str(getattr(event, "error", "") or ""),
        "turn_segments": list(tuple(getattr(event, "turn_segments", ()) or ())),
    }
    return StageProtocolEvent(
        type=protocol_type,
        turn_id=str(getattr(event, "turn_id", "") or getattr(frame, "turn_id", "") or ""),
        seq=_event_seq(event, frame),
        display_text=str(getattr(frame, "display_text", "") or ""),
        tts_text=str(getattr(event, "text", "") or getattr(frame, "tts_text", "") or ""),
        emotion=str(getattr(event, "emotion", "") or getattr(frame, "emotion", "") or ""),
        motion=str(getattr(event, "motion", "") or getattr(frame, "motion", "") or ""),
        interruptible=bool(getattr(frame, "interruptible", True)),
        reason=str(getattr(event, "reason", "") or ""),
        source=str(getattr(frame, "source", "") or ""),
        data={key: value for key, value in data.items() if value not in ("", [], {}, None)},
    )


def stage_state_event(*, event_type: str, reason: str = "", data: dict[str, Any] | None = None) -> StageProtocolEvent:
    return StageProtocolEvent(
        type=event_type,
        reason=reason,
        data=dict(data or {}),
    )


def _seq(stage_frame: Any) -> int:
    try:
        return int(getattr(stage_frame, "segment_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _event_seq(event: Any, stage_frame: Any) -> int:
    try:
        return int(getattr(event, "segment_id", getattr(stage_frame, "segment_id", 0)) or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["playback_event", "stage_segment_event", "stage_state_event"]
