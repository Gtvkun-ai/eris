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
import time
from dataclasses import replace
from typing import Any, Callable, Iterable

from runtime.stage_contracts import StageFrame


def _dispatch_mode() -> str:
    # Env mức thấp vẫn thắng để test một nhánh riêng. Nếu không có, profile có
    # tên quyết định cả cụm thay vì để bốn toggle tự mâu thuẫn với nhau.
    env_value = os.environ.get("ERIS_TTS_SEGMENT_DISPATCH", "").strip().lower()
    if env_value in {"inline", "queued"}:
        return env_value
    from runtime.stage_profiles import active_stage_profile
    return active_stage_profile().dispatch_mode


def _task_manager_enabled() -> bool:
    env_value = os.environ.get("ERIS_TTS_TASK_MANAGER", "").strip().lower()
    if env_value:
        return env_value not in {"0", "false", "off", "no", "none"}
    from runtime.stage_profiles import active_stage_profile
    return active_stage_profile().task_manager_enabled


def _join_tts_segments(frames: list[StageFrame]) -> str:
    """Ghép segment thành một transcript liên tục để tránh nhiều call TTS.

    Không chèn tag vào đây; prosody/markup vẫn thuộc ``tts_engine``. Dấu câu sẵn
    có trong từng segment đủ cho Gemini tạo ngắt nhịp tự nhiên trong cùng audio.
    Dùng line break thay vì dấu cách để mỗi segment là một breath group ngắn.
    """
    # Dùng khoảng trắng; line break ở vài backend remote bị diễn giải thành
    # pause dài bất thường. Điểm rơi đã có trong dấu câu + prosody_notes.
    return " ".join(str(frame.tts_text or "").strip() for frame in frames if str(frame.tts_text or "").strip()).strip()


def _speech_kwargs(frame) -> dict[str, object]:
    """Truyền contract đã pin theo turn xuống backend TTS."""
    contract = getattr(frame, "speech_contract", None)
    if not isinstance(contract, dict):
        return {}
    return {
        "language_hint": str(contract.get("language", "") or ""),
        "voice_family": str(contract.get("voice_family", "") or ""),
        "locale": str(contract.get("locale", "") or ""),
        "prelocalized": bool(contract.get("prelocalized", False)),
    }


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


def _opening_hold_ms(frame: StageFrame) -> int:
    act = frame.stage_act if isinstance(getattr(frame, "stage_act", None), dict) else {}
    try:
        return max(0, min(250, int(act.get("opening_hold_ms", 0) or 0)))
    except (TypeError, ValueError):
        return 0


class StageDispatcher:
    def __init__(self, *, profile: object | None = None) -> None:
        if isinstance(profile, str):
            from runtime.stage_profiles import stage_profile
            profile = stage_profile(profile)
        self.profile = profile

    def _profile(self):
        if self.profile is not None:
            return self.profile
        from runtime.stage_profiles import active_stage_profile
        return active_stage_profile()

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
        # Setting có thể đổi trong panel sau khi Python đã khởi động.
        refresh = getattr(tts_engine, "refresh_configuration", None) if tts_engine is not None else None
        if callable(refresh):
            refresh()
        frame_list = [frame for frame in frames if str(frame.tts_text or "").strip()]
        if not frame_list or tts_engine is None or not getattr(tts_engine, "_ok", False):
            return False

        # Opening hold là nhịp thật, nhưng giới hạn 250ms để không biến stage thành
        # lag. Text/UI có thể đã hiện trước; TTS vào sau một nhịp nhỏ như performer.
        opening_hold = _opening_hold_ms(frame_list[0])
        if opening_hold > 0:
            time.sleep(opening_hold / 1000.0)

        manager_enabled = (
            _task_manager_enabled()
            if os.environ.get("ERIS_TTS_TASK_MANAGER", "").strip()
            else bool(getattr(self._profile(), "task_manager_enabled", False))
        )
        if manager_enabled:
            try:
                manager = getattr(tts_engine, "task_manager", None)
                if manager is None:
                    from runtime.stage_audio_bus import StageAudioBus
                    from runtime.tts_task_manager import TtsTaskManager

                    # Manager sống cùng engine để cancel_current/shutdown có thể
                    # chạm đúng queue đang phát khi user chen vào.
                    manager = TtsTaskManager(
                        audio_bus=StageAudioBus(),
                        prefetch_workers=int(getattr(self._profile(), "prefetch_workers", 2) or 2),
                        max_prefetch_segments=int(getattr(self._profile(), "max_prefetch_segments", 4) or 4),
                    )
                    setattr(tts_engine, "task_manager", manager)
                else:
                    # Manager có thể đã được tạo ở conversation profile. Cập nhật
                    # policy live khi chuyển sang recording, không bắt restart app.
                    if hasattr(manager, "prefetch_workers"):
                        manager.prefetch_workers = int(getattr(self._profile(), "prefetch_workers", 2) or 2)
                    if hasattr(manager, "max_prefetch_segments"):
                        manager.max_prefetch_segments = int(getattr(self._profile(), "max_prefetch_segments", 4) or 4)
                scheduled = manager.dispatch_frames(
                    frame_list,
                    backend=tts_engine,
                    valence=valence,
                    arousal=arousal,
                    stance=stance,
                    on_first_start=on_first_start,
                    on_event=on_event,
                )
                if scheduled:
                    return True
            except Exception:
                # Fallback giữ Eris có tiếng nói kể cả khi manager mới lỗi.
                pass

        dispatch_mode = (
            _dispatch_mode()
            if os.environ.get("ERIS_TTS_SEGMENT_DISPATCH", "").strip()
            else str(getattr(self._profile(), "dispatch_mode", "inline") or "inline")
        )
        if dispatch_mode == "inline" or len(frame_list) == 1:
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
                f"between the {len(frame_list)} sentence segments; do not insert long silence. "
                "Treat punctuation as short intentional speech beats."
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
            **_speech_kwargs(inline_frame),
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
                **_speech_kwargs(frame),
            )
            scheduled = True
        return scheduled


__all__ = ["StageDispatcher"]
