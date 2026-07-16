# -*- coding: utf-8 -*-
"""autonomous_debug_snapshot.py - snapshot giải thích vì sao Eris nói hoặc im.

Snapshot chỉ giữ metadata policy, không giữ public text, prompt hay transcript.
Nó phù hợp để hiển thị trên panel debug mà không vô tình biến panel thành một
bản sao lịch sử hội thoại, vì dự án này đã có đủ nơi để state sinh sôi rồi.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from typing import Any, Mapping

from runtime.autonomous_version import AUTONOMOUS_STAGE_ARCHITECTURE_VERSION


def _now_ms() -> int:
    return int(time.time() * 1000)


class AutonomousDebugSnapshotStore:
    VERSION = "autonomous_debug_snapshot.v1"

    def __init__(self, *, history_size: int = 48) -> None:
        self._decisions: deque[dict[str, Any]] = deque(maxlen=max(8, history_size))
        self._commits: deque[dict[str, Any]] = deque(maxlen=max(8, history_size // 2))
        self._suppression_counts: Counter[str] = Counter()
        self._last_audit: dict[str, Any] = {}

    def record_plan(
        self,
        plan: Any,
        *,
        policy_decision: Any = None,
        audit_snapshot: Any = None,
    ) -> None:
        permit = getattr(plan, "permit", None)
        scene = getattr(plan, "scene", None)
        opportunity = getattr(plan, "selected_opportunity", None)
        directive = getattr(plan, "session_directive", None)
        preset = getattr(plan, "stage_preset", None)
        feedback = getattr(plan, "audience_feedback", None)
        policy = policy_decision or getattr(plan, "policy_decision", None)
        blockers = tuple(getattr(policy, "blockers", ()) or ())
        conflicts = tuple(getattr(policy, "conflict_flags", ()) or ())
        reason = str(getattr(permit, "reason", "unknown") or "unknown")
        allowed = bool(getattr(permit, "allowed", False))
        if not allowed:
            self._suppression_counts[reason[:120]] += 1

        item = {
            "evaluated_at_ms": int(getattr(plan, "evaluated_at_ms", _now_ms()) or _now_ms()),
            "scene": str(getattr(scene, "name", "unknown") or "unknown"),
            "opportunity_id": str(getattr(opportunity, "opportunity_id", "") or ""),
            "opportunity_kind": str(getattr(opportunity, "kind", "none") or "none"),
            "opportunity_strength": round(float(getattr(opportunity, "strength", 0.0) or 0.0), 3),
            "allowed": allowed,
            "mode": str(getattr(permit, "mode", "suppress") or "suppress"),
            "max_words": int(getattr(permit, "max_words", 0) or 0),
            "cooldown_after_ms": int(getattr(permit, "cooldown_after_ms", 0) or 0),
            "reason": reason,
            "phase": str(getattr(directive, "phase", "unknown") or "unknown"),
            "cadence": str(getattr(directive, "cadence", "unknown") or "unknown"),
            "preset_id": str(getattr(preset, "preset_id", "legacy.default") or "legacy.default"),
            "feedback_mode": str(getattr(feedback, "mode", "normal") or "normal"),
            "blockers": list(blockers),
            "conflicts": list(conflicts),
        }
        self._decisions.append(item)
        if audit_snapshot is not None:
            payload = getattr(audit_snapshot, "to_payload", None)
            self._last_audit = payload() if callable(payload) else dict(audit_snapshot or {})

    def record_commit(
        self,
        plan: Any,
        *,
        intent: str = "",
        hook_id: str = "",
        at_ms: int | None = None,
    ) -> None:
        opportunity = getattr(plan, "selected_opportunity", None)
        scene = getattr(plan, "scene", None)
        self._commits.append(
            {
                "committed_at_ms": int(at_ms if at_ms is not None else _now_ms()),
                "scene": str(getattr(scene, "name", "unknown") or "unknown"),
                "opportunity_id": str(getattr(opportunity, "opportunity_id", "") or ""),
                "opportunity_kind": str(getattr(opportunity, "kind", "unknown") or "unknown"),
                "intent": str(intent or "")[:64],
                "hook_id": str(hook_id or "")[:96],
            }
        )

    def snapshot(
        self,
        *,
        audit_snapshot: Any = None,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        audit = self._last_audit
        if audit_snapshot is not None:
            payload = getattr(audit_snapshot, "to_payload", None)
            audit = payload() if callable(payload) else dict(audit_snapshot or {})
        current = self._decisions[-1] if self._decisions else None
        return {
            "contract": AUTONOMOUS_STAGE_ARCHITECTURE_VERSION,
            "snapshot_version": self.VERSION,
            "observed_at_ms": int(now_ms if now_ms is not None else _now_ms()),
            "current": dict(current) if isinstance(current, Mapping) else current,
            "recent_decisions": [dict(item) for item in list(self._decisions)[-12:]],
            "recent_commits": [dict(item) for item in list(self._commits)[-8:]],
            "suppression_summary": [
                {"reason": reason, "count": count}
                for reason, count in sorted(
                    self._suppression_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:12]
            ],
            "audit": dict(audit or {}),
        }


__all__ = ["AutonomousDebugSnapshotStore"]
