# -*- coding: utf-8 -*-
"""Một scheduler continuation duy nhất cho public conversation V12.

Scheduler chỉ quản lý lease + generation. Nó không lưu "ý tiếp theo", không
chọn thread và không replay text. Khi lease đến hạn, caller phải gọi lại RootAgent.
"""
from __future__ import annotations

from dataclasses import replace
import threading
import time
import uuid
from typing import Any

from .contracts import ConversationAfter, ContinuationLease


class ContinuationLeaseScheduler:
    def __init__(self, *, logger: Any = None) -> None:
        self.logger = logger
        self._lock = threading.RLock()
        self._leases: dict[str, ContinuationLease] = {}

    def schedule(
        self,
        *,
        session_id: str,
        generation: int,
        move_id: str,
        after: ConversationAfter,
        now: float | None = None,
        may_continue_delay: float = 1.2,
        continue_self_delay: float = 0.15,
    ) -> ContinuationLease | None:
        self.cancel_session(session_id)
        if after == ConversationAfter.WAIT_USER:
            return None
        ts = float(now if now is not None else time.time())
        delay = continue_self_delay if after == ConversationAfter.CONTINUE_SELF else may_continue_delay
        lease = ContinuationLease(
            lease_id=f"lease:{uuid.uuid4().hex}",
            session_id=str(session_id or "default")[:180],
            generation=max(0, int(generation)),
            source_move_id=str(move_id or "")[:180],
            due_at=ts + max(0.0, float(delay)),
            mode=after,
            status="pending",
            updated_at=ts,
        )
        with self._lock:
            self._leases[lease.session_id] = lease
        return lease

    def cancel_session(self, session_id: str) -> bool:
        sid = str(session_id or "default")[:180]
        with self._lock:
            prior = self._leases.pop(sid, None)
        return prior is not None

    def peek(self, session_id: str) -> ContinuationLease | None:
        with self._lock:
            return self._leases.get(str(session_id or "default")[:180])

    def claim_due(self, *, session_id: str, generation: int, now: float | None = None) -> ContinuationLease | None:
        sid = str(session_id or "default")[:180]
        ts = float(now if now is not None else time.time())
        with self._lock:
            lease = self._leases.get(sid)
            if lease is None:
                return None
            if lease.generation != int(generation) or lease.status != "pending" or lease.due_at > ts:
                return None
            claimed = replace(
                lease,
                status="claimed",
                claim_token=f"claim:{uuid.uuid4().hex}",
                updated_at=ts,
            )
            self._leases[sid] = claimed
            return claimed

    def consume(self, lease: ContinuationLease) -> None:
        with self._lock:
            current = self._leases.get(lease.session_id)
            if current and current.lease_id == lease.lease_id and current.claim_token == lease.claim_token:
                self._leases.pop(lease.session_id, None)

    def release(self, lease: ContinuationLease, *, retry_seconds: float = 0.5) -> None:
        with self._lock:
            current = self._leases.get(lease.session_id)
            if current is None or current.lease_id != lease.lease_id or current.claim_token != lease.claim_token:
                return
            self._leases[lease.session_id] = replace(
                current,
                status="pending",
                claim_token="",
                due_at=time.time() + max(0.1, float(retry_seconds)),
                updated_at=time.time(),
            )


__all__ = ["ContinuationLeaseScheduler"]
