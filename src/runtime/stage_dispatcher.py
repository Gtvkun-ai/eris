# -*- coding: utf-8 -*-
"""stage_dispatcher.py — phát StageFrame ra TTS theo đúng nhịp segment.

Coordinator không nên tự biết quá nhiều về queue TTS. Dispatcher nhận list frame,
và chọn cách phát phù hợp với backend.

Với Gemini/remote TTS, gọi API riêng cho từng segment tạo khoảng chờ rất dài
giữa các câu. Vì vậy mặc định dispatcher gộp các segment thành MỘT transcript có
pause tự nhiên, rồi gọi TTS một lần. Nếu muốn test queue từng segment, bật:

    ERIS_TTS_SEGMENT_DISPATCH=queued
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Callable, Iterable

from runtime.stage_contracts import StageFrame


def _dispatch_mode() -> str:
    value = os.environ.get("ERIS_TTS_SEGMENT_DISPATCH", "inline").strip().lower()
    return value if value in {"inline", "queued"} else "inline"


def _join_tts_segments(frames: list[StageFrame]) -> str:
    """Ghép segment thành một transcript liên tục để tránh nhiều call TTS.

    Không chèn tag vào đây; prosody/markup vẫn thuộc ``tts_engine``. Dấu câu sẵn
    có trong từng segment đủ cho Gemini tạo ngắt nhịp tự nhiên trong cùng audio.
    Dùng line break thay vì dấu cách để mỗi segment là một breath group ngắn.
    """
    return "\n".join(str(frame.tts_text or "").strip() for frame in frames if str(frame.tts_text or "").strip()).strip()


def _performance_kwargs(frame: StageFrame) -> dict[str, str]:
    """Rút metadata vocal cache từ delivery payload nếu có.

    Dispatcher chỉ truyền metadata; TTS engine tự quyết định có dùng cache hay
    không. Như vậy stage không biết chi tiết file/cache/audio backend.
    """
    delivery = frame.delivery if isinstance(frame.delivery, dict) else {}
    act = delivery.get("performance_act") if isinstance(delivery, dict) else None
    if not isinstance(act, dict):
        return {}
    return {
        "vocal_cache_kind": str(act.get("kind", "") or ""),
        "vocal_prefix": str(act.get("audible_prefix", "") or ""),
    }


class StageDispatcher:
    def dispatch_tts(
        self,
        frames: Iterable[StageFrame],
        *,
        tts_engine: Any,
        valence: float,
        arousal: float,
        stance: str,
        on_first_start: Callable[[], None] | None = None,
        on_event: Callable[[Any, StageFrame], None] | None = None,
    ) -> bool:
        frame_list = [frame for frame in frames if str(frame.tts_text or "").strip()]
        if not frame_list or tts_engine is None or not getattr(tts_engine, "_ok", False):
            return False

        if _dispatch_mode() == "inline" or len(frame_list) == 1:
            return self._dispatch_inline(
                frame_list,
                tts_engine=tts_engine,
                valence=valence,
                arousal=arousal,
                stance=stance,
                on_first_start=on_first_start,
                on_event=on_event,
            )
        return self._dispatch_queued(
            frame_list,
            tts_engine=tts_engine,
            valence=valence,
            arousal=arousal,
            stance=stance,
            on_first_start=on_first_start,
            on_event=on_event,
        )

    def _dispatch_inline(
        self,
        frame_list: list[StageFrame],
        *,
        tts_engine: Any,
        valence: float,
        arousal: float,
        stance: str,
        on_first_start: Callable[[], None] | None,
        on_event: Callable[[Any, StageFrame], None] | None,
    ) -> bool:
        base = frame_list[0]
        joined = _join_tts_segments(frame_list)
        if not joined:
            return False
        notes = base.prosody_notes
        if len(frame_list) > 1:
            notes = (
                f"{notes} Read the transcript as one continuous turn with natural short pauses "
                f"between the {len(frame_list)} sentence segments. Treat line breaks as short speech beats, "
                "not long silence."
            ).strip()
        inline_frame = replace(base, segment_id=0, tts_text=joined, prosody_notes=notes)

        def event_callback(event, *, _frame=inline_frame):
            if on_event is not None:
                on_event(event, _frame)

        tts_engine.speak(
            inline_frame.tts_text,
            valence=valence,
            arousal=arousal,
            stance=stance,
            on_start_play=on_first_start,
            prosody_style=inline_frame.prosody_style,
            prosody_notes=inline_frame.prosody_notes,
            turn_id=inline_frame.turn_id,
            segment_id=inline_frame.segment_id,
            interruptible=inline_frame.interruptible,
            replace=True,
            on_event=event_callback,
            **_performance_kwargs(inline_frame),
        )
        return True

    def _dispatch_queued(
        self,
        frame_list: list[StageFrame],
        *,
        tts_engine: Any,
        valence: float,
        arousal: float,
        stance: str,
        on_first_start: Callable[[], None] | None,
        on_event: Callable[[Any, StageFrame], None] | None,
    ) -> bool:
        scheduled = False
        for index, frame in enumerate(frame_list):
            start_callback = on_first_start if index == 0 else None

            def event_callback(event, *, _frame=frame):
                if on_event is not None:
                    on_event(event, _frame)

            tts_engine.speak(
                frame.tts_text,
                valence=valence,
                arousal=arousal,
                stance=stance,
                on_start_play=start_callback,
                prosody_style=frame.prosody_style,
                prosody_notes=frame.prosody_notes,
                turn_id=frame.turn_id,
                segment_id=frame.segment_id,
                interruptible=frame.interruptible,
                replace=(index == 0),
                on_event=event_callback,
                **_performance_kwargs(frame),
            )
            scheduled = True
        return scheduled


__all__ = ["StageDispatcher"]
