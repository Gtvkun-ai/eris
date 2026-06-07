# -*- coding: utf-8 -*-
"""
runtime/private_mind_model_adapter.py
=====================================

Adapter API cho private mind:
- evaluate_fragment(evaluator_name, dossier)
- synthesize_judgment(dossier, fragments)

Adapter này ưu tiên dùng `llm_service` nếu được inject từ coordinator; nếu không
thì cố build provider từ env giống các adapter runtime khác. Khi API hỏng, nó
trả None để rule fallback chạy tiếp. Nội tâm không nên chết vì HTTP 500, tuy thế
cũng đừng biến HTTP 500 thành thơ.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from ast import literal_eval
from dataclasses import dataclass, field
from typing import Any, Mapping

from cortex.private_mind.contracts import EvidenceDossier, ThoughtFragment, compact_text, to_plain
from eris_secrets import apply_secrets_to_environ, get_secret
from llm.client import GeminiClient, LlamaServerClient, OpenAICompatibleClient


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


@dataclass(slots=True, frozen=True)
class PrivateMindModelAdapterConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_PRIVATE_MIND_API_ENABLED", False))
    provider: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_PROVIDER", os.getenv("ERIS_DAYDREAM_PROVIDER", "llama_server")) or "llama_server").strip().lower())
    model: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_MODEL", os.getenv("ERIS_DAYDREAM_MODEL", "gemma-4-26b-a4b-it")) or "gemma-4-26b-a4b-it").strip())
    base_url: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_BASE_URL", os.getenv("ERIS_REMOTE_BASE_URL", "")) or "").strip())
    api_key: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_API_KEY", "") or "").strip())
    llama_server_url: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_LLAMA_SERVER_URL", os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1")) or "http://127.0.0.1:8080/v1").strip())
    timeout_seconds: float = field(default_factory=lambda: max(4.0, _as_float(os.getenv("ERIS_PRIVATE_MIND_TIMEOUT", "28"), 28.0)))
    temperature: float = field(default_factory=lambda: _as_float(os.getenv("ERIS_PRIVATE_MIND_TEMPERATURE", "0.15"), 0.15))
    max_tokens_fragment: int = field(default_factory=lambda: max(128, int(os.getenv("ERIS_PRIVATE_MIND_FRAGMENT_TOKENS", "420") or 420)))
    max_tokens_judgment: int = field(default_factory=lambda: max(256, int(os.getenv("ERIS_PRIVATE_MIND_JUDGMENT_TOKENS", "900") or 900)))


@dataclass(slots=True)
class PrivateMindModelResult:
    ok: bool
    parsed: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RuntimePrivateMindModelAdapter:
    """Adapter chung cho 4 mini-evaluator và GemmaInnerSynthesizer."""

    def __init__(self, *, config: PrivateMindModelAdapterConfig | None = None, llm_service: Any = None, logger: Any = None) -> None:
        self.config = config or PrivateMindModelAdapterConfig()
        self.llm_service = llm_service
        self.logger = logger
        self._llama_model_name: str | None = None
        self._provider_client: Any | None = None
        self._calls = 0
        self._ok_calls = 0
        self._failed_calls = 0
        self._total_latency_ms = 0.0
        self._total_tokens = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._last_error = ""
        self._last_call_at = 0.0
        self._invalid_json_streak = 0
        self._json_cooldown_until = 0.0

    @classmethod
    def from_env(cls, *, llm_service: Any = None, logger: Any = None) -> "RuntimePrivateMindModelAdapter | None":
        apply_secrets_to_environ()
        config = PrivateMindModelAdapterConfig()
        if not config.enabled:
            return None
        adapter = cls(config=config, llm_service=llm_service, logger=logger)
        adapter._log("info", "[PrivateMind API] ready provider=%s model=%s", config.provider, config.model)
        return adapter

    @property
    def min_interval_seconds(self) -> float:
        return 0.0

    def evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier) -> Mapping[str, Any] | None:
        messages = self._fragment_messages(evaluator_name, dossier)
        result = self._tracked_chat_json(
            messages,
            max_tokens=self.config.max_tokens_fragment,
            response_schema=self._fragment_response_schema(evaluator_name),
        )
        if not result.ok:
            if result.error != "invalid_json_cooldown":
                self._log("warning", "[PrivateMind API] fragment failed evaluator=%s error=%s", evaluator_name, result.error)
            return None
        parsed = dict(result.parsed)
        parsed.setdefault("source", evaluator_name)
        parsed.setdefault("provider", self.config.provider)
        parsed.setdefault("model", self.config.model)
        return parsed

    def synthesize_judgment(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> Mapping[str, Any] | None:
        messages = self._judgment_messages(dossier, fragments)
        result = self._tracked_chat_json(
            messages,
            max_tokens=self.config.max_tokens_judgment,
            response_schema=self._judgment_response_schema(),
        )
        if not result.ok:
            if result.error != "invalid_json_cooldown":
                self._log("warning", "[PrivateMind API] synthesis failed error=%s", result.error)
            return None
        parsed = dict(result.parsed)
        parsed.setdefault("provider", self.config.provider)
        parsed.setdefault("model", self.config.model)
        return parsed

    def _fragment_messages(self, evaluator_name: str, dossier: EvidenceDossier) -> list[dict[str, str]]:
        evaluator_contract = {
            "intent_evaluator": "Estimate what the user/runtime is trying to do. No public reply.",
            "memory_resonance_evaluator": "Find recurring user corrections/preferences and memory resonance. No public reply.",
            "risk_and_permission_evaluator": "Find privacy/leak/API-cost/permission risks. No public reply.",
            "future_bias_evaluator": "Propose behavior-bias state mutations. No public reply.",
        }.get(evaluator_name, "Evaluate private cognition evidence. No public reply.")
        schema = {
            "source": evaluator_name,
            "claim": "private claim, not dialogue",
            "confidence": 0.0,
            "evidence_ids": ["must use only dossier evidence ids"],
            "pressure": 0.0,
            "suggested_question": "private open question",
            "hypotheses": [{"label": "...", "description": "...", "confidence": 0.0, "evidence_ids": [], "pressure": 0.0}],
            "metadata": {"theme": "...", "state_mutations": []},
        }
        return [
            {
                "role": "system",
                "content": (
                    "You are a private evaluator inside ERIS. Return exactly one compact JSON object. "
                    "Do not write public speech. Do not expose chain-of-thought. Use only evidence_ids from dossier. "
                    f"Evaluator task: {evaluator_contract}. Required schema: {json.dumps(schema, ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": json.dumps(dossier.to_dict(), ensure_ascii=False)[:12000]},
        ]

    def _judgment_messages(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...]) -> list[dict[str, str]]:
        schema = {
            "dominant_judgment": "private verdict, not public speech",
            "ranked_hypotheses": [{"label": "...", "description": "...", "confidence": 0.0, "evidence_ids": [], "pressure": 0.0}],
            "rejected_hypotheses": [{"label": "...", "description": "...", "confidence": 0.0, "evidence_ids": [], "pressure": 0.0, "rejected": True, "reason": "..."}],
            "open_questions": ["..."],
            "private_concern_update": {"theme": "...", "pressure": 0.0, "uncertainty": 0.0, "evidence_ids": [], "open_questions": [], "future_biases": []},
            "state_mutations": [{"target": "speech_bias", "operation": "prefer", "value": "...", "confidence": 0.0, "evidence_ids": [], "reason": "...", "priority": 0.0}],
            "surface_candidate": None,
            "confidence": 0.0,
            "pressure": 0.0,
            "evidence_ids": [],
        }
        payload = {
            "dossier": dossier.to_dict(),
            "fragments": [f.to_dict() for f in fragments],
        }
        return [
            {
                "role": "system",
                "content": (
                    "You are GemmaInnerSynthesizer, a private judge inside ERIS. Return exactly one compact JSON object. "
                    "You are not a dialogue writer. Do not reveal private chain. State mutations must affect future behavior. "
                    "surface_candidate may be null; if present, it must be public-safe topic seed only. "
                    f"Required schema: {json.dumps(schema, ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": json.dumps(to_plain(payload), ensure_ascii=False)[:18000]},
        ]

    def _fragment_response_schema(self, evaluator_name: str) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "claim": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "pressure": {"type": "number"},
                "suggested_question": {"type": "string"},
                "hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "confidence": {"type": "number"},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            "pressure": {"type": "number"},
                        },
                    },
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "theme": {"type": "string"},
                        "state_mutations": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["claim", "confidence", "evidence_ids", "pressure"],
        }

    def _judgment_response_schema(self) -> dict[str, Any]:
        mutation_schema = {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "operation": {"type": "string"},
                "value": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "priority": {"type": "number"},
            },
        }
        hypothesis_schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "description": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "pressure": {"type": "number"},
                "rejected": {"type": "boolean"},
                "reason": {"type": "string"},
            },
        }
        return {
            "type": "object",
            "properties": {
                "dominant_judgment": {"type": "string"},
                "ranked_hypotheses": {"type": "array", "items": hypothesis_schema},
                "rejected_hypotheses": {"type": "array", "items": hypothesis_schema},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "private_concern_update": {
                    "type": "object",
                    "properties": {
                        "theme": {"type": "string"},
                        "pressure": {"type": "number"},
                        "uncertainty": {"type": "number"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "open_questions": {"type": "array", "items": {"type": "string"}},
                        "future_biases": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "state_mutations": {"type": "array", "items": mutation_schema},
                "surface_candidate": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "topic_seed": {"type": "string"},
                        "usefulness": {"type": "number"},
                        "confidence": {"type": "number"},
                        "interrupt_cost": {"type": "number"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                    "nullable": True,
                },
                "confidence": {"type": "number"},
                "pressure": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["dominant_judgment", "confidence", "pressure", "evidence_ids"],
        }

    def debug_status(self) -> dict[str, Any]:
        api_key_configured = bool(self.config.api_key or get_secret("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"))
        average_latency = self._total_latency_ms / self._calls if self._calls else 0.0
        return {
            "enabled": bool(self.config.enabled),
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": self.config.base_url or (self.config.llama_server_url if self.config.provider == "llama_server" else ""),
            "api_key_configured": api_key_configured,
            "api_degraded": bool(self._last_error or self._json_cooldown_active()),
            "calls": self._calls,
            "ok_calls": self._ok_calls,
            "failed_calls": self._failed_calls,
            "average_latency_ms": round(average_latency, 1),
            "last_call_at": round(float(self._last_call_at or 0.0), 3),
            "last_error": self._last_error,
            "invalid_json_streak": self._invalid_json_streak,
            "json_cooldown_until": round(float(self._json_cooldown_until or 0.0), 3),
            "usage": {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._total_tokens,
                "cost_known": False,
                "estimated_cost_usd": None,
            },
        }

    def _tracked_chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        if self._json_cooldown_active():
            self._last_error = "invalid_json_cooldown"
            return PrivateMindModelResult(ok=False, error="invalid_json_cooldown")
        started = time.time()
        result = self._chat_json(messages, max_tokens=max_tokens, response_schema=response_schema)
        elapsed_ms = (time.time() - started) * 1000.0
        self._calls += 1
        self._total_latency_ms += elapsed_ms
        self._last_call_at = time.time()
        if result.ok:
            self._ok_calls += 1
            self._last_error = ""
            self._invalid_json_streak = 0
        else:
            self._failed_calls += 1
            self._last_error = result.error
            if result.error == "invalid_json":
                self._invalid_json_streak += 1
                self._maybe_enter_json_cooldown()
            elif result.error != "invalid_json_cooldown":
                self._invalid_json_streak = 0
        usage = self._extract_usage(result.raw)
        self._prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self._completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self._total_tokens += int(usage.get("total_tokens", 0) or 0)
        return result

    def _json_cooldown_active(self) -> bool:
        return bool(self._json_cooldown_until and time.time() < self._json_cooldown_until)

    def _maybe_enter_json_cooldown(self) -> None:
        if self._invalid_json_streak < 3 or self._json_cooldown_active():
            return
        self._json_cooldown_until = time.time() + 120.0
        self._log(
            "warning",
            "[PrivateMind API] invalid_json cooldown active seconds=%d streak=%d",
            120,
            self._invalid_json_streak,
        )

    def _extract_usage(self, raw: Any) -> dict[str, int]:
        if not isinstance(raw, Mapping):
            return {}
        usage = raw.get("usage")
        if isinstance(usage, Mapping):
            prompt = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
            total = int(usage.get("total_tokens", prompt + completion) or 0)
            return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
        gemini_usage = raw.get("usageMetadata")
        if isinstance(gemini_usage, Mapping):
            prompt = int(gemini_usage.get("promptTokenCount", 0) or 0)
            completion = int(gemini_usage.get("candidatesTokenCount", 0) or 0)
            total = int(gemini_usage.get("totalTokenCount", prompt + completion) or 0)
            return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
        return {}

    def _chat_json(self, messages: list[dict[str, str]], *, max_tokens: int, response_schema: dict[str, Any] | None = None) -> PrivateMindModelResult:
        result = self._chat_json_once(messages, max_tokens=max_tokens, temperature=self.config.temperature, response_schema=response_schema)
        if result.error == "invalid_json" and result.content:
            retry = self._chat_json_once(
                self._json_repair_messages(messages, result.content),
                max_tokens=max_tokens,
                temperature=0.0,
                response_schema=response_schema,
            )
            if retry.ok:
                return retry
        return result

    def _chat_json_once(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        # Nếu llm_service có method chat JSON riêng thì dùng. Repo này chưa chuẩn hóa
        # hết service boundary, nên adapter phải bớt ngây thơ một chút.
        if self.llm_service is not None:
            for method_name in ("chat_json", "generate_json", "create_chat_completion"):
                method = getattr(self.llm_service, method_name, None)
                if callable(method):
                    try:
                        raw = method(messages=messages, temperature=temperature, max_tokens=max_tokens, response_format=self._response_format(response_schema))
                        content = self._extract_content(raw)
                        parsed = self._parse_json(content)
                        return PrivateMindModelResult(ok=bool(parsed), parsed=parsed, content=content, raw=self._safe_raw(raw), error="" if parsed else "invalid_json")
                    except TypeError:
                        continue
                    except Exception as exc:
                        return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}")
        if self.config.provider == "llama_server":
            return self._llama_server_chat_json(messages, max_tokens=max_tokens, temperature=temperature)
        if self.config.provider in {"gemini", "openai", "openai_compatible", "compatible", "remote"}:
            return self._provider_chat_json(messages, max_tokens=max_tokens, temperature=temperature, response_schema=response_schema)
        return PrivateMindModelResult(ok=False, error=f"unsupported_provider:{self.config.provider}")

    def _response_format(self, response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        response_format: dict[str, Any] = {"type": "json_object"}
        if self.config.provider == "gemini" and response_schema:
            response_format["schema"] = response_schema
        return response_format

    def _json_repair_messages(self, messages: list[dict[str, str]], invalid_content: str) -> list[dict[str, str]]:
        excerpt = compact_text(invalid_content, 1200)
        return [
            {
                "role": "system",
                "content": (
                    "Return only one JSON object. No markdown. No prose. No code fence. "
                    "Repair the previous output format only; preserve the intended private-evaluation fields."
                ),
            },
            *messages,
            {
                "role": "user",
                "content": (
                    "Previous invalid output excerpt, JSON-escaped for repair context: "
                    f"{json.dumps(excerpt, ensure_ascii=False)}\n"
                    "Return the corrected JSON object only."
                ),
            },
        ]

    def _provider_chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        response_schema: dict[str, Any] | None = None,
    ) -> PrivateMindModelResult:
        client = self._provider_client_or_build()
        if client is None:
            return PrivateMindModelResult(ok=False, error=f"missing_provider_client:{self.config.provider}")
        try:
            raw = client.create_chat_completion(
                messages=messages,
                temperature=temperature,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=max_tokens,
                response_format=self._response_format(response_schema),
                timeout=self.config.timeout_seconds,
            )
            content = self._extract_content(raw)
            parsed = self._parse_json(content)
            return PrivateMindModelResult(
                ok=bool(parsed),
                parsed=parsed,
                content=content,
                raw=self._safe_raw(raw),
                error="" if parsed else "invalid_json",
            )
        except Exception as exc:
            return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}")

    def _provider_client_or_build(self) -> Any | None:
        if self._provider_client is not None:
            return self._provider_client
        provider = str(self.config.provider or "").strip().lower()
        timeout = int(max(4.0, float(self.config.timeout_seconds or 28.0)))
        if provider == "gemini":
            api_key = self.config.api_key or get_secret("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
            if not api_key:
                return None
            base_url = self.config.base_url or os.getenv("ERIS_REMOTE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
            self._provider_client = GeminiClient(base_url=base_url, api_key=api_key, model_name=self.config.model, timeout=timeout)
            return self._provider_client
        if provider in {"openai", "openai_compatible", "compatible", "remote"}:
            api_key = self.config.api_key or get_secret("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
            if not api_key:
                return None
            base_url = self.config.base_url or os.getenv("ERIS_REMOTE_BASE_URL", "https://api.openai.com/v1")
            self._provider_client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model_name=self.config.model, timeout=timeout)
            return self._provider_client
        if provider == "llama_server":
            self._provider_client = LlamaServerClient(base_url=self.config.llama_server_url, timeout=timeout)
            return self._provider_client
        return None

    def _llama_server_chat_json(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> PrivateMindModelResult:
        payload = {
            "model": self._llama_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            raw = self._llama_request("POST", "/chat/completions", payload)
            content = self._extract_content(raw)
            parsed = self._parse_json(content)
            return PrivateMindModelResult(ok=bool(parsed), parsed=parsed, content=content, raw=raw, error="" if parsed else "invalid_json")
        except Exception as exc:
            return PrivateMindModelResult(ok=False, error=f"{type(exc).__name__}:{exc}")

    def _llama_model(self) -> str:
        if self._llama_model_name:
            return self._llama_model_name
        try:
            raw = self._llama_request("GET", "/models", None)
            data = raw.get("data")
            if isinstance(data, list) and data and isinstance(data[0], Mapping):
                self._llama_model_name = str(data[0].get("id") or self.config.model)
        except Exception:
            self._llama_model_name = self.config.model
        return self._llama_model_name or self.config.model

    def _llama_request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        url = self.config.llama_server_url.rstrip("/") + path
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:  # noqa: S310 - local runtime endpoint by config
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body or "{}")
        return parsed if isinstance(parsed, dict) else {}

    def _extract_content(self, raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, Mapping):
            choices = raw.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, Mapping):
                    msg = first.get("message")
                    if isinstance(msg, Mapping):
                        return str(msg.get("content") or "")
                    return str(first.get("text") or "")
            candidates = raw.get("candidates")
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, Mapping):
                    content = first.get("content")
                    if isinstance(content, Mapping):
                        parts = content.get("parts")
                        if isinstance(parts, list):
                            texts = [
                                str(part.get("text") or "")
                                for part in parts
                                if isinstance(part, Mapping) and str(part.get("text") or "").strip()
                            ]
                            if texts:
                                return "\n".join(texts)
            for key in ("content", "text", "raw_text"):
                if raw.get(key):
                    return str(raw.get(key))
        return compact_text(raw, 8000)

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {}
        for candidate in self._json_candidates(text):
            parsed = self._loads_json_object(candidate)
            if parsed:
                return parsed
        return {}

    def _json_candidates(self, text: str) -> tuple[str, ...]:
        stripped = str(text or "").strip()
        if not stripped:
            return ()
        candidates: list[str] = [stripped]
        unfenced = self._strip_markdown_fences(stripped)
        if unfenced and unfenced not in candidates:
            candidates.append(unfenced)

        balanced = self._extract_first_json_object(unfenced or stripped)
        if balanced and balanced not in candidates:
            candidates.append(balanced)

        repaired = self._extract_repairable_json_object(unfenced or stripped)
        if repaired and repaired not in candidates:
            candidates.append(repaired)
        return tuple(candidates)

    def _strip_markdown_fences(self, text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"```(?:json|JSON)?\s*", "", cleaned)
        cleaned = cleaned.replace("```", "")
        return cleaned.strip()

    def _extract_first_json_object(self, text: str) -> str:
        start = str(text or "").find("{")
        if start < 0:
            return ""
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return ""

    def _extract_repairable_json_object(self, text: str) -> str:
        start = str(text or "").find("{")
        if start < 0:
            return ""
        candidate = text[start:].strip()
        candidate = re.sub(r"\s*```.*$", "", candidate, flags=re.S).strip()
        balance = self._json_object_balance(candidate)
        if balance > 0:
            candidate += "}" * balance
        return candidate

    def _json_object_balance(self, text: str) -> int:
        depth = 0
        in_string = False
        escaped = False
        for ch in str(text or ""):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
        return depth

    def _loads_json_object(self, candidate: str) -> dict[str, Any]:
        raw = str(candidate or "").strip()
        if not raw:
            return {}
        variants = (raw, self._repair_common_json_noise(raw))
        for item in variants:
            try:
                parsed = json.loads(item)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        for item in (raw, self._repair_common_json_noise(raw)):
            try:
                parsed = literal_eval(item)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _repair_common_json_noise(self, text: str) -> str:
        repaired = str(text or "").strip()
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        repaired = re.sub(r"\bNone\b", "null", repaired)
        repaired = re.sub(r"\bTrue\b", "true", repaired)
        repaired = re.sub(r"\bFalse\b", "false", repaired)
        return repaired

    def _safe_raw(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, Mapping):
            return {str(k): to_plain(v) for k, v in raw.items() if str(k) not in {"prompt", "messages"}}
        return {"raw": compact_text(raw, 1200)}

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(msg, *args)
