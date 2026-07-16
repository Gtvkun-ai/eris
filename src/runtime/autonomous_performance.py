# -*- coding: utf-8 -*-
"""autonomous_performance.py - biến một câu autonomous thành một màn diễn nhỏ.

Một câu có sân khấu không đồng nghĩa thêm "haha" vào đầu. Nó cần opening hold,
điểm rơi, breath group và closing settle. Module này tạo contract nhịp trung
tính để TTS/UI/body hiện tại dùng được, đồng thời avatar 3D sau này có thể map
``gaze_intent``/``head_intent``/``gesture_intent`` mà không biết Live2D là ai.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping


_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


@dataclass(frozen=True, slots=True)
class PerformanceBeat:
    beat_index: int
    kind: str
    text: str = ""
    start_after_ms: int = 0
    duration_ms: int = 0
    pause_after_ms: int = 0
    tts_style: str = ""
    emotion: str = ""
    motion_intent: str = ""
    gaze_intent: str = ""
    head_intent: str = ""
    gesture_intent: str = ""
    actions: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = list(self.actions)
        return payload


@dataclass(frozen=True, slots=True)
class AutonomousPerformanceAct:
    act_id: str
    opportunity_id: str
    opportunity_kind: str
    scene_mode: str
    intent: str
    session_phase: str
    cadence: str
    stage_preset_id: str
    performance_lane: str
    gesture_density: str
    body_first: bool
    audience_feedback_mode: str
    intrusion_pressure: float
    show_arc_id: str
    show_arc_family: str
    show_arc_stage: str
    show_format_id: str
    show_format_family: str
    show_format_variant: int
    stage_energy: float
    line_shape: str
    opening_mode: str
    closing_mode: str
    beats: tuple[PerformanceBeat, ...]
    total_budget_ms: int
    cooldown_ms: int
    opening_hold_ms: int
    closing_hold_ms: int
    director_note: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "act_id": self.act_id,
            "opportunity_id": self.opportunity_id,
            "opportunity_kind": self.opportunity_kind,
            "scene_mode": self.scene_mode,
            "intent": self.intent,
            "session_phase": self.session_phase,
            "cadence": self.cadence,
            "stage_preset_id": self.stage_preset_id,
            "performance_lane": self.performance_lane,
            "gesture_density": self.gesture_density,
            "body_first": self.body_first,
            "audience_feedback_mode": self.audience_feedback_mode,
            "intrusion_pressure": self.intrusion_pressure,
            "show_arc_id": self.show_arc_id,
            "show_arc_family": self.show_arc_family,
            "show_arc_stage": self.show_arc_stage,
            "show_format_id": self.show_format_id,
            "show_format_family": self.show_format_family,
            "show_format_variant": self.show_format_variant,
            "stage_energy": self.stage_energy,
            "line_shape": self.line_shape,
            "opening_mode": self.opening_mode,
            "closing_mode": self.closing_mode,
            "beats": [beat.to_payload() for beat in self.beats],
            "total_budget_ms": self.total_budget_ms,
            "cooldown_ms": self.cooldown_ms,
            "opening_hold_ms": self.opening_hold_ms,
            "closing_hold_ms": self.closing_hold_ms,
            "director_note": self.director_note,
        }

    @property
    def speech_beats(self) -> tuple[PerformanceBeat, ...]:
        return tuple(beat for beat in self.beats if beat.kind == "speech" and beat.text)


@dataclass(frozen=True, slots=True)
class ScheduledBeat:
    at_ms: int
    beat: PerformanceBeat

    def to_payload(self) -> dict[str, Any]:
        return {"at_ms": self.at_ms, "beat": self.beat.to_payload()}


class AutonomousPerformancePlanner:
    """Art-direct rule-based; LLM chỉ viết nội dung, stage giữ quyền về nhịp."""

    def plan(
        self,
        text: str,
        *,
        autonomous_plan: Mapping[str, Any] | None = None,
        performance_context: Mapping[str, Any] | None = None,
        emotion: str = "neutral",
        motion: str = "none",
        tts_style: str = "neutral",
    ) -> AutonomousPerformanceAct | None:
        line = _clean(text)
        plan = autonomous_plan if isinstance(autonomous_plan, Mapping) else {}
        permit = plan.get("permit") if isinstance(plan.get("permit"), Mapping) else {}
        opportunity = plan.get("selected_opportunity") if isinstance(plan.get("selected_opportunity"), Mapping) else {}
        scene = plan.get("scene") if isinstance(plan.get("scene"), Mapping) else {}
        directive = plan.get("session_directive") if isinstance(plan.get("session_directive"), Mapping) else {}
        show_arc = plan.get("show_arc_directive") if isinstance(plan.get("show_arc_directive"), Mapping) else {}
        show_format = plan.get("show_format") if isinstance(plan.get("show_format"), Mapping) else {}
        stage_preset = plan.get("stage_preset") if isinstance(plan.get("stage_preset"), Mapping) else {}
        audience_feedback = plan.get("audience_feedback") if isinstance(plan.get("audience_feedback"), Mapping) else {}
        perf = performance_context if isinstance(performance_context, Mapping) else {}

        if not plan or not bool(permit.get("allowed", False)) or not line:
            return None

        kind = str(opportunity.get("kind", "autonomous") or "autonomous")
        scene_mode = str(scene.get("name", opportunity.get("scene_mode", "private_idle")) or "private_idle")
        intent = str(perf.get("performance_intent", opportunity.get("suggested_intent", "micro_presence")) or "micro_presence")
        delivery = str(perf.get("delivery_style", "") or "")
        style = str(perf.get("tts_style", tts_style) or tts_style or "neutral")
        stage_emotion = str(perf.get("stage_emotion", emotion) or emotion or "neutral")
        stage_motion = str(perf.get("stage_motion", motion) or motion or "none")

        session_phase = str(directive.get("phase", "settled") or "settled")
        cadence = str(directive.get("cadence", "balanced") or "balanced")
        stage_preset_id = str(stage_preset.get("preset_id", "legacy.default") or "legacy.default")
        performance_lane = str(stage_preset.get("performance_lane", "default") or "default")
        gesture_density = str(stage_preset.get("gesture_density", "low") or "low")
        body_first = bool(stage_preset.get("body_first", True))
        audience_feedback_mode = str(audience_feedback.get("mode", "normal") or "normal")
        try:
            intrusion_pressure = max(0.0, min(1.0, float(audience_feedback.get("intrusion_pressure", 0.0) or 0.0)))
        except (TypeError, ValueError):
            intrusion_pressure = 0.0
        if audience_feedback_mode == "recovery":
            gesture_density = "minimal"
            body_first = True
        show_arc_id = str(show_arc.get("arc_id", "") or "")
        show_arc_family = str(show_arc.get("arc_family", "standalone") or "standalone")
        show_arc_stage = str(show_arc.get("arc_stage", "setup") or "setup")
        show_format_id = str(show_format.get("format_id", "micro_reaction") or "micro_reaction")
        show_format_family = str(show_format.get("family", "reaction") or "reaction")
        try:
            show_format_variant = max(1, int(show_format.get("variant", 1) or 1))
        except (TypeError, ValueError):
            show_format_variant = 1
        try:
            stage_energy = max(0.0, min(1.0, float(show_format.get("stage_energy", 0.32) or 0.32)))
        except (TypeError, ValueError):
            stage_energy = 0.32
        line_shape = str(show_arc.get("line_shape", "single_strike") or "single_strike")
        opening_mode = str(show_format.get("opening_mode") or show_arc.get("opening_mode", "scene_set") or "scene_set")
        closing_mode = str(show_format.get("closing_mode") or show_arc.get("closing_mode", "neutral_settle") or "neutral_settle")
        try:
            hold_bias = int(directive.get("opening_hold_bias_ms", 0) or 0)
            hold_bias += int(stage_preset.get("opening_hold_bias_ms", 0) or 0)
        except (TypeError, ValueError):
            hold_bias = 0
        opening_hold = max(40, min(460, self._opening_hold(
            kind=kind, delivery=delivery, scene=scene_mode, opening_mode=opening_mode
        ) + hold_bias))
        if audience_feedback_mode == "recovery":
            opening_hold = min(opening_hold, 90)
        elif audience_feedback_mode == "low_intrusion":
            opening_hold = min(opening_hold, 130)
        closing_hold = self._closing_hold(kind=kind, closing_mode=closing_mode)
        if audience_feedback_mode == "recovery":
            closing_hold = min(closing_hold, 300)
        try:
            closing_hold = max(closing_hold, int(stage_preset.get("closing_hold_min_ms", 0) or 0))
        except (TypeError, ValueError):
            pass
        if cadence == "sparse":
            closing_hold = max(closing_hold, 500)
        elif cadence == "restrained":
            closing_hold = max(closing_hold, 360)
        sentence_parts = self._split_line(line)
        try:
            max_beats = max(1, min(3, int(show_format.get("max_beats", 2) or 2)))
        except (TypeError, ValueError):
            max_beats = 2
        if len(sentence_parts) > max_beats:
            sentence_parts = (*sentence_parts[: max_beats - 1], " ".join(sentence_parts[max_beats - 1:]).strip())
        # Variant lặp hạ cử chỉ; energy cao mới cho phép nâng density một nấc.
        if show_format_variant >= 2 and gesture_density in {"medium", "high"}:
            gesture_density = "low"
        elif stage_energy >= 0.70 and gesture_density == "low":
            gesture_density = "medium"
        speech_beats: list[PerformanceBeat] = []
        for idx, part in enumerate(sentence_parts):
            pause = self._pause_after(
                part, index=idx, count=len(sentence_parts), kind=kind,
                line_shape=line_shape, arc_stage=show_arc_stage,
            )
            speech_beats.append(
                PerformanceBeat(
                    beat_index=idx + 1,
                    kind="speech",
                    text=part,
                    start_after_ms=0,
                    duration_ms=self._estimate_duration_ms(part),
                    pause_after_ms=pause,
                    tts_style=style,
                    emotion=stage_emotion,
                    motion_intent=stage_motion if idx == 0 else "hold_pose",
                    gaze_intent=self._gaze_for(delivery, kind, show_arc_stage),
                    head_intent=self._head_for(stage_motion),
                    gesture_intent=self._gesture_for(line_shape, show_arc_stage, idx, gesture_density),
                    actions=(),
                )
            )

        beats: list[PerformanceBeat] = [
            PerformanceBeat(
                beat_index=0,
                kind="opening_hold",
                duration_ms=opening_hold,
                emotion=stage_emotion,
                motion_intent=stage_motion,
                gaze_intent=self._gaze_for(delivery, kind, show_arc_stage),
                head_intent=self._head_for(stage_motion),
            ),
            *speech_beats,
            PerformanceBeat(
                beat_index=len(speech_beats) + 1,
                kind="closing_settle",
                duration_ms=closing_hold,
                emotion="settle",
                motion_intent="settle",
                gaze_intent="soft_attention" if closing_mode == "soft_return" else "scene_focus",
                head_intent="neutral_small",
                gesture_intent=(
                    "small_release"
                    if closing_mode == "clean_release" and gesture_density != "minimal"
                    else "none"
                ),
            ),
        ]
        total = opening_hold + closing_hold + sum(item.duration_ms + item.pause_after_ms for item in speech_beats)
        cooldown = int(permit.get("cooldown_after_ms", 24_000) or 24_000)
        note = (
            f"Autonomous stage act ({session_phase}/{cadence}; preset={stage_preset_id}; "
            f"lane={performance_lane}; feedback={audience_feedback_mode}; "
            f"arc={show_arc_family}/{show_arc_stage}; format={show_format_id}/v{show_format_variant}; "
            f"energy={stage_energy:.2f}; shape={line_shape}). "
            f"Hold {opening_hold}ms before the first word. "
            f"Deliver {len(speech_beats)} deliberate speech beat(s); keep pauses short and intentional. "
            "Do not add filler, laughter, or stage directions that are not present in the text."
        )
        return AutonomousPerformanceAct(
            act_id=f"act_{uuid.uuid4().hex[:12]}",
            opportunity_id=str(opportunity.get("opportunity_id", "") or ""),
            opportunity_kind=kind,
            scene_mode=scene_mode,
            intent=intent,
            session_phase=session_phase,
            cadence=cadence,
            stage_preset_id=stage_preset_id,
            performance_lane=performance_lane,
            gesture_density=gesture_density,
            body_first=body_first,
            audience_feedback_mode=audience_feedback_mode,
            intrusion_pressure=intrusion_pressure,
            show_arc_id=show_arc_id,
            show_arc_family=show_arc_family,
            show_arc_stage=show_arc_stage,
            show_format_id=show_format_id,
            show_format_family=show_format_family,
            show_format_variant=show_format_variant,
            stage_energy=stage_energy,
            line_shape=line_shape,
            opening_mode=opening_mode,
            closing_mode=closing_mode,
            beats=tuple(beats),
            total_budget_ms=total,
            cooldown_ms=cooldown,
            opening_hold_ms=opening_hold,
            closing_hold_ms=closing_hold,
            director_note=note,
        )

    @staticmethod
    def _split_line(text: str) -> tuple[str, ...]:
        parts = tuple(part.strip() for part in _SENTENCE_RE.split(text) if part.strip())
        if len(parts) <= 1:
            # Dấu chấm phẩy và hai chấm có thể là điểm rơi tốt, nhưng chỉ tách
            # khi hai vế đủ dài. TTS đọc mẩu 2 từ riêng nghe như mạng lag.
            semicolon = [part.strip() for part in re.split(r"(?<=[;:])\s+", text) if part.strip()]
            if len(semicolon) > 1 and all(len(part) >= 10 for part in semicolon):
                parts = tuple(semicolon)
        return parts or (text,)

    @staticmethod
    def _opening_hold(*, kind: str, delivery: str, scene: str, opening_mode: str) -> int:
        mode_values = {
            "quick_focus": 60,
            "release_hold": 120,
            "recognition_hold": 190,
            "ambient_hold": 205,
            "reentry_hold": 145,
            "scene_set": 110,
        }
        if opening_mode in mode_values:
            return mode_values[opening_mode]
        if kind == "new_error":
            return 70
        if "dry" in delivery or kind == "dead_air":
            return 170
        if scene == "coding_partner":
            return 90
        if kind == "return_after_idle":
            return 130
        return 110

    @staticmethod
    def _closing_hold(*, kind: str, closing_mode: str) -> int:
        mode_values = {
            "clean_release": 460,
            "soft_return": 410,
            "focused_hold": 280,
            "linger_short": 500,
            "neutral_settle": 300,
        }
        return mode_values.get(closing_mode, 420 if kind in {"dead_air", "return_after_idle"} else 300)

    @staticmethod
    def _pause_after(
        text: str, *, index: int, count: int, kind: str, line_shape: str, arc_stage: str
    ) -> int:
        if index >= count - 1:
            return 0
        if line_shape in {"setup_payoff", "technical_two_step"}:
            return 220 if arc_stage == "payoff" else 180
        if line_shape == "quiet_callback":
            return 205
        if text.endswith(("?", "!")):
            return 210
        if kind in {"dead_air", "scene_transition"}:
            return 190
        return 150

    @staticmethod
    def _estimate_duration_ms(text: str) -> int:
        words = max(1, len(text.split()))
        return max(420, min(4_000, 260 + words * 255))

    @staticmethod
    def _gaze_for(delivery: str, kind: str, arc_stage: str = "setup") -> str:
        if arc_stage == "payoff":
            return "scene_focus_then_release"
        if arc_stage == "callback":
            return "recognition_then_return"
        if "dry" in delivery:
            return "look_aside_then_return"
        if kind == "new_error":
            return "scene_focus"
        return "soft_attention"

    @staticmethod
    def _gesture_for(line_shape: str, arc_stage: str, index: int, density: str = "low") -> str:
        if index > 0:
            return "none"
        density = str(density or "low").lower()
        # Preset minimal giữ body yên để không phá focus. Payoff vẫn được quyền
        # có một release nhỏ nếu scene cho gesture, thay vì mọi câu đều vẫy tay
        # như nhân viên quảng cáo đứng trước siêu thị.
        if density == "minimal":
            return "none"
        if arc_stage == "payoff":
            return "small_release"
        if arc_stage == "escalation" and density in {"medium", "high"}:
            return "micro_emphasis"
        if line_shape == "technical_two_step" and density in {"medium", "high"}:
            return "point_small"
        if line_shape == "observation_turn":
            return "open_small" if density in {"medium", "high"} else "none"
        return "none"

    @staticmethod
    def _head_for(motion: str) -> str:
        if "tilt" in motion:
            return "tilt_small"
        if motion in {"blink_slow", "look_away", "look_down"}:
            return "still_small"
        return "neutral_small"


class BeatScheduler:
    """Biến act thành timeline tuyệt đối; không tự sleep và không sở hữu TTS."""

    def schedule(self, act: AutonomousPerformanceAct, *, started_at_ms: int | None = None) -> tuple[ScheduledBeat, ...]:
        cursor = int(started_at_ms if started_at_ms is not None else time.time() * 1000)
        scheduled: list[ScheduledBeat] = []
        for beat in act.beats:
            cursor += max(0, int(beat.start_after_ms or 0))
            scheduled.append(ScheduledBeat(at_ms=cursor, beat=beat))
            cursor += max(0, int(beat.duration_ms or 0)) + max(0, int(beat.pause_after_ms or 0))
        return tuple(scheduled)


__all__ = [
    "AutonomousPerformanceAct",
    "AutonomousPerformancePlanner",
    "BeatScheduler",
    "PerformanceBeat",
    "ScheduledBeat",
]
