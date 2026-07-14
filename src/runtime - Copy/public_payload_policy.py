# -*- coding: utf-8 -*-
"""Chính sách metadata gửi từ Python sang Godot.

Runtime vẫn giữ đầy đủ parse/debug trace trong memory và log debug. Payload công
khai mặc định chỉ chứa những gì body cần để hiện chữ, cử động và phát TTS.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


_INTERNAL_DEBUG_FIELDS = (
    "debug_trace",
    "parser_trace",
    "parse_mode",
    "reasoning_tags",
)


def body_debug_metadata_enabled() -> bool:
    return os.environ.get("ERIS_BODY_DEBUG_METADATA", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def sanitize_body_payload(
    payload: Mapping[str, Any],
    *,
    include_debug: bool | None = None,
) -> dict[str, Any]:
    """Copy payload và bỏ metadata parser khi body không ở chế độ debug."""

    result = dict(payload or {})
    enabled = body_debug_metadata_enabled() if include_debug is None else bool(include_debug)
    if enabled:
        return result
    for key in _INTERNAL_DEBUG_FIELDS:
        result.pop(key, None)
    return result


__all__ = ["body_debug_metadata_enabled", "sanitize_body_payload"]
