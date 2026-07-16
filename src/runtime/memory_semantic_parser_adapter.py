from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from memory.understanding.semantic_parser import (
    FallbackSurfaceSemanticParser,
    MeaningParseResult,
    ModelSemanticParser,
    StructuredFrameParser,
)


_SYSTEM_PROMPT = """Báº¡n lÃ  memory classification engine cho ERIS.
Nhiá»‡m vá»¥: nháº­n user_text vÃ  quyáº¿t Ä‘á»‹nh nÃ³ nÃªn Ä‘Æ°á»£c lÆ°u vÃ o memory nhÆ° tháº¿ nÃ o.

Báº¡n pháº£i quyáº¿t Ä‘á»‹nh hoÃ n toÃ n â€” khÃ´ng cáº§n theo schema cá»©ng. Má»—i máº£nh thÃ´ng tin cÃ³ thá»ƒ:
- LÃ  fact á»•n Ä‘á»‹nh (tÃªn, sinh nháº­t, quÃª, sá»Ÿ thÃ­ch lÃ¢u dÃ i)
- LÃ  sá»± kiá»‡n (chuyá»‡n xáº£y ra, cÃ³ thá»i gian, cÃ³ ngá»¯ cáº£nh)
- LÃ  cáº£m xÃºc/tÃ¢m tráº¡ng thoÃ¡ng qua (buá»“n hÃ´m nay, má»‡t, vui vÃ¬ Ä‘iá»u gÃ¬)
- LÃ  kiáº¿n thá»©c (dáº¡y ERIS biáº¿t Ä‘iá»u gÃ¬ vá» tháº¿ giá»›i, ká»¹ thuáº­t, khÃ¡i niá»‡m)
- LÃ  thá»±c thá»ƒ (ngÆ°á»i, váº­t, Ä‘á»‹a Ä‘iá»ƒm user Ä‘á» cáº­p â€” con mÃ¨o hÃ ng xÃ³m, báº¡n tÃªn X, quÃ¡n Äƒn)
- LÃ  niá»m tin/quan Ä‘iá»ƒm (user nghÄ© A lÃ  Ä‘Ãºng, khÃ´ng Ä‘á»“ng Ã½ vá»›i B)
- LÃ  má»¥c tiÃªu (user muá»‘n lÃ m gÃ¬, dá»± Ä‘á»‹nh gÃ¬)
- LÃ  pháº£n há»“i vá» ERIS (khen, chÃª, sá»­a, hÆ°á»›ng dáº«n cÃ¡ch pháº£n há»“i)
- LÃ  quy Æ°á»›c (tá»« giá» X nghÄ©a lÃ  Y, gá»i tÃ´i lÃ  Z)
- LÃ  ngá»¯ cáº£nh thoÃ¡ng qua (khÃ´ng quan trá»ng lÃ¢u dÃ i)

Vá»›i má»—i frame, báº¡n quyáº¿t Ä‘á»‹nh:
- memory_type: loáº¡i memory (fact, event, emotion, knowledge, entity, belief, goal, feedback, convention, context)
- storage_target: nÆ¡i lÆ°u (semantic, episodic, procedural, affective_residue, relational, candidate)
- importance: 0.0-1.0 (fact tÃªn=0.95, cáº£m xÃºc thoÃ¡ng=0.3, kiáº¿n thá»©c chung=0.6)
- decay: slow (nÄƒm+) | normal (thÃ¡ng) | fast (tuáº§n) | ephemeral (ngÃ y/session)
- surface_fn: can_answer (tráº£ lá»i trá»±c tiáº¿p khi há»i) | background (áº£nh hÆ°á»Ÿng context) | never (khÃ´ng surface)
- fact_key: key ngáº¯n náº¿u lÃ  fact rÃµ (user.name, user.hometown, ...) hoáº·c Ä‘á»ƒ trá»‘ng

Quy táº¯c storage_target:
- semantic: fact á»•n Ä‘á»‹nh, kiáº¿n thá»©c, niá»m tin, thá»±c thá»ƒ quan trá»ng
- episodic: sá»± kiá»‡n cá»¥ thá»ƒ cÃ³ thá»i gian/ngá»¯ cáº£nh
- procedural: quy táº¯c hÃ nh vi, convention, cÃ¡ch xá»­ lÃ½
- affective_residue: cáº£m xÃºc, tÃ¢m tráº¡ng (KHÃ”NG surface nhÆ° fact)
- relational: pattern quan há»‡ vá»›i user, ngÆ°á»i khÃ¡c
- candidate: khÃ´ng cháº¯c cháº¯n, cáº§n xem xÃ©t thÃªm

KhÃ´ng táº¡o frame cho: cÃ¢u há»i recall ("tÃ´i tÃªn gÃ¬"), chÃ o há»i Ä‘Æ¡n giáº£n, cÃ¢u vÃ´ nghÄ©a.
Chá»‰ tráº£ JSON."""

_USER_PROMPT_TEMPLATE = """PhÃ¢n tÃ­ch vÃ  phÃ¢n loáº¡i memory cho cÃ¢u sau.

Output schema:
{
  "frames": [
    {
      "memory_type": "fact|event|emotion|knowledge|entity|belief|goal|feedback|convention|context",
      "storage_target": "semantic|episodic|procedural|affective_residue|relational|candidate",
      "subject": "user|eris|world|other:<name>",
      "claim": "cÃ¢u tÃ³m táº¯t ngáº¯n gá»n cÃ¡i cáº§n nhá»› (khÃ´ng pháº£i raw text)",
      "value": "giÃ¡ trá»‹ cá»‘t lÃµi náº¿u lÃ  fact/entity (tÃªn ngÆ°á»i, Ä‘á»‹a Ä‘iá»ƒm, ...) hoáº·c null",
      "fact_key": "user.name | user.hometown | ... hoáº·c '' náº¿u khÃ´ng cÃ³ key chuáº©n",
      "importance": 0.0,
      "decay": "slow|normal|fast|ephemeral",
      "surface_fn": "can_answer|background|never",
      "time_scope": "stable|current|past|future|session",
      "confidence": 0.0,
      "why": "lÃ½ do ngáº¯n â€” táº¡i sao phÃ¢n loáº¡i tháº¿ nÃ y"
    }
  ]
}

VÃ­ dá»¥:
- "tÃ´i tÃªn HÃ²a" â†’ memory_type=fact, storage_target=semantic, fact_key=user.name, value=HÃ²a, importance=0.95, decay=slow, surface_fn=can_answer
- "con mÃ¨o nhÃ  hÃ ng xÃ³m tÃªn Miso hay sang Äƒn trá»™m Ä‘á»“" â†’ memory_type=entity, storage_target=episodic, fact_key='', importance=0.45, decay=normal, surface_fn=background
- "tÃ´i Ä‘ang buá»“n vÃ¬ dá»± Ã¡n bá»‹ delay" â†’ memory_type=emotion, storage_target=affective_residue, importance=0.35, decay=fast, surface_fn=never
- "Python lÃ  ngÃ´n ngá»¯ láº­p trÃ¬nh hÆ°á»›ng Ä‘á»‘i tÆ°á»£ng" â†’ memory_type=knowledge, storage_target=semantic, importance=0.55, decay=slow, surface_fn=background
- "tá»« giá» khi tÃ´i nÃ³i 'loi' tá»©c lÃ  bug" â†’ memory_type=convention, storage_target=procedural, importance=0.88, decay=slow, surface_fn=background
- "tÃ´i muá»‘n build game nháº­p vai nÄƒm nay" â†’ memory_type=goal, storage_target=semantic, importance=0.72, decay=normal, surface_fn=background
- "tráº£ lá»i ngáº¯n thÃ´i Ä‘á»«ng dÃ i dÃ²ng" â†’ memory_type=feedback, storage_target=procedural, fact_key=user.response_style, importance=0.85, decay=slow, surface_fn=background

user_text:
{text}
"""




@dataclass(frozen=True, slots=True)
class MemorySemanticParserConfig:
    enabled: bool = field(default_factory=lambda: _runtime_bool("memory", "semantic_parser", False))
    provider: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_PROVIDER", "llm_service").strip().lower() or "llm_service")
    model: str = field(default_factory=lambda: os.getenv("ERIS_MEMORY_SEMANTIC_MODEL", "").strip())
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
    provider: str = "llm_service"
    timeout_seconds: float = 4.0
    fallback_enabled: bool = True
    keep_alive: str | int = "10m"
    max_tokens: int = 384
    logger: Any | None = None
    verifier: StructuredFrameParser = field(default_factory=StructuredFrameParser, repr=False)
    fallback_parser: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "llm_service").strip().lower()
        self.model = str(self.model or "").strip()
        self.logger = self.logger or logging.getLogger(__name__)
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
        if self.provider == "llm_service":
            return self._call_llm_service(text, context=context)
        raise RuntimeError(f"unsupported_memory_semantic_provider:{self.provider}")

    def _call_llm_service(self, text: str, *, context: dict[str, Any] | None = None) -> Mapping[str, Any] | None:
        service = self.llm_service
        client = getattr(service, "client", None)
        if not callable(getattr(client, "create_chat_completion", None)):
            raise RuntimeError("llm_service_client_missing_chat_completion")
        # Dung bat ky remote client nao dang duoc cau hinh: Gemini hoac OpenAI-compatible.
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

def _runtime_bool(section: str, key: str, default: bool) -> bool:
    try:
        from runtime.runtime_settings_store import runtime_bool
        return runtime_bool(section, key, default=default)
    except Exception:
        return default



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
