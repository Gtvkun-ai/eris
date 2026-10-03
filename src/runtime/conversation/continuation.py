# -*- coding: utf-8 -*-
"""Một scheduler continuation duy nhất cho public conversation V12.

Scheduler chỉ quản lý lease + generation + resource breaker. Nó không lưu
"ý tiếp theo", không chọn thread và không replay text. Khi lease đến hạn,
caller phải gọi lại RootAgent để quyết định từ ngữ cảnh mới nhất.

Nếu có ``atomic_store`` thì lease được ghi vào SQLite atomic state hiện có.
Mục đích là sống sót qua restart mà không tạo ghost speech: sau restart ta chỉ
khôi phục *quyền được re-evaluate*, không khôi phục câu chữ cũ.
"""
from __future__ import annotations

from dataclasses import replace
import threading
import time
import uuid
from typing import Any, Mapping

from .contracts import ConversationAfter, ContinuationLease


class ContinuationLeaseScheduler:
    """Quản lý đúng một lease continuation trên mỗi conversation.

    ``max_consecutive_self_wakes`` và ``max_chain_seconds`` là circuit breaker
    tài nguyên. Đây KHÔNG phải pacing policy: chúng không cắt câu, không giới hạn
    số sentence và không quyết định nội dung nên nói.
    """

    def __init__(
        self,
        *,
        atomic_store: Any | None = None,
        logger: Any = None,
        max_consecutive_self_wakes: int = 24,
        max_chain_seconds: float = 120.0,
        lease_ttl_seconds: float = 30.0,
    ) -> None:
        self.atomic_store = atomic_store
        self.logger = logger
        self.max_consecutive_self_wakes = max(1, int(max_consecutive_self_wakes))
        self.max_chain_seconds = max(5.0, float(max_chain_seconds))
        self.lease_ttl_seconds = max(2.0, float(lease_ttl_seconds))
        self._lock = threading.RLock()
        self._leases: dict[str, ContinuationLease] = {}

    @staticmethod
    def _sid(session_id: str) -> str:
        return str(session_id or "default").strip()[:180] or "default"

    @classmethod
    def _key(cls, session_id: str) -> str:
        return f"eris.continuation_lease.v12:{cls._sid(session_id)}"

    @staticmethod
    def _empty_payload(session_id: str, *, updated_at: float) -> dict[str, Any]:
        return {
            "schema": "eris.continuation_lease.v12",
            "session_id": str(session_id or "default")[:180],
            "status": "absent",
            "updated_at": float(updated_at),
        }

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
        parent_chain_started_at: float = 0.0,
        parent_self_wakes: int = 0,
    ) -> ContinuationLease | None:
        sid = self._sid(session_id)
        ts = float(now if now is not None else time.time())

        if after == ConversationAfter.WAIT_USER:
            self.cancel_session(sid)
            return None

        # Một user turn mới không truyền parent chain, vì vậy đây là chain mới.
        # Continuation wake truyền lại metadata cơ học của lease cha để breaker
        # thấy được chuỗi self-wake xuyên nhiều lần root re-evaluate.
        chain_started_at = float(parent_chain_started_at or ts)
        next_self_wakes = max(0, int(parent_self_wakes)) + 1
        chain_age = max(0.0, ts - chain_started_at)
        if (
            next_self_wakes > self.max_consecutive_self_wakes
            or chain_age > self.max_chain_seconds
        ):
            self.cancel_session(sid)
            self._log(
                "warning",
                "[conversation-v12] continuation breaker session=%s wakes=%s age=%.2fs",
                sid,
                next_self_wakes,
                chain_age,
            )
            return None

        delay = continue_self_delay if after == ConversationAfter.CONTINUE_SELF else may_continue_delay
        due_at = ts + max(0.0, float(delay))
        # TTL luôn dài hơn due time một khoảng đủ lớn để scheduler có cơ hội claim,
        # nhưng lease cũ không thể sống vô hạn sau suspend/restart dài.
        expires_at = max(due_at + 1.0, ts + self.lease_ttl_seconds)
        lease = ContinuationLease(
            lease_id=f"lease:{uuid.uuid4().hex}",
            session_id=sid,
            generation=max(0, int(generation)),
            source_move_id=str(move_id or "")[:180],
            due_at=due_at,
            expires_at=expires_at,
            chain_started_at=chain_started_at,
            consecutive_self_wakes=next_self_wakes,
            mode=after,
            status="pending",
            updated_at=ts,
        )
        self._write(lease)
        return lease

    def cancel_session(self, session_id: str) -> bool:
        sid = self._sid(session_id)
        prior = self.peek(sid)
        self._clear(sid)
        return prior is not None

    def peek(self, session_id: str) -> ContinuationLease | None:
        sid = self._sid(session_id)
        if self.atomic_store is None:
            with self._lock:
                return self._leases.get(sid)
        try:
            record = self.atomic_store.load(self._key(sid))
            if record is None:
                return None
            lease = ContinuationLease.from_mapping(record.payload)
            with self._lock:
                if lease is None:
                    self._leases.pop(sid, None)
                else:
                    self._leases[sid] = lease
            return lease
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[conversation-v12] durable lease peek degraded: %s", exc)
            with self._lock:
                return self._leases.get(sid)

    def claim_due(self, *, session_id: str, generation: int, now: float | None = None) -> ContinuationLease | None:
        sid = self._sid(session_id)
        ts = float(now if now is not None else time.time())
        if self.atomic_store is None:
            with self._lock:
                lease = self._leases.get(sid)
                if lease is None:
                    return None
                if lease.expires_at and lease.expires_at <= ts:
                    self._leases.pop(sid, None)
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

        # Durable path phải claim trong cùng một SQLite transaction để hai worker
        # không cùng lấy một continuation lease sau restart/race.
        try:
            key = self._key(sid)
            with self.atomic_store.transaction(key, self._empty_payload(sid, updated_at=ts)) as tx:
                lease = ContinuationLease.from_mapping(tx.payload)
                if lease is None:
                    return None
                if lease.expires_at and lease.expires_at <= ts:
                    tx.stage(self._empty_payload(sid, updated_at=ts))
                    return None
                if lease.generation != int(generation) or lease.status != "pending" or lease.due_at > ts:
                    return None
                claimed = replace(
                    lease,
                    status="claimed",
                    claim_token=f"claim:{uuid.uuid4().hex}",
                    updated_at=ts,
                )
                tx.stage(claimed.to_dict())
            with self._lock:
                self._leases[sid] = claimed
            return claimed
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[conversation-v12] durable lease claim degraded: %s", exc)
            return None

    def consume(self, lease: ContinuationLease) -> None:
        sid = self._sid(lease.session_id)
        if self.atomic_store is None:
            with self._lock:
                current = self._leases.get(sid)
                if current and current.lease_id == lease.lease_id and current.claim_token == lease.claim_token:
                    self._leases.pop(sid, None)
            return
        try:
            ts = time.time()
            with self.atomic_store.transaction(
                self._key(sid), self._empty_payload(sid, updated_at=ts)
            ) as tx:
                current = ContinuationLease.from_mapping(tx.payload)
                if current is None:
                    return
                if current.lease_id == lease.lease_id and current.claim_token == lease.claim_token:
                    tx.stage(self._empty_payload(sid, updated_at=ts))
            with self._lock:
                self._leases.pop(sid, None)
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[conversation-v12] durable lease consume degraded: %s", exc)

    def release(self, lease: ContinuationLease, *, retry_seconds: float = 0.5) -> None:
        sid = self._sid(lease.session_id)
        ts = time.time()
        retry_at = ts + max(0.1, float(retry_seconds))
        if lease.expires_at and retry_at >= lease.expires_at:
            self._clear(sid)
            return
        released = replace(
            lease,
            status="pending",
            claim_token="",
            due_at=retry_at,
            updated_at=ts,
        )
        if self.atomic_store is None:
            with self._lock:
                current = self._leases.get(sid)
                if current is None or current.lease_id != lease.lease_id or current.claim_token != lease.claim_token:
                    return
                self._leases[sid] = released
            return
        try:
            with self.atomic_store.transaction(
                self._key(sid), self._empty_payload(sid, updated_at=ts)
            ) as tx:
                current = ContinuationLease.from_mapping(tx.payload)
                if current is None:
                    return
                if current.lease_id != lease.lease_id or current.claim_token != lease.claim_token:
                    return
                tx.stage(released.to_dict())
            with self._lock:
                self._leases[sid] = released
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[conversation-v12] durable lease release degraded: %s", exc)

    def _write(self, lease: ContinuationLease) -> None:
        sid = self._sid(lease.session_id)
        if self.atomic_store is not None:
            try:
                self.atomic_store.replace(self._key(sid), lease.to_dict())
            except Exception as exc:  # noqa: BLE001
                self._log("warning", "[conversation-v12] durable lease write degraded: %s", exc)
        with self._lock:
            self._leases[sid] = lease

    def _clear(self, session_id: str) -> None:
        sid = self._sid(session_id)
        ts = time.time()
        if self.atomic_store is not None:
            try:
                self.atomic_store.replace(self._key(sid), self._empty_payload(sid, updated_at=ts))
            except Exception as exc:  # noqa: BLE001
                self._log("warning", "[conversation-v12] durable lease clear degraded: %s", exc)
        with self._lock:
            self._leases.pop(sid, None)

    def _log(self, level: str, message: str, *args: Any) -> None:
        method = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


__all__ = ["ContinuationLeaseScheduler"]
