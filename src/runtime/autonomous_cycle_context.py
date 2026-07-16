# -*- coding: utf-8 -*-
"""autonomous_cycle_context.py - context bất biến cho một vòng autonomous.

Phase 7 đóng lỗi "permit vừa mở đã biến mất": observer có thể refresh evidence
nhiều lần trong một vòng, nhưng opportunity/policy đã chọn chỉ được evaluate một
lần. Context này giữ plan theo ``cycle_id`` tới lúc stage commit/cancel.

Không chứa raw text user/assistant. Vì vậy có thể đưa vào debug panel mà không
biến telemetry thành kho lưu hội thoại trá hình, một sở thích khá phổ biến của
phần mềm khi không ai để mắt.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


_FINAL_STATES = {"spoken", "suppressed", "cancelled", "failed", "expired"}


@dataclass(slots=True)
class AutonomousCycleContext:
    cycle_id: str
    created_at_ms: int
    status: str = "created"
    plan: Any = None
    observer_refresh_count: int = 0
    last_updated_ms: int = 0
    final_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, *, now_ms: int | None = None) -> "AutonomousCycleContext":
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        return cls(
            cycle_id=f"auto_{uuid.uuid4().hex[:14]}",
            created_at_ms=now,
            last_updated_ms=now,
        )

    @property
    def frozen(self) -> bool:
        return self.plan is not None and self.status in {"frozen", "generating", "staged"}

    @property
    def final(self) -> bool:
        return self.status in _FINAL_STATES

    def freeze(self, plan: Any, *, now_ms: int | None = None) -> Any:
        """Gắn plan đúng một lần; caller lặp chỉ nhận lại plan cũ."""
        if self.plan is None:
            self.plan = plan
            self.status = "frozen"
            self.last_updated_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        return self.plan

    def note_observer_refresh(self, *, now_ms: int | None = None) -> None:
        self.observer_refresh_count += 1
        self.last_updated_ms = int(now_ms if now_ms is not None else time.time() * 1000)

    def mark(self, status: str, reason: str = "", *, now_ms: int | None = None) -> None:
        clean = str(status or "").strip().lower()
        if clean:
            self.status = clean
        self.final_reason = str(reason or self.final_reason or "")
        self.last_updated_ms = int(now_ms if now_ms is not None else time.time() * 1000)

    def to_payload(self) -> dict[str, Any]:
        plan_payload = None
        if self.plan is not None:
            renderer = getattr(self.plan, "to_payload", None)
            plan_payload = renderer() if callable(renderer) else None
        return {
            "cycle_id": self.cycle_id,
            "created_at_ms": self.created_at_ms,
            "last_updated_ms": self.last_updated_ms,
            "status": self.status,
            "observer_refresh_count": self.observer_refresh_count,
            "final_reason": self.final_reason,
            "plan": plan_payload,
            "metadata": dict(self.metadata),
        }


__all__ = ["AutonomousCycleContext"]
