# -*- coding: utf-8 -*-
"""autonomous_long_run_audit.py - kiểm toán nhịp autonomous dài hạn.

Unit test từng lượt không phát hiện được các bệnh chỉ lộ sau 30-60 phút: permit
lặp mà không commit, một loại opportunity chiếm sóng, mật độ thoại vượt preset,
hoặc hệ im quá lâu dù liên tục thấy cơ hội đủ mạnh. Audit này không sinh lời và
không thay đổi policy; nó chỉ ghi các sự kiện an toàn rồi trả báo cáo có thể đưa
lên debug panel/telemetry.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Any

from runtime.autonomous_version import AUTONOMOUS_STAGE_ARCHITECTURE_VERSION


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class AutonomousAuditConfig:
    window_ms: int = 3_600_000
    pending_permit_timeout_ms: int = 120_000
    max_lines_per_hour: int = 12
    max_same_kind_streak: int = 3
    max_orphaned_permits: int = 2
    healthy_commit_ratio_floor: float = 0.35


@dataclass(frozen=True, slots=True)
class AutonomousAuditSnapshot:
    version: str
    status: str
    evaluations_total: int
    unique_permits_total: int
    commits_total: int
    lines_last_hour: int
    max_same_kind_streak: int
    pending_permits: int
    orphaned_permits: int
    commit_ratio: float
    suppression_reasons: tuple[tuple[str, int], ...]
    recent_kinds: tuple[str, ...]
    violations: tuple[str, ...]
    observed_at_ms: int

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["suppression_reasons"] = [
            {"reason": reason, "count": count}
            for reason, count in self.suppression_reasons
        ]
        payload["recent_kinds"] = list(self.recent_kinds)
        payload["violations"] = list(self.violations)
        return payload


class AutonomousLongRunAudit:
    """Tích lũy thống kê theo timestamp; test có thể mô phỏng một giờ tức thì."""

    VERSION = "autonomous_long_run_audit.v1"

    def __init__(self, config: AutonomousAuditConfig | None = None) -> None:
        self.config = config or AutonomousAuditConfig()
        self.evaluations_total = 0
        self.unique_permits_total = 0
        self.commits_total = 0
        self._commit_history: deque[tuple[int, str]] = deque(maxlen=512)
        self._recent_kinds: deque[str] = deque(maxlen=32)
        self._suppression_reasons: Counter[str] = Counter()
        self._pending_permits: dict[str, tuple[int, str]] = {}
        self._seen_permit_ids: set[str] = set()
        self._orphaned_permits = 0
        self._max_same_kind_streak_seen = 0

    def observe_plan(self, plan: Any, *, now_ms: int | None = None) -> None:
        now = int(now_ms if now_ms is not None else _now_ms())
        self.evaluations_total += 1
        self._expire_pending(now)

        permit = getattr(plan, "permit", None)
        opportunity = getattr(plan, "selected_opportunity", None)
        allowed = bool(getattr(permit, "allowed", False))
        opportunity_id = str(getattr(opportunity, "opportunity_id", "") or "")
        kind = str(getattr(opportunity, "kind", "none") or "none")
        if allowed and opportunity_id:
            if opportunity_id not in self._seen_permit_ids:
                self._seen_permit_ids.add(opportunity_id)
                self.unique_permits_total += 1
            self._pending_permits.setdefault(opportunity_id, (now, kind))
        elif not allowed:
            reason = str(getattr(permit, "reason", "unknown") or "unknown")
            self._suppression_reasons[reason[:120]] += 1

    def record_commit(self, plan: Any, *, at_ms: int | None = None) -> None:
        now = int(at_ms if at_ms is not None else _now_ms())
        self._expire_pending(now)
        opportunity = getattr(plan, "selected_opportunity", None)
        opportunity_id = str(getattr(opportunity, "opportunity_id", "") or "")
        kind = str(getattr(opportunity, "kind", "unknown") or "unknown")
        self.commits_total += 1
        self._commit_history.append((now, kind))
        self._recent_kinds.append(kind)
        if opportunity_id:
            self._pending_permits.pop(opportunity_id, None)
        self._max_same_kind_streak_seen = max(
            self._max_same_kind_streak_seen,
            self._tail_same_kind_streak(),
        )

    def snapshot(self, *, now_ms: int | None = None) -> AutonomousAuditSnapshot:
        now = int(now_ms if now_ms is not None else _now_ms())
        self._expire_pending(now)
        cutoff = now - max(1, int(self.config.window_ms))
        while self._commit_history and self._commit_history[0][0] < cutoff:
            self._commit_history.popleft()

        lines_last_hour = len(self._commit_history)
        ratio = self.commits_total / max(1.0, float(self.unique_permits_total))
        violations: list[str] = []
        if lines_last_hour > self.config.max_lines_per_hour:
            violations.append("speech_density_exceeded")
        if self._max_same_kind_streak_seen > self.config.max_same_kind_streak:
            violations.append("same_kind_streak_exceeded")
        if self._orphaned_permits > self.config.max_orphaned_permits:
            violations.append("orphaned_permit_budget_exceeded")
        if self.unique_permits_total >= 4 and ratio < self.config.healthy_commit_ratio_floor:
            violations.append("permit_commit_ratio_too_low")

        severe = {
            "speech_density_exceeded",
            "same_kind_streak_exceeded",
        }
        if any(item in severe for item in violations):
            status = "violation"
        elif violations:
            status = "warning"
        else:
            status = "ok"

        suppressions = tuple(
            sorted(self._suppression_reasons.items(), key=lambda item: (-item[1], item[0]))[:12]
        )
        return AutonomousAuditSnapshot(
            version=AUTONOMOUS_STAGE_ARCHITECTURE_VERSION,
            status=status,
            evaluations_total=self.evaluations_total,
            unique_permits_total=self.unique_permits_total,
            commits_total=self.commits_total,
            lines_last_hour=lines_last_hour,
            max_same_kind_streak=self._max_same_kind_streak_seen,
            pending_permits=len(self._pending_permits),
            orphaned_permits=self._orphaned_permits,
            commit_ratio=max(0.0, min(1.0, ratio)),
            suppression_reasons=suppressions,
            recent_kinds=tuple(self._recent_kinds)[-12:],
            violations=tuple(violations),
            observed_at_ms=now,
        )

    def _expire_pending(self, now_ms: int) -> None:
        timeout = max(5_000, int(self.config.pending_permit_timeout_ms))
        expired = [
            opportunity_id
            for opportunity_id, (first_seen, _kind) in self._pending_permits.items()
            if now_ms - first_seen >= timeout
        ]
        for opportunity_id in expired:
            self._pending_permits.pop(opportunity_id, None)
            self._orphaned_permits += 1

    def _tail_same_kind_streak(self) -> int:
        if not self._recent_kinds:
            return 0
        target = self._recent_kinds[-1]
        streak = 0
        for kind in reversed(self._recent_kinds):
            if kind != target:
                break
            streak += 1
        return streak


__all__ = [
    "AutonomousAuditConfig",
    "AutonomousAuditSnapshot",
    "AutonomousLongRunAudit",
]
