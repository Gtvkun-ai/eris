# -*- coding: utf-8 -*-
"""Repair-state có TTL và số lượt hữu hạn.

State này không tự phát hiện lỗi. Nó chỉ giữ vòng đời của một repair đã được
TurnFrame/repair policy xác nhận, để rerun lỗi không biến thành vòng lặp vĩnh cửu.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class RepairState:
    active: bool = False
    started_at: float = 0.0
    turns_left: int = 0
    fallback_used: bool = False
    target: str = ""
    exhausted: bool = False


class RepairStateController:
    def __init__(self, *, ttl_s: float = 60.0, max_public_turns: int = 2) -> None:
        self.ttl_s = max(1.0, float(ttl_s))
        self.max_public_turns = max(1, int(max_public_turns))
        self.state = RepairState()

    def begin(self, *, target: str = "", now: float | None = None, force: bool = False) -> RepairState:
        if self.state.exhausted and not force:
            return self.state
        self.state = RepairState(
            active=True,
            started_at=time.monotonic() if now is None else float(now),
            turns_left=self.max_public_turns,
            fallback_used=False,
            target=str(target or ""),
            exhausted=False,
        )
        return self.state

    def available(self, *, now: float | None = None) -> bool:
        if not self.state.active:
            return False
        ts = time.monotonic() if now is None else float(now)
        if ts - self.state.started_at > self.ttl_s or self.state.turns_left <= 0:
            self.exhaust()
            return False
        return True

    def consume_public_turn(self, *, now: float | None = None) -> bool:
        if not self.available(now=now):
            return False
        self.state.turns_left -= 1
        if self.state.turns_left <= 0:
            self.exhaust()
        return True

    def consume_fallback_once(self, *, now: float | None = None) -> bool:
        if not self.available(now=now) or self.state.fallback_used:
            self.exhaust()
            return False
        self.state.fallback_used = True
        self.state.turns_left -= 1
        return True

    def exhaust(self) -> None:
        self.state.active = False
        self.state.turns_left = 0
        self.state.exhausted = True

    def clear(self) -> None:
        """Topic đã đổi hoặc user đã chấp nhận; cho phép repair mới sau đó."""
        self.state = RepairState()


__all__ = ["RepairState", "RepairStateController"]
