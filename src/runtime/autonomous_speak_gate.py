# -*- coding: utf-8 -*-
"""autonomous_speak_gate.py - van quyền nói cho autonomous performer.

WakeGovernor trả lời "có đáng thức không". SpeakGate trả lời câu khó chịu hơn:
"dù đã thức, có đáng chen vào không?". Hai câu hỏi này không được nhập làm một;
nếu không silence debt sẽ dần biến thành giấy phép nói nhảm theo lịch.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_scene_runtime import SceneRuntimeState


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _tuple_value(obj: Any, name: str) -> tuple[str, ...]:
    value = _get(obj, name, ()) or ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item or "") for item in value if str(item or "").strip())
    return ()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))


@dataclass(frozen=True, slots=True)
class SpeakPermit:
    allowed: bool
    mode: str
    max_words: int
    max_duration_ms: int
    reason: str
    cooldown_after_ms: int
    confidence: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SpeakGateConfig:
    startup_quiet_ms: int = 12_000
    min_gap_ms: int = 18_000
    max_lines_per_hour: int = 12
    max_same_kind_streak: int = 2

    @classmethod
    def from_env(cls) -> "SpeakGateConfig":
        def env_int(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, str(default)).strip())
            except (TypeError, ValueError):
                return default

        return cls(
            startup_quiet_ms=max(0, env_int("ERIS_AUTONOMOUS_STARTUP_QUIET_MS", 12_000)),
            min_gap_ms=max(3_000, env_int("ERIS_AUTONOMOUS_MIN_SPEECH_GAP_MS", 18_000)),
            max_lines_per_hour=max(1, env_int("ERIS_AUTONOMOUS_MAX_LINES_PER_HOUR", 12)),
            max_same_kind_streak=max(1, env_int("ERIS_AUTONOMOUS_MAX_SAME_KIND_STREAK", 2)),
        )


class AutonomousSpeakPermissionGate:
    """Giữ lịch sử phát biểu ngắn hạn và cấp permit có budget cụ thể."""

    def __init__(self, config: SpeakGateConfig | None = None, *, started_at_ms: int | None = None) -> None:
        self.config = config or SpeakGateConfig.from_env()
        self.started_at_ms = int(started_at_ms if started_at_ms is not None else _now_ms())
        self.last_performance_at_ms = 0
        self.last_kind = ""
        self.same_kind_streak = 0
        self._spoken_history_ms: deque[int] = deque(maxlen=64)

    def evaluate(
        self,
        opportunity: AutonomousOpportunity | None,
        *,
        scene: SceneRuntimeState,
        user_context: Any = None,
        wake_decision: Any = None,
        stage_preset: Any = None,
        now_ms: int | None = None,
    ) -> SpeakPermit:
        now = int(now_ms if now_ms is not None else _now_ms())
        if opportunity is None:
            return self._deny("suppress", "no_opportunity")
        if now >= opportunity.expires_at_ms:
            return self._deny("suppress", "opportunity_expired")

        allowed_kinds = set(_tuple_value(stage_preset, "allowed_opportunity_kinds"))
        if allowed_kinds and opportunity.kind not in allowed_kinds:
            emergency = opportunity.kind == "new_error" and opportunity.urgency >= 0.90
            if not emergency:
                return self._deny("body_only", "stage_preset_prefers_body_only", confidence=0.94)

        since_boot = now - self.started_at_ms
        startup_quiet_ms = int(_get(stage_preset, "startup_quiet_ms", self.config.startup_quiet_ms) or 0)
        if since_boot < max(0, startup_quiet_ms) and opportunity.kind not in {"new_error", "return_after_idle"}:
            return self._deny("body_only", "startup_presence_before_speech", confidence=0.92)

        if scene.user_typing:
            return self._deny("body_only", "user_is_typing", confidence=0.96)

        interrupt_cost = _clamp01(_get(user_context, "interrupt_cost", _get(wake_decision, "interrupt_cost", 0.0)))
        busy_score = _clamp01(_get(user_context, "busy_score", 0.0))
        if interrupt_cost >= 0.70 or busy_score >= 0.82:
            if opportunity.kind == "new_error" and opportunity.urgency >= 0.82:
                pass
            else:
                return self._deny("body_only", "focus_interrupt_cost_high", confidence=max(interrupt_cost, busy_score))

        if self.last_performance_at_ms:
            gap = now - self.last_performance_at_ms
            required_gap = max(
                self.config.min_gap_ms,
                int(_get(stage_preset, "min_gap_ms", 0) or 0),
            )
            if opportunity.kind == "dead_air":
                required_gap = max(required_gap, 35_000)
            if gap < required_gap and opportunity.kind not in {"new_error", "return_after_idle"}:
                return self._deny("body_only", "global_speech_cooldown", confidence=0.88)

        cutoff = now - 3_600_000
        while self._spoken_history_ms and self._spoken_history_ms[0] < cutoff:
            self._spoken_history_ms.popleft()
        preset_hourly_limit = int(_get(stage_preset, "max_lines_per_hour", self.config.max_lines_per_hour) or self.config.max_lines_per_hour)
        hourly_limit = max(1, min(self.config.max_lines_per_hour, preset_hourly_limit))
        if len(self._spoken_history_ms) >= hourly_limit:
            return self._deny("body_only", "hourly_speech_budget_exhausted", confidence=0.98)

        if self.same_kind_streak >= self.config.max_same_kind_streak and opportunity.kind == self.last_kind:
            return self._deny("body_only", "same_opportunity_streak", confidence=0.90)

        preset_threshold = _clamp01(_get(stage_preset, "min_opportunity_strength", 0.46), 0.46)
        threshold = max(0.46, preset_threshold)
        if opportunity.kind in {"return_after_idle", "task_progress"}:
            threshold = max(0.40, threshold - 0.08)
        if opportunity.strength < threshold:
            return self._deny("body_only", "opportunity_too_weak_for_stage_preset", confidence=0.80)

        # Không có preset thì giữ compatibility cũ. Khi preset tồn tại, chính
        # playbook scene quyết định high_salience game/media có đáng thành lời hay
        # không; tránh hard-code hai tầng cùng tranh quyền đạo diễn.
        if stage_preset is None and scene.name in {"game_companion", "media_companion"} and opportunity.kind not in {"new_error", "return_after_idle"}:
            return self._deny("body_only", "scene_prefers_silent_presence", confidence=0.84)

        if opportunity.kind == "dead_air":
            return self._cap_with_preset(SpeakPermit(
                allowed=True,
                mode="short_reply",
                max_words=10,
                max_duration_ms=1_800,
                reason="dead_air_micro_line",
                cooldown_after_ms=40_000,
                confidence=0.72,
            ), stage_preset)
        if opportunity.kind in {"scene_transition", "return_after_idle", "task_progress"}:
            return self._cap_with_preset(SpeakPermit(
                allowed=True,
                mode="short_reply",
                max_words=14,
                max_duration_ms=2_400,
                reason=f"{opportunity.kind}_short_act",
                cooldown_after_ms=24_000,
                confidence=0.80,
            ), stage_preset)
        if opportunity.kind == "new_error":
            mode = "full_line" if opportunity.strength >= 0.82 else "short_reply"
            return self._cap_with_preset(SpeakPermit(
                allowed=True,
                mode=mode,
                max_words=18 if mode == "full_line" else 13,
                max_duration_ms=3_000,
                reason="new_error_has_actionable_value",
                cooldown_after_ms=22_000,
                confidence=max(0.78, opportunity.strength),
            ), stage_preset)
        return self._cap_with_preset(SpeakPermit(
            allowed=True,
            mode="short_reply",
            max_words=12,
            max_duration_ms=2_200,
            reason="autonomous_opportunity_allowed",
            cooldown_after_ms=28_000,
            confidence=0.70,
        ), stage_preset)

    @staticmethod
    def _cap_with_preset(permit: SpeakPermit, stage_preset: Any) -> SpeakPermit:
        if stage_preset is None or not permit.allowed:
            return permit
        try:
            max_words = max(1, min(permit.max_words, int(_get(stage_preset, "max_words", permit.max_words) or permit.max_words)))
            max_duration = max(500, min(permit.max_duration_ms, int(_get(stage_preset, "max_duration_ms", permit.max_duration_ms) or permit.max_duration_ms)))
            preset_gap = max(0, int(_get(stage_preset, "min_gap_ms", 0) or 0))
        except (TypeError, ValueError):
            return permit
        return SpeakPermit(
            allowed=permit.allowed,
            mode=permit.mode,
            max_words=max_words,
            max_duration_ms=max_duration,
            reason=f"{permit.reason}|preset={str(_get(stage_preset, 'preset_id', '') or 'scene')}",
            cooldown_after_ms=max(permit.cooldown_after_ms, preset_gap),
            confidence=permit.confidence,
        )

    def record_spoken(self, *, kind: str, at_ms: int | None = None) -> None:
        """Chỉ gọi sau khi output public thật sự được commit."""
        now = int(at_ms if at_ms is not None else _now_ms())
        self.last_performance_at_ms = now
        self._spoken_history_ms.append(now)
        if kind and kind == self.last_kind:
            self.same_kind_streak += 1
        else:
            self.last_kind = str(kind or "")
            self.same_kind_streak = 1 if kind else 0

    @staticmethod
    def _deny(mode: str, reason: str, *, confidence: float = 0.75) -> SpeakPermit:
        return SpeakPermit(
            allowed=False,
            mode=mode,
            max_words=0,
            max_duration_ms=0,
            reason=reason,
            cooldown_after_ms=0,
            confidence=confidence,
        )


__all__ = [
    "AutonomousSpeakPermissionGate",
    "SpeakGateConfig",
    "SpeakPermit",
]
