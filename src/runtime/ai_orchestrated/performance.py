# -*- coding: utf-8 -*-
"""Stage act cho self-initiated turn Architecture C.

Planner này chỉ art-direct nhịp từ ``IntentionPlan`` typed. Nó không cần permit,
opportunity, show arc hay scene director legacy. Nội dung/ý nghĩa vẫn thuộc main
model; stage chỉ quyết định hold, beat, gaze và settle sau khi câu đã được duyệt.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping

_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class PerformanceBeat:
    beat_index: int
    kind: str
    text: str = ""
    # Bubble và TTS có thể khác ngôn ngữ. Giữ display riêng để segment Nhật
    # không vô tình thay luôn UI Việt, một lỗi khá sáng tạo nhưng không hữu ích.
    display_text: str = ""
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
        payload = asdict(self)
        payload["beats"] = [beat.to_payload() for beat in self.beats]
        return payload

    @property
    def speech_beats(self) -> tuple[PerformanceBeat, ...]:
        return tuple(beat for beat in self.beats if beat.kind == "speech" and beat.text)


class AutonomousPerformancePlanner:
    """Dựng nhịp từ semantic contract; không tạo thêm semantic authority."""

    def plan(
        self,
        text: str,
        *,
        autonomous_plan: Mapping[str, Any] | None = None,
        performance_context: Mapping[str, Any] | None = None,
        opening_plan: Mapping[str, Any] | None = None,
        emotion: str = "neutral",
        motion: str = "none",
        tts_style: str = "neutral",
    ) -> AutonomousPerformanceAct | None:
        line = _clean(text)
        plan = _mapping(autonomous_plan)
        if not line or not plan or not bool(plan.get("speak", False)):
            return None
        semantics = _mapping(plan.get("semantics"))
        activity = _mapping(plan.get("activity"))
        perf = _mapping(performance_context)
        kind = str(semantics.get("turn_kind", "other") or "other")
        speech_act = str(semantics.get("speech_act", "unspecified") or "unspecified")
        hint = str(plan.get("performance_hint", perf.get("delivery_style", "neutral")) or "neutral")
        stage_emotion = str(perf.get("stage_emotion", emotion) or emotion or "neutral")
        stage_motion = str(perf.get("stage_motion", motion) or motion or "none")
        style = str(perf.get("tts_style", tts_style) or tts_style or "neutral")
        intrusion = max(0.0, min(1.0, float(plan.get("intrusion_risk", 0.0) or 0.0)))

        cadence, opening_hold, closing_hold, density = self._timing(kind, hint, intrusion)
        opening = _mapping(opening_plan)
        explicit_beats = tuple(
            item for item in (perf.get("opening_beats") or ())
            if isinstance(item, Mapping)
        )
        if opening:
            prosody = _mapping(opening.get("prosody_plan"))
            opening_hold = max(0, min(1000, int(prosody.get("opening_hold_ms", perf.get("opening_hold_ms", opening_hold)) or opening_hold)))
            closing_hold = max(0, min(1600, int(prosody.get("closing_settle_ms", perf.get("closing_settle_ms", closing_hold)) or closing_hold)))
            cadence = "opening_directed"

        speech_beats: list[PerformanceBeat] = []
        if explicit_beats:
            # Opening Director đã quyết định beat intent và pause. Stage chỉ map
            # sang contract cơ học, không chia lại theo dấu câu như thời đồ đá.
            for index, raw in enumerate(explicit_beats[:3]):
                part = _clean(raw.get("speech_text") or raw.get("display_text") or raw.get("text"))
                if not part:
                    continue
                beat_style = str(raw.get("delivery", style) or style)
                beat_motion = str(raw.get("motion", stage_motion if index == 0 else "hold_pose") or "none")
                beat_gaze = str(raw.get("gaze", "user_attention") or "user_attention")
                pause = max(0, min(1200, int(raw.get("pause_after_ms", 0) or 0)))
                emphasis = tuple(str(item) for item in (raw.get("emphasis") or ())[:4] if str(item).strip())
                speech_beats.append(PerformanceBeat(
                    beat_index=index + 1,
                    kind="speech",
                    text=part,
                    display_text=_clean(raw.get("display_text") or raw.get("text")),
                    duration_ms=self._duration(part),
                    pause_after_ms=pause,
                    tts_style=beat_style,
                    emotion=stage_emotion,
                    motion_intent=beat_motion,
                    gaze_intent=beat_gaze,
                    head_intent="neutral_small" if beat_motion in {"", "none"} else beat_motion,
                    gesture_intent="small_mark" if density == "low" and index == 0 else "none",
                    actions=tuple(f"emphasize:{item}" for item in emphasis),
                ))
        else:
            parts = self._split(line)[:2]
            for index, part in enumerate(parts):
                speech_beats.append(PerformanceBeat(
                    beat_index=index + 1,
                    kind="speech",
                    text=part,
                    display_text=part,
                    duration_ms=self._duration(part),
                    pause_after_ms=170 if index < len(parts) - 1 else 0,
                    tts_style=style,
                    emotion=stage_emotion,
                    motion_intent=stage_motion if index == 0 else "hold_pose",
                    gaze_intent="user_attention" if kind == "continuation" else "scene_focus",
                    head_intent="neutral_small" if stage_motion in {"", "none"} else stage_motion,
                    gesture_intent="small_mark" if density == "low" and index == 0 else "none",
                ))
        beats = (
            PerformanceBeat(
                beat_index=0,
                kind="opening_hold",
                duration_ms=opening_hold,
                emotion=stage_emotion,
                motion_intent=stage_motion,
                gaze_intent="user_attention" if kind == "continuation" else "scene_focus",
                head_intent="neutral_small",
            ),
            *speech_beats,
            PerformanceBeat(
                beat_index=len(speech_beats) + 1,
                kind="closing_settle",
                duration_ms=closing_hold,
                emotion="settle",
                motion_intent="settle",
                gaze_intent="soft_attention",
                head_intent="neutral_small",
            ),
        )
        total = opening_hold + closing_hold + sum(item.duration_ms + item.pause_after_ms for item in speech_beats)
        phase = str(activity.get("phase", "unknown") or "unknown")
        note = (
            f"Architecture C self-turn: kind={kind}; speech_act={speech_act}; cadence={cadence}; "
            f"activity_phase={phase}. Hold {opening_hold}ms, deliver {len(speech_beats)} beat(s), "
            "then settle. Do not add words or stage directions."
        )
        return AutonomousPerformanceAct(
            act_id=f"act_{uuid.uuid4().hex[:12]}",
            opportunity_id=str(plan.get("plan_id", "") or ""),
            opportunity_kind=kind,
            scene_mode=str(activity.get("activity_kind", "unknown") or "unknown"),
            intent=speech_act,
            session_phase=phase,
            cadence=cadence,
            stage_preset_id=f"architecture_c.{kind}",
            performance_lane="self_turn",
            gesture_density=density,
            body_first=True,
            audience_feedback_mode="mechanical_gate",
            intrusion_pressure=intrusion,
            show_arc_id="",
            show_arc_family="single_turn",
            show_arc_stage="complete",
            show_format_id="typed_self_turn",
            show_format_family="presence",
            show_format_variant=1,
            stage_energy=max(0.20, min(0.72, 0.58 - intrusion * 0.28)),
            line_shape=("multi_beat" if len(speech_beats) > 2 else "two_beat" if len(speech_beats) > 1 else "single_strike"),
            opening_mode="typed_hold",
            closing_mode="soft_return",
            beats=tuple(beats),
            total_budget_ms=total,
            cooldown_ms=0,  # InitiativeController sở hữu cooldown; stage không nhân đôi gate.
            opening_hold_ms=opening_hold,
            closing_hold_ms=closing_hold,
            director_note=note,
        )

    @staticmethod
    def _timing(kind: str, hint: str, intrusion: float) -> tuple[str, int, int, str]:
        if kind == "continuation":
            base = ("connected", 70, 300, "low")
        elif kind == "activity_event":
            base = ("responsive", 55, 250, "low")
        elif kind == "environment":
            base = ("observant", 95, 340, "low")
        elif kind in {"internal", "discovery"}:
            base = ("deliberate", 145, 430, "minimal")
        else:
            base = ("restrained", 110, 360, "minimal")
        cadence, opening, closing, density = base
        if "dry" in hint or "quiet" in hint:
            opening += 35
            closing += 60
        if intrusion >= 0.65:
            opening = min(opening, 70)
            closing = min(closing, 260)
            density = "minimal"
        return cadence, opening, closing, density

    @staticmethod
    def _split(text: str) -> tuple[str, ...]:
        parts = tuple(part.strip() for part in _SENTENCE_RE.split(text) if part.strip())
        return parts or (text,)

    @staticmethod
    def _duration(text: str) -> int:
        return max(420, min(4000, 260 + max(1, len(text.split())) * 255))


__all__ = ["AutonomousPerformanceAct", "AutonomousPerformancePlanner", "PerformanceBeat"]
