# -*- coding: utf-8 -*-
"""autonomous_opportunity.py - phát hiện lý do đáng để Eris chủ động biểu diễn.

Không gọi LLM ở đây. Một timer đến hạn không phải là lý do nói, nó chỉ là bằng
chứng rằng đồng hồ vẫn còn hoạt động. Detector chỉ phát opportunity khi có biến
đổi scene, lỗi mới, quay lại sau idle, dead-air đủ dài hoặc một mốc công việc có
ý nghĩa.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from runtime.autonomous_scene_runtime import SceneRuntimeState


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))


@dataclass(frozen=True, slots=True)
class AutonomousOpportunity:
    opportunity_id: str
    kind: str
    scene_mode: str
    strength: float
    urgency: float
    novelty: float
    evidence_refs: tuple[str, ...]
    created_at_ms: int
    expires_at_ms: int
    suggested_intent: str
    public_safe: bool = True
    reason: str = ""
    # Phase 7: opportunity có thể được phát hiện trong post-chat grace. Khi đó
    # nó ở trạng thái pending và TTL chỉ tính từ lúc thực sự eligible.
    eligible_after_ms: int = 0
    status: str = "eligible"
    dedupe_key: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(slots=True)
class OpportunityDetectorConfig:
    dead_air_after_ms: int = 24_000
    dead_air_expires_ms: int = 18_000
    return_after_idle_ms: int = 90_000
    long_focus_ms: int = 45 * 60_000
    new_error_threshold: float = 0.66


class AutonomousOpportunityDetector:
    """Detector có cooldown nội bộ để một sự kiện không bị phát lại mỗi tick."""

    _COOLDOWN_MS = {
        "scene_transition": 12_000,
        "new_error": 28_000,
        "return_after_idle": 60_000,
        "dead_air": 45_000,
        "long_focus": 25 * 60_000,
        "task_progress": 25_000,
        "high_salience": 30_000,
    }

    def __init__(self, config: OpportunityDetectorConfig | None = None) -> None:
        self.config = config or OpportunityDetectorConfig()
        self._last_scene_seq = 0
        self._last_idle_ms = 0
        self._last_error_band = 0
        self._last_emitted_ms: dict[str, int] = {}
        self._seen_initial_scene = False

    def detect(
        self,
        *,
        scene: SceneRuntimeState,
        signal_snapshot: Any,
        observer_frame: Any = None,
        signal_diff: Any = None,
        wake_decision: Any = None,
        now_ms: int | None = None,
    ) -> tuple[AutonomousOpportunity, ...]:
        now = int(now_ms if now_ms is not None else _now_ms())
        opportunities: list[AutonomousOpportunity] = []
        idle_ms = max(0, int(float(_get(signal_snapshot, "idle_seconds", 0.0) or 0.0) * 1000))
        possible_error = _clamp01(_get(observer_frame, "possible_error", 0.0))
        novelty = _clamp01(_get(observer_frame, "novelty", _get(signal_diff, "novelty", 0.0)))
        salience = _clamp01(_get(observer_frame, "salience", _get(signal_diff, "diff_score", 0.0)))
        events = " ".join(str(item or "").lower() for item in (_get(signal_snapshot, "recent_events", ()) or ()))

        if not self._seen_initial_scene:
            self._seen_initial_scene = True
            self._last_scene_seq = scene.transition_seq
        elif scene.transition_seq != self._last_scene_seq:
            self._last_scene_seq = scene.transition_seq
            self._append(
                opportunities,
                kind="scene_transition",
                scene=scene,
                strength=0.66 + min(0.20, scene.confidence * 0.15),
                urgency=0.36,
                novelty=max(0.55, novelty),
                evidence=("scene_transition", "active_app"),
                intent="react",
                now=now,
                expires_ms=15_000,
                reason=f"{scene.previous_name}->{scene.name}",
            )

        if self._last_idle_ms >= self.config.return_after_idle_ms and idle_ms <= 5_000:
            self._append(
                opportunities,
                kind="return_after_idle",
                scene=scene,
                strength=0.74,
                urgency=0.48,
                novelty=0.78,
                evidence=("idle_transition", "user_presence"),
                intent="micro_presence",
                now=now,
                expires_ms=12_000,
                reason="user_returned_after_long_idle",
            )

        error_band = 2 if possible_error >= 0.82 else (1 if possible_error >= self.config.new_error_threshold else 0)
        if error_band > self._last_error_band or (error_band > 0 and novelty >= 0.72):
            self._append(
                opportunities,
                kind="new_error",
                scene=scene,
                strength=max(0.72, possible_error),
                urgency=max(0.58, possible_error),
                novelty=max(0.55, novelty),
                evidence=("observer_possible_error", "observer_novelty"),
                intent="technical_help" if scene.name == "coding_partner" else "react",
                now=now,
                expires_ms=20_000,
                reason="observer_detected_new_error_pattern",
            )
        self._last_error_band = error_band

        progress_tokens = (
            "build_success", "build completed", "test_passed", "tests passed", "task_complete",
            "save_complete", "export_complete", "render_complete",
        )
        if any(token in events for token in progress_tokens):
            self._append(
                opportunities,
                kind="task_progress",
                scene=scene,
                strength=0.70,
                urgency=0.32,
                novelty=max(0.60, novelty),
                evidence=("recent_event",),
                intent="react",
                now=now,
                expires_ms=18_000,
                reason="meaningful_progress_event",
            )

        # Dead-air chỉ được coi là cơ hội nhẹ. Gate phía sau vẫn có quyền đổi nó
        # thành body-only nếu user đang tập trung hoặc vừa nghe Eris nói xong.
        if idle_ms >= self.config.dead_air_after_ms and idle_ms < self.config.return_after_idle_ms * 2 and not scene.user_typing:
            strength = 0.48 + min(0.22, (idle_ms - self.config.dead_air_after_ms) / 180_000.0)
            self._append(
                opportunities,
                kind="dead_air",
                scene=scene,
                strength=strength,
                urgency=0.18,
                novelty=max(0.32, novelty),
                evidence=("idle_ms",),
                intent="micro_presence",
                now=now,
                expires_ms=self.config.dead_air_expires_ms,
                reason="silence_ladder_micro_line",
            )

        if scene.stable_for_ms >= self.config.long_focus_ms and idle_ms <= 8_000:
            self._append(
                opportunities,
                kind="long_focus",
                scene=scene,
                strength=0.58,
                urgency=0.20,
                novelty=0.45,
                evidence=("scene_stable_for_ms",),
                intent="micro_presence",
                now=now,
                expires_ms=60_000,
                reason="long_focus_checkpoint",
            )

        # Wake pressure cao nhưng không có loại sự kiện cụ thể vẫn chỉ tạo hook
        # yếu. Nó không được phép lách qua SpeakGate bằng cảm giác mơ hồ.
        speech_value = _clamp01(_get(wake_decision, "speech_value", 0.0))
        if not opportunities and salience >= 0.78 and speech_value >= 0.58:
            self._append(
                opportunities,
                kind="high_salience",
                scene=scene,
                strength=min(0.78, 0.45 * salience + 0.45 * speech_value),
                urgency=0.42,
                novelty=max(0.48, novelty),
                evidence=("observer_salience", "wake_speech_value"),
                intent="react",
                now=now,
                expires_ms=12_000,
                reason="high_salience_without_specific_event",
            )

        self._last_idle_ms = idle_ms
        opportunities.sort(key=lambda item: (item.strength + item.urgency * 0.25 + item.novelty * 0.15), reverse=True)
        return tuple(opportunities)

    def _append(
        self,
        output: list[AutonomousOpportunity],
        *,
        kind: str,
        scene: SceneRuntimeState,
        strength: float,
        urgency: float,
        novelty: float,
        evidence: tuple[str, ...],
        intent: str,
        now: int,
        expires_ms: int,
        reason: str,
    ) -> None:
        last = int(self._last_emitted_ms.get(kind, 0) or 0)
        cooldown = int(self._COOLDOWN_MS.get(kind, 20_000))
        if last and now - last < cooldown:
            return
        self._last_emitted_ms[kind] = now
        output.append(
            AutonomousOpportunity(
                opportunity_id=f"opp_{uuid.uuid4().hex[:12]}",
                kind=kind,
                scene_mode=scene.name,
                strength=_clamp01(strength),
                urgency=_clamp01(urgency),
                novelty=_clamp01(novelty),
                evidence_refs=tuple(dict.fromkeys(evidence)),
                created_at_ms=now,
                expires_at_ms=now + max(1_000, int(expires_ms)),
                suggested_intent=intent,
                public_safe=True,
                reason=reason,
                eligible_after_ms=now,
                status="eligible",
                dedupe_key=f"{kind}:{scene.previous_name}->{scene.name}" if kind == "scene_transition" else kind,
            )
        )


__all__ = [
    "AutonomousOpportunity",
    "AutonomousOpportunityDetector",
    "OpportunityDetectorConfig",
]
