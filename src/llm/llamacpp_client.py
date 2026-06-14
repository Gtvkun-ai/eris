# -*- coding: utf-8 -*-
"""
llm/llamacpp_client.py
======================

Engine inference local IN-PROCESS dựa trên llama-cpp-python.

Mục đích: chạy model gguf đặt thẳng trong `src/` mà KHÔNG cần Ollama hay
llama-server ngoài → bản build self-contained, chạy được trên mọi máy (chỉ cần
runtime Python đã bundle llama-cpp-python).

Client phơi ra `create_chat_completion(...)` cùng chữ ký với GeminiClient/
OpenAICompatibleClient để các adapter dùng chung một interface. Model được nạp
lười (lazy) và cache theo (path, n_ctx, n_gpu_layers) để nhiều adapter cùng model
chia sẻ một instance, tránh nạp trùng trên VRAM 4GB.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

# Khoá TOÀN CỤC cho mọi inference llama-cpp in-process. llama-cpp-python KHÔNG
# thread-safe: nếu nhiều luồng (fragment×5 / vision / scheduler) cùng decode trên
# một hay nhiều Llama instance → heap corruption (0xC0000374) làm sập tiến trình.
# Khoá này ép mọi nạp model + inference chạy LẦN LƯỢT. RLock để re-entrant
# (create_chat_completion giữ khoá rồi gọi _llama cũng cần khoá).
_LLAMA_GLOBAL_LOCK = threading.RLock()


def _project_root() -> Path:
    env = os.environ.get("ERIS_PROJECT_ROOT", "").strip()
    if env:
        return Path(env)
    return Path.cwd()


def _bundle_root() -> Path | None:
    """PyInstaller bundle root (_MEIPASS). None khi chạy script thường."""
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    return Path(meipass) if meipass else None


def resolve_model_path(path_or_name: str) -> str:
    """Định vị file gguf. Ưu tiên đường dẫn tuyệt đối; rồi project_root/path;
    rồi bundle _MEIPASS/src/; rồi cwd."""
    raw = str(path_or_name or "").strip()
    if not raw:
        return raw
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return str(p)
    root = _project_root()
    bundle = _bundle_root()
    candidates = [root / raw, Path.cwd() / raw, root / "src" / Path(raw).name]
    if bundle is not None:
        candidates += [bundle / raw, bundle / "src" / Path(raw).name]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return str(root / raw)


class LlamaCppClient:
    """Wrapper llama-cpp-python theo interface create_chat_completion của ERIS."""

    _cache: dict[tuple[str, int, int], Any] = {}
    _lock = threading.Lock()

    def __init__(
        self,
        *,
        model_path: str,
        model_name: str = "",
        n_ctx: int | None = None,
        n_gpu_layers: int | None = None,
        chat_format: str | None = None,
    ) -> None:
        self.model_path = resolve_model_path(model_path)
        self.model_name = model_name or Path(self.model_path).stem
        self.n_ctx = int(n_ctx if n_ctx is not None else os.getenv("ERIS_LLAMACPP_N_CTX", "8192") or 8192)
        # -1 = nạp toàn bộ layer lên GPU nếu build có CUDA; build CPU sẽ tự bỏ qua.
        self.n_gpu_layers = int(
            n_gpu_layers if n_gpu_layers is not None else os.getenv("ERIS_LLAMACPP_N_GPU_LAYERS", "-1") or -1
        )
        self.chat_format = chat_format or (os.getenv("ERIS_LLAMACPP_CHAT_FORMAT", "").strip() or None)

    def _llama(self) -> Any:
        key = (self.model_path, self.n_ctx, self.n_gpu_layers)
        with _LLAMA_GLOBAL_LOCK:
            inst = LlamaCppClient._cache.get(key)
            if inst is None:
                from llama_cpp import Llama  # import trễ: chỉ cần khi thật sự chạy local

                if not Path(self.model_path).exists():
                    raise FileNotFoundError(f"gguf not found: {self.model_path}")
                inst = Llama(
                    model_path=self.model_path,
                    n_ctx=self.n_ctx,
                    n_gpu_layers=self.n_gpu_layers,
                    chat_format=self.chat_format,
                    verbose=False,
                )
                LlamaCppClient._cache[key] = inst
            return inst

    def create_chat_completion(
        self,
        *,
        messages,
        temperature=0.7,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        max_tokens=512,
        response_format=None,
        grammar=None,
        timeout=None,  # llama-cpp chạy in-process, không có timeout mạng — bỏ qua.
        **kwargs: Any,
    ):
        call_kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "frequency_penalty": float(frequency_penalty or 0.0),
            "presence_penalty": float(presence_penalty or 0.0),
        }
        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            call_kwargs["response_format"] = {"type": "json_object"}
        # Serialize toàn bộ inference: không bao giờ để 2 luồng decode đồng thời.
        with _LLAMA_GLOBAL_LOCK:
            llama = self._llama()
            return llama.create_chat_completion(**call_kwargs)
