# -*- coding: utf-8 -*-
"""Quan sát neo bề mặt cho câu autonomous, không chỉnh final.

Module phát hiện tiền đề thiếu evidence và tạo metadata hậu quả. Nó không còn là
guard: không rewrite, không suppress, không body-only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").replace("đ", "d")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_\s]", " ", text)).strip()


def _clean(value: Any, limit: int = 280) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


@dataclass(frozen=True, slots=True)
class AutonomousAnchorObservation:
    accepted: bool
    text: str
    original_text: str
    reason: str
    opportunity_kind: str
    evidence_refs: tuple[str, ...]
    unsupported: tuple[str, ...]
    rewritten: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["unsupported"] = list(self.unsupported)
        return payload


class AutonomousSurfaceAnchorObserver:
    VERSION = "autonomous_anchor.v1"

    _TECH_MARKERS = ("bug", "loi", "test", "repo", "parser", "network", "tts", "phan kho", "nut that")
    _USER_STATE_MARKERS = ("ban dang", "ban co ve", "ban buon", "ban lo", "ban muon", "ban met", "ban buc")
    _SCREEN_MARKERS = ("toi thay", "man hinh", "cua so", "tab", "dong code", "khung meet")
    _AUDIENCE_MARKERS = ("chat", "khan gia", "moi nguoi", "ca phong")
    _CONTINUITY_MARKERS = ("lai ", "tiep tuc", "van nhu", "nhu lan truoc")
    _HOLLOW_TASK_MARKERS = ("vao viec", "giao toi", "phan kho nhat", "bat dau tu dau", "dua viec day")

    def validate(self, text: str, autonomous_plan: Mapping[str, Any] | None) -> AutonomousAnchorObservation:
        original = _clean(text)
        plan = autonomous_plan if isinstance(autonomous_plan, Mapping) else {}
        opportunity = plan.get("selected_opportunity") if isinstance(plan.get("selected_opportunity"), Mapping) else {}
        scene = plan.get("scene") if isinstance(plan.get("scene"), Mapping) else {}
        show_format = plan.get("show_format") if isinstance(plan.get("show_format"), Mapping) else {}
        kind = str(opportunity.get("kind", "") or "")
        evidence = tuple(str(x) for x in (opportunity.get("evidence_refs") or []) if str(x))
        evidence_norm = " ".join(_norm(x) for x in evidence)
        scene_name = str(scene.get("name", "") or "")
        normalized = _norm(original)
        unsupported: list[str] = []

        has_technical = kind in {"new_error", "repeated_error", "task_failure", "error_loop", "task_progress", "task_complete"} or any(
            token in evidence_norm for token in ("error", "bug", "task", "test", "tts", "network", "parser")
        )
        has_screen = any(token in evidence_norm for token in ("screen", "active_app", "window", "uia", "ocr"))
        has_audience = scene_name in {"stream_host", "collab", "announcement"} and any(
            token in evidence_norm for token in ("chat", "audience", "stream", "viewer")
        )
        has_continuity = kind in {"return_after_idle", "scene_transition", "running_bit", "topic_callback", "memory_callback", "session_return"}
        has_user_state = any(token in evidence_norm for token in ("typing", "idle", "user_text", "explicit_emotion"))

        if any(marker in normalized for marker in self._HOLLOW_TASK_MARKERS) and not has_technical:
            unsupported.append("hollow_task_premise")
        if any(marker in normalized for marker in self._TECH_MARKERS) and not has_technical:
            unsupported.append("technical_claim_without_anchor")
        if any(marker in normalized for marker in self._USER_STATE_MARKERS) and not has_user_state:
            unsupported.append("user_state_without_anchor")
        if any(marker in normalized for marker in self._SCREEN_MARKERS) and not has_screen:
            unsupported.append("screen_claim_without_anchor")
        if any(marker in normalized for marker in self._AUDIENCE_MARKERS) and not has_audience:
            unsupported.append("audience_without_anchor")
        if any(marker in normalized for marker in self._CONTINUITY_MARKERS) and not has_continuity:
            unsupported.append("continuity_without_anchor")
        if str(show_format.get("anchor_policy", "")) == "require_surface_anchor" and not evidence and kind not in {"dead_air", "idle_presence", "presence_maintenance"}:
            unsupported.append("missing_surface_anchor")

        unsupported = list(dict.fromkeys(unsupported))
        return AutonomousAnchorObservation(
            accepted=True,
            text=original,
            original_text=original,
            reason="anchored" if not unsupported else "passthrough_unsupported_logged",
            opportunity_kind=kind,
            evidence_refs=evidence,
            unsupported=tuple(unsupported),
            rewritten=False,
        )



# Compatibility aliases for older imports.
AutonomousAnchorVerdict = AutonomousAnchorObservation
AutonomousSurfaceAnchorGuard = AutonomousSurfaceAnchorObserver

__all__ = [
    "AutonomousAnchorObservation",
    "AutonomousSurfaceAnchorObserver",
    "AutonomousAnchorVerdict",
    "AutonomousSurfaceAnchorGuard",
]
