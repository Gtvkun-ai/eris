# -*- coding: utf-8 -*-
"""
memory/embedding_index.py
=========================

In-memory embedding index cho SemanticMemoryStore.

Dùng transformers + numpy (đã có sẵn trong runtime).
Không cần FAISS, ChromaDB, hay server nào.

Model mặc định: paraphrase-multilingual-MiniLM-L12-v2
- ~120MB, support tiếng Việt
- L12 = 12 layers, MiniLM = distilled, đủ nhanh trên CPU
- Cosine similarity trong numpy = đủ cho 300 items

Hook interface: object có method
    search(query: str, items: list[Any], *, text_fn: Callable, limit: int)
    → list[tuple[float, item]]

SemanticMemoryStore gọi self.embedding_index.search(...) nếu không None.
Embedding chỉ lấy candidate; scoring cuối vẫn thuộc domain/fact_key/confidence.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)

# Model MiniLM đa ngôn ngữ đi kèm repo: src/paraphrase-multilingual-MiniLM-L12-v2
# (embedding_index.py nằm ở src/memory/, nên model ở thư mục cha một cấp.)
_LOCAL_MODEL_DIR = Path(__file__).resolve().parents[1] / "paraphrase-multilingual-MiniLM-L12-v2"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity giữa vector a và matrix b (N, D).
    Trả ndarray shape (N,).
    """
    a_norm = a / (np.linalg.norm(a) + 1e-9)
    b_norms = np.linalg.norm(b, axis=1, keepdims=True) + 1e-9
    b_normalized = b / b_norms
    return b_normalized @ a_norm


def _short_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


# ---------------------------------------------------------------------------
# EmbeddingIndex
# ---------------------------------------------------------------------------

class EmbeddingIndex:
    """In-memory embedding index dùng transformers.

    Workflow:
    1. `ensure_vectors(items, text_fn)` — embed mọi item chưa có vector
    2. `search(query, items, text_fn, limit)` — encode query, cosine search
    3. Vectors cache trong memory dict. Restart thì rebuild (nhanh, 300 items ~2-3s).

    Không persist vectors ra file riêng — đơn giản hơn, khi model đổi không bị stale cache.
    Items nhỏ (<500), rebuild mỗi boot không thành vấn đề.
    """

    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    # Nếu muốn model nhỏ hơn: "paraphrase-MiniLM-L3-v2" (~60MB, English-only)

    def __init__(
        self,
        *,
        model_name: str | None = None,
        cache_dir: str | None = None,
        device: str | None = None,
        max_seq_length: int = 128,
    ) -> None:
        self.model_name = model_name or os.getenv(
            "ERIS_EMBEDDING_MODEL", self.DEFAULT_MODEL
        )
        self.cache_dir = cache_dir or os.getenv(
            "ERIS_EMBEDDING_CACHE_DIR",
            # Mặc định đặt cạnh model.gguf — cùng thư mục src/
            str(Path("src") / "embedding_model"),
        )
        self.max_seq_length = max_seq_length
        self._device = device or ("cuda" if self._cuda_available() else "cpu")
        self._model: Any = None
        self._tokenizer: Any = None
        self._loaded = False
        self._load_error: str = ""
        # Cache: text_hash → ndarray
        self._vector_cache: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Public interface (contract cho SemanticMemoryStore)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        items: list[Any],
        *,
        text_fn: Callable[[Any], str],
        limit: int = 24,
    ) -> list[tuple[float, Any]]:
        """Tìm items gần với query nhất theo cosine similarity.

        Trả list[tuple[score, item]] đã sorted descending.
        Score trong [0, 1] (normalized cosine).
        """
        if not items or not str(query or "").strip():
            return []
        if not self._ensure_loaded():
            return []

        try:
            query_vec = self._encode([query])[0]
        except Exception as exc:
            logger.warning("EmbeddingIndex query encode failed: %s", exc)
            return []

        # Encode item texts
        texts = [text_fn(item) for item in items]
        vecs = self._encode_with_cache(texts)
        if vecs is None or len(vecs) == 0:
            return []

        scores = _cosine_similarity(query_vec, vecs)

        # Sort descending, trả top-limit
        top_indices = np.argsort(scores)[::-1][:limit]
        results: list[tuple[float, Any]] = []
        for idx in top_indices:
            score = float(scores[idx])
            if score > 0.10:  # Threshold nhẹ — loại item hoàn toàn không liên quan
                results.append((score, items[idx]))
        return results

    def ensure_vectors(
        self,
        items: list[Any],
        *,
        text_fn: Callable[[Any], str],
    ) -> int:
        """Pre-embed items vào cache. Trả số item mới được embed.

        Gọi từ maintenance hoặc khi store load. Không bắt buộc —
        search() tự encode nếu cần, nhưng ensure_vectors() làm nó ấm trước.
        """
        if not self._ensure_loaded():
            return 0
        texts = [text_fn(item) for item in items]
        new_count = 0
        for text in texts:
            key = _short_hash(text)
            if key not in self._vector_cache:
                new_count += 1
        if new_count == 0:
            return 0
        try:
            self._encode_with_cache(texts)
        except Exception as exc:
            logger.warning("EmbeddingIndex ensure_vectors failed: %s", exc)
            return 0
        return new_count

    def clear_cache(self) -> None:
        self._vector_cache.clear()

    def debug_status(self) -> dict[str, Any]:
        return {
            "loaded": self._loaded,
            "load_error": self._load_error,
            "model": self.model_name,
            "device": self._device,
            "cache_size": len(self._vector_cache),
        }

    # ------------------------------------------------------------------
    # Model loading (lazy)
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        if self._load_error:
            return False
        try:
            self._load_model()
            self._loaded = True
            return True
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "EmbeddingIndex model load failed (%s): %s — recall sẽ dùng lexical only.",
                self.model_name,
                exc,
            )
            return False

    def _load_model(self) -> None:
        from transformers import AutoTokenizer, AutoModel
        t0 = time.time()
        os.makedirs(self.cache_dir, exist_ok=True)

        # Nếu cache_dir chứa config.json thì đó là local model path — load trực tiếp.
        # Nếu không thì dùng cache_dir làm HuggingFace cache và download.
        local_model_path = os.path.join(self.cache_dir, "config.json")
        load_path = self.cache_dir if os.path.isfile(local_model_path) else self.model_name
        cache_arg = None if os.path.isfile(local_model_path) else self.cache_dir

        logger.info(
            "[EmbeddingIndex] Loading model from %s (device=%s)...",
            load_path, self._device,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            load_path, cache_dir=cache_arg
        )
        self._model = AutoModel.from_pretrained(
            load_path, cache_dir=cache_arg
        )
        self._model.eval()
        if self._device != "cpu":
            try:
                self._model = self._model.to(self._device)
            except Exception:
                self._device = "cpu"
        elapsed = time.time() - t0
        logger.info("[EmbeddingIndex] Model loaded in %.1fs.", elapsed)

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode list of texts → ndarray (N, D)."""
        import torch
        batch_size = 32
        all_vecs: list[np.ndarray] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Pad/truncate
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_seq_length,
                return_tensors="pt",
            )
            if self._device != "cpu":
                encoded = {k: v.to(self._device) for k, v in encoded.items()}
            with torch.no_grad():
                output = self._model(**encoded)
            # Mean pooling over token dimension
            token_embeddings = output.last_hidden_state  # (B, T, D)
            attention_mask = encoded["attention_mask"]   # (B, T)
            mask_expanded = attention_mask.unsqueeze(-1).float()
            summed = (token_embeddings * mask_expanded).sum(dim=1)
            counts = mask_expanded.sum(dim=1).clamp(min=1e-9)
            mean_pooled = (summed / counts).cpu().numpy()  # (B, D)
            all_vecs.append(mean_pooled)

        return np.vstack(all_vecs)  # (N, D)

    def _encode_with_cache(self, texts: list[str]) -> np.ndarray | None:
        """Encode texts, dùng cache để tránh re-embed text đã biết."""
        if not texts:
            return None

        keys = [_short_hash(t) for t in texts]
        uncached_indices = [i for i, k in enumerate(keys) if k not in self._vector_cache]

        if uncached_indices:
            uncached_texts = [texts[i] for i in uncached_indices]
            try:
                new_vecs = self._encode(uncached_texts)
                for j, idx in enumerate(uncached_indices):
                    self._vector_cache[keys[idx]] = new_vecs[j]
            except Exception as exc:
                logger.warning("EmbeddingIndex encode batch failed: %s", exc)
                return None

        # Assemble in original order
        try:
            result = np.stack([self._vector_cache[k] for k in keys])
            return result
        except KeyError:
            return None

    # ------------------------------------------------------------------
    # Provider interface (cho event_semantics / situation_model)
    # ------------------------------------------------------------------

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed một text -> vector tuple. Trả () nếu model không sẵn sàng.

        Đây là interface provider dùng chung: EventSemanticProfiler và
        consumer semantic có thể nhận trực tiếp EmbeddingIndex làm provider.
        """

        vectors = self.embed_events([str(text or "")])
        return vectors[0] if vectors else ()

    def embed_events(self, texts) -> list[tuple[float, ...]]:
        """Embed nhiều text -> list vector tuple (cùng thứ tự).

        Mọi lỗi (model chưa nạp được, encode lỗi) -> list các tuple rỗng tương
        ứng, để caller tự graceful degrade thay vì vỡ.
        """

        items = [str(t or "") for t in (texts or [])]
        if not items:
            return []
        if not self._ensure_loaded():
            return [() for _ in items]
        try:
            matrix = self._encode_with_cache(items)
            if matrix is None:
                return [() for _ in items]
            return [tuple(float(x) for x in row) for row in matrix]
        except Exception as exc:  # pragma: no cover - đường lỗi phòng vệ
            logger.warning("EmbeddingIndex.embed_events failed: %s", exc)
            return [() for _ in items]

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_embedding_index(
    *,
    model_name: str | None = None,
    enabled: bool = True,
) -> EmbeddingIndex | None:
    """Build EmbeddingIndex nếu enabled.

    Trả None nếu disabled hoặc import fail — caller tự graceful degrade.
    Env: ERIS_EMBEDDING_ENABLED=1 (default 1)
         ERIS_EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
    """
    env_enabled = os.getenv("ERIS_EMBEDDING_ENABLED", "1").strip().lower()
    if env_enabled in {"0", "false", "no", "off"}:
        return None
    if not enabled:
        return None
    try:
        import torch  # noqa: F401 — check availability
        from transformers import AutoTokenizer  # noqa: F401
    except ImportError:
        logger.warning(
            "EmbeddingIndex: torch/transformers chưa install. Recall dùng lexical only."
        )
        return None
    return EmbeddingIndex(model_name=model_name)


# ---------------------------------------------------------------------------
# Shared singleton — một model dùng chung cho memory + event_semantics + situation
# ---------------------------------------------------------------------------

_SHARED_INDEX: EmbeddingIndex | None = None
_SHARED_BUILT = False


def get_shared_embedding_index() -> EmbeddingIndex | None:
    """Trả EmbeddingIndex dùng chung toàn tiến trình (build một lần, lazy nạp model).

    Ưu tiên model local trong repo (src/paraphrase-multilingual-MiniLM-L12-v2) để
    khỏi tải mạng. Trả None nếu embedding bị tắt qua env hoặc thiếu torch/transformers
    — caller tự graceful degrade.

    Việc tạo object là rẻ; model chỉ thực sự nạp ở lần embed()/search() đầu tiên.
    Nhờ vậy memory store, event semantics và situation model chia sẻ đúng một model.
    """

    global _SHARED_INDEX, _SHARED_BUILT
    if _SHARED_BUILT:
        return _SHARED_INDEX

    _SHARED_BUILT = True
    env_enabled = os.getenv("ERIS_EMBEDDING_ENABLED", "1").strip().lower()
    if env_enabled in {"0", "false", "no", "off"}:
        _SHARED_INDEX = None
        return None
    try:
        cache_dir = str(_LOCAL_MODEL_DIR) if _LOCAL_MODEL_DIR.is_dir() else None
        _SHARED_INDEX = EmbeddingIndex(cache_dir=cache_dir)
    except Exception:
        _SHARED_INDEX = None
    return _SHARED_INDEX


def reset_shared_embedding_index() -> None:
    """Xoá singleton (dùng cho test/maintenance)."""

    global _SHARED_INDEX, _SHARED_BUILT
    _SHARED_INDEX = None
    _SHARED_BUILT = False


__all__ = [
    "EmbeddingIndex",
    "build_embedding_index",
    "get_shared_embedding_index",
    "reset_shared_embedding_index",
]
