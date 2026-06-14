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
from typing import List

_LOGGER = logging.getLogger("LLM")


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

    def current_key(self) -> str:
        now = time.time()
        with self._lock:
            if not self._keys:
                return ""
            if self._alive_locked(self._index, now):
                return self._keys[self._index]
            alive = self._next_alive_locked(self._index, now)
            if alive >= 0:
                self._index = alive
                return self._keys[alive]
            # Tất cả đang nghỉ → chọn key sắp hồi sớm nhất (least-bad), thử bừa.
            soonest = min(range(len(self._keys)), key=lambda i: self._dead_until[i])
            self._index = soonest
            return self._keys[soonest]

    def rotate(self) -> bool:
        """Xoay sang key SỐNG kế tiếp. Trả True nếu chuyển được sang index khác."""
        now = time.time()
        with self._lock:
            if len(self._keys) <= 1:
                return False
            nxt = self._next_alive_locked((self._index + 1) % len(self._keys), now)
            if nxt < 0 or nxt == self._index:
                # Không có key sống khác → vẫn nhích con trỏ để không kẹt.
                new_index = (self._index + 1) % len(self._keys)
                if new_index == self._index:
                    return False
                self._index = new_index
                self._rotations += 1
                return True
            self._index = nxt
            self._rotations += 1
            return True

    def mark_dead(self, seconds: float = 60.0) -> None:
        """Đánh dấu key hiện tại nghỉ trong ``seconds`` giây (429/413/5xx)."""
        now = time.time()
        with self._lock:
            if not self._keys:
                return
            self._dead_until[self._index] = now + max(1.0, float(seconds))
            _LOGGER.warning(
                "[KEY POOL] mark dead index=%d cooldown=%.0fs alive=%d/%d",
                self._index,
                seconds,
                sum(1 for i in range(len(self._keys)) if self._dead_until[i] <= now and i != self._index),
                len(self._keys),
            )

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
            keys = _collect_groq_keys() if k == "groq" else _collect_gemini_keys()
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
    acquired = sem.acquire(timeout=timeout) if timeout is not None else sem.acquire()
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
