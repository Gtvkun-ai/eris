# -*- coding: utf-8 -*-
"""
llm/key_pool.py

Pool API key dùng CHUNG cho mọi mạch gọi Gemini (main / speech / private_mind).

Mỗi key thường thuộc một Google project khác nhau (vd nhiều Gmail) → mỗi key có
hũ free quota riêng. Free tier tính theo PROJECT chứ không theo key, nên cách
duy nhất để "buff free" là xoay vòng qua các key thuộc project khác nhau.

Pool này giữ MỘT index dùng chung cho cả ba mạch: khi một mạch gặp 429 và xoay
key, các mạch còn lại cũng dùng key mới đó. Vắt cạn project này thì cả hệ nhảy
sang project kế tiếp cùng lúc.

Thread-safe. Không bao giờ ném lỗi ra ngoài (đọc secrets hỏng → pool rỗng).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, List

_LOGGER = logging.getLogger("LLM")

@dataclass(frozen=True, slots=True)
class ApiKeyLease:
    """Một key cụ thể đã được cấp cho đúng một request.

    Request phải giữ lease này cho tới khi thành công/thất bại. Khi báo lỗi,
    pool đánh dấu chính ``lease.index`` thay vì con trỏ toàn cục có thể đã bị
    thread khác xoay mất.
    """

    index: int
    key: str


class ApiKeyPool:
    """Danh sách key + một con trỏ rotation dùng chung, có theo dõi key "chết".

    Mỗi key có thể bị đánh dấu nghỉ (dead) trong N giây khi gặp 429/413/5xx; pool
    tự bỏ qua key nghỉ khi xoay/đọc, và tự "hồi" sau khi hết cooldown. Nhờ vậy các
    mạch chạy song song không cùng đập vào một key đã hết quota.
    """

    def __init__(self, keys: List[str]) -> None:
        seen: set[str] = set()
        ordered: list[str] = []
        for k in keys:
            k = str(k or "").strip()
            if k and k not in seen:
                seen.add(k)
                ordered.append(k)
        self._keys = ordered
        self._dead_until: list[float] = [0.0] * len(ordered)
        self._index = 0
        self._lock = threading.Lock()
        self._rotations = 0

    @property
    def size(self) -> int:
        return len(self._keys)

    def _alive_locked(self, idx: int, now: float) -> bool:
        return self._dead_until[idx] <= now

    def alive_count(self) -> int:
        now = time.time()
        with self._lock:
            return sum(1 for i in range(len(self._keys)) if self._alive_locked(i, now))

    def _next_alive_locked(self, start: int, now: float) -> int:
        """Tìm index key sống kế tiếp (gồm cả start). -1 nếu không có key sống."""
        n = len(self._keys)
        for offset in range(n):
            idx = (start + offset) % n
            if self._alive_locked(idx, now):
                return idx
        return -1

    def acquire(
        self,
        *,
        exclude_indices: Iterable[int] = (),
        allow_cooling: bool = False,
    ) -> ApiKeyLease | None:
        """Cấp một lease cho key sống, bỏ qua các index request đã thử.

        ``allow_cooling=False`` là đường request chuẩn: nếu toàn pool đang cooldown
        thì trả ``None`` để caller dừng, không lấy key "ít chết nhất" rồi tiếp tục
        bắn API. ``current_key`` giữ hành vi tương thích cũ cho lúc khởi tạo client.
        """

        excluded = {int(i) for i in exclude_indices}
        now = time.time()
        with self._lock:
            if not self._keys:
                return None
            n = len(self._keys)
            for offset in range(n):
                idx = (self._index + offset) % n
                if idx in excluded or not self._alive_locked(idx, now):
                    continue
                if idx != self._index:
                    self._rotations += 1
                self._index = idx
                return ApiKeyLease(index=idx, key=self._keys[idx])

            if not allow_cooling:
                return None
            candidates = [i for i in range(n) if i not in excluded]
            if not candidates:
                candidates = list(range(n))
            idx = min(candidates, key=lambda i: self._dead_until[i])
            if idx != self._index:
                self._rotations += 1
            self._index = idx
            return ApiKeyLease(index=idx, key=self._keys[idx])

    def current_key(self) -> str:
        lease = self.acquire(allow_cooling=True)
        return lease.key if lease is not None else ""

    def rotate(
        self,
        *,
        from_index: int | None = None,
        lease: ApiKeyLease | None = None,
    ) -> bool:
        """Xoay từ đúng key đã dùng, không mặc định đổ lỗi cho con trỏ hiện tại."""

        now = time.time()
        with self._lock:
            if len(self._keys) <= 1:
                return False
            base = lease.index if lease is not None else from_index
            if base is None or not (0 <= int(base) < len(self._keys)):
                base = self._index
            base = int(base)
            nxt = self._next_alive_locked((base + 1) % len(self._keys), now)
            if nxt < 0 or nxt == base:
                return False
            if nxt != self._index:
                self._rotations += 1
            self._index = nxt
            return True

    def mark_dead(
        self,
        seconds: float = 60.0,
        *,
        index: int | None = None,
        lease: ApiKeyLease | None = None,
        reason: str = "",
    ) -> None:
        """Đánh dấu chính key gây lỗi, kể cả khi thread khác đã xoay pool."""

        now = time.time()
        with self._lock:
            if not self._keys:
                return
            target = lease.index if lease is not None else index
            if target is None or not (0 <= int(target) < len(self._keys)):
                target = self._index
            target = int(target)
            cooldown = max(1.0, float(seconds))
            self._dead_until[target] = max(self._dead_until[target], now + cooldown)
            alive = sum(1 for i in range(len(self._keys)) if self._dead_until[i] <= now)
            suffix = f" reason={reason}" if reason else ""
            _LOGGER.warning(
                "[KEY POOL] mark dead index=%d cooldown=%.0fs alive=%d/%d%s",
                target,
                cooldown,
                alive,
                len(self._keys),
                suffix,
            )

    def next_available_in(self) -> float:
        """Số giây còn lại tới lúc ít nhất một key hồi; 0 nếu có key sống."""

        now = time.time()
        with self._lock:
            if not self._keys:
                return 0.0
            waits = [max(0.0, deadline - now) for deadline in self._dead_until]
            return min(waits) if waits else 0.0

    def index(self) -> int:
        with self._lock:
            return self._index

    def stats(self) -> dict[str, int]:
        now = time.time()
        with self._lock:
            alive = sum(1 for i in range(len(self._keys)) if self._dead_until[i] <= now)
            return {
                "size": len(self._keys),
                "alive": alive,
                "dead": len(self._keys) - alive,
                "rotations": self._rotations,
            }


_GROQ_PROVIDERS = {"openai", "openai_compatible", "compatible", "remote", "groq"}

# Mỗi "kind" (gemini / groq) có pool riêng để chạy SONG SONG hai provider:
# việc khó/cần JSON chuẩn đi Groq, việc nhẹ/cần nhanh đi Gemma. Tách pool để
# không bao giờ gửi nhầm key Gemini sang endpoint Groq và ngược lại.
_pools: dict[str, ApiKeyPool] = {}
_pools_lock = threading.Lock()


def _normalize_kind(kind: str) -> str:
    k = str(kind or "").strip().lower()
    return "groq" if k in _GROQ_PROVIDERS else "gemini"


def _is_placeholder(value: str) -> bool:
    v = str(value or "").strip()
    return (not v) or v.upper().startswith("PASTE_")


def _split_keys_env(*names: str) -> list[str]:
    """Tách danh sách key từ env (phân tách bằng dấu phẩy / xuống dòng / ;)."""
    out: list[str] = []
    for name in names:
        raw = os.environ.get(name, "") or ""
        for chunk in raw.replace("\n", ",").replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk and not _is_placeholder(chunk):
                out.append(chunk)
    return out


def _collect_gemini_keys() -> list[str]:
    """Gom key Gemini: chính + remote + speech + fallback pool."""
    ordered: list[str] = []
    try:
        from eris_secrets import _load_secrets, get_secret

        payload = _load_secrets() or {}
        api_keys = payload.get("api_keys", {}) if isinstance(payload, dict) else {}

        primary = get_secret("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
        if primary:
            ordered.append(primary)
        if isinstance(api_keys, dict):
            for single in ("ERIS_REMOTE_API_KEY", "ERIS_SPEECH_API_KEY"):
                val = api_keys.get(single)
                if val:
                    ordered.append(str(val))
            fallbacks = api_keys.get("ERIS_PRIVATE_MIND_FALLBACK_API_KEYS")
            if isinstance(fallbacks, list):
                ordered.extend(str(k) for k in fallbacks if str(k or "").strip())
    except Exception:
        pass
    # T4.1: thêm key từ env (sau khi .env đã nạp) — hỗ trợ danh sách phân tách.
    ordered.extend(_split_keys_env("ERIS_PRIVATE_MIND_FALLBACK_API_KEYS", "ERIS_GEMINI_FALLBACK_API_KEYS"))
    return ordered


def _collect_groq_keys() -> list[str]:
    """Gom key Groq: ERIS_GROQ_API_KEY + ERIS_GROQ_FALLBACK_API_KEYS (bỏ placeholder)."""
    ordered: list[str] = []
    try:
        from eris_secrets import _load_secrets, get_secret

        payload = _load_secrets() or {}
        api_keys = payload.get("api_keys", {}) if isinstance(payload, dict) else {}

        primary = get_secret("ERIS_GROQ_API_KEY")
        if not _is_placeholder(primary):
            ordered.append(primary)
        if isinstance(api_keys, dict):
            fallbacks = api_keys.get("ERIS_GROQ_FALLBACK_API_KEYS")
            if isinstance(fallbacks, list):
                ordered.extend(str(k) for k in fallbacks if not _is_placeholder(k))
    except Exception:
        pass
    ordered.extend(_split_keys_env("ERIS_GROQ_FALLBACK_API_KEYS"))
    return ordered


def get_key_pool(kind: str = "gemini") -> ApiKeyPool:
    """Trả pool singleton theo provider-kind ('gemini' hoặc 'groq').

    Mỗi consumer truyền đúng provider của mình để luôn lấy đúng họ key, bất kể
    provider toàn cục đang là gì.
    """
    k = _normalize_kind(kind)
    pool = _pools.get(k)
    if pool is not None:
        return pool
    with _pools_lock:
        if k not in _pools:
            if k == "groq":
                keys = _collect_groq_keys()
            else:
                keys = _collect_gemini_keys()
            _pools[k] = ApiKeyPool(keys)
        return _pools[k]


def get_shared_key_pool() -> ApiKeyPool:
    """Tương thích ngược: chọn pool theo ERIS_REMOTE_PROVIDER toàn cục."""
    import os

    return get_key_pool(os.getenv("ERIS_REMOTE_PROVIDER", "gemini"))


def reset_shared_key_pool() -> None:
    """Chỉ dùng cho test: xóa toàn bộ pool để build lại từ secrets."""
    with _pools_lock:
        _pools.clear()


# ── T4.3: Giới hạn đồng thời per-provider ────────────────────────────────────
# Worker song song (Phase 2 DDS) qua đây để không tự bắn vượt RPM mỗi key.
_semaphores: dict[str, threading.BoundedSemaphore] = {}
_sem_lock = threading.Lock()


def _max_concurrency(provider: str) -> int:
    kind = _normalize_kind(provider)
    specific = os.environ.get(f"ERIS_LLM_{kind.upper()}_MAX_CONCURRENCY", "").strip()
    generic = os.environ.get("ERIS_LLM_MAX_CONCURRENCY", "").strip()
    raw = specific or generic
    try:
        value = int(raw) if raw else 4
    except ValueError:
        value = 4
    return max(1, value)


def _get_semaphore(provider: str) -> threading.BoundedSemaphore:
    kind = _normalize_kind(provider)
    sem = _semaphores.get(kind)
    if sem is not None:
        return sem
    with _sem_lock:
        if kind not in _semaphores:
            _semaphores[kind] = threading.BoundedSemaphore(_max_concurrency(kind))
        return _semaphores[kind]


@contextmanager
def concurrency_slot(provider: str = "gemini", *, timeout: float | None = None):
    """Context manager giới hạn số call đồng thời per-provider.

    Dùng trong worker runner song song. Nếu hết slot trong ``timeout`` giây thì
    vẫn chạy (best-effort, không chặn cứng) để không treo hot path.
    """
    sem = _get_semaphore(provider)
    effective_timeout = timeout if timeout is not None else 30.0
    acquired = sem.acquire(timeout=effective_timeout)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                sem.release()
            except ValueError:
                pass


def reset_concurrency_limits() -> None:
    """Test/hot-reload: dựng lại semaphore theo env hiện tại."""
    with _sem_lock:
        _semaphores.clear()

# ── Provider circuit breaker ─────────────────────────────────────────────────
# 5xx là lỗi provider/model, không phải lỗi API key. Nếu cứ xoay key khi 503,
# ta chỉ biến một outage chung thành nghĩa địa key. Circuit này dùng chung theo
# provider endpoint và chặn các request nền trong một khoảng ngắn.

class ProviderCircuitOpen(RuntimeError):
    pass


class ProviderCircuitBreaker:
    def __init__(self, *, failure_threshold: int = 2, cooldown_s: float = 20.0) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_s = max(1.0, float(cooldown_s))
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def before_request(self, provider: str = "provider") -> None:
        now = time.monotonic()
        with self._lock:
            if self._open_until > now:
                raise ProviderCircuitOpen(
                    f"{provider} circuit đang mở; thử lại sau khoảng {self._open_until - now:.1f}s"
                )
            if self._open_until and self._open_until <= now:
                # Half-open: cho đúng một request đi qua; thành công sẽ reset.
                self._open_until = 0.0
                self._failures = max(0, self.failure_threshold - 1)

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def record_failure(self, *, provider: str = "provider", status: int | None = None) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = max(self._open_until, now + self.cooldown_s)
                _LOGGER.warning(
                    "[PROVIDER CIRCUIT] open provider=%s status=%s cooldown=%.0fs failures=%d",
                    provider,
                    status if status is not None else "?",
                    self.cooldown_s,
                    self._failures,
                )

    def remaining_s(self) -> float:
        with self._lock:
            return max(0.0, self._open_until - time.monotonic())


_provider_circuits: dict[str, ProviderCircuitBreaker] = {}
_provider_circuits_lock = threading.Lock()


def get_provider_circuit(provider_id: str) -> ProviderCircuitBreaker:
    key = str(provider_id or "provider").strip().lower()
    circuit = _provider_circuits.get(key)
    if circuit is not None:
        return circuit
    with _provider_circuits_lock:
        circuit = _provider_circuits.get(key)
        if circuit is None:
            try:
                threshold = int(os.environ.get("ERIS_PROVIDER_CIRCUIT_FAILURES", "2"))
            except ValueError:
                threshold = 2
            try:
                cooldown = float(os.environ.get("ERIS_PROVIDER_CIRCUIT_COOLDOWN_S", "20"))
            except ValueError:
                cooldown = 20.0
            circuit = ProviderCircuitBreaker(failure_threshold=threshold, cooldown_s=cooldown)
            _provider_circuits[key] = circuit
        return circuit


def reset_provider_circuits() -> None:
    with _provider_circuits_lock:
        _provider_circuits.clear()
