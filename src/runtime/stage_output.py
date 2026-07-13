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


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+")


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

        # Chỉ tách khi dấu kết câu được theo sau bởi whitespace. Vì vậy dấu
        # chấm trong 3.5, v1.2.3, URL hoặc tên file không bị coi là hết câu.
        parts = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(clean) if part.strip()]
        if len(parts) <= 1:
            return (clean,)

        # Gộp câu quá ngắn vào câu trước để tránh TTS phát mẩu vụn.
        merged: list[str] = []
        for part in parts:
            if merged and len(part) < 12:
                merged[-1] = f"{merged[-1]} {part}".strip()
            else:
                merged.append(part)

        # Không được slice rồi làm mất phần cuối. Nếu vượt max segment, gộp toàn
        # bộ phần dư vào segment cuối để bảo toàn 100% nội dung.
        max_segments = _max_segments()
        if len(merged) > max_segments:
            head = merged[: max_segments - 1]
            tail = " ".join(merged[max_segments - 1 :]).strip()
            merged = [*head, tail]
        return tuple(merged)


class StageOutputPipeline:
    """Base StageFrame -> tuple[StageFrame, ...]."""

    def __init__(self) -> None:
        self.segmenter = SentenceSegmenter()
        self.prosody = ProsodyDirector()

    def frames_for_tts(self, frame: StageFrame) -> tuple[StageFrame, ...]:
        # Một audio preset đã render ứng với toàn bộ câu. Tách segment sẽ làm
        # metadata file WAV lệch khỏi transcript và phát cùng file nhiều lần.
        if str(getattr(frame, "audio_asset", "") or "").strip():
            return (frame,)
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
                    memory_text=segment,
                    prosody_style=plan.style,
                    prosody_notes=plan.director_notes,
                )
            )
        return tuple(frames)


__all__ = ["SentenceSegmenter", "StageOutputPipeline"]
