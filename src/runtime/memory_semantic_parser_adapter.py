from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from llm.client import LlamaServerClient
from llm.ollama_client import OllamaClient
from memory.understanding.semantic_parser import (
    FallbackSurfaceSemanticParser,
    MeaningParseResult,
    ModelSemanticParser,
    StructuredFrameParser,
)


_SYSTEM_PROMPT = """Bạn là semantic frame parser.
Nhiệm vụ: chuyển user_text thành danh sách meaning frames.
Không quyết định lưu memory.
Không giải thích.
Không suy diễn ngoài câu chữ.
Nếu không chắc, dùng certainty thấp hoặc frame_type="unknown".
Chỉ trả JSON."""

_USER_PROMPT_TEMPLATE = """Phân tích câu người dùng sau thành meaning frames JSON.

Schema:
{
  "frames": [
    {
      "frame_type": "identity|location|preference|instruction|feedback|correction|memory_request|project|unknown",
      "relation": "name|hometown|living_location|current_location|likes|dislikes|style_preference|...",
      "subject": "user|eris|project:ERIS|other",
      "target": {
        "text": "...",
        "kind": "person_name|location|style|project|text|unknown"
      },
      "polarity": "asserted|denied|uncertain|hypothetical|quoted",
      "modality": "fact|preference|desire|belief|instruction|feedback|observation",
      "time_scope": "current|session|stable|past|future|habitual|unknown",
      "certainty": 0.0,
      "evidence_span": "đoạn chữ gốc"
    }
  ]
}

user_text:
{text}
"""


@dataclass(frozen=True, slots=True)
class MemorySemanticParserConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_SEMANTIC_PARSER", False))
    provider: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_PROVIDER", "ollama").strip().lower() or "ollama")
    model: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_MODEL", "qwen3:0.6b").strip() or "qwen3:0.6b")
    timeout_seconds: float = field(default_factory=lambda: _env_float("ERIS_MEMORY_SEMANTIC_TIMEOUT", 4.0))
    fallback_enabled: bool = field(default_factory=lambda: _env_flag("ERIS_MEMORY_SEMANTIC_FALLBACK", True))
    keep_alive: str | int = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_KEEP_ALIVE", "10m"))
    max_tokens: int = field(default_factory=lambda: _env_int("ERIS_MEMORY_SEMANTIC_MAX_TOKENS", 384))

    @classmethod
    def from_env(cls) -> "MemorySemanticParserConfig":
        return cls()


@dataclass(slots=True)
class RuntimeSemanticParser:
    """Adapter runtime -> MeaningFrame JSON -> verified MeaningParseResult.

    Lớp này chỉ gọi model để parse ngữ nghĩa câu user thành frame.
    Nó không commit memory, không quyết định retention, và không biết store nằm đâu.
    """

    llm_service: Any = None
    model: str = ""
    provider: str = "ollama"
    timeout_seconds: float = 4.0
    fallback_enabled: bool = True
    keep_alive: str | int = "10m"
    max_tokens: int = 384
    ollama_client: Any | None = None
    logger: Any | None = None
    verifier: StructuredFrameParser = field(default_factory=StructuredFrameParser, repr=False)
    fallback_parser: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "ollama").strip().lower()
        self.model = str(self.model or "").strip()
        self.logger = self.logger or logging.getLogger(__name__)
        if self.ollama_client is None and self.provider == "ollama":
            self.ollama_client = OllamaClient(timeout=self.timeout_seconds)
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
                # Verify JSON shape through the memory-owned parser contract.
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
        if self.provider in {"llama_server", "llm_service"}:
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

    def _call_llm_service(self, text: str, *, context: dict[str, Any] | None = None) -> Mapping[str, Any] | None:
        service = self.llm_service
        client = getattr(service, "client", None)
        if not isinstance(client, LlamaServerClient):
            raise RuntimeError("llm_service_client_not_llama_server")
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
