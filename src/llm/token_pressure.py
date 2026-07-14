from __future__ import annotations

"""Bộ điều tiết áp lực token và 429 dùng chung cho các lane LLM của ERIS.

Mục tiêu của module này không phải đo token chính xác tuyệt đối. Nó tạo một tín
hiệu đủ ổn định để runtime biết lúc nào nên:

- giữ request chat chính nhưng rút prompt/output;
- hạ số candidate của Director;
- bỏ các pass phụ như micro-presence khi provider đang nóng;
- ngừng xoay key vô ích sau một cụm HTTP 429.

Mọi số liệu đều nằm trong RAM, có cửa sổ trượt và tự hết hạn. Module không ghi
API key, prompt hay nội dung người dùng ra đĩa.
"""

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Mapping

from llm.token_budget import budget_for_provider


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True, slots=True)
class TokenPressureSnapshot:
    provider: str
    lane: str
    window_tokens: int
    budget_tokens: int
    pressure: float
    level: str
    recent_429: int
    cooldown_remaining_s: float
    prompt_scale: float
    output_scale: float
    max_model_candidates: int
    shed_optional_passes: bool

    @property
    def hot(self) -> bool:
        return self.level in {"high", "critical"}


@dataclass(frozen=True, slots=True)
class TokenRequestPlan:
    provider: str
    lane: str
    allowed: bool
    prompt_limit: int
    output_tokens: int
    reason: str
    snapshot: TokenPressureSnapshot


class TokenPressureGovernor:
    """Theo dõi token ước lượng trong cửa sổ trượt và phản ứng với 429.

    Governor cố tình thread-safe vì chat, private mind, presence và TTS có thể
    chạy song song. Các request chính không bị chặn chỉ vì pressure cao; chúng
    được rút gọn. Chỉ pass phụ mới có thể bị shed hoàn toàn.
    """

    def __init__(
        self,
        *,
        window_seconds: float | None = None,
        budgets: Mapping[str, int] | None = None,
    ) -> None:
        self.window_seconds = max(
            5.0,
            float(window_seconds if window_seconds is not None else _env_float("ERIS_TOKEN_PRESSURE_WINDOW_S", 60.0)),
        )
        self._budgets = {str(k).lower(): max(256, int(v)) for k, v in dict(budgets or {}).items()}
        self._events: dict[str, Deque[tuple[float, int, str]]] = defaultdict(deque)
        self._rate_limits: dict[str, Deque[float]] = defaultdict(deque)
        self._cooldown_until: dict[str, float] = defaultdict(float)
        self._last_success: dict[str, float] = defaultdict(float)
        self._lock = threading.RLock()

    @staticmethod
    def _provider(provider: str) -> str:
        return str(provider or "default").strip().lower() or "default"

    def _budget(self, provider: str) -> int:
        key = self._provider(provider)
        override = _env_int(f"ERIS_TOKEN_PRESSURE_BUDGET_{key.upper()}", 0)
        if override > 0:
            return override
        return self._budgets.get(key, budget_for_provider(key))

    def _prune_locked(self, provider: str, now: float) -> None:
        threshold = now - self.window_seconds
        events = self._events[provider]
        while events and events[0][0] < threshold:
            events.popleft()
        rate_limits = self._rate_limits[provider]
        while rate_limits and rate_limits[0] < threshold:
            rate_limits.popleft()

    def record_request(
        self,
        provider: str,
        *,
        lane: str,
        prompt_tokens: int,
        output_tokens: int,
        now: float | None = None,
    ) -> None:
        """Ghi budget request đã gửi, gồm prompt và output reserve.

        Dùng output reserve thay vì usage thật là chủ ý: pressure governor nên hơi
        bảo thủ, vì provider tính cả reasoning token mà nhiều response không trả
        usage đầy đủ.
        """

        ts = time.time() if now is None else float(now)
        key = self._provider(provider)
        total = max(0, int(prompt_tokens)) + max(0, int(output_tokens))
        with self._lock:
            self._prune_locked(key, ts)
            self._events[key].append((ts, total, str(lane or "unknown")))

    def record_rate_limit(
        self,
        provider: str,
        *,
        retry_after_s: float = 20.0,
        now: float | None = None,
    ) -> None:
        """Ghi HTTP 429 và mở cooldown chung cho pass phụ của provider."""

        ts = time.time() if now is None else float(now)
        key = self._provider(provider)
        wait = max(1.0, min(float(retry_after_s or 20.0), 300.0))
        with self._lock:
            self._prune_locked(key, ts)
            self._rate_limits[key].append(ts)
            # Không khóa chat chính. Cờ cooldown chỉ khiến các pass phụ bị shed và
            # request chính tự hạ budget trong ``plan_request``.
            self._cooldown_until[key] = max(self._cooldown_until[key], ts + wait)

    def record_success(self, provider: str, *, now: float | None = None) -> None:
        """Request thành công chứng minh provider vẫn phục vụ được.

        Ta hạ cooldown ngay, nhưng không xóa token window. Nhờ vậy một key mới sống
        lại không khiến runtime quên rằng TPM vẫn đang gần trần.
        """

        ts = time.time() if now is None else float(now)
        key = self._provider(provider)
        with self._lock:
            self._last_success[key] = ts
            self._cooldown_until[key] = 0.0
            self._prune_locked(key, ts)

    def snapshot(
        self,
        provider: str,
        *,
        lane: str = "unknown",
        now: float | None = None,
    ) -> TokenPressureSnapshot:
        ts = time.time() if now is None else float(now)
        key = self._provider(provider)
        with self._lock:
            self._prune_locked(key, ts)
            window_tokens = sum(item[1] for item in self._events[key])
            recent_429 = len(self._rate_limits[key])
            cooldown_remaining = max(0.0, self._cooldown_until[key] - ts)

        budget = max(256, self._budget(key))
        raw_pressure = window_tokens / budget
        # 429 là bằng chứng provider đã chạm giới hạn, dù estimator chưa đếm đủ.
        if cooldown_remaining > 0.0:
            raw_pressure = max(raw_pressure, 1.0)
        elif recent_429:
            raw_pressure = max(raw_pressure, 0.90)
        pressure = max(0.0, min(raw_pressure, 1.5))

        if pressure >= 0.90:
            level = "critical"
            prompt_scale, output_scale, max_candidates = 0.62, 0.58, 0
        elif pressure >= 0.75:
            level = "high"
            prompt_scale, output_scale, max_candidates = 0.76, 0.72, 1
        elif pressure >= 0.55:
            level = "warm"
            prompt_scale, output_scale, max_candidates = 0.90, 0.86, 2
        else:
            level = "normal"
            prompt_scale, output_scale, max_candidates = 1.0, 1.0, 3

        lane_key = str(lane or "unknown").strip().lower()
        optional_lane = lane_key in {
            "director_candidates",
            "micro_presence",
            "curiosity_seed",
            "private_mind_optional",
            "style_rewrite_optional",
        }
        # Micro-presence bị shed sớm hơn vì nó từng là lane đốt TPM nhiều nhất mà
        # giá trị mỗi request chỉ là một câu rất ngắn.
        micro_hot = lane_key == "micro_presence" and pressure >= 0.55
        shed_optional = optional_lane and (pressure >= 0.75 or micro_hot or cooldown_remaining > 0.0)

        return TokenPressureSnapshot(
            provider=key,
            lane=lane_key,
            window_tokens=window_tokens,
            budget_tokens=budget,
            pressure=pressure,
            level=level,
            recent_429=recent_429,
            cooldown_remaining_s=cooldown_remaining,
            prompt_scale=prompt_scale,
            output_scale=output_scale,
            max_model_candidates=max_candidates,
            shed_optional_passes=shed_optional,
        )

    def plan_request(
        self,
        provider: str,
        *,
        lane: str,
        prompt_tokens: int,
        requested_output_tokens: int,
        optional_pass: bool = False,
        min_prompt_tokens: int = 256,
        min_output_tokens: int = 128,
        now: float | None = None,
    ) -> TokenRequestPlan:
        snap = self.snapshot(provider, lane=lane, now=now)
        allowed = not (optional_pass and snap.shed_optional_passes)
        prompt_limit = max(int(min_prompt_tokens), int(max(0, prompt_tokens) * snap.prompt_scale))
        output_tokens = max(int(min_output_tokens), int(max(1, requested_output_tokens) * snap.output_scale))
        output_tokens = min(max(1, int(requested_output_tokens)), output_tokens)
        reason = "ok"
        if not allowed:
            reason = f"shed_optional:{snap.level}"
        elif snap.level != "normal":
            reason = f"degraded_budget:{snap.level}"
        return TokenRequestPlan(
            provider=snap.provider,
            lane=snap.lane,
            allowed=allowed,
            prompt_limit=prompt_limit,
            output_tokens=output_tokens,
            reason=reason,
            snapshot=snap,
        )

    def reset(self) -> None:
        """Xóa telemetry trong RAM. Chỉ dùng cho test/debug."""

        with self._lock:
            self._events.clear()
            self._rate_limits.clear()
            self._cooldown_until.clear()
            self._last_success.clear()


GLOBAL_TOKEN_PRESSURE_GOVERNOR = TokenPressureGovernor()


__all__ = [
    "GLOBAL_TOKEN_PRESSURE_GOVERNOR",
    "TokenPressureGovernor",
    "TokenPressureSnapshot",
    "TokenRequestPlan",
]
