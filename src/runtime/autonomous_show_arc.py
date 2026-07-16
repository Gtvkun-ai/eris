# -*- coding: utf-8 -*-
"""autonomous_show_arc.py - giữ mạch sân khấu xuyên nhiều lần Eris chủ động nói.

SessionDirector quyết định mật độ và cadence. ShowArcDirector giữ một tầng khác:
Eris đang *mở một nhịp*, đang callback một sự kiện cũ, đang đẩy cao xung đột,
hay đang trả payoff rồi rời sân khấu. Nếu thiếu tầng này, mỗi câu autonomous có
thể hay riêng lẻ nhưng cả phiên vẫn nghe như một túi câu ngẫu nhiên bị lắc đều.

Module chỉ phát ý đồ trung tính: arc, line shape, opening/closing mode. Không có
Live2D hotkey, tên blendshape hay phụ thuộc avatar cụ thể. Body 3D sau này chỉ
cần map các ý đồ này sang gaze/gesture phù hợp.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from runtime.autonomous_opportunity import AutonomousOpportunity
from runtime.autonomous_scene_runtime import SceneRuntimeState
from runtime.autonomous_session_director import SessionDirective


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(1, int(limit))]


def _opening_signature(text: str) -> str:
    """Lấy 2-3 từ mở đầu để prompt lượt sau tránh lặp khuôn câu."""
    normalized = re.sub(r"[^0-9A-Za-zÀ-ỹĐđ]+", " ", str(text or "").lower())
    words = [item for item in normalized.split() if item]
    return " ".join(words[:3])


@dataclass(slots=True)
class ShowArcConfig:
    arc_timeout_ms: int = 12 * 60_000
    callback_window_ms: int = 8 * 60_000
    resolved_grace_ms: int = 90_000
    recent_surface_size: int = 8
    max_beats_per_arc: int = 4

    @classmethod
    def from_env(cls) -> "ShowArcConfig":
        def env_int(name: str, default: int) -> int:
            try:
                return int(str(os.environ.get(name, default)).strip())
            except (TypeError, ValueError):
                return default

        return cls(
            arc_timeout_ms=max(60_000, env_int("ERIS_AUTONOMOUS_ARC_TIMEOUT_MS", 12 * 60_000)),
            callback_window_ms=max(30_000, env_int("ERIS_AUTONOMOUS_CALLBACK_WINDOW_MS", 8 * 60_000)),
            resolved_grace_ms=max(10_000, env_int("ERIS_AUTONOMOUS_RESOLVED_GRACE_MS", 90_000)),
            recent_surface_size=max(4, min(24, env_int("ERIS_AUTONOMOUS_SURFACE_HISTORY", 8))),
            max_beats_per_arc=max(2, min(8, env_int("ERIS_AUTONOMOUS_MAX_BEATS_PER_ARC", 4))),
        )


@dataclass(slots=True)
class _ShowArcState:
    arc_id: str
    family: str
    scene_mode: str
    anchor_kind: str
    opened_at_ms: int
    last_touched_ms: int
    beat_count: int = 0
    resolved: bool = False
    last_kind: str = ""
    last_hook_id: str = ""
    callback_anchor: str = ""


@dataclass(frozen=True, slots=True)
class ShowArcDirective:
    """Contract nhỏ được gửi vào prompt và Stage planner."""

    arc_id: str
    arc_family: str
    arc_stage: str
    continuity_mode: str
    line_shape: str
    opening_mode: str
    closing_mode: str
    callback_anchor: str
    avoid_openings: tuple[str, ...]
    novelty_target: float
    escalation_level: int
    reason: str

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["avoid_openings"] = list(self.avoid_openings)
        return payload


class AutonomousShowArcDirector:
    """Tạo mạch setup -> callback/escalation -> payoff -> release.

    Đây không phải một máy viết kịch bản dài. Mỗi arc chỉ giữ vài beat ngắn và
    tự hết hạn. Mục tiêu là continuity vừa đủ để Eris có cảm giác đang biểu diễn,
    không biến autonomous thành độc thoại dài về chính nó.
    """

    _SHAPE_ROTATION = (
        "single_strike",
        "observation_turn",
        "setup_payoff",
        "quiet_callback",
        "technical_two_step",
    )

    def __init__(self, config: ShowArcConfig | None = None) -> None:
        self.config = config or ShowArcConfig.from_env()
        self.active_arc: _ShowArcState | None = None
        self._recent_line_shapes: deque[str] = deque(maxlen=self.config.recent_surface_size)
        self._recent_openings: deque[str] = deque(maxlen=self.config.recent_surface_size)
        self._recent_text_fingerprints: deque[str] = deque(maxlen=self.config.recent_surface_size)

    def direct(
        self,
        *,
        scene: SceneRuntimeState,
        opportunity: AutonomousOpportunity | None,
        session_directive: SessionDirective | None = None,
        now_ms: int | None = None,
    ) -> ShowArcDirective:
        now = int(now_ms if now_ms is not None else _now_ms())
        self._expire_arc(now)

        if opportunity is None:
            return ShowArcDirective(
                arc_id=str(getattr(self.active_arc, "arc_id", "") or ""),
                arc_family=str(getattr(self.active_arc, "family", "silent_presence") or "silent_presence"),
                arc_stage="hold",
                continuity_mode="none",
                line_shape="silent_presence",
                opening_mode="none",
                closing_mode="none",
                callback_anchor="",
                avoid_openings=tuple(self._recent_openings),
                novelty_target=0.0,
                escalation_level=0,
                reason="no_selected_opportunity",
            )

        kind = str(opportunity.kind or "autonomous")
        family = self._family_for(kind)
        stage, continuity, reuse_active = self._stage_for(
            kind=kind,
            family=family,
            scene=scene,
            now=now,
        )

        # Planning phải thuần dữ liệu. Không mở/advance arc ở đây vì permit hoặc
        # StageScorer còn có thể chặn câu. Arc chỉ thành sự thật trong record_spoken.
        if reuse_active and self.active_arc is not None:
            arc = self.active_arc
        else:
            arc = _ShowArcState(
                arc_id=f"arc_{uuid.uuid4().hex[:12]}",
                family=family,
                scene_mode=str(scene.name or opportunity.scene_mode or "private_idle"),
                anchor_kind=kind,
                opened_at_ms=now,
                last_touched_ms=now,
                callback_anchor=kind,
            )
        line_shape = self._choose_line_shape(
            kind=kind,
            stage=stage,
            scene=str(scene.name or "private_idle"),
        )
        opening_mode, closing_mode = self._stage_modes(kind=kind, stage=stage)
        beat_count = int(getattr(arc, "beat_count", 0) or 0)
        escalation = min(3, max(0, beat_count if stage in {"callback", "escalation"} else 0))
        callback_anchor = self._callback_anchor(arc, kind=kind, stage=stage)
        novelty = 0.62
        if line_shape in self._recent_line_shapes:
            novelty += 0.12
        if stage in {"callback", "escalation", "payoff"}:
            novelty += 0.08
        if session_directive is not None:
            novelty += float(getattr(session_directive, "audience_fatigue", 0.0) or 0.0) * 0.12
        novelty = max(0.45, min(0.95, novelty))

        reason = (
            f"family={str(getattr(arc, 'family', family))};stage={stage};"
            f"continuity={continuity};shape={line_shape};beats={beat_count}"
        )
        return ShowArcDirective(
            arc_id=str(getattr(arc, "arc_id", "") or ""),
            arc_family=str(getattr(arc, "family", family) or family),
            arc_stage=stage,
            continuity_mode=continuity,
            line_shape=line_shape,
            opening_mode=opening_mode,
            closing_mode=closing_mode,
            callback_anchor=callback_anchor,
            avoid_openings=tuple(self._recent_openings),
            novelty_target=novelty,
            escalation_level=escalation,
            reason=reason,
        )

    def record_spoken(
        self,
        *,
        text: str,
        opportunity: AutonomousOpportunity | None,
        directive: ShowArcDirective | None,
        intent: str = "",
        hook_id: str = "",
        at_ms: int | None = None,
    ) -> None:
        """Commit arc chỉ sau khi câu public thật sự được gửi.

        Không gọi ở bước candidate. Nếu provider lỗi hoặc scorer chặn, arc không
        được phép tự tưởng tượng rằng một beat đã xảy ra.
        """
        now = int(at_ms if at_ms is not None else _now_ms())
        clean_text = _clean(text)
        opening = _opening_signature(clean_text)
        if opening:
            self._recent_openings.append(opening)
        fingerprint = re.sub(r"\s+", " ", clean_text.lower()).strip()
        if fingerprint:
            self._recent_text_fingerprints.append(fingerprint[:160])
        if directive is not None and directive.line_shape:
            self._recent_line_shapes.append(directive.line_shape)

        arc = self.active_arc
        if directive is None:
            return
        if arc is None or directive.arc_id != arc.arc_id:
            # Đây là commit đầu tiên của một arc mới. Trước mốc này directive chỉ
            # là proposal, tránh phantom continuity khi provider/scorer thất bại.
            arc = _ShowArcState(
                arc_id=directive.arc_id or f"arc_{uuid.uuid4().hex[:12]}",
                family=directive.arc_family or self._family_for(str(getattr(opportunity, "kind", "") or "autonomous")),
                scene_mode=str(getattr(opportunity, "scene_mode", "private_idle") or "private_idle"),
                anchor_kind=str(getattr(opportunity, "kind", "autonomous") or "autonomous"),
                opened_at_ms=now,
                last_touched_ms=now,
            )
            self.active_arc = arc
        arc.beat_count += 1
        arc.last_touched_ms = now
        arc.last_kind = str(getattr(opportunity, "kind", "") or "")
        arc.last_hook_id = _clean(hook_id, 96)
        # Anchor ưu tiên hook vì nó mô tả mạch nội dung tốt hơn tên opportunity.
        arc.callback_anchor = arc.last_hook_id or arc.last_kind or _clean(intent, 64) or arc.anchor_kind
        if directive.arc_stage == "payoff" or arc.beat_count >= self.config.max_beats_per_arc:
            arc.resolved = True

    def snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        now = int(now_ms if now_ms is not None else _now_ms())
        self._expire_arc(now)
        arc = self.active_arc
        return {
            "active_arc": {
                "arc_id": str(getattr(arc, "arc_id", "") or ""),
                "family": str(getattr(arc, "family", "") or ""),
                "scene_mode": str(getattr(arc, "scene_mode", "") or ""),
                "anchor_kind": str(getattr(arc, "anchor_kind", "") or ""),
                "beat_count": int(getattr(arc, "beat_count", 0) or 0),
                "resolved": bool(getattr(arc, "resolved", False)),
                "last_kind": str(getattr(arc, "last_kind", "") or ""),
                "last_hook_id": str(getattr(arc, "last_hook_id", "") or ""),
            },
            "recent_line_shapes": list(self._recent_line_shapes),
            "recent_openings": list(self._recent_openings),
        }

    def _expire_arc(self, now: int) -> None:
        arc = self.active_arc
        if arc is None:
            return
        age = now - arc.last_touched_ms
        limit = self.config.resolved_grace_ms if arc.resolved else self.config.arc_timeout_ms
        if age > limit:
            self.active_arc = None

    @staticmethod
    def _family_for(kind: str) -> str:
        if kind == "new_error":
            return "problem_thread"
        if kind == "task_progress":
            return "progress_moment"
        if kind == "scene_transition":
            return "scene_entry"
        if kind == "return_after_idle":
            return "reentry"
        if kind == "long_focus":
            return "focus_thread"
        if kind == "dead_air":
            return "ambient_presence"
        return "reaction_thread"

    def _stage_for(
        self,
        *,
        kind: str,
        family: str,
        scene: SceneRuntimeState,
        now: int,
    ) -> tuple[str, str, bool]:
        arc = self.active_arc
        if arc is None:
            return "setup", "new_arc", False
        same_scene = str(arc.scene_mode or "") == str(scene.name or "")
        recent = now - arc.last_touched_ms <= self.config.callback_window_ms

        if kind == "task_progress" and arc.family == "problem_thread" and same_scene and recent and not arc.resolved:
            return "payoff", "resolve_previous_problem", True
        if kind == "new_error" and arc.family == "problem_thread" and same_scene and recent and not arc.resolved:
            if arc.beat_count <= 1:
                return "escalation", "same_problem_family", True
            return "callback", "compressed_problem_callback", True
        if kind == "dead_air" and same_scene and recent and arc.beat_count > 0 and not arc.resolved:
            return "callback", "quiet_callback_to_open_arc", True
        if family == arc.family and same_scene and recent and not arc.resolved:
            return "callback", "same_arc_family", True
        return "setup", "new_arc", False

    def _choose_line_shape(self, *, kind: str, stage: str, scene: str) -> str:
        if stage == "payoff":
            preferred = "setup_payoff"
        elif stage == "callback":
            preferred = "quiet_callback"
        elif stage == "escalation":
            preferred = "observation_turn"
        elif kind == "new_error" and scene == "coding_partner":
            preferred = "technical_two_step"
        elif kind in {"scene_transition", "return_after_idle"}:
            preferred = "observation_turn"
        elif kind in {"dead_air", "long_focus"}:
            preferred = "single_strike"
        else:
            preferred = "setup_payoff"

        # Không lặp nguyên shape ở hai act liên tiếp nếu có lựa chọn hợp lý khác.
        if not self._recent_line_shapes or self._recent_line_shapes[-1] != preferred:
            return preferred
        for candidate in self._SHAPE_ROTATION:
            if candidate != preferred and candidate not in tuple(self._recent_line_shapes)[-2:]:
                if kind == "new_error" and candidate == "quiet_callback":
                    continue
                return candidate
        return preferred

    @staticmethod
    def _stage_modes(*, kind: str, stage: str) -> tuple[str, str]:
        if stage == "payoff":
            return "release_hold", "clean_release"
        if stage == "callback":
            return "recognition_hold", "soft_return"
        if stage == "escalation":
            return "quick_focus", "focused_hold"
        if kind == "new_error":
            return "quick_focus", "focused_hold"
        if kind == "dead_air":
            return "ambient_hold", "linger_short"
        if kind == "return_after_idle":
            return "reentry_hold", "soft_return"
        return "scene_set", "neutral_settle"

    @staticmethod
    def _callback_anchor(arc: _ShowArcState | None, *, kind: str, stage: str) -> str:
        if arc is None or stage not in {"callback", "escalation", "payoff"}:
            return ""
        return _clean(arc.callback_anchor or arc.last_hook_id or arc.last_kind or kind, 96)


__all__ = [
    "AutonomousShowArcDirector",
    "ShowArcConfig",
    "ShowArcDirective",
]
