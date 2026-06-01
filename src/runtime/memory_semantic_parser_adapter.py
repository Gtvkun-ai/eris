from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from memory.understanding.semantic_parser import (
    FallbackSurfaceSemanticParser,
    MeaningParseResult,
    ModelSemanticParser,
    StructuredFrameParser,
)


_SYSTEM_PROMPT = """Bạn là semantic frame parser cho memory intake ERIS.
Nhiệm vụ duy nhất: chuyển user_text tự nhiên thành danh sách MeaningFrame JSON.
Không quyết định lưu memory. Không chọn semantic/episodic/candidate.
Không giải thích. Không suy diễn ngoài câu chữ.
Nếu user hỏi lại ký ức phiên như "tôi tên gì", "câu đầu tiên tôi nhắn là gì", hãy tạo frame session_event/asked_about hoặc không tạo frame dài hạn.
Nếu user muốn ERIS nhớ nhưng câu mơ hồ, tạo frame_type="memory_request", relation="remember_unresolved", target.text là câu gốc hoặc nội dung cần giữ, và slots.candidate_fact_keys nếu đoán được.
Với fact rõ, relation có thể là relation trừu tượng như "name" hoặc fact_key như "user.name".
Chỉ trả JSON."""

_USER_PROMPT_TEMPLATE = """Phân tích câu người dùng sau thành meaning frames JSON.

Schema:
{
  "frames": [
    {
      "frame_type": "identity|location|preference|instruction|feedback|correction|memory_request|project|unknown",
      "relation": "name|user.name|hometown|user.hometown|living_location|current_location|likes|dislikes|response_style|remember_unresolved|...",
      "subject": "user|eris|project:ERIS|other",
      "target": {
        "text": "...",
        "kind": "person_name|location|style|project|text|unknown"
      },
      "polarity": "asserted|denied|uncertain|hypothetical|quoted",
      "modality": "fact|preference|desire|belief|instruction|feedback|observation",
      "time_scope": "current|session|stable|past|future|habitual|unknown",
      "certainty": 0.0,
      "evidence_span": "đoạn chữ gốc",
      "slots": {
        "candidate_fact_keys": ["user.name"],
        "domain_guess": "identity|project_logic|style_or_vibe|general_memory_candidate"
      }
    }
  ]
}


Ví dụ bắt buộc:
- user_text: "tôi tên Hòa" -> frames[0]: frame_type="identity", relation="user.name", target.text="Hòa", target.kind="person_name", modality="fact", time_scope="stable", certainty>=0.80.
- user_text: "gọi tôi là Hòa" -> tương tự user.name, vì đây là preferred name.
- user_text: "tôi tên gì" -> không tạo identity fact; nếu cần thì frame_type="session_event", relation="asked_about", target.text="user.name".
- user_text: "nhớ vibe này" -> frame_type="memory_request", relation="remember_unresolved", target.text là câu gốc, slots.domain_guess="style_or_vibe".
- user_text: "câu đầu tiên tôi nhắn là gì" -> session query, không tạo semantic fact.

user_text:
{text}
"""


@dataclass(slots=True)
class _StandaloneOllamaResult:
    ok: bool
    parsed: Mapping[str, Any] | None = None
    error: str = ""


class _StandaloneOllamaClient:
    """Client Ollama tối thiểu cho memory parser, tránh import package llm."""

    def __init__(self, base_url: str | None = None, timeout: float = 4.0) -> None:
        self.base_url = str(base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = float(timeout or 4.0)

    def chat_json(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        keep_alive: str | int = "10m",
        temperature: float = 0.0,
    ) -> _StandaloneOllamaResult:
        payload = {
            "model": model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"temperature": temperature},
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - local/runtime URL từ env
                raw = resp.read().decode("utf-8", errors="replace")
            outer = json.loads(raw or "{}")
            message = outer.get("message") if isinstance(outer, Mapping) else None
            content = message.get("content") if isinstance(message, Mapping) else outer.get("response") if isinstance(outer, Mapping) else ""
            parsed = _parse_json_object(str(content or ""))
            return _StandaloneOllamaResult(ok=parsed is not None, parsed=parsed, error="" if parsed is not None else "ollama_json_parse_failed")
        except Exception as exc:
            return _StandaloneOllamaResult(ok=False, error=f"{type(exc).__name__}:{exc}")


class _StandaloneLlamaServerClient:
    """Client tối thiểu cho memory semantic parser."""

    def __init__(self, base_url: str, timeout: float = 4.0) -> None:
        self.base_url = str(base_url or "http://127.0.0.1:8080/v1").rstrip("/")
        self.timeout = float(timeout or 4.0)
        self.model_name = self._detect_model_name()

    def _json_request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - local/runtime URL từ env
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}

    def _detect_model_name(self) -> str:
        try:
            payload = self._json_request("GET", f"{self.base_url}/models")
            models = payload.get("data")
            if isinstance(models, list) and models:
                first = models[0]
                if isinstance(first, Mapping):
                    return str(first.get("id") or "local-model")
        except Exception:
            pass
        return "local-model"

    def create_chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        frequency_penalty: float,
        presence_penalty: float,
        max_tokens: int,
        response_format: Mapping[str, Any] | None = None,
        grammar: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        if grammar is not None:
            payload["grammar"] = grammar
        old_timeout = self.timeout
        if timeout is not None:
            self.timeout = float(timeout)
        try:
            return self._json_request("POST", f"{self.base_url}/chat/completions", payload)
        finally:
            self.timeout = old_timeout


@dataclass(frozen=True, slots=True)
class MemorySemanticParserConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_SEMANTIC_PARSER", False))
    provider: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_PROVIDER", "ollama").strip().lower() or "ollama")
    model: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_MODEL", "qwen3:0.6b").strip() or "qwen3:0.6b")
    llama_server_url: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_LLAMA_SERVER_URL", os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1")).strip() or "http://127.0.0.1:8080/v1")
    timeout_seconds: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_SEMANTIC_TIMEOUT", 4.0))
    fallback_enabled: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_SEMANTIC_FALLBACK", True))
    keep_alive: str | int = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_KEEP_ALIVE", "10m"))
    max_tokens: int = field(default_factory=lambda: _env_int("ERIS_MEMORY_SEMANTIC_MAX_TOKENS", 384))

    @classmethod
    def from_env(cls) -> "MemorySemanticParserConfig":
        return cls()


@dataclass(slots=True)
class RuntimeSemanticParser:
    """Adapter runtime -> MeaningFrame JSON -> verified MeaningParseResult."""

    llm_service: Any = None
    model: str = ""
    provider: str = "ollama"
    llama_server_url: str = ""
    timeout_seconds: float = 4.0
    fallback_enabled: bool = True
    keep_alive: str | int = "10m"
    max_tokens: int = 384
    ollama_client: Any | None = None
    logger: Any | None = None
    _llama_server_client: Any | None = field(default=None, init=False, repr=False)
    verifier: StructuredFrameParser = field(default_factory=StructuredFrameParser, repr=False)
    fallback_parser: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "ollama").strip().lower()
        self.model = str(self.model or "").strip()
        self.logger = self.logger or logging.getLogger(__name__)
        if self.ollama_client is None and self.provider == "ollama":
            self.ollama_client = _StandaloneOllamaClient(timeout=self.timeout_seconds)
        self._llama_server_client = None
        if self.provider == "llama_server":
            self._llama_server_client = _StandaloneLlamaServerClient(self.llama_server_url, timeout=self.timeout_seconds)
        if self.fallback_parser is None and self.fallback_enabled:
            self.fallback_parser = FallbackSurfaceSemanticParser()

    @classmethod
    def from_env(cls, *, llm_service: Any = None, logger: Any = None) -> "RuntimeSemanticParser | None":
        config = MemorySemanticParserConfig.from_env()
        if not config.enabled:
            return None
        return cls(
            llm_service=llm_service,
            model=config.model,
            provider=config.provider,
            llama_server_url=config.llama_server_url,
            timeout_seconds=config.timeout_seconds,
            fallback_enabled=config.fallback_enabled,
            keep_alive=config.keep_alive,
            max_tokens=config.max_tokens,
            logger=logger,
        )

    def parse(
        self,
        text: str,
        *,
        structured: Mapping[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> MeaningParseResult:
        raw = str(text or "").strip()
        if not raw:
            return MeaningParseResult(source="runtime_memory_parser", confidence=0.0, diagnostics=("empty_input",))
        if structured is not None:
            return self.verifier.parse(raw, structured=structured)

        try:
            payload = self._call_provider(raw, context=context)
            if payload:
                return ModelSemanticParser(lambda _text: payload, fallback=self.fallback_parser).parse(raw)
        except Exception as exc:
            self._log_warning("Runtime semantic parser failed: %s", exc)
            if self.fallback_parser is not None:
                result = self.fallback_parser.parse(raw)
                return MeaningParseResult(
                    frames=result.frames,
                    source="runtime_memory_parser_fallback",
                    confidence=result.confidence,
                    diagnostics=(f"provider_error:{type(exc).__name__}", *result.diagnostics),
                )
            return MeaningParseResult(source="runtime_memory_parser_failed", confidence=0.0, diagnostics=(f"provider_error:{type(exc).__name__}",))

        if self.fallback_parser is not None:
            result = self.fallback_parser.parse(raw)
            return MeaningParseResult(
                frames=result.frames,
                source="runtime_memory_parser_empty_fallback",
                confidence=result.confidence,
                diagnostics=("empty_provider_payload", *result.diagnostics),
            )
        return MeaningParseResult(source="runtime_memory_parser_empty", confidence=0.0, diagnostics=("empty_provider_payload",))

    def _call_provider(self, text: str, *, context: dict[str, Any] | None = None) -> Mapping[str, Any] | None:
        if self.provider == "ollama":
            return self._call_ollama(text, context=context)
        if self.provider == "llama_server":
            return self._call_llama_server(text, context=context)
        if self.provider == "llm_service":
            return self._call_llm_service(text, context=context)
        raise RuntimeError(f"unsupported_memory_semantic_provider:{self.provider}")

    def _call_ollama(self, text: str, *, context: dict[str, Any] | None = None) -> Mapping[str, Any] | None:
        client = self.ollama_client
        if client is None or not callable(getattr(client, "chat_json", None)):
            raise RuntimeError("missing_ollama_client")
        result = client.chat_json(
            self.model,
            self._messages(text, context=context),
            keep_alive=self.keep_alive,
            temperature=0.0,
        )
        if not getattr(result, "ok", False):
            raise RuntimeError(getattr(result, "error", "ollama_failed") or "ollama_failed")
        parsed = getattr(result, "parsed", None)
        return parsed if isinstance(parsed, Mapping) else None

    def _call_llama_server(self, text: str, *, context: dict[str, Any] | None = None) -> Mapping[str, Any] | None:
        client = getattr(self, "_llama_server_client", None)
        if not isinstance(client, _StandaloneLlamaServerClient):
            client = _StandaloneLlamaServerClient(self.llama_server_url, timeout=self.timeout_seconds)
            self._llama_server_client = client
        response = client.create_chat_completion(
            messages=self._messages(text, context=context),
            temperature=0.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            grammar=None,
            timeout=self.timeout_seconds,
        )
        content = _extract_response_text(response)
        payload = _parse_json_object(content)
        if not isinstance(payload, Mapping):
            raise RuntimeError("llama_server_json_parse_failed")
        return payload

    def _call_llm_service(self, text: str, *, context: dict[str, Any] | None = None) -> Mapping[str, Any] | None:
        service = self.llm_service
        client = getattr(service, "client", None)
        if not callable(getattr(client, "create_chat_completion", None)):
            raise RuntimeError("llm_service_client_missing_chat_completion")
        client_name = type(client).__name__.lower()
        base_url = str(getattr(client, "base_url", "") or "").lower()
        if "llama" not in client_name and "127.0.0.1" not in base_url and "localhost" not in base_url:
            raise RuntimeError("llm_service_client_not_local_llama_server")
        response = client.create_chat_completion(
            messages=self._messages(text, context=context),
            temperature=0.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            grammar=None,
            timeout=self.timeout_seconds,
        )
        extractor = getattr(service, "_extract_content", None)
        content = str(extractor(response) or "") if callable(extractor) else _extract_response_text(response)
        payload = _parse_json_object(content)
        if not isinstance(payload, Mapping):
            raise RuntimeError("llm_service_json_parse_failed")
        return payload

    def _messages(self, text: str, *, context: dict[str, Any] | None = None) -> list[dict[str, str]]:
        prompt = _USER_PROMPT_TEMPLATE.format(text=text)
        if context:
            compact_context = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
            prompt = f"{prompt}\n\nruntime_context:\n{compact_context}"
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def _log_warning(self, message: str, *args: Any) -> None:
        logger = self.logger
        if logger is not None and callable(getattr(logger, "warning", None)):
            logger.warning(message, *args)


def build_runtime_memory_semantic_parser(*, llm_service: Any = None, logger: Any = None) -> RuntimeSemanticParser | None:
    return RuntimeSemanticParser.from_env(llm_service=llm_service, logger=logger)


def _extract_response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return ""
    direct = response.get("output_text") or response.get("text") or response.get("content")
    if isinstance(direct, str):
        return direct
    choices = response.get("choices")
    if not isinstance(choices, list):
        return ""
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message")
        if isinstance(message, Mapping) and isinstance(message.get("content"), str):
            return str(message.get("content") or "")
    return ""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except Exception:
        return default


__all__ = [
    "MemorySemanticParserConfig",
    "RuntimeSemanticParser",
    "build_runtime_memory_semantic_parser",
]
