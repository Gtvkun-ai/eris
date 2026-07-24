# -*- coding: utf-8 -*-
"""Chính sách đồng bộ bubble chat với TTS.

Text mặc định chỉ được public khi audio bắt đầu phát. Panel/debug vẫn có thể cập
nhật ngay. Khi TTS synth thất bại trước playback, coordinator phải nhả text ra để
không làm mất câu trả lời.
"""
from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}
_DEFAULT_TEXT_SYNC_TIMEOUT_SECONDS = 8.0


def sync_text_with_tts_enabled() -> bool:
    """Mặc định bật; đặt ERIS_TTS_SYNC_TEXT=0 để quay về hành vi legacy."""

    return os.environ.get("ERIS_TTS_SYNC_TEXT", "1").strip().lower() in _TRUE


def text_sync_timeout_seconds() -> float:
    """Fallback delay before showing text if playback never reports audio start."""

    raw = os.environ.get("ERIS_TTS_TEXT_SYNC_TIMEOUT", "").strip()
    if not raw:
        return _DEFAULT_TEXT_SYNC_TIMEOUT_SECONDS
    try:
        return max(0.15, min(30.0, float(raw)))
    except ValueError:
        return _DEFAULT_TEXT_SYNC_TIMEOUT_SECONDS


def tts_event_releases_deferred_text(event_type: str) -> bool:
    """Nhả text khi synth thất bại trước lúc callback playback được gọi."""

    return str(event_type or "").strip().lower() == "audio_failed"


__all__ = [
    "sync_text_with_tts_enabled",
    "text_sync_timeout_seconds",
    "tts_event_releases_deferred_text",
]
