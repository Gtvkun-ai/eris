# -*- coding: utf-8 -*-
"""Biến event sân khấu Eris thành parameter Live2D liên tục.

Model hiện chưa có ``exp3``/``motion3``, nên adapter không giả vờ rằng chúng tồn
tại. Biểu cảm được tạo trực tiếp bằng parameter đã rig: lông mày, mouth form,
AngleX/Z và lip sync. Khi người dùng bổ sung expression/motion, renderer có thể
nâng cấp mà không đổi protocol backend.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Live2DSnapshot:
    emotion: str
    motion: str
    speaking: bool
    parameters: Mapping[str, float]
    last_event_type: str = ""


# Target nhỏ, cố ý không bẻ mặt quá tay. Parameter thực tế sẽ được live2d-py
# clamp theo min/max của model.
_EMOTION_PARAMETERS: dict[str, dict[str, float]] = {
    "neutral": {
        "ParamMouthForm": 0.00,
        "ParamBrowLAngle": 0.00,
        "ParamBrowRAngle": 0.00,
        "ParamAngleX": 0.00,
        "ParamAngleZ": 0.00,
    },
    "flat_calm": {
        "ParamMouthForm": -0.05,
        "ParamBrowLAngle": -0.02,
        "ParamBrowRAngle": -0.02,
        "ParamAngleX": 0.00,
        "ParamAngleZ": 0.00,
    },
    "warm_soft": {
        "ParamMouthForm": 0.35,
        "ParamBrowLAngle": 0.08,
        "ParamBrowRAngle": 0.08,
        "ParamAngleX": 1.0,
        "ParamAngleZ": 1.2,
    },
    "soft_near": {
        "ParamMouthForm": 0.28,
        "ParamBrowLAngle": 0.06,
        "ParamBrowRAngle": 0.06,
        "ParamAngleX": 1.8,
        "ParamAngleZ": 1.8,
    },
    "dry_tease": {
        "ParamMouthForm": 0.22,
        "ParamBrowLAngle": 0.12,
        "ParamBrowRAngle": -0.06,
        "ParamAngleX": -1.2,
        "ParamAngleZ": -1.8,
    },
    "mischief_soft": {
        "ParamMouthForm": 0.42,
        "ParamBrowLAngle": 0.16,
        "ParamBrowRAngle": -0.08,
        "ParamAngleX": -1.8,
        "ParamAngleZ": -2.0,
    },
    "curious": {
        "ParamMouthForm": 0.06,
        "ParamBrowLAngle": 0.20,
        "ParamBrowRAngle": 0.06,
        "ParamAngleX": 2.0,
        "ParamAngleZ": 3.2,
    },
    "focused": {
        "ParamMouthForm": -0.08,
        "ParamBrowLAngle": -0.12,
        "ParamBrowRAngle": -0.12,
        "ParamAngleX": -1.0,
        "ParamAngleZ": 0.6,
    },
    "thinking": {
        "ParamMouthForm": -0.02,
        "ParamBrowLAngle": 0.08,
        "ParamBrowRAngle": -0.10,
        "ParamAngleX": -2.0,
        "ParamAngleZ": 2.6,
    },
    "annoyed_soft": {
        "ParamMouthForm": -0.28,
        "ParamBrowLAngle": -0.30,
        "ParamBrowRAngle": -0.30,
        "ParamAngleX": -2.5,
        "ParamAngleZ": -1.4,
    },
    "quiet_low": {
        "ParamMouthForm": -0.22,
        "ParamBrowLAngle": -0.10,
        "ParamBrowRAngle": -0.10,
        "ParamAngleX": -1.2,
        "ParamAngleZ": 0.8,
    },
    "distant": {
        "ParamMouthForm": -0.20,
        "ParamBrowLAngle": -0.08,
        "ParamBrowRAngle": -0.08,
        "ParamAngleX": -3.2,
        "ParamAngleZ": 1.4,
    },
    "surprise": {
        "ParamMouthForm": 0.08,
        "ParamBrowLAngle": 0.34,
        "ParamBrowRAngle": 0.34,
        "ParamAngleX": 0.0,
        "ParamAngleZ": 0.0,
    },
}

_EMOTION_ALIASES = {
    "soft": "warm_soft",
    "soft_smile": "warm_soft",
    "playful": "mischief_soft",
    "smug": "dry_tease",
    "annoyed": "annoyed_soft",
    "sad": "quiet_low",
    "sad_distant": "distant",
    "thinking_soft": "thinking",
}

_MOTION_OFFSETS: dict[str, dict[str, float]] = {
    "read": {"ParamAngleX": -1.5, "ParamAngleZ": 2.0},
    "thinking_small": {"ParamAngleX": -1.5, "ParamAngleZ": 2.6},
    "tilt_head": {"ParamAngleZ": 3.0},
    "look_aside": {"ParamAngleX": -4.0},
    "look_away": {"ParamAngleX": -4.0},
    "look_down": {"ParamAngleX": -2.5, "ParamAngleZ": 0.8},
    "lean_in_small": {"ParamAngleX": 2.0, "ParamAngleZ": 1.0},
    "sad": {"ParamAngleX": -2.0, "ParamAngleZ": 1.0},
    "stand": {},
    "idle": {},
}


class Live2DStageState:
    """State thread-safe giữa UDP receiver và render loop."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._emotion = "neutral"
        self._motion = "stand"
        self._speaking = False
        self._last_event_type = ""
        self._last_event_at = time.monotonic()
        self._current: dict[str, float] = dict(_EMOTION_PARAMETERS["neutral"])

    def handle_payload(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            return
        protocol = str(payload.get("protocol", "") or "")
        event_type = str(payload.get("type", "") or "")
        with self._lock:
            if protocol == "eris.stage":
                self._handle_stage_event(payload, event_type)
            else:
                self._handle_legacy_payload(payload)
            self._last_event_type = event_type
            self._last_event_at = time.monotonic()

    def _handle_stage_event(self, payload: Mapping[str, Any], event_type: str) -> None:
        emotion = str(payload.get("emotion", "") or "").strip().lower()
        motion = str(payload.get("motion", "") or "").strip().lower()
        if emotion:
            self._emotion = self._normalize_emotion(emotion)
        if motion:
            self._motion = motion

        if event_type == "audio_playback_started":
            self._speaking = True
        elif event_type in {
            "audio_playback_done",
            "stage_segment_cancelled",
            "stage_segment_failed",
            "continuation_cancelled",
        }:
            self._speaking = False
        elif event_type == "thinking_started":
            self._motion = motion or "thinking_small"
        elif event_type == "thinking_finished":
            self._motion = motion or "stand"

    def _handle_legacy_payload(self, payload: Mapping[str, Any]) -> None:
        emotion = str(
            payload.get("preset_emotion", payload.get("emotion", "")) or ""
        ).strip().lower()
        motion = str(
            payload.get("stage_motion", payload.get("animation", "")) or ""
        ).strip().lower()
        if emotion:
            self._emotion = self._normalize_emotion(emotion)
        if motion:
            self._motion = motion
        if "should_speak" in payload:
            self._speaking = bool(payload.get("should_speak"))

    @staticmethod
    def _normalize_emotion(value: str) -> str:
        normalized = _EMOTION_ALIASES.get(value, value)
        return normalized if normalized in _EMOTION_PARAMETERS else "neutral"

    def advance(self, dt: float, *, now: float | None = None) -> Live2DSnapshot:
        """Tiến state một frame và trả parameter đã làm mượt."""
        timestamp = time.monotonic() if now is None else float(now)
        dt = max(0.0, min(0.1, float(dt)))
        with self._lock:
            target = dict(_EMOTION_PARAMETERS.get(self._emotion, _EMOTION_PARAMETERS["neutral"]))
            for key, value in _MOTION_OFFSETS.get(self._motion, {}).items():
                target[key] = target.get(key, 0.0) + value

            # Mouth mở theo hai nhịp lệch pha, tránh kiểu sin đều như cá cảnh.
            if self._speaking:
                fast = math.sin(timestamp * 16.7)
                detail = math.sin(timestamp * 29.3 + 0.8)
                mouth_open = 0.10 + 0.42 * (fast * fast) + 0.12 * (detail * detail)
            elif self._emotion == "surprise" and timestamp - self._last_event_at < 0.8:
                mouth_open = 0.28
            else:
                mouth_open = 0.0
            target["ParamMouthOpenY"] = mouth_open

            # Easing theo hàm mũ, không phụ thuộc FPS.
            blend = 1.0 - math.exp(-10.0 * dt) if dt > 0 else 1.0
            keys = set(self._current) | set(target)
            for key in keys:
                current = self._current.get(key, 0.0)
                desired = target.get(key, 0.0)
                self._current[key] = current + (desired - current) * blend

            return Live2DSnapshot(
                emotion=self._emotion,
                motion=self._motion,
                speaking=self._speaking,
                parameters=dict(self._current),
                last_event_type=self._last_event_type,
            )
