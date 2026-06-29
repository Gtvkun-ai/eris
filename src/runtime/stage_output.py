# -*- coding: utf-8 -*-
"""stage_output.py — transformer chain nhỏ cho output sân khấu.

Sau StageFrame đầu tiên, câu vẫn có thể quá dài để TTS nghe tự nhiên.  Người
thật thường nói thành mấy nhịp ngắn: "Khoan." rồi mới tới câu chính.  Module
này tách ``StageFrame`` thành nhiều segment TTS, nhưng vẫn giữ cùng ``turn_id``.

Đây là transformer thuần dữ liệu: không gọi TTS, không gửi UI, không chạm memory.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace

from runtime.prosody_director import ProsodyDirector
from runtime.stage_contracts import StageFrame


_SENTENCE_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?")


def _enabled() -> bool:
    return os.environ.get("ERIS_STAGE_SEGMENT_TTS", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _max_segments() -> int:
    raw = os.environ.get("ERIS_STAGE_MAX_TTS_SEGMENTS", "4").strip()
    try:
        return max(1, min(8, int(raw)))
    except ValueError:
        return 4


def _min_split_chars() -> int:
    raw = os.environ.get("ERIS_STAGE_MIN_SPLIT_CHARS", "72").strip()
    try:
        return max(24, min(160, int(raw)))
    except ValueError:
        return 72


class SentenceSegmenter:
    """Chia text TTS thành các câu ngắn, không đụng vào text UI."""

    def split(self, text: str) -> tuple[str, ...]:
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return ()
        if len(clean) < _min_split_chars():
            return (clean,)

        parts = [match.group(0).strip() for match in _SENTENCE_RE.finditer(clean)]
        parts = [part for part in parts if part]
        if len(parts) <= 1:
            return (clean,)

        # Gộp câu quá ngắn vào câu sau/trước để tránh TTS phát mấy mẩu vụn.
        merged: list[str] = []
        for part in parts:
            if merged and len(part) < 12:
                merged[-1] = f"{merged[-1]} {part}".strip()
            else:
                merged.append(part)
        return tuple(merged[: _max_segments()])


class StageOutputPipeline:
    """Base StageFrame -> tuple[StageFrame, ...]."""

    def __init__(self) -> None:
        self.segmenter = SentenceSegmenter()
        self.prosody = ProsodyDirector()

    def frames_for_tts(self, frame: StageFrame) -> tuple[StageFrame, ...]:
        if not _enabled():
            return (frame,)
        segments = self.segmenter.split(frame.tts_text)
        if len(segments) <= 1:
            return (frame,)

        frames: list[StageFrame] = []
        for index, segment in enumerate(segments):
            plan = self.prosody.plan(
                segment,
                emotion=frame.emotion,
                style_hint=frame.prosody_style,
                notes_hint=frame.prosody_notes,
            )
            frames.append(
                replace(
                    frame,
                    segment_id=index,
                    display_text=segment,
                    tts_text=segment,
                    prosody_style=plan.style,
                    prosody_notes=plan.director_notes,
                )
            )
        return tuple(frames)


__all__ = ["SentenceSegmenter", "StageOutputPipeline"]
