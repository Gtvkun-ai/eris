from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from llm.ollama_client import OllamaClient, OllamaResult


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


@dataclass(slots=True, frozen=True)
class DaydreamModelAdapterConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_DAYDREAM_ENABLED", True))
    provider: str = field(default_factory=lambda: str(os.getenv("ERIS_DAYDREAM_PROVIDER", "ollama") or "ollama").strip().lower())
    model: str = field(default_factory=lambda: str(os.getenv("ERIS_DAYDREAM_MODEL", "qwen3.5:4b") or "qwen3.5:4b").strip())
    keep_alive: str | int | None = field(default_factory=lambda: os.getenv("ERIS_DAYDREAM_KEEP_ALIVE", "0"))
    timeout_seconds: float = field(default_factory=lambda: float(os.getenv("ERIS_DAYDREAM_TIMEOUT", "45") or 45.0))
    llama_server_url: str = field(default_factory=lambda: str(os.getenv("ERIS_DAYDREAM_LLAMA_SERVER_URL", os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1")) or "http://127.0.0.1:8080/v1").strip())


@dataclass(slots=True, frozen=True)
class DaydreamModelResult:
    ok: bool
    parsed: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RuntimeDaydreamModelAdapter:
    """Adapter riêng cho daydream 4B, không ké style client."""

    def __init__(
        self,
        *,
        config: DaydreamModelAdapterConfig | None = None,
        ollama_client: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        self.config = config or DaydreamModelAdapterConfig()
        self.logger = logger
        self.ollama_client = ollama_client if ollama_client is not None else (OllamaClient(timeout=self.config.timeout_seconds) if self.config.provider == "ollama" else None)
        self._llama_server_model: str | None = None

    @classmethod
    def from_env(cls, *, logger: Any | None = None) -> "RuntimeDaydreamModelAdapter | None":
        config = DaydreamModelAdapterConfig()
        if not config.enabled:
            return None
        return cls(config=config, logger=logger)

    def chat_json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        keep_alive: str | int | None = None,
        temperature: float = 0.0,
    ) -> DaydreamModelResult:
        selected_model = str(model or self.config.model or "").strip()
        if not selected_model:
            return DaydreamModelResult(ok=False, error="missing_model")
        if self.config.provider == "ollama":
            if self.ollama_client is None:
                return DaydreamModelResult(ok=False, error="missing_ollama_client")
            result = self.ollama_client.chat_json(
                selected_model,
                messages,
                keep_alive=self.config.keep_alive if keep_alive is None else keep_alive,
                temperature=temperature,
            )
            return self._from_ollama_result(result)
        if self.config.provider == "llama_server":
            return self._llama_server_chat_json(selected_model, messages, temperature=temperature)
        return DaydreamModelResult(ok=False, error=f"unsupported_provider:{self.config.provider}")

    def _from_ollama_result(self, result: OllamaResult) -> DaydreamModelResult:
        if not getattr(result, "ok", False):
            return DaydreamModelResult(
                ok=False,
                content=str(getattr(result, "content", "") or ""),
                error=str(getattr(result, "error", "unknown") or "unknown"),
                raw=dict(getattr(result, "raw", {}) or {}),
            )
        parsed = getattr(result, "parsed", None)
        return DaydreamModelResult(
            ok=isinstance(parsed, dict),
            parsed=dict(parsed or {}),
            content=str(getattr(result, "content", "") or ""),
            raw=dict(getattr(result, "raw", {}) or {}),
            error="" if isinstance(parsed, dict) else "invalid_json",
        )

    def _llama_server_chat_json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
    ) -> DaydreamModelResult:
        payload = {
            "model": self._llama_server_model_name(model),
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            raw = self._llama_request("POST", "/chat/completions", payload)
            content = self._llama_content(raw)
            parsed = json.loads(content or "{}")
            if not isinstance(parsed, dict):
                return DaydreamModelResult(ok=False, content=content, error="invalid_json", raw=raw)
            return DaydreamModelResult(ok=True, parsed=parsed, content=content, raw=raw)
        except Exception as exc:
            self._log("warning", "Daydream llama-server failed: %s", exc)
            return DaydreamModelResult(ok=False, error=f"{type(exc).__name__}:{exc}")

    def _llama_server_model_name(self, fallback: str) -> str:
        if self._llama_server_model:
            return self._llama_server_model
        try:
            raw = self._llama_request("GET", "/models", None)
            data = raw.get("data")
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, Mapping):
                    self._llama_server_model = str(first.get("id") or fallback)
        except Exception:
            self._llama_server_model = fallback
        return self._llama_server_model or fallback

    def _llama_request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        url = self.config.llama_server_url.rstrip("/") + path
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:  # noqa: S310 - local runtime URL from env
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body or "{}")
        return parsed if isinstance(parsed, dict) else {}

    def _llama_content(self, raw: Mapping[str, Any]) -> str:
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, Mapping):
                message = first.get("message")
                if isinstance(message, Mapping):
                    return str(message.get("content") or "")
        return str(raw.get("content") or "")

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(msg, *args)
