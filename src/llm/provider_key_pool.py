# -*- coding: utf-8 -*-
"""Wrapper lease thống nhất cho mọi request provider.

``current_key()`` vẫn tồn tại để dựng client compat, nhưng request thật nên đi
qua wrapper này để lỗi được gắn đúng lease. Không còn cảnh thread A làm chết key
của thread B chỉ vì con trỏ pool đã xoay giữa hai dòng code.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from llm.key_pool import ApiKeyLease, ApiKeyPool, get_key_pool
from llm.provider_errors import ProviderErrorKind, classify_provider_error


@dataclass(frozen=True, slots=True)
class ProviderLease:
    provider: str
    lease: ApiKeyLease | None

    @property
    def key(self) -> str:
        return self.lease.key if self.lease is not None else ""

    @property
    def index(self) -> int | None:
        return self.lease.index if self.lease is not None else None


class ProviderKeyPoolWrapper:
    def __init__(self, provider: str, pool: ApiKeyPool | None = None, *, logger: Any = None) -> None:
        self.provider = str(provider or "gemini").strip().lower()
        self.pool = pool if pool is not None else get_key_pool(self.provider)
        self.logger = logger

    def acquire(self, *, exclude_indices=()) -> ProviderLease:
        lease = self.pool.acquire(exclude_indices=exclude_indices) if self.pool is not None else None
        return ProviderLease(provider=self.provider, lease=lease)

    @contextmanager
    def lease(self, *, exclude_indices=()) -> Iterator[ProviderLease]:
        wrapped = self.acquire(exclude_indices=exclude_indices)
        try:
            yield wrapped
        except Exception as exc:
            self.record_error(wrapped, exc)
            raise
        else:
            self.record_success(wrapped)

    def record_success(self, wrapped: ProviderLease | ApiKeyLease | None) -> None:
        if self.pool is None:
            return
        lease = wrapped.lease if isinstance(wrapped, ProviderLease) else wrapped
        if lease is not None:
            self.pool.mark_success(lease=lease)

    def record_error(
        self,
        wrapped: ProviderLease | ApiKeyLease | None,
        exc: Exception | str,
        *,
        status_code: int | None = None,
        rate_limit_seconds: float = 60.0,
    ) -> ProviderErrorKind:
        if self.pool is None:
            return classify_provider_error(exc, status_code=status_code)
        lease = wrapped.lease if isinstance(wrapped, ProviderLease) else wrapped
        kind = classify_provider_error(exc, status_code=status_code)
        if lease is None:
            return kind
        if kind == ProviderErrorKind.KEY_REVOKED:
            self.pool.mark_permanently_dead(lease=lease, reason=f"{self.provider}_revoked")
        elif kind == ProviderErrorKind.RATE_LIMIT:
            self.pool.mark_rate_limited(seconds=rate_limit_seconds, lease=lease, reason=f"{self.provider}_429")
        elif kind == ProviderErrorKind.PROJECT_PERMISSION:
            self.pool.mark_dead(3600.0, lease=lease, reason=f"{self.provider}_permission")
        elif kind == ProviderErrorKind.TRANSIENT_SERVER:
            # 5xx là provider-level. Không giết key, chỉ caller/circuit xử lý.
            pass
        return kind


__all__ = ["ProviderLease", "ProviderKeyPoolWrapper"]
