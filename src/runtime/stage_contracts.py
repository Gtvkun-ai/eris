# -*- coding: utf-8 -*-
"""stage_contracts.py — hợp đồng sân khấu giữa Decision, UI, TTS và body.

``Decision`` là kết quả của não: ERIS định nói gì, animation nào, action nào.
``StageFrame`` là một lát biểu diễn: UI hiện gì, TTS đọc gì, mặt/động tác gì,
có cho ngắt không, và trace về lượt nói.

Tầng này cố ý nhỏ.  Mục tiêu là tách string public khỏi string TTS trước đã; sau
này có Live2D/expression chi tiết thì chỉ cần map thêm vào ``emotion``/``motion``
chứ không phải nhét "(cười khẽ)" vào text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from runtime.prosody_director import ProsodyDirector
from runtime.speech_delivery_planner import SpeechDeliveryPlanner, affect_signals_from
from runtime.stage_transformers import StageTransformerChain


@dataclass(frozen=True, slots=True)
class StageFrame:
    turn_id: str
    segment_id: int
    display_text: str
    tts_text: str
    memory_text: str
    emotion: str
    motion: str
    actions: tuple[str, ...]
    prosody_style: str
    prosody_notes: str
    delivery: dict[str, Any]
    interruptible: bool
    source: str

    def to_payload_patch(self) -> dict[str, Any]:
        """Patch gắn vào payload cũ mà không phá Godot/client hiện tại."""
        return {
            "display_text": self.display_text,
            "stage": {
                "turn_id": self.turn_id,
                "segment_id": self.segment_id,
                "emotion": self.emotion,
                "motion": self.motion,
                "actions": list(self.actions),
                "prosody_style": self.prosody_style,
                "delivery": self.delivery,
                "interruptible": self.interruptible,
                "source": self.source,
            },
        }


_TRANSFORMERS = StageTransformerChain()


def clean_display_text(text: str) -> str:
    """Text cho UI: giữ nội dung, chỉ dọn whitespace/markdown thô."""
    return _TRANSFORMERS.transform(text).display_text


def clean_tts_source(text: str) -> str:
    """Text nguồn cho TTS: không đọc markdown, URL, code, hay tag diễn xuất."""
    return _TRANSFORMERS.transform(text).tts_text


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _emotion_from_payload(payload: dict[str, Any], frame: Any = None) -> str:
    """Rút emotion thô cho stage từ appraisal/envelope hiện có.

    Đây chỉ là nhãn sân khấu, không phải claim "ERIS có cảm xúc người".
    """
    appraisal = getattr(frame, "appraisal", None) if frame is not None else None
    stance = str(getattr(appraisal, "stance", "") or "").strip().lower()
    if stance:
        return stance

    mood = {}
    emotion_debug = payload.get("emotion_debug")
    if isinstance(emotion_debug, dict):
        raw_mood = emotion_debug.get("summary")
        if isinstance(raw_mood, dict):
            mood = raw_mood

    valence = _safe_float(mood.get("valence"), 0.0) if isinstance(mood, dict) else 0.0
    arousal = _safe_float(getattr(appraisal, "arousal", 0.3), 0.3)
    if valence > 0.25 and arousal > 0.35:
        return "warm_playful"
    if valence > 0.12:
        return "warm_soft"
    if valence < -0.25 and arousal > 0.45:
        return "tense"
    if valence < -0.15:
        return "quiet_low"
    if arousal > 0.62:
        return "focused"
    return "neutral"


def _prosody_numbers(payload: dict[str, Any], frame: Any = None) -> tuple[float, float, str]:
    """Trích valence/arousal/stance cho prosody mà không bắt stage biết cognition."""
    appraisal = getattr(frame, "appraisal", None) if frame is not None else None
    emotion_debug = payload.get("emotion_debug")
    mood = {}
    if isinstance(emotion_debug, dict) and isinstance(emotion_debug.get("summary"), dict):
        mood = emotion_debug.get("summary") or {}
    valence = _safe_float(mood.get("valence"), 0.0) if isinstance(mood, dict) else 0.0
    arousal = _safe_float(getattr(appraisal, "arousal", 0.3), 0.3)
    stance = str(getattr(appraisal, "stance", "") or "")
    return valence, arousal, stance


def _motion_from_decision(decision: Any) -> str:
    resolver = getattr(decision, "resolve_motion_intent", None)
    if callable(resolver):
        motion = str(resolver() or "").strip()
        if motion:
            return motion
    animation = str(getattr(decision, "animation", "") or "").strip()
    return animation or "none"


class StageFrameBuilder:
    """Dịch ``Decision`` thành ``StageFrame``.

    Localizer được inject để test/offline dễ hơn.  Nếu không có localizer, TTS đọc
    câu đã clean bằng chính ngôn ngữ gốc.
    """

    def __init__(self, *, localizer: Any = None, language_hint: str = "auto") -> None:
        self.localizer = localizer
        self.language_hint = language_hint or "auto"
        self.prosody_director = ProsodyDirector()
        self.transformers = StageTransformerChain()
        self.delivery_planner = SpeechDeliveryPlanner()

    def build(
        self,
        decision: Any,
        *,
        payload: dict[str, Any],
        channel: str | None = None,
        frame: Any = None,
        turn_id: str | None = None,
        segment_id: int = 0,
    ) -> StageFrame:
        raw_text = str(payload.get("text", getattr(decision, "text", "")) or "")
        surfaces = self.transformers.transform(raw_text)
        tts_source = surfaces.tts_text
        if self.localizer is not None and tts_source:
            try:
                tts_text = str(self.localizer.localize(tts_source, language_hint=self.language_hint) or "").strip()
            except Exception:
                tts_text = tts_source
        else:
            tts_text = tts_source

        should_speak = bool(payload.get("should_speak", getattr(decision, "should_speak", True)))
        affect = affect_signals_from(payload, frame=frame)
        delivery_hint = str(payload.get("delivery_hint", getattr(decision, "delivery_hint", "")) or "").strip()
        nonverbal_cue = str(payload.get("nonverbal_cue", getattr(decision, "nonverbal_cue", "")) or "").strip()
        stage_motion = str(payload.get("stage_motion", getattr(decision, "stage_motion", "")) or "").strip()
        base_emotion = surfaces.marks.emotion_hint or _emotion_from_payload(payload, frame=frame)
        explicit_motion = _motion_from_decision(decision)
        extracted_actions = tuple(
            item
            for item in (*surfaces.marks.actions, nonverbal_cue)
            if str(item or "").strip()
        )
        delivery = self.delivery_planner.plan(
            surfaces.display_text or surfaces.tts_text,
            intent=str(getattr(decision, "intent", "") or ""),
            delivery_hint=delivery_hint,
            explicit_emotion=base_emotion,
            explicit_motion=stage_motion or surfaces.marks.motion_hint,
            extracted_actions=extracted_actions,
            affect=affect,
        )
        emotion = delivery.emotion or base_emotion
        motion = stage_motion or (explicit_motion if explicit_motion and explicit_motion != "none" else delivery.motion)
        valence, arousal, stance = _prosody_numbers(payload, frame=frame)
        prosody = self.prosody_director.plan(
            tts_text,
            emotion=emotion,
            intent=str(getattr(decision, "intent", "") or ""),
            stance=stance,
            valence=valence,
            arousal=arousal,
            style_hint=delivery.voice_style,
            notes_hint=delivery.prosody_notes,
        )
        return StageFrame(
            turn_id=str(turn_id or uuid.uuid4().hex),
            segment_id=int(segment_id),
            display_text=surfaces.display_text,
            tts_text=tts_text,
            memory_text=surfaces.memory_text,
            emotion=emotion,
            motion=motion or "none",
            actions=delivery.pre_speech_actions,
            prosody_style=prosody.style,
            prosody_notes=prosody.director_notes,
            delivery=delivery.to_payload(),
            interruptible=bool(should_speak and str(channel or "").strip().lower() not in {"system_warning"}),
            source=f"decision:{str(getattr(decision, 'intent', '') or channel or 'unknown')}",
        )


__all__ = [
    "StageFrame",
    "StageFrameBuilder",
    "clean_display_text",
    "clean_tts_source",
]
