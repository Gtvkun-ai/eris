# -*- coding: utf-8 -*-
"""autonomous_scene_runtime.py - trạng thái sân khấu liên tục cho autonomous.

Scene classifier cũ thường nhìn từng tick độc lập. Cửa sổ mất focus vài trăm
mili-giây là mode nhảy qua lại, rồi Eris cư xử như vừa tỉnh dậy ở một vũ trụ
khác. Module này thêm hysteresis và thời gian sống cho scene:

    tín hiệu máy + observer -> candidate scene -> SceneRuntimeState ổn định

Contract chỉ dùng ý nghĩa trung tính, không chứa khái niệm riêng của Live2D.
Sau này body là Godot 3D, VRM hay một cục hình học biết chớp mắt cũng không làm
Director phải đổi schema. Tiến bộ hiếm hoi, xin đừng làm hỏng nó bằng hotkey
vendor ở tầng cognition.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping


KNOWN_SCENES = {
    "private_idle",
    "private_active",
    "coding_partner",
    "study_session",
    "game_companion",
    "media_companion",
    "stream_host",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).strip().lower()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


@dataclass(slots=True)
class SceneRuntimeConfig:
    """Các ngưỡng đổi scene.

    ``transition_hold_ms`` cố ý ngắn hơn một chu kỳ cognition đầy đủ nhưng dài
    hơn flicker focus của Windows. Scene khẩn như stream/game được phép đổi sớm
    khi confidence đủ cao.
    """

    transition_hold_ms: int = 2200
    immediate_confidence: float = 0.88
    idle_scene_after_seconds: float = 18.0

    @classmethod
    def from_env(cls) -> "SceneRuntimeConfig":
        def env_int(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, str(default)).strip())
            except (TypeError, ValueError):
                return default

        return cls(
            transition_hold_ms=max(250, env_int("ERIS_AUTONOMOUS_SCENE_HOLD_MS", 2200)),
            immediate_confidence=0.88,
            idle_scene_after_seconds=18.0,
        )


@dataclass(slots=True)
class SceneRuntimeState:
    name: str = "private_idle"
    confidence: float = 0.0
    previous_name: str = ""
    entered_at_ms: int = 0
    stable_for_ms: int = 0
    transition_seq: int = 0
    transition_reason: str = "init"
    candidate_name: str = ""
    candidate_since_ms: int = 0
    active_app: str = ""
    active_window_title: str = ""
    user_idle_ms: int = 0
    user_typing: bool = False
    focus_kind: str = "unknown"
    activity_intent: str = "unknown"

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class AutonomousSceneRuntime:
    """Giữ scene ổn định qua nhiều tick, thay vì classify rồi quên ngay."""

    def __init__(self, config: SceneRuntimeConfig | None = None) -> None:
        self.config = config or SceneRuntimeConfig.from_env()
        self.state = SceneRuntimeState()
        self._initialized = False

    def update(
        self,
        *,
        signal_snapshot: Any,
        observer_frame: Any = None,
        now_ms: int | None = None,
    ) -> SceneRuntimeState:
        now = int(now_ms if now_ms is not None else _now_ms())
        candidate, confidence, reason = self._classify(signal_snapshot, observer_frame)
        candidate = candidate if candidate in KNOWN_SCENES else "private_active"

        idle_seconds = max(0.0, _safe_float(_get(signal_snapshot, "idle_seconds", 0.0)))
        recent_events = _get(signal_snapshot, "recent_events", ()) or ()
        metadata = _get(signal_snapshot, "metadata", {}) or {}
        user_typing = self._infer_typing(recent_events, metadata, idle_seconds)
        active_app = str(_get(signal_snapshot, "active_app", "") or "")
        title = str(_get(signal_snapshot, "active_window_title", "") or "")
        focus_kind = str(_get(observer_frame, "focus_kind", _get(signal_snapshot, "focus_kind_hint", "unknown")) or "unknown")
        activity_intent = str(_get(observer_frame, "activity_intent", "unknown") or "unknown")

        if not self._initialized:
            self.state = SceneRuntimeState(
                name=candidate,
                confidence=confidence,
                previous_name="",
                entered_at_ms=now,
                stable_for_ms=0,
                transition_seq=0,
                transition_reason=f"initial:{reason}",
                active_app=active_app,
                active_window_title=title,
                user_idle_ms=int(idle_seconds * 1000),
                user_typing=user_typing,
                focus_kind=focus_kind,
                activity_intent=activity_intent,
            )
            self._initialized = True
            return self.state

        current = self.state
        transitioned = False
        if candidate == current.name:
            current.candidate_name = ""
            current.candidate_since_ms = 0
            current.confidence = max(0.0, min(1.0, confidence))
        else:
            if current.candidate_name != candidate:
                current.candidate_name = candidate
                current.candidate_since_ms = now
            held_ms = max(0, now - int(current.candidate_since_ms or now))
            immediate = confidence >= self.config.immediate_confidence and candidate in {
                "stream_host",
                "game_companion",
                "coding_partner",
            }
            if immediate or held_ms >= self.config.transition_hold_ms:
                previous = current.name
                current.name = candidate
                current.previous_name = previous
                current.entered_at_ms = now
                current.stable_for_ms = 0
                current.transition_seq += 1
                current.transition_reason = reason if not immediate else f"immediate:{reason}"
                current.confidence = max(0.0, min(1.0, confidence))
                current.candidate_name = ""
                current.candidate_since_ms = 0
                transitioned = True

        if not transitioned:
            current.stable_for_ms = max(0, now - int(current.entered_at_ms or now))
        current.active_app = active_app
        current.active_window_title = title
        current.user_idle_ms = int(idle_seconds * 1000)
        current.user_typing = user_typing
        current.focus_kind = focus_kind
        current.activity_intent = activity_intent
        return current

    def _classify(self, snapshot: Any, observer: Any) -> tuple[str, float, str]:
        metadata = _get(snapshot, "metadata", {}) or {}
        explicit = str(_get(metadata, "scene_mode", "") or "").strip().lower()
        if explicit in KNOWN_SCENES:
            return explicit, 0.98, "metadata_scene_mode"

        app = str(_get(snapshot, "active_app", "") or "")
        title = str(_get(snapshot, "active_window_title", "") or "")
        path = str(_get(snapshot, "url_or_path_hint", "") or "")
        focus = str(_get(observer, "focus_kind", _get(snapshot, "focus_kind_hint", "unknown")) or "unknown").lower()
        activity = str(_get(observer, "activity_intent", "unknown") or "unknown").lower()
        hay = _text(app, title, path, focus, activity)
        idle = max(0.0, _safe_float(_get(snapshot, "idle_seconds", 0.0)))

        if bool(_get(metadata, "stream_active", False)) or _contains_any(
            hay,
            ("obs studio", "streamlabs", "youtube studio", "twitch dashboard", "livestream", "stream host"),
        ):
            return "stream_host", 0.94, "stream_signal"

        if focus == "code" or activity in {"debugging", "designing"} or _contains_any(
            hay,
            ("visual studio code", "vscode", "pycharm", "rider", "godot", "unity", ".py", ".cs", "github"),
        ):
            return "coding_partner", 0.90, "code_focus"

        if focus == "game" or _contains_any(hay, ("mini world", "steam", "minecraft", "game client")):
            return "game_companion", 0.91, "game_focus"

        if focus in {"docs", "browser"} and activity in {"reading", "searching"}:
            return "study_session", 0.78, "reading_focus"
        if _contains_any(hay, ("pdf", "powerpoint", "notion", "google docs", "document", "slide")):
            return "study_session", 0.76, "document_focus"

        if focus == "media" or _contains_any(hay, ("youtube", "vlc", "spotify", "netflix")):
            return "media_companion", 0.80, "media_focus"

        if idle >= self.config.idle_scene_after_seconds or activity in {"idle", "resting"}:
            return "private_idle", 0.76, "idle"
        return "private_active", 0.62, "generic_active"

    @staticmethod
    def _infer_typing(recent_events: Any, metadata: Any, idle_seconds: float) -> bool:
        if isinstance(metadata, Mapping) and bool(metadata.get("typing_active", False)):
            return True
        joined = " ".join(str(item or "").lower() for item in recent_events)
        has_key_event = bool(re.search(r"\b(?:key_press|keypress|typing|text_input|keyboard)\b", joined))
        return bool(has_key_event and idle_seconds <= 3.0)


__all__ = [
    "AutonomousSceneRuntime",
    "KNOWN_SCENES",
    "SceneRuntimeConfig",
    "SceneRuntimeState",
]
