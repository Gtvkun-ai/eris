# -*- coding: utf-8 -*-
"""Biến event sân khấu và affect nội tại thành parameter Live2D liên tục.

Model INFJ chưa có ``exp3``/``motion3`` nên biểu cảm được phối trực tiếp từ
parameter đã rig. Có ba lớp độc lập:

1. affect nền từ ``PersistentInternalState`` / private mind;
2. emotion + motion tạm thời của câu đang nói;
3. idle director tạo vi chuyển động có lịch khi im lặng.

Raw chain-of-thought không bao giờ đi vào renderer. Runtime chỉ gửi vector số
đã chuẩn hóa, bởi vì để từng dòng suy luận giật lông mày trực tiếp là một ý
kiến rất con người và rất tệ.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .affect import AffectPose, AffectVector, NEUTRAL_AFFECT
from .idle import IdleDirector
from .parameter_profile import INFJ_PARAMETER_PROFILE


@dataclass(frozen=True, slots=True)
class Live2DSnapshot:
    emotion: str
    motion: str
    speaking: bool
    parameters: Mapping[str, float]
    eye_open_left: float = 1.0
    eye_open_right: float = 1.0
    gaze_bias_x: float = 0.0
    gaze_bias_y: float = 0.0
    affect: Mapping[str, float] | None = None
    affect_source: str = ""
    idle_action: str = "settle"
    explicit_emotion_weight: float = 0.0
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

    @classmethod
    def from_affect_pose(cls, pose: AffectPose) -> "ExpressionTarget":
        return cls(
            mouth_form=pose.mouth_form,
            brow_left=pose.brow_left,
            brow_right=pose.brow_right,
            angle_x=pose.angle_x,
            angle_z=pose.angle_z,
            eye_open_left=pose.eye_open_left,
            eye_open_right=pose.eye_open_right,
        )

    def blend(self, other: "ExpressionTarget", weight: float) -> "ExpressionTarget":
        ratio = max(0.0, min(1.0, float(weight)))
        return ExpressionTarget(
            mouth_form=self.mouth_form + (other.mouth_form - self.mouth_form) * ratio,
            brow_left=self.brow_left + (other.brow_left - self.brow_left) * ratio,
            brow_right=self.brow_right + (other.brow_right - self.brow_right) * ratio,
            angle_x=self.angle_x + (other.angle_x - self.angle_x) * ratio,
            angle_z=self.angle_z + (other.angle_z - self.angle_z) * ratio,
            eye_open_left=self.eye_open_left + (other.eye_open_left - self.eye_open_left) * ratio,
            eye_open_right=self.eye_open_right + (other.eye_open_right - self.eye_open_right) * ratio,
        )


# Brow dương mang sắc thái nhướng/đặt câu hỏi, không phải mặc định của nụ cười.
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


def _clamp01(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


class Live2DStageState:
    """State thread-safe giữa UDP receiver và render loop."""

    def __init__(self, *, idle_seed: int | None = None) -> None:
        self._lock = threading.RLock()
        self._emotion = "neutral"
        self._motion = "stand"
        self._speaking = False
        self._thinking = False
        self._last_event_type = ""
        now = time.monotonic()
        self._last_event_at = now
        self._emotion_at = -1.0e9
        self._motion_at = now

        self._affect_target = NEUTRAL_AFFECT
        self._affect_current = NEUTRAL_AFFECT
        self._affect_last_at = -1.0e9
        self._affect_source = ""
        self._thought_pressure = 0.0
        self._thought_confidence = 0.0
        self._idle = IdleDirector(seed=idle_seed)

        neutral = _EMOTION_TARGETS["neutral"]
        self._current: dict[str, float] = neutral.parameters()
        self._current["ParamMouthOpenY"] = INFJ_PARAMETER_PROFILE.mouth_closed
        self._eye_open_left = neutral.eye_open_left
        self._eye_open_right = neutral.eye_open_right

    def handle_payload(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            return
        protocol = str(payload.get("protocol", "") or "")
        event_type = str(payload.get("type", "") or "").strip().lower()
        with self._lock:
            if protocol == "eris.stage":
                self._handle_stage_event(payload, event_type)
            else:
                self._handle_legacy_payload(payload)
            self._last_event_type = event_type
            self._last_event_at = time.monotonic()

    def _handle_stage_event(self, payload: Mapping[str, Any], event_type: str) -> None:
        if event_type in {"affect_state", "cognitive_affect", "inner_affect"}:
            self._handle_affect_event(payload)
            return

        # Một số frontend gói affect chung trong stage_state. Nhận nhưng không
        # cho nó thay đổi emotion tường minh nếu payload không yêu cầu.
        data = payload.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("affect"), Mapping):
            self._handle_affect_event(payload)

        emotion = str(payload.get("emotion", "") or "").strip().lower()
        motion = str(payload.get("motion", "") or "").strip().lower()
        now = time.monotonic()
        if emotion:
            self._emotion = self._normalize_emotion(emotion)
            self._emotion_at = now
        if motion:
            self._motion = motion
            self._motion_at = now

        if event_type in {"received", "thinking_started", "content_committed", "audio_buffering"}:
            # Content may already be committed while its bubble remains hidden
            # waiting for ElevenLabs. The body keeps the same visible thinking
            # state until playback truly starts.
            self._thinking = True
            self._motion = motion or "thinking_small"
            self._motion_at = now
            if not emotion:
                self._emotion = "thinking"
                self._emotion_at = now
        elif event_type in {"speaking", "audio_playback_started"}:
            self._thinking = False
            self._speaking = True
        elif event_type in {
            "done",
            "degraded",
            "interrupted",
            "audio_playback_done",
            "stage_segment_cancelled",
            "stage_segment_failed",
            "continuation_cancelled",
        }:
            self._thinking = False
            self._speaking = False
            self._motion = motion or "stand"
            self._motion_at = now
        elif event_type == "thinking_finished":
            self._thinking = False
            self._motion = motion or "stand"
            self._motion_at = now

    def _handle_affect_event(self, payload: Mapping[str, Any]) -> None:
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
        assert isinstance(data, Mapping)
        raw_affect = data.get("affect") if isinstance(data.get("affect"), Mapping) else data
        if not isinstance(raw_affect, Mapping):
            return
        self._affect_target = AffectVector.from_mapping(raw_affect, fallback=self._affect_target)
        self._affect_last_at = time.monotonic()
        self._affect_source = str(data.get("source", payload.get("source", "")) or "")[:120]
        self._thought_pressure = max(
            self._thought_pressure * 0.72,
            _clamp01(data.get("thought_pressure", data.get("pressure", 0.0))),
        )
        self._thought_confidence = _clamp01(data.get("confidence", 0.0))
        self._idle.notify_affect(
            now=self._affect_last_at,
            source=self._affect_source,
            thought_pressure=self._thought_pressure,
            confidence=self._thought_confidence,
        )

    def _handle_legacy_payload(self, payload: Mapping[str, Any]) -> None:
        emotion = str(
            payload.get("preset_emotion", payload.get("emotion", "")) or ""
        ).strip().lower()
        motion = str(
            payload.get("stage_motion", payload.get("animation", "")) or ""
        ).strip().lower()
        now = time.monotonic()
        if emotion:
            self._emotion = self._normalize_emotion(emotion)
            self._emotion_at = now
        if motion:
            self._motion = motion
            self._motion_at = now
        if "should_speak" in payload:
            self._speaking = bool(payload.get("should_speak"))
        raw_affect = payload.get("affect")
        if isinstance(raw_affect, Mapping):
            self._handle_affect_event({"data": {"affect": raw_affect, "source": "legacy"}})

    @staticmethod
    def _normalize_emotion(value: str) -> str:
        normalized = _EMOTION_ALIASES.get(value, value)
        return normalized if normalized in _EMOTION_TARGETS else "neutral"

    def advance(self, dt: float, *, now: float | None = None) -> Live2DSnapshot:
        """Tiến state một frame và trả parameter đã làm mượt."""

        timestamp = time.monotonic() if now is None else float(now)
        dt = max(0.0, min(0.1, float(dt)))
        with self._lock:
            affect_blend = 1.0 - math.exp(-1.8 * dt) if dt > 0.0 else 1.0
            self._affect_current = self._affect_current.lerp(self._affect_target, affect_blend)
            self._thought_pressure *= math.exp(-dt / 48.0) if dt > 0.0 else 1.0

            affect_age = max(0.0, timestamp - self._affect_last_at)
            if self._affect_last_at < 0.0:
                freshness = 0.0
            elif affect_age <= 75.0:
                freshness = 1.0
            else:
                freshness = math.exp(-(affect_age - 75.0) / 240.0)
            visual_affect = NEUTRAL_AFFECT.lerp(self._affect_current, freshness)
            affect_pose = visual_affect.visual_pose(thought_pressure=self._thought_pressure)
            affect_target = ExpressionTarget.from_affect_pose(affect_pose)

            emotion_weight = self._explicit_emotion_weight(timestamp)
            expression = _EMOTION_TARGETS.get(self._emotion, _EMOTION_TARGETS["neutral"])
            composed = affect_target.blend(expression, emotion_weight)
            target = composed.parameters()

            motion_weight = self._motion_weight(timestamp)
            for key, value in _MOTION_OFFSETS.get(self._motion, {}).items():
                target[key] = target.get(key, 0.0) + value * motion_weight

            allow_idle_gesture = (
                not self._speaking
                and self._motion in {"stand", "idle"}
                and emotion_weight < 0.72
            )
            idle_active = not self._speaking
            idle_pose = self._idle.advance(
                now=timestamp,
                active=idle_active,
                allow_gesture=allow_idle_gesture,
                affect=visual_affect,
                thought_pressure=self._thought_pressure,
            )
            idle_scale = 0.42 if self._thinking else 1.0
            target["ParamAngleX"] += idle_pose.angle_x * idle_scale
            target["ParamAngleZ"] += idle_pose.angle_z * idle_scale
            target["ParamBrowLAngle"] += idle_pose.brow_left * idle_scale
            target["ParamBrowRAngle"] += idle_pose.brow_right * idle_scale
            target["ParamMouthForm"] += idle_pose.mouth_form * idle_scale

            if self._speaking:
                fast = math.sin(timestamp * 16.7)
                detail = math.sin(timestamp * 29.3 + 0.8)
                open_ratio = 0.16 + 0.55 * (fast * fast) + 0.13 * (detail * detail)
                mouth_open = INFJ_PARAMETER_PROFILE.mouth_open_from_ratio(min(0.90, open_ratio))
                # Khi mở miệng, giảm nhẹ form để khóe miệng không bị kéo quá tay.
                target["ParamMouthForm"] *= 0.78
            elif self._emotion == "surprise" and max(0.0, timestamp - self._emotion_at) < 0.8:
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

            desired_eye_left = composed.eye_open_left * idle_pose.eye_open_left_scale
            desired_eye_right = composed.eye_open_right * idle_pose.eye_open_right_scale
            eye_blend = 1.0 - math.exp(-7.0 * dt) if dt > 0.0 else 1.0
            self._eye_open_left += (desired_eye_left - self._eye_open_left) * eye_blend
            self._eye_open_right += (desired_eye_right - self._eye_open_right) * eye_blend

            visible_emotion = self._emotion if emotion_weight >= 0.22 else visual_affect.dominant_label()
            return Live2DSnapshot(
                emotion=visible_emotion,
                motion=self._motion,
                speaking=self._speaking,
                parameters=dict(self._current),
                eye_open_left=INFJ_PARAMETER_PROFILE.clamp_eye_open(self._eye_open_left),
                eye_open_right=INFJ_PARAMETER_PROFILE.clamp_eye_open(self._eye_open_right),
                gaze_bias_x=INFJ_PARAMETER_PROFILE.clamp_eye_axis(
                    affect_pose.gaze_bias_x + idle_pose.gaze_bias_x * idle_scale
                ),
                gaze_bias_y=INFJ_PARAMETER_PROFILE.clamp_eye_axis(
                    affect_pose.gaze_bias_y + idle_pose.gaze_bias_y * idle_scale
                ),
                affect=visual_affect.to_dict(),
                affect_source=self._affect_source,
                idle_action=idle_pose.action,
                explicit_emotion_weight=emotion_weight,
                last_event_type=self._last_event_type,
            )

    def _explicit_emotion_weight(self, timestamp: float) -> float:
        if self._emotion_at < 0.0:
            return 0.0
        age = max(0.0, timestamp - self._emotion_at)
        if self._speaking:
            return 0.92
        if self._thinking:
            return max(0.58, math.exp(-age / 18.0))
        # Emotion của lời thoại còn dư âm rồi tan dần về affect nền.
        return math.exp(-age / 12.0)

    def _motion_weight(self, timestamp: float) -> float:
        if self._motion in {"stand", "idle"}:
            return 1.0
        if self._thinking and self._motion in {"thinking_small", "read"}:
            return 1.0
        age = max(0.0, timestamp - self._motion_at)
        if self._speaking:
            return 1.0
        return math.exp(-age / 2.8)
