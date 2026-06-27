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

import re
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StageFrame:
    turn_id: str
    segment_id: int
    display_text: str
    tts_text: str
    emotion: str
    motion: str
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
                "interruptible": self.interruptible,
                "source": self.source,
            },
        }


_URL_RE = re.compile(r"https?://\S+")
_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_ACTION_PARENS_RE = re.compile(
    r"^\s*[\(\[]\s*(?:cười|nhíu mắt|thở|im lặng|nghiêng đầu|liếc|nhìn|gật|lắc|smile|laugh|sigh|whisper)[^\)\]]*[\)\]]\s*",
    re.I,
)


def clean_display_text(text: str) -> str:
    """Text cho UI: giữ nội dung, chỉ dọn whitespace/markdown thô."""
    t = str(text or "")
    t = _FENCE_RE.sub("[code]", t)
    t = _MARKDOWN_HEADING_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def clean_tts_source(text: str) -> str:
    """Text nguồn cho TTS: không đọc markdown, URL, code, hay tag diễn xuất."""
    t = clean_display_text(text)
    t = _ACTION_PARENS_RE.sub("", t)
    t = _INLINE_CODE_RE.sub("", t)
    t = _URL_RE.sub("", t)
    t = re.sub(r"\*{1,2}([^*]*)\*{1,2}", r"\1", t)
    t = re.sub(r"_{1,2}([^_]*)_{1,2}", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


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
        display_text = clean_display_text(str(payload.get("text", getattr(decision, "text", "")) or ""))
        tts_source = clean_tts_source(display_text)
        if self.localizer is not None and tts_source:
            try:
                tts_text = str(self.localizer.localize(tts_source, language_hint=self.language_hint) or "").strip()
            except Exception:
                tts_text = tts_source
        else:
            tts_text = tts_source

        should_speak = bool(payload.get("should_speak", getattr(decision, "should_speak", True)))
        return StageFrame(
            turn_id=str(turn_id or uuid.uuid4().hex),
            segment_id=int(segment_id),
            display_text=display_text,
            tts_text=tts_text,
            emotion=_emotion_from_payload(payload, frame=frame),
            motion=_motion_from_decision(decision),
            interruptible=bool(should_speak and str(channel or "").strip().lower() not in {"system_warning"}),
            source=f"decision:{str(getattr(decision, 'intent', '') or channel or 'unknown')}",
        )


__all__ = [
    "StageFrame",
    "StageFrameBuilder",
    "clean_display_text",
    "clean_tts_source",
]
