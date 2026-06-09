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

import threading
from typing import List


class ApiKeyPool:
    """Danh sách key + một con trỏ rotation dùng chung."""

    def __init__(self, keys: List[str]) -> None:
        seen: set[str] = set()
        ordered: list[str] = []
        for k in keys:
            k = str(k or "").strip()
            if k and k not in seen:
                seen.add(k)
                ordered.append(k)
        self._keys = ordered
        self._index = 0
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._keys)

    def current_key(self) -> str:
        with self._lock:
            if not self._keys:
                return ""
            return self._keys[self._index % len(self._keys)]

    def rotate(self) -> bool:
        """Xoay sang key kế tiếp (wrap-around).

        Trả True nếu pool có >1 key (tức việc xoay có ý nghĩa). Wrap-around an
        toàn vì mọi vòng retry gọi rotate() đều có giới hạn số lần.
        """
        with self._lock:
            if len(self._keys) <= 1:
                return False
            self._index = (self._index + 1) % len(self._keys)
            return True

    def index(self) -> int:
        with self._lock:
            return self._index


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
