# -*- coding: utf-8 -*-
"""Exactly-once guard for public turn side effects.

The provider may retry, a caller may re-enter after a timeout, and UI/TTS/memory
all have different opinions about what "already happened" means. This registry
gives one idempotency key one committed result inside a runtime process.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar
from weakref import WeakKeyDictionary


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TurnCommitRecord(Generic[T]):
    idempotency_key: str
    result: T
    committed_at: float


class PublicTurnTransactionRegistry:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._inflight: set[str] = set()
        self._records: dict[str, TurnCommitRecord[Any]] = {}

    def run_once(self, idempotency_key: str, operation: Callable[[], T], *, wait_timeout: float = 5.0) -> T:
        key = str(idempotency_key or "").strip()
        if not key:
            return operation()

        deadline = time.monotonic() + max(0.05, float(wait_timeout))
        with self._condition:
            while key in self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise TimeoutError(f"public_turn_commit_inflight:{key}")
                self._condition.wait(timeout=remaining)
            existing = self._records.get(key)
            if existing is not None:
                return existing.result
            self._inflight.add(key)

        try:
            result = operation()
        except Exception:
            with self._condition:
                self._inflight.discard(key)
                self._condition.notify_all()
            raise

        with self._condition:
            self._records[key] = TurnCommitRecord(
                idempotency_key=key,
                result=result,
                committed_at=time.time(),
            )
            self._inflight.discard(key)
            # Bound memory. A runtime conversation does not need an archaeological
            # layer for every bubble ever emitted.
            if len(self._records) > 512:
                oldest = sorted(self._records.values(), key=lambda item: item.committed_at)[:128]
                for record in oldest:
                    self._records.pop(record.idempotency_key, None)
            self._condition.notify_all()
        return result

    def get(self, idempotency_key: str) -> TurnCommitRecord[Any] | None:
        with self._condition:
            return self._records.get(str(idempotency_key or "").strip())


_REGISTRIES: "WeakKeyDictionary[Any, PublicTurnTransactionRegistry]" = WeakKeyDictionary()
_REGISTRY_LOCK = threading.RLock()
_FALLBACK_REGISTRY = PublicTurnTransactionRegistry()


def registry_for(owner: Any) -> PublicTurnTransactionRegistry:
    existing = getattr(owner, "_public_turn_transaction_registry", None)
    if isinstance(existing, PublicTurnTransactionRegistry):
        return existing
    registry = PublicTurnTransactionRegistry()
    try:
        setattr(owner, "_public_turn_transaction_registry", registry)
        return registry
    except Exception:
        pass
    try:
        with _REGISTRY_LOCK:
            current = _REGISTRIES.get(owner)
            if current is None:
                _REGISTRIES[owner] = registry
                current = registry
            return current
    except Exception:
        return _FALLBACK_REGISTRY


__all__ = ["PublicTurnTransactionRegistry", "TurnCommitRecord", "registry_for"]
