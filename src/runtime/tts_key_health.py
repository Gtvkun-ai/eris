# -*- coding: utf-8 -*-
"""tts_key_health.py - health key theo lane TTS.

Một key có thể dùng LLM nhưng project chưa bật Gemini TTS. 403 vì permission vì
thế chỉ hard-disable lane TTS của key đó, không giết cả key pool. 429 vẫn để pool
cooldown; 5xx để circuit breaker/backoff xử lý.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from llm.provider_errors import ProviderErrorKind, classify_provider_error


@dataclass(slots=True)
class TtsKeyLaneStatus:
    index: int
    state: str = "healthy"
    reason: str = ""
    disabled_until: float = 0.0
    failures: int = 0
    updated_at: float = 0.0

    @property
    def excluded(self) -> bool:
        return self.state in {"permission_denied", "revoked", "invalid_key"} or self.disabled_until > time.time()


class TtsKeyLaneHealth:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._statuses: dict[int, TtsKeyLaneStatus] = {}

    def excluded_indices(self) -> set[int]:
        with self._lock:
            return {idx for idx, status in self._statuses.items() if status.excluded}

    def record_success(self, index: int | None) -> None:
        if index is None:
            return
        with self._lock:
            self._statuses[int(index)] = TtsKeyLaneStatus(
                index=int(index), state="healthy", updated_at=time.time()
            )

    def record_error(self, index: int | None, exc: Exception | str) -> ProviderErrorKind:
        kind = classify_provider_error(exc)
        if index is None:
            return kind
        now = time.time()
        idx = int(index)
        with self._lock:
            old = self._statuses.get(idx) or TtsKeyLaneStatus(index=idx)
            state = old.state
            disabled_until = old.disabled_until
            if kind == ProviderErrorKind.PROJECT_PERMISSION:
                state = "permission_denied"
                disabled_until = float("inf")
            elif kind == ProviderErrorKind.KEY_REVOKED:
                state = "revoked"
                disabled_until = float("inf")
            elif kind == ProviderErrorKind.RATE_LIMIT:
                state = "rate_limited"
                disabled_until = max(disabled_until, now + 60.0)
            elif kind == ProviderErrorKind.TRANSIENT_SERVER:
                state = "temporarily_unavailable"
                disabled_until = max(disabled_until, now + min(30.0, 2.0 ** min(5, old.failures + 1)))
            elif kind == ProviderErrorKind.INVALID_REQUEST:
                state = "invalid_request"
            elif kind == ProviderErrorKind.INVALID_RESPONSE_SHAPE:
                state = "invalid_response"
            else:
                state = "unknown_error"
            self._statuses[idx] = TtsKeyLaneStatus(
                index=idx,
                state=state,
                reason=str(kind),
                disabled_until=disabled_until,
                failures=old.failures + 1,
                updated_at=now,
            )
        return kind

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                str(idx): {
                    "state": status.state,
                    "reason": status.reason,
                    "excluded": status.excluded,
                    "failures": status.failures,
                    "disabled_until": status.disabled_until,
                }
                for idx, status in self._statuses.items()
            }

    def reset(self) -> None:
        with self._lock:
            self._statuses.clear()


GLOBAL_TTS_KEY_LANE_HEALTH = TtsKeyLaneHealth()


__all__ = ["TtsKeyLaneStatus", "TtsKeyLaneHealth", "GLOBAL_TTS_KEY_LANE_HEALTH"]
