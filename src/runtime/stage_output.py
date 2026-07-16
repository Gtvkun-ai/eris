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
    from runtime.runtime_settings_store import runtime_bool
    return runtime_bool("stage", "segment_tts", default=True)


def _max_segments() -> int:
    from runtime.runtime_settings_store import runtime_int
    return max(1, min(16, runtime_int("stage", "max_tts_segments", default=8)))


def _min_split_chars() -> int:
    from runtime.runtime_settings_store import runtime_int
    return max(24, min(120, runtime_int("stage", "min_split_chars", default=58)))


def _max_segment_chars() -> int:
    from runtime.runtime_settings_store import runtime_int
    # Gemini TTS ổn định hơn với nhịp 45–90 ký tự. Câu dài được chia trước
    # provider thay vì đẩy một blob rồi trách key pool vì nghệ thuật kể chuyện.
    return max(48, min(320, runtime_int("stage", "max_tts_segment_chars", default=88)))


def _split_long_piece(text: str, max_chars: int) -> list[str]:
    """Tách câu dài không dấu chấm theo clause/word, không làm mất ký tự."""
    source = " ".join(str(text or "").split()).strip()
    if not source or len(source) <= max_chars:
        return [source] if source else []

    chunks: list[str] = []
    rest = source
    while len(rest) > max_chars:
        window = rest[: max_chars + 1]
        cut = -1
        # Ưu tiên dấu ngắt tự nhiên, sau đó mới tới khoảng trắng.
        for marker in ("; ", ": ", ", ", " — ", " - ", " "):
            pos = window.rfind(marker)
            if pos >= int(max_chars * 0.55):
                cut = pos + (len(marker.rstrip()) if marker.strip() else 0)
                break
        if cut <= 0:
            cut = max_chars
        piece = rest[:cut].strip()
        if not piece:
            piece = rest[:max_chars].strip()
            cut = max_chars
        chunks.append(piece)
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


def _rebalance_to_limit(chunks: list[str], max_segments: int) -> list[str]:
    """Gộp cân bằng khi quá nhiều chunk, tránh dồn toàn bộ phần dư vào câu cuối."""
    if len(chunks) <= max_segments:
        return chunks
    total_chars = sum(len(item) for item in chunks) + max(0, len(chunks) - 1)
    groups: list[str] = []
    cursor = 0
    remaining_chars = total_chars
    while cursor < len(chunks) and len(groups) < max_segments:
        groups_left = max_segments - len(groups)
        chunks_left = len(chunks) - cursor
        if groups_left == 1:
            groups.append(" ".join(chunks[cursor:]).strip())
            break
        target = max(1, remaining_chars // groups_left)
        current: list[str] = []
        current_len = 0
        # Luôn để lại ít nhất một chunk cho mỗi group còn lại.
        while cursor < len(chunks) - (groups_left - 1):
            candidate = chunks[cursor]
            added = len(candidate) + (1 if current else 0)
            if current and current_len + added > target:
                break
            current.append(candidate)
            current_len += added
            cursor += 1
        if not current:
            current.append(chunks[cursor])
            current_len = len(chunks[cursor])
            cursor += 1
        groups.append(" ".join(current).strip())
        remaining_chars = max(0, remaining_chars - current_len - 1)
    return groups


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
        if not parts:
            return ()

        # Gộp câu quá ngắn vào câu trước để tránh TTS phát mẩu vụn.
        merged: list[str] = []
        for part in parts:
            if merged and len(part) < 12:
                merged[-1] = f"{merged[-1]} {part}".strip()
            else:
                merged.append(part)

        # Một câu không có dấu chấm vẫn có thể dài hàng nghìn ký tự. Tách tiếp
        # theo clause/word trước khi chạm provider, thay vì để TTS drift rồi đổ
        # cho model vì con người đã viết một đoạn văn như biên bản họp.
        hard_chunks: list[str] = []
        for part in merged:
            hard_chunks.extend(_split_long_piece(part, _max_segment_chars()))

        balanced = _rebalance_to_limit(hard_chunks, _max_segments())
        return tuple(item for item in balanced if item)


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

        # Autonomous act đã có speech beat do Stage Director đặt. Ưu tiên beat
        # này hơn sentence splitter tổng quát để điểm rơi không bị chia lại lần hai.
        act = frame.stage_act if isinstance(getattr(frame, "stage_act", None), dict) else {}
        beats = act.get("beats") if isinstance(act, dict) else None
        speech_beats = [
            beat for beat in (beats or [])
            if isinstance(beat, dict) and str(beat.get("kind", "")) == "speech" and str(beat.get("text", "")).strip()
        ]
        if speech_beats:
            frames: list[StageFrame] = []
            segment_index = 0
            for beat in speech_beats:
                beat_text = str(beat.get("text", "") or "").strip()
                beat_parts = self.segmenter.split(beat_text) or ((beat_text,) if beat_text else ())
                for part_index, text in enumerate(beat_parts):
                    delivery = dict(frame.delivery) if isinstance(frame.delivery, dict) else {}
                    delivery["active_beat"] = dict(beat)
                    pause_after = int(beat.get("pause_after_ms", 0) or 0) if part_index == len(beat_parts) - 1 else 0
                    notes = frame.prosody_notes
                    if pause_after > 0:
                        notes = f"{notes} End this beat with a short {pause_after}ms rhetorical pause.".strip()
                    plan = self.prosody.plan(
                        text,
                        emotion=str(beat.get("emotion", frame.emotion) or frame.emotion),
                        style_hint=str(beat.get("tts_style", frame.prosody_style) or frame.prosody_style),
                        notes_hint=notes,
                    )
                    frames.append(
                        replace(
                            frame,
                            segment_id=segment_index,
                            display_text=text,
                            tts_text=text,
                            memory_text=text,
                            emotion=str(beat.get("emotion", frame.emotion) or frame.emotion),
                            motion=str(beat.get("motion_intent", frame.motion) or frame.motion),
                            prosody_style=plan.style,
                            prosody_notes=plan.director_notes,
                            delivery=delivery,
                        )
                    )
                    segment_index += 1
            return tuple(frames)

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
