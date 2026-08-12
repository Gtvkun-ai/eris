# -*- coding: utf-8 -*-
"""Biến yêu cầu nói chủ động của user thành policy runtime thật.

Không dùng model để đoán một directive quá rõ như "mở lên là nói tự động".
Module này chỉ nhận diện ý định điều khiển sản phẩm, lưu preference vào
``runtime_settings.json`` và tạo prompt context xác nhận policy đã áp dụng.
Nó không tự viết câu public và không tạo local text fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

from runtime.cognition.normalization import normalize_vi
from runtime.runtime_settings_store import get_runtime_settings_store


@dataclass(frozen=True, slots=True)
class AutonomousSurfacePreferenceResult:
    applied: bool = False
    mode: str = ""
    reason: str = ""
    prompt_context: str = ""


# Các phrase này mô tả hành vi sản phẩm, không phải chủ đề tán gẫu. Giữ danh
# sách nhỏ và semantic, tránh biến mọi chữ "nói" thành lệnh bật radio 24/7.
_ENABLE_MARKERS = (
    "loa phat thanh tu dong",
    "tu dong noi",
    "tu noi nhieu hon",
    "noi chu dong",
    "mo len la noi",
    "mo ban len la can co tieng",
    "co tieng la duoc",
    "noi linh tinh di",
    "noi linh tinh ik",
    "cu noi di",
)
_DISABLE_MARKERS = (
    "dung noi tu dong",
    "tat loa tu dong",
    "im di",
    "de toi yen",
    "dung noi linh tinh",
)


def _normalized(text: str) -> str:
    return " ".join(normalize_vi(str(text or "")).split()).strip().lower()


def detect_autonomous_surface_directive(user_text: str) -> str:
    """Trả ``enable``/``disable``/``""`` cho directive rõ ràng của user."""

    text = _normalized(user_text)
    if not text:
        return ""
    # Chat đời thường kéo dài chữ ("tiếnggg", "nammmm"). Co cụm từ ba ký
    # tự lặp trở lên để directive không biến mất chỉ vì user đang gõ có cảm xúc.
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    if any(marker in text for marker in _DISABLE_MARKERS):
        return "disable"
    if any(marker in text for marker in _ENABLE_MARKERS):
        return "enable"
    # Câu dài hơn có đủ ba ý: tự động + nói/tiếng + mở/chạy.
    if "tu dong" in text and any(token in text for token in ("noi", "tieng", "loa")):
        return "enable"
    return ""


def apply_autonomous_surface_preference(host: Any, user_text: str) -> AutonomousSurfacePreferenceResult:
    """Áp directive vào runtime settings và trả context cho public writer.

    Preference này làm DeepSeek Surface được cân nhắc thường xuyên hơn; nó không
    cấp quyền cho runtime phát câu hard-code. Surface unavailable thì im và thử
    lại ở nhịp sau, đúng kiểu thất bại trung thực thay vì loa phường đóng giả AI.
    """

    mode = detect_autonomous_surface_directive(user_text)
    if not mode:
        return AutonomousSurfacePreferenceResult()

    enabled = mode == "enable"
    patch = {
        "commentary": {
            "user_requested_autonomous_surface": enabled,
            "surface_only": True,
            "open_topic": True,
            "preference_updated_at": int(time.time()),
            "enabled": enabled,
            "desired_interval_seconds": 35 if enabled else 60,
            "maximum_quiet_seconds": 70 if enabled else 120,
            "startup_delay_seconds": 5 if enabled else 8,
            "minimum_user_silence_seconds": 8 if enabled else 12,
        },
        "initiative": {
            "enabled": enabled,
            "global_hourly_budget": 120 if enabled else 40,
            "minimum_interval_seconds": 25 if enabled else 60,
            "minimum_user_silence_seconds": 8 if enabled else 12,
        },
    }
    try:
        store = getattr(host, "runtime_settings_store", None) or get_runtime_settings_store(
            logger=getattr(host, "logger", None)
        )
        result = store.apply_patch(patch, materialize_env=True)
        setattr(host, "runtime_settings", result.settings)
    except Exception as exc:  # policy failure must not kill chat
        logger = getattr(host, "logger", None)
        if logger is not None:
            try:
                logger.warning("[autonomous preference] apply failed: %s", exc)
            except Exception:
                pass
        return AutonomousSurfacePreferenceResult(
            applied=False,
            mode=mode,
            reason="settings_apply_failed",
        )

    setattr(host, "_autonomous_surface_user_enabled", enabled)
    context = (
        "autonomous_surface_preference: enabled; source=user_directive; surface_only=true; "
        "cadence=35s; max_quiet=70s. The runtime already applied this preference. "
        "Acknowledge briefly; do not ask the user what content to provide and do not claim a fake action."
        if enabled
        else
        "autonomous_surface_preference: disabled; source=user_directive. The runtime already applied this preference."
    )
    logger = getattr(host, "logger", None)
    if logger is not None:
        try:
            logger.info(
                "[autonomous preference] applied mode=%s surface_only=1 desired=%ss max_quiet=%ss",
                mode,
                35 if enabled else 60,
                70 if enabled else 120,
            )
        except Exception:
            pass
    wake = getattr(host, "_wake_autonomous_loop", None)
    if enabled and callable(wake):
        try:
            wake("user_enabled_autonomous_surface")
        except Exception:
            pass
    return AutonomousSurfacePreferenceResult(
        applied=True,
        mode=mode,
        reason="user_directive",
        prompt_context=context,
    )


__all__ = [
    "AutonomousSurfacePreferenceResult",
    "detect_autonomous_surface_directive",
    "apply_autonomous_surface_preference",
]
