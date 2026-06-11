# -*- coding: utf-8 -*-
"""
llm/local_llama_engine.py
=========================

Engine local thống nhất bằng llama-cpp-python, drop-in thay cho ``OllamaClient``.

Mục tiêu: dồn TẤT CẢ model nội bộ về một engine duy nhất chạy gguf trong ``src/``
(không cần Ollama/llama-server ngoài) → bản build self-contained.

- Text (observer/sensory/private-mind): nạp model text gguf.
- Vision (moondream): nạp model vision gguf + mmproj qua MoondreamChatHandler.

Lớp này phơi ra ĐÚNG interface mà các consumer đang gọi trên OllamaClient:
``chat_json`` / ``generate_json`` / ``unload`` / ``encode_image_*`` /
``data_uri_to_base64`` — nên có thể thay thẳng mà không sửa caller.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

try:
    from llm.ollama_client import OllamaResult
except Exception:  # pragma: no cover
    from dataclasses import dataclass, field

    @dataclass
    class OllamaResult:  # type: ignore
        ok: bool
        parsed: dict = field(default_factory=dict)
        content: str = ""
        raw: dict = field(default_factory=dict)
        error: str = ""

from llm.llamacpp_client import resolve_model_path


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _n_gpu_layers() -> int:
    try:
        return int(os.getenv("ERIS_LLAMACPP_N_GPU_LAYERS", "-1") or -1)
    except Exception:
        return -1


class LocalLlamaEngine:
    """Engine llama-cpp dùng chung, interface tương thích OllamaClient."""

    # Cache theo (kind, model_path) để nhiều consumer cùng model chia sẻ 1 instance.
    _cache: dict[tuple[str, str], Any] = {}
    _lock = threading.RLock()

    def __init__(self, *, timeout: float | None = None) -> None:
        # timeout giữ cho tương thích chữ ký; llama-cpp chạy in-process nên bỏ qua.
        self.timeout = timeout
        self.text_model_path = resolve_model_path(
            _env("ERIS_LLAMACPP_TEXT_MODEL")
            or _env("ERIS_PRIVATE_MIND_FRAGMENT_MODEL")
            or "src/qwen3-1.7b-q4_k_m.gguf"
        )
        self.vision_model_path = resolve_model_path(
            _env("ERIS_LLAMACPP_VISION_MODEL") or "src/moondream2-q4_k.gguf"
        )
        self.vision_mmproj_path = resolve_model_path(
            _env("ERIS_LLAMACPP_VISION_MMPROJ") or "src/moondream2-mmproj-f16.gguf"
        )
        self.n_ctx = int(_env("ERIS_LLAMACPP_N_CTX", "4096") or 4096)
        self.n_gpu_layers = _n_gpu_layers()

    # ------------------------------------------------------------------
    # Model loading (cached)
    # ------------------------------------------------------------------
    def _text_llm(self) -> Any:
        key = ("text", self.text_model_path)
        with LocalLlamaEngine._lock:
            inst = LocalLlamaEngine._cache.get(key)
            if inst is None:
                from llama_cpp import Llama

                inst = Llama(
                    model_path=self.text_model_path,
                    n_ctx=self.n_ctx,
                    n_gpu_layers=self.n_gpu_layers,
                    verbose=False,
                )
                LocalLlamaEngine._cache[key] = inst
            return inst

    def _vision_llm(self) -> Any:
        key = ("vision", self.vision_model_path)
        with LocalLlamaEngine._lock:
            inst = LocalLlamaEngine._cache.get(key)
            if inst is None:
                from llama_cpp import Llama
                from llama_cpp.llama_chat_format import MoondreamChatHandler

                handler = MoondreamChatHandler(clip_model_path=self.vision_mmproj_path, verbose=False)
                inst = Llama(
                    model_path=self.vision_model_path,
                    chat_handler=handler,
                    n_ctx=self.n_ctx,
                    n_gpu_layers=self.n_gpu_layers,
                    verbose=False,
                )
                LocalLlamaEngine._cache[key] = inst
            return inst

    # ------------------------------------------------------------------
    # OllamaClient-compatible API
    # ------------------------------------------------------------------
    def chat_json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        images: Optional[list[str]] = None,
        schema: Optional[dict[str, Any]] = None,
        keep_alive: str | int | None = None,
        temperature: float = 0.0,
        options: Optional[dict[str, Any]] = None,
    ) -> OllamaResult:
        try:
            if images:
                content = self._chat_vision(messages, images, schema=schema, temperature=temperature)
                # keep_alive == 0 → giải phóng VRAM vision ngay (4GB chật).
                if str(keep_alive).strip() in {"0", "0s"}:
                    self.unload(model)
            else:
                content = self._chat_text(messages, schema=schema, temperature=temperature)
        except Exception as exc:  # runtime fallback sạch, không phá loop
            return OllamaResult(ok=False, error=f"{type(exc).__name__}:{exc}")

        parsed = self._parse_json_object(content)
        if parsed is None:
            return OllamaResult(ok=False, content=content, error="json_parse_failed")
        return OllamaResult(ok=True, parsed=parsed, content=content)

    def generate_json(
        self,
        model: str,
        prompt: str,
        *,
        images: Optional[list[str]] = None,
        schema: Optional[dict[str, Any]] = None,
        keep_alive: str | int | None = None,
        temperature: float = 0.0,
        options: Optional[dict[str, Any]] = None,
    ) -> OllamaResult:
        messages = [{"role": "user", "content": prompt}]
        return self.chat_json(
            model, messages, images=images, schema=schema,
            keep_alive=keep_alive, temperature=temperature, options=options,
        )

    def _response_format(self, schema: Optional[dict[str, Any]]) -> dict[str, Any]:
        rf: dict[str, Any] = {"type": "json_object"}
        if isinstance(schema, dict) and schema:
            rf["schema"] = schema
        return rf

    def _chat_text(self, messages, *, schema, temperature) -> str:
        llm = self._text_llm()
        out = llm.create_chat_completion(
            messages=messages,
            temperature=float(temperature),
            max_tokens=int(_env("ERIS_LLAMACPP_MAX_TOKENS", "768") or 768),
            response_format=self._response_format(schema),
        )
        return self._extract_content(out)

    def _chat_vision(self, messages, images, *, schema, temperature) -> str:
        llm = self._vision_llm()
        # Gộp text của messages thành một prompt + đính ảnh kiểu OpenAI multimodal.
        prompt_text = self._messages_to_text(messages)
        b64 = self.data_uri_to_base64(images[0]) if images else ""
        data_uri = f"data:image/png;base64,{b64}"
        vmsg = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt_text},
                ],
            }
        ]
        out = llm.create_chat_completion(
            messages=vmsg,
            temperature=float(temperature),
            max_tokens=int(_env("ERIS_LLAMACPP_VISION_MAX_TOKENS", "512") or 512),
            response_format=self._response_format(schema),
        )
        return self._extract_content(out)

    def unload(self, model: str) -> OllamaResult:
        """Giải phóng model vision khỏi VRAM (text giữ resident)."""
        with LocalLlamaEngine._lock:
            key = ("vision", self.vision_model_path)
            inst = LocalLlamaEngine._cache.pop(key, None)
        if inst is not None:
            try:
                close = getattr(inst, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
            del inst
        return OllamaResult(ok=True)

    def list_models(self) -> OllamaResult:
        return OllamaResult(ok=True, parsed={"models": [self.text_model_path, self.vision_model_path]})

    # ------------------------------------------------------------------
    # Helpers (giữ chữ ký như OllamaClient)
    # ------------------------------------------------------------------
    @staticmethod
    def encode_image_file(path: str) -> str:
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")

    @staticmethod
    def encode_image_bytes(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def data_uri_to_base64(data_uri_or_base64: str) -> str:
        text = str(data_uri_or_base64 or "").strip()
        if text.startswith("data:") and "," in text:
            return text.split(",", 1)[1]
        return text

    @staticmethod
    def _messages_to_text(messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for m in messages or []:
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text" and str(c.get("text") or "").strip():
                        parts.append(str(c["text"]).strip())
        return "\n\n".join(parts).strip() or "Describe this screen concisely as JSON."

    @staticmethod
    def _extract_content(raw: Any) -> str:
        if isinstance(raw, dict):
            choices = raw.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(msg, dict):
                    return str(msg.get("content") or "")
        return str(raw or "")

    @staticmethod
    def _parse_json_object(content: str) -> Optional[dict[str, Any]]:
        text = str(content or "").strip()
        if not text:
            return None
        # Bóc fence markdown nếu có.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
        candidates = [text]
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])
        for cand in candidates:
            try:
                obj = json.loads(cand)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                return obj
        return None


def build_local_or_ollama_client(*, timeout: float | None = None):
    """Trả LocalLlamaEngine nếu ERIS_LOCAL_LLM_ENGINE=llamacpp, ngược lại OllamaClient.

    Dùng làm điểm chuyển đổi engine duy nhất cho observer/sensory/vision.
    """
    engine = _env("ERIS_LOCAL_LLM_ENGINE", "ollama").lower()
    if engine in {"llamacpp", "llama_cpp", "local", "gguf"}:
        return LocalLlamaEngine(timeout=timeout)
    from llm.ollama_client import OllamaClient

    return OllamaClient() if timeout is None else OllamaClient(timeout=timeout)
