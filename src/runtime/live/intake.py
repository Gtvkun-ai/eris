"""Bounded ingress. Không có IO hoặc LLM trên callback TikTok."""
from __future__ import annotations
from collections import OrderedDict, deque
from threading import RLock
import time
from .contracts import LiveCounters, LiveEvent

class BoundedLiveIntake:
    def __init__(self, *, capacity: int = 256, ttl_seconds: float = 20.0,
                 dedup_seconds: float = 120.0, counters: LiveCounters | None = None) -> None:
        self.capacity = max(16, min(4096, int(capacity)))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.dedup_seconds = max(1.0, float(dedup_seconds))
        self.counters = counters or LiveCounters()
        self._lock = RLock()
        self._queue: deque[LiveEvent] = deque()
        self._seen: OrderedDict[str, float] = OrderedDict()

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._queue)

    def offer(self, event: LiveEvent, *, now: float | None = None) -> bool:
        now = time.time() if now is None else float(now)
        with self._lock:
            while self._seen and next(iter(self._seen.values())) + self.dedup_seconds < now:
                self._seen.popitem(last=False)
            if event.event_id in self._seen:
                self.counters.duplicate += 1
                return False
            if now - event.occurred_at > self.ttl_seconds:
                self.counters.expired += 1
                return False
            self._seen[event.event_id] = now
            if len(self._seen) > self.capacity * 8:
                self._seen.popitem(last=False)
            if len(self._queue) >= self.capacity:
                # Giữ những sự kiện mới hơn trong room; trường hợp áp lực cao
                # bộ batch đã có số liệu drop, không bí mật phình RAM.
                self._queue.popleft()
                self.counters.overflow += 1
            self._queue.append(event)
            self.counters.accepted += 1
            return True

    def drain(self, *, limit: int = 512, now: float | None = None) -> list[LiveEvent]:
        now = time.time() if now is None else float(now)
        with self._lock:
            taken = [self._queue.popleft() for _ in range(min(len(self._queue), max(1, limit)))]
        fresh = [event for event in taken if now - event.occurred_at <= self.ttl_seconds]
        self.counters.expired += len(taken) - len(fresh)
        return fresh

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()
            self._seen.clear()
