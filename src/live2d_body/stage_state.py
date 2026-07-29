# -*- coding: utf-8 -*-
"""Biến event sân khấu Eris thành parameter Live2D liên tục.

Model hiện chưa có ``exp3``/``motion3``, vì vậy biểu cảm được phối trực tiếp từ
parameter đã rig. Profile này ưu tiên chuyển động nhỏ, bất đối xứng vừa đủ và
đúng miền giá trị riêng của model INFJ.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .parameter_profile import INFJ_PARAMETER_PROFILE


@dataclass(frozen=True, slots=True)
class Live2DSnapshot:
    emotion: str
    motion: str
    speaking: bool
    parameters: Mapping[str, float]
    eye_open_left: float = 1.0
    eye_open_right: float = 1.0
    last_event_type: str = ""


@dataclass(frozen=True, slots=True)
class ExpressionTarget:
    mouth_form: float = 0.0
    brow_left: float = 0.0
    brow_right: float = 0.0
    angle_x: float = 0.0
    angle_z: float = 0.0
    eye_open_left: float = 1.0
    eye_open_right: float = 1.0

    def parameters(self) -> dict[str, float]:
        return {
            "ParamMouthForm": self.mouth_form,
            "ParamBrowLAngle": self.brow_left,
            "ParamBrowRAngle": self.brow_right,
            "ParamAngleX": self.angle_x,
            "ParamAngleZ": self.angle_z,
        }


# Theo semantics model: brow dương mang sắc thái nhướng/đặt câu hỏi, không phải
# mặc định của nụ cười. Vì vậy các mood ấm giữ mày quanh 0 hoặc hơi thấp; chỉ
# curious/tease/surprise mới nhướng rõ.
_EMOTION_TARGETS: dict[str, ExpressionTarget] = {
    "neutral": ExpressionTarget(),
    "flat_calm": ExpressionTarget(
        mouth_form=-0.04,
        brow_left=-0.08,
        brow_right=-0.07,
        eye_open_left=0.96,
        eye_open_right=0.96,
    ),
    "warm_soft": ExpressionTarget(
        mouth_form=0.30,
        brow_left=-0.04,
        brow_right=-0.03,
        angle_x=0.8,
        angle_z=0.8,
        eye_open_left=0.94,
        eye_open_right=0.95,
    ),
    "soft_near": ExpressionTarget(
        mouth_form=0.24,
        brow_left=-0.07,
        brow_right=-0.05,
        angle_x=1.4,
        angle_z=1.3,
        eye_open_left=0.91,
        eye_open_right=0.93,
    ),
    "dry_tease": ExpressionTarget(
        mouth_form=0.16,
        brow_left=0.34,
        brow_right=-0.08,
        angle_x=-2.8,
        angle_z=-1.5,
        eye_open_left=0.90,
        eye_open_right=0.96,
    ),
    "mischief_soft": ExpressionTarget(
        mouth_form=0.38,
        brow_left=0.28,
        brow_right=-0.10,
        angle_x=-3.8,
        angle_z=-1.8,
        eye_open_left=0.88,
        eye_open_right=0.95,
    ),
    "curious": ExpressionTarget(
        mouth_form=0.05,
        brow_left=0.42,
        brow_right=0.16,
        angle_x=2.0,
        angle_z=2.7,
        eye_open_left=1.0,
        eye_open_right=1.0,
    ),
    "focused": ExpressionTarget(
        mouth_form=-0.10,
        brow_left=-0.22,
        brow_right=-0.20,
        angle_x=-1.8,
        angle_z=0.4,
        eye_open_left=0.88,
        eye_open_right=0.88,
    ),
    "thinking": ExpressionTarget(
        mouth_form=-0.02,
        brow_left=0.24,
        brow_right=-0.12,
        angle_x=-4.6,
        angle_z=2.2,
        eye_open_left=0.91,
        eye_open_right=0.96,
    ),
    "annoyed_soft": ExpressionTarget(
        mouth_form=-0.32,
        brow_left=-0.34,
        brow_right=-0.27,
        angle_x=-3.8,
        angle_z=-1.0,
        eye_open_left=0.80,
        eye_open_right=0.84,
    ),
    "quiet_low": ExpressionTarget(
        mouth_form=-0.20,
        brow_left=-0.18,
        brow_right=-0.16,
        angle_x=-2.0,
        angle_z=0.7,
        eye_open_left=0.84,
        eye_open_right=0.86,
    ),
    "distant": ExpressionTarget(
        mouth_form=-0.18,
        brow_left=-0.14,
        brow_right=-0.13,
        angle_x=-6.5,
        angle_z=1.1,
        eye_open_left=0.79,
        eye_open_right=0.81,
    ),
    "surprise": ExpressionTarget(
        mouth_form=0.04,
        brow_left=0.56,
        brow_right=0.54,
        eye_open_left=1.0,
        eye_open_right=1.0,
    ),
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
    "read": {"ParamAngleX": -1.8, "ParamAngleZ": 1.6},
    "thinking_small": {"ParamAngleX": -1.8, "ParamAngleZ": 2.2},
    "tilt_head": {"ParamAngleZ": 2.6},
    "look_aside": {"ParamAngleX": -4.8},
    "look_away": {"ParamAngleX": -5.5},
    "look_down": {"ParamAngleX": -2.8, "ParamAngleZ": 0.6},
    "lean_in_small": {"ParamAngleX": 1.8, "ParamAngleZ": 0.8},
    "sad": {"ParamAngleX": -2.2, "ParamAngleZ": 0.8},
    "stand": {},
    "idle": {},
}

_PARAMETER_RESPONSE = {
    "ParamMouthOpenY": 18.0,
    "ParamMouthForm": 7.5,
    "ParamBrowLAngle": 6.5,
    "ParamBrowRAngle": 6.5,
    "ParamAngleX": 5.2,
    "ParamAngleZ": 5.0,
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
        neutral = _EMOTION_TARGETS["neutral"]
        self._current: dict[str, float] = neutral.parameters()
        self._current["ParamMouthOpenY"] = INFJ_PARAMETER_PROFILE.mouth_closed
        self._eye_open_left = neutral.eye_open_left
        self._eye_open_right = neutral.eye_open_right

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
        return normalized if normalized in _EMOTION_TARGETS else "neutral"

    def advance(self, dt: float, *, now: float | None = None) -> Live2DSnapshot:
        """Tiến state một frame và trả parameter đã làm mượt."""
        timestamp = time.monotonic() if now is None else float(now)
        dt = max(0.0, min(0.1, float(dt)))
        with self._lock:
            expression = _EMOTION_TARGETS.get(self._emotion, _EMOTION_TARGETS["neutral"])
            target = expression.parameters()
            for key, value in _MOTION_OFFSETS.get(self._motion, {}).items():
                target[key] = target.get(key, 0.0) + value

            # Một lượng chuyển động rất nhỏ giúp model không đứng như ảnh CCCD,
            # nhưng biên độ đủ thấp để physics tóc không rung liên tục.
            idle_weight = 0.0 if self._motion not in {"stand", "idle"} else 1.0
            target["ParamAngleX"] += idle_weight * 0.18 * math.sin(timestamp * 0.43)
            target["ParamAngleZ"] += idle_weight * 0.22 * math.sin(timestamp * 0.31 + 1.2)

            if self._speaking:
                fast = math.sin(timestamp * 16.7)
                detail = math.sin(timestamp * 29.3 + 0.8)
                open_ratio = 0.16 + 0.55 * (fast * fast) + 0.13 * (detail * detail)
                mouth_open = INFJ_PARAMETER_PROFILE.mouth_open_from_ratio(min(0.90, open_ratio))
                # Khi mở miệng, giảm nhẹ form để khóe miệng không bị kéo quá tay.
                target["ParamMouthForm"] *= 0.78
            elif self._emotion == "surprise" and timestamp - self._last_event_at < 0.8:
                mouth_open = INFJ_PARAMETER_PROFILE.mouth_open_from_ratio(0.58)
            else:
                mouth_open = INFJ_PARAMETER_PROFILE.mouth_closed
            target["ParamMouthOpenY"] = mouth_open

            keys = set(self._current) | set(target)
            for key in keys:
                response = _PARAMETER_RESPONSE.get(key, 7.0)
                blend = 1.0 - math.exp(-response * dt) if dt > 0.0 else 1.0
                current = self._current.get(key, 0.0)
                desired = INFJ_PARAMETER_PROFILE.sanitize(key, target.get(key, 0.0))
                self._current[key] = current + (desired - current) * blend

            eye_blend = 1.0 - math.exp(-7.0 * dt) if dt > 0.0 else 1.0
            self._eye_open_left += (expression.eye_open_left - self._eye_open_left) * eye_blend
            self._eye_open_right += (expression.eye_open_right - self._eye_open_right) * eye_blend

            return Live2DSnapshot(
                emotion=self._emotion,
                motion=self._motion,
                speaking=self._speaking,
                parameters=dict(self._current),
                eye_open_left=INFJ_PARAMETER_PROFILE.clamp_eye_open(self._eye_open_left),
                eye_open_right=INFJ_PARAMETER_PROFILE.clamp_eye_open(self._eye_open_right),
                last_event_type=self._last_event_type,
            )
