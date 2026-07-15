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

        opening_hold = self._opening_hold(kind=kind, delivery=delivery, scene=scene_mode)
        closing_hold = 420 if kind in {"dead_air", "return_after_idle"} else 300
        sentence_parts = self._split_line(line)
        speech_beats: list[PerformanceBeat] = []
        for idx, part in enumerate(sentence_parts):
            pause = self._pause_after(part, index=idx, count=len(sentence_parts), kind=kind)
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
                    gaze_intent=self._gaze_for(delivery, kind),
                    head_intent=self._head_for(stage_motion),
                    gesture_intent="none",
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
                gaze_intent=self._gaze_for(delivery, kind),
                head_intent=self._head_for(stage_motion),
            ),
            *speech_beats,
            PerformanceBeat(
                beat_index=len(speech_beats) + 1,
                kind="closing_settle",
                duration_ms=closing_hold,
                emotion="settle",
                motion_intent="settle",
                gaze_intent="scene_focus",
                head_intent="neutral_small",
            ),
        ]
        total = opening_hold + closing_hold + sum(item.duration_ms + item.pause_after_ms for item in speech_beats)
        cooldown = int(permit.get("cooldown_after_ms", 24_000) or 24_000)
        note = (
            f"Autonomous stage act. Hold {opening_hold}ms before the first word. "
            f"Deliver {len(speech_beats)} deliberate speech beat(s); keep pauses short and intentional. "
            "Do not add filler, laughter, or stage directions that are not present in the text."
        )
        return AutonomousPerformanceAct(
            act_id=f"act_{uuid.uuid4().hex[:12]}",
            opportunity_id=str(opportunity.get("opportunity_id", "") or ""),
            opportunity_kind=kind,
            scene_mode=scene_mode,
            intent=intent,
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
    def _opening_hold(*, kind: str, delivery: str, scene: str) -> int:
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
    def _pause_after(text: str, *, index: int, count: int, kind: str) -> int:
        if index >= count - 1:
            return 0
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
    def _gaze_for(delivery: str, kind: str) -> str:
        if "dry" in delivery:
            return "look_aside_then_return"
        if kind == "new_error":
            return "scene_focus"
        return "soft_attention"

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
