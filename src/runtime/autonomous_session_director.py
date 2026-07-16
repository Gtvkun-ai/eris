# -*- coding: utf-8 -*-
"""autonomous_session_director.py - đạo diễn nhịp của cả phiên autonomous.

OpportunityDetector nhìn từng sự kiện. SpeakGate giữ quyền nói theo lượt. Module
này giữ thứ mà hai tầng kia không nên tự gánh: nhịp của *cả phiên biểu diễn*.
Nó nhớ Eris vừa nói loại câu nào, mật độ lời trong một giờ, scene đã ổn định bao
lâu và mức mệt của khán giả. Nhờ vậy autonomous không biến thành chiếc đồng hồ
cứ đủ 30 giây lại phát một câu, một thành tựu kỹ thuật khá buồn cười nếu gọi là
"có sân khấu".

Contract vẫn trung tính với avatar. Không có Live2D hotkey, blendshape hay tên
vendor ở đây; chỉ có cadence, phase, budget và body-only bias.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_speak_gate import SpeakPermit


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))


@dataclass(slots=True)
class AutonomousSessionConfig:
    """Ngưỡng cadence có thể đổi bằng env, không cần sửa code giữa hai preset."""

    opening_phase_ms: int = 24_000
    focus_phase_after_ms: int = 8 * 60_000
    fatigue_soft_lines_per_hour: int = 7
    fatigue_hard_lines_per_hour: int = 12
    repeated_kind_penalty: float = 0.15
    minimum_opportunity_score: float = 0.34
    history_size: int = 8

    @classmethod
    def from_env(cls) -> "AutonomousSessionConfig":
        def env_int(name: str, default: int) -> int:
            try:
                return int(str(os.environ.get(name, default)).strip())
            except (TypeError, ValueError):
                return default

        def env_float(name: str, default: float) -> float:
            try:
                return float(str(os.environ.get(name, default)).strip())
            except (TypeError, ValueError):
                return default

        soft = max(1, env_int("ERIS_AUTONOMOUS_FATIGUE_SOFT_LINES_HOUR", 7))
        hard = max(soft + 1, env_int("ERIS_AUTONOMOUS_FATIGUE_HARD_LINES_HOUR", 12))
        return cls(
            opening_phase_ms=max(0, env_int("ERIS_AUTONOMOUS_OPENING_PHASE_MS", 24_000)),
            focus_phase_after_ms=max(30_000, env_int("ERIS_AUTONOMOUS_FOCUS_PHASE_AFTER_MS", 8 * 60_000)),
            fatigue_soft_lines_per_hour=soft,
            fatigue_hard_lines_per_hour=hard,
            repeated_kind_penalty=max(0.0, min(0.45, env_float("ERIS_AUTONOMOUS_REPEAT_KIND_PENALTY", 0.15))),
            minimum_opportunity_score=max(0.0, min(1.0, env_float("ERIS_AUTONOMOUS_MIN_OPPORTUNITY_SCORE", 0.34))),
            history_size=max(3, min(24, env_int("ERIS_AUTONOMOUS_SESSION_HISTORY_SIZE", 8))),
        )


@dataclass(frozen=True, slots=True)
class SessionDirective:
    """Chỉ thị nhịp gửi xuống gate và stage planner."""

    phase: str
    cadence: str
    selected_opportunity_id: str
    selected_kind: str
    selected_score: float
    audience_fatigue: float
    speech_density: float
    body_only_bias: float
    max_words_cap: int
    cooldown_multiplier: float
    opening_hold_bias_ms: int
    preferred_intent: str
    lines_last_hour: int
    recent_kinds: tuple[str, ...]
    reason: str

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["recent_kinds"] = list(self.recent_kinds)
        return payload


class AutonomousSessionDirector:
    """Giữ cadence xuyên nhiều tick và chọn opportunity phù hợp nhất cho phiên."""

    def __init__(self, config: AutonomousSessionConfig | None = None, *, started_at_ms: int | None = None) -> None:
        self.config = config or AutonomousSessionConfig.from_env()
        self.started_at_ms = int(started_at_ms if started_at_ms is not None else _now_ms())
        self.current_scene = ""
        self.scene_entered_at_ms = self.started_at_ms
        self.last_act_at_ms = 0
        self._spoken_history_ms: deque[int] = deque(maxlen=96)
        self._recent_kinds: deque[str] = deque(maxlen=self.config.history_size)
        self._recent_intents: deque[str] = deque(maxlen=self.config.history_size)
        self._recent_hooks: deque[str] = deque(maxlen=self.config.history_size)

    def direct(
        self,
        *,
        scene: SceneRuntimeState,
        opportunities: Iterable[AutonomousOpportunity],
        now_ms: int | None = None,
    ) -> SessionDirective:
        now = int(now_ms if now_ms is not None else _now_ms())
        self._refresh_scene(scene, now)
        self._prune_hour(now)

        lines = len(self._spoken_history_ms)
        fatigue = self._fatigue(lines)
        density = _clamp01(lines / max(1.0, float(self.config.fatigue_soft_lines_per_hour)))
        phase = self._phase(scene, now)
        ranked: list[tuple[float, AutonomousOpportunity, str]] = []
        for opportunity in tuple(opportunities):
            score, why = self._score(opportunity, scene=scene, phase=phase, fatigue=fatigue, now=now)
            ranked.append((score, opportunity, why))
        ranked.sort(key=lambda item: item[0], reverse=True)

        selected: AutonomousOpportunity | None = None
        selected_score = 0.0
        selected_why = "no_opportunity"
        if ranked and ranked[0][0] >= self.config.minimum_opportunity_score:
            selected_score, selected, selected_why = ranked[0]

        same_kind_count = 0
        selected_kind = str(getattr(selected, "kind", "") or "")
        if selected_kind:
            same_kind_count = sum(1 for kind in self._recent_kinds if kind == selected_kind)

        body_only_bias = fatigue * 0.82 + min(0.28, same_kind_count * 0.10)
        if phase == "arrival":
            body_only_bias += 0.28
        if scene.user_typing:
            body_only_bias = 1.0
        if scene.name in {"game_companion", "media_companion"}:
            body_only_bias += 0.24
        if selected_kind in {"new_error", "return_after_idle"}:
            body_only_bias -= 0.18
        body_only_bias = _clamp01(body_only_bias)

        cadence = self._cadence(phase=phase, fatigue=fatigue, scene=scene)
        max_words_cap = self._max_words_cap(phase=phase, scene=scene, fatigue=fatigue)
        cooldown_multiplier = 1.0 + fatigue * 1.25 + min(0.50, same_kind_count * 0.18)
        if scene.name in {"game_companion", "media_companion"}:
            cooldown_multiplier += 0.35
        opening_hold_bias_ms = self._opening_hold_bias(phase=phase, scene=scene, selected_kind=selected_kind)
        preferred_intent = str(getattr(selected, "suggested_intent", "") or "")

        reason = (
            f"phase={phase};cadence={cadence};selected={selected_kind or 'none'};"
            f"score={selected_score:.3f};fatigue={fatigue:.3f};{selected_why}"
        )
        return SessionDirective(
            phase=phase,
            cadence=cadence,
            selected_opportunity_id=str(getattr(selected, "opportunity_id", "") or ""),
            selected_kind=selected_kind,
            selected_score=max(0.0, min(1.0, selected_score)),
            audience_fatigue=fatigue,
            speech_density=density,
            body_only_bias=body_only_bias,
            max_words_cap=max_words_cap,
            cooldown_multiplier=max(1.0, cooldown_multiplier),
            opening_hold_bias_ms=opening_hold_bias_ms,
            preferred_intent=preferred_intent,
            lines_last_hour=lines,
            recent_kinds=tuple(self._recent_kinds),
            reason=reason,
        )

    def apply_to_permit(
        self,
        permit: SpeakPermit,
        directive: SessionDirective,
        *,
        opportunity: AutonomousOpportunity | None,
    ) -> SpeakPermit:
        """Siết budget của permit; không tự nâng một permit đã bị từ chối."""
        if not permit.allowed:
            return permit
        kind = str(getattr(opportunity, "kind", "") or "")
        urgent_exception = kind == "new_error" and float(getattr(opportunity, "urgency", 0.0) or 0.0) >= 0.82
        if directive.body_only_bias >= 0.80 and not urgent_exception:
            return SpeakPermit(
                allowed=False,
                mode="body_only",
                max_words=0,
                max_duration_ms=0,
                reason="session_director_body_only_bias",
                cooldown_after_ms=0,
                confidence=max(permit.confidence, directive.body_only_bias),
            )

        words = max(1, min(int(permit.max_words), int(directive.max_words_cap)))
        duration_ratio = words / max(1.0, float(permit.max_words or words))
        duration_ms = max(650, int(float(permit.max_duration_ms) * max(0.55, duration_ratio)))
        cooldown_ms = max(permit.cooldown_after_ms, int(permit.cooldown_after_ms * directive.cooldown_multiplier))
        return SpeakPermit(
            allowed=True,
            mode=permit.mode,
            max_words=words,
            max_duration_ms=duration_ms,
            reason=f"{permit.reason}|session:{directive.phase}/{directive.cadence}",
            cooldown_after_ms=cooldown_ms,
            confidence=max(permit.confidence, 1.0 - directive.audience_fatigue * 0.35),
        )

    def record_spoken(
        self,
        *,
        kind: str,
        intent: str = "",
        hook_id: str = "",
        at_ms: int | None = None,
    ) -> None:
        now = int(at_ms if at_ms is not None else _now_ms())
        self.last_act_at_ms = now
        self._spoken_history_ms.append(now)
        if kind:
            self._recent_kinds.append(str(kind))
        if intent:
            self._recent_intents.append(str(intent))
        if hook_id:
            self._recent_hooks.append(str(hook_id))

    def snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        now = int(now_ms if now_ms is not None else _now_ms())
        self._prune_hour(now)
        return {
            "started_at_ms": self.started_at_ms,
            "current_scene": self.current_scene,
            "scene_entered_at_ms": self.scene_entered_at_ms,
            "last_act_at_ms": self.last_act_at_ms,
            "lines_last_hour": len(self._spoken_history_ms),
            "audience_fatigue": self._fatigue(len(self._spoken_history_ms)),
            "recent_kinds": list(self._recent_kinds),
            "recent_intents": list(self._recent_intents),
            "recent_hooks": list(self._recent_hooks),
        }

    def _refresh_scene(self, scene: SceneRuntimeState, now: int) -> None:
        name = str(scene.name or "private_idle")
        if name != self.current_scene:
            self.current_scene = name
            self.scene_entered_at_ms = now

    def _prune_hour(self, now: int) -> None:
        cutoff = now - 3_600_000
        while self._spoken_history_ms and self._spoken_history_ms[0] < cutoff:
            self._spoken_history_ms.popleft()

    def _fatigue(self, lines: int) -> float:
        soft = self.config.fatigue_soft_lines_per_hour
        hard = self.config.fatigue_hard_lines_per_hour
        if lines <= soft:
            return _clamp01((lines / max(1, soft)) * 0.28)
        return _clamp01(0.28 + (lines - soft) / max(1, hard - soft) * 0.72)

    def _phase(self, scene: SceneRuntimeState, now: int) -> str:
        if now - self.started_at_ms < self.config.opening_phase_ms:
            return "arrival"
        if scene.name == "private_idle":
            return "idle_presence"
        if scene.name in {"coding_partner", "study_session"} and scene.stable_for_ms >= self.config.focus_phase_after_ms:
            return "deep_focus"
        if scene.name in {"game_companion", "media_companion"}:
            return "spectator"
        return "settled"

    def _score(
        self,
        opportunity: AutonomousOpportunity,
        *,
        scene: SceneRuntimeState,
        phase: str,
        fatigue: float,
        now: int,
    ) -> tuple[float, str]:
        score = opportunity.strength * 0.54 + opportunity.urgency * 0.20 + opportunity.novelty * 0.26
        reasons = ["base"]
        kind = opportunity.kind

        if kind == "new_error" and scene.name == "coding_partner":
            score += 0.14
            reasons.append("coding_error_boost")
        if kind == "task_progress" and scene.name in {"coding_partner", "study_session"}:
            score += 0.10
            reasons.append("progress_scene_fit")
        if kind == "dead_air":
            if scene.name == "private_idle":
                score += 0.07
                reasons.append("idle_dead_air_fit")
            elif phase in {"deep_focus", "spectator"}:
                score -= 0.16
                reasons.append("dead_air_focus_penalty")
        if kind == "scene_transition" and scene.stable_for_ms <= 8_000:
            score += 0.08
            reasons.append("fresh_scene_transition")
        if kind == "return_after_idle":
            score += 0.09
            reasons.append("return_presence")

        same_count = sum(1 for recent in self._recent_kinds if recent == kind)
        if same_count:
            score -= min(0.42, same_count * self.config.repeated_kind_penalty)
            reasons.append(f"repeat_penalty_{same_count}")
        if self._recent_kinds and self._recent_kinds[-1] == kind:
            score -= 0.07
            reasons.append("immediate_repeat")

        score -= fatigue * (0.10 if kind == "new_error" else 0.28)
        if phase == "arrival" and kind not in {"new_error", "return_after_idle"}:
            score -= 0.10
            reasons.append("arrival_restraint")
        if now >= opportunity.expires_at_ms:
            score = 0.0
            reasons.append("expired")
        return max(0.0, min(1.0, score)), "+".join(reasons)

    @staticmethod
    def _cadence(*, phase: str, fatigue: float, scene: SceneRuntimeState) -> str:
        if fatigue >= 0.72:
            return "sparse"
        if phase in {"deep_focus", "spectator"}:
            return "restrained"
        if phase == "idle_presence":
            return "ambient"
        if phase == "arrival":
            return "presence_first"
        return "balanced"

    @staticmethod
    def _max_words_cap(*, phase: str, scene: SceneRuntimeState, fatigue: float) -> int:
        cap = {
            "arrival": 9,
            "deep_focus": 12,
            "spectator": 8,
            "idle_presence": 14,
            "settled": 15,
        }.get(phase, 13)
        if scene.name == "coding_partner":
            cap = min(cap, 14)
        if fatigue >= 0.55:
            cap = min(cap, 10)
        return max(6, cap)

    @staticmethod
    def _opening_hold_bias(*, phase: str, scene: SceneRuntimeState, selected_kind: str) -> int:
        if selected_kind == "new_error":
            return -20
        if phase == "arrival":
            return 100
        if phase == "idle_presence":
            return 55
        if phase == "deep_focus":
            return -15
        if scene.name in {"game_companion", "media_companion"}:
            return 80
        return 0


__all__ = [
    "AutonomousSessionConfig",
    "AutonomousSessionDirector",
    "SessionDirective",
]
