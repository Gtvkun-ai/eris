# -*- coding: utf-8 -*-
"""stage_profiles.py — profile nhịp sân khấu có tên, thay cho cụm công tắc rời.

Hai profile dựng sẵn:

``conversation``
    Vẫn tách câu thành beat logic để protocol/body biết nhịp, nhưng gộp audio
    thành một lượt TTS. Đây là mode nói chuyện thường, tránh khoảng hở remote TTS.

``recording``
    Phát từng beat qua queue + TtsTaskManager, prefetch song song và giữ pause
    có chủ đích. Đây là mode quay take/TikTok.

``custom``
    Tôn trọng toàn bộ setting thấp tầng cũ. Giữ lại để debug, không bắt người dùng
    phải chọn giữa hai preset như một menu máy giặt có tham vọng nghệ thuật.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StageRuntimeProfile:
    name: str
    logical_segment_tts: bool
    dispatch_mode: str
    task_manager_enabled: bool
    prefetch_workers: int
    max_tts_segments: int
    min_split_chars: int
    max_prefetch_segments: int


_PRESETS: dict[str, StageRuntimeProfile] = {
    "conversation": StageRuntimeProfile(
        name="conversation",
        logical_segment_tts=True,
        dispatch_mode="inline",
        task_manager_enabled=False,
        prefetch_workers=1,
        max_tts_segments=8,
        min_split_chars=58,
        max_prefetch_segments=4,
    ),
    "recording": StageRuntimeProfile(
        name="recording",
        logical_segment_tts=True,
        dispatch_mode="queued",
        task_manager_enabled=True,
        prefetch_workers=3,
        max_tts_segments=8,
        min_split_chars=42,
        max_prefetch_segments=8,
    ),
}


def _custom_profile() -> StageRuntimeProfile:
    """Đọc profile thấp tầng cũ tại thời điểm gọi và chuẩn hóa một lần."""

    from runtime.runtime_settings_store import runtime_bool, runtime_int, runtime_text

    dispatch = runtime_text("stage", "segment_dispatch", default="inline").strip().lower()
    if dispatch not in {"inline", "queued"}:
        dispatch = "inline"
    max_segments = max(1, min(12, runtime_int("stage", "max_tts_segments", default=8)))
    return StageRuntimeProfile(
        name="custom",
        logical_segment_tts=runtime_bool("stage", "segment_tts", default=True),
        dispatch_mode=dispatch,
        task_manager_enabled=runtime_bool("stage", "tts_task_manager", default=False),
        prefetch_workers=max(1, min(6, runtime_int("stage", "prefetch_workers", default=2))),
        max_tts_segments=max_segments,
        min_split_chars=max(24, min(160, runtime_int("stage", "min_split_chars", default=58))),
        max_prefetch_segments=max_segments,
    )


def active_stage_profile() -> StageRuntimeProfile:
    """Trả profile hiệu lực; env chỉ là override tạm cho CLI/test/take."""

    env_name = str(os.environ.get("ERIS_STAGE_PROFILE", "") or "").strip().lower()
    if env_name in _PRESETS:
        return _PRESETS[env_name]

    from runtime.runtime_settings_store import runtime_text

    name = runtime_text("stage", "performance_profile", default="conversation").strip().lower()
    if name in _PRESETS:
        return _PRESETS[name]

    # custom: các nút thấp tầng cũ vẫn còn tác dụng. Clamp tập trung để config
    # hỏng không biến queue thành đàn châu chấu.
    return _custom_profile()



def stage_profile(name: str) -> StageRuntimeProfile:
    key = str(name or "").strip().lower()
    if key in _PRESETS:
        return _PRESETS[key]
    if key == "custom":
        # Đọc custom tại thời điểm gọi để panel live apply có hiệu lực ngay.
        # Không sửa os.environ tạm thời: hai thread đọc profile cùng lúc thì trò
        # ảo thuật đó rất dễ biến thành race khó truy vết.
        return _custom_profile()
    return active_stage_profile()


def stage_profile_payload() -> dict[str, object]:
    profile = active_stage_profile()
    return {
        "name": profile.name,
        "logical_segment_tts": profile.logical_segment_tts,
        "segment_dispatch": profile.dispatch_mode,
        "tts_task_manager": profile.task_manager_enabled,
        "prefetch_workers": profile.prefetch_workers,
        "max_tts_segments": profile.max_tts_segments,
        "min_split_chars": profile.min_split_chars,
        "max_prefetch_segments": profile.max_prefetch_segments,
    }


__all__ = ["StageRuntimeProfile", "active_stage_profile", "stage_profile", "stage_profile_payload"]
