# -*- coding: utf-8 -*-
"""Feature flag cho bốn ranh giới kiến trúc public-speech.

Mặc định mới là fail-closed. Code cũ vẫn còn để rollback, nhưng chỉ chạy khi
flag tương ứng được bật rõ ràng. Cách này bớt hào hứng hơn việc xóa sạch rồi cầu
nguyện lúc deploy, nhưng đáng tin hơn đáng kể.
"""
from __future__ import annotations

import os
from typing import Any


def _flag(setting_name: str, env_name: str, default: bool = False) -> bool:
    try:
        from runtime.runtime_settings_store import runtime_bool
        return bool(runtime_bool("architecture", setting_name, default=default))
    except Exception:
        raw: Any = os.getenv(env_name)
        if raw is None:
            return bool(default)
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "bật", "bat"}


def private_cognition_surface_export_enabled() -> bool:
    """Cho PrivateMind/PrivateLife xuất candidate speech kiểu cũ (mặc định tắt)."""
    return _flag("private_cognition_surface_export", "ERIS_PRIVATE_COGNITION_SURFACE_EXPORT", False)


def surface_cross_worker_fallback_enabled() -> bool:
    """Cho worker khác giả làm Surface khi Surface chết (mặc định tắt)."""
    return _flag("surface_cross_worker_fallback", "ERIS_SURFACE_REALIZER_COMPANION_FALLBACK", False)


def legacy_model_lanes_enabled() -> bool:
    """Khởi động local/open-model/style lane cũ (mặc định tắt)."""
    return _flag("legacy_model_lanes_enabled", "ERIS_LEGACY_MODEL_LANES_ENABLED", False)


def inner_diary_model_enabled() -> bool:
    """Cho inner diary gọi model riêng (mặc định tắt; renderer local vẫn còn)."""
    return _flag("inner_diary_model_enabled", "ERIS_INNER_DIARY_MODEL_ENABLED", False)


def background_tutor_enabled() -> bool:
    """Khởi động tutor/research nền (mặc định tắt)."""
    return _flag("background_tutor_enabled", "ERIS_BACKGROUND_TUTOR_ENABLED", False)


def legacy_social_fallback_enabled() -> bool:
    """Bật generic social liveness fallback cũ (mặc định tắt)."""
    return _flag("legacy_social_fallback_enabled", "ERIS_LEGACY_SOCIAL_FALLBACK_ENABLED", False)


def event_trace_enabled() -> bool:
    """Ghi trace xuyên candidate -> governor -> Surface -> TTS -> outcome."""
    return _flag("event_trace_enabled", "ERIS_PUBLIC_EVENT_TRACE_ENABLED", True)


PUBLIC_INTENT_OWNERS = frozenset({"intent_planner", "social_initiative"})


def is_public_intent_owner(owner: object) -> bool:
    return str(owner or "").strip().lower() in PUBLIC_INTENT_OWNERS


__all__ = [
    "PUBLIC_INTENT_OWNERS", "is_public_intent_owner",
    "private_cognition_surface_export_enabled", "surface_cross_worker_fallback_enabled",
    "legacy_model_lanes_enabled", "inner_diary_model_enabled", "background_tutor_enabled",
    "legacy_social_fallback_enabled", "event_trace_enabled",
]
